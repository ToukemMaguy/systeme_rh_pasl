"""Point d'entrée de l'application PASL-RH : création de l'application, sécurité, et assemblage des modules.

Chaque domaine fonctionnel est dans son propre fichier du dossier app/routes/ :
  auth, tableau_de_bord, employes, demandes, espace, absences, conges, admin.
Les règles métier partagées sont dans app/regles_rh.py, les outils web dans app/outils.py.
"""
import os
import uuid
from fastapi import FastAPI, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from .database import SessionLocal
from . import models
from .outils import FichierRefuse, RedirectionVers, templates
from .journal_technique import configurer_logs, logger
from .securite import verifier_csrf
from .regles_rh import appliquer_departs_echus
from . import journal  # [LOT 1 - POINT 1] active l'enregistrement automatique du journal d'audit
from datetime import date
from .routes import auth, tableau_de_bord, employes, demandes, espace, absences, conges, admin, compte, licenciements, calendrier_equipe, fichier_rh, personnel_mad

# ============================================================
# APPLICATION
# ============================================================

# [LOT 1 - POINT 3] verifier_csrf s'applique à TOUTES les routes : tout POST sans jeton valide est refusé.
# [PRODUCTION - POINT 7] Pages techniques /docs, /redoc et /openapi.json désactivées (inutiles aux utilisateurs,
# et elles décrivaient toutes les adresses de l'application).
app = FastAPI(title="Système RH", dependencies=[Depends(verifier_csrf)],
              docs_url=None, redoc_url=None, openapi_url=None)
configurer_logs()


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
        # Point 10 : un employé qui encadre au moins un collaborateur voit « Calendrier de mon équipe »
        request.session["est_n_plus_1"] = bool(utilisateur.employe_id and db.query(models.Employe.id).filter(
            models.Employe.n_plus_1_id == utilisateur.employe_id, models.Employe.statut == "actif").first())
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


# [PRODUCTION - POINT 2] En-têtes de sécurité ajoutés à toutes les réponses :
# - nosniff : le navigateur n'interprète jamais un fichier envoyé autrement que selon son type déclaré ;
# - DENY : l'application ne peut pas être affichée à l'intérieur d'un autre site (piège au clic) ;
# - same-origin : les adresses internes ne sont pas transmises à des sites extérieurs.
EN_TETES_SECURITE = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        reponse = await self._controler(request, call_next)
        for nom, valeur in EN_TETES_SECURITE.items():
            reponse.headers.setdefault(nom, valeur)
        return reponse

    async def _controler(self, request: Request, call_next):
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


# ============================================================
# [PRODUCTION - POINT 4] Pages d'erreur en français + trace dans logs/app.log
# ============================================================
def _page_erreur(request: Request, code: int, titre: str, message: str, reference: str | None = None):
    return templates.TemplateResponse(request, "erreur.html", {
        "code": code, "titre": titre, "message": message, "reference": reference,
    }, status_code=code)


MESSAGES_HTTP = {
    403: ("Accès refusé", "Vous n'avez pas les droits nécessaires pour ouvrir cette page."),
    404: ("Page introuvable", "Cette page n'existe pas ou l'élément demandé a été supprimé."),
    405: ("Action impossible", "Cette action n'est pas disponible depuis cette page. Revenez en arrière et réessayez."),
}


@app.exception_handler(StarletteHTTPException)
async def gerer_erreur_http(request: Request, exc: StarletteHTTPException):
    titre, message = MESSAGES_HTTP.get(exc.status_code, ("Requête impossible", str(exc.detail or "")))
    if exc.status_code == 404 and exc.detail and exc.detail != "Not Found":
        message = str(exc.detail)          # ex. « Demande introuvable »
    if exc.status_code == 403 and exc.detail and "Formulaire expiré" in str(exc.detail):
        titre, message = "Formulaire expiré", "Le formulaire a expiré (page restée ouverte trop longtemps). Revenez en arrière, rechargez la page (F5) et recommencez."
    return _page_erreur(request, exc.status_code, titre, message)


@app.exception_handler(RequestValidationError)
async def gerer_formulaire_invalide(request: Request, exc: RequestValidationError):
    logger.warning("Formulaire invalide sur %s : %s", request.url.path, exc.errors()[:3])
    return _page_erreur(request, 400, "Formulaire incomplet",
                        "Un champ obligatoire est vide ou une valeur n'a pas le bon format. Revenez en arrière, vérifiez le formulaire et recommencez.")


@app.exception_handler(FichierRefuse)
async def gerer_fichier_refuse(request: Request, exc: FichierRefuse):
    return _page_erreur(request, 400, "Fichier refusé", exc.message + " Revenez en arrière pour choisir un autre fichier.")


@app.exception_handler(Exception)
async def gerer_erreur_inattendue(request: Request, exc: Exception):
    reference = uuid.uuid4().hex[:8].upper()
    utilisateur = request.session.get("nom") if "session" in request.scope else None
    logger.exception("Erreur %s sur %s %s (utilisateur : %s)", reference, request.method, request.url.path, utilisateur or "—")
    if isinstance(exc, OperationalError):
        return _page_erreur(request, 503, "Service momentanément indisponible",
                            "La base de données ne répond pas. Réessayez dans quelques minutes ; si cela dure, prévenez le service informatique.",
                            reference)
    return _page_erreur(request, 500, "Une erreur s'est produite",
                        "L'opération n'a pas pu aboutir et rien n'a été enregistré. Vous pouvez réessayer.", reference)


# Assemblage des modules (l'ordre est celui de l'ancien main.py : il compte pour les adresses
# qui se ressemblent, ex. /employes/nouveau doit passer avant /employes/{employe_id})
for module in (auth, tableau_de_bord, employes, demandes, espace, absences, conges, admin, compte, licenciements,
               calendrier_equipe, fichier_rh, personnel_mad):
    app.include_router(module.router)
