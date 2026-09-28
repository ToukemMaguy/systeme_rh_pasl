"""Demandes RH : dépôt, avis du N+1, décision RH, « Mes validations »."""
from datetime import date, datetime
from urllib.parse import quote
from fastapi import APIRouter, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..notifications import notifier_nouvelle_demande, notifier_avis_n_plus_1, email_employe
from .. import models
from ..calendrier import nb_jours_ouvrables, nb_jours_calendaires
from ..outils import _acces_refuse, _date_ou_none, _enregistrer_fichier, _entier_ou_none, _exiger_non_employe, _exiger_rh, _fmt_nombre, templates
from ..regles_rh import STATUTS_TRAITES, _enregistrer_jours_conge, _solde_conges, _tranche_age, sortir_des_effectifs

router = APIRouter()


# ============================================================
# DEMANDES RH
# ============================================================

def _contexte_reference_demande(db: Session) -> dict:
    return {
        "types_demande": db.query(models.TypeDemande).order_by(models.TypeDemande.id).all(),
        "employes": db.query(models.Employe).filter_by(statut="actif").order_by(models.Employe.nom).all(),
        "departements": db.query(models.Departement).order_by(models.Departement.nom).all(),
        "agences": db.query(models.Agence).order_by(models.Agence.nom).all(),
        "postes": db.query(models.Poste).order_by(models.Poste.intitule).all(),
        "utilisateurs": db.query(models.Utilisateur).order_by(models.Utilisateur.nom).all(),
        "employes_suppleants": db.query(models.Employe)
            .filter_by(statut="actif")
            .order_by(models.Employe.nom, models.Employe.prenom)
            .all(),
    }


@router.get("/demandes")
def liste_demandes(
    request: Request,
    db: Session = Depends(get_db),
    type: str = "",
    agence_id: str = "",
    departement_id: str = "",
    q: str = "",
    sexe: str = "",
    tranche_age: str = "",
    embauche_debut: str = "",
    embauche_fin: str = "",
):
    _exiger_non_employe(request)

    demandes = (
        db.query(models.DemandeRh)
        .order_by(models.DemandeRh.date_demande.desc())
        .all()
    )

    if type:
        demandes = [d for d in demandes if d.type_demande and d.type_demande.libelle == type]

    # Filtres sur l'employé concerné
    agence_filtre = _entier_ou_none(agence_id)
    departement_filtre = _entier_ou_none(departement_id)
    embauche_debut_filtre = _date_ou_none(embauche_debut)
    embauche_fin_filtre = _date_ou_none(embauche_fin)

    # Filtre recherche (nom/prénom/matricule de l'employé concerné)
    if q:
        recherche = q.lower()
        demandes = [
            d for d in demandes
            if d.employe_concerne and (
                recherche in (d.employe_concerne.nom or "").lower()
                or recherche in (d.employe_concerne.prenom or "").lower()
                or recherche in (d.employe_concerne.matricule or "").lower()
            )
        ]

    # Filtres agence / département / sexe / embauche
    if agence_filtre or departement_filtre or sexe or embauche_debut_filtre or embauche_fin_filtre:
        filtrees = []
        for d in demandes:
            emp = d.employe_concerne
            if not emp:
                continue
            if agence_filtre and emp.agence_id != agence_filtre:
                continue
            if departement_filtre and emp.departement_id != departement_filtre:
                continue
            if sexe and emp.genre != sexe:
                continue
            if embauche_debut_filtre and (not emp.date_embauche or emp.date_embauche < embauche_debut_filtre):
                continue
            if embauche_fin_filtre and (not emp.date_embauche or emp.date_embauche > embauche_fin_filtre):
                continue
            filtrees.append(d)
        demandes = filtrees

    # Filtre tranche d'âge
    if tranche_age:
        demandes = [
            d for d in demandes
            if d.employe_concerne and _tranche_age(d.employe_concerne.date_naissance) == tranche_age
        ]

    stats_agences = []
    for agence in db.query(models.Agence).order_by(models.Agence.nom).all():
        concernees = [d for d in demandes if d.employe_concerne and d.employe_concerne.agence_id == agence.id]
        if not concernees:
            continue
        par_type: dict[str, int] = {}
        demandeurs = set()
        for d in concernees:
            libelle = d.type_demande.libelle if d.type_demande else "Autre"
            par_type[libelle] = par_type.get(libelle, 0) + 1
            demandeurs.add(f"{d.employe_concerne.nom} {d.employe_concerne.prenom}")
        stats_agences.append({
            "agence": agence.nom,
            "total": len(concernees),
            "par_type": par_type,
            "demandeurs": sorted(demandeurs),
        })

    return templates.TemplateResponse(request, "liste_demandes.html", {
        "demandes": demandes,
        "stats_agences": stats_agences,
        "types_demande": db.query(models.TypeDemande).order_by(models.TypeDemande.id).all(),
        "agences": db.query(models.Agence).order_by(models.Agence.nom).all(),
        "departements": db.query(models.Departement).order_by(models.Departement.nom).all(),
        "type_selectionne": type,
        "agence_id": agence_id,
        "departement_id": departement_id,
        "q": q,
        "sexe": sexe,
        "tranche_age": tranche_age,
        "embauche_debut": embauche_debut,
        "embauche_fin": embauche_fin,
    })


