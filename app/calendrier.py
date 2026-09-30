"""[CORRECTIF B9] Calendrier de travail : jours ouvrables et jours fériés du Cameroun.

Avant : un congé du vendredi au lundi comptait 4 jours (dimanche et samedi inclus).
Le Code du travail camerounais (art. 89) exprime le congé en jours OUVRABLES :
tous les jours sauf le dimanche et les jours fériés.

Validé par la RH de PASL : semaine de travail de 6 jours, du lundi au samedi.
Un jour de congé posé un samedi est donc décompté ; le dimanche et les jours fériés ne le sont pas.

À faire par la RH chaque année :
  - compléter FETES_A_DATE_VARIABLE (fêtes musulmanes, annoncées par le gouvernement).
"""
from datetime import date, timedelta

# 0 = lundi ... 5 = samedi, 6 = dimanche
JOURS_OUVRABLES = {0, 1, 2, 3, 4, 5}

# Fêtes à date fixe (mois, jour)
FETES_FIXES = [
    (1, 1),    # Jour de l'an
    (2, 11),   # Fête de la Jeunesse
    (5, 1),    # Fête du Travail
    (5, 20),   # Fête nationale
    (8, 15),   # Assomption
    (12, 25),  # Noël
]

# Fêtes dont la date est fixée chaque année par décision officielle (Aïd el-Fitr, Aïd el-Adha / Tabaski).
# À compléter par la RH dès l'annonce, sous la forme : 2027: [date(2027, 3, 10), date(2027, 5, 17)],
FETES_A_DATE_VARIABLE: dict[int, list[date]] = {}


def _paques(annee: int) -> date:
    """Date du dimanche de Pâques (algorithme de Meeus/Jones/Butcher)."""
    a = annee % 19
    b, c = divmod(annee, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mois = (h + l - 7 * m + 114) // 31
    jour = (h + l - 7 * m + 114) % 31 + 1
    return date(annee, mois, jour)


def jours_feries(annee: int) -> set[date]:
    """Ensemble des jours fériés de l'année."""
    paques = _paques(annee)
    feries = {date(annee, m, j) for m, j in FETES_FIXES}
    feries.add(paques - timedelta(days=2))   # Vendredi saint
    feries.add(paques + timedelta(days=39))  # Ascension
    feries.update(FETES_A_DATE_VARIABLE.get(annee, []))
    return feries


def nb_jours_ouvrables(debut: date | None, fin: date | None) -> int:
    """Nombre de jours ouvrables entre debut et fin inclus (dimanches et jours fériés exclus)."""
    if not debut or not fin or fin < debut:
        return 0
    feries = set()
    for annee in range(debut.year, fin.year + 1):
        feries |= jours_feries(annee)
    total = 0
    jour = debut
    while jour <= fin:
        if jour.weekday() in JOURS_OUVRABLES and jour not in feries:
            total += 1
        jour += timedelta(days=1)
    return total


def nb_jours_calendaires(debut: date | None, fin: date | None) -> int:
    """Nombre de jours calendaires entre debut et fin inclus."""
    if not debut or not fin or fin < debut:
        return 0
    return (fin - debut).days + 1
