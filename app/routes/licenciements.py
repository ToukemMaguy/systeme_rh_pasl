"""Module licenciement (étape 3).

Circuit validé avec PASL :
  1. Ouverture du dossier par la RH (faits, motif, sanctions antérieures, mise à pied conservatoire).
  2. Conseil de discipline : après la séance, la RH saisit la date, les membres, l'avis et joint le PV.
     - Si le conseil propose une sanction plus légère (ou la relaxe), la RH clôt le dossier
       (la sanction est alors créée automatiquement dans l'historique disciplinaire).
  3. La RH complète le dossier (préavis, avis RH) puis le TRANSMET au Comité de direction
     (bouton disponible seulement quand la liste de contrôle est complète).
  4. Le Comité de direction décide : approuver / rejeter / renvoyer à la RH pour complément.
  5. Si approuvé : la RH notifie (lettre PDF, date de notification, date de sortie).
  6. Sortie des effectifs à la date prévue : statut inactif, accès coupés, demandes en attente annulées,
     alerte si l'employé était N+1 (mécanismes du lot 1, point 4).

Confidentialité : dossiers visibles uniquement par la RH (Chef RH, Assistant RH) et par le Comité de
direction (une fois transmis). Aucun montant ni salaire : seules les durées sont enregistrées.
"""
from datetime import date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from .. import models
from .. import pdf as pdf_module
from ..outils import templates, _date_ou_none, _entier_ou_none, _enregistrer_fichier, _acces_refuse
from ..regles_rh import _employe_ou_404, _anciennete, _solde_conges, sortir_des_effectifs
from ..notifications import notifier_licenciement_transmis, notifier_licenciement_decide

router = APIRouter()

ROLES_RH = ("Chef RH", "Assistant RH")
ROLE_COMITE = "Comité de direction"

TYPES_MOTIF = ["Faute simple", "Faute grave", "Faute lourde", "Insuffisance professionnelle",
               "Motif économique", "Inaptitude médicale", "Autre"]
SANCTIONS_ALTERNATIVES = ["Avertissement", "Blâme", "Mise à pied"]
MODES_NOTIFICATION = ["Remise en main propre contre décharge", "Lettre recommandée", "Exploit d'huissier"]

STATUTS = {
    "ouvert": ("En instruction (RH)", "bg-[#EBF4FF] text-[#2B6CB0]"),
    "complement": ("Complément demandé par le Comité", "bg-[#FFFBEB] text-[#92400E]"),
    "transmis": ("En attente de décision du Comité", "bg-[#FFFBEB] text-[#92400E]"),
    "approuve": ("Approuvé — à notifier", "bg-[#F0FDF4] text-[#166534]"),
    "notifie": ("Notifié", "bg-[#F0FDF4] text-[#166534]"),
    "rejete": ("Rejeté par le Comité", "bg-[#fed7d7] text-[#9b2c2c]"),
    "clos_sanction": ("Clos — sanction plus légère", "bg-surface-container-high text-on-surface-variant"),
    "clos_relaxe": ("Clos — relaxe", "bg-surface-container-high text-on-surface-variant"),
    "annule": ("Annulé", "bg-surface-container-high text-on-surface-variant"),
}
STATUTS_EN_COURS = ("ouvert", "complement", "transmis", "approuve")
ETAPES = ["Ouverture", "Conseil de discipline", "Dossier RH", "Décision du Comité", "Notification", "Sortie"]


# ------------------------------------------------------------------
# Outils
# ------------------------------------------------------------------
def _role(request: Request) -> str | None:
    return request.session.get("role")


def _exiger_rh_licenciement(request: Request):
    if _role(request) not in ROLES_RH:
        _acces_refuse(request)


def _dossier_ou_404(db: Session, dossier_id: int, request: Request) -> models.Licenciement:
    dossier = db.query(models.Licenciement).get(dossier_id)
    if not dossier:
        raise HTTPException(status_code=404, detail="Dossier introuvable")
    role = _role(request)
    # Confidentialité : RH, ou Comité de direction une fois le dossier transmis
    if role in ROLES_RH or (role == ROLE_COMITE and dossier.transmis_le is not None):
        return dossier
    _acces_refuse(request)