@router.get("/demandes/nouvelle")
def formulaire_demande(request: Request, db: Session = Depends(get_db)):
    role = request.session.get("role")
    # Le Comité de direction et l'Administrateur ne peuvent pas déposer de demande
    if role in ("Comité de direction", "Administrateur"):
        _acces_refuse(request)

    return templates.TemplateResponse(request, "formulaire_demande.html", {
        "valeurs": {},
        "erreur": None,
        "types_absence_permission": db.query(models.TypeAbsence)
            .filter_by(categorie="Permission")
            .order_by(models.TypeAbsence.libelle)
            .all(),
        "types_absence_absence": db.query(models.TypeAbsence)
            .filter_by(categorie="Absence")
            .order_by(models.TypeAbsence.libelle)
            .all(),
        **_contexte_reference_demande(db),
    })


@router.post("/demandes/nouvelle")
async def creer_demande(
    request: Request,
    db: Session = Depends(get_db),
    type_demande_id: str = Form(""),
    demandeur_id: str = Form(""),  # ignoré : voir [CORRECTIF F1] ci-dessous
    employe_concerne_id: str = Form(""),
    commentaire: str = Form(""),
    date_debut_conge: str = Form(""),
    date_fin_conge: str = Form(""),
    poste_recherche_id: str = Form(""),
    departement_recherche_id: str = Form(""),
    nombre_postes: str = Form(""),
    nouveau_departement_id: str = Form(""),
    nouvelle_agence_id: str = Form(""),
    nouveau_poste_id: str = Form(""),
    date_effet_mutation: str = Form(""),
    date_depart: str = Form(""),
    type_depart: str = Form(""),
    permission_type_absence_id: str = Form(""),
    permission_date_debut: str = Form(""),
    permission_date_fin: str = Form(""),
    permission_motif: str = Form(""),
    permission_justificatif: UploadFile = File(None),
    absence_type_absence_id: str = Form(""),
    absence_date_debut: str = Form(""),
    absence_date_fin: str = Form(""),
    absence_motif: str = Form(""),
    absence_justificatif: UploadFile = File(None),
    suppleant_id: str = Form(""),
):
    role = request.session.get("role")
    if role in ("Comité de direction", "Administrateur"):
        _acces_refuse(request)

    # [CORRECTIF F1] Le demandeur et, pour un employé, l'employé concerné viennent de la SESSION,
    # jamais du formulaire : les champs cachés pouvaient être modifiés dans le navigateur pour
    # déposer une demande au nom d'un collègue.
    demandeur_id = request.session.get("user_id")
    if role == "Employé":
        employe_concerne_id = str(request.session.get("employe_id") or "")
        if not employe_concerne_id:
            _acces_refuse(request)

    valeurs = {
        "type_demande_id": _entier_ou_none(type_demande_id),
        "demandeur_id": demandeur_id,
        "employe_concerne_id": _entier_ou_none(employe_concerne_id),
        "commentaire": commentaire,
        "date_debut_conge": date_debut_conge, "date_fin_conge": date_fin_conge,
        "poste_recherche_id": _entier_ou_none(poste_recherche_id),
        "departement_recherche_id": _entier_ou_none(departement_recherche_id),
        "nombre_postes": nombre_postes,
        "nouveau_departement_id": _entier_ou_none(nouveau_departement_id),
        "nouvelle_agence_id": _entier_ou_none(nouvelle_agence_id),
        "nouveau_poste_id": _entier_ou_none(nouveau_poste_id),
        "date_effet_mutation": date_effet_mutation,
        "date_depart": date_depart, "type_depart": type_depart,
        "permission_type_absence_id": _entier_ou_none(permission_type_absence_id),
        "permission_date_debut": permission_date_debut,
        "permission_date_fin": permission_date_fin,
        "permission_motif": permission_motif,
        "absence_type_absence_id": _entier_ou_none(absence_type_absence_id),
        "absence_date_debut": absence_date_debut,
        "absence_date_fin": absence_date_fin,
        "absence_motif": absence_motif,
        "suppleant_id": _entier_ou_none(suppleant_id),
    }

    def erreur_rendue(message: str):
        return templates.TemplateResponse(request, "formulaire_demande.html", {
            "valeurs": valeurs, "erreur": message,
            "types_absence_permission": db.query(models.TypeAbsence).filter_by(categorie="Permission").order_by(models.TypeAbsence.libelle).all(),
            "types_absence_absence": db.query(models.TypeAbsence).filter_by(categorie="Absence").order_by(models.TypeAbsence.libelle).all(),
            **_contexte_reference_demande(db),
        }, status_code=400)

    if not type_demande_id:
        return erreur_rendue("Merci de choisir un type de demande.")

    # [CORRECTIF B11] Identifiants non numériques → message clair au lieu d'une erreur 500
    for brut in (type_demande_id, employe_concerne_id, suppleant_id, poste_recherche_id,
                 departement_recherche_id, nouveau_departement_id, nouvelle_agence_id, nouveau_poste_id,
                 permission_type_absence_id, absence_type_absence_id):
        if brut and _entier_ou_none(brut) is None:
            return erreur_rendue("Une des valeurs sélectionnées est invalide. Merci de recharger le formulaire.")
    if nombre_postes and (_entier_ou_none(nombre_postes) or 0) < 1:
        return erreur_rendue("Le nombre de postes doit être un nombre entier supérieur ou égal à 1.")

    # [CORRECTIF B12] Toutes les dates saisies doivent être de vraies dates (AAAA-MM-JJ).
    # Avant : elles étaient comparées comme du texte et enregistrées telles quelles, ce qui faisait
    # planter la validation RH plus tard.
    for brut in (date_debut_conge, date_fin_conge, date_effet_mutation, date_depart,
                 permission_date_debut, permission_date_fin, absence_date_debut, absence_date_fin):
        if brut and _date_ou_none(brut) is None:
            return erreur_rendue(f"La date « {brut} » n'est pas valide.")
    if employe_concerne_id and not db.query(models.Employe).get(int(employe_concerne_id)):
        return erreur_rendue("Employé concerné introuvable.")

    type_demande = db.query(models.TypeDemande).get(int(type_demande_id))
    if not type_demande:
        return erreur_rendue("Type de demande invalide.")

    if type_demande.libelle in ("Congé", "Mutation / Mouvement interne", "Départ", "Permission", "Absence") and not employe_concerne_id:
        return erreur_rendue("Merci de choisir l'employé concerné par cette demande.")

    if type_demande.libelle in ("Congé", "Permission", "Absence"):
        if not suppleant_id:
            return erreur_rendue("Merci de choisir un suppléant.")
        if int(suppleant_id) == int(employe_concerne_id or 0):
            return erreur_rendue("Le suppléant ne peut pas être l'employé lui-même.")

    donnees = {}

    if type_demande.libelle == "Congé":
        if not date_debut_conge or not date_fin_conge:
            return erreur_rendue("Merci de renseigner les deux dates du congé.")
        if date_fin_conge < date_debut_conge:
            return erreur_rendue("La date de fin du congé doit être après la date de début.")
        donnees = {"date_debut": date_debut_conge, "date_fin": date_fin_conge}

    elif type_demande.libelle == "Permission":
        if not permission_type_absence_id:
            return erreur_rendue("Merci de choisir un type de permission.")
        if not permission_date_debut or not permission_date_fin:
            return erreur_rendue("Merci de renseigner les deux dates de la permission.")
        if permission_date_fin < permission_date_debut:
            return erreur_rendue("La date de fin doit être après la date de début.")

        chemin_justif = None
        if permission_justificatif and permission_justificatif.filename:
            chemin_justif = _enregistrer_fichier(permission_justificatif, int(employe_concerne_id), "perm")

        donnees = {
            "type_absence_id": int(permission_type_absence_id),
            "date_debut": permission_date_debut,
            "date_fin": permission_date_fin,
            "motif": permission_motif,
            "justificatif_path": chemin_justif,
        }

    elif type_demande.libelle == "Absence":
        if not absence_type_absence_id:
            return erreur_rendue("Merci de choisir un type d'absence.")
        if not absence_date_debut or not absence_date_fin:
            return erreur_rendue("Merci de renseigner les deux dates de l'absence.")
        if absence_date_fin < absence_date_debut:
            return erreur_rendue("La date de fin doit être après la date de début.")

        chemin_justif = None
        if absence_justificatif and absence_justificatif.filename:
            chemin_justif = _enregistrer_fichier(absence_justificatif, int(employe_concerne_id), "abs")

        donnees = {
            "type_absence_id": int(absence_type_absence_id),
            "date_debut": absence_date_debut,
            "date_fin": absence_date_fin,
            "motif": absence_motif,
            "justificatif_path": chemin_justif,
        }

    elif type_demande.libelle == "Recrutement":
        if not poste_recherche_id:
            return erreur_rendue("Merci de préciser le poste recherché.")
        donnees = {
            "poste_recherche_id": int(poste_recherche_id),
            "departement_recherche_id": int(departement_recherche_id) if departement_recherche_id else None,
            "nombre_postes": int(nombre_postes) if nombre_postes else 1,
        }

    elif type_demande.libelle == "Mutation / Mouvement interne":
        if not (nouveau_departement_id or nouvelle_agence_id or nouveau_poste_id):
            return erreur_rendue("Merci de préciser au moins un changement (département, agence ou poste).")
        donnees = {
            "nouveau_departement_id": int(nouveau_departement_id) if nouveau_departement_id else None,
            "nouvelle_agence_id": int(nouvelle_agence_id) if nouvelle_agence_id else None,
            "nouveau_poste_id": int(nouveau_poste_id) if nouveau_poste_id else None,
            "date_effet": date_effet_mutation or None,
        }

    elif type_demande.libelle == "Départ":
        if not date_depart or not type_depart:
            return erreur_rendue("Merci de renseigner la date et le type de départ.")
        donnees = {"date_depart": date_depart, "type_depart": type_depart}

    statut_initial = "en_attente_n_plus_1"
    p_debut = None
    p_fin = None

    if type_demande.libelle == "Congé":
        if date_debut_conge:
            try: p_debut = date.fromisoformat(date_debut_conge)
            except ValueError: pass
        if date_fin_conge:
            try: p_fin = date.fromisoformat(date_fin_conge)
            except ValueError: pass
    elif type_demande.libelle == "Permission":
        if permission_date_debut:
            try: p_debut = date.fromisoformat(permission_date_debut)
            except ValueError: pass
        if permission_date_fin:
            try: p_fin = date.fromisoformat(permission_date_fin)
            except ValueError: pass
    elif type_demande.libelle == "Absence":
        if absence_date_debut:
            try: p_debut = date.fromisoformat(absence_date_debut)
            except ValueError: pass
        if absence_date_fin:
            try: p_fin = date.fromisoformat(absence_date_fin)
            except ValueError: pass
    elif type_demande.libelle == "Départ":
        if date_depart:
            try: p_debut = date.fromisoformat(date_depart)
            except ValueError: pass
    elif type_demande.libelle == "Mutation / Mouvement interne":
        if date_effet_mutation:
            try: p_debut = date.fromisoformat(date_effet_mutation)
            except ValueError: pass

    demande = models.DemandeRh(
        type_demande_id=type_demande.id,
        employe_concerne_id=int(employe_concerne_id) if employe_concerne_id else None,
        demandeur_id=demandeur_id,
        commentaire=commentaire or None,
        donnees_specifiques=donnees,
        statut=statut_initial,
        suppleant_id=int(suppleant_id) if suppleant_id else None,
        periode_sollicitee_debut=p_debut,
        periode_sollicitee_fin=p_fin,
    )
    db.add(demande)
    db.flush()  # attribue un numéro à la demande (utilisé dans les mails)
    notifier_nouvelle_demande(db, demande)  # [LOT 1 - POINT 18] mail au N+1 (ou à la RH)
    db.commit()

    message = quote(f"Demande de {type_demande.libelle.lower()} envoyée.")
    return RedirectResponse(url=f"/demandes?ok={message}", status_code=303)


