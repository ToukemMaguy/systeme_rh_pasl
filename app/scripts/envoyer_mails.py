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
                print(f"  [OK] Envoyé à {mail.destinataire}")
                time.sleep(1.5)  # Pause pour respecter la limite Mailtrap
            except Exception as e:
                message_erreur = str(e)
                # Si c'est une limite de débit, on remet en attente pour un prochain envoi
                if "Too many emails" in message_erreur or "rate limit" in message_erreur.lower():
                    print(f"  [RETRY] Limite atteinte pour {mail.destinataire} — sera renvoyé plus tard")
                    # On ne change PAS le statut → il restera "en_attente"
                else:
                    mail.statut = "erreur"
                    mail.message_erreur = message_erreur[:500]
                    print(f"  [ERREUR] Pour {mail.destinataire} : {e}")

        db.commit()
        print(f"[{datetime.now()}] Terminé.")

    finally:
        db.close()


if __name__ == "__main__":
    traiter_file_attente()