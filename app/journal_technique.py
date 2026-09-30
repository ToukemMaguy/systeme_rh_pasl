"""[PRODUCTION - POINT 4] Journal technique : fichier logs/app.log pour diagnostiquer les pannes.

À ne pas confondre avec le journal d'audit (app/journal.py), qui trace les actions des utilisateurs
dans la base. Ici on enregistre les ERREURS techniques (base arrêtée, bug...), avec la référence
affichée à l'utilisateur sur la page d'erreur, pour retrouver la trace complète.
Rotation automatique : 10 fichiers de 5 Mo au maximum (les plus anciens sont supprimés).
"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

DOSSIER_LOGS = Path("logs")
logger = logging.getLogger("pasl_rh")


def configurer_logs() -> None:
    if logger.handlers:          # déjà configuré (rechargement du module)
        return
    DOSSIER_LOGS.mkdir(exist_ok=True)
    fichier = RotatingFileHandler(DOSSIER_LOGS / "app.log", maxBytes=5 * 1024 * 1024, backupCount=10, encoding="utf-8")
    fichier.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(fichier)
    # Les erreurs du serveur web (uvicorn) vont aussi dans le même fichier
    logging.getLogger("uvicorn.error").addHandler(fichier)
