"""Employés : liste, création, modification, fiche, sanctions, documents PDF."""
from datetime import date, timedelta
from urllib.parse import quote
from fastapi import APIRouter, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from ..database import get_db
from .. import models
from .. import pdf as pdf_module
from ..outils import verifier_fichier, _date_ou_none, _email_valide, _enregistrer_fichier, _entier_ou_none, _exiger_chef_rh, _exiger_lecture, _exiger_non_employe, _exiger_rh, _valider_saisies_employe, templates
from ..regles_rh import AGE_RETRAITE, DG_ID, contexte_fiche_pdf, date_retraite, _age_annees, _anciennete, _employe_ou_404, _historique_employe, _solde_conges, _tranche_age, _valeurs_depuis_employe

router = APIRouter()


# ============================================================
# EMPLOYÉS — helpers
# ============================================================

def _contexte_reference_employe(db: Session, employe_id_exclu: int | None = None) -> dict:
    """Fournit les référentiels pour le formulaire employé."""
    query_n1 = db.query(models.Employe).filter_by(statut="actif")
    if employe_id_exclu:
        query_n1 = query_n1.filter(models.Employe.id != employe_id_exclu)
    n_plus_1_possibles = query_n1.order_by(models.Employe.nom, models.Employe.prenom).all()

    # [N+1 — tri par niveau, NON bloquant] Les grades PASL sont encore provisoires (la RH les
    # redéfinira elle-même une fois l'application en main) : on ne s'en sert donc jamais pour
    # interdire un choix de N+1, seulement pour faire remonter en premier les profils les plus
    # gradés dans la liste déroulante. Un grade absent ou mal calibré ne fait jamais planter ni
    # bloquer le choix — au pire l'ordre d'affichage est juste sous-optimal.
    n_plus_1_possibles = sorted(
        n_plus_1_possibles,
        key=lambda e: (
            -(e.grade.niveau_hierarchique if e.grade and e.grade.niveau_hierarchique is not None else -1),
            e.nom or "", e.prenom or "",
        ),
    )

    # On prépare la liste des N+1 avec leur département pour le filtrage JS
    n_plus_1_data = [
        {
            "id": e.id,
            "nom": e.nom,
            "prenom": e.prenom,
            "matricule": e.matricule or "",
            "poste": e.poste.intitule if e.poste else "",
            "departement_id": e.departement_id,
            # Pour le tri d'affichage côté JS uniquement — jamais utilisé pour bloquer un choix.
            "niveau_hierarchique": (
                e.grade.niveau_hierarchique if e.grade and e.grade.niveau_hierarchique is not None else None
            ),
        }
        for e in n_plus_1_possibles
    ]

    # Exception DG : on transmet son id au template pour qu'il apparaisse
    # toujours dans la liste N+1, quel que soit le département sélectionné.
    dg_existe = db.query(models.Employe.id).filter_by(id=DG_ID).first() is not None

    return {
        "departements": db.query(models.Departement).order_by(models.Departement.nom).all(),
        "agences": db.query(models.Agence).order_by(models.Agence.nom).all(),
        "postes": db.query(models.Poste).order_by(models.Poste.intitule).all(),
        "grades": db.query(models.Grade).order_by(models.Grade.niveau_hierarchique).all(),
        "n_plus_1_possibles": n_plus_1_possibles,
        "n_plus_1_data": n_plus_1_data,
        "dg_id": DG_ID if dg_existe else None,
    }

