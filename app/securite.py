"""Sécurité des comptes et des formulaires (lot 1, point 3).

1. Protection CSRF
   Chaque formulaire POST contient un jeton secret propre à la session ({{ csrf_input(request) }}).
   Un site extérieur ne connaît pas ce jeton : il ne peut donc pas faire valider / supprimer quelque
   chose à la place d'un utilisateur connecté à PASL-RH.
2. Blocage temporaire après plusieurs mots de passe erronés.
3. Règles de mot de passe et génération de mots de passe provisoires.
"""
import hmac
import secrets
import string
from datetime import timedelta

from fastapi import HTTPException, Request
from markupsafe import Markup

# --- Paramètres (modifiables ici) ---
MAX_TENTATIVES = 5                         # échecs consécutifs avant blocage
DUREE_BLOCAGE = timedelta(minutes=15)      # durée du blocage
LONGUEUR_MIN_MDP = 8

CLE_SESSION_CSRF = "csrf_token"
METHODES_PROTEGEES = {"POST", "PUT", "PATCH", "DELETE"}


# ------------------------------------------------------------------
# CSRF
# ------------------------------------------------------------------
def jeton_csrf(request: Request) -> str:
    """Retourne le jeton CSRF de la session (le crée au premier appel)."""
    jeton = request.session.get(CLE_SESSION_CSRF)
    if not jeton:
        jeton = secrets.token_urlsafe(32)
        request.session[CLE_SESSION_CSRF] = jeton
    return jeton


def csrf_input(request: Request) -> Markup:
    """Champ caché à placer dans chaque formulaire POST (utilisé dans les templates)."""
    return Markup(f'<input type="hidden" name="csrf_token" value="{jeton_csrf(request)}">')


async def verifier_csrf(request: Request):
    """Dépendance appliquée à toute l'application : refuse un POST sans jeton valide."""
    if request.method not in METHODES_PROTEGEES:
        return
    attendu = request.session.get(CLE_SESSION_CSRF)
    formulaire = await request.form()
    recu = formulaire.get("csrf_token") or request.headers.get("x-csrf-token")
    if not attendu or not recu or not hmac.compare_digest(str(recu), str(attendu)):
        raise HTTPException(
            status_code=403,
            detail="Formulaire expiré ou invalide. Rechargez la page, puis recommencez.",
        )


# ------------------------------------------------------------------
# Mots de passe
# ------------------------------------------------------------------
def valider_nouveau_mot_de_passe(mot_de_passe: str) -> str | None:
    """Retourne un message d'erreur si le mot de passe est trop faible, sinon None."""
    if len(mot_de_passe) < LONGUEUR_MIN_MDP:
        return f"Le mot de passe doit contenir au moins {LONGUEUR_MIN_MDP} caractères."
    if not any(c.isalpha() for c in mot_de_passe) or not any(c.isdigit() for c in mot_de_passe):
        return "Le mot de passe doit contenir au moins une lettre et un chiffre."
    return None


def generer_mot_de_passe_provisoire() -> str:
    """Mot de passe provisoire lisible (sans 0/O, 1/l/I pour éviter les confusions à la lecture)."""
    alphabet = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")
    while True:
        mdp = "".join(secrets.choice(alphabet) for _ in range(10))
        if valider_nouveau_mot_de_passe(mdp) is None:
            return mdp
