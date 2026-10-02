"""Assigne le Directeur Général comme N+1 des directeurs, des chefs de département,
du responsable réclamations et du responsable marketing et communication.

Les chefs de service ne sont PAS concernés (leur N+1 est le directeur de leur direction).

Usage :
    venv\\Scripts\\python.exe -m app.scripts.assigner_dg_n_plus_1              # simulation
    venv\\Scripts\\python.exe -m app.scripts.assigner_dg_n_plus_1 --appliquer  # applique
"""
import sys
from sqlalchemy.orm import Session
from ..database import SessionLocal
from .. import models
from ..regles_rh import DG_ID


# Mots-clés de poste concernés (comparaison insensible à la casse).
# NB : "chef département" (sans "de") capture à la fois "chef de département" et "chef département".
# NB : "chef de service" est volontairement ABSENT (le DG est leur N+2, pas leur N+1).
POSTES_CIBLES = [
    "directeur",
    "chef département",
    "responsable réclamation",
    "responsable reclamation",
    "responsable marketing",
    "responsable communication",
]


def _poste_concerne(intitule: str) -> bool:
    if not intitule:
        return False
    libelle = intitule.lower()
    return any(cible in libelle for cible in POSTES_CIBLES)


def main(appliquer: bool):
    db: Session = SessionLocal()
    try:
        dg = db.query(models.Employe).get(DG_ID)
        if not dg:
            print(f"❌ Aucun employé avec id={DG_ID}.")
            print("   Vérifie la constante DG_ID dans app/regles_rh.py.")
            return

        print(f"🎯 Directeur Général : {dg.nom} {dg.prenom} (id={dg.id}, matricule={dg.matricule})\n")

        employes = (
            db.query(models.Employe)
            .filter(models.Employe.statut == "actif", models.Employe.id != DG_ID)
            .all()
        )

        a_modifier = []
        deja_bon = []
        for e in employes:
            poste_lib = e.poste.intitule if e.poste else ""
            if not _poste_concerne(poste_lib):
                continue
            if e.n_plus_1_id == DG_ID:
                deja_bon.append(e)
                continue
            a_modifier.append(e)

        if deja_bon:
            print(f"✅ {len(deja_bon)} employé(s) ont déjà le DG comme N+1 :")
            for e in deja_bon:
                print(f"  • {e.nom} {e.prenom:30s} | {e.poste.intitule if e.poste else '—'}")
            print()

        if not a_modifier:
            print("✅ Aucun changement à faire.")
            return

        print(f"📋 {len(a_modifier)} employé(s) à mettre à jour :\n")
        for e in a_modifier:
            avant = f"{e.n_plus_1.nom} {e.n_plus_1.prenom}" if e.n_plus_1 else "—"
            print(f"  • id={e.id:5d} | {e.nom} {e.prenom:30s} | {e.poste.intitule if e.poste else '—':45s} | N+1 actuel : {avant}")

        if not appliquer:
            print("\n⚠️  Mode SIMULATION. Relance avec --appliquer pour enregistrer.")
            return

        for e in a_modifier:
            e.n_plus_1_id = DG_ID
        db.commit()
        print(f"\n✅ {len(a_modifier)} employé(s) mis à jour avec le DG comme N+1.")
    finally:
        db.close()


if __name__ == "__main__":
    main("--appliquer" in sys.argv)