# ------------------------------------------------------------------
# Fiche signalétique : 7 champs administratifs facultatifs, communs à la création et à la modification
# ------------------------------------------------------------------
def _infos_signaletiques(
    lieu_naissance: str = Form(""),
    nationalite: str = Form(""),
    numero_cni: str = Form(""),
    cni_delivree_le: str = Form(""),
    adresse: str = Form(""),
    numero_cnps: str = Form(""),
    niveau_etudes: str = Form(""),
) -> dict:
    """Saisie brute (réaffichée telle quelle en cas d'erreur dans le formulaire)."""
    return {
        "lieu_naissance": lieu_naissance.strip(), "nationalite": nationalite.strip(),
        "numero_cni": numero_cni.strip(), "cni_delivree_le": cni_delivree_le.strip(),
        "adresse": adresse.strip(), "numero_cnps": numero_cnps.strip(), "niveau_etudes": niveau_etudes.strip(),
    }


def _erreur_infos_signaletiques(infos: dict) -> str | None:
    if infos["cni_delivree_le"]:
        delivree = _date_ou_none(infos["cni_delivree_le"])
        if not delivree:
            return "La date de délivrance de la CNI n'est pas valide."
        if delivree > date.today():
            return "La date de délivrance de la CNI ne peut pas être dans le futur."
    return None


def _appliquer_infos_signaletiques(employe: models.Employe, infos: dict) -> None:
    for champ in ("lieu_naissance", "nationalite", "numero_cni", "adresse", "numero_cnps", "niveau_etudes"):
        setattr(employe, champ, infos[champ] or None)
    employe.cni_delivree_le = _date_ou_none(infos["cni_delivree_le"])


def _valider_donnees_employe(genre: str, date_embauche: str, date_naissance: str = "") -> str | None:
    if genre not in ("H", "F"):
        return "Le genre doit être 'H' (Homme) ou 'F' (Femme)."
    try:
        embauche = date.fromisoformat(date_embauche)
    except ValueError:
        return "La date d'embauche n'est pas valide."
    if date_naissance:
        try:
            naissance = date.fromisoformat(date_naissance)
        except ValueError:
            return "La date de naissance n'est pas valide."
        if naissance >= embauche:
            return "La date de naissance doit être antérieure à la date d'embauche."
        age = (date.today() - naissance).days // 365
        if age < 16:
            return "La date de naissance indique un âge inférieur à 16 ans."
    return None


# ============================================================
# EMPLOYÉS — routes
# ============================================================

@router.get("/employes")
def liste_employes(
    request: Request,
    q: str = "",
    departement_id: str = "",
    agence_id: str = "",
    sexe: str = "",
    tranche_age: str = "",
    embauche_debut: str = "",
    embauche_fin: str = "",
    db: Session = Depends(get_db),
):
    _exiger_non_employe(request)

    dept_filtre = _entier_ou_none(departement_id)
    agence_filtre = _entier_ou_none(agence_id)
    embauche_debut_filtre = _date_ou_none(embauche_debut)
    embauche_fin_filtre = _date_ou_none(embauche_fin)

    query = db.query(models.Employe).filter_by(statut="actif")
    if q:
        recherche = f"%{q}%"
        query = query.filter(
            models.Employe.nom.ilike(recherche)
            | models.Employe.prenom.ilike(recherche)
            | models.Employe.matricule.ilike(recherche)
        )
    if dept_filtre:
        query = query.filter(models.Employe.departement_id == dept_filtre)
    if agence_filtre:
        query = query.filter(models.Employe.agence_id == agence_filtre)
    if sexe:
        query = query.filter(models.Employe.genre == sexe)
    if embauche_debut_filtre:
        query = query.filter(models.Employe.date_embauche >= embauche_debut_filtre)
    if embauche_fin_filtre:
        query = query.filter(models.Employe.date_embauche <= embauche_fin_filtre)

    employes = query.order_by(models.Employe.nom, models.Employe.prenom).all()

    if tranche_age:
        employes = [e for e in employes if _tranche_age(e.date_naissance) == tranche_age]

    groupes: dict[str, list] = {}
    for e in employes:
        cle = e.agence.nom if e.agence else "Siège"
        groupes.setdefault(cle, []).append(e)
    agences_groupees = sorted(groupes.items(), key=lambda x: (x[0] != "Siège", x[0]))

    return templates.TemplateResponse(request, "liste_employes.html", {
        "agences_groupees": agences_groupees,
        "total_actifs": len(employes),
        "age_annees": _age_annees,
        "q": q, "departement_id": departement_id, "agence_id": agence_id,
        "sexe": sexe, "tranche_age": tranche_age,
        "embauche_debut": embauche_debut, "embauche_fin": embauche_fin,
        "departements": db.query(models.Departement).order_by(models.Departement.nom).all(),
        "agences": db.query(models.Agence).order_by(models.Agence.nom).all(),
    })


