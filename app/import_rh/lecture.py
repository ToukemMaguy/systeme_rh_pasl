"""Lecture du fichier RH (même présentation que « fixhiier_r.xlsx »), sans rien écrire en base.

Chaque feuille est lue à des positions connues (colonnes et lignes d'en-tête). Avant de lire, on vérifie
que les en-têtes attendus sont bien là : si la RH a renommé une feuille ou inséré une colonne, la lecture
s'arrête avec un message clair au lieu d'importer des données dans les mauvais champs.

Données volontairement IGNORÉES : salaires et montants (feuille Provision congés, colonnes BQ-BR).
"""
from dataclasses import dataclass, field
from datetime import date, datetime

from openpyxl import load_workbook

from .referentiel import cle


class FichierNonConforme(Exception):
    """La présentation du fichier ne correspond pas à celle attendue."""


@dataclass
class LigneEffectif:
    ligne: int
    nom_complet: str
    genre: str
    fonction: str | None
    date_embauche: date
    tel_pro: str | None
    tel_perso: str | None
    email: str | None
    section: str | None           # titre de section : « AGENCE DE CONGO », « YAOUNDE », « MIS A DISPOSITION »...


@dataclass
class LigneProvision:
    ligne: int
    matricule: str
    nom_complet: str
    date_embauche: date | None
    fin_periode: date | None      # colonne BI « Fin Période » : date à laquelle le solde est arrêté
    total: float | None           # colonne BP « Total » = jours dus (JD) + reliquat
    conges: list = field(default_factory=list)   # [(début, fin), ...] périodes de congé déjà prises


@dataclass
class LigneMouvement:
    ligne: int
    nom_complet: str
    ancien_poste: str | None
    ancienne_agence: str | None
    nouveau_poste: str | None
    nouvelle_agence: str | None
    nature: str | None
    date_effet: date | None


@dataclass
class LigneDepart:
    ligne: int
    nom_complet: str
    localisation: str | None
    fonction: str | None
    departement: str | None
    date_embauche: date | None
    date_depart: date | None
    motif: str | None


@dataclass
class ContenuFichier:
    effectif: list
    provision: list
    matricules_entrees: dict      # clé du nom -> [matricules] (feuille Entrées)
    mouvements: list
    departs: list
    avertissements: list
    genre_manquant: list = field(default_factory=list)   # lignes de la feuille Effectif sans genre


def _date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return None


def _texte(v):
    if v is None:
        return None
    s = str(v).strip()
    if isinstance(v, float) and v.is_integer():
        s = str(int(v))
    return s or None


def _feuille(wb, debut_nom):
    for nom in wb.sheetnames:
        if cle(nom).startswith(cle(debut_nom)):
            return wb[nom]
    raise FichierNonConforme(f"Feuille « {debut_nom} » introuvable. Feuilles présentes : {', '.join(wb.sheetnames)}.")


def _verifier_entetes(ws, attendus):
    """attendus : {(ligne, colonne): texte attendu au début de la cellule} (lignes et colonnes à partir de 1)."""
    for (l, c), texte in attendus.items():
        valeur = ws.cell(row=l, column=c).value
        if not cle(valeur).startswith(cle(texte)):
            raise FichierNonConforme(
                f"Feuille « {ws.title.strip()} » : la cellule {ws.cell(row=l, column=c).coordinate} devrait contenir "
                f"« {texte} » mais contient « {valeur} ». Une colonne a-t-elle été ajoutée ou déplacée ?")


