"""Moteur d'import du fichier RH : utilisé par le script (rechargement initial) et, ensuite, par la page
« Mettre à jour depuis le fichier RH ».

Règles validées avec la RH (30/09/2026) :
- Le fichier fait foi pour ce qu'il contient : nom, genre, fonction, lieu (siège / agence), date d'embauche,
  téléphones, email. Ce qui n'existe que dans l'application (CNI, CNPS, photos, comptes, demandes, N+1 déjà
  saisi...) n'est JAMAIS modifié.
- Le siège n'est pas une agence ; la section « YAOUNDE » = personnel du siège ; la direction de chaque
  employé est déduite de sa fonction (organigramme 2024).
- Les « mis à disposition » (MAD) ne sont pas des employés : ils vont dans un registre séparé.
- Un employé actif absent du fichier n'est jamais supprimé ni sorti des effectifs : il est seulement signalé.
- Soldes de congés : le solde calculé par la RH (Provision congés, colonne « Total ») devient le solde
  d'ouverture de l'application à la « Fin Période » ; les salaires du fichier ne sont jamais lus.
- Simulation : tout est calculé puis ANNULÉ (rollback) ; rien n'est enregistré tant qu'on n'applique pas.
"""
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from .. import models
from ..journal import journaliser_evenement
from ..regles_rh import _solde_alloue_cumule
from .lecture import ContenuFichier
from .referentiel import (AGENCES, CODES_IGNORES, DIRECTIONS, MAD, POSTES_CHEF_AGENCE, SIEGE, cle, direction_depuis_code,
                          fonction_officielle, lieu_officiel)

POSTE_HISTORIQUE = "Autre (historique)"
FEUILLE_EFFECTIF = "Effectif_mois août 2026"
FEUILLE_PROVISION = "Provision_congés_24j_"
GRADE_DEFAUT = "Employé"


@dataclass
class Rapport:
    simulation: bool = True
    crees: list = field(default_factory=list)            # (nom, détail)
    modifies: list = field(default_factory=list)         # (nom, [« champ : avant → après »])
    inchanges: int = 0
    mad_crees: list = field(default_factory=list)
    mad_modifies: list = field(default_factory=list)
    n_plus_1: list = field(default_factory=list)         # (employé, chef d'agence)
    soldes: int = 0
    conges_historique: int = 0
    mouvements: int = 0
    anciens_employes: int = 0
    absents_du_fichier: list = field(default_factory=list)
    a_verifier: list = field(default_factory=list)       # messages pour la RH
    inconnus: list = field(default_factory=list)         # écritures non reconnues (à ajouter au référentiel)
    infos: list = field(default_factory=list)            # différences sans conséquence, pour information
    anomalies: list = field(default_factory=list)        # même contenu, avec feuille + cellule exactes (rapport Excel)

    def signaler(self, feuille, cellule, nom, probleme, action, info=False):
        """Point à corriger dans le fichier de la RH, avec son emplacement exact (Ctrl+G dans Excel)."""
        self.anomalies.append({"feuille": feuille, "cellule": cellule, "nom": nom, "probleme": probleme,
                               "action": action, "gravite": "Information" if info else "À corriger"})
        texte = f"[{feuille} ! {cellule}] {nom} : {probleme}"
        (self.infos if info else self.a_verifier).append(texte)

    def resume(self) -> str:
        mode = "SIMULATION (rien n'a été enregistré)" if self.simulation else "IMPORT APPLIQUÉ"
        lignes = [
            f"=== {mode} ===",
            f"Employés créés : {len(self.crees)} | modifiés : {len(self.modifies)} | inchangés : {self.inchanges}",
            f"Mis à disposition : {len(self.mad_crees)} ajouté(s), {len(self.mad_modifies)} modifié(s)",
            f"N+1 pré-remplis (chef d'agence) : {len(self.n_plus_1)}",
            f"Soldes de congés d'ouverture : {self.soldes} | congés passés ajoutés à l'historique : {self.conges_historique}",
            f"Mouvements internes ajoutés à l'historique : {self.mouvements} | anciens employés (départs) : {self.anciens_employes}",
            f"Employés actifs de l'application absents du fichier : {len(self.absents_du_fichier)}",
            f"Points à vérifier : {len(self.a_verifier)} | écritures inconnues : {len(self.inconnus)}",
        ]
        return "\n".join(lignes)