def _retour(dossier_id: int, ok: str | None = None, erreur: str | None = None) -> RedirectResponse:
    param = f"?ok={quote(ok)}" if ok else (f"?erreur={quote(erreur)}" if erreur else "")
    return RedirectResponse(url=f"/licenciements/{dossier_id}{param}", status_code=303)


def etape_courante(d: models.Licenciement) -> int:
    """Numéro (1 à 6) de l'étape en cours, pour la frise."""
    if d.statut in ("ouvert", "complement"):
        return 3 if d.conseil_date else 2
    if d.statut == "transmis":
        return 4
    if d.statut == "approuve":
        return 5
    if d.statut == "notifie":
        return 6
    return 0  # dossier clos (rejeté, annulé, sanction, relaxe)


def liste_de_controle(d: models.Licenciement) -> list[tuple[str, bool]]:
    """Conditions à remplir avant de pouvoir transmettre au Comité."""
    preavis_ok = d.type_motif == "Faute lourde" or d.preavis_dispense or d.preavis_jours is not None
    return [
        ("Exposé des faits renseigné", bool((d.expose_faits or "").strip())),
        ("Date du conseil de discipline", d.conseil_date is not None),
        ("Procès-verbal (PV) du conseil joint", bool(d.pv_path)),
        ("Avis du conseil : licenciement", d.conseil_avis == "licenciement"),
        ("Préavis renseigné (durée ou dispense)" + (" — non dû pour faute lourde" if d.type_motif == "Faute lourde" else ""), preavis_ok),
        ("Avis de la RH donné", d.avis_rh in ("favorable", "defavorable")),
    ]


def nb_licenciements_a_decider() -> int:
    """Compteur affiché dans le menu du Comité de direction."""
    db = SessionLocal()
    try:
        return db.query(models.Licenciement).filter_by(statut="transmis").count()
    finally:
        db.close()


templates.env.globals["nb_licenciements_a_decider"] = nb_licenciements_a_decider
templates.env.globals["STATUTS_LICENCIEMENT"] = STATUTS


def dossier_en_cours(db: Session, employe_id: int):
    return (db.query(models.Licenciement)
            .filter(models.Licenciement.employe_id == employe_id, models.Licenciement.statut.in_(STATUTS_EN_COURS))
            .first())


# ------------------------------------------------------------------
# Liste des dossiers
# ------------------------------------------------------------------
@router.get("/licenciements")
def liste_licenciements(request: Request, statut: str = "", db: Session = Depends(get_db)):
    role = _role(request)
    if role not in ROLES_RH and role != ROLE_COMITE:
        _acces_refuse(request)
    q = db.query(models.Licenciement)
    if role == ROLE_COMITE:
        q = q.filter(models.Licenciement.transmis_le.isnot(None))
        statut = statut or "transmis"
    if statut and statut != "tous":
        q = q.filter(models.Licenciement.statut == statut)
    dossiers = q.order_by(models.Licenciement.id.desc()).all()
    return templates.TemplateResponse(request, "licenciements.html", {
        "dossiers": dossiers, "statut": statut, "statuts": STATUTS, "est_comite": role == ROLE_COMITE,
    })


# ------------------------------------------------------------------
# 1. Ouverture
# ------------------------------------------------------------------
@router.get("/employes/{employe_id}/licenciement/nouveau")
def formulaire_ouverture(employe_id: int, request: Request, db: Session = Depends(get_db)):
    _exiger_rh_licenciement(request)
    employe = _employe_ou_404(db, employe_id)
    existant = dossier_en_cours(db, employe_id)
    if existant:
        return _retour(existant.id, erreur="Une procédure est déjà en cours pour cet employé.")
    if employe.statut != "actif":
        return RedirectResponse(url=f"/employes/{employe_id}?erreur={quote('Cet employé ne fait plus partie des effectifs.')}", status_code=303)
    sanctions = db.query(models.Sanction).filter_by(employe_id=employe_id).order_by(models.Sanction.date_sanction.desc()).all()
    return templates.TemplateResponse(request, "licenciement_nouveau.html", {
        "employe": employe, "sanctions": sanctions, "types_motif": TYPES_MOTIF,
        "anciennete": _anciennete(employe.date_embauche), "erreur": None, "valeurs": {},
    })


