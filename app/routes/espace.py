"""Espace personnel de l'employé connecté."""
from datetime import date
from fastapi import APIRouter, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from .. import pdf as pdf_module
from ..outils import _acces_refuse, _email_valide, _enregistrer_fichier, _entier_ou_none, _valider_saisies_employe, templates
from ..regles_rh import QUOTA_CONGES_PAR_MOIS, _age_annees, _anciennete, _historique_employe, _solde_conges

router = APIRouter()


# ============================================================
# ESPACE EMPLOYÉ
# ============================================================

@router.get("/mes-infos")
def mes_infos(request: Request, db: Session = Depends(get_db)):
    """Fiche complète de l'employé connecté (lecture seule)."""
    if request.session.get("role") != "Employé":
        _acces_refuse(request)

    utilisateur = db.query(models.Utilisateur).get(request.session["user_id"])
    if not utilisateur or not utilisateur.employe_id:
        raise HTTPException(status_code=404, detail="Aucune fiche employé rattachée à ce compte.")

    employe = db.query(models.Employe).get(utilisateur.employe_id)
    historique = _historique_employe(db, employe.id)

    soldes = (
        db.query(models.SoldeConge)
        .filter_by(employe_id=employe.id)
        .order_by(models.SoldeConge.annee.desc())
        .all()
    )

    # Absences
    mes_absences = (
        db.query(models.Absence)
        .filter_by(employe_id=employe.id)
        .order_by(models.Absence.date_debut.desc())
        .all()
    )

    # Sanctions
    mes_sanctions = (
        db.query(models.Sanction)
        .filter_by(employe_id=employe.id)
        .order_by(models.Sanction.date_sanction.desc())
        .all()
    )

    return templates.TemplateResponse(request, "mes_infos.html", {
        "employe": employe,
        "historique": historique,
        "soldes": soldes,
        "mes_absences": mes_absences,
        "mes_sanctions": mes_sanctions,
        "anciennete": _anciennete(employe.date_embauche),
        "age": _age_annees(employe.date_naissance),
    })
@router.get("/mes-infos/pdf")
def mes_infos_pdf(request: Request, db: Session = Depends(get_db)):
    """Téléchargement de sa propre fiche employé en PDF."""
    if request.session.get("role") != "Employé":
        _acces_refuse(request)

    utilisateur = db.query(models.Utilisateur).get(request.session["user_id"])
    if not utilisateur or not utilisateur.employe_id:
        raise HTTPException(status_code=404, detail="Aucune fiche employé rattachée à ce compte.")

    employe = db.query(models.Employe).get(utilisateur.employe_id)
    historique = _historique_employe(db, employe.id)
    sanctions = (
        db.query(models.Sanction)
        .filter_by(employe_id=employe.id)
        .order_by(models.Sanction.date_sanction.desc())
        .all()
    )

    # [CORRECTIF B3] Solde calculé par la fonction commune (avant : « années × 18 »)
    solde = _solde_conges(db, employe)

    type_conge = db.query(models.TypeAbsence).filter(models.TypeAbsence.libelle.ilike("%ongé%")).first()
    conges_pris = []
    if type_conge:
        conges_pris = (
            db.query(models.Absence)
            .filter_by(employe_id=employe.id, type_absence_id=type_conge.id)
            .order_by(models.Absence.date_debut.desc())
            .all()
        )

    soldes_conges = {**solde, "conges_pris": conges_pris}

    contenu = pdf_module.generer_fiche_employe_pdf(employe, historique, sanctions, soldes_conges)
    nom_fichier = f"ma_fiche_{employe.matricule or employe.id}_{employe.nom}_{employe.prenom}.pdf".replace(" ", "_")

    return Response(
        content=contenu,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'},
    )
@router.get("/mes-infos/modifier")
def mes_infos_modifier_form(request: Request, db: Session = Depends(get_db)):
    """Formulaire de modification de ses propres informations."""
    if request.session.get("role") != "Employé":
        _acces_refuse(request)

    utilisateur = db.query(models.Utilisateur).get(request.session["user_id"])
    if not utilisateur or not utilisateur.employe_id:
        raise HTTPException(status_code=404, detail="Aucune fiche employé rattachée à ce compte.")

    employe = db.query(models.Employe).get(utilisateur.employe_id)

    return templates.TemplateResponse(request, "mes_infos_modifier.html", {
        "employe": employe,
        "erreur": None,
        "succes": None,
    })


