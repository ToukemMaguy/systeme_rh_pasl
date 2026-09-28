"""Point d'entrée de l'application PASL-RH : création de l'application, sécurité, et assemblage des modules.

Chaque domaine fonctionnel est dans son propre fichier du dossier app/routes/ :
  auth, tableau_de_bord, employes, demandes, espace, absences, conges, admin.
Les règles métier partagées sont dans app/regles_rh.py, les outils web dans app/outils.py.
"""
import os
from fastapi import FastAPI, Request, Depends
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from .database import SessionLocal
from . import models
from .outils import RedirectionVers
from .securite import verifier_csrf
from .regles_rh import appliquer_departs_echus
from . import journal  # [LOT 1 - POINT 1] active l'enregistrement automatique du journal d'audit
from datetime import date
from .routes import auth, tableau_de_bord, employes, demandes, espace, absences, conges, admin, compte, licenciements

# ============================================================
# APPLICATION
# ============================================================

# [LOT 1 - POINT 3] verifier_csrf s'applique à TOUTES les routes : tout POST sans jeton valide est refusé.
app = FastAPI(title="Système RH", dependencies=[Depends(verifier_csrf)])


app.mount("/static", StaticFiles(directory="app/static"), name="static")

PUBLIC_PATHS = {"/login"}


def _rafraichir_session(request: Request) -> bool:
    """[CORRECTIF F2] Relit le compte en base à chaque requête.

    Avant : le rôle était lu uniquement dans le cookie de session. Un compte supprimé ou rétrogradé
    par l'administrateur gardait donc ses anciens droits jusqu'à 14 jours (durée du cookie).
    Retourne False si le compte n'existe plus (la session est alors vidée)."""
    db = SessionLocal()
    try:
        utilisateur = db.query(models.Utilisateur).get(request.session.get("user_id"))
        # [LOT 1 - POINT 4] un compte désactivé (départ de l'employé) est déconnecté immédiatement
        if not utilisateur or not utilisateur.compte_actif:
            request.session.clear()
            return False
        request.session["nom"] = utilisateur.nom
        request.session["role"] = utilisateur.role
        request.session["employe_id"] = utilisateur.employe_id
        request.session["doit_changer_mdp"] = bool(utilisateur.doit_changer_mdp)
        return True
    finally:
        db.close()


# [LOT 1 - POINT 4] Départs programmés : vérifiés au plus une fois par jour, à la première requête du jour.
_derniere_verification_departs: date | None = None


def _verifier_departs_du_jour():
    global _derniere_verification_departs
    if _derniere_verification_departs == date.today():
        return
    journal.definir_auteur(**{k: v for k, v in journal.UTILISATEUR_SYSTEME.items() if k != "id"})
    db = SessionLocal()
    try:
        appliquer_departs_echus(db)
        _derniere_verification_departs = date.today()
    finally:
        db.close()


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/static"):
            return await call_next(request)
        _verifier_departs_du_jour()
        ip = request.client.host if request.client else None
        journal.definir_auteur(ip=ip)
        if path in PUBLIC_PATHS:
            return await call_next(request)
        if not request.session.get("user_id") or not _rafraichir_session(request):
            return RedirectResponse(url="/login")
        # [LOT 1 - POINT 1] auteur des modifications faites pendant cette requête
        journal.definir_auteur(request.session.get("user_id"), request.session.get("nom"), request.session.get("role"), ip)
        # [LOT 1 - POINT 3] Décision PASL : le changement du mot de passe provisoire n'est PAS imposé.
        # L'utilisateur peut le changer quand il le souhaite (icône 🔑 du menu).
        return await call_next(request)


# [CORRECTIF F3] Plus de clé secrète « par défaut » écrite dans le code : sans SECRET_KEY dans le .env,
# n'importe qui connaissant la valeur par défaut pouvait fabriquer un cookie « Chef RH ».
SECRET_KEY = os.getenv("SECRET_KEY", "")
if len(SECRET_KEY) < 32:
    raise RuntimeError(
        "SECRET_KEY absente ou trop courte dans le fichier .env (32 caractères minimum). "
        "Générez-en une avec : python -c \"import secrets; print(secrets.token_hex(32))\""
    )

app.add_middleware(AuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=8 * 3600, same_site="lax")  # session de 8 h (une journée de travail)


@app.exception_handler(RedirectionVers)
async def gerer_redirection_vers(request: Request, exc: RedirectionVers):
    return RedirectResponse(url=exc.url, status_code=303)


# Assemblage des modules (l'ordre est celui de l'ancien main.py : il compte pour les adresses
# qui se ressemblent, ex. /employes/nouveau doit passer avant /employes/{employe_id})
for module in (auth, tableau_de_bord, employes, demandes, espace, absences, conges, admin, compte, licenciements):
    app.include_router(module.router)
