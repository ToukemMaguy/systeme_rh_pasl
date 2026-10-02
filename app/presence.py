"""Point 10 : calendrier d'équipe et seuil de présence (validé par la RH le 30/09/2026).

Règles :
- Une « unité » est l'agence de l'employé ; s'il n'est rattaché à aucune agence (personnel du siège),
  c'est son département.
- Chaque agence et chaque département peut avoir un seuil : le NOMBRE MINIMUM d'agents présents
  chaque jour ouvrable. Sans seuil, aucun contrôle.
- Est « absent » un jour donné tout employé ayant une absence enregistrée ce jour-là (congé, permission,
  maladie...). Les dimanches et jours fériés ne sont pas contrôlés.
- Le contrôle est un AVERTISSEMENT affiché au N+1 et à la RH avant validation : il ne bloque rien.
"""
import calendar
from datetime import date, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import models
from .calendrier import JOURS_OUVRABLES, jours_feries


# ------------------------------------------------------------------
# Unités (agence ou département)
# ------------------------------------------------------------------
def unite_de(employe: models.Employe) -> tuple[str, int]:
    return ("agence", employe.agence_id) if employe.agence_id else ("departement", employe.departement_id)


def objet_unite(db: Session, unite: tuple[str, int]):
    genre, ident = unite
    return db.get(models.Agence if genre == "agence" else models.Departement, ident)


def libelle_unite(objet, genre: str) -> str:
    if objet is None:
        return "—"
    return objet.nom if genre == "agence" else f"{objet.nom} (Siège)"


def lire_unite(valeur: str | None) -> tuple[str, int] | None:
    """« agence-3 » → ("agence", 3) ; valeur invalide → None."""
    try:
        genre, ident = (valeur or "").split("-", 1)
        if genre in ("agence", "departement"):
            return genre, int(ident)
    except ValueError:
        pass
    return None


def employes_de_unite(db: Session, unite: tuple[str, int]) -> list[models.Employe]:
    """Employés actifs de l'unité (pour un département : ceux qui ne sont rattachés à aucune agence)."""
    genre, ident = unite
    requete = db.query(models.Employe).filter(models.Employe.statut == "actif")
    if genre == "agence":
        requete = requete.filter(models.Employe.agence_id == ident)
    else:
        requete = requete.filter(models.Employe.departement_id == ident, models.Employe.agence_id.is_(None))
    return requete.order_by(models.Employe.nom, models.Employe.prenom).all()


# ------------------------------------------------------------------
# Absences et jours travaillés
# ------------------------------------------------------------------
def absences_par_employe(db: Session, ids: list[int], debut: date, fin: date) -> dict[int, list[models.Absence]]:
    resultat: dict[int, list[models.Absence]] = {i: [] for i in ids}
    if not ids:
        return resultat
    absences = (
        db.query(models.Absence)
        .filter(models.Absence.employe_id.in_(ids),
                models.Absence.date_debut <= fin, models.Absence.date_fin >= debut)
        .all()
    )
    for a in absences:
        resultat[a.employe_id].append(a)
    return resultat


def departs_programmes(db: Session, ids: list[int]) -> dict[int, date]:
    """Date de sortie des effectifs déjà enregistrée pour des employés encore actifs."""
    if not ids:
        return {}
    resultat: dict[int, date] = {}
    for d in db.query(models.Depart).filter(models.Depart.employe_id.in_(ids)).all():
        if d.employe_id not in resultat or d.date_depart < resultat[d.employe_id]:
            resultat[d.employe_id] = d.date_depart
    return resultat


def est_jour_travaille(jour: date, feries: set[date]) -> bool:
    return jour.weekday() in JOURS_OUVRABLES and jour not in feries


def _dans_effectif(employe, jour: date, departs: dict[int, date]) -> bool:
    if employe.date_embauche and employe.date_embauche > jour:
        return False
    depart = departs.get(employe.id)
    return not (depart and depart <= jour)


def _absent(absences: list, jour: date):
    for a in absences:
        if a.date_debut <= jour <= a.date_fin:
            return a
    return None


