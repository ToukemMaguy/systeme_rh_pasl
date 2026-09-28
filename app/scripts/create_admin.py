"""Crée ou met à jour un compte utilisateur. Lancer : python -m app.scripts.create_admin"""
import getpass
from app.database import SessionLocal
from app import models, auth

db = SessionLocal()
nom = input("Nom complet : ")
email = input("Email (identifiant de connexion) : ")
role = input("Rôle (Administrateur / Chef RH / Assistant RH / Comité de direction / Employé) : ") or "Administrateur"
mot_de_passe = getpass.getpass("Mot de passe : ")

existant = db.query(models.Utilisateur).filter_by(email=email).first()
if existant:
    existant.mot_de_passe_hash = auth.hash_password(mot_de_passe)
    existant.role = role
    existant.nom = nom
    print("Compte existant mis à jour.")
else:
    db.add(models.Utilisateur(
        nom=nom, email=email, role=role,
        mot_de_passe_hash=auth.hash_password(mot_de_passe),
    ))
    print("Compte créé.")

db.commit()
db.close()