# ------------------------------------------------------------------
# Outils
# ------------------------------------------------------------------
def _separer_nom(nom_complet: str) -> tuple[str, str]:
    """Convention du fichier RH : le premier mot est le nom de famille, la suite les prénoms."""
    parties = nom_complet.split(" ", 1)
    return parties[0], (parties[1] if len(parties) > 1 else "")


def _similarite(a: str, b: str) -> float:
    return SequenceMatcher(None, cle(a), cle(b)).ratio()


class _Cache:
    """Référentiels chargés une fois (directions, agences, postes) ; créés s'ils manquent."""

    def __init__(self, db: Session):
        self.db = db
        self.directions = {}
        for code, nom in DIRECTIONS.items():
            d = (db.query(models.Departement).filter_by(code=code).first()
                 or db.query(models.Departement).filter_by(nom=nom).first())
            if not d:
                d = models.Departement(code=code, nom=nom)
                db.add(d)
            d.code, d.nom = code, nom
            self.directions[code] = d
        self.agences = {}
        for nom, ville in AGENCES.items():
            a = db.query(models.Agence).filter_by(nom=nom).first()
            if not a:
                a = models.Agence(nom=nom, ville=ville)
                db.add(a)
            a.ville = a.ville or ville
            self.agences[nom] = a
        grade = db.query(models.Grade).filter_by(libelle=GRADE_DEFAUT).first()
        if not grade:
            grade = models.Grade(libelle=GRADE_DEFAUT, niveau_hierarchique=1)
            db.add(grade)
        self.grade_defaut = grade
        # Clé sans accents ni casse : MySQL (interclassement *_ci) considère « Directeur des engagements »
        # et « Directeur des Engagements » comme le même intitulé et refuserait le doublon.
        self.postes = {}
        for p in db.query(models.Poste).order_by(models.Poste.id):
            self.postes.setdefault(cle(p.intitule), p)
        db.flush()

    def poste(self, intitule: str) -> models.Poste:
        intitule = " ".join(intitule.split())
        k = cle(intitule)
        if k not in self.postes:
            p = models.Poste(intitule=intitule)
            self.db.add(p)
            self.db.flush()
            self.postes[k] = p
        return self.postes[k]

    def agence(self, lieu):
        """lieu_officiel() -> objet Agence, ou None pour le siège."""
        return self.agences.get(lieu) if lieu not in (None, SIEGE, MAD, False) else None


def _trouver_matricule(ligne, provision_par_nom, provision, entrees, deja_pris):
    """Matricule : feuille Provision congés (nom identique, sinon même date d'embauche et nom proche),
    puis feuille Entrées. Retourne (matricule, ligne Provision correspondante ou None).
    deja_pris : matricules déjà attribués à une autre ligne de ce même fichier (jamais réutilisés)."""
    c = cle(ligne.nom_complet)
    p = provision_par_nom.get(c)
    if p and p.matricule in deja_pris:
        p = None
    if not p:
        candidats = [x for x in provision if x.date_embauche == ligne.date_embauche and x.matricule not in deja_pris]
        meilleurs = sorted(candidats, key=lambda x: _similarite(x.nom_complet, ligne.nom_complet), reverse=True)
        if meilleurs and _similarite(meilleurs[0].nom_complet, ligne.nom_complet) >= 0.75:
            p = meilleurs[0]
    if p:
        return p.matricule, p
    mats = [m for m in set(entrees.get(c, [])) if m not in deja_pris]
    return (mats[0] if len(mats) == 1 else None), None


