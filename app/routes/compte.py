"""Mon compte : changement de mot de passe (tous les rôles). Lot 1, point 3."""
from fastapi import APIRouter, Request, Depends, Form
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from .. import auth
from ..outils import templates
from ..securite import valider_nouveau_mot_de_passe, LONGUEUR_MIN_MDP

router = APIRouter()


def _page(request: Request, erreur: str | None = None, succes: str | None = None, status_code: int = 200):
    return templates.TemplateResponse(request, "mot_de_passe.html", {
        "erreur": erreur,
        "succes": succes,
        # simple information (le changement n'est pas imposé)
        "obligatoire": bool(request.session.get("doit_changer_mdp")),
        "longueur_min": LONGUEUR_MIN_MDP,
        "accueil": "/espace" if request.session.get("role") == "Employé" else "/",
    }, status_code=status_code)


@router.get("/mon-compte/mot-de-passe")
def formulaire_mot_de_passe(request: Request):
    return _page(request)


@router.post("/mon-compte/mot-de-passe")
def changer_mot_de_passe(
    request: Request,
    db: Session = Depends(get_db),
    mot_de_passe_actuel: str = Form(...),
    nouveau_mot_de_passe: str = Form(...),
    confirmation: str = Form(...),
):
    utilisateur = db.query(models.Utilisateur).get(request.session.get("user_id"))

    if not auth.verify_password(mot_de_passe_actuel, utilisateur.mot_de_passe_hash):
        return _page(request, erreur="Le mot de passe actuel est incorrect.", status_code=400)
    erreur = valider_nouveau_mot_de_passe(nouveau_mot_de_passe)
    if erreur:
        return _page(request, erreur=erreur, status_code=400)
    if nouveau_mot_de_passe != confirmation:
        return _page(request, erreur="La confirmation ne correspond pas au nouveau mot de passe.", status_code=400)
    if nouveau_mot_de_passe == mot_de_passe_actuel:
        return _page(request, erreur="Le nouveau mot de passe doit être différent de l'actuel.", status_code=400)

    utilisateur.mot_de_passe_hash = auth.hash_password(nouveau_mot_de_passe)
    utilisateur.doit_changer_mdp = False
    db.commit()
    request.session["doit_changer_mdp"] = False
    return _page(request, succes="Votre mot de passe a bien été modifié.")
