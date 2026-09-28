"""
Authentification par session : hachage de mot de passe (sans dépendance
externe, via hashlib), et dépendances FastAPI pour protéger les routes.
"""
import hashlib
import hmac
import secrets
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from .database import get_db
from . import models


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest_hex = stored.split("$")
    except ValueError:
        return False
    nouveau = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return hmac.compare_digest(nouveau.hex(), digest_hex)


def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Dépendance utilisable dans une route pour récupérer l'utilisateur connecté.
    La présence d'une session est déjà garantie par AuthMiddleware (main.py) :
    on ne devrait jamais arriver ici sans session valide, mais on vérifie quand même."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Non connecté")
    user = db.query(models.Utilisateur).get(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Session invalide")
    return user


def exiger_role(request: Request, *roles: str):
    """À appeler au début d'une route sensible : lève une 403 si le rôle
    de l'utilisateur connecté n'est pas dans la liste autorisée."""
    role = request.session.get("role")
    if role not in roles:
        raise HTTPException(status_code=403, detail="Action réservée à : " + ", ".join(roles))