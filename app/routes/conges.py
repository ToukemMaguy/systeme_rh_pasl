"""Congés et soldes."""
import csv
import io
from datetime import date
from urllib.parse import quote
from fastapi import APIRouter, Request, Depends, UploadFile, File
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..outils import _date_ou_none, _entier_ou_none, _exiger_lecture, _exiger_rh, templates
from ..regles_rh import QUOTA_CONGES_PAR_MOIS, _anciennete, _solde_conges, _tranche_age

router = APIRouter()


# ============================================================
# CONGÉS
# ============================================================

@router.get("/conges")
def liste_conges(
    request: Request,
    db: Session = Depends(get_db),
    annee: str = "",
    departement_id: str = "",
    agence_id: str = "",
    q: str = "",
    sexe: str = "",
    tranche_age: str = "",
    embauche_debut: str = "",
    embauche_fin: str = "",
):
    _exiger_lecture(request)

    dept_filtre = _entier_ou_none(departement_id)
    agence_filtre = _entier_ou_none(agence_id)
    annee_filtre = _entier_ou_none(annee)
    embauche_debut_filtre = _date_ou_none(embauche_debut)
    embauche_fin_filtre = _date_ou_none(embauche_fin)

    aujourdhui = date.today()
    jusqua = date(annee_filtre, 12, 31) if annee_filtre and annee_filtre < aujourdhui.year else aujourdhui

    # Base : tous les employés actifs
    requete_employes = db.query(models.Employe).filter_by(statut="actif")

    # Filtres
    if dept_filtre:
        requete_employes = requete_employes.filter(models.Employe.departement_id == dept_filtre)
    if agence_filtre:
        requete_employes = requete_employes.filter(models.Employe.agence_id == agence_filtre)

    # Filtre recherche nom/prénom/matricule
    if q:
        recherche = f"%{q}%"
        requete_employes = requete_employes.filter(
            models.Employe.nom.ilike(recherche)
            | models.Employe.prenom.ilike(recherche)
            | models.Employe.matricule.ilike(recherche)
        )

    # Filtre sexe
    if sexe:
        requete_employes = requete_employes.filter(models.Employe.genre == sexe)

    # Filtre date d'embauche
    if embauche_debut_filtre:
        requete_employes = requete_employes.filter(models.Employe.date_embauche >= embauche_debut_filtre)
    if embauche_fin_filtre:
        requete_employes = requete_employes.filter(models.Employe.date_embauche <= embauche_fin_filtre)

    employes = requete_employes.order_by(models.Employe.nom, models.Employe.prenom).all()

    # Filtre tranche d'âge (côté Python)
    if tranche_age:
        employes = [e for e in employes if _tranche_age(e.date_naissance) == tranche_age]

    # Calcul des soldes cumulés
    soldes_cumules = []
    for e in employes:
        # [CORRECTIF B3 + B6] Solde calculé par la fonction commune
        solde = _solde_conges(db, e, jusqua, annee_max=annee_filtre)
        alloue_cumule = solde["total_alloue"]
        pris_cumule = solde["total_pris"]
        restant_cumule = solde["total_restant"]

        soldes_cumules.append({
            "employe": e,
            "anciennete": _anciennete(e.date_embauche),
            "alloue_cumule": alloue_cumule,
            "pris_cumule": pris_cumule,
            "restant_cumule": restant_cumule,
        })

    annee_min = min((e.date_embauche.year for e in employes if e.date_embauche), default=aujourdhui.year)
    annees_disponibles = list(range(aujourdhui.year, annee_min - 1, -1))

    return templates.TemplateResponse(request, "conges.html", {
        "soldes_cumules": soldes_cumules,
        "quota_par_mois": QUOTA_CONGES_PAR_MOIS,
        "annees_disponibles": annees_disponibles,
        "annee_selectionnee": annee_filtre or "",
        "departements": db.query(models.Departement).order_by(models.Departement.nom).all(),
        "agences": db.query(models.Agence).order_by(models.Agence.nom).all(),
        "departement_id": departement_id,
        "agence_id": agence_id,
        "q": q,
        "sexe": sexe,
        "tranche_age": tranche_age,
        "embauche_debut": embauche_debut,
        "embauche_fin": embauche_fin,
    })

@router.post("/conges/importer")
async def importer_soldes(
    request: Request,
    db: Session = Depends(get_db),
    fichier: UploadFile = File(...),
):
    _exiger_rh(request)
    try:
        contenu = (await fichier.read()).decode("utf-8-sig")
        lecteur = csv.DictReader(io.StringIO(contenu))
        nb_importes = 0
        for ligne in lecteur:
            matricule = (ligne.get("matricule") or "").strip()
            if not matricule:
                continue
            employe = db.query(models.Employe).filter_by(matricule=matricule).first()
            if not employe:
                continue
            annee = int(ligne["annee"])
            alloues = float(ligne.get("jours_alloues") or 0)
            pris = float(ligne.get("jours_pris") or 0)
            restants_brut = (ligne.get("jours_restants") or "").strip()
            restants = float(restants_brut) if restants_brut else alloues - pris

            solde = db.query(models.SoldeConge).filter_by(employe_id=employe.id, annee=annee).first()
            if not solde:
                solde = models.SoldeConge(employe_id=employe.id, annee=annee)
                db.add(solde)
            solde.jours_alloues = alloues
            solde.jours_pris = pris
            solde.jours_restants = restants
            nb_importes += 1
        db.commit()
        return RedirectResponse(url=f"/conges?ok={quote(str(nb_importes) + ' solde(s) importé(s).')}", status_code=303)
    except Exception:
        db.rollback()
        message = quote("Import impossible : vérifiez le format CSV (colonnes matricule,annee,jours_alloues,jours_pris,jours_restants).")
        return RedirectResponse(url=f"/conges?erreur={message}", status_code=303)
