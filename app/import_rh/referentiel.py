"""Table de traduction du fichier RH (fixhiier_r.xlsx) vers l'organisation officielle de la PASL.

La RH garde son fichier tel quel : c'est l'application qui « comprend » ses différentes écritures.
Sources : organigramme PASL 2024, feuille « SUIVI Du Personnel 2026 », réponses de la RH (30/09/2026).

Si une nouvelle écriture apparaît un jour dans le fichier, le rapport d'import la signale :
il suffit alors d'ajouter UNE ligne dans le dictionnaire concerné ci-dessous.
"""
import re
import unicodedata

# ------------------------------------------------------------------
# Siège (n'est PAS une agence : les employés du siège n'ont pas d'agence dans l'application)
# ------------------------------------------------------------------
LIBELLE_SIEGE = "Siège (Douala - Koumassi)"
SIEGE = "SIEGE"          # valeur interne renvoyée par lieu_officiel()
MAD = "MAD"              # section des agents mis à disposition (registre séparé, pas des employés)

# ------------------------------------------------------------------
# Directions et départements (organigramme 2024)
# ------------------------------------------------------------------
DIRECTIONS = {
    "DG": "Direction Générale",
    "AUDIT": "Département de l'Audit Interne",
    "DCP": "Département du Contrôle Permanent",
    "DRHMG": "Département des Ressources Humaines et Moyens Généraux",
    "DCF": "Direction Comptable et Financière",
    "DOT": "Direction des Opérations et de la Technologie",
    "DER": "Direction des Engagements et du Recouvrement",
    "DEXRA": "Direction de l'Exploitation et du Réseau d'Agences",
    "DJ": "Direction Juridique",
}

# ------------------------------------------------------------------
# Agences (nom officiel -> ville)
# ------------------------------------------------------------------
AGENCES = {
    "Agence de Bépanda": "Douala", "Agence de Bonabéri": "Douala", "Agence de Bonamoussadi": "Douala",
    "Agence de Congo": "Douala", "Agence de Mboppi": "Douala", "Agence de Ndokoti": "Douala",
    "Agence de Village": "Douala",
    "Agence d'Etoudi": "Yaoundé", "Agence de Mfoundi": "Yaoundé", "Agence de Mokolo": "Yaoundé",
    "Agence de Mvog-Mbi": "Yaoundé",
    "Agence de Bafoussam": "Bafoussam", "Agence de Bertoua": "Bertoua", "Agence de Maroua": "Maroua",
}


def cle(texte) -> str:
    """Forme comparable : sans accents, majuscules, ponctuation remplacée par des espaces."""
    if texte is None:
        return ""
    texte = unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode("ascii").upper()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", texte).split())


# Mot-clé trouvé dans l'écriture du fichier -> agence officielle (l'ordre compte : du plus précis au plus large)
_MOTS_AGENCES = [
    ("MVOG", "Agence de Mvog-Mbi"), ("MVOMGBI", "Agence de Mvog-Mbi"),
    ("BEPANDA", "Agence de Bépanda"),
    ("BONAMOUSSADI", "Agence de Bonamoussadi"), ("BSSADI", "Agence de Bonamoussadi"),
    ("BONABERI", "Agence de Bonabéri"), ("BONBERI", "Agence de Bonabéri"),
    ("CONGO", "Agence de Congo"), ("MBOPPI", "Agence de Mboppi"), ("MBPOPPI", "Agence de Mboppi"),
    ("NDOKOTI", "Agence de Ndokoti"), ("VILLAGE", "Agence de Village"),
    ("ETOUDI", "Agence d'Etoudi"), ("MFOUNDI", "Agence de Mfoundi"), ("MOKOLO", "Agence de Mokolo"),
    ("BAFOUSSAM", "Agence de Bafoussam"), ("BERTOUA", "Agence de Bertoua"), ("MAROUA", "Agence de Maroua"),
]
# Écritures qui désignent le siège (décision RH : la section « YAOUNDE » = personnel de la Direction Générale)
_MOTS_SIEGE = ("SIEGE", "HEAD OFFICE", "DIRECTION GENERALE", "YAOUNDE", "YDE", "AUDIT")
_VIDES = ("", "NA", "N A", "NON APPLICABLE")


