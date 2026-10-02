"""Import du fichier RH (même présentation que fixhiier_r.xlsx) en ligne de commande.

    python -m app.scripts.import_fichier_rh data\\fixhiier_r.xlsx                          # SIMULATION (rien n'est écrit)
    python -m app.scripts.import_fichier_rh data\\fixhiier_r.xlsx --appliquer              # import réel
    python -m app.scripts.import_fichier_rh data\\fixhiier_r.xlsx --repartir-de-zero --appliquer
        -> AVANT la mise en production seulement : efface toutes les données du personnel puis recharge le fichier

Un rapport Excel détaillé est écrit dans data\\rapport_import_AAAAMMJJ_HHMM.xlsx (dossier non versionné).
Ensuite, la RH fait les mises à jour elle-même depuis l'application : menu « Mettre à jour depuis le fichier RH ».
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

from app.database import SessionLocal
from app import journal
from app.import_rh.lecture import FichierNonConforme, lire_fichier
from app.import_rh.moteur import importer, repartir_de_zero
from app.import_rh.rapport_excel import rapport_en_excel


def main():
    parser = argparse.ArgumentParser(description="Import du fichier RH dans PASL-RH")
    parser.add_argument("fichier")
    parser.add_argument("--appliquer", action="store_true", help="enregistre réellement (sinon simulation)")
    parser.add_argument("--repartir-de-zero", action="store_true", help="efface les données du personnel avant l'import")
    args = parser.parse_args()

    try:
        contenu = lire_fichier(args.fichier)
    except FichierNonConforme as e:
        print(f"FICHIER REFUSÉ : {e}")
        sys.exit(1)

    journal.definir_auteur(nom="Import du fichier RH (script)")
    db = SessionLocal()
    try:
        if args.repartir_de_zero:
            if not args.appliquer:
                print("--repartir-de-zero n'a d'effet qu'avec --appliquer (la simulation part toujours des données actuelles).")
            else:
                print("ATTENTION : toutes les données du personnel (employés, absences, demandes, soldes, comptes « Employé »...)")
                print("vont être EFFACÉES puis rechargées depuis le fichier. Les comptes Administrateur / RH / Comité sont gardés.")
                if input("Tapez OUI pour confirmer : ").strip() != "OUI":
                    print("Annulé.")
                    return
                resultat = repartir_de_zero(db)
                print(f"Données effacées ({resultat['employe_supprimes']} compte(s) Employé supprimé(s), "
                      f"{resultat['autres_detaches']} compte(s) détaché(s) de leur fiche).")
        rapport = importer(db, contenu, appliquer=args.appliquer, auteur="Import du fichier RH (script)")
    finally:
        db.close()

    print(rapport.resume())
    Path("data").mkdir(exist_ok=True)
    chemin = Path("data") / f"rapport_import_{datetime.now():%Y%m%d_%H%M}.xlsx"
    chemin.write_bytes(rapport_en_excel(rapport))
    print(f"Rapport détaillé : {chemin}")
    if not args.appliquer:
        print("\nC'était une SIMULATION. Pour enregistrer : relancez avec --appliquer")


if __name__ == "__main__":
    main()
