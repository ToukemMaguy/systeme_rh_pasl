"""Suivi des absences."""
from datetime import date
from urllib.parse import quote
from fastapi import APIRouter, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..calendrier import nb_jours_ouvrables
from ..outils import _date_ou_none, _enregistrer_fichier, _entier_ou_none, _exiger_chef_rh, _exiger_lecture, _exiger_non_employe, _exiger_rh, templates
from ..regles_rh import _tranche_age

router = APIRouter()


# ============================================================
# ABSENCES
# ============================================================

@router.get("/absences/nouvelle")
def formulaire_absence(request: Request, db: Session = Depends(get_db)):
    _exiger_rh(request)
    return templates.TemplateResponse(request, "formulaire_absence.html", {
        "employes": db.query(models.Employe).filter_by(statut="actif").order_by(models.Employe.nom).all(),
        "types_absence": db.query(models.TypeAbsence).filter(models.TypeAbsence.categorie.in_(["Permission", "Absence"])).order_by(models.TypeAbsence.categorie, models.TypeAbsence.libelle).all(),
        "valeurs": {},
        "erreur": None,
    })


@router.post("/absences/nouvelle")
def creer_absence(
    request: Request,
    db: Session = Depends(get_db),
    employe_id: int = Form(...),
    type_absence_id: int = Form(...),
    date_debut: str = Form(...),
    date_fin: str = Form(...),
    motif: str = Form(""),
    enregistre_par: str = Form(""),
    justifiee: str = Form(""),
):
    _exiger_rh(request)

    valeurs = {
        "employe_id": employe_id,
        "type_absence_id": type_absence_id,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "motif": motif,
        "enregistre_par": enregistre_par,
        "justifiee": bool(justifiee),
    }

    def erreur_rendue(msg):
        return templates.TemplateResponse(request, "formulaire_absence.html", {
            "employes": db.query(models.Employe).filter_by(statut="actif").order_by(models.Employe.nom).all(),
            "types_absence": db.query(models.TypeAbsence).filter(models.TypeAbsence.categorie.in_(["Permission", "Absence"])).order_by(models.TypeAbsence.categorie, models.TypeAbsence.libelle).all(),
            "valeurs": valeurs,
            "erreur": msg,
        }, status_code=400)

    # Vérifications
    employe = db.query(models.Employe).get(employe_id)
    if not employe:
        return erreur_rendue("Employé introuvable.")

    type_abs = db.query(models.TypeAbsence).get(type_absence_id)
    if not type_abs:
        return erreur_rendue("Type d'absence invalide.")

    # Vérification du genre requis (Maternité = F, Paternité = H)
    if type_abs.genre_requis and type_abs.genre_requis != employe.genre:
        return erreur_rendue(
            f"Ce type d'absence est réservé aux employés de genre "
            f"{'Féminin' if type_abs.genre_requis == 'F' else 'Masculin'}."
        )

    try:
        d_debut = date.fromisoformat(date_debut)
        d_fin = date.fromisoformat(date_fin)
    except ValueError:
        return erreur_rendue("Les dates saisies ne sont pas valides.")

    if d_fin < d_debut:
        return erreur_rendue("La date de fin doit être après la date de début.")

    # --- Calcul des jours déduits du congé ---
    nb_jours = (d_fin - d_debut).days + 1
    jours_deduits = 0

    # Règle 1 : Permissions avec plafond (ex: 3 jours)
    if type_abs.categorie == "Permission" and type_abs.plafond_jours:
        if nb_jours > type_abs.plafond_jours:
            jours_deduits = nb_jours - type_abs.plafond_jours

    # Règle 2 : Absence non justifiée → tout déduit
    if type_abs.code == "ABS_NON_JUSTIFIEE":
        jours_deduits = nb_jours

    # Règle 3 : Durée standard dépassée (Maternité, Paternité, ...)
    if type_abs.duree_standard_jours and nb_jours > type_abs.duree_standard_jours:
        depasse = nb_jours - type_abs.duree_standard_jours
        jours_deduits = max(jours_deduits, depasse)

    # Création de l'absence
    absence = models.Absence(
        employe_id=employe_id,
        type_absence_id=type_absence_id,
        date_debut=d_debut,
        date_fin=d_fin,
        motif=motif.strip() or None,
        justifiee=bool(justifiee),
        enregistre_par=enregistre_par.strip() or None,
        jours_deduits_conges=jours_deduits if jours_deduits > 0 else None,
    )
    db.add(absence)
    db.commit()

    # Message final
    message_txt = f"Absence enregistrée pour {employe.nom} {employe.prenom}."
    if jours_deduits > 0:
        message_txt += f" ⚠️ {jours_deduits} jour(s) seront déduits du congé annuel."
    message = quote(message_txt)

    return RedirectResponse(url=f"/absences?ok={message}", status_code=303)
