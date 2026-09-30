"""Outils web communs : gabarits Jinja, contrôles d'accès, lecture des formulaires, fichiers envoyés."""
import re
import uuid
from pathlib import Path
from datetime import date
from fastapi import Request
from fastapi.templating import Jinja2Templates
from .calendrier import nb_jours_ouvrables, nb_jours_calendaires
from .securite import csrf_input


DOSSIER_UPLOADS = Path("app/static/uploads/employes")


# ============================================================
# OUTILS FICHIERS
# ============================================================

# [PRODUCTION - POINT 2] Contrôle des fichiers envoyés. Avant, n'importe quel fichier était accepté et
# publié tel quel : une page web piégée (.html, .svg) jointe à une demande pouvait agir à la place du
# collègue RH qui l'ouvrait. On n'accepte plus que des PDF et des images JPG/PNG de 5 Mo maximum,
# en vérifiant le CONTENU du fichier (signature), pas seulement son extension.
TAILLE_MAX_FICHIER = 5 * 1024 * 1024
SIGNATURES = {
    ".pdf": (b"%PDF",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
}
EXTENSIONS_IMAGES = {".jpg", ".jpeg", ".png"}


class FichierRefuse(Exception):
    """Fichier envoyé non conforme : le message est affiché tel quel à l'utilisateur."""
    def __init__(self, message: str):
        self.message = message


def verifier_fichier(fichier, images_seulement: bool = False) -> str | None:
    """Message d'erreur si le fichier n'est pas acceptable, None s'il est correct (ou absent)."""
    if not fichier or not fichier.filename:
        return None
    extension = Path(fichier.filename).suffix.lower()
    autorisees = EXTENSIONS_IMAGES if images_seulement else set(SIGNATURES)
    formats = "JPG ou PNG" if images_seulement else "PDF, JPG ou PNG"
    nom = Path(fichier.filename).name
    if extension not in autorisees:
        return f"« {nom} » : format non accepté. Formats autorisés : {formats}."
    contenu = fichier.file.read(TAILLE_MAX_FICHIER + 1)
    fichier.file.seek(0)
    if len(contenu) > TAILLE_MAX_FICHIER:
        return f"« {nom} » dépasse la taille maximale de 5 Mo. Réduisez-le (scan en qualité moyenne) puis réessayez."
    if not contenu.startswith(SIGNATURES[extension]):
        return f"« {nom} » n'est pas un vrai fichier {extension[1:].upper()} (fichier renommé ou abîmé)."
    return None


def _enregistrer_fichier(fichier, employe_id: int, prefixe: str) -> str | None:
    """Sauvegarde un fichier uploadé et retourne son chemin relatif (ou None si rien envoyé).
    Lève FichierRefuse si le fichier n'est pas conforme (voir verifier_fichier)."""
    if not fichier or not fichier.filename:
        return None
    erreur = verifier_fichier(fichier, images_seulement=(prefixe == "photo"))
    if erreur:
        raise FichierRefuse(erreur)
    dossier = DOSSIER_UPLOADS / str(employe_id)
    dossier.mkdir(parents=True, exist_ok=True)
    extension = Path(fichier.filename).suffix.lower()
    nom_sur = re.sub(r"[^a-zA-Z0-9_-]", "_", Path(fichier.filename).stem)[:50]
    nom_fichier = f"{prefixe}_{nom_sur}_{uuid.uuid4().hex[:8]}{extension}"
    chemin_disque = dossier / nom_fichier
    with open(chemin_disque, "wb") as f:
        f.write(fichier.file.read(TAILLE_MAX_FICHIER + 1))
    return f"static/uploads/employes/{employe_id}/{nom_fichier}"

templates = Jinja2Templates(directory="app/templates")


def _fmt_nombre(valeur) -> str:
    """Affiche 25 au lieu de 25.0, 22.5 reste 22.5."""
    if valeur is None:
        return "0"
    valeur = float(valeur)
    return str(int(valeur)) if valeur == int(valeur) else str(valeur)


templates.env.filters["fmt_nombre"] = _fmt_nombre


# [CORRECTIF B9] Durées affichées : les congés annuels en jours ouvrables (dimanches et fériés exclus),
# les autres absences (maladie, maternité...) restent en jours calendaires.
def _duree_absence(absence) -> int:
    if absence.type_absence and absence.type_absence.code == "CA":
        return nb_jours_ouvrables(absence.date_debut, absence.date_fin)
    return nb_jours_calendaires(absence.date_debut, absence.date_fin)


def _duree_demande(type_libelle: str, debut, fin) -> str:
    if type_libelle == "Congé":
        return f"{nb_jours_ouvrables(debut, fin)} jour(s) ouvrable(s)"
    return f"{nb_jours_calendaires(debut, fin)} jour(s)"


templates.env.globals["duree_absence"] = _duree_absence
templates.env.globals["duree_demande"] = _duree_demande
# [LOT 1 - POINT 3] {{ csrf_input(request) }} dans chaque formulaire POST
templates.env.globals["csrf_input"] = csrf_input


class RedirectionVers(Exception):
    """Levée pour renvoyer l'utilisateur vers une autre page."""
    def __init__(self, url: str):
        self.url = url


# ============================================================
# HELPERS ACCÈS / VALIDATION
# ============================================================
def _acces_refuse(request: Request):
    """Redirige silencieusement l'utilisateur vers son espace d'accueil."""
    role = request.session.get("role")
    if role == "Employé":
        raise RedirectionVers("/espace")
    raise RedirectionVers("/")
def _exiger_non_employe(request: Request):
    if request.session.get("role") == "Employé":
        raise RedirectionVers("/espace")


def _exiger_admin(request: Request):
    """Réservé à l'Administrateur (comptes + référentiels)."""
    role = request.session.get("role")
    if role != "Administrateur":
        _acces_refuse(request)


def _exiger_chef_rh(request: Request):
    """Réservé au Chef RH (validation des départs, licenciements)."""
    role = request.session.get("role")
    if role != "Chef RH":
        _acces_refuse(request)


def _exiger_rh(request: Request):
    """Réservé aux rôles RH : Chef RH et Assistant RH."""
    role = request.session.get("role")
    if role not in ("Chef RH", "Assistant RH"):
        _acces_refuse(request)


def _exiger_lecture(request: Request):
    """Accessible à tous les rôles non-Employé (RH + Administrateur + Comité)."""
    role = request.session.get("role")
    if role == "Employé":
        _acces_refuse(request)

    

def _entier_ou_none(valeur: str) -> int | None:
    if not valeur:
        return None
    try:
        return int(valeur)
    except ValueError:
        return None


def _date_ou_none(valeur: str) -> date | None:
    if not valeur:
        return None
    try:
        return date.fromisoformat(valeur)
    except ValueError:
        return None
def _email_valide(email: str) -> str | None:
    """Retourne l'email nettoyé s'il est valide, None sinon.
    Un email valide doit contenir '@' et un '.' après le '@'."""
    if not email:
        return None
    email = email.strip()
    if not email:
        return None
    if "@" not in email:
        return None
    parties = email.split("@")
    if len(parties) != 2:
        return None
    domaine = parties[1]
    if "." not in domaine or len(domaine) < 3:
        return None
    return email


def _valider_saisies_employe(nombre_enfants: str, email_pro: str, email_perso: str) -> str | None:
    """[CORRECTIF B11 + B13] Contrôles complémentaires du formulaire employé.
    Avant : « 2 enfants » provoquait une erreur 500, et un email mal saisi était effacé sans prévenir."""
    if nombre_enfants.strip():
        n = _entier_ou_none(nombre_enfants.strip())
        if n is None or n < 0:
            return "Le nombre d'enfants doit être un nombre entier (ex. 2)."
    if email_pro.strip() and not _email_valide(email_pro):
        return f"L'email professionnel « {email_pro.strip()} » n'est pas valide."
    if email_perso.strip() and not _email_valide(email_perso):
        return f"L'email personnel « {email_perso.strip()} » n'est pas valide."
    return None
