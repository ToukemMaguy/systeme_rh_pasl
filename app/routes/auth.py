"""Connexion / déconnexion."""
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from .. import auth
from ..outils import templates
from ..securite import MAX_TENTATIVES, DUREE_BLOCAGE
from ..journal import journaliser_evenement, definir_auteur

router = APIRouter()


# ============================================================
# AUTHENTIFICATION
# ============================================================

@router.get("/login")
def page_connexion(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request, "login.html", {"erreur": None})


@router.post("/login")
def connexion(request: Request, db: Session = Depends(get_db), email: str = Form(...), mot_de_passe: str = Form(...)):
    utilisateur = db.query(models.Utilisateur).filter_by(email=email.strip()).first()
    maintenant = datetime.now()
    ip = request.client.host if request.client else None
    if utilisateur:
        definir_auteur(utilisateur.id, utilisateur.nom, utilisateur.role, ip)

    # [LOT 1 - POINT 4] Compte désactivé (départ de l'employé ou décision de l'administrateur).
    # Message affiché seulement si le mot de passe est juste, pour ne rien révéler à un inconnu.
    if utilisateur and not utilisateur.compte_actif and auth.verify_password(mot_de_passe, utilisateur.mot_de_passe_hash):
        return templates.TemplateResponse(request, "login.html", {
            "erreur": "Ce compte a été désactivé. Pour toute question, contactez le service RH.",
        }, status_code=403)
    if utilisateur and not utilisateur.compte_actif:
        return templates.TemplateResponse(request, "login.html", {
            "erreur": "Identifiant ou mot de passe incorrect.",
        }, status_code=400)

    # [LOT 1 - POINT 3] Compte temporairement bloqué après trop d'échecs
    if utilisateur and utilisateur.bloque_jusqua and utilisateur.bloque_jusqua > maintenant:
        minutes = int((utilisateur.bloque_jusqua - maintenant).total_seconds() // 60) + 1
        return templates.TemplateResponse(request, "login.html", {
            "erreur": f"Trop de tentatives échouées : compte bloqué pendant encore {minutes} minute(s). "
                      "En cas d'oubli du mot de passe, contactez l'administrateur.",
        }, status_code=400)

    if not utilisateur or not auth.verify_password(mot_de_passe, utilisateur.mot_de_passe_hash):
        # [LOT 1 - POINT 1] trace des échecs (utile pour repérer des tentatives d'intrusion)
        journaliser_evenement(db, "echec_connexion", f"Échec de connexion pour « {email.strip()[:100]} »", utilisateur, ip)
        if not utilisateur:
            db.commit()
        if utilisateur:
            utilisateur.tentatives_echouees = (utilisateur.tentatives_echouees or 0) + 1
            if utilisateur.tentatives_echouees >= MAX_TENTATIVES:
                utilisateur.bloque_jusqua = maintenant + DUREE_BLOCAGE
                utilisateur.tentatives_echouees = 0
            db.commit()
        return templates.TemplateResponse(request, "login.html", {
            "erreur": "Identifiant ou mot de passe incorrect.",
        }, status_code=400)

    # Connexion réussie : remise à zéro du compteur d'échecs
    utilisateur.tentatives_echouees = 0
    utilisateur.bloque_jusqua = None
    journaliser_evenement(db, "connexion", "Connexion réussie", utilisateur, ip)
    db.commit()

    request.session["user_id"] = utilisateur.id
    request.session["nom"] = utilisateur.nom
    request.session["role"] = utilisateur.role
    request.session["employe_id"] = utilisateur.employe_id
    request.session["doit_changer_mdp"] = bool(utilisateur.doit_changer_mdp)
    cible = "/espace" if utilisateur.role == "Employé" else "/"
    return RedirectResponse(url=cible, status_code=303)


@router.get("/logout")
def deconnexion(request: Request, db: Session = Depends(get_db)):
    if request.session.get("user_id"):
        utilisateur = db.query(models.Utilisateur).get(request.session["user_id"])
        journaliser_evenement(db, "deconnexion", "Déconnexion", utilisateur, request.client.host if request.client else None)
        db.commit()
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