@router.get("/employes/nouveau")
def formulaire_employe(request: Request, db: Session = Depends(get_db)):
    _exiger_rh(request)
    return templates.TemplateResponse(request, "formulaire_employe.html", {
        "mode": "creation",
        "valeurs": {},
        "employe_id": None,
        "erreur": None,
        **_contexte_reference_employe(db),
    })


@router.post("/employes/nouveau")
def creer_employe(
    request: Request,
    db: Session = Depends(get_db),
    nom: str = Form(...),
    prenom: str = Form(...),
    genre: str = Form(...),
    date_embauche: str = Form(...),
    date_naissance: str = Form(""),
    matricule: str = Form(""),
    departement_id: int = Form(...),
    agence_id: str = Form(""),
    poste_id: int = Form(...),
    grade_id: int = Form(...),
    statut_matrimonial: str = Form(""),
    nombre_enfants: str = Form(""),
    contact_urgence_nom: str = Form(""),
    contact_urgence_tel: str = Form(""),
    telephone_pro: str = Form(""),
    telephone_perso: str = Form(""),
    email_pro: str = Form(""),
    email_perso: str = Form(""),
    photo: UploadFile = File(None),
    cni: UploadFile = File(None),
    plan_localisation: UploadFile = File(None),
    n_plus_1_id: str = Form(""),
    infos: dict = Depends(_infos_signaletiques),
):
    _exiger_rh(request)

    valeurs = {
        "nom": nom, "prenom": prenom, "genre": genre, "date_embauche": date_embauche,
        "date_naissance": date_naissance, "matricule": matricule,
        "departement_id": departement_id,
        "agence_id": _entier_ou_none(agence_id),
        "poste_id": poste_id, "grade_id": grade_id,
        "statut_matrimonial": statut_matrimonial,
        "nombre_enfants": nombre_enfants,
        "contact_urgence_nom": contact_urgence_nom,
        "contact_urgence_tel": contact_urgence_tel,
        "telephone_pro": telephone_pro,
        "telephone_perso": telephone_perso,
        "email_pro": email_pro,
        "email_perso": email_perso,
        "n_plus_1_id": _entier_ou_none(n_plus_1_id),
        **infos,
    }

    erreur = (_valider_donnees_employe(genre, date_embauche, date_naissance)
              or _valider_saisies_employe(nombre_enfants, email_pro, email_perso)
              or _erreur_infos_signaletiques(infos)
              or verifier_fichier(photo, images_seulement=True) or verifier_fichier(cni) or verifier_fichier(plan_localisation))
    if erreur:
        return templates.TemplateResponse(request, "formulaire_employe.html", {
            "mode": "creation", "valeurs": valeurs, "employe_id": None, "erreur": erreur,
            **_contexte_reference_employe(db),
        }, status_code=400)

        # Vérifier que le N+1 est bien dans le même département
    # ✅ EXCEPTION : le Directeur Général est toujours un N+1 valide, quel que soit son département
    n_plus_1_id_final = _entier_ou_none(n_plus_1_id)
    if n_plus_1_id_final:
        n1 = db.query(models.Employe).get(n_plus_1_id_final)
        est_le_dg = n1 is not None and n1.id == DG_ID
        if not n1 or (not est_le_dg and n1.departement_id != departement_id):
            n_plus_1_id_final = None

    employe = models.Employe(
        nom=nom,
        prenom=prenom,
        genre=genre,
        date_embauche=date.fromisoformat(date_embauche),
        date_naissance=date.fromisoformat(date_naissance) if date_naissance else None,
        matricule=matricule or None,
        departement_id=departement_id,
        agence_id=valeurs["agence_id"],
        poste_id=poste_id,
        grade_id=grade_id,
        statut="actif",
        statut_matrimonial=statut_matrimonial or None,
        nombre_enfants=_entier_ou_none(nombre_enfants.strip()),
        contact_urgence_nom=contact_urgence_nom or None,
        contact_urgence_tel=contact_urgence_tel or None,
        telephone_pro=telephone_pro.strip() or None,
        telephone_perso=telephone_perso.strip() or None,
        email_pro=_email_valide(email_pro),
        email_perso=_email_valide(email_perso),
        n_plus_1_id=n_plus_1_id_final,
    )
    _appliquer_infos_signaletiques(employe, infos)
    db.add(employe)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(request, "formulaire_employe.html", {
            "mode": "creation", "valeurs": valeurs, "employe_id": None,
            "erreur": "Ce matricule est déjà utilisé par un autre employé. Vérifie le numéro saisi.",
            **_contexte_reference_employe(db),
        }, status_code=400)
    db.refresh(employe)

    chemin_photo = _enregistrer_fichier(photo, employe.id, "photo")
    chemin_cni = _enregistrer_fichier(cni, employe.id, "cni")
    chemin_plan = _enregistrer_fichier(plan_localisation, employe.id, "plan")
    if chemin_photo:
        employe.photo_path = chemin_photo
    if chemin_cni:
        employe.cni_path = chemin_cni
    if chemin_plan:
        employe.plan_localisation_path = chemin_plan
    if chemin_photo or chemin_cni or chemin_plan:
        db.commit()

    affectation = models.Affectation(
        employe_id=employe.id,
        departement_id=departement_id,
        agence_id=valeurs["agence_id"],
        poste_id=poste_id,
        grade_id=grade_id,
        date_debut=date.fromisoformat(date_embauche),
        type_mouvement="embauche",
    )
    db.add(affectation)
    db.commit()

    message = quote(f"{nom} {prenom} a bien été ajouté(e).")
    return RedirectResponse(url=f"/employes?ok={message}", status_code=303)
