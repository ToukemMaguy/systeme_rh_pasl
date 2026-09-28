"""Notifications à chaque étape du circuit de validation (lot 1, point 18).

Avant : un seul mail, à la décision finale de la RH. Le N+1 ne savait pas qu'une demande l'attendait,
et la RH ne savait pas qu'une demande venait de recevoir un avis favorable : les demandes « dormaient ».

Maintenant :
  1. Dépôt d'une demande      → mail au N+1 de l'employé (ou à la RH s'il n'y a pas de N+1).
  2. Avis favorable du N+1    → mail à la RH (Chef RH et Assistants RH) : « demande à traiter ».
  3. Avis défavorable du N+1  → mail à l'employé (refus définitif).
  4. Décision de la RH        → mails existants à l'employé et au suppléant (inchangés).

Les mails ne partent pas immédiatement : ils sont mis dans la file d'attente (table mails_a_envoyer),
envoyée par le script app/scripts/envoyer_mails.py (planificateur de tâches Windows).
"""
import os

from sqlalchemy.orm import Session

from . import models

SIGNATURE = "\nCordialement,\nPASL-RH — Pan-African Savings & Loans\n"


def _lien(chemin: str) -> str:
    """Adresse complète d'une page (APP_URL dans le .env, sinon l'adresse locale)."""
    return os.getenv("APP_URL", "http://127.0.0.1:8000").rstrip("/") + chemin


def email_employe(employe) -> str | None:
    """Adresse de travail en priorité, sinon l'adresse personnelle."""
    if not employe:
        return None
    return employe.email_pro or employe.email_perso


def emails_rh(db: Session) -> list[str]:
    """Adresses des comptes RH actifs (Chef RH et Assistants RH)."""
    comptes = (
        db.query(models.Utilisateur)
        .filter(models.Utilisateur.role.in_(["Chef RH", "Assistant RH"]), models.Utilisateur.compte_actif.is_(True))
        .all()
    )
    return sorted({c.email for c in comptes if c.email})


def _ajouter(db: Session, destinataire: str, sujet: str, corps: str, demande, type_mail: str):
    db.add(models.MailAEnvoyer(destinataire=destinataire, sujet=sujet, corps=corps + SIGNATURE,
                               demande_id=demande.id, type_mail=type_mail))


def _resume(demande) -> str:
    employe = demande.employe_concerne
    lignes = [f"Type : {demande.type_demande.libelle if demande.type_demande else 'Demande'}"]
    if employe:
        lignes.append(f"Employé : {employe.nom} {employe.prenom}" + (f" ({employe.matricule})" if employe.matricule else ""))
    if demande.periode_sollicitee_debut and demande.periode_sollicitee_fin:
        lignes.append(f"Période demandée : du {demande.periode_sollicitee_debut.strftime('%d/%m/%Y')} "
                      f"au {demande.periode_sollicitee_fin.strftime('%d/%m/%Y')}")
    elif demande.periode_sollicitee_debut:
        lignes.append(f"Date : {demande.periode_sollicitee_debut.strftime('%d/%m/%Y')}")
    if demande.commentaire:
        lignes.append(f"Commentaire : {demande.commentaire}")
    return "\n".join(lignes)


def notifier_nouvelle_demande(db: Session, demande) -> None:
    """Étape 1 : une demande vient d'être déposée."""
    employe = demande.employe_concerne
    n_plus_1 = employe.n_plus_1 if employe else None
    type_lib = (demande.type_demande.libelle if demande.type_demande else "demande").lower()

    if n_plus_1 and email_employe(n_plus_1):
        _ajouter(db, email_employe(n_plus_1),
                 f"[PASL-RH] Demande de {type_lib} à examiner — {employe.nom} {employe.prenom}",
                 f"Bonjour {n_plus_1.prenom},\n\n"
                 f"Une demande attend votre avis en tant que responsable hiérarchique (N+1) :\n\n"
                 f"{_resume(demande)}\n\n"
                 f"Donner votre avis : {_lien('/mes-validations')}\n",
                 demande, "notif_n_plus_1_nouvelle_demande")
        return

    # Pas de N+1 (ou sans adresse email) : la RH est prévenue directement
    motif = "L'employé n'a pas de N+1 renseigné" if employe and not n_plus_1 else \
            "Le N+1 n'a pas d'adresse email" if n_plus_1 else "Demande sans employé concerné"
    for destinataire in emails_rh(db):
        _ajouter(db, destinataire, f"[PASL-RH] Nouvelle demande de {type_lib} à traiter",
                 f"Bonjour,\n\nUne nouvelle demande a été déposée ({motif.lower()}) :\n\n"
                 f"{_resume(demande)}\n\nTraiter la demande : {_lien(f'/demandes/{demande.id}/traiter-rh')}\n",
                 demande, "notif_rh_nouvelle_demande")


