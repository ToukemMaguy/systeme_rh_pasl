"""
Ajoute les postes manquants identifiés en comparant l'organigramme PASL (PDF)
à la table `postes` existante.

Usage :
    python -m app.scripts.ajouter_postes_organigramme              # aperçu seulement (rien n'est modifié)
    python -m app.scripts.ajouter_postes_organigramme --executer   # applique réellement les ajouts

Le script est sans risque à relancer plusieurs fois : il ignore automatiquement
les postes qui existent déjà (comparaison insensible à la casse/aux espaces).
"""
import sys
from app.database import SessionLocal
from app import models

POSTES_A_AJOUTER = [
    "Directeur Juridique",
    "Chef Département Audit Interne",
    "Chef Département Contrôle Permanent",
    "Responsable Marketing et Communication",
    "Chef Service Recouvrement",
    "Chef Service Technologie",
    "Chef Service Opérations",
    "Chef Service Risque",
    "Chef Service Moyens Généraux",
    "Assistant(e) Juriste",
    "Assistant(e) Marketing",
    "Chargé(e) de Réclamations",
    "Analyste Risque",
    "Superviseur Régional",
]


def _normalise(texte: str) -> str:
    return " ".join(texte.strip().lower().split())


def main():
    executer = "--executer" in sys.argv
    db = SessionLocal()

    existants = {_normalise(p.intitule) for p in db.query(models.Poste).all()}

    a_creer = [nom for nom in POSTES_A_AJOUTER if _normalise(nom) not in existants]
    deja_presents = [nom for nom in POSTES_A_AJOUTER if _normalise(nom) in existants]

    print(f"=== Postes de l'organigramme à vérifier : {len(POSTES_A_AJOUTER)} ===\n")

    if deja_presents:
        print(f"Déjà présents en base, ignorés ({len(deja_presents)}) :")
        for nom in deja_presents:
            print(f"  - {nom}")
        print()

    if not a_creer:
        print("Rien à ajouter : tous les postes existent déjà.")
        db.close()
        return

    print(f"À créer ({len(a_creer)}) :")
    for nom in a_creer:
        print(f"  + {nom}")
    print()

    if not executer:
        print("--- APERÇU SEULEMENT, rien n'a été modifié en base ---")
        print("Relance avec --executer pour appliquer ces ajouts :")
        print("  python -m app.scripts.ajouter_postes_organigramme --executer")
        db.close()
        return

    for nom in a_creer:
        db.add(models.Poste(intitule=nom))
    db.commit()

    print(f"=== {len(a_creer)} poste(s) ajouté(s) avec succès. ===")
    db.close()


if __name__ == "__main__":
    main()