@router.get("/employes/{employe_id}")
def fiche_employe(employe_id: int, request: Request, onglet: str = "historique", db: Session = Depends(get_db)):
    """[ÉTAPE 5] Fiche employé : en-tête, chiffres clés, alertes, informations et onglets.
    Les onglets gardent leurs anciennes adresses (?onglet=conges, documents, disciplinaire) :
    les liens existants depuis les autres pages continuent de fonctionner."""
    _exiger_lecture(request)
    employe = _employe_ou_404(db, employe_id)
    aujourdhui = date.today()
    est_rh = request.session.get("role") in ("Chef RH", "Assistant RH")
    if onglet not in ("historique", "conges", "documents", "disciplinaire"):
        onglet = "historique"

    # --- Chiffres clés ---
    solde = _solde_conges(db, employe)
    retraite = date_retraite(employe.date_naissance)

    # --- Pièces du dossier (onglet Documents + alerte « dossier incomplet ») ---
    pieces = [
        ("Photo d'identité", employe.photo_path),
        ("Carte nationale d'identité", employe.cni_path),
        ("Plan de localisation", employe.plan_localisation_path),
    ]
    pieces_manquantes = [libelle for libelle, chemin in pieces if not chemin]

    # --- Absence en cours aujourd'hui ---
    absence_en_cours = (
        db.query(models.Absence)
        .filter(models.Absence.employe_id == employe_id,
                models.Absence.date_debut <= aujourdhui,
                models.Absence.date_fin >= aujourdhui)
        .order_by(models.Absence.date_debut.desc())
        .first()
    )

    # --- Départ enregistré mais pas encore effectif (sortie programmée) ---
    depart_programme = None
    if employe.statut == "actif":
        depart_programme = (
            db.query(models.Depart)
            .filter(models.Depart.employe_id == employe_id, models.Depart.date_depart > aujourdhui)
            .order_by(models.Depart.date_depart)
            .first()
        )

    # --- Compte d'accès et dernière connexion (lue dans le journal d'audit) ---
    compte = db.query(models.Utilisateur).filter_by(employe_id=employe_id).first()
    derniere_connexion = None
    if compte:
        derniere = (
            db.query(models.JournalAudit)
            .filter_by(utilisateur_id=compte.id, action="connexion")
            .order_by(models.JournalAudit.date_heure.desc())
            .first()
        )
        derniere_connexion = derniere.date_heure if derniere else None

    # --- Données propres à l'onglet affiché ---
    historique = _historique_employe(db, employe_id) if onglet == "historique" else []
    absences = []
    if onglet == "conges":
        absences = (
            db.query(models.Absence)
            .filter_by(employe_id=employe_id)
            .order_by(models.Absence.date_debut.desc())
            .limit(100)
            .all()
        )
    sanctions = []
    if onglet == "disciplinaire":
        sanctions = (
            db.query(models.Sanction)
            .filter_by(employe_id=employe_id)
            .order_by(models.Sanction.date_sanction.desc())
            .all()
        )

    return templates.TemplateResponse(request, "fiche_employe.html", {
        "employe": employe,
        "est_rh": est_rh,
        "aujourdhui": aujourdhui,
        "onglet": onglet,
        "anciennete": _anciennete(employe.date_embauche),
        "age": _age_annees(employe.date_naissance),
        "age_retraite": AGE_RETRAITE,
        "date_retraite": retraite,
        # Alerte si le départ à la retraite tombe dans les 12 prochains mois
        "retraite_proche": bool(employe.statut == "actif" and retraite
                                and aujourdhui <= retraite <= aujourdhui + timedelta(days=365)),
        "solde": solde,
        "pieces": pieces,
        "pieces_manquantes": pieces_manquantes,
        "absence_en_cours": absence_en_cours,
        "depart_programme": depart_programme,
        "compte": compte,
        "derniere_connexion": derniere_connexion,
        "historique": historique,
        "absences": absences,
        "sanctions": sanctions,
        # [ÉTAPE 3] procédure de licenciement en cours (affichée aux RH uniquement)
        "dossier_licenciement": db.query(models.Licenciement).filter(
            models.Licenciement.employe_id == employe_id,
            models.Licenciement.statut.in_(["ouvert", "complement", "transmis", "approuve"]),
        ).first() if est_rh else None,
    })