def notifier_avis_n_plus_1(db: Session, demande, avis: str) -> None:
    """Étapes 2 et 3 : le N+1 vient de donner son avis."""
    employe = demande.employe_concerne
    type_lib = (demande.type_demande.libelle if demande.type_demande else "demande").lower()

    if avis == "favorable":
        for destinataire in emails_rh(db):
            _ajouter(db, destinataire, f"[PASL-RH] Demande de {type_lib} à traiter (avis favorable du N+1)",
                     f"Bonjour,\n\nLe N+1 a donné un avis favorable. La demande attend maintenant la décision de la RH :\n\n"
                     f"{_resume(demande)}\n"
                     + (f"Commentaire du N+1 : {demande.commentaire_n_plus_1}\n" if demande.commentaire_n_plus_1 else "")
                     + f"\nTraiter la demande : {_lien(f'/demandes/{demande.id}/traiter-rh')}\n",
                     demande, "notif_rh_avis_favorable")
    elif employe and email_employe(employe):
        _ajouter(db, email_employe(employe), f"[PASL-RH] Votre demande de {type_lib} n'a pas été acceptée",
                 f"Bonjour {employe.prenom},\n\n"
                 f"Votre responsable hiérarchique a émis un avis défavorable sur votre demande de {type_lib}.\n"
                 + (f"Motif : {demande.commentaire_n_plus_1}\n" if demande.commentaire_n_plus_1 else "")
                 + f"\nVous pouvez consulter le détail dans votre espace : {_lien('/espace')}\n",
                 demande, "notif_employe_refus_n_plus_1")


# ------------------------------------------------------------------
# Étape 3 : licenciement et sorties des effectifs
# ------------------------------------------------------------------
def emails_comite(db: Session) -> list[str]:
    """Adresses des comptes actifs du Comité de direction (décideurs des licenciements)."""
    comptes = (
        db.query(models.Utilisateur)
        .filter(models.Utilisateur.role == "Comité de direction", models.Utilisateur.compte_actif.is_(True))
        .all()
    )
    return sorted({c.email for c in comptes if c.email})


def _mail_simple(db: Session, destinataire: str, sujet: str, corps: str, type_mail: str):
    db.add(models.MailAEnvoyer(destinataire=destinataire, sujet=sujet, corps=corps + SIGNATURE, type_mail=type_mail))


def notifier_licenciement_transmis(db: Session, dossier) -> None:
    """Le dossier est transmis au Comité de direction pour décision."""
    e = dossier.employe
    for destinataire in emails_comite(db):
        _mail_simple(db, destinataire,
                     f"[PASL-RH] Licenciement à décider — {e.nom} {e.prenom}",
                     f"Bonjour,\n\nUn dossier de licenciement vous est transmis pour décision.\n\n"
                     f"Employé : {e.nom} {e.prenom}" + (f" ({e.matricule})" if e.matricule else "") + "\n"
                     f"Transmis par : {dossier.transmis_par}\n\n"
                     f"Consulter le dossier et décider : {_lien(f'/licenciements/{dossier.id}')}\n",
                     "licenciement_transmis")


def notifier_licenciement_decide(db: Session, dossier) -> None:
    """Le Comité a décidé : la RH est prévenue."""
    e = dossier.employe
    libelles = {"approuve": "APPROUVÉ", "rejete": "REJETÉ", "complement": "RENVOYÉ POUR COMPLÉMENT"}
    for destinataire in emails_rh(db):
        _mail_simple(db, destinataire,
                     f"[PASL-RH] Licenciement {libelles.get(dossier.decision, '')} — {e.nom} {e.prenom}",
                     f"Bonjour,\n\nLe Comité de direction a statué sur le dossier de licenciement de {e.nom} {e.prenom} : "
                     f"{libelles.get(dossier.decision, dossier.decision)}.\n"
                     + (f"Commentaire : {dossier.decision_commentaire}\n" if dossier.decision_commentaire else "")
                     + f"\nDossier : {_lien(f'/licenciements/{dossier.id}')}\n",
                     "licenciement_decide")


def notifier_n_plus_1_a_reaffecter(db: Session, employe, subordonnes) -> None:
    """Un N+1 quitte PASL : ses collaborateurs n'ont plus de responsable pour valider leurs demandes."""
    liste = "\n".join(f"  - {s.nom} {s.prenom}" + (f" ({s.matricule})" if s.matricule else "") for s in subordonnes)
    for destinataire in emails_rh(db):
        _mail_simple(db, destinataire,
                     f"[PASL-RH] N+1 à réaffecter — départ de {employe.nom} {employe.prenom}",
                     f"Bonjour,\n\n{employe.nom} {employe.prenom} quitte les effectifs. Il/elle était le N+1 de :\n\n{liste}\n\n"
                     f"Pensez à leur attribuer un nouveau responsable dans leur fiche, sinon leurs demandes "
                     f"seront bloquées à l'étape « avis du N+1 ».\n",
                     "n_plus_1_a_reaffecter")