@router.post("/employes/{employe_id}/licenciement/nouveau")
def ouvrir_dossier(
    employe_id: int,
    request: Request,
    db: Session = Depends(get_db),
    type_motif: str = Form(...),
    date_faits: str = Form(""),
    expose_faits: str = Form(""),
    sanctions_liees: list[str] = Form([]),
    mise_a_pied_conservatoire: str = Form(""),
    mise_a_pied_debut: str = Form(""),
    mise_a_pied_fin: str = Form(""),
):
    _exiger_rh_licenciement(request)
    employe = _employe_ou_404(db, employe_id)
    existant = dossier_en_cours(db, employe_id)
    if existant:
        return _retour(existant.id, erreur="Une procédure est déjà en cours pour cet employé.")

    erreur = None
    if type_motif not in TYPES_MOTIF:
        erreur = "Merci de choisir le motif du licenciement."
    elif not expose_faits.strip():
        erreur = "Merci de décrire les faits reprochés."
    elif date_faits and not _date_ou_none(date_faits):
        erreur = "La date des faits n'est pas valide."
    if erreur:
        sanctions = db.query(models.Sanction).filter_by(employe_id=employe_id).order_by(models.Sanction.date_sanction.desc()).all()
        return templates.TemplateResponse(request, "licenciement_nouveau.html", {
            "employe": employe, "sanctions": sanctions, "types_motif": TYPES_MOTIF,
            "anciennete": _anciennete(employe.date_embauche), "erreur": erreur,
            "valeurs": {"type_motif": type_motif, "date_faits": date_faits, "expose_faits": expose_faits},
        }, status_code=400)

    ids_sanctions = [i for i in (_entier_ou_none(s) for s in sanctions_liees) if i]
    dossier = models.Licenciement(
        employe_id=employe.id,
        statut="ouvert",
        type_motif=type_motif,
        date_faits=_date_ou_none(date_faits),
        expose_faits=expose_faits.strip(),
        sanctions_liees=ids_sanctions or None,
        mise_a_pied_conservatoire=bool(mise_a_pied_conservatoire),
        mise_a_pied_debut=_date_ou_none(mise_a_pied_debut) if mise_a_pied_conservatoire else None,
        mise_a_pied_fin=_date_ou_none(mise_a_pied_fin) if mise_a_pied_conservatoire else None,
        ouvert_par=request.session.get("nom"),
        ouvert_le=datetime.now(),
    )
    db.add(dossier)
    db.commit()
    return _retour(dossier.id, ok="Dossier ouvert. Complétez-le après le conseil de discipline.")


# ------------------------------------------------------------------
# Dossier
# ------------------------------------------------------------------
@router.get("/licenciements/{dossier_id}")
def page_dossier(dossier_id: int, request: Request, db: Session = Depends(get_db)):
    dossier = _dossier_ou_404(db, dossier_id, request)
    employe = dossier.employe
    sanctions = {s.id: s for s in db.query(models.Sanction).filter_by(employe_id=employe.id)}
    controle = liste_de_controle(dossier)
    return templates.TemplateResponse(request, "licenciement_dossier.html", {
        "d": dossier,
        "employe": employe,
        "anciennete": _anciennete(employe.date_embauche),
        "conges_restants": _solde_conges(db, employe)["total_restant"],
        "sanctions_liees": [sanctions[i] for i in (dossier.sanctions_liees or []) if i in sanctions],
        "controle": controle,
        "pret_a_transmettre": all(ok for _, ok in controle),
        "etape": etape_courante(dossier),
        "etapes": ETAPES,
        "statuts": STATUTS,
        "est_rh": _role(request) in ROLES_RH,
        "est_comite": _role(request) == ROLE_COMITE,
        "modifiable": dossier.statut in ("ouvert", "complement") and _role(request) in ROLES_RH,
        "sanctions_alternatives": SANCTIONS_ALTERNATIVES,
        "modes_notification": MODES_NOTIFICATION,
        "aujourdhui": date.today(),
    })