@router.get("/employes/{employe_id}/modifier")
def modifier_employe_get(employe_id: int, request: Request, db: Session = Depends(get_db)):
    _exiger_rh(request)
    employe = _employe_ou_404(db, employe_id)
    return templates.TemplateResponse(request, "formulaire_employe.html", {
        "mode": "edition",
        "valeurs": _valeurs_depuis_employe(employe),
        "employe_id": employe.id,
        "historique": _historique_employe(db, employe_id),
        "erreur": None,
        **_contexte_reference_employe(db, employe_id_exclu=employe_id),
    })


@router.post("/employes/{employe_id}")
def modifier_employe(
    employe_id: int,
    request: Request,
    db: Session = Depends(get_db),
    nom: str = Form(...),
    prenom: str = Form(...),
    genre: str = Form(...),
    date_embauche: str = Form(...),
    date_naissance: str = Form(""),
    matricule: str = Form(""),
    departement_id: int = Form(...),
    agence_id: str = Form(""),
    poste_id: int = Form(...),
    grade_id: int = Form(...),
    statut_matrimonial: str = Form(""),
    nombre_enfants: str = Form(""),
    contact_urgence_nom: str = Form(""),
    contact_urgence_tel: str = Form(""),
    motif_changement: str = Form(""),
    telephone_pro: str = Form(""),
    telephone_perso: str = Form(""),
    email_pro: str = Form(""),
    email_perso: str = Form(""),
    photo: UploadFile = File(None),
    cni: UploadFile = File(None),
    plan_localisation: UploadFile = File(None),
    n_plus_1_id: str = Form(""),
    infos: dict = Depends(_infos_signaletiques),
):
    _exiger_rh(request)

    employe = _employe_ou_404(db, employe_id)
    nouvelle_agence_id = _entier_ou_none(agence_id)

    valeurs = {
        "nom": nom, "prenom": prenom, "genre": genre, "date_embauche": date_embauche,
        "date_naissance": date_naissance, "matricule": matricule,
        "departement_id": departement_id,
        "agence_id": nouvelle_agence_id, "poste_id": poste_id, "grade_id": grade_id,
        "statut_matrimonial": statut_matrimonial,
        "nombre_enfants": nombre_enfants,
        "contact_urgence_nom": contact_urgence_nom,
        "contact_urgence_tel": contact_urgence_tel,
        # [CORRECTIF B14] ces champs étaient perdus quand le formulaire était réaffiché avec une erreur
        "telephone_pro": telephone_pro,
        "telephone_perso": telephone_perso,
        "email_pro": email_pro,
        "email_perso": email_perso,
        "n_plus_1_id": _entier_ou_none(n_plus_1_id),
        **infos,
    }

    erreur = (_valider_donnees_employe(genre, date_embauche, date_naissance)
              or _valider_saisies_employe(nombre_enfants, email_pro, email_perso)
              or _erreur_infos_signaletiques(infos)
              or verifier_fichier(photo, images_seulement=True) or verifier_fichier(cni) or verifier_fichier(plan_localisation))
    if erreur:
        return templates.TemplateResponse(request, "formulaire_employe.html", {
            "mode": "edition", "valeurs": valeurs, "employe_id": employe_id, "erreur": erreur,
            "historique": _historique_employe(db, employe_id),
            **_contexte_reference_employe(db, employe_id_exclu=employe_id),  # [CORRECTIF B14]
        }, status_code=400)

    situation_a_change = (
        employe.departement_id != departement_id
        or employe.agence_id != nouvelle_agence_id
        or employe.poste_id != poste_id
        or employe.grade_id != grade_id
    )
        # Si le département change → réinitialiser le N+1
    departement_change = employe.departement_id != departement_id
    if departement_change:
        n_plus_1_id_final = None
    else:
        n_plus_1_id_final = _entier_ou_none(n_plus_1_id)

    # Vérifier que le N+1 est bien dans le même département
    # ✅ EXCEPTION : le Directeur Général est toujours un N+1 valide, quel que soit son département
    if n_plus_1_id_final:
        n1 = db.query(models.Employe).get(n_plus_1_id_final)
        est_le_dg = n1 is not None and n1.id == DG_ID
        if not n1 or n1.id == employe_id or (not est_le_dg and n1.departement_id != departement_id):
            n_plus_1_id_final = None  # invalide → on le vide

    employe.nom = nom
    employe.prenom = prenom
    employe.genre = genre
    employe.date_embauche = date.fromisoformat(date_embauche)
    employe.matricule = matricule or None
    employe.departement_id = departement_id
    employe.agence_id = nouvelle_agence_id
    employe.poste_id = poste_id
    employe.grade_id = grade_id
    employe.date_naissance = date.fromisoformat(date_naissance) if date_naissance else None
    employe.statut_matrimonial = statut_matrimonial or None
    employe.nombre_enfants = _entier_ou_none(nombre_enfants.strip())
    employe.contact_urgence_nom = contact_urgence_nom or None
    employe.contact_urgence_tel = contact_urgence_tel or None
    employe.telephone_pro = telephone_pro.strip() or None
    employe.telephone_perso = telephone_perso.strip() or None
    employe.email_pro = _email_valide(email_pro)
    employe.email_perso = _email_valide(email_perso)
    employe.n_plus_1_id = n_plus_1_id_final
    _appliquer_infos_signaletiques(employe, infos)

    chemin_photo = _enregistrer_fichier(photo, employe.id, "photo")
    chemin_cni = _enregistrer_fichier(cni, employe.id, "cni")
    chemin_plan = _enregistrer_fichier(plan_localisation, employe.id, "plan")
    if chemin_photo:
        employe.photo_path = chemin_photo
    if chemin_cni:
        employe.cni_path = chemin_cni
    if chemin_plan:
        employe.plan_localisation_path = chemin_plan

    if situation_a_change:
        aujourdhui = date.today()
        affectation_ouverte = (
            db.query(models.Affectation)
            .filter_by(employe_id=employe.id, date_fin=None)
            .first()
        )
        if affectation_ouverte:
            affectation_ouverte.date_fin = aujourdhui

        db.add(models.Affectation(
            employe_id=employe.id,
            departement_id=departement_id,
            agence_id=nouvelle_agence_id,
            poste_id=poste_id,
            grade_id=grade_id,
            date_debut=aujourdhui,
            type_mouvement="modification",
            motif=motif_changement or None,
        ))

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(request, "formulaire_employe.html", {
            "mode": "edition", "valeurs": valeurs, "employe_id": employe_id,
            "erreur": "Ce matricule est déjà utilisé par un autre employé. Vérifie le numéro saisi.",
            "historique": _historique_employe(db, employe_id),
            **_contexte_reference_employe(db, employe_id_exclu=employe_id),  # [CORRECTIF B14]
        }, status_code=400)

    message = quote("Modifications enregistrées.")
    return RedirectResponse(url=f"/employes?ok={message}", status_code=303)