@router.post("/mes-infos/modifier")
def mes_infos_modifier_post(
    request: Request,
    db: Session = Depends(get_db),
    telephone_perso: str = Form(""),
    email_perso: str = Form(""),
    statut_matrimonial: str = Form(""),
    nombre_enfants: str = Form(""),
    contact_urgence_nom: str = Form(""),
    contact_urgence_tel: str = Form(""),
    photo: UploadFile = File(None),
):
    """Enregistrement des modifications de l'employé."""
    if request.session.get("role") != "Employé":
        _acces_refuse(request)

    utilisateur = db.query(models.Utilisateur).get(request.session["user_id"])
    if not utilisateur or not utilisateur.employe_id:
        raise HTTPException(status_code=404, detail="Aucune fiche employé rattachée à ce compte.")

    employe = db.query(models.Employe).get(utilisateur.employe_id)

    # [CORRECTIF B11 + B13] Contrôle des saisies avant enregistrement
    erreur = _valider_saisies_employe(nombre_enfants, "", email_perso)
    if erreur:
        return templates.TemplateResponse(request, "mes_infos_modifier.html", {
            "employe": employe, "erreur": erreur, "succes": None,
        }, status_code=400)

    # Mise à jour des champs autorisés
    employe.telephone_perso = telephone_perso.strip() or None
    employe.email_perso = _email_valide(email_perso)
    employe.statut_matrimonial = statut_matrimonial.strip() or None
    try:
        employe.nombre_enfants = _entier_ou_none(nombre_enfants.strip())
    except ValueError:
        employe.nombre_enfants = None
    employe.contact_urgence_nom = contact_urgence_nom.strip() or None
    employe.contact_urgence_tel = contact_urgence_tel.strip() or None

    # Upload de la photo si fournie
    chemin_photo = _enregistrer_fichier(photo, employe.id, "photo")
    if chemin_photo:
        employe.photo_path = chemin_photo

    db.commit()

    return templates.TemplateResponse(request, "mes_infos_modifier.html", {
        "employe": employe,
        "erreur": None,
        "succes": "Vos informations ont bien été enregistrées.",
    })
@router.get("/espace")
def espace_perso(request: Request, db: Session = Depends(get_db)):
    if request.session.get("role") != "Employé":
        return RedirectResponse(url="/", status_code=303)
    utilisateur = db.query(models.Utilisateur).get(request.session["user_id"])
    if not utilisateur or not utilisateur.employe_id:
        raise HTTPException(status_code=404, detail="Aucune fiche employé rattachée à ce compte.")
    employe = db.query(models.Employe).get(utilisateur.employe_id)
    aujourdhui = date.today()

    # [CORRECTIF B3 + B6] Solde calculé par la fonction commune (inclut les jours déduits)
    solde = _solde_conges(db, employe, aujourdhui)
    soldes = (
        db.query(models.SoldeConge)
        .filter_by(employe_id=employe.id)
        .order_by(models.SoldeConge.annee)
        .all()
    )

    type_conge = db.query(models.TypeAbsence).filter(models.TypeAbsence.libelle.ilike("%ongé%")).first()
    conges_pris = []
    if type_conge:
        conges_pris = (
            db.query(models.Absence)
            .filter_by(employe_id=employe.id, type_absence_id=type_conge.id)
            .order_by(models.Absence.date_debut.desc())
            .all()
        )
    mes_demandes = (
        db.query(models.DemandeRh)
        .filter(
            (models.DemandeRh.demandeur_id == utilisateur.id)
            | (models.DemandeRh.employe_concerne_id == employe.id)
        )
        .order_by(models.DemandeRh.date_demande.desc())
        .all()
    )
    # Mes absences réelles (toutes, pas seulement les congés)
    mes_absences = (
        db.query(models.Absence)
        .filter_by(employe_id=employe.id)
        .order_by(models.Absence.date_debut.desc())
        .all()
    )
        # Sanctions de l'employé
    mes_sanctions = (
        db.query(models.Sanction)
        .filter_by(employe_id=employe.id)
        .order_by(models.Sanction.date_sanction.desc())
        .all()
    )
    return templates.TemplateResponse(request, "espace.html", {
        "employe": employe,
        "alloues_depuis_embauche": solde["total_alloue"],
        "pris_depuis_embauche": solde["total_pris"],
        "restants_depuis_embauche": solde["total_restant"],
        "annees_comptees": solde["annees_comptees"],
        "quota_annuel": round(QUOTA_CONGES_PAR_MOIS * 12, 1),
        "soldes": soldes,
        "conges_pris": conges_pris,
        "mes_demandes": mes_demandes,
        "anciennete": _anciennete(employe.date_embauche),
        "mes_absences": mes_absences,
        "mes_sanctions": mes_sanctions,
    })