def _type_absence_conge(db: Session) -> models.TypeAbsence:
    type_absence = db.query(models.TypeAbsence).filter_by(code="CA").first()
    if not type_absence:
        type_absence = models.TypeAbsence(code="CA", libelle="Congé annuel")
        db.add(type_absence)
        db.flush()
    return type_absence


@router.get("/demandes/{demande_id}/avis")
def formulaire_avis_n_plus_1(demande_id: int, request: Request, db: Session = Depends(get_db)):
    """Formulaire pour que le N+1 donne son avis."""
    employe_id = request.session.get("employe_id")
    if not employe_id:
        _acces_refuse(request)

    demande = db.query(models.DemandeRh).get(demande_id)
    if not demande:
        raise HTTPException(status_code=404, detail="Demande introuvable")

    # Vérifier que je suis bien le N+1 de l'employé concerné
    employe_concerne = demande.employe_concerne
    if not employe_concerne or employe_concerne.n_plus_1_id != employe_id:
        _acces_refuse(request)

    if demande.statut != "en_attente_n_plus_1":
        message = quote("Cette demande n'est plus en attente de votre avis.")
        return RedirectResponse(url=f"/mes-validations?erreur={message}", status_code=303)

    types_demande_map = {t.id: t.libelle for t in db.query(models.TypeDemande).all()}

    return templates.TemplateResponse(request, "formulaire_avis_n_plus_1.html", {
        "demande": demande,
        "type_libelle": types_demande_map.get(demande.type_demande_id, "—"),
        "erreur": None,
    })
