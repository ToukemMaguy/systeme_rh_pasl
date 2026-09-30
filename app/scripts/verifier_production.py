"""[PRODUCTION - POINT 7] Vérification avant mise en production (et après chaque mise à jour).

    python -m app.scripts.verifier_production

Contrôle la configuration (.env), la base, les comptes et les fichiers, puis affiche une liste :
    [OK]        conforme
    [ATTENTION] à corriger si possible (ne bloque pas le démarrage)
    [ERREUR]    à corriger avant d'ouvrir l'application aux utilisateurs
"""
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()
resultats = []


def _ok(message): resultats.append(("OK", message))
def _attention(message): resultats.append(("ATTENTION", message))
def _erreur(message): resultats.append(("ERREUR", message))


def verifier_configuration():
    cle = os.getenv("SECRET_KEY", "")
    _ok("SECRET_KEY définie (64 caractères conseillés).") if len(cle) >= 32 else _erreur("SECRET_KEY absente ou trop courte.")

    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("mysql"):
        _erreur("DATABASE_URL ne désigne pas une base MySQL.")
    elif (urlparse(url.replace("mysql+pymysql://", "mysql://")).username or "") == "root":
        _attention("La base est utilisée avec le compte « root » : créez le compte dédié pasl_rh (voir README).")
    else:
        _ok("Compte MySQL dédié utilisé.")

    app_url = os.getenv("APP_URL", "")
    if not app_url or "127.0.0.1" in app_url or "localhost" in app_url:
        _erreur(f"APP_URL = « {app_url} » : les liens des mails ne fonctionneront pas sur les autres postes. "
                "Mettez l'adresse du serveur, ex. http://NOM-DU-SERVEUR:8000")
    else:
        _ok(f"APP_URL = {app_url}")

    if not all(os.getenv(v) for v in ("SMTP_SERVER", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM_EMAIL")):
        _erreur("Paramètres SMTP incomplets : aucun mail ne partira.")
    elif "mailtrap" in os.getenv("SMTP_SERVER", ""):
        _attention("SMTP_SERVER pointe vers Mailtrap (boîte de TEST) : les mails n'arriveront pas aux employés.")
    else:
        _ok(f"Serveur de mail : {os.getenv('SMTP_SERVER')}")

    mysqldump = os.getenv("MYSQLDUMP", r"C:\xampp\mysql\bin\mysqldump.exe")
    _ok("mysqldump trouvé (sauvegardes possibles).") if Path(mysqldump).exists() else _erreur(f"mysqldump introuvable ({mysqldump}) : renseignez MYSQLDUMP dans .env.")


def verifier_fichiers():
    for chemin in ("app/static/vendor/tailwind.css", "app/static/vendor/polices.css",
                   "app/static/vendor/polices/material-symbols-outlined.woff2"):
        if not Path(chemin).exists():
            _erreur(f"Fichier d'affichage manquant : {chemin}")
    dossier = Path("app/static/uploads/employes")
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        test = dossier / ".test_ecriture"
        test.write_text("ok"); test.unlink()
        _ok("Dossier des pièces jointes accessible en écriture.")
    except OSError as e:
        _erreur(f"Impossible d'écrire dans {dossier} : {e}")

    sauvegardes = Path(os.getenv("SAUVEGARDE_DOSSIER", "sauvegardes"))
    dates = []
    for d in (sauvegardes.iterdir() if sauvegardes.exists() else []):
        try:
            dates.append(datetime.strptime(d.name, "%Y-%m-%d_%H%M"))
        except ValueError:
            pass
    if not dates:
        _attention("Aucune sauvegarde trouvée : lancez « python -m app.scripts.sauvegarder » pour tester.")
    elif (datetime.now() - max(dates)).days > 1:
        _attention(f"Dernière sauvegarde le {max(dates):%d/%m/%Y} : la tâche planifiée tourne-t-elle ?")
    else:
        _ok(f"Dernière sauvegarde : {max(dates):%d/%m/%Y %H:%M}")


def verifier_base():
    try:
        from sqlalchemy import text
        from app.database import SessionLocal
        from app import models
        db = SessionLocal()
    except Exception as e:
        _erreur(f"Connexion à la base impossible : {e}")
        return
    try:
        db.execute(text("SELECT 1"))
        _ok("Connexion à la base réussie.")
        try:
            from alembic.config import Config
            from alembic.script import ScriptDirectory
            tete = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
            actuelle = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
            _ok("Base à jour (migrations).") if actuelle == tete else _erreur(
                f"Base pas à jour (version {actuelle}, attendue {tete}) : lancez « python -m alembic upgrade head ».")
        except Exception as e:
            _attention(f"Version de la base non vérifiée : {e}")

        admins = db.query(models.Utilisateur).filter_by(role="Administrateur", compte_actif=True).count()
        _ok(f"{admins} compte(s) Administrateur actif(s).") if admins else _erreur("Aucun compte Administrateur actif.")

        suspects = [u.email for u in db.query(models.Utilisateur).all()
                    if any(m in (u.email or "").lower() for m in ("@t.cm", "test", "exemple", "example", "demo"))]
        if suspects:
            _attention(f"Comptes qui ressemblent à des comptes de TEST (à supprimer ?) : {', '.join(suspects[:10])}")
        else:
            _ok("Aucun compte de test repéré.")

        sans_matricule = db.query(models.Employe).filter(models.Employe.statut == "actif",
                                                         (models.Employe.matricule.is_(None)) | (models.Employe.matricule == "")).count()
        if sans_matricule:
            _attention(f"{sans_matricule} employé(s) actif(s) sans matricule : ils ne pourront pas se connecter avec leur matricule.")
        actifs = db.query(models.Employe).filter_by(statut="actif").count()
        avec_compte = db.query(models.Utilisateur).filter(models.Utilisateur.employe_id.isnot(None)).count()
        _ok(f"{actifs} employé(s) actif(s), {avec_compte} compte(s) rattaché(s) à une fiche.")
    except Exception as e:
        _erreur(f"Vérification de la base impossible : {e}")
    finally:
        db.close()


if __name__ == "__main__":
    verifier_configuration()
    verifier_fichiers()
    verifier_base()
    print("\nVérification de la mise en production PASL-RH\n" + "=" * 48)
    for niveau, message in resultats:
        print(f"[{niveau}] {message}")
    nb_erreurs = sum(1 for n, _ in resultats if n == "ERREUR")
    print(f"\n{nb_erreurs} erreur(s), {sum(1 for n, _ in resultats if n == 'ATTENTION')} point(s) d'attention.")
    sys.exit(1 if nb_erreurs else 0)