# ------------------------------------------------------------------
# 2 et 3. Conseil de discipline + dossier RH (enregistrement)
# ------------------------------------------------------------------
@router.post("/licenciements/{dossier_id}/enregistrer")
def enregistrer_dossier(
    dossier_id: int,
    request: Request,
    db: Session = Depends(get_db),
    expose_faits: str = Form(""),
    conseil_date: str = Form(""),
    conseil_membres: str = Form(""),
    conseil_avis: str = Form(""),
    conseil_sanction_proposee: str = Form(""),
    conseil_resume: str = Form(""),
    pv: UploadFile = File(None),
    preavis_jours: str = Form(""),
    preavis_dispense: str = Form(""),
    avis_rh: str = Form(""),
    commentaire_rh: str = Form(""),
):
    _exiger_rh_licenciement(request)
    d = _dossier_ou_404(db, dossier_id, request)
    if d.statut not in ("ouvert", "complement"):
        return _retour(d.id, erreur="Ce dossier ne peut plus être modifié à ce stade.")
    if conseil_date and not _date_ou_none(conseil_date):
        return _retour(d.id, erreur="La date du conseil n'est pas valide.")
    if preavis_jours.strip() and (_entier_ou_none(preavis_jours.strip()) is None or int(preavis_jours) < 0):
        return _retour(d.id, erreur="La durée du préavis doit être un nombre de jours (ex. 30).")
    if conseil_avis == "sanction" and conseil_sanction_proposee not in SANCTIONS_ALTERNATIVES:
        return _retour(d.id, erreur="Précisez la sanction proposée par le conseil.")

    if expose_faits.strip():
        d.expose_faits = expose_faits.strip()
    d.conseil_date = _date_ou_none(conseil_date)
    d.conseil_membres = conseil_membres.strip() or None
    d.conseil_avis = conseil_avis if conseil_avis in ("licenciement", "sanction", "relaxe") else None
    d.conseil_sanction_proposee = conseil_sanction_proposee if d.conseil_avis == "sanction" else None
    d.conseil_resume = conseil_resume.strip() or None
    chemin_pv = _enregistrer_fichier(pv, d.employe_id, f"pv_conseil_{d.id}")
    if chemin_pv:
        d.pv_path = chemin_pv
    d.preavis_dispense = bool(preavis_dispense)
    d.preavis_jours = _entier_ou_none(preavis_jours.strip()) if not d.preavis_dispense else None
    d.avis_rh = avis_rh if avis_rh in ("favorable", "defavorable") else None
    d.commentaire_rh = commentaire_rh.strip() or None
    db.commit()
    return _retour(d.id, ok="Dossier enregistré.")


@router.post("/licenciements/{dossier_id}/transmettre")
def transmettre_au_comite(dossier_id: int, request: Request, db: Session = Depends(get_db)):
    """RH → Comité de direction. Refusé tant que la liste de contrôle n'est pas complète."""
    _exiger_rh_licenciement(request)
    d = _dossier_ou_404(db, dossier_id, request)
    if d.statut not in ("ouvert", "complement"):
        return _retour(d.id, erreur="Ce dossier a déjà été transmis ou clôturé.")
    manquants = [libelle for libelle, ok in liste_de_controle(d) if not ok]
    if manquants:
        return _retour(d.id, erreur="Dossier incomplet : " + " ; ".join(manquants) + ".")
    d.statut = "transmis"
    d.transmis_par = request.session.get("nom")
    d.transmis_le = datetime.now()
    d.decision = None
    notifier_licenciement_transmis(db, d)
    db.commit()
    return _retour(d.id, ok="Dossier transmis au Comité de direction.")


