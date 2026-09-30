"""[PRODUCTION - POINT 5] Sauvegarde quotidienne : base MySQL + pièces jointes des employés.

Lancé chaque soir par le Planificateur de tâches Windows (voir deploiement/installer_taches.ps1),
ou à la main :
    python -m app.scripts.sauvegarder

Produit dans le dossier SAUVEGARDE_DOSSIER (par défaut « sauvegardes » à côté de l'application) :
    AAAA-MM-JJ_HHMM/base_systeme_rh.sql    (export complet de la base, restaurable avec mysql)
    AAAA-MM-JJ_HHMM/pieces_jointes.zip     (CNI, photos, justificatifs, PV...)
Les sauvegardes de plus de SAUVEGARDE_JOURS jours (30 par défaut) sont supprimées automatiquement.

CONSEIL : faire pointer SAUVEGARDE_DOSSIER vers un AUTRE disque ou un partage réseau. Une sauvegarde
sur le même disque que la base ne protège pas d'une panne de ce disque.

Restauration (en cas de besoin) :
    mysql -u pasl_rh -p systeme_rh < sauvegardes\\AAAA-MM-JJ_HHMM\\base_systeme_rh.sql
    puis décompresser pieces_jointes.zip dans app\\static\\uploads\\employes
"""
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

load_dotenv()

DOSSIER = Path(os.getenv("SAUVEGARDE_DOSSIER", "sauvegardes"))
JOURS_A_GARDER = int(os.getenv("SAUVEGARDE_JOURS", "30"))
MYSQLDUMP = os.getenv("MYSQLDUMP", r"C:\xampp\mysql\bin\mysqldump.exe")
DOSSIER_UPLOADS = Path("app/static/uploads/employes")


def _journal(message: str) -> None:
    ligne = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    print(ligne)
    Path("logs").mkdir(exist_ok=True)
    with open(Path("logs") / "sauvegardes.log", "a", encoding="utf-8") as f:
        f.write(ligne + "\n")


def _exporter_base(fichier: Path) -> None:
    url = urlparse(os.getenv("DATABASE_URL", "").replace("mysql+pymysql://", "mysql://"))
    if url.scheme != "mysql":
        raise RuntimeError("DATABASE_URL n'est pas une base MySQL : sauvegarde de la base impossible.")
    if not Path(MYSQLDUMP).exists() and not shutil.which(MYSQLDUMP):
        raise RuntimeError(f"mysqldump introuvable ({MYSQLDUMP}). Renseignez MYSQLDUMP dans le fichier .env.")
    env = dict(os.environ)
    env["MYSQL_PWD"] = unquote(url.password or "")   # mot de passe transmis sans apparaître dans la ligne de commande
    commande = [MYSQLDUMP, "--single-transaction", "--routines", "--default-character-set=utf8mb4",
                "-h", url.hostname or "localhost", "-P", str(url.port or 3306),
                "-u", unquote(url.username or ""), url.path.lstrip("/")]
    with open(fichier, "wb") as sortie:
        resultat = subprocess.run(commande, stdout=sortie, stderr=subprocess.PIPE, env=env, timeout=1800)
    if resultat.returncode != 0:
        raise RuntimeError("mysqldump a échoué : " + resultat.stderr.decode("utf-8", "replace")[:500])
    if fichier.stat().st_size < 1000:
        raise RuntimeError("Export de la base anormalement petit : vérifiez la sauvegarde.")


def _archiver_pieces(fichier: Path) -> int:
    nombre = 0
    with zipfile.ZipFile(fichier, "w", zipfile.ZIP_DEFLATED) as archive:
        if DOSSIER_UPLOADS.exists():
            for chemin in DOSSIER_UPLOADS.rglob("*"):
                if chemin.is_file():
                    archive.write(chemin, chemin.relative_to(DOSSIER_UPLOADS))
                    nombre += 1
    return nombre


def _supprimer_anciennes() -> int:
    limite = datetime.now() - timedelta(days=JOURS_A_GARDER)
    supprimees = 0
    for dossier in DOSSIER.iterdir():
        try:
            date_dossier = datetime.strptime(dossier.name, "%Y-%m-%d_%H%M")
        except ValueError:
            continue        # dossier qui n'est pas une sauvegarde : on n'y touche pas
        if dossier.is_dir() and date_dossier < limite:
            shutil.rmtree(dossier)
            supprimees += 1
    return supprimees


def sauvegarder() -> bool:
    cible = DOSSIER / datetime.now().strftime("%Y-%m-%d_%H%M")
    cible.mkdir(parents=True, exist_ok=True)
    try:
        _exporter_base(cible / "base_systeme_rh.sql")
        nb = _archiver_pieces(cible / "pieces_jointes.zip")
        taille = sum(f.stat().st_size for f in cible.iterdir()) / 1024 / 1024
        supprimees = _supprimer_anciennes()
        _journal(f"OK : {cible} ({taille:.1f} Mo, {nb} pièce(s) jointe(s)). Anciennes sauvegardes supprimées : {supprimees}.")
        return True
    except Exception as e:
        _journal(f"ÉCHEC de la sauvegarde {cible} : {e}")
        return False


if __name__ == "__main__":
    sys.exit(0 if sauvegarder() else 1)