# ------------------------------------------------------------------
# Contrôle du seuil avant validation d'une demande
# ------------------------------------------------------------------
def alertes_seuil(db: Session, employe: models.Employe | None, debut: date | None, fin: date | None) -> dict | None:
    """Jours de la période où, si l'employé s'absente, l'unité passe sous son seuil.
    Retourne None s'il n'y a rien à signaler (pas de seuil, pas de période, ou seuil respecté)."""
    if not employe or not debut or not fin or fin < debut or (fin - debut).days > 366:
        return None
    unite = unite_de(employe)
    objet = objet_unite(db, unite)
    seuil = getattr(objet, "seuil_presence_min", None)
    if not seuil:
        return None
    equipe = employes_de_unite(db, unite)
    ids = [e.id for e in equipe]
    absences = absences_par_employe(db, ids, debut, fin)
    departs = departs_programmes(db, ids)
    feries = jours_feries(debut.year) | jours_feries(fin.year)
    jours = []
    jour = debut
    while jour <= fin:
        if est_jour_travaille(jour, feries):
            effectif = [e for e in equipe if _dans_effectif(e, jour, departs)]
            presents = sum(1 for e in effectif if e.id != employe.id and not _absent(absences[e.id], jour))
            if presents < seuil:
                jours.append({"jour": jour, "presents": presents, "effectif": len(effectif)})
        jour += timedelta(days=1)
    if not jours:
        return None
    return {"unite": libelle_unite(objet, unite[0]), "cle": f"{unite[0]}-{unite[1]}", "seuil": seuil, "jours": jours}


# ------------------------------------------------------------------
# Calendrier mensuel
# ------------------------------------------------------------------
def calendrier_mois(db: Session, employes: list[models.Employe], annee: int, mois: int, seuil: int | None) -> dict:
    premier = date(annee, mois, 1)
    dernier = date(annee, mois, calendar.monthrange(annee, mois)[1])
    feries = jours_feries(annee)
    jours = [premier + timedelta(days=i) for i in range((dernier - premier).days + 1)]
    ids = [e.id for e in employes]
    absences = absences_par_employe(db, ids, premier, dernier)
    departs = departs_programmes(db, ids)

    lignes = []
    for e in employes:
        cases = []
        for j in jours:
            if not _dans_effectif(e, j, departs):
                cases.append({"etat": "hors"})
            elif not est_jour_travaille(j, feries):
                cases.append({"etat": "ferme"})
            else:
                a = _absent(absences[e.id], j)
                if a:
                    # Couleur : congé annuel (code CA), permission, ou autre absence
                    t = a.type_absence
                    categorie = "Congé" if (t and t.code == "CA") else ("Permission" if (t and t.categorie == "Permission") else "Absence")
                    cases.append({"etat": "absent", "categorie": categorie,
                                  "libelle": a.type_absence.libelle if a.type_absence else "Absence",
                                  "absence_id": a.id})
                else:
                    cases.append({"etat": "present"})
        lignes.append({"employe": e, "cases": cases})

    totaux = []
    for i, j in enumerate(jours):
        if not est_jour_travaille(j, feries):
            totaux.append(None)
            continue
        effectif = sum(1 for l in lignes if l["cases"][i]["etat"] != "hors")
        presents = sum(1 for l in lignes if l["cases"][i]["etat"] == "present")
        totaux.append({"presents": presents, "effectif": effectif, "sous_seuil": bool(seuil and presents < seuil)})

    return {
        "jours": jours, "lignes": lignes, "totaux": totaux, "feries": feries,
        "nb_jours_sous_seuil": sum(1 for t in totaux if t and t["sous_seuil"]),
        "mois_precedent": (premier - timedelta(days=1)).strftime("%Y-%m"),
        "mois_suivant": (dernier + timedelta(days=1)).strftime("%Y-%m"),
    }


def unites_disponibles(db: Session) -> list[dict]:
    """Liste pour le sélecteur : agences, puis directions du siège."""
    unites = [{"cle": f"agence-{a.id}", "libelle": a.nom, "groupe": "Agences", "seuil": a.seuil_presence_min}
              for a in db.query(models.Agence).order_by(models.Agence.nom).all()]
    unites += [{"cle": f"departement-{d.id}", "libelle": d.nom, "groupe": "Siège (par direction)",
                "seuil": d.seuil_presence_min}
               for d in db.query(models.Departement).order_by(models.Departement.nom).all()]
    return unites


def equipe_du_n_plus_1(db: Session, employe_id: int) -> list[models.Employe]:
    """Le N+1 et ses collaborateurs directs actifs."""
    return (
        db.query(models.Employe)
        .filter(models.Employe.statut == "actif",
                or_(models.Employe.n_plus_1_id == employe_id, models.Employe.id == employe_id))
        .order_by(models.Employe.nom, models.Employe.prenom)
        .all()
    )