@router.post("/demandes/{demande_id}/avis-n-plus-1")
def donner_avis_n_plus_1(
    demande_id: int,
    request: Request,
    db: Session = Depends(get_db),
    avis: str = Form(...),
    commentaire: str = Form(""),
    periode_accordee_debut: str = Form(""),
    periode_accordee_fin: str = Form(""),
):
    """Le N+1 donne son avis : favorable ou defavorable."""
    role = request.session.get("role")
    employe_id = request.session.get("employe_id")

    if not employe_id:
        _acces_refuse(request)

    demande = db.query(models.DemandeRh).get(demande_id)
    if not demande:
        raise HTTPException(status_code=404, detail="Demande introuvable")

    # Vérifier que je suis bien le N+1 de l'employé concerné
    employe_concerne = demande.employe_concerne
    if not employe_concerne or employe_concerne.n_plus_1_id != employe_id:
        _acces_refuse(request)

    # Vérifier que la demande est bien en attente de mon avis
    if demande.statut != "en_attente_n_plus_1":
        message = quote("Cette demande n'est plus en attente de votre avis.")
        return RedirectResponse(url=f"/mes-validations?erreur={message}", status_code=303)

    if avis not in ("favorable", "defavorable"):
        message = quote("Avis invalide.")
        return RedirectResponse(url=f"/mes-validations?erreur={message}", status_code=303)

    # Enregistrer l'avis
    demande.avis_n_plus_1 = avis
    demande.commentaire_n_plus_1 = commentaire.strip() or None
    demande.date_avis_n_plus_1 = datetime.now()

    if avis == "favorable":
        # Statut suivant : en attente RH
        demande.statut = "en_attente_rh"

        # Enregistrer la période accordée (si modifiée par le N+1)
        if periode_accordee_debut:
            try:
                demande.periode_accordee_debut = date.fromisoformat(periode_accordee_debut)
            except ValueError:
                pass
        if periode_accordee_fin:
            try:
                demande.periode_accordee_fin = date.fromisoformat(periode_accordee_fin)
            except ValueError:
                pass

        # Si non modifiées, on copie les périodes sollicitées
        if not demande.periode_accordee_debut:
            demande.periode_accordee_debut = demande.periode_sollicitee_debut
        if not demande.periode_accordee_fin:
            demande.periode_accordee_fin = demande.periode_sollicitee_fin

        message = quote("Avis favorable enregistré. La demande est transmise aux RH.")
    else:
        # Refus définitif
        demande.statut = "refusee_n_plus_1"
        message = quote("Avis défavorable enregistré. La demande est refusée.")

    notifier_avis_n_plus_1(db, demande, avis)  # [LOT 1 - POINT 18] mail à la RH ou à l'employé
    db.commit()
    return RedirectResponse(url=f"/mes-validations?ok={message}", status_code=303)