@router.get("/absences/{absence_id}")
def detail_absence(
    absence_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _exiger_non_employe(request)

    absence = db.query(models.Absence).get(absence_id)
    if not absence:
        raise HTTPException(status_code=404, detail="Absence introuvable")

    return templates.TemplateResponse(request, "absence_detail.html", {
        "absence": absence,
        "role": request.session.get("role"),
    })

@router.post("/absences/{absence_id}/archiver")
def archiver_absence(
    absence_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _exiger_rh(request)
    absence = db.query(models.Absence).get(absence_id)
    if not absence:
        raise HTTPException(status_code=404, detail="Absence introuvable")

    absence.archivee = not absence.archivee
    db.commit()

    statut = "archivée" if absence.archivee else "réactivée"
    message = quote(f"Absence {statut}.")
    return RedirectResponse(url=f"/absences/{absence_id}?ok={message}", status_code=303)

@router.post("/absences/{absence_id}/justifier")
def justifier_absence(
    absence_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _exiger_rh(request)
    absence = db.query(models.Absence).get(absence_id)
    if not absence:
        raise HTTPException(status_code=404, detail="Absence introuvable")

    role = request.session.get("role")

    # Si on passe de non-justifiée à justifiée
    if not absence.justifiee:
        # Assistant RH doit avoir une pièce jointe
        if role == "Assistant RH" and not absence.justificatif_path:
            message = quote(
                "Vous ne pouvez pas marquer cette absence comme justifiée "
                "sans avoir au préalable uploadé un justificatif."
            )
            return RedirectResponse(url=f"/absences/{absence_id}?erreur={message}", status_code=303)

        absence.justifiee = True
        statut = "justifiée"
    else:
        # Déjustifier : libre
        absence.justifiee = False
        statut = "non justifiée"

    db.commit()
    message = quote(f"Absence marquée comme {statut}.")
    return RedirectResponse(url=f"/absences/{absence_id}?ok={message}", status_code=303)

@router.post("/absences/{absence_id}/justificatif")
async def upload_justificatif(
    absence_id: int,
    request: Request,
    db: Session = Depends(get_db),
    fichier: UploadFile = File(...),
):
    _exiger_rh(request)
    absence = db.query(models.Absence).get(absence_id)
    if not absence:
        raise HTTPException(status_code=404, detail="Absence introuvable")

    # Sauvegarde du fichier dans app/static/uploads/justificatifs/{absence_id}/
    chemin = _enregistrer_fichier(fichier, absence.employe_id, f"justif_{absence_id}")
    if chemin:
        absence.justificatif_path = chemin
        # Marquer aussi comme justifiée
        absence.justifiee = True
        db.commit()
        message = quote("Justificatif uploadé et absence marquée justifiée.")
    else:
        message = quote("Aucun fichier n'a été envoyé.")

    return RedirectResponse(url=f"/absences/{absence_id}?ok={message}", status_code=303)

@router.post("/absences/{absence_id}/supprimer")
def supprimer_absence(
    absence_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _exiger_chef_rh(request)
    absence = db.query(models.Absence).get(absence_id)
    if not absence:
        raise HTTPException(status_code=404, detail="Absence introuvable")

    # [CORRECTIF B10] Un congé annuel supprimé rend ses jours au solde de l'année.
    # (Les jours « déduits » d'une permission / absence disparaissent d'eux-mêmes : ils sont
    # recalculés à partir des absences existantes par _solde_conges.)
    if absence.type_absence and absence.type_absence.code == "CA":
        solde = db.query(models.SoldeConge).filter_by(employe_id=absence.employe_id, annee=absence.date_debut.year).first()
        if solde:
            jours = nb_jours_ouvrables(absence.date_debut, absence.date_fin)
            solde.jours_pris = max(float(solde.jours_pris or 0) - jours, 0)
            solde.jours_restants = max(float(solde.jours_alloues or 0) - float(solde.jours_pris), 0)

    db.delete(absence)
    db.commit()
    message = quote("Absence supprimée.")
    return RedirectResponse(url=f"/absences?ok={message}", status_code=303)



@router.get("/absences")
def liste_absences(
    request: Request,
    db: Session = Depends(get_db),
    q: str = "",
    agence_id: str = "",
    departement_id: str = "",
    sexe: str = "",
    tranche_age: str = "",
    embauche_debut: str = "",
    embauche_fin: str = "",
    type_absence_id: str = "",
    date_debut: str = "",
    date_fin: str = "",
    non_justifiees: str = "",
    masquer_archivees: str = "",
    periode: str = "en_cours",
):
    _exiger_lecture(request)

    # Filtres de base  ([CORRECTIF B15] ces variables étaient initialisées deux fois)
    dept_filtre = _entier_ou_none(departement_id)
    agence_filtre = _entier_ou_none(agence_id)
    type_filtre = _entier_ou_none(type_absence_id)
    date_debut_filtre = _date_ou_none(date_debut)
    date_fin_filtre = _date_ou_none(date_fin)
    embauche_debut_filtre = _date_ou_none(embauche_debut)
    embauche_fin_filtre = _date_ou_none(embauche_fin)

    query = (
        db.query(models.Absence)
        .join(models.Employe)
        .order_by(models.Absence.archivee, models.Absence.date_debut.desc())
    )

    # Filtre recherche nom/matricule
    if q:
        recherche = f"%{q}%"
        query = query.filter(
            models.Employe.nom.ilike(recherche)
            | models.Employe.prenom.ilike(recherche)
            | models.Employe.matricule.ilike(recherche)
        )

    # Filtre agence
    if agence_filtre:
        query = query.filter(models.Employe.agence_id == agence_filtre)

    # Filtre département
    if dept_filtre:
        query = query.filter(models.Employe.departement_id == dept_filtre)

    # Filtre sexe
    if sexe:
        query = query.filter(models.Employe.genre == sexe)

    # Filtre date d'embauche
    if embauche_debut_filtre:
        query = query.filter(models.Employe.date_embauche >= embauche_debut_filtre)
    if embauche_fin_filtre:
        query = query.filter(models.Employe.date_embauche <= embauche_fin_filtre)

    # Filtre type d'absence
    if type_filtre:
        query = query.filter(models.Absence.type_absence_id == type_filtre)

    # Filtre période d'absence
    if date_debut_filtre:
        query = query.filter(models.Absence.date_debut >= date_debut_filtre)
    if date_fin_filtre:
        query = query.filter(models.Absence.date_fin <= date_fin_filtre)

    absences = query.all()

    # Filtre tranche d'âge (côté Python car calculé)
    if tranche_age:
        absences = [a for a in absences if a.employe and _tranche_age(a.employe.date_naissance) == tranche_age]

    # Filtre justifiées uniquement
    if non_justifiees:
        absences = [a for a in absences if not a.justifiee]

    # Filtre masquer archivées
    if masquer_archivees:
        absences = [a for a in absences if not a.archivee]

    # Filtre par période  ([CORRECTIF B15] ce bloc était copié deux fois) (en cours / passées / toutes)
    aujourdhui_date = date.today()
    if periode == "en_cours":
        absences = [a for a in absences if a.date_debut and a.date_fin
                    and a.date_debut <= aujourdhui_date <= a.date_fin]
    elif periode == "passees":
        absences = [a for a in absences if a.date_fin and a.date_fin < aujourdhui_date]
    # "toutes" → pas de filtre

    # Groupement par agence
    absences_par_agence: dict[str, list] = {}
    for a in absences:
        nom_agence = a.employe.agence.nom if a.employe and a.employe.agence else "Direction Générale"
        absences_par_agence.setdefault(nom_agence, []).append(a)
    groupes = sorted(absences_par_agence.items(), key=lambda x: x[0])

    return templates.TemplateResponse(request, "absences.html", {
        "groupes": groupes,
        "total_absences": len(absences),
        "agences": db.query(models.Agence).order_by(models.Agence.nom).all(),
        "departements": db.query(models.Departement).order_by(models.Departement.nom).all(),
        "types_absence": db.query(models.TypeAbsence)
            .filter(models.TypeAbsence.categorie.in_(["Permission", "Absence"]))
            .order_by(models.TypeAbsence.categorie, models.TypeAbsence.libelle)
            .all(),
        "q": q,
        "agence_id": agence_id,
        "departement_id": departement_id,
        "sexe": sexe,
        "tranche_age": tranche_age,
        "embauche_debut": embauche_debut,
        "embauche_fin": embauche_fin,
        "type_absence_id": type_absence_id,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "non_justifiees": non_justifiees,
        "masquer_archivees": masquer_archivees,
        "periode": periode,
    })
