"""
Script d'import des données RH depuis le fichier Excel source vers MySQL.
À lancer une fois l'environnement configuré : python -m app.scripts.import_excel
"""
import re
import unicodedata
import datetime
import pandas as pd
from app.database import SessionLocal
from app import models

EXCEL_PATH = "data/effectif.xlsx"

# ---------- Normalisation pour le rapprochement nom+prénom ----------

def normalize(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s


def to_date(value):
    if isinstance(value, (datetime.datetime, pd.Timestamp)):
        return value.date()
    return None


# ---------- Aide pour éviter les doublons dans les tables de référence ----------

def get_or_create(db, model, filtre, **kwargs):
    obj = db.query(model).filter_by(**filtre).first()
    if obj:
        return obj
    obj = model(**{**filtre, **kwargs})
    db.add(obj)
    db.flush()  # attribue l'id sans valider toute la transaction
    return obj


def departement_et_agence_pour_section(db, section):
    """
    Détermine département + agence à partir du nom de section trouvé
    dans la feuille Effectif. Règle validée : DG = pas d'agence ;
    tout le reste (agences nommées + villes régionales) rattaché à
    'Exploitation et Réseau' avec une agence propre.
    """
    if section is None or "DIRECTION GENERALE" in section or "HEAD OFFICE" in section:
        dep = get_or_create(db, models.Departement, {"nom": "Direction Générale"})
        return dep, None

    if "MIS A DISPOSITION" in section:
        # Cas particulier à faire valider avec l'encadrant : rattaché à la
        # DG en attendant une règle métier plus précise.
        dep = get_or_create(db, models.Departement, {"nom": "Direction Générale"})
        return dep, None

    dep = get_or_create(db, models.Departement, {"nom": "Exploitation et Réseau"})
    nom_agence = section.replace("AGENCE DE", "").replace("AGENCE", "").strip().title()
    if not nom_agence:
        nom_agence = section.title()
    agence = get_or_create(db, models.Agence, {"nom": nom_agence})
    return dep, agence


def main():
    db = SessionLocal()
    xls = pd.ExcelFile(EXCEL_PATH)

    rapport_ambigus = []
    rapport_non_matches = []

    # ---------- 1. Grades de base (si pas déjà seedés) ----------
    for libelle, niveau in [("Employé", 1), ("Agent de maîtrise", 2), ("Cadre", 3)]:
        get_or_create(db, models.Grade, {"libelle": libelle}, niveau_hierarchique=niveau)
    grade_defaut = db.query(models.Grade).filter_by(libelle="Employé").first()
    db.commit()

    # ---------- 2. Matricules depuis "Entrées" ----------
    ent = pd.read_excel(xls, sheet_name="Entrées", header=None, skiprows=4)
    matricules = {}  # nom normalisé -> [matricules]
    for _, row in ent.iterrows():
        mat, nom = row[1], row[2]
        if isinstance(nom, str) and pd.notna(mat):
            matricules.setdefault(normalize(nom), []).append(str(mat))

    # ---------- 3. Import des employés depuis "Effectif_mois août 2026" ----------
    feuille_effectif = [s for s in xls.sheet_names if s.strip().startswith("Effectif_mois")][0]
    eff = pd.read_excel(xls, sheet_name=feuille_effectif, header=None)

    employes_par_nom = {}  # nom normalisé -> objet Employe (pour les étapes suivantes)
    current_section = None

    for _, row in eff.iterrows():
        col1, col2, col3, col5, col6, col7, col8, col9, col10 = (
            row[1], row[2], row[3], row[5], row[6], row[7], row[8], row[9], row[10]
        )
        # Ligne d'en-tête de section (département/agence)
        if isinstance(col5, str) and pd.isna(col7) and pd.isna(col6):
            label = col5.strip()
            if label.isupper() or label.startswith("AGENCE") or label.startswith("DIRECTION"):
                current_section = label
            continue

        # Ligne employé : présence d'une vraie date d'embauche
        if not (isinstance(col7, (datetime.datetime, pd.Timestamp)) and isinstance(col5, str)):
            continue

        nom_complet = col5.strip()
        cle = normalize(nom_complet)

        # Genre : cherché sur plusieurs colonnes possibles (fichier pas 100% uniforme)
        genre = None
        if isinstance(col3, str) and "H" in col3:
            genre = "H"
        elif isinstance(col1, str) and "F" in col1:
            genre = "F"
        elif pd.notna(col2):
            genre = "H"
        else:
            genre = "F"

        # Séparer nom/prénom au mieux (première partie = nom de famille,
        # convention utilisée dans le fichier). À vérifier avec l'encadrant
        # sur les cas composés.
        parts = nom_complet.split(" ", 1)
        nom = parts[0]
        prenom = parts[1] if len(parts) > 1 else ""

        dep, agence = departement_et_agence_pour_section(db, current_section)
        poste = get_or_create(db, models.Poste, {"intitule": (col6.strip() if isinstance(col6, str) else "Non renseigné")})

        mats = matricules.get(cle)
        if mats and len(mats) > 1:
            rapport_ambigus.append({"nom": nom_complet, "matricules_possibles": mats})
        matricule = mats[0] if mats else None

        employe = db.query(models.Employe).filter_by(nom=nom, prenom=prenom, date_embauche=to_date(col7)).first()
        if not employe:
            employe = models.Employe(
                matricule=matricule,
                nom=nom,
                prenom=prenom,
                genre=genre,
                date_embauche=to_date(col7),
                telephone_pro=str(col8) if pd.notna(col8) else None,
                telephone_perso=str(col9) if pd.notna(col9) else None,
                email_perso=str(col10) if pd.notna(col10) else None,
                statut="actif",
                departement_id=dep.id,
                agence_id=agence.id if agence else None,
                poste_id=poste.id,
                grade_id=grade_defaut.id,
            )
            db.add(employe)
            db.flush()

            db.add(models.Affectation(
                employe_id=employe.id,
                departement_id=dep.id,
                agence_id=agence.id if agence else None,
                poste_id=poste.id,
                grade_id=grade_defaut.id,
                date_debut=to_date(col7),
                type_mouvement="embauche",
            ))

        employes_par_nom[cle] = employe

    db.commit()
    print(f"{len(employes_par_nom)} employés importés depuis '{feuille_effectif}'.")

    # ---------- 4. Départs ----------
    dep_df = pd.read_excel(xls, sheet_name="Départs", header=None, skiprows=3)
    n_departs = 0
    for _, row in dep_df.iterrows():
        nom_complet = row[1]
        if not isinstance(nom_complet, str):
            continue
        cle = normalize(nom_complet)
        employe = employes_par_nom.get(cle)
        if not employe:
            rapport_non_matches.append({"source": "Départs", "nom": nom_complet})
            continue

        date_arret = to_date(row[7])
        db.add(models.Depart(
            employe_id=employe.id,
            date_depart=date_arret,
            motif=str(row[8]) if pd.notna(row[8]) else None,
            type_depart=str(row[8]) if pd.notna(row[8]) else None,
        ))
        employe.statut = "inactif"

        # Clôture l'affectation en cours
        affectation_ouverte = (
            db.query(models.Affectation)
            .filter_by(employe_id=employe.id, date_fin=None)
            .first()
        )
        if affectation_ouverte:
            affectation_ouverte.date_fin = date_arret
        n_departs += 1

    db.commit()
    print(f"{n_departs} départs importés (sur {len(dep_df)} lignes).")

    # ---------- 5. Mouvements internes ----------
    mv_df = pd.read_excel(xls, sheet_name="Mouvements internes", header=None, skiprows=3)
    n_mvts = 0
    for _, row in mv_df.iterrows():
        nom_complet = row[1]
        if not isinstance(nom_complet, str):
            continue
        cle = normalize(nom_complet)
        employe = employes_par_nom.get(cle)
        if not employe:
            rapport_non_matches.append({"source": "Mouvements internes", "nom": nom_complet})
            continue

        nouveau_poste = get_or_create(db, models.Poste, {"intitule": str(row[4]).strip()}) if pd.notna(row[4]) else None
        nouvelle_agence = get_or_create(db, models.Agence, {"nom": str(row[5]).strip()}) if pd.notna(row[5]) else None
        date_effet = to_date(row[7])
        nature = str(row[6]).strip().lower() if pd.notna(row[6]) else "mutation_departement"
        if date_effet is None:
            rapport_non_matches.append({"source": "Mouvements internes (date manquante)", "nom": nom_complet})
            continue

        # Clôture l'affectation en cours à la veille du mouvement
        affectation_ouverte = (
            db.query(models.Affectation)
            .filter_by(employe_id=employe.id, date_fin=None)
            .first()
        )
        if affectation_ouverte and date_effet:
            affectation_ouverte.date_fin = date_effet

        db.add(models.Affectation(
            employe_id=employe.id,
            departement_id=employe.departement_id,
            agence_id=nouvelle_agence.id if nouvelle_agence else employe.agence_id,
            poste_id=nouveau_poste.id if nouveau_poste else employe.poste_id,
            grade_id=employe.grade_id,
            date_debut=date_effet,
            type_mouvement=nature,
            motif=f"Import : {row[2]} -> {row[4]}",
        ))

        if nouveau_poste:
            employe.poste_id = nouveau_poste.id
        if nouvelle_agence:
            employe.agence_id = nouvelle_agence.id
        n_mvts += 1

    db.commit()
    print(f"{n_mvts} mouvements internes importés (sur {len(mv_df)} lignes).")

    # ---------- 6. Provision congés (solde_conges) ----------
    # ATTENTION : mapping des colonnes JD/Reliquat/Total à faire valider avec
    # l'encadrant — hypothèse retenue : Total = jours alloués cumulés,
    # Reliquat = jours restants, jours_pris = Total - Reliquat.
    pc_df = pd.read_excel(xls, sheet_name="Provision_congés_24j_", header=None, skiprows=5)
    n_soldes = 0
    for _, row in pc_df.iterrows():
        nom_complet = row[2]
        if not isinstance(nom_complet, str):
            continue
        cle = normalize(nom_complet)
        employe = employes_par_nom.get(cle)
        if not employe:
            continue

        total = row[67] if pd.notna(row[67]) else None
        reliquat = row[66] if pd.notna(row[66]) else None
        if total is None:
            continue

        existant = db.query(models.SoldeConge).filter_by(employe_id=employe.id, annee=2026).first()
        if existant:
            continue
        db.add(models.SoldeConge(
            employe_id=employe.id,
            annee=2026,
            jours_alloues=total,
            jours_pris=(total - reliquat) if reliquat is not None else None,
            jours_restants=reliquat,
        ))
        n_soldes += 1

    db.commit()
    print(f"{n_soldes} soldes de congés importés.")

    # ---------- 7. Rapport des cas ambigus / non matchés ----------
    if rapport_ambigus:
        pd.DataFrame(rapport_ambigus).to_csv("data/rapport_ambigus.csv", index=False)
        print(f"{len(rapport_ambigus)} cas ambigus (plusieurs matricules pour un même nom) -> data/rapport_ambigus.csv")

    if rapport_non_matches:
        pd.DataFrame(rapport_non_matches).to_csv("data/rapport_non_matches.csv", index=False)
        print(f"{len(rapport_non_matches)} lignes non rapprochées à un employé -> data/rapport_non_matches.csv")

    db.close()


if __name__ == "__main__":
    main()