# ============================================================
# DÉCISION RH — logique unique
# ------------------------------------------------------------
# [CORRECTIF B1 + B4 + B5]
# Avant : deux routes (/traiter-rh et /statut) validaient les demandes avec deux logiques
# différentes. /traiter-rh ne vérifiait pas le solde, ne désactivait pas l'employé lors d'un
# départ et n'appliquait pas les mutations ; /statut ne bloquait pas une double validation
# (double décompte du congé). Les mails étaient en plus mis deux fois en file d'attente.
# Maintenant : les deux routes appellent _appliquer_decision_rh(), qui fait tout, une seule fois.
# ============================================================

def _calcul_jours_deduits(type_abs, nb_jours: int) -> int:
    """Jours à retirer du congé annuel pour une permission / absence (mêmes règles qu'avant)."""
    jours_deduits = 0
    # Règle 1 : permissions avec plafond
    if type_abs.categorie == "Permission" and type_abs.plafond_jours and nb_jours > type_abs.plafond_jours:
        jours_deduits = nb_jours - type_abs.plafond_jours
    # Règle 2 : absence non justifiée → tout est déduit
    if type_abs.code == "ABS_NON_JUSTIFIEE":
        jours_deduits = nb_jours
    # Règle 3 : durée standard dépassée (maternité, paternité...)
    if type_abs.duree_standard_jours and nb_jours > type_abs.duree_standard_jours:
        jours_deduits = max(jours_deduits, nb_jours - type_abs.duree_standard_jours)
    return jours_deduits


def _creer_absence_depuis_demande(demande, db, request):
    """Crée l'absence correspondant à une demande validée (Congé / Permission / Absence).
    Pour un congé, les jours sont aussi ajoutés au solde de l'année."""
    donnees = demande.donnees_specifiques or {}
    employe = demande.employe_concerne
    if not employe:
        return

    type_lib = demande.type_demande.libelle
    if type_lib == "Congé":
        type_abs = _type_absence_conge(db)
    elif donnees.get("type_absence_id"):
        type_abs = db.query(models.TypeAbsence).get(donnees["type_absence_id"])
    else:
        type_abs = None
    date_debut = demande.periode_accordee_debut or _date_ou_none(donnees.get("date_debut") or "")
    date_fin = demande.periode_accordee_fin or _date_ou_none(donnees.get("date_fin") or "")
    if not type_abs or not date_debut or not date_fin:
        return

    nb_jours = nb_jours_calendaires(date_debut, date_fin)

    if type_lib == "Congé":
        nb_jours = nb_jours_ouvrables(date_debut, date_fin)  # [CORRECTIF B9]
        jours_deduits = 0  # un congé est décompté via solde_conges, pas via jours_deduits_conges
        _enregistrer_jours_conge(db, employe.id, date_debut.year, nb_jours)
    else:
        jours_deduits = _calcul_jours_deduits(type_abs, nb_jours)

    # Justification : pièce jointe fournie, ou validation par le Chef RH
    a_justificatif = bool(donnees.get("justificatif_path"))
    justifiee = a_justificatif or request.session.get("role") == "Chef RH"

    db.add(models.Absence(
        employe_id=employe.id,
        type_absence_id=type_abs.id,
        date_debut=date_debut,
        date_fin=date_fin,
        motif=donnees.get("motif") or demande.commentaire,
        justifiee=justifiee,
        justificatif_path=donnees.get("justificatif_path"),
        enregistre_par=request.session.get("nom"),
        jours_deduits_conges=jours_deduits if jours_deduits > 0 else None,
    ))