def _trouver_employe(db, matricule, ligne, actifs):
    if matricule:
        e = db.query(models.Employe).filter_by(matricule=matricule).first()
        if e:
            return e
    c = cle(ligne.nom_complet)
    for e in actifs:
        if cle(f"{e.nom} {e.prenom}") == c and e.date_embauche == ligne.date_embauche:
            return e
    for e in actifs:                       # nom corrigé dans le fichier : même date d'embauche et nom très proche
        if e.date_embauche == ligne.date_embauche and _similarite(f"{e.nom} {e.prenom}", ligne.nom_complet) >= 0.85:
            return e
    return None


# ------------------------------------------------------------------
# Réinitialisation (avant la mise en production uniquement)
# ------------------------------------------------------------------
def repartir_de_zero(db: Session) -> dict:
    """Supprime toutes les données du personnel (employés, absences, demandes, soldes, départs, MAD...)
    ainsi que les comptes « Employé ». Les autres comptes (Admin, RH, Comité) sont gardés mais détachés
    de leur fiche. À n'utiliser qu'AVANT l'ouverture aux utilisateurs."""
    comptes = {}
    # D'abord tout ce qui dépend des employés et des comptes (ordre imposé par les clés étrangères MySQL)
    for modele in (models.Licenciement, models.MailAEnvoyer, models.DemandeRh, models.Sanction, models.Absence,
                   models.SoldeConge, models.Depart, models.Affectation, models.PersonnelMAD):
        db.query(modele).delete(synchronize_session=False)
    comptes["employe_supprimes"] = db.query(models.Utilisateur).filter_by(role="Employé").delete(synchronize_session=False)
    comptes["autres_detaches"] = db.query(models.Utilisateur).filter(models.Utilisateur.employe_id.isnot(None)).update(
        {models.Utilisateur.employe_id: None}, synchronize_session=False)
    db.query(models.Employe).update({models.Employe.n_plus_1_id: None}, synchronize_session=False)
    db.query(models.Employe).delete(synchronize_session=False)
    for modele in (models.Poste, models.Agence, models.Departement):
        db.query(modele).delete(synchronize_session=False)
    journaliser_evenement(db, "suppression", "Réinitialisation des données du personnel avant rechargement du fichier RH")
    return comptes


# ------------------------------------------------------------------
# Import
# ------------------------------------------------------------------
def importer(db: Session, contenu: ContenuFichier, appliquer: bool = False, auteur: str = "Import du fichier RH") -> Rapport:
    rapport = Rapport(simulation=not appliquer)
    for ligne in contenu.genre_manquant:
        rapport.signaler(FEUILLE_EFFECTIF, f"B{ligne} / D{ligne}", f"ligne {ligne}", "genre non indiqué (« H » retenu)",
                         "Mettre F en colonne B (femme) ou H en colonne D (homme).")
    try:
        _importer(db, contenu, rapport)
        if appliquer:
            journaliser_evenement(db, "modification", f"{auteur} : {len(rapport.crees)} créé(s), {len(rapport.modifies)} modifié(s)")
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    return rapport