# ============================================================
# SANCTIONS DISCIPLINAIRES
# ============================================================

@router.get("/employes/{employe_id}/sanctions/nouvelle")
def formulaire_sanction(employe_id: int, request: Request, db: Session = Depends(get_db)):
    _exiger_rh(request)
    employe = _employe_ou_404(db, employe_id)
    return templates.TemplateResponse(request, "formulaire_sanction.html", {
        "employe": employe,
        "valeurs": {},
        "erreur": None,
    })


@router.post("/employes/{employe_id}/sanctions/nouvelle")
def creer_sanction(
    employe_id: int,
    request: Request,
    db: Session = Depends(get_db),
    date_sanction: str = Form(...),
    type_sanction: str = Form(...),
    motif: str = Form(...),
    duree: str = Form(""),
    commentaire: str = Form(""),
    enregistre_par: str = Form(""),
):
    _exiger_rh(request)
    employe = _employe_ou_404(db, employe_id)

    valeurs = {
        "date_sanction": date_sanction,
        "type_sanction": type_sanction,
        "motif": motif,
        "duree": duree,
        "commentaire": commentaire,
        "enregistre_par": enregistre_par,
    }

    # [ÉTAPE 3] « Licenciement disciplinaire » retiré : un licenciement passe obligatoirement par la
    # procédure (conseil de discipline + décision du Comité). Les anciennes sanctions de ce type restent visibles.
    if type_sanction not in ("Avertissement", "Blâme", "Mise à pied"):
        return templates.TemplateResponse(request, "formulaire_sanction.html", {
            "employe": employe, "valeurs": valeurs,
            "erreur": "Type de sanction invalide.",
        }, status_code=400)

    try:
        date_s = date.fromisoformat(date_sanction)
    except ValueError:
        return templates.TemplateResponse(request, "formulaire_sanction.html", {
            "employe": employe, "valeurs": valeurs,
            "erreur": "La date de sanction n'est pas valide.",
        }, status_code=400)

    if not motif.strip():
        return templates.TemplateResponse(request, "formulaire_sanction.html", {
            "employe": employe, "valeurs": valeurs,
            "erreur": "Le motif est obligatoire.",
        }, status_code=400)

    sanction = models.Sanction(
        employe_id=employe.id,
        type_sanction=type_sanction,
        motif=motif.strip(),
        date_sanction=date_s,
        duree=duree.strip() or None,
        commentaire=commentaire.strip() or None,
        enregistre_par=enregistre_par.strip() or None,
    )
    db.add(sanction)
    db.commit()

    message = quote(f"Sanction « {type_sanction} » enregistrée pour {employe.nom} {employe.prenom}.")
    return RedirectResponse(url=f"/employes/{employe.id}?onglet=disciplinaire&ok={message}", status_code=303)