def _appliquer_depart(demande, db):
    """Départ validé : enregistrement du départ.
    [LOT 1 - POINT 4] Si la date de départ est arrivée : sortie des effectifs immédiate (statut inactif,
    affectation clôturée, comptes désactivés). Si elle est future : l'employé reste actif (il travaille
    encore) et la sortie se fera automatiquement à cette date (voir regles_rh.appliquer_departs_echus).
    Avant : l'employé passait inactif dès la validation, même pour un départ prévu dans un mois."""
    donnees = demande.donnees_specifiques or {}
    employe = demande.employe_concerne
    if not employe:
        return
    date_depart_effet = _date_ou_none(donnees.get("date_depart") or "") or date.today()
    depart = models.Depart(
        employe_id=employe.id,
        date_depart=date_depart_effet,
        motif=demande.commentaire,
        type_depart=donnees.get("type_depart"),
    )
    db.add(depart)
    if date_depart_effet <= date.today():
        sortir_des_effectifs(db, employe, depart)


def _appliquer_mutation(demande, db):
    """Mutation validée : mise à jour de l'employé + nouvelle ligne d'historique."""
    donnees = demande.donnees_specifiques or {}
    employe = demande.employe_concerne
    if not employe:
        return
    date_effet = _date_ou_none(donnees.get("date_effet") or "") or date.today()

    employe.departement_id = donnees.get("nouveau_departement_id") or employe.departement_id
    employe.agence_id = donnees.get("nouvelle_agence_id") or employe.agence_id
    employe.poste_id = donnees.get("nouveau_poste_id") or employe.poste_id

    affectation_ouverte = db.query(models.Affectation).filter_by(employe_id=employe.id, date_fin=None).first()
    if affectation_ouverte:
        affectation_ouverte.date_fin = date_effet
    db.add(models.Affectation(
        employe_id=employe.id,
        departement_id=employe.departement_id,
        agence_id=employe.agence_id,
        poste_id=employe.poste_id,
        grade_id=employe.grade_id,
        date_debut=date_effet,
        type_mouvement="mutation",
        motif=demande.commentaire,
    ))


def _mettre_mails_en_file(demande, action: str, db):
    """[CORRECTIF B1] Prépare les mails UNE seule fois (le bloc était dupliqué → mails envoyés en double)."""
    employe = demande.employe_concerne
    if not employe:
        return
    type_libelle = demande.type_demande.libelle if demande.type_demande else "demande"
    date_debut_txt = demande.periode_accordee_debut.strftime("%d/%m/%Y") if demande.periode_accordee_debut else ""
    date_fin_txt = demande.periode_accordee_fin.strftime("%d/%m/%Y") if demande.periode_accordee_fin else ""
    signature = "\nCordialement,\nLe service RH — PASL Cameroun\n"

    if action == "valider":
        # Mail au suppléant
        if demande.suppleant and email_employe(demande.suppleant):
            db.add(models.MailAEnvoyer(
                destinataire=email_employe(demande.suppleant),
                sujet=f"[PASL-RH] Vous êtes suppléant de {employe.nom} {employe.prenom}",
                corps=(
                    f"Bonjour {demande.suppleant.prenom},\n\n"
                    f"{employe.nom} {employe.prenom} sera absent(e) du {date_debut_txt} au {date_fin_txt}.\n\n"
                    f"Vous avez été désigné(e) comme suppléant(e) pour cette période.\n\n"
                    f"Type de demande : {type_libelle}\n"
                    f"Motif : {demande.commentaire or 'Non renseigné'}\n\n"
                    f"Merci de prendre les dispositions nécessaires.\n" + signature
                ),
                demande_id=demande.id,
                type_mail="notif_suppleant",
            ))
        # Mail à l'employé
        if email_employe(employe):  # [LOT 1 - POINT 18] adresse pro en priorité
            corps = (
                f"Bonjour {employe.prenom},\n\n"
                f"Votre demande de {type_libelle.lower()} a été validée.\n\n"
            )
            if date_debut_txt and date_fin_txt:
                corps += f"Période accordée : du {date_debut_txt} au {date_fin_txt}\n"
            if demande.suppleant:
                corps += f"Suppléant désigné : {demande.suppleant.nom} {demande.suppleant.prenom}\n"
            db.add(models.MailAEnvoyer(
                destinataire=email_employe(employe),
                sujet=f"[PASL-RH] Votre demande de {type_libelle.lower()} a été validée",
                corps=corps + signature,
                demande_id=demande.id,
                type_mail="notif_employe_valide",
            ))
    elif email_employe(employe):  # [LOT 1 - POINT 18] adresse pro en priorité
        db.add(models.MailAEnvoyer(
            destinataire=email_employe(employe),
            sujet=f"[PASL-RH] Votre demande de {type_libelle.lower()} a été refusée",
            corps=(
                f"Bonjour {employe.prenom},\n\n"
                f"Votre demande de {type_libelle.lower()} a été refusée.\n\n"
                f"Motif : {demande.commentaire or 'Non précisé'}\n\n"
                f"Vous pouvez consulter le détail dans votre espace personnel sur PASL-RH.\n" + signature
            ),
            demande_id=demande.id,
            type_mail="notif_employe_refuse",
        ))