def _importer(db: Session, contenu: ContenuFichier, rapport: Rapport):
    ref = _Cache(db)
    provision_par_nom = {cle(p.nom_complet): p for p in contenu.provision}
    # Matricules en double dans le fichier : signalés (chaque personne est rapprochée par son nom)
    lignes_par_matricule = {}
    for p in contenu.provision:
        lignes_par_matricule.setdefault(p.matricule, []).append(p)
    for mat, lignes in lignes_par_matricule.items():
        if len(lignes) > 1 and len({cle(x.nom_complet) for x in lignes}) > 1:
            for x in lignes:
                autres = ", ".join(f"{y.nom_complet} (A{y.ligne})" for y in lignes if y is not x)
                rapport.signaler(FEUILLE_PROVISION, f"A{x.ligne}", x.nom_complet, f"matricule {mat} aussi donné à : {autres}",
                                 "Corriger le matricule de la personne concernée en colonne A.")
    actifs = db.query(models.Employe).filter_by(statut="actif").all()
    vus, lignes_employes, matricules_pris = set(), [], set()

    # ---------- 1. Effectif : employés et personnel mis à disposition ----------
    for l in contenu.effectif:
        lieu = lieu_officiel(l.section)
        fonction = fonction_officielle(l.fonction)
        if lieu is False:
            rapport.inconnus.append(f"Section « {l.section} » (ligne {l.ligne}) : lieu non reconnu, employé placé au siège.")
            lieu = SIEGE
        if not fonction:
            rapport.inconnus.append(f"Fonction « {l.fonction} » (ligne {l.ligne}, {l.nom_complet}) non reconnue : poste repris tel quel, direction à compléter.")
        poste = ref.poste(fonction[0] if fonction else (l.fonction or "Non renseigné"))
        direction = ref.directions[fonction[1]] if fonction else ref.directions["DG"]

        if lieu == MAD:
            _importer_mad(db, l, poste, direction, rapport)
            continue

        agence = ref.agence(lieu)
        nom, prenom = _separer_nom(l.nom_complet)
        matricule, ligne_prov = _trouver_matricule(l, provision_par_nom, contenu.provision, contenu.matricules_entrees,
                                                   matricules_pris)
        if ligne_prov and ligne_prov.date_embauche and ligne_prov.date_embauche != l.date_embauche:
            # Fréquent : dans « Provision congés », la colonne Embauche semble porter la date du contrat en cours.
            # Le solde repris reste exact (il est aligné sur le « Total » de la RH à la fin de période).
            rapport.signaler(FEUILLE_EFFECTIF, f"H{l.ligne}", l.nom_complet,
                             f"embauche le {l.date_embauche:%d/%m/%Y} ici, mais le {ligne_prov.date_embauche:%d/%m/%Y} "
                             f"dans {FEUILLE_PROVISION} (cellule E{ligne_prov.ligne})",
                             "Vérifier quelle date est la bonne (celle de l'Effectif est retenue).", info=True)
        if matricule:
            matricules_pris.add(matricule)
        else:
            rapport.signaler(FEUILLE_EFFECTIF, f"F{l.ligne}", l.nom_complet, "matricule introuvable (nom absent de "
                             f"{FEUILLE_PROVISION} colonne C et de Entrées colonne C, ou écrit autrement)",
                             "Ajouter la personne avec son matricule dans Provision congés, ou aligner l'orthographe du nom.")
        employe = _trouver_employe(db, matricule, l, actifs)
        if employe is not None and employe.id in vus:
            rapport.signaler(FEUILLE_EFFECTIF, f"F{l.ligne}", l.nom_complet,
                             f"ressemble à une autre ligne déjà lue ({employe.nom} {employe.prenom}) : doublon ?",
                             "Supprimer la ligne en double si c'est la même personne.")
            employe = None
        valeurs = {"nom": nom, "prenom": prenom, "genre": l.genre, "date_embauche": l.date_embauche,
                   "poste_id": poste.id, "departement_id": direction.id, "agence_id": agence.id if agence else None,
                   "telephone_pro": l.tel_pro, "telephone_perso": l.tel_perso}

        if employe is None:
            employe = models.Employe(matricule=matricule, statut="actif", grade_id=ref.grade_defaut.id,
                                     email_perso=l.email, **valeurs)
            db.add(employe)
            db.flush()
            db.add(models.Affectation(employe_id=employe.id, departement_id=direction.id, agence_id=valeurs["agence_id"],
                                      poste_id=poste.id, grade_id=ref.grade_defaut.id, date_debut=l.date_embauche,
                                      type_mouvement="embauche"))
            rapport.crees.append((l.nom_complet, f"{poste.intitule} — {agence.nom if agence else 'Siège'}"))
            nouveau = True
        else:
            nouveau = False
            changements = []
            etiquettes = {"nom": "Nom", "prenom": "Prénom", "genre": "Genre", "date_embauche": "Date d'embauche",
                          "poste_id": "Poste", "departement_id": "Direction", "agence_id": "Lieu",
                          "telephone_pro": "Tél. pro", "telephone_perso": "Tél. perso"}
            situation_avant = (employe.poste_id, employe.agence_id, employe.departement_id)
            for champ, valeur in valeurs.items():
                if valeur in (None, "") or getattr(employe, champ) == valeur:
                    continue        # une case vide dans le fichier n'efface jamais une donnée
                changements.append(f"{etiquettes[champ]} : {_lisible(db, champ, getattr(employe, champ))} → {_lisible(db, champ, valeur)}")
                setattr(employe, champ, valeur)
            if l.email and not employe.email_perso:
                employe.email_perso = l.email
                changements.append(f"Email perso : — → {l.email}")
            if matricule and not employe.matricule:
                employe.matricule = matricule
                changements.append(f"Matricule : — → {matricule}")
            if situation_avant != (employe.poste_id, employe.agence_id, employe.departement_id):
                _nouvelle_affectation(db, employe, "mise à jour (fichier RH)")
            if changements:
                rapport.modifies.append((l.nom_complet, changements))
            else:
                rapport.inchanges += 1
        vus.add(employe.id)
        lignes_employes.append((employe, l, ligne_prov, nouveau))

    # ---------- 2. N+1 = chef d'agence (seulement s'il n'est pas déjà renseigné) ----------
    db.flush()
    postes_chefs = {ref.postes[cle(p)].id for p in POSTES_CHEF_AGENCE if cle(p) in ref.postes}
    chefs = {}
    for employe, l, _, _ in lignes_employes:
        if employe.agence_id and employe.poste_id in postes_chefs:
            chefs.setdefault(employe.agence_id, []).append(employe)
    for employe, l, _, _ in lignes_employes:
        if not employe.agence_id or employe.n_plus_1_id:
            continue
        candidats = [c for c in chefs.get(employe.agence_id, []) if c.id != employe.id]
        if len(candidats) == 1:
            employe.n_plus_1_id = candidats[0].id
            rapport.n_plus_1.append((l.nom_complet, f"{candidats[0].nom} {candidats[0].prenom}"))
        elif len(candidats) > 1:
            rapport.signaler(FEUILLE_EFFECTIF, f"F{l.ligne}", l.nom_complet, "plusieurs chefs d'agence dans son agence",
                             "Choisir le N+1 sur la fiche de l'employé dans l'application.")

    # ---------- 3. Congés : solde d'ouverture + périodes passées ----------
    type_ca = db.query(models.TypeAbsence).filter_by(code="CA").first()
    if not type_ca:
        type_ca = models.TypeAbsence(code="CA", libelle="Congé annuel", categorie="Absence")
        db.add(type_ca)
        db.flush()
    db.flush()
    for employe, l, p, nouveau in lignes_employes:
        if not p:
            continue
        db.flush()
        a_deja_des_conges = db.query(models.SoldeConge).filter_by(employe_id=employe.id).first() is not None
        if p.total is not None and p.fin_periode and not a_deja_des_conges:
            alloue = _solde_alloue_cumule(employe.date_embauche, p.fin_periode)
            db.add(models.SoldeConge(employe_id=employe.id, annee=p.fin_periode.year, jours_alloues=alloue,
                                     jours_pris=round(alloue - float(p.total), 1), jours_restants=float(p.total)))
            rapport.soldes += 1
            if p.total < 0:
                rapport.signaler(FEUILLE_PROVISION, f"BP{p.ligne}", l.nom_complet, f"solde de congés négatif ({p.total} j)",
                                 "Vérifier le calcul du solde.")
        for debut, fin in p.conges:
            chevauche = db.query(models.Absence).filter(models.Absence.employe_id == employe.id,
                                                        models.Absence.date_debut <= fin, models.Absence.date_fin >= debut).first()
            if not chevauche:
                db.add(models.Absence(employe_id=employe.id, type_absence_id=type_ca.id, date_debut=debut, date_fin=fin,
                                      justifiee=True, motif="Congé repris du fichier RH (historique)",
                                      enregistre_par="Import du fichier RH"))
                rapport.conges_historique += 1

    # ---------- 4. Mouvements internes : historique des affectations des nouveaux employés ----------
    par_nom = {cle(l.nom_complet): e for e, l, _, nouveau in lignes_employes if nouveau}
    mouvements = {}
    for m in contenu.mouvements:
        e = par_nom.get(cle(m.nom_complet))
        if e:
            mouvements.setdefault(e.id, (e, []))[1].append(m)
    for e, liste in mouvements.values():
        liste.sort(key=lambda m: m.date_effet)
        _historique_mouvements(db, ref, e, liste, rapport)

    # ---------- 5. Départs : anciens employés (historique, pour les statistiques) ----------
    noms_actifs = {cle(f"{e.nom} {e.prenom}") for e in db.query(models.Employe).filter_by(statut="actif").all()}
    for d in contenu.departs:
        c = cle(d.nom_complet)
        if c in noms_actifs:
            rapport.signaler("Départs", f"B{d.ligne}", d.nom_complet,
                             "porte le même nom qu'un employé actuel (réembauche ou homonyme ?) : départ non importé",
                             "Rien à faire si c'est une réembauche ; sinon, préciser le nom.", info=True)
            continue
        _ancien_employe(db, ref, d, rapport)

    # ---------- 6. Employés actifs de l'application absents du fichier ----------
    for e in actifs:
        if e.id not in vus:
            rapport.absents_du_fichier.append(f"{e.nom} {e.prenom} ({e.matricule or 'sans matricule'})")
    db.flush()