@router.post("/licenciements/{dossier_id}/cloturer")
def cloturer_sans_licenciement(dossier_id: int, request: Request, db: Session = Depends(get_db)):
    """Le conseil a proposé une sanction plus légère ou la relaxe : le dossier est clos.
    Pour une sanction, elle est créée automatiquement dans l'historique disciplinaire."""
    _exiger_rh_licenciement(request)
    d = _dossier_ou_404(db, dossier_id, request)
    if d.statut not in ("ouvert", "complement") or d.conseil_avis not in ("sanction", "relaxe"):
        return _retour(d.id, erreur="Clôture possible seulement si le conseil a proposé une sanction plus légère ou la relaxe.")
    if d.conseil_avis == "sanction":
        sanction = models.Sanction(
            employe_id=d.employe_id,
            type_sanction=d.conseil_sanction_proposee,
            motif=d.expose_faits,
            date_sanction=d.conseil_date or date.today(),
            commentaire=f"Décidée par le conseil de discipline du "
                        f"{d.conseil_date.strftime('%d/%m/%Y') if d.conseil_date else '—'} (dossier n°{d.id}).",
            enregistre_par=request.session.get("nom"),
        )
        db.add(sanction)
        db.flush()
        d.sanction_id = sanction.id
        d.statut = "clos_sanction"
        message = f"Dossier clos. Sanction « {d.conseil_sanction_proposee} » ajoutée à l'historique disciplinaire."
    else:
        d.statut = "clos_relaxe"
        message = "Dossier clos (relaxe)."
    db.commit()
    return _retour(d.id, ok=message)


@router.post("/licenciements/{dossier_id}/annuler")
def annuler_dossier(dossier_id: int, request: Request, db: Session = Depends(get_db), motif: str = Form("")):
    _exiger_rh_licenciement(request)
    d = _dossier_ou_404(db, dossier_id, request)
    if d.statut not in ("ouvert", "complement"):
        return _retour(d.id, erreur="Ce dossier ne peut plus être annulé à ce stade.")
    if not motif.strip():
        return _retour(d.id, erreur="Le motif de l'annulation est obligatoire.")
    d.statut = "annule"
    d.motif_annulation = motif.strip()
    db.commit()
    return _retour(d.id, ok="Dossier annulé.")


# ------------------------------------------------------------------
# 4. Décision du Comité de direction
# ------------------------------------------------------------------
@router.post("/licenciements/{dossier_id}/decision")
def decider(
    dossier_id: int,
    request: Request,
    db: Session = Depends(get_db),
    decision: str = Form(...),
    commentaire: str = Form(""),
):
    if _role(request) != ROLE_COMITE:
        _acces_refuse(request)
    d = _dossier_ou_404(db, dossier_id, request)
    if d.statut != "transmis":
        return _retour(d.id, erreur="Ce dossier n'est pas en attente de décision.")
    if decision not in ("approuve", "rejete", "complement"):
        return _retour(d.id, erreur="Décision invalide.")
    if decision in ("rejete", "complement") and not commentaire.strip():
        return _retour(d.id, erreur="Un commentaire est obligatoire pour rejeter ou demander un complément.")
    d.decision = decision
    d.decision_commentaire = commentaire.strip() or None
    d.decide_par = request.session.get("nom")
    d.decide_le = datetime.now()
    d.statut = {"approuve": "approuve", "rejete": "rejete", "complement": "complement"}[decision]
    notifier_licenciement_decide(db, d)
    db.commit()
    libelles = {"approuve": "Licenciement approuvé. La RH va procéder à la notification.",
                "rejete": "Licenciement rejeté.", "complement": "Dossier renvoyé à la RH pour complément."}
    return _retour(d.id, ok=libelles[decision])


