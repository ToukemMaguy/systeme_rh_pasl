"""Règles métier RH partagées : soldes de congés, statuts des demandes, âge, ancienneté."""
from datetime import date, datetime
from fastapi import HTTPException
from sqlalchemy.orm import Session
from . import models
from .notifications import notifier_n_plus_1_a_reaffecter


# Règle PASL (confirmée par la RH) : 2 jours ouvrables de congé par mois de service, soit 24 jours par an.
# C'est plus favorable que le minimum du Code du travail camerounais (art. 89 : 1,5 jour par mois).
# Le solde est recalculé depuis la date d'embauche : modifier cette valeur change TOUS les soldes.
QUOTA_CONGES_PAR_MOIS = 2
PLAFOND_PERMISSION_JOURS = 3  # Au-delà, les jours supplémentaires sont déduits du congé annuel

# [CORRECTIF B7] Tous les statuts qui signifient « demande pas encore tranchée ».
# « en_attente_rh » (après avis favorable du N+1) était oublié dans les compteurs du tableau de bord.
STATUTS_EN_ATTENTE = ["en_attente", "en_attente_n_plus_1", "en_attente_rh"]
# Statuts définitifs : une demande dans l'un de ces états ne peut plus être validée ni refusée.
STATUTS_TRAITES = ("validee", "refusee", "refusee_n_plus_1")


def _mois_travailles(date_embauche, jusqua) -> int:
    """Nombre de mois complets travaillés entre la date d'embauche et une date donnée."""
    if not date_embauche or not jusqua or jusqua < date_embauche:
        return 0
    mois = (jusqua.year - date_embauche.year) * 12 + (jusqua.month - date_embauche.month)
    if jusqua.day >= date_embauche.day:
        mois += 1
    return max(mois, 0)


def _solde_alloue_cumule(date_embauche, jusqua=None) -> float:
    """Jours de congé cumulés depuis l'embauche, à raison de QUOTA_CONGES_PAR_MOIS jours par mois travaillé."""
    jusqua = jusqua or date.today()
    return round(_mois_travailles(date_embauche, jusqua) * QUOTA_CONGES_PAR_MOIS, 1)