def _lisible(db, champ, valeur):
    if valeur is None:
        return "—"
    if champ == "poste_id":
        return db.get(models.Poste, valeur).intitule
    if champ == "departement_id":
        return db.get(models.Departement, valeur).nom
    if champ == "agence_id":
        return db.get(models.Agence, valeur).nom
    if isinstance(valeur, date):
        return valeur.strftime("%d/%m/%Y")
    return str(valeur)


def _nouvelle_affectation(db, employe, motif):
    aujourdhui = date.today()
    ouverte = db.query(models.Affectation).filter_by(employe_id=employe.id, date_fin=None).first()
    if ouverte:
        ouverte.date_fin = aujourdhui
    db.add(models.Affectation(employe_id=employe.id, departement_id=employe.departement_id, agence_id=employe.agence_id,
                              poste_id=employe.poste_id, grade_id=employe.grade_id, date_debut=aujourdhui,
                              type_mouvement="mutation", motif=motif))


def _poste_et_lieu(ref, poste_txt, lieu_txt, employe):
    f = fonction_officielle(poste_txt) if poste_txt else None
    poste = ref.poste(f[0]) if f else (employe.poste if not poste_txt else ref.poste(POSTE_HISTORIQUE))
    lieu = lieu_officiel(lieu_txt) if lieu_txt else None
    agence = ref.agence(lieu) if lieu not in (None, False) else None
    return poste, agence, f