@router.post("/employes/{employe_id}/sanctions/{sanction_id}/supprimer")
def supprimer_sanction(
    employe_id: int,
    sanction_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _exiger_chef_rh(request)
    employe = _employe_ou_404(db, employe_id)
    sanction = db.query(models.Sanction).get(sanction_id)
    if not sanction or sanction.employe_id != employe.id:
        raise HTTPException(status_code=404, detail="Sanction introuvable")

    db.delete(sanction)
    db.commit()
    message = quote("Sanction supprimée.")
    return RedirectResponse(url=f"/employes/{employe.id}?onglet=disciplinaire&ok={message}", status_code=303)



# ============================================================
# GÉNÉRATION PDF
# ============================================================

@router.get("/employes/{employe_id}/pdf/fiche")
def pdf_fiche_employe(employe_id: int, request: Request, db: Session = Depends(get_db)):
    _exiger_lecture(request)
    employe = _employe_ou_404(db, employe_id)
    # [ÉTAPE 5] Fiche signalétique : données préparées par une fonction commune (RH et espace employé)
    contenu = pdf_module.generer_fiche_employe_pdf(employe, contexte_fiche_pdf(db, employe, request.session.get("nom")))
    nom_fichier = f"fiche_{employe.matricule or employe.id}_{employe.nom}_{employe.prenom}.pdf".replace(" ", "_")

    return Response(
        content=contenu,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'},
    )


@router.get("/employes/{employe_id}/pdf/certificat")
def pdf_certificat(employe_id: int, request: Request, db: Session = Depends(get_db)):
    _exiger_lecture(request)
    employe = _employe_ou_404(db, employe_id)

    depart = (
        db.query(models.Depart)
        .filter_by(employe_id=employe_id)
        .order_by(models.Depart.date_depart.desc())
        .first()
    )
    # [CORRECTIF B16] Un certificat de travail se délivre à la FIN du contrat : il atteste que
    # l'employé est « libre de tout engagement ». Pour un employé en poste → attestation de travail.
    if employe.statut == "actif" or not depart:
        message = quote("Le certificat de travail n'est délivré qu'après un départ validé. "
                        "Pour un employé en poste, utilisez l'attestation de travail.")
        return RedirectResponse(url=f"/employes/{employe.id}?erreur={message}", status_code=303)
    date_depart = depart.date_depart

    contenu = pdf_module.generer_certificat_travail_pdf(employe, date_depart)
    nom_fichier = f"certificat_{employe.matricule or employe.id}_{employe.nom}_{employe.prenom}.pdf".replace(" ", "_")

    return Response(
        content=contenu,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'},
    )


@router.get("/employes/{employe_id}/pdf/attestation")
def pdf_attestation(employe_id: int, request: Request, db: Session = Depends(get_db)):
    _exiger_lecture(request)
    employe = _employe_ou_404(db, employe_id)

    contenu = pdf_module.generer_attestation_travail_pdf(employe)
    nom_fichier = f"attestation_{employe.matricule or employe.id}_{employe.nom}_{employe.prenom}.pdf".replace(" ", "_")

    return Response(
        content=contenu,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'},
    )