def _solde_conges(db: Session, employe, jusqua: date | None = None, annee_max: int | None = None) -> dict:
    """[CORRECTIF B3 + B6] SEULE source de vérité pour le solde de congés d'un employé.

    Avant ce correctif, le solde était calculé de trois façons différentes (années × 18 dans les PDF,
    18 j/an dans /traiter-rh, mois × 2 ailleurs) : un même employé n'avait pas le même solde
    selon l'écran. Toutes les pages et tous les PDF passent désormais par cette fonction.

    - alloué  = mois travaillés depuis l'embauche × QUOTA_CONGES_PAR_MOIS
    - pris    = jours de congé enregistrés (table solde_conges)
              + jours « déduits du congé annuel » des absences/permissions (B6 : ils étaient
                affichés mais jamais retirés du solde)
    - annee_max : si fourni, ne compte que les années <= annee_max (filtre de la page Congés).
    """
    jusqua = jusqua or date.today()
    alloue = _solde_alloue_cumule(employe.date_embauche if employe else None, jusqua)

    lignes = db.query(models.SoldeConge).filter_by(employe_id=employe.id).all()
    if annee_max:
        lignes = [l for l in lignes if l.annee <= annee_max]
    jours_conges = sum(float(l.jours_pris or 0) for l in lignes)

    absences_deduites = (
        db.query(models.Absence)
        .filter(models.Absence.employe_id == employe.id,
                models.Absence.jours_deduits_conges.isnot(None))
        .all()
    )
    if annee_max:
        absences_deduites = [a for a in absences_deduites if a.date_debut.year <= annee_max]
    jours_deduits = sum(float(a.jours_deduits_conges or 0) for a in absences_deduites)

    total_pris = round(jours_conges + jours_deduits, 1)
    return {
        "total_alloue": alloue,
        "jours_conges": round(jours_conges, 1),
        "jours_deduits": round(jours_deduits, 1),
        "total_pris": total_pris,
        "total_restant": round(alloue - total_pris, 1),
        "annees_comptees": max(_mois_travailles(employe.date_embauche, jusqua) // 12, 1),
    }


def _enregistrer_jours_conge(db: Session, employe_id: int, annee: int, nb_jours: int):
    """Ajoute nb_jours aux jours pris de l'année (crée la ligne si besoin, avec le quota annuel légal)."""
    reference_annuelle = round(QUOTA_CONGES_PAR_MOIS * 12, 1)
    solde = db.query(models.SoldeConge).filter_by(employe_id=employe_id, annee=annee).first()
    if not solde:
        solde = models.SoldeConge(employe_id=employe_id, annee=annee, jours_alloues=reference_annuelle,
                                  jours_pris=0, jours_restants=reference_annuelle)
        db.add(solde)
        db.flush()
    solde.jours_pris = float(solde.jours_pris or 0) + nb_jours
    solde.jours_restants = max(float(solde.jours_alloues or reference_annuelle) - float(solde.jours_pris), 0)


def _employe_ou_404(db: Session, employe_id: int) -> models.Employe:
    employe = db.query(models.Employe).get(employe_id)
    if not employe:
        raise HTTPException(status_code=404, detail="Employé introuvable")
    return employe


def _valeurs_depuis_employe(employe: models.Employe) -> dict:
    return {
        "nom": employe.nom,
        "prenom": employe.prenom,
        "genre": employe.genre,
        "date_embauche": employe.date_embauche.isoformat() if employe.date_embauche else "",
        "date_naissance": employe.date_naissance.isoformat() if employe.date_naissance else "",
        "matricule": employe.matricule or "",
        "departement_id": employe.departement_id,
        "agence_id": employe.agence_id,
        "poste_id": employe.poste_id,
        "grade_id": employe.grade_id,
        "photo_path": employe.photo_path,
        "cni_path": employe.cni_path,
        "plan_localisation_path": employe.plan_localisation_path,
        "statut_matrimonial": employe.statut_matrimonial or "",
        "nombre_enfants": employe.nombre_enfants,
        "contact_urgence_nom": employe.contact_urgence_nom or "",
        "contact_urgence_tel": employe.contact_urgence_tel or "",
        # [CORRECTIF B21] ces 4 champs manquaient : le formulaire de modification les affichait vides
        # et les EFFAÇAIT à l'enregistrement.
        "telephone_pro": employe.telephone_pro or "",
        "telephone_perso": employe.telephone_perso or "",
        "email_pro": employe.email_pro or "",
        "email_perso": employe.email_perso or "",
        "n_plus_1_id": employe.n_plus_1_id,
        # Fiche signalétique
        "lieu_naissance": employe.lieu_naissance or "",
        "nationalite": employe.nationalite or "",
        "numero_cni": employe.numero_cni or "",
        "cni_delivree_le": employe.cni_delivree_le.isoformat() if employe.cni_delivree_le else "",
        "adresse": employe.adresse or "",
        "numero_cnps": employe.numero_cnps or "",
        "niveau_etudes": employe.niveau_etudes or "",
    }


def contexte_fiche_pdf(db: Session, employe: models.Employe, edite_par: str | None) -> dict:
    """Données de la fiche signalétique PDF (utilisée par la RH et par l'employé dans son espace)."""
    return {
        "historique": _historique_employe(db, employe.id),
        "sanctions": db.query(models.Sanction).filter_by(employe_id=employe.id)
                       .order_by(models.Sanction.date_sanction.desc()).all(),
        "solde": _solde_conges(db, employe),
        "absences": db.query(models.Absence).filter_by(employe_id=employe.id)
                      .order_by(models.Absence.date_debut.desc()).limit(8).all(),
        "n_plus_1": employe.n_plus_1,
        "anciennete": _anciennete(employe.date_embauche),
        "age": _age_annees(employe.date_naissance),
        "date_retraite": date_retraite(employe.date_naissance),
        "pieces": [("Photo d'identité", bool(employe.photo_path)),
                   ("Carte nationale d'identité", bool(employe.cni_path)),
                   ("Plan de localisation", bool(employe.plan_localisation_path))],
        "edite_par": edite_par,
    }


# Âge légal de départ à la retraite appliqué à la PASL (confirmé par la RH)
AGE_RETRAITE = 60


def date_retraite(date_naissance) -> date | None:
    """Date des 60 ans (un 29 février devient le 28 février les années non bissextiles)."""
    if not date_naissance:
        return None
    try:
        return date_naissance.replace(year=date_naissance.year + AGE_RETRAITE)
    except ValueError:
        return date(date_naissance.year + AGE_RETRAITE, 2, 28)


def _age_annees(date_naissance) -> int | None:
    if not date_naissance:
        return None
    aujourdhui = date.today()
    age = aujourdhui.year - date_naissance.year
    if (aujourdhui.month, aujourdhui.day) < (date_naissance.month, date_naissance.day):
        age -= 1
    return age


def _tranche_age(date_naissance) -> str | None:
    age = _age_annees(date_naissance)
    if age is None:
        return None
    if age <= 25:
        return "≤25"  # [CORRECTIF B18] même libellé que le tableau de bord (avant : « 18-25 »)
    if age <= 35:
        return "26-35"
    if age <= 45:
        return "36-45"
    if age <= 55:
        return "46-55"
    return "56+"


def _anciennete(date_embauche) -> str:
    if not date_embauche:
        return "—"
    aujourdhui = date.today()
    mois = (aujourdhui.year - date_embauche.year) * 12 + aujourdhui.month - date_embauche.month
    if aujourdhui.day < date_embauche.day:
        mois -= 1
    annees, mois_restants = divmod(max(mois, 0), 12)
    if annees and mois_restants:
        return f"{annees} an(s) et {mois_restants} mois"
    if annees:
        return f"{annees} an(s)"
    return f"{mois_restants} mois"


def _historique_employe(db: Session, employe_id: int):
    return (
        db.query(models.Affectation)
        .filter_by(employe_id=employe_id)
        .order_by(models.Affectation.date_debut.desc())
        .all()
    )


# ============================================================
# SORTIE DES EFFECTIFS ET DÉSACTIVATION DES ACCÈS (lot 1, point 4)
# ------------------------------------------------------------
# Règle PASL : un employé reste « actif » tant qu'il fait partie du personnel, même absent
# (congé, maladie, mission). Il ne devient « inactif » qu'à la date effective de son départ
# (démission, licenciement, retraite...). À cette date, ses comptes sont désactivés.
# ============================================================

def desactiver_comptes_employe(db: Session, employe_id: int, motif: str) -> int:
    """Désactive tous les comptes rattachés à un employé. Retourne le nombre de comptes désactivés."""
    comptes = db.query(models.Utilisateur).filter_by(employe_id=employe_id, compte_actif=True).all()
    for compte in comptes:
        compte.compte_actif = False
        compte.desactive_le = datetime.now()
        compte.motif_desactivation = motif[:255]
    return len(comptes)


def sortir_des_effectifs(db: Session, employe, depart) -> None:
    """Applique un départ arrivé à échéance : employé inactif, affectation clôturée, accès coupés."""
    employe.statut = "inactif"
    affectation_ouverte = db.query(models.Affectation).filter_by(employe_id=employe.id, date_fin=None).first()
    if affectation_ouverte:
        affectation_ouverte.date_fin = depart.date_depart
    libelle = depart.type_depart or "départ"
    desactiver_comptes_employe(db, employe.id, f"Sortie des effectifs ({libelle}) le {depart.date_depart.strftime('%d/%m/%Y')}")

    # [ÉTAPE 3] Les demandes encore en attente de l'employé n'ont plus d'objet : elles sont annulées.
    for demande in db.query(models.DemandeRh).filter(
        models.DemandeRh.employe_concerne_id == employe.id,
        models.DemandeRh.statut.in_(STATUTS_EN_ATTENTE),
    ):
        demande.statut = "annulee"
        note = f"[Système] Demande annulée : sortie des effectifs le {depart.date_depart.strftime('%d/%m/%Y')}."
        demande.commentaire = f"{demande.commentaire}\n\n{note}" if demande.commentaire else note

    # [ÉTAPE 3] S'il était N+1 d'autres employés, la RH doit leur réaffecter un responsable.
    subordonnes = db.query(models.Employe).filter_by(n_plus_1_id=employe.id, statut="actif").all()
    if subordonnes:
        notifier_n_plus_1_a_reaffecter(db, employe, subordonnes)


def appliquer_departs_echus(db: Session, aujourdhui: date | None = None) -> int:
    """Applique les départs validés dont la date est arrivée (départs programmés à l'avance).
    Retourne le nombre d'employés sortis des effectifs."""
    aujourdhui = aujourdhui or date.today()
    echus = (
        db.query(models.Depart, models.Employe)
        .join(models.Employe, models.Depart.employe_id == models.Employe.id)
        .filter(models.Depart.date_depart <= aujourdhui, models.Employe.statut == "actif")
        .all()
    )
    for depart, employe in echus:
        sortir_des_effectifs(db, employe, depart)
    if echus:
        db.commit()
    return len(echus)