def _historique_mouvements(db, ref, employe, liste, rapport):
    """Reconstitue les affectations : embauche -> mouvement 1 -> ... -> situation actuelle (celle de l'effectif)."""
    embauche = db.query(models.Affectation).filter_by(employe_id=employe.id, type_mouvement="embauche").first()
    premier = liste[0]
    if embauche and premier.date_effet > employe.date_embauche:
        poste, agence, _ = _poste_et_lieu(ref, premier.ancien_poste, premier.ancienne_agence, employe)
        embauche.poste_id, embauche.agence_id, embauche.date_fin = poste.id, (agence.id if agence else None), premier.date_effet
    for i, m in enumerate(liste):
        fin = liste[i + 1].date_effet if i + 1 < len(liste) else None
        poste, agence, f = _poste_et_lieu(ref, m.nouveau_poste, m.nouvelle_agence, employe)
        if fin is None:     # dernier mouvement : la situation actuelle reste celle de la feuille Effectif
            poste, agence = employe.poste, employe.agence
        nature = (m.nature or "mutation").strip().lower()
        db.add(models.Affectation(employe_id=employe.id, departement_id=employe.departement_id,
                                  agence_id=agence.id if agence else None, poste_id=poste.id, grade_id=employe.grade_id,
                                  date_debut=m.date_effet, date_fin=fin, type_mouvement=nature[:50],
                                  motif=f"Fichier RH : {m.ancien_poste or '—'} ({m.ancienne_agence or '—'}) → "
                                        f"{m.nouveau_poste or '—'} ({m.nouvelle_agence or '—'})"))
        rapport.mouvements += 1