def lieu_officiel(texte):
    """Écriture du fichier -> nom d'agence officiel, SIEGE, MAD, None (vide) ou False (inconnu : à signaler)."""
    c = cle(texte)
    if c in _VIDES:
        return None
    if "MIS A DISPOSITION" in c or c == "MAD":
        return MAD
    for mot, agence in _MOTS_AGENCES:          # « YAOUNDE - MVOGMBI » -> Mvog-Mbi (l'agence prime sur la ville)
        if mot in c:
            return agence
    if any(c == m or c.startswith(m + " ") or c.endswith(" " + m) for m in _MOTS_SIEGE) or c == "DOUALA":
        return SIEGE
    return False


# ------------------------------------------------------------------
# Codes de direction (feuille Départs) -> direction officielle
# ------------------------------------------------------------------
_CODES_DIRECTION = {
    "DEX": "DEXRA", "DEXRA": "DEXRA", "EXPLOITATION": "DEXRA",
    "OPERATION": "DOT", "OPERATIONS": "DOT", "DOT": "DOT", "DSI": "DOT", "INFORMATIQUE": "DOT", "IT": "DOT",
    "CREDIT": "DER", "DER": "DER", "RECOUVREMENT": "DER",
    "AUDIT": "AUDIT", "AUDIT INTERNE": "AUDIT", "IA": "AUDIT",
    "CIC": "DCP", "RCIC": "DCP", "IC": "DCP", "ICRM": "DCP", "CONTROLE INTERNE": "DCP", "CONTROLE PERMANENT": "DCP",
    "DRHMG": "DRHMG", "DHMG": "DRHMG", "CDRHMG": "DRHMG", "HR": "DRHMG", "RH": "DRHMG", "GIS": "DRHMG",
    "DCF": "DCF", "DAF": "DCF",
    "DG": "DG", "JURIDIQUE": "DJ", "AFF JUR ADM": "DJ",
}
# Codes à ignorer : « LAA » = ancien poste du Directeur Général Adjoint, qui n'existe plus (décision RH)
CODES_IGNORES = {"LAA"}


def direction_depuis_code(texte):
    return _CODES_DIRECTION.get(cle(texte))


# ------------------------------------------------------------------
# Fonctions (feuille Effectif) -> (poste officiel, code direction)
# ------------------------------------------------------------------
_FONCTIONS = {
    "Managing Director": ("Directeur Général", "DG"),
    "Deputy Managing Director-LAA": ("Directeur Général Adjoint", "DG"),
    "Executive Assisant": ("Assistant(e) de Direction", "DG"),
    "Executive Assistant": ("Assistant(e) de Direction", "DG"),
    "Responsable Réclamations": ("Responsable Réclamations", "DG"),
    "Internal Auditor": ("Auditeur Interne", "AUDIT"),
    "Auditeur Interne junior": ("Auditeur Interne Junior", "AUDIT"),
    "Auditeur Junior 2": ("Auditeur Interne Junior", "AUDIT"),
    "Chef Service Contrôle Interne": ("Chef Service Contrôle Interne et Conformité", "DCP"),
    "Internal Controller": ("Contrôleur Interne", "DCP"),
    "Contrôleur Interne": ("Contrôleur Interne", "DCP"),
    "Internal Controller Sénior": ("Contrôleur Interne Senior", "DCP"),
    "Head of Human Resources Department": ("Chef Département RH et Moyens Généraux", "DRHMG"),
    "Chef service ressources humaines": ("Chef Service Ressources Humaines", "DRHMG"),
    "Assistante Ressources Humaines": ("Assistant(e) Ressources Humaines", "DRHMG"),
    "Driver": ("Chauffeur", "DRHMG"),
    "General Internal Service Agent Junior": ("Agent des Services Généraux (GISA) Junior", "DRHMG"),
    "Directeur Comptable et Financier": ("Directeur Comptable et Financier", "DCF"),
    "Chef Service Comptable": ("Chef Service Comptable", "DCF"),
    "Comptable": ("Comptable", "DCF"),
    "Assistant Comptable": ("Assistant(e) Comptable", "DCF"),
    "Directeur Opérations et Technologie": ("Directeur des Opérations et de la Technologie", "DOT"),
    "Archiviste": ("Archiviste", "DOT"),
    "Information Technology  in charge of Exploitation_Ass": ("Assistant Informatique (Exploitation)", "DOT"),
    "Information Technology Agent in charge of maintenance": ("Assistant Informatique (Maintenance)", "DOT"),
    "Information Technology Infrastucture engeneer": ("Ingénieur Infrastructure Informatique", "DOT"),
    "Back Office Supervisor": ("Back Office Supervisor (BOS)", "DOT"),
    "Cashier": ("Caissier (Cashier Agent)", "DOT"),
    "Cashier Agent": ("Caissier (Cashier Agent)", "DOT"),
    "Cashier Agent P-S": ("Caissier (Cashier Agent)", "DOT"),
    "Customer Service Agent": ("Customer Service Agent (CSA)", "DOT"),
    "Customer Service Agent P-S": ("Customer Service Agent (CSA)", "DOT"),
    "Directeur des engagements et du recouvrement": ("Directeur des Engagements et du Recouvrement", "DER"),
    "Chef Service Engagement": ("Chef Service Engagement", "DER"),
    "Analyste crédit": ("Analyste Crédit", "DER"),
    "Analyste crédt": ("Analyste Crédit", "DER"),
    "Analyste crédit / RA": ("Analyste Crédit", "DER"),
    "Recovery Supervisor": ("Superviseur Recouvrement", "DER"),
    "Recovery Agent": ("Agent de Recouvrement (RA)", "DER"),
    "RA": ("Agent de Recouvrement (RA)", "DER"),
    "RA Junior": ("Agent de Recouvrement (RA) Junior", "DER"),
    "Directeur de l'Exploitation et du Réseau d'agences": ("Directeur de l'Exploitation et du Réseau d'Agences", "DEXRA"),
    "Branch Manager": ("Chef d'Agence (Branch Manager)", "DEXRA"),
    "Branch manager / RRD1": ("Chef d'Agence et Responsable Régional Douala 1", "DEXRA"),
    "BM / RRD2": ("Chef d'Agence et Responsable Régional Douala 2", "DEXRA"),
    "BM / Responsable Régional Yaoundé 1": ("Chef d'Agence et Responsable Régional Yaoundé 1", "DEXRA"),
    "BM / Responsable Régional Yaoundé 2": ("Chef d'Agence et Responsable Régional Yaoundé 2", "DEXRA"),
    "Loan Supervisor": ("Superviseur de Crédit (Loan Supervisor)", "DEXRA"),
    "Loan Officer": ("Loan Officer (LO)", "DEXRA"),
    "LO": ("Loan Officer (LO)", "DEXRA"),
    "Loan Officer I": ("Loan Officer (LO)", "DEXRA"),
    "LOI": ("Loan Officer (LO)", "DEXRA"),                 # décision RH : LOI = Loan Officer
    "Loan Officer Int": ("Loan Officer Intermédiaire", "DEXRA"),
    "LO Intermédiaire": ("Loan Officer Intermédiaire", "DEXRA"),
    "Loan Officer Intermédiaire": ("Loan Officer Intermédiaire", "DEXRA"),
    "Loan Officer jr": ("Loan Officer Junior", "DEXRA"),
    "CCPME": ("Chargé de Clientèle PME (CCPME)", "DEXRA"),
    "Detail Sales Agent": ("Detail Sales Agent (DSA)", "DEXRA"),
    "DSA Junior": ("Detail Sales Agent (DSA) Junior", "DEXRA"),
    "DSA Jnr": ("Detail Sales Agent (DSA) Junior", "DEXRA"),
    "Responsable Epargne": ("Responsable Épargne", "DEXRA"),
    "Responsable Remittences": ("Responsable Remittances", "DEXRA"),
    "Chef Service Epargne & Remittence": ("Chef Service Épargne et Remittances", "DEXRA"),
}
_FONCTIONS_CLE = {cle(k): v for k, v in _FONCTIONS.items()}

# Postes reconnus comme « chef d'agence » (servent à pré-remplir le N+1 du personnel de l'agence)
POSTES_CHEF_AGENCE = {p for p, _ in _FONCTIONS.values() if p.startswith("Chef d'Agence")}


def fonction_officielle(texte):
    """Écriture du fichier -> (poste officiel, code direction), ou None si inconnue (à signaler)."""
    c = cle(texte)
    if c in _FONCTIONS_CLE:
        return _FONCTIONS_CLE[c]
    if c.startswith("BRANCH MANAGER") or c.startswith("BM "):
        return ("Chef d'Agence (Branch Manager)", "DEXRA")
    return None
