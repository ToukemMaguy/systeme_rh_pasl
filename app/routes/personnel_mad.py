"""Registre du personnel mis à disposition (MAD) : chauffeurs, agents de recouvrement, DSA...
Ce ne sont pas des employés de la PASL (ni contrat, ni matricule, ni compte), mais la RH doit savoir
combien il y en a et où. Lecture : RH, Comité, Administrateur. Modification : RH.
"""
from collections import Counter
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..outils import _date_ou_none, _entier_ou_none, _exiger_lecture, _exiger_rh, templates

router = APIRouter()


def _references(db):
    return {
        "departements": db.query(models.Departement).order_by(models.Departement.nom).all(),
        "agences": db.query(models.Agence).order_by(models.Agence.nom).all(),
        "entreprises": sorted({s for (s,) in db.query(models.PersonnelMAD.societe).distinct() if s}),
    }


@router.get("/personnel-mad")
def liste_mad(request: Request, statut: str = "actifs", entreprise: str = "", db: Session = Depends(get_db)):
    _exiger_lecture(request)
    requete = db.query(models.PersonnelMAD)
    if statut == "actifs":
        requete = requete.filter(models.PersonnelMAD.actif.is_(True))
    elif statut == "anciens":
        requete = requete.filter(models.PersonnelMAD.actif.is_(False))
    if entreprise:
        requete = requete.filter(models.PersonnelMAD.societe == (None if entreprise == "-" else entreprise))
    personnes = requete.order_by(models.PersonnelMAD.nom_complet).all()
    actifs = db.query(models.PersonnelMAD).filter(models.PersonnelMAD.actif.is_(True)).all()
    return templates.TemplateResponse(request, "personnel_mad.html", {
        "personnes": personnes, "statut": statut, "nb_actifs": len(actifs),
        "par_fonction": Counter(p.fonction or "Non précisée" for p in actifs).most_common(),
        "par_lieu": Counter(p.agence.nom if p.agence else "Siège" for p in actifs).most_common(),
        "par_entreprise": Counter(p.societe or "Non renseignée" for p in actifs).most_common(),
        "entreprise": entreprise,
        "est_rh": request.session.get("role") in ("Chef RH", "Assistant RH"),
    })


def _formulaire(request, db, valeurs, mad_id=None, erreur=None, status_code=200):
    return templates.TemplateResponse(request, "formulaire_mad.html", {
        "valeurs": valeurs, "mad_id": mad_id, "erreur": erreur, **_references(db)}, status_code=status_code)


@router.get("/personnel-mad/nouveau")
def formulaire_nouveau(request: Request, db: Session = Depends(get_db)):
    _exiger_rh(request)
    return _formulaire(request, db, {"actif": True})


@router.get("/personnel-mad/{mad_id}/modifier")
def formulaire_modifier(mad_id: int, request: Request, db: Session = Depends(get_db)):
    _exiger_rh(request)
    p = db.get(models.PersonnelMAD, mad_id)
    if not p:
        raise HTTPException(status_code=404, detail="Personne introuvable dans le registre")
    return _formulaire(request, db, p.__dict__, mad_id)


def _enregistrer(p, nom_complet, fonction, departement_id, agence_id, societe, telephone, email, date_debut, date_fin, actif, observations):
    p.nom_complet = " ".join(nom_complet.split())
    p.fonction = fonction.strip() or None
    p.departement_id = _entier_ou_none(departement_id)
    p.agence_id = _entier_ou_none(agence_id)
    p.societe = societe.strip() or None
    p.telephone = telephone.strip() or None
    p.email = email.strip() or None
    p.date_debut = _date_ou_none(date_debut)
    p.date_fin = _date_ou_none(date_fin)
    p.actif = actif == "1"
    p.observations = observations.strip() or None


@router.post("/personnel-mad/enregistrer")
def enregistrer(
    request: Request, db: Session = Depends(get_db),
    mad_id: str = Form(""), nom_complet: str = Form(""), fonction: str = Form(""), departement_id: str = Form(""),
    agence_id: str = Form(""), societe: str = Form(""), telephone: str = Form(""), email: str = Form(""),
    date_debut: str = Form(""), date_fin: str = Form(""), actif: str = Form(""), observations: str = Form(""),
):
    _exiger_rh(request)
    saisie = dict(nom_complet=nom_complet, fonction=fonction, departement_id=_entier_ou_none(departement_id),
                  agence_id=_entier_ou_none(agence_id), societe=societe, telephone=telephone, email=email,
                  date_debut=date_debut, date_fin=date_fin, actif=actif == "1", observations=observations)
    ident = _entier_ou_none(mad_id)
    if not nom_complet.strip():
        return _formulaire(request, db, saisie, ident, "Le nom est obligatoire.", 400)
    d1, d2 = _date_ou_none(date_debut), _date_ou_none(date_fin)
    if d1 and d2 and d2 < d1:
        return _formulaire(request, db, saisie, ident, "La date de fin ne peut pas précéder la date de début.", 400)
    p = db.get(models.PersonnelMAD, ident) if ident else models.PersonnelMAD()
    if ident and not p:
        raise HTTPException(status_code=404, detail="Personne introuvable dans le registre")
    _enregistrer(p, nom_complet, fonction, departement_id, agence_id, societe, telephone, email, date_debut, date_fin, actif, observations)
    if not ident:
        db.add(p)
    db.commit()
    return RedirectResponse(url=f"/personnel-mad?ok={quote(f'« {p.nom_complet} » enregistré.')}", status_code=303)


@router.post("/personnel-mad/{mad_id}/supprimer")
def supprimer(mad_id: int, request: Request, db: Session = Depends(get_db)):
    _exiger_rh(request)
    p = db.get(models.PersonnelMAD, mad_id)
    if p:
        nom = p.nom_complet
        db.delete(p)
        db.commit()
        return RedirectResponse(url=f"/personnel-mad?ok={quote(f'« {nom} » retiré du registre.')}", status_code=303)
    return RedirectResponse(url="/personnel-mad", status_code=303)
