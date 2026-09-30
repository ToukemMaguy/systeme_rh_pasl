"""
Script d'envoi des mails en attente.

Lancé par Windows Task Scheduler (ou manuellement pour tester).

Usage :
    python -m app.scripts.envoyer_mails
"""
import smtplib
import os
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv

from app.database import SessionLocal
from app import models

# Charge les variables d'environnement depuis .env
load_dotenv()

# Pause entre deux mails (limites d'envoi du fournisseur ; 1,5 s convenait à Mailtrap)
PAUSE_ENTRE_MAILS = float(os.getenv("SMTP_PAUSE", "1.5"))

SMTP_SERVER = os.getenv("SMTP_SERVER", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "PASL-RH")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", SMTP_USER)


def envoyer_mail(destinataire, sujet, corps):
    """Envoie un mail via SMTP. Lève une exception en cas d'erreur."""
    msg = MIMEMultipart()
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    msg["To"] = destinataire
    msg["Subject"] = sujet
    msg.attach(MIMEText(corps, "plain", "utf-8"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as serveur:
        serveur.starttls()
        serveur.login(SMTP_USER, SMTP_PASSWORD)
        serveur.send_message(msg)


def _erreur_du_destinataire(e: Exception) -> bool:
    """Vrai si l'échec vient de CE mail (adresse refusée, contenu rejeté), faux si c'est le serveur qui
    est indisponible. Attention : toutes les erreurs smtplib héritent de OSError, d'où ce tri explicite."""
    if "too many" in str(e).lower() or "rate limit" in str(e).lower():
        return False
    return isinstance(e, (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError))


def traiter_file_attente():
    """Parcourt la file d'attente et envoie les mails en attente."""
    db = SessionLocal()
    try:
        mails = (
            db.query(models.MailAEnvoyer)
            .filter_by(statut="en_attente")
            .order_by(models.MailAEnvoyer.date_creation)
            .all()
        )

        if not mails:
            print(f"[{datetime.now()}] Aucun mail à envoyer.")
            return

        print(f"[{datetime.now()}] {len(mails)} mail(s) à envoyer...")

        for mail in mails:
            # Vérifie que le destinataire est valide
            if not mail.destinataire or "@" not in mail.destinataire or len(mail.destinataire) < 5:
                mail.statut = "erreur"
                mail.message_erreur = f"Destinataire invalide : {mail.destinataire!r}"
                print(f"  [SKIP] Destinataire invalide : {mail.destinataire!r}")
                continue

            try:
                envoyer_mail(mail.destinataire, mail.sujet, mail.corps)
                mail.statut = "envoye"
                mail.date_envoi = datetime.now()
                # [PRODUCTION - POINT 6] enregistré tout de suite : si le script s'arrête en cours de route,
                # les mails déjà partis ne seront pas renvoyés au passage suivant
                db.commit()
                print(f"  [OK] Envoyé à {mail.destinataire}")
                time.sleep(PAUSE_ENTRE_MAILS)
            except Exception as e:
                db.rollback()
                message_erreur = str(e)
                if _erreur_du_destinataire(e):
                    # Adresse refusée ou message rejeté : inutile de réessayer
                    mail.statut = "erreur"
                    mail.message_erreur = message_erreur[:500]
                    db.commit()
                    print(f"  [ERREUR] Pour {mail.destinataire} : {e}")
                else:
                    # [PRODUCTION - POINT 6] serveur injoignable, limite d'envoi, identifiants... : les mails
                    # RESTENT en attente et partiront au prochain passage (toutes les 10 minutes)
                    print(f"  [PAUSE] Envoi interrompu ({e}) : nouvel essai au prochain passage.")
                    break

        db.commit()
        print(f"[{datetime.now()}] Terminé.")

    finally:
        db.close()


if __name__ == "__main__":
    traiter_file_attente()