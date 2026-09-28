"""Génération des documents PDF officiels PASL-RH.

Utilise ReportLab (pur Python). Chaque fonction retourne les bytes du PDF,
prêts à être envoyés via une Response FastAPI.
"""
from io import BytesIO
from datetime import date
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Spacer, Table, TableStyle,
    Image, PageBreak, HRFlowable,
)
from reportlab.platypus import Paragraph as _ParagraphReportLab
from xml.sax.saxutils import escape as _echapper

from .calendrier import nb_jours_ouvrables


# ------------------------------------------------------------------
# [CORRECTIF B17] Échappement des textes
# ReportLab interprète le texte d'un Paragraph comme du balisage (<b>, <font>...). Un nom ou un motif
# contenant « & » ou « < » (ex. « Ets X & Fils ») faisait planter la génération du PDF.
# - Paragraph(...)        : texte brut, échappé automatiquement (cas général) ;
# - ParagraphBalise(...)  : texte contenant du balisage VOULU ; les valeurs dynamiques y sont
#                           échappées une à une avec _e().
# ------------------------------------------------------------------
def _e(valeur) -> str:
    return _echapper(str(valeur)) if valeur is not None else ""


def Paragraph(texte, style):
    return _ParagraphReportLab(_e(texte), style)


def ParagraphBalise(texte, style):
    return _ParagraphReportLab(texte, style)


def _civilite(employe) -> str:
    """[CORRECTIF B16] « Monsieur » ou « Madame » selon le genre, au lieu de « Monsieur/Madame »."""
    return "Madame" if employe.genre == "F" else "Monsieur"

# ------------------------------------------------------------------
# Constantes PASL
# ------------------------------------------------------------------
PASL_NOM = "Pan-African Savings & Loans S.A"
PASL_SLOGAN = "Powered by Ecobank Microfinance"
PASL_ADRESSE = "Boulevard Bèssèke, Immeuble Interface, 2e et 3e étages - BP: 8437 Douala - Cameroun - Tél.: (237) 679 52 67 31 - Email: info@panafricansl-cameroun.com - Site: Panafricansl-cameroun.com"
PASL_LEGAL_1 = "Etablissement de Microfinance - 2ème Catégorie SOCIETE ANONYME AU CAPITAL FCFA 781 000 000 - N° Cont. M100700029551J - RCCM: Rc/Dla/2007/B/1961"
PASL_LEGAL_2 = "N° d'agrément: Arrêté N° 00000331 / Minfi du 15 Octobre 2009 DCI N°: 0126/11 du 26/05/2011 - Immatriculation CNC N° EMF/2011/0126"
PASL_SLOGAN_ENV = "\"En économisant nos ressources, nous protégeons notre environnement\""
PASL_VILLE = "Douala"

COULEUR_PRIMAIRE = colors.HexColor("#06547A")
COULEUR_BLEU_MARIN = colors.HexColor("#1a365d")
COULEUR_GRIS = colors.HexColor("#4A5568")
COULEUR_BORDURE = colors.HexColor("#E5E7EB")
COULEUR_FOND_ALT = colors.HexColor("#F7FAFC")

CHEMIN_LOGO = Path("app/static/logo-pasl.jpg")


# ------------------------------------------------------------------
# Styles
# ------------------------------------------------------------------
def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="PaslTitre",
        fontName="Helvetica-Bold",
        fontSize=13,
        textColor=COULEUR_PRIMAIRE,
        alignment=TA_CENTER,
        spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        name="PaslSousTitre",
        fontName="Helvetica",
        fontSize=8,
        textColor=COULEUR_GRIS,
        alignment=TA_CENTER,
        spaceAfter=1,
    ))
    styles.add(ParagraphStyle(
        name="PaslSection",
        fontName="Helvetica-Bold",
        fontSize=10,
        textColor=COULEUR_PRIMAIRE,
        alignment=TA_LEFT,
        spaceBefore=6,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="PaslCorps",
        fontName="Helvetica",
        fontSize=10,
        textColor=colors.black,
        alignment=TA_LEFT,
        leading=14,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="PaslDocumentTitre",
        fontName="Helvetica-Bold",
        fontSize=15,
        textColor=COULEUR_PRIMAIRE,
        alignment=TA_CENTER,
        spaceBefore=12,
        spaceAfter=14,
    ))
    styles.add(ParagraphStyle(
        name="PaslItalique",
        fontName="Helvetica-Oblique",
        fontSize=8.5,
        textColor=COULEUR_GRIS,
        alignment=TA_CENTER,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="PaslCellLabel",
        fontName="Helvetica-Bold",
        fontSize=8.5,
        textColor=COULEUR_PRIMAIRE,
        alignment=TA_LEFT,
    ))
    styles.add(ParagraphStyle(
        name="PaslCellValue",
        fontName="Helvetica",
        fontSize=8.5,
        textColor=colors.black,
        alignment=TA_LEFT,
    ))
    styles.add(ParagraphStyle(
        name="PaslCellHeader",
        fontName="Helvetica-Bold",
        fontSize=8,
        textColor=colors.white,
        alignment=TA_LEFT,
    ))
    return styles


# ------------------------------------------------------------------
# En-tête PASL : logo à gauche, infos au centre, photo à droite
# ------------------------------------------------------------------
def _entete_pasl(styles, employe=None):
    """En-tête : logo à gauche, infos société au centre, photo 4x4 à droite."""
    elements = []

    contenu_gauche = []
    if CHEMIN_LOGO.exists():
        try:
            logo = Image(str(CHEMIN_LOGO), width=38 * mm, height=14 * mm)
            contenu_gauche.append(logo)
        except Exception:
            pass

    contenu_centre = [
        Paragraph(PASL_NOM, styles["PaslTitre"]),
        Paragraph(PASL_SLOGAN, styles["PaslSousTitre"]),
    ]

    contenu_droite = []
    if employe and employe.photo_path:
        chemin_photo = Path(employe.photo_path)
        if not chemin_photo.is_absolute():
            chemin_photo = Path("app") / chemin_photo
        if chemin_photo.exists():
            try:
                photo = Image(str(chemin_photo), width=30 * mm, height=30 * mm)
                contenu_droite.append(photo)
            except Exception:
                pass

    ligne_entete = Table(
        [[contenu_gauche, contenu_centre, contenu_droite]],
        colWidths=[50 * mm, 90 * mm, 40 * mm],
    )
    ligne_entete.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(ligne_entete)
    elements.append(Spacer(1, 3 * mm))
    elements.append(HRFlowable(width="100%", thickness=1, color=COULEUR_PRIMAIRE))
    elements.append(Spacer(1, 4 * mm))

    return elements


# ------------------------------------------------------------------
# Pied de page : infos société en bleu marine, tout centré
# ------------------------------------------------------------------
def _pied_de_page(canvas, doc):
    canvas.saveState()

    canvas.setStrokeColor(COULEUR_BLEU_MARIN)
    canvas.setLineWidth(0.5)
    canvas.line(15 * mm, 42 * mm, 195 * mm, 42 * mm)

    canvas.setFillColor(COULEUR_BLEU_MARIN)
    centre = 105 * mm

    lignes = [
        (PASL_NOM, "Helvetica-Bold", 9),
        (PASL_ADRESSE, "Helvetica", 6.5),
        (PASL_LEGAL_1, "Helvetica", 6.5),
        (PASL_LEGAL_2, "Helvetica", 6.5),
        (PASL_SLOGAN_ENV, "Helvetica", 6.5),
    ]

    y = 38 * mm
    for texte, police, taille in lignes:
        canvas.setFont(police, taille)
        canvas.drawCentredString(centre, y, texte)
        y -= 3.7 * mm

    canvas.restoreState()


# ------------------------------------------------------------------
# Helper : table de paires label / valeur
# ------------------------------------------------------------------
def _table_paires(paires, styles, largeur_label=30 * mm, largeur_valeur=52 * mm):
    data = []
    for label, valeur in paires:
        data.append([
            Paragraph(label, styles["PaslCellLabel"]),
            Paragraph(str(valeur), styles["PaslCellValue"]),
        ])
    table = Table(data, colWidths=[largeur_label, largeur_valeur])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, COULEUR_BORDURE),
    ]))
    return table


# ------------------------------------------------------------------
# Fiche employé PDF
# ------------------------------------------------------------------
def generer_fiche_employe_pdf(employe, historique, sanctions=None, soldes_conges=None) -> bytes:
    """Fiche employé compacte : en-tête + 2 colonnes + historique + sanctions + congés."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=12 * mm, bottomMargin=45 * mm,
        title=f"Fiche employé - {employe.nom} {employe.prenom}",
    )
    styles = _styles()
    elements = _entete_pasl(styles, employe)

    elements.append(Paragraph("FICHE EMPLOYÉ", styles["PaslDocumentTitre"]))

    age_str = "—"
    if employe.date_naissance:
        auj = date.today()
        age = auj.year - employe.date_naissance.year
        if (auj.month, auj.day) < (employe.date_naissance.month, employe.date_naissance.day):
            age -= 1
        age_str = f"{age} ans"

     # --- Colonne 1 : état civil ---
    paires_col1 = [
        ("Matricule", employe.matricule or "—"),
        ("Nom", employe.nom or "—"),
        ("Prénom", employe.prenom or "—"),
        ("Genre", "Homme" if employe.genre == "H" else "Femme"),
        ("Naissance", employe.date_naissance.strftime("%d/%m/%Y") if employe.date_naissance else "—"),
        ("Âge", age_str),
    ]
    table_col1 = _table_paires(paires_col1, styles, largeur_label=18 * mm, largeur_valeur=42 * mm)

    # --- Colonne 2 : situation familiale + contact ---
    paires_col2 = [
        ("Statut matrimonial", employe.statut_matrimonial or "—"),
        ("Nombre d'enfants", str(employe.nombre_enfants) if employe.nombre_enfants is not None else "—"),
        ("Tél. pro", employe.telephone_pro or "—"),
        ("Tél. perso", employe.telephone_perso or "—"),
        ("Email", employe.email_perso or "—"),
    ]
    table_col2 = _table_paires(paires_col2, styles, largeur_label=28 * mm, largeur_valeur=32 * mm)

    # --- Colonne 3 : pro ---
    paires_col3 = [
        ("Département", employe.departement.nom if employe.departement else "—"),
        ("Agence", employe.agence.nom if employe.agence else "Direction Générale"),
        ("Poste", employe.poste.intitule if employe.poste else "—"),
        ("Grade", employe.grade.libelle if employe.grade else "—"),
        ("Embauche", employe.date_embauche.strftime("%d/%m/%Y") if employe.date_embauche else "—"),
        ("Statut", "Actif" if employe.statut == "actif" else "Inactif"),
    ]
    table_col3 = _table_paires(paires_col3, styles, largeur_label=20 * mm, largeur_valeur=40 * mm)

    # --- Contact d'urgence (ligne du dessous, pleine largeur) ---
    contact_urgence_txt = "—"
    if employe.contact_urgence_nom or employe.contact_urgence_tel:
        contact_urgence_txt = (
            f"{employe.contact_urgence_nom or '—'} "
            f"— Tél. : {employe.contact_urgence_tel or '—'}"
        )

    # --- Tableau 3 colonnes ---
    ligne_3_colonnes = Table(
        [[table_col1, table_col2, table_col3]],
        colWidths=[60 * mm, 60 * mm, 60 * mm],
    )
    ligne_3_colonnes.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("LEFTPADDING", (1, 0), (1, 0), 6),
        ("LEFTPADDING", (2, 0), (2, 0), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(ligne_3_colonnes)
    elements.append(Spacer(1, 2 * mm))

    # --- Ligne contact d'urgence en pleine largeur ---
    elements.append(ParagraphBalise(
        f"<b><font color='#06547A'>Contact d'urgence :</font></b> {_e(contact_urgence_txt)}",
        styles["PaslCellValue"]
    ))
    elements.append(Spacer(1, 4 * mm))

    # --- Historique de carrière ---
    if historique:
        elements.append(Paragraph("Historique de carrière", styles["PaslSection"]))
        lignes = [[
            Paragraph("Type", styles["PaslCellHeader"]),
            Paragraph("Début", styles["PaslCellHeader"]),
            Paragraph("Fin", styles["PaslCellHeader"]),
            Paragraph("Poste", styles["PaslCellHeader"]),
            Paragraph("Département / Agence", styles["PaslCellHeader"]),
            Paragraph("Grade", styles["PaslCellHeader"]),
        ]]
        for h in historique:
            lignes.append([
                Paragraph((h.type_mouvement or "—").replace("_", " ").capitalize(), styles["PaslCellValue"]),
                Paragraph(h.date_debut.strftime("%d/%m/%Y") if h.date_debut else "—", styles["PaslCellValue"]),
                Paragraph(h.date_fin.strftime("%d/%m/%Y") if h.date_fin else "En cours", styles["PaslCellValue"]),
                Paragraph(h.poste.intitule if h.poste else "—", styles["PaslCellValue"]),
                Paragraph(
                    (h.departement.nom if h.departement else "—")
                    + (" / " + h.agence.nom if h.agence else ""),
                    styles["PaslCellValue"],
                ),
                Paragraph(h.grade.libelle if h.grade else "—", styles["PaslCellValue"]),
            ])
        table_hist = Table(
            lignes,
            colWidths=[22 * mm, 20 * mm, 20 * mm, 40 * mm, 55 * mm, 23 * mm],
            repeatRows=1,
        )
        table_hist.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COULEUR_PRIMAIRE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.25, COULEUR_BORDURE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COULEUR_FOND_ALT]),
        ]))
        elements.append(table_hist)
        elements.append(Spacer(1, 4 * mm))

    # --- Suivi disciplinaire ---
    if sanctions:
        elements.append(Paragraph("Suivi disciplinaire", styles["PaslSection"]))
        lignes_s = [[
            Paragraph("Date", styles["PaslCellHeader"]),
            Paragraph("Type", styles["PaslCellHeader"]),
            Paragraph("Motif", styles["PaslCellHeader"]),
            Paragraph("Durée", styles["PaslCellHeader"]),
        ]]
        for s in sanctions:
            import re as _re
            motif_clean = s.motif or "—"
            # Supprime les liens Markdown [texte](url) → garde "texte"
            motif_clean = _re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', motif_clean)
            # Supprime les liens Markdown incomplets [n] ou [n] (
            motif_clean = _re.sub(r'\[\d+\]\s*\(?', '', motif_clean)
            # Supprime toute URL résiduelle
            motif_clean = _re.sub(r'https?://\S+', '', motif_clean)
            # Supprime les parenthèses orphelines et espaces en trop
            motif_clean = _re.sub(r'\s*\(\s*\)', '', motif_clean)
            motif_clean = _re.sub(r'\s+', ' ', motif_clean).strip()

            lignes_s.append([
                Paragraph(s.date_sanction.strftime("%d/%m/%Y") if s.date_sanction else "—", styles["PaslCellValue"]),
                Paragraph(s.type_sanction or "—", styles["PaslCellValue"]),
                Paragraph(motif_clean or "—", styles["PaslCellValue"]),
                Paragraph(s.duree or "—", styles["PaslCellValue"]),
            ])
        table_s = Table(lignes_s, colWidths=[25 * mm, 40 * mm, 95 * mm, 20 * mm], repeatRows=1)
        table_s.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#9B2C2C")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.25, COULEUR_BORDURE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FFF5F5")]),
        ]))
        elements.append(table_s)
        elements.append(Spacer(1, 4 * mm))

    # --- Congés ---
    if soldes_conges:
        COULEUR_CONGE_TITRE = colors.HexColor("#5F9B2E")  # vert PASL foncé (lisible)
        style_conge = ParagraphStyle(
            name="PaslSectionConge",
            parent=styles["PaslSection"],
            textColor=COULEUR_CONGE_TITRE,
        )
        elements.append(Paragraph("Congés", style_conge))

        total_alloue = soldes_conges.get("total_alloue", 0)
        total_pris = soldes_conges.get("total_pris", 0)
        total_restant = soldes_conges.get("total_restant", 0)
        annees_comptees = soldes_conges.get("annees_comptees", 0)

        recap_data = [
            [
                ParagraphBalise("<b>Alloués (cumul)</b>", styles["PaslCellValue"]),
                ParagraphBalise("<b>Pris</b>", styles["PaslCellValue"]),
                ParagraphBalise("<b>Restants</b>", styles["PaslCellValue"]),
                ParagraphBalise("<b>Ancienneté</b>", styles["PaslCellValue"]),
            ],
            [
                Paragraph(f"{total_alloue}j", styles["PaslCellValue"]),
                Paragraph(f"{total_pris}j", styles["PaslCellValue"]),
                Paragraph(f"{total_restant}j", styles["PaslCellValue"]),
                Paragraph(f"{annees_comptees} an(s)", styles["PaslCellValue"]),
            ],
        ]
        table_recap = Table(recap_data, colWidths=[45 * mm, 45 * mm, 45 * mm, 45 * mm])
        COULEUR_CONGE_FOND = colors.HexColor("#6BA534")  # vert PASL (fond tableau)
        table_recap.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COULEUR_CONGE_FOND),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.25, COULEUR_BORDURE),
        ]))
        elements.append(table_recap)
        elements.append(Spacer(1, 3 * mm))

        conges_pris = soldes_conges.get("conges_pris", [])
        if conges_pris:
            lignes_c = [[
                Paragraph("Du", styles["PaslCellHeader"]),
                Paragraph("Au", styles["PaslCellHeader"]),
                Paragraph("Durée", styles["PaslCellHeader"]),
                Paragraph("Motif", styles["PaslCellHeader"]),
            ]]
            for c in conges_pris:
                duree = nb_jours_ouvrables(c.date_debut, c.date_fin)  # [CORRECTIF B9] jours ouvrables
                lignes_c.append([
                    Paragraph(c.date_debut.strftime("%d/%m/%Y") if c.date_debut else "—", styles["PaslCellValue"]),
                    Paragraph(c.date_fin.strftime("%d/%m/%Y") if c.date_fin else "—", styles["PaslCellValue"]),
                    Paragraph(f"{duree}j", styles["PaslCellValue"]),
                    Paragraph(c.motif or "—", styles["PaslCellValue"]),
                ])
            table_c = Table(lignes_c, colWidths=[30 * mm, 30 * mm, 20 * mm, 100 * mm], repeatRows=1)
            table_c.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), COULEUR_CONGE_FOND),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("GRID", (0, 0), (-1, -1), 0.25, COULEUR_BORDURE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COULEUR_FOND_ALT]),
            ]))
            elements.append(table_c)

    doc.build(elements, onFirstPage=_pied_de_page, onLaterPages=_pied_de_page)
    buffer.seek(0)
    return buffer.read()


# ------------------------------------------------------------------
# Certificat de travail PDF
# ------------------------------------------------------------------
def generer_certificat_travail_pdf(employe, date_depart=None) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=12 * mm, bottomMargin=45 * mm,
        title=f"Certificat de travail - {employe.nom} {employe.prenom}",
    )
    styles = _styles()
    elements = _entete_pasl(styles, employe)

    elements.append(Paragraph("CERTIFICAT DE TRAVAIL", styles["PaslDocumentTitre"]))
    elements.append(Spacer(1, 8 * mm))

    date_fin = date_depart or date.today()
    poste_txt = employe.poste.intitule if employe.poste else "employé(e)"
    date_debut_txt = employe.date_embauche.strftime("%d/%m/%Y") if employe.date_embauche else "—"
    date_fin_txt = date_fin.strftime("%d/%m/%Y")

    employe_e = "employée" if employe.genre == "F" else "employé"
    texte_corps = (
        f"Je soussigné, le Directeur des Ressources Humaines de la "
        f"<b>{_e(PASL_NOM)}</b>, agissant en qualité de responsable du personnel, "
        f"certifie que {_civilite(employe)} <b>{_e(employe.nom)} {_e(employe.prenom)}</b>, "
        f"matricule <b>{_e(employe.matricule or '—')}</b>, a été {employe_e} au sein de "
        f"notre société du <b>{date_debut_txt}</b> au <b>{date_fin_txt}</b>, "
        f"en qualité de <b>{_e(poste_txt)}</b>."
    )
    elements.append(ParagraphBalise(texte_corps, styles["PaslCorps"]))
    elements.append(Spacer(1, 6 * mm))

    texte_suite = (
        f"{'L’intéressée' if employe.genre == 'F' else 'L’intéressé'} est libre de tout engagement envers notre société à compter "
        "de la date de fin de contrat ci-dessus mentionnée."
    )
    elements.append(Paragraph(texte_suite, styles["PaslCorps"]))
    elements.append(Spacer(1, 8 * mm))

    texte_fin = (
        "En foi de quoi, le présent certificat est délivré à l'intéressé(e) "
        "pour servir et valoir ce que de droit."
    )
    elements.append(Paragraph(texte_fin, styles["PaslCorps"]))
    elements.append(Spacer(1, 20 * mm))

    signature = [
        [Paragraph(f"Fait à {PASL_VILLE}, le {date.today().strftime('%d/%m/%Y')}", styles["PaslCorps"])],
        [Spacer(1, 8 * mm)],
        [ParagraphBalise("<b>Le Directeur des Ressources Humaines</b>", styles["PaslCorps"])],
        [Spacer(1, 18 * mm)],
        [Paragraph("(Signature et cachet)", styles["PaslItalique"])],
    ]
    table_sig = Table(signature, colWidths=[80 * mm])
    table_sig.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "RIGHT")]))
    elements.append(table_sig)

    doc.build(elements, onFirstPage=_pied_de_page, onLaterPages=_pied_de_page)
    buffer.seek(0)
    return buffer.read()


# ------------------------------------------------------------------
# Attestation de travail PDF
# ------------------------------------------------------------------
def generer_attestation_travail_pdf(employe) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=12 * mm, bottomMargin=45 * mm,
        title=f"Attestation de travail - {employe.nom} {employe.prenom}",
    )
    styles = _styles()
    elements = _entete_pasl(styles, employe)

    elements.append(Paragraph("ATTESTATION DE TRAVAIL", styles["PaslDocumentTitre"]))
    elements.append(Spacer(1, 8 * mm))

    poste_txt = employe.poste.intitule if employe.poste else "employé(e)"
    date_debut_txt = employe.date_embauche.strftime("%d/%m/%Y") if employe.date_embauche else "—"

    texte_corps = (
        f"Nous, la <b>{_e(PASL_NOM)}</b>, attestons que "
        f"{_civilite(employe)} <b>{_e(employe.nom)} {_e(employe.prenom)}</b>, "
        f"matricule <b>{_e(employe.matricule or '—')}</b>, fait partie de notre personnel "
        f"depuis le <b>{date_debut_txt}</b>, en qualité de <b>{_e(poste_txt)}</b>."
    )
    elements.append(ParagraphBalise(texte_corps, styles["PaslCorps"]))
    elements.append(Spacer(1, 6 * mm))

    texte_fin = (
        "La présente attestation est délivrée à l'intéressé(e) pour servir et valoir ce que de droit."
    )
    elements.append(Paragraph(texte_fin, styles["PaslCorps"]))
    elements.append(Spacer(1, 20 * mm))

    signature = [
        [Paragraph(f"Fait à {PASL_VILLE}, le {date.today().strftime('%d/%m/%Y')}", styles["PaslCorps"])],
        [Spacer(1, 8 * mm)],
        [ParagraphBalise("<b>Le Directeur des Ressources Humaines</b>", styles["PaslCorps"])],
        [Spacer(1, 18 * mm)],
        [Paragraph("(Signature et cachet)", styles["PaslItalique"])],
    ]
    table_sig = Table(signature, colWidths=[80 * mm])
    table_sig.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "RIGHT")]))
    elements.append(table_sig)

    doc.build(elements, onFirstPage=_pied_de_page, onLaterPages=_pied_de_page)
    buffer.seek(0)
    return buffer.read()


# ------------------------------------------------------------------
# Lettre de licenciement (étape 3)
# ------------------------------------------------------------------
def generer_lettre_licenciement_pdf(employe, dossier) -> bytes:
    """Lettre notifiant le licenciement, après approbation du Comité de direction.
    Le texte est un modèle : il doit être relu et signé par la Direction avant remise."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=12 * mm, bottomMargin=45 * mm,
        title=f"Lettre de licenciement - {employe.nom} {employe.prenom}",
    )
    styles = _styles()
    elements = _entete_pasl(styles)

    date_lettre = dossier.date_notification or date.today()
    elements.append(ParagraphBalise(f"{_e(PASL_VILLE)}, le {date_lettre.strftime('%d/%m/%Y')}", styles["PaslCorps"]))
    elements.append(Spacer(1, 4 * mm))
    destinataire = (f"{_civilite(employe)} <b>{_e(employe.nom)} {_e(employe.prenom)}</b><br/>"
                    f"Matricule : {_e(employe.matricule or '—')}<br/>"
                    f"{_e(employe.poste.intitule if employe.poste else '')}")
    elements.append(ParagraphBalise(destinataire, styles["PaslCorps"]))
    elements.append(Spacer(1, 6 * mm))
    elements.append(ParagraphBalise("<b>Objet : notification de licenciement</b>", styles["PaslCorps"]))
    elements.append(Spacer(1, 4 * mm))

    elements.append(Paragraph(f"{_civilite(employe)},", styles["PaslCorps"]))
    conseil = (f" Votre situation a été examinée par le conseil de discipline réuni le "
               f"{dossier.conseil_date.strftime('%d/%m/%Y')}." if dossier.conseil_date else "")
    elements.append(ParagraphBalise(
        f"Nous vous informons que la Direction de la <b>{_e(PASL_NOM)}</b> a décidé de mettre fin à votre contrat "
        f"de travail pour le motif suivant : <b>{_e(dossier.type_motif.lower())}</b>.{_e(conseil)}",
        styles["PaslCorps"]))
    if dossier.expose_faits:
        elements.append(ParagraphBalise(f"<b>Faits reprochés :</b> {_e(dossier.expose_faits)}", styles["PaslCorps"]))

    if dossier.type_motif == "Faute lourde":
        preavis = "Compte tenu de la gravité des faits (faute lourde), aucun préavis ne sera effectué."
    elif dossier.preavis_dispense:
        preavis = "Vous êtes dispensé(e) de l'exécution de votre préavis."
    elif dossier.preavis_jours:
        preavis = (f"Votre préavis, d'une durée de {dossier.preavis_jours} jours, court à compter de la "
                   "notification de la présente lettre.")
    else:
        preavis = ""
    if preavis:
        elements.append(Paragraph(preavis, styles["PaslCorps"]))
    if dossier.date_sortie:
        elements.append(ParagraphBalise(
            f"Vous cesserez de faire partie des effectifs de la société le "
            f"<b>{dossier.date_sortie.strftime('%d/%m/%Y')}</b>.", styles["PaslCorps"]))
    elements.append(Paragraph(
        "Votre certificat de travail ainsi que votre solde de tout compte seront tenus à votre disposition "
        "auprès du service des Ressources Humaines.", styles["PaslCorps"]))
    elements.append(Paragraph(
        f"Veuillez agréer, {_civilite(employe)}, l'expression de nos salutations distinguées.", styles["PaslCorps"]))
    elements.append(Spacer(1, 14 * mm))

    signature = [
        [ParagraphBalise("<b>La Direction Générale</b>", styles["PaslCorps"])],
        [Spacer(1, 18 * mm)],
        [Paragraph("(Signature et cachet)", styles["PaslItalique"])],
        [Spacer(1, 6 * mm)],
        [Paragraph("Reçu le : ____ / ____ / ________   Signature de l'intéressé(e) :", styles["PaslCorps"])],
    ]
    table_sig = Table(signature, colWidths=[170 * mm])
    table_sig.setStyle(TableStyle([("ALIGN", (0, 0), (-1, 2), "RIGHT")]))
    elements.append(table_sig)

    doc.build(elements, onFirstPage=_pied_de_page, onLaterPages=_pied_de_page)
    buffer.seek(0)
    return buffer.read()