# ------------------------------------------------------------------
# 5. Notification (RH) et 6. sortie des effectifs
# ------------------------------------------------------------------
@router.post("/licenciements/{dossier_id}/notifier")
def notifier(
    dossier_id: int,
    request: Request,
    db: Session = Depends(get_db),
    date_notification: str = Form(""),
    mode_notification: str = Form(""),
    date_sortie: str = Form(""),
    lettre_signee: UploadFile = File(None),
):
    _exiger_rh_licenciement(request)
    d = _dossier_ou_404(db, dossier_id, request)
    if d.statut != "approuve":
        return _retour(d.id, erreur="La notification n'est possible qu'après l'approbation du Comité.")
    d_notif, d_sortie = _date_ou_none(date_notification), _date_ou_none(date_sortie)
    if not d_notif or not d_sortie:
        return _retour(d.id, erreur="Les dates de notification et de sortie sont obligatoires.")
    if d_sortie < d_notif:
        return _retour(d.id, erreur="La date de sortie ne peut pas précéder la date de notification.")

    employe = d.employe
    d.date_notification = d_notif
    d.mode_notification = mode_notification if mode_notification in MODES_NOTIFICATION else None
    d.date_sortie = d_sortie
    d.jours_conges_restants = _solde_conges(db, employe, d_sortie)["total_restant"]
    chemin = _enregistrer_fichier(lettre_signee, employe.id, f"lettre_licenciement_{d.id}")
    if chemin:
        d.lettre_signee_path = chemin
    d.notifie_par = request.session.get("nom")
    d.statut = "notifie"

    depart = models.Depart(employe_id=employe.id, date_depart=d_sortie,
                           type_depart=f"Licenciement ({d.type_motif})", motif=d.expose_faits)
    db.add(depart)
    db.flush()
    d.depart_id = depart.id
    if d_sortie <= date.today():
        sortir_des_effectifs(db, employe, depart)
        message = "Licenciement notifié. L'employé est sorti des effectifs et ses accès sont coupés."
    else:
        message = (f"Licenciement notifié. Sortie des effectifs programmée le {d_sortie.strftime('%d/%m/%Y')} "
                   "(statut et accès mis à jour automatiquement à cette date).")
    db.commit()
    return _retour(d.id, ok=message)


@router.post("/licenciements/{dossier_id}/lettre")
def enregistrer_lettre(
    dossier_id: int,
    request: Request,
    db: Session = Depends(get_db),
    lettre_texte: str = Form(""),
):
    """Texte libre de la lettre (les formats varient selon les cas : pas de modèle imposé).
    Modifiable tant que le licenciement n'est pas notifié ; ensuite, il est figé (c'est la lettre remise)."""
    _exiger_rh_licenciement(request)
    d = _dossier_ou_404(db, dossier_id, request)
    if d.statut != "approuve":
        return _retour(d.id, erreur="Le texte de la lettre n'est modifiable qu'entre l'approbation du Comité et la notification.")
    d.lettre_texte = lettre_texte.strip() or None
    db.commit()
    return _retour(d.id, ok="Texte de la lettre enregistré. Vous pouvez télécharger le PDF sur papier à en-tête.")


@router.get("/licenciements/{dossier_id}/pdf/lettre")
def pdf_lettre(dossier_id: int, request: Request, db: Session = Depends(get_db)):
    _exiger_rh_licenciement(request)
    d = _dossier_ou_404(db, dossier_id, request)
    if d.statut not in ("approuve", "notifie"):
        return _retour(d.id, erreur="La lettre n'est disponible qu'après l'approbation du Comité.")
    if not d.lettre_texte:
        return _retour(d.id, erreur="Rédigez et enregistrez d'abord le texte de la lettre.")
    contenu = pdf_module.generer_lettre_licenciement_pdf(d.employe, d)
    nom = f"lettre_licenciement_{d.employe.matricule or d.employe.id}_{d.employe.nom}.pdf".replace(" ", "_")
    return Response(content=contenu, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{nom}"'})