def _ancien_employe(db, ref, d, rapport):
    nom, prenom = _separer_nom(d.nom_complet)
    existe = (db.query(models.Employe).join(models.Depart, models.Depart.employe_id == models.Employe.id)
              .filter(models.Employe.nom == nom, models.Employe.prenom == prenom, models.Depart.date_depart == d.date_depart)
              .first())
    if existe:
        return
    f = fonction_officielle(d.fonction)
    code = direction_depuis_code(d.departement) or (f[1] if f else None)
    lieu = lieu_officiel(d.localisation)
    if d.departement and not direction_depuis_code(d.departement) and cle(d.departement) not in CODES_IGNORES:
        rapport.inconnus.append(f"Départs ligne {d.ligne} : direction « {d.departement} » non reconnue.")
    if lieu is False:
        rapport.inconnus.append(f"Départs ligne {d.ligne} : lieu « {d.localisation} » non reconnu.")
    poste = ref.poste(f[0] if f else POSTE_HISTORIQUE)
    direction = ref.directions[code or "DG"]
    agence = ref.agence(lieu)
    embauche = d.date_embauche or d.date_depart
    e = models.Employe(nom=nom, prenom=prenom, genre=None, date_embauche=embauche, statut="inactif",
                       departement_id=direction.id, agence_id=agence.id if agence else None,
                       poste_id=poste.id, grade_id=ref.grade_defaut.id)
    db.add(e)
    db.flush()
    motif = (d.motif or "").strip()
    db.add(models.Affectation(employe_id=e.id, departement_id=direction.id, agence_id=e.agence_id, poste_id=poste.id,
                              grade_id=ref.grade_defaut.id, date_debut=embauche, date_fin=d.date_depart,
                              type_mouvement="embauche",
                              motif=None if f else f"Fonction dans le fichier : {d.fonction or '—'}"))
    db.add(models.Depart(employe_id=e.id, date_depart=d.date_depart, motif=motif or None,
                         type_depart=motif.capitalize()[:50] if motif else None))
    rapport.anciens_employes += 1


def _importer_mad(db, l, poste, direction, rapport):
    existant = next((m for m in db.query(models.PersonnelMAD).all() if cle(m.nom_complet) == cle(l.nom_complet)), None)
    valeurs = {"fonction": poste.intitule, "departement_id": direction.id, "telephone": l.tel_pro or l.tel_perso,
               "email": l.email, "date_debut": l.date_embauche}
    if not existant:
        db.add(models.PersonnelMAD(nom_complet=l.nom_complet, actif=True, **valeurs))
        rapport.mad_crees.append(l.nom_complet)
        return
    changes = [k for k, v in valeurs.items() if v not in (None, "") and getattr(existant, k) != v]
    for k in changes:
        setattr(existant, k, valeurs[k])
    if changes:
        rapport.mad_modifies.append(l.nom_complet)