def _appliquer_decision_rh(demande, action: str, db: Session, request: Request,
                           periode_accordee_debut: str = "", periode_accordee_fin: str = "",
                           commentaire_rh: str = "") -> str | None:
    """Applique la décision RH (valider / refuser). Retourne un message d'erreur, ou None si tout va bien.
    Aucune modification n'est faite en base avant que toutes les vérifications soient passées."""

    # --- 1. Vérifications (rien n'est modifié tant qu'elles ne sont pas toutes passées) ---
    if demande.statut == "refusee_n_plus_1":
        return "Cette demande a été refusée par le N+1. Le refus est définitif."
    if demande.statut in STATUTS_TRAITES:
        # [CORRECTIF B5] empêche la double validation (double-clic, retour arrière, 2e onglet...)
        return "Cette demande a déjà été traitée."
    if action not in ("valider", "refuser"):
        return "Action invalide."

    type_lib = demande.type_demande.libelle if demande.type_demande else ""
    if action == "valider" and type_lib == "Départ" and request.session.get("role") != "Chef RH":
        # [CORRECTIF B4] la règle « seul le Chef RH valide un départ » s'applique aux deux routes
        return "Seul le Chef RH peut valider un départ."

    debut = _date_ou_none(periode_accordee_debut) or demande.periode_accordee_debut or demande.periode_sollicitee_debut
    fin = _date_ou_none(periode_accordee_fin) or demande.periode_accordee_fin or demande.periode_sollicitee_fin
    if action == "valider" and debut and fin and fin < debut:
        return "La date de fin de la période accordée doit être après la date de début."

    if action == "valider" and type_lib == "Congé":
        # [CORRECTIF B4] le contrôle du solde s'applique aussi au formulaire RH
        if not debut or not fin:
            return "Les dates du congé sont manquantes : impossible de valider."
        employe = demande.employe_concerne
        nb_jours = nb_jours_ouvrables(debut, fin)  # [CORRECTIF B9] dimanches et jours fériés exclus
        if nb_jours == 0:
            return "La période accordée ne contient aucun jour ouvrable (dimanches / jours fériés uniquement)."
        restant = _solde_conges(db, employe, debut)["total_restant"] if employe else 0
        if restant < nb_jours:
            return (f"Solde insuffisant : {_fmt_nombre(restant)} jour(s) disponible(s) (cumul depuis l'embauche) "
                    f"pour {nb_jours} jour(s) ouvrable(s) demandé(s). Renégociez la période avec l'employé ou refusez la demande.")

    # --- 2. Enregistrement de la décision ---
    if demande.statut == "en_attente_n_plus_1":
        # La RH tranche sans attendre le N+1 : on le trace
        demande.avis_n_plus_1 = "favorable"
        demande.commentaire_n_plus_1 = "Intervention directe de la RH"
        demande.date_avis_n_plus_1 = datetime.now()

    prefixe = "[RH]" if action == "valider" else "[RH - Refus]"
    if commentaire_rh.strip():
        ajout = f"{prefixe} {commentaire_rh.strip()}"
        demande.commentaire = f"{demande.commentaire}\n\n{ajout}" if demande.commentaire else ajout

    demande.valide_par_id = request.session.get("user_id")
    demande.date_validation = datetime.now()

    if action == "valider":
        demande.periode_accordee_debut = debut
        demande.periode_accordee_fin = fin
        demande.statut = "validee"
        # --- 3. Conséquences selon le type de demande ---
        if type_lib in ("Congé", "Permission", "Absence"):
            _creer_absence_depuis_demande(demande, db, request)
        elif type_lib == "Départ":
            _appliquer_depart(demande, db)
        elif type_lib == "Mutation / Mouvement interne":
            _appliquer_mutation(demande, db)
    else:
        demande.statut = "refusee"

    # --- 4. Notifications (une seule fois) ---
    _mettre_mails_en_file(demande, action, db)
    return None


