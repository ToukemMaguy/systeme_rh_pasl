"""« Mettre à jour depuis le fichier RH » : la RH dépose SON fichier habituel (fixhiier_r.xlsx),
voit d'abord ce qui va changer (simulation), puis applique.

Le fichier déposé est gardé le temps de la confirmation dans data/imports/ (dossier non publié sur le web,
supprimé après application ou au bout de 24 h).
"""
import re
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..import_rh.lecture import FichierNonConforme, lire_fichier
from ..import_rh.moteur import importer
from ..import_rh.rapport_excel import rapport_en_excel
from ..outils import _exiger_rh, templates

router = APIRouter()

DOSSIER = Path("data/imports")
TAILLE_MAX = 20 * 1024 * 1024
_JETON = re.compile(r"^[0-9a-f]{32}$")


def _nettoyer_anciens():
    if DOSSIER.exists():
        for f in DOSSIER.iterdir():
            if f.is_file() and time.time() - f.stat().st_mtime > 24 * 3600:
                f.unlink(missing_ok=True)


def _chemin(jeton: str) -> Path | None:
    if not _JETON.match(jeton or ""):
        return None
    chemin = DOSSIER / f"{jeton}.xlsx"
    return chemin if chemin.exists() else None


@router.get("/fichier-rh")
def page_fichier_rh(request: Request):
    _exiger_rh(request)
    return templates.TemplateResponse(request, "fichier_rh.html", {"etape": "depot", "erreur": None})


@router.post("/fichier-rh/simuler")
def simuler(request: Request, db: Session = Depends(get_db), fichier: UploadFile = File(None)):
    _exiger_rh(request)
    _nettoyer_anciens()

    def erreur(message):
        return templates.TemplateResponse(request, "fichier_rh.html", {"etape": "depot", "erreur": message}, status_code=400)

    if not fichier or not fichier.filename:
        return erreur("Choisissez le fichier Excel de la RH.")
    if not fichier.filename.lower().endswith(".xlsx"):
        return erreur("Le fichier doit être au format Excel .xlsx (dans Excel : Fichier > Enregistrer sous > Classeur Excel).")
    contenu_brut = fichier.file.read(TAILLE_MAX + 1)
    if len(contenu_brut) > TAILLE_MAX:
        return erreur("Fichier trop volumineux (20 Mo maximum).")
    if not contenu_brut.startswith(b"PK"):
        return erreur("Ce fichier n'est pas un vrai classeur Excel .xlsx.")

    DOSSIER.mkdir(parents=True, exist_ok=True)
    jeton = uuid.uuid4().hex
    chemin = DOSSIER / f"{jeton}.xlsx"
    chemin.write_bytes(contenu_brut)
    try:
        rapport = importer(db, lire_fichier(chemin), appliquer=False)
    except FichierNonConforme as e:
        chemin.unlink(missing_ok=True)
        return erreur(f"Fichier non reconnu : {e}")
    (DOSSIER / f"{jeton}_simulation.xlsx").write_bytes(rapport_en_excel(rapport))
    return templates.TemplateResponse(request, "fichier_rh.html", {
        "etape": "simulation", "rapport": rapport, "jeton": jeton, "nom_fichier": fichier.filename, "erreur": None,
    })


@router.post("/fichier-rh/appliquer")
def appliquer(request: Request, db: Session = Depends(get_db), jeton: str = Form("")):
    _exiger_rh(request)
    chemin = _chemin(jeton)
    if not chemin:
        return templates.TemplateResponse(request, "fichier_rh.html", {
            "etape": "depot", "erreur": "La simulation a expiré (plus de 24 h) : déposez à nouveau le fichier."}, status_code=400)
    rapport = importer(db, lire_fichier(chemin), appliquer=True,
                       auteur=f"Import du fichier RH par {request.session.get('nom')}")
    chemin.unlink(missing_ok=True)
    (DOSSIER / f"{jeton}_simulation.xlsx").unlink(missing_ok=True)
    (DOSSIER / f"{jeton}_applique.xlsx").write_bytes(rapport_en_excel(rapport))
    return templates.TemplateResponse(request, "fichier_rh.html", {
        "etape": "applique", "rapport": rapport, "jeton": jeton, "erreur": None,
    })


@router.get("/fichier-rh/rapport/{jeton}/{type_rapport}")
def telecharger_rapport(jeton: str, type_rapport: str, request: Request):
    _exiger_rh(request)
    if not _JETON.match(jeton) or type_rapport not in ("simulation", "applique"):
        return RedirectResponse(url="/fichier-rh", status_code=303)
    chemin = DOSSIER / f"{jeton}_{type_rapport}.xlsx"
    if not chemin.exists():
        return RedirectResponse(url="/fichier-rh", status_code=303)
    return Response(content=chemin.read_bytes(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="rapport_import_{type_rapport}.xlsx"'})