def lire_fichier(chemin) -> ContenuFichier:
    try:
        wb = load_workbook(chemin, data_only=True, read_only=True)
    except Exception as e:
        raise FichierNonConforme(f"Impossible d'ouvrir le fichier Excel : {e}")
    avertissements = []

    # ---------- Effectif (liste des employés actuels, par sections) ----------
    ws = _feuille(wb, "Effectif_mois")
    _verifier_entetes(ws, {(2, 7): "Fonction", (2, 8): "Date d'embauche", (2, 9): "Num. tél Prof",
                           (2, 10): "Num. tél personnel", (2, 11): "Adresse Personnelle"})
    effectif, section, genre_manquant = [], None, []
    for n, r in enumerate(ws.iter_rows(values_only=True), start=1):
        r = list(r) + [None] * 12
        nom, fonction, embauche = r[5], r[6], r[7]
        if isinstance(nom, str) and fonction is None and embauche is None:
            titre = nom.strip()
            if titre.isupper() or titre.upper().startswith(("AGENCE", "DIRECTION")):
                section = titre
            continue
        if not (isinstance(nom, str) and _date(embauche)):
            continue
        # Genre : « F » en colonne B ou « H » en colonne D (fichier RH)
        genre = "F" if isinstance(r[1], str) and "F" in r[1].upper() else ("H" if isinstance(r[3], str) and "H" in r[3].upper() else None)
        if not genre:
            genre_manquant.append(n)
            genre = "H"
        effectif.append(LigneEffectif(n, " ".join(nom.split()), genre, _texte(fonction), _date(embauche),
                                      _texte(r[8]), _texte(r[9]), _texte(r[10]), section))

    # ---------- Provision congés (matricule, solde arrêté, périodes de congé) ----------
    ws = _feuille(wb, "Provision_cong")
    _verifier_entetes(ws, {(5, 1): "MAT", (5, 3): "Noms et Pr", (5, 5): "Embauche", (5, 61): "Fin P", (5, 68): "Total"})
    provision = []
    for n, r in enumerate(ws.iter_rows(min_row=6, values_only=True), start=6):
        r = list(r) + [None] * 70
        if not (r[0] is not None and isinstance(r[2], str)):
            continue
        # Périodes de congé : paires de dates consécutives entre les colonnes G et BG
        conges, j = [], 6
        while j < 59:
            d1, d2 = _date(r[j]), _date(r[j + 1])
            if d1 and d2 and d2 >= d1:
                conges.append((d1, d2))
                j += 2
            else:
                j += 1
        total = r[67] if isinstance(r[67], (int, float)) else None
        provision.append(LigneProvision(n, _texte(r[0]), " ".join(r[2].split()), _date(r[4]), _date(r[60]), total, conges))

    # ---------- Entrées (matricules des embauches, en complément) ----------
    ws = _feuille(wb, "Entr")
    matricules = {}
    for r in ws.iter_rows(values_only=True):
        r = list(r) + [None] * 5
        if r[1] is not None and isinstance(r[2], str) and cle(r[2]) not in ("NOMS ET PRENOMS",):
            mat = _texte(r[1])
            if mat and mat.upper() != "MAT":
                matricules.setdefault(cle(r[2]), []).append(mat)

    # ---------- Mouvements internes ----------
    ws = _feuille(wb, "Mouvements internes")
    mouvements = []
    for n, r in enumerate(ws.iter_rows(values_only=True), start=1):
        r = list(r) + [None] * 10
        if isinstance(r[1], str) and cle(r[1]) not in ("NOMS ET PRENOMS", "") and _date(r[7]):
            mouvements.append(LigneMouvement(n, " ".join(r[1].split()), _texte(r[2]), _texte(r[3]), _texte(r[4]),
                                             _texte(r[5]), _texte(r[6]), _date(r[7])))

    # ---------- Départs ----------
    ws = _feuille(wb, "Départs")
    departs = []
    for n, r in enumerate(ws.iter_rows(values_only=True), start=1):
        r = list(r) + [None] * 10
        if isinstance(r[1], str) and cle(r[1]) not in ("NOMS ET PRENOMS", "") and _date(r[7]):
            departs.append(LigneDepart(n, " ".join(r[1].split()), _texte(r[2]), _texte(r[3]), _texte(r[5]),
                                       _date(r[6]), _date(r[7]), _texte(r[8])))

    wb.close()
    if not effectif:
        raise FichierNonConforme("Aucun employé trouvé dans la feuille Effectif : le fichier est-il le bon ?")
    return ContenuFichier(effectif, provision, matricules, mouvements, departs, avertissements, genre_manquant)