@router.get("/demandes/{demande_id}/traiter-rh")
def traiter_demande_rh(demande_id: int, request: Request, db: Session = Depends(get_db)):
    """Formulaire RH pour ajuster la période et valider/refuser une demande."""
    _exiger_rh(request)

    demande = db.query(models.DemandeRh).get(demande_id)
    if not demande:
        raise HTTPException(status_code=404, detail="Demande introuvable")

    # Vérifier que le N+1 n'a pas refusé (définitif)
    if demande.statut == "refusee_n_plus_1":
        message = quote("Cette demande a été refusée par le N+1. Le refus est définitif.")
        return RedirectResponse(url=f"/demandes?erreur={message}", status_code=303)

    # Vérifier que la demande n'est pas déjà traitée
    if demande.statut in ("validee", "refusee"):
        message = quote("Cette demande a déjà été traitée.")
        return RedirectResponse(url=f"/demandes?erreur={message}", status_code=303)

    types_demande_map = {t.id: t.libelle for t in db.query(models.TypeDemande).all()}

    return templates.TemplateResponse(request, "traiter_demande_rh.html", {
        "demande": demande,
        "type_libelle": types_demande_map.get(demande.type_demande_id, "—"),
        "erreur": None,
    })


@router.post("/demandes/{demande_id}/traiter-rh")
def traiter_demande_rh_post(
    demande_id: int,
    request: Request,
    db: Session = Depends(get_db),
    action: str = Form(...),
    periode_accordee_debut: str = Form(""),
    periode_accordee_fin: str = Form(""),
    commentaire_rh: str = Form(""),
):
    """Décision finale de la RH depuis le formulaire complet (avec ajustement de la période)."""
    _exiger_rh(request)
    demande = db.query(models.DemandeRh).get(demande_id)
    if not demande:
        raise HTTPException(status_code=404, detail="Demande introuvable")

    erreur = _appliquer_decision_rh(demande, action, db, request,
                                    periode_accordee_debut, periode_accordee_fin, commentaire_rh)
    if erreur:
        db.rollback()
        return RedirectResponse(url=f"/demandes?erreur={quote(erreur)}", status_code=303)

    db.commit()
    message = quote(f"Demande {'validée' if action == 'valider' else 'refusée'}.")
    return RedirectResponse(url=f"/demandes?ok={message}", status_code=303)


@router.post("/demandes/{demande_id}/statut")
def changer_statut_demande(
    demande_id: int,
    request: Request,
    db: Session = Depends(get_db),
    nouveau_statut: str = Form(...),
):
    """Raccourci Valider / Refuser (sans formulaire). Même logique que /traiter-rh."""
    _exiger_rh(request)
    demande = db.query(models.DemandeRh).get(demande_id)
    if not demande:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    actions = {"validee": "valider", "refusee": "refuser"}
    if nouveau_statut not in actions:
        raise HTTPException(status_code=400, detail="Statut invalide")

    erreur = _appliquer_decision_rh(demande, actions[nouveau_statut], db, request)
    if erreur:
        db.rollback()
        return RedirectResponse(url=f"/demandes?erreur={quote(erreur)}", status_code=303)

    db.commit()
    return RedirectResponse(url=f"/demandes?ok={quote('Statut mis à jour.')}", status_code=303)

@router.get("/mes-validations")
def mes_validations(request: Request, db: Session = Depends(get_db)):
    """Espace du N+1 : liste des demandes de ses subordonnés en attente de son avis."""
    role = request.session.get("role")
    if role == "Employé":
        # Un employé n'a pas de N-1, sauf s'il est chef d'équipe (mais on simplifie)
        # On vérifie quand même s'il est N+1 de quelqu'un
        employe_id = request.session.get("employe_id")
        if not employe_id:
            _acces_refuse(request)
    else:
        employe_id = request.session.get("employe_id")

    if not employe_id:
        _acces_refuse(request)

    # Sous-employés (N-1) dont je suis le N+1
    mes_n_moins_1 = (
        db.query(models.Employe)
        .filter_by(n_plus_1_id=employe_id, statut="actif")
        .all()
    )
    ids_n_moins_1 = [e.id for e in mes_n_moins_1]

    # Demandes de mes N-1 en attente de mon avis
    demandes_a_valider = []
    if ids_n_moins_1:
        demandes_a_valider = (
            db.query(models.DemandeRh)
            .filter(models.DemandeRh.employe_concerne_id.in_(ids_n_moins_1))
            .filter(models.DemandeRh.statut == "en_attente_n_plus_1")
            .order_by(models.DemandeRh.date_demande.desc())
            .all()
        )

    # Demandes déjà traitées par moi (historique)
    demandes_traitees = []
    if ids_n_moins_1:
        demandes_traitees = (
            db.query(models.DemandeRh)
            .filter(models.DemandeRh.employe_concerne_id.in_(ids_n_moins_1))
            .filter(models.DemandeRh.avis_n_plus_1.in_(["favorable", "defavorable"]))
            .order_by(models.DemandeRh.date_avis_n_plus_1.desc())
            .limit(10)
            .all()
        )

    # Liste des types de demande pour l'affichage
    types_demande_map = {t.id: t.libelle for t in db.query(models.TypeDemande).all()}

    return templates.TemplateResponse(request, "mes_validations.html", {
        "demandes_a_valider": demandes_a_valider,
        "demandes_traitees": demandes_traitees,
        "mes_n_moins_1": mes_n_moins_1,
        "types_demande_map": types_demande_map,
    })
