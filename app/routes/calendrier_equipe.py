"""Point 10 : calendrier d'équipe et seuil de présence.

- RH, Comité de direction, Administrateur : calendrier de n'importe quelle agence ou département (DG).
- Employé qui encadre une équipe (N+1) : calendrier de son équipe directe uniquement.
- Seule la RH fixe le seuil (nombre minimum d'agents présents par jour).
"""
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..outils import _acces_refuse, _entier_ou_none, _exiger_rh, templates
from ..presence import (calendrier_mois, employes_de_unite, equipe_du_n_plus_1, libelle_unite, lire_unite,
                        objet_unite, unite_de, unites_disponibles)

router = APIRouter()

MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
           "septembre", "octobre", "novembre", "décembre"]
JOURS_FR = ["L", "M", "M", "J", "V", "S", "D"]


def _lire_mois(valeur: str | None) -> tuple[int, int]:
    try:
        annee, mois = (int(x) for x in (valeur or "").split("-"))
        if 2000 <= annee <= 2100 and 1 <= mois <= 12:
            return annee, mois
    except ValueError:
        pass
    aujourdhui = date.today()
    return aujourdhui.year, aujourdhui.month


@router.get("/calendrier")
def calendrier_equipe(request: Request, mois: str = "", unite: str = "", db: Session = Depends(get_db)):
    role = request.session.get("role")
    annee, num_mois = _lire_mois(mois)
    contexte = {
        "annee": annee, "mois": num_mois, "libelle_mois": f"{MOIS_FR[num_mois - 1]} {annee}",
        "jours_fr": JOURS_FR, "aujourdhui": date.today(), "est_rh": role in ("Chef RH", "Assistant RH"),
    }

    if role == "Employé":
        # N+1 : uniquement son équipe directe, sans seuil (le seuil concerne l'agence ou le département entier)
        employe_id = request.session.get("employe_id")
        if not employe_id or not request.session.get("est_n_plus_1"):
            _acces_refuse(request)
        employes = equipe_du_n_plus_1(db, employe_id)
        contexte.update({"vue_equipe": True, "titre": "Calendrier de mon équipe", "unite_cle": "",
                         "unites": [], "seuil": None,
                         **calendrier_mois(db, employes, annee, num_mois, None)})
        return templates.TemplateResponse(request, "calendrier_equipe.html", contexte)

    # RH, Comité, Administrateur : choix de l'agence ou du département
    unites = unites_disponibles(db)
    choix = lire_unite(unite)
    if not choix:
        # Par défaut : l'unité de l'utilisateur s'il est rattaché à une fiche employé, sinon la première
        moi = db.get(models.Employe, request.session.get("employe_id")) if request.session.get("employe_id") else None
        choix = unite_de(moi) if moi else (lire_unite(unites[0]["cle"]) if unites else None)
    objet = objet_unite(db, choix) if choix else None
    if not objet:
        contexte.update({"vue_equipe": False, "titre": "Calendrier d'équipe", "unites": unites, "unite_cle": "",
                         "seuil": None, "jours": [], "lignes": [], "totaux": [], "nb_jours_sous_seuil": 0,
                         "mois_precedent": "", "mois_suivant": "", "feries": set()})
        return templates.TemplateResponse(request, "calendrier_equipe.html", contexte)

    seuil = objet.seuil_presence_min
    contexte.update({
        "vue_equipe": False, "titre": "Calendrier d'équipe", "unites": unites,
        "unite_cle": f"{choix[0]}-{choix[1]}", "libelle_unite": libelle_unite(objet, choix[0]), "seuil": seuil,
        **calendrier_mois(db, employes_de_unite(db, choix), annee, num_mois, seuil),
    })
    return templates.TemplateResponse(request, "calendrier_equipe.html", contexte)


@router.post("/calendrier/seuil")
def fixer_seuil(request: Request, db: Session = Depends(get_db),
                unite: str = Form(""), mois: str = Form(""), seuil: str = Form("")):
    """La RH fixe (ou supprime, champ vide) le nombre minimum d'agents présents par jour."""
    _exiger_rh(request)
    choix = lire_unite(unite)
    objet = objet_unite(db, choix) if choix else None
    retour = f"/calendrier?unite={quote(unite)}&mois={quote(mois)}"
    if not objet:
        return RedirectResponse(url=retour, status_code=303)
    valeur = _entier_ou_none(seuil.strip()) if seuil.strip() else None
    if seuil.strip() and (valeur is None or valeur < 1 or valeur > 500):
        return RedirectResponse(url=f"{retour}&erreur={quote('Le seuil doit être un nombre entier entre 1 et 500.')}", status_code=303)
    objet.seuil_presence_min = valeur
    db.commit()
    message = (f"Seuil enregistré : au moins {valeur} agent(s) présent(s) par jour." if valeur
               else "Seuil supprimé : plus aucun contrôle pour cette unité.")
    return RedirectResponse(url=f"{retour}&ok={quote(message)}", status_code=303)
