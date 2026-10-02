"""Génération des documents PDF officiels PASL-RH.

Utilise ReportLab (pur Python). Chaque fonction retourne les bytes du PDF,
prêts à être envoyés via une Response FastAPI.
"""
import re
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
    Image, PageBreak, HRFlowable, KeepTogether,
)
from reportlab.pdfgen import canvas as _canvas
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
VERT_PASL = colors.HexColor("#B4D02E")
LARGEUR = 180 * mm          # A4 (210) - marges 15 + 15
JOUR = "%d/%m/%Y"


def _nb(v) -> str:
    """25 → « 25 », 22.5 → « 22,5 » (format français)."""
    if v is None:
        return "0"
    v = float(v)
    return str(int(v)) if v == int(v) else str(v).replace(".", ",")


def _d(d) -> str:
    return d.strftime(JOUR) if d else "—"


class _CanevasNumerote(_canvas.Canvas):
    """Ajoute « Page x / y » : on mémorise chaque page, puis on numérote à la fin."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for etat in self._pages:
            self.__dict__.update(etat)
            self.setFont("Helvetica", 7.5)
            self.setFillColor(COULEUR_GRIS)
            self.drawRightString(195 * mm, 44.5 * mm, f"Page {self._pageNumber} / {total}")
            super().showPage()
        super().save()


def _styles_fiche():
    s = _styles()
    s.add(ParagraphStyle("FLabel", fontName="Helvetica", fontSize=8, textColor=COULEUR_GRIS, leading=10))
    s.add(ParagraphStyle("FValeur", fontName="Helvetica-Bold", fontSize=8.8, textColor=colors.black, leading=11))
    s.add(ParagraphStyle("FVide", fontName="Helvetica-Oblique", fontSize=8.5, textColor=colors.HexColor("#A0AEC0"), leading=11))
    s.add(ParagraphStyle("FNom", fontName="Helvetica-Bold", fontSize=17, textColor=COULEUR_PRIMAIRE, leading=21))
    s.add(ParagraphStyle("FSous", fontName="Helvetica", fontSize=9.5, textColor=colors.black, leading=13))
    s.add(ParagraphStyle("FPetit", fontName="Helvetica", fontSize=7.5, textColor=COULEUR_GRIS, leading=9.5))
    s.add(ParagraphStyle("FPetitD", parent=s["FPetit"], alignment=TA_RIGHT))
    s.add(ParagraphStyle("FTitreDoc", fontName="Helvetica-Bold", fontSize=13, textColor=colors.white, leading=16))
    s.add(ParagraphStyle("FSection", fontName="Helvetica-Bold", fontSize=9.5, textColor=COULEUR_PRIMAIRE, leading=12))
    s.add(ParagraphStyle("FCell", fontName="Helvetica", fontSize=8, leading=10))
    s.add(ParagraphStyle("FCellH", fontName="Helvetica-Bold", fontSize=7.8, textColor=COULEUR_PRIMAIRE, leading=10))
    s.add(ParagraphStyle("FPhoto", fontName="Helvetica", fontSize=7.5, textColor=colors.HexColor("#A0AEC0"), alignment=TA_CENTER, leading=10))
    return s


def _section(titre, st):
    """Titre de section : texte bleu PASL + filet vert."""
    t = Table([[Paragraph(titre.upper(), st["FSection"])]], colWidths=[LARGEUR])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1.2, VERT_PASL),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [Spacer(1, 4 * mm), t, Spacer(1, 2 * mm)]


def _grille(champs, st, colonnes=3):
    """Champs « libellé au-dessus, valeur en dessous » répartis sur n colonnes (valeurs jamais coupées en plein mot)."""
    cellules = []
    for libelle, valeur in champs:
        v = Paragraph(valeur, st["FValeur"]) if valeur not in (None, "", "—") else Paragraph("Non renseigné", st["FVide"])
        cellules.append([Paragraph(libelle, st["FLabel"]), v] if libelle else "")
    while len(cellules) % colonnes:
        cellules.append("")
    lignes = [cellules[i:i + colonnes] for i in range(0, len(cellules), colonnes)]
    t = Table(lignes, colWidths=[LARGEUR / colonnes] * colonnes)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    return t


def _tableau(entetes, lignes, largeurs, st):
    data = [[Paragraph(h, st["FCellH"]) for h in entetes]]
    data += [[Paragraph(str(c), st["FCell"]) for c in l] for l in lignes]
    t = Table(data, colWidths=largeurs, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7EEFE")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, COULEUR_BORDURE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COULEUR_FOND_ALT]),
    ]))
    return t


def _cadre_photo(employe, st):
    """Photo d'identité 30 x 38 mm ; si absente, cadre vide réservé (à coller à la main)."""
    chemin = None
    if employe.photo_path:
        p = Path(employe.photo_path)
        chemin = p if p.is_absolute() else Path("app") / p
    contenu = ParagraphBalise("PHOTO<br/>D'IDENTITÉ", st["FPhoto"])
    if chemin and chemin.exists():
        try:
            contenu = Image(str(chemin), width=30 * mm, height=38 * mm)
        except Exception:
            pass
    t = Table([[contenu]], colWidths=[30 * mm], rowHeights=[38 * mm])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E0")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def generer_fiche_employe_pdf(employe, ctx) -> bytes:
    """[ÉTAPE 5] Fiche signalétique de l'employé (maquette validée par la RH le 30/09/2026).
    ctx est préparé par regles_rh.contexte_fiche_pdf() : historique, sanctions, solde, absences, n_plus_1,
    anciennete, age, date_retraite, pieces [(libellé, fourni)], edite_par.
    Sans photo, un cadre vide « Photo d'identité » est réservé."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=10 * mm, bottomMargin=48 * mm,
                            title=f"Fiche signalétique - {employe.nom} {employe.prenom}")
    st = _styles_fiche()
    el = []

    # ---------- En-tête : logo + raison sociale | mentions d'édition ----------
    logo = Image(str(CHEMIN_LOGO), width=36 * mm, height=13.9 * mm) if CHEMIN_LOGO.exists() else ""
    gauche = Table([[logo, [Paragraph(PASL_NOM, st["FSection"]), Paragraph(PASL_SLOGAN, st["FPetit"])]]],
                   colWidths=[40 * mm, 70 * mm])
    gauche.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    droite = [Paragraph(f"Édité le {date.today().strftime(JOUR)}", st["FPetitD"]),
              # Paragraph(f"par {_e(ctx.get('edite_par') or '—')}", st["FPetitD"]),
              Paragraph("par les Ressources Humaines", st["FPetitD"]),
              ParagraphBalise("<font color='#9B2C2C'><b>DOCUMENT CONFIDENTIEL</b></font>", st["FPetitD"])]
    entete = Table([[gauche, droite]], colWidths=[120 * mm, 60 * mm])
    entete.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    el.append(entete)
    el.append(Spacer(1, 3 * mm))

    # ---------- Bandeau titre ----------
    bandeau = Table([[Paragraph("FICHE SIGNALÉTIQUE DE L'EMPLOYÉ", st["FTitreDoc"])]], colWidths=[LARGEUR])
    bandeau.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COULEUR_PRIMAIRE),
        ("LINEBELOW", (0, 0), (-1, -1), 3, VERT_PASL),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    el.append(bandeau)
    el.append(Spacer(1, 5 * mm))

    # ---------- Bloc identité : photo + résumé ----------
    statut = "Actif" if employe.statut == "actif" else "Inactif (sorti des effectifs)"
    couleur_statut = "#166534" if employe.statut == "actif" else "#9B2C2C"
    resume = [
        Paragraph(f"{employe.nom} {employe.prenom}", st["FNom"]),
        Spacer(1, 1 * mm),
        ParagraphBalise(f"<b>{_e(employe.poste.intitule if employe.poste else '—')}</b> · "
                        f"{_e(employe.grade.libelle if employe.grade else '—')}", st["FSous"]),
        Paragraph(f"{employe.departement.nom if employe.departement else '—'} · "
                  f"{employe.agence.nom if employe.agence else 'Siège'}", st["FSous"]),
        Spacer(1, 3 * mm),
    ]
    chiffres = Table([[
        [Paragraph("Matricule", st["FLabel"]), Paragraph(employe.matricule or "—", st["FValeur"])],
        [Paragraph("Statut", st["FLabel"]), ParagraphBalise(f"<font color='{couleur_statut}'><b>{statut}</b></font>", st["FValeur"])],
        [Paragraph("Ancienneté", st["FLabel"]), Paragraph(ctx.get("anciennete") or "—", st["FValeur"])],
        [Paragraph("Congés disponibles", st["FLabel"]), Paragraph(f"{_nb(ctx['solde']['total_restant'])} jours", st["FValeur"])],
    ]], colWidths=[34 * mm, 42 * mm, 34 * mm, 34 * mm])
    chiffres.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COULEUR_FOND_ALT), ("BOX", (0, 0), (-1, -1), 0.3, COULEUR_BORDURE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    resume.append(chiffres)
    bloc = Table([[_cadre_photo(employe, st), resume]], colWidths=[36 * mm, 144 * mm])
    bloc.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    el.append(bloc)

    # ---------- 1. État civil ----------
    naissance = _d(employe.date_naissance)
    if getattr(employe, "lieu_naissance", None):
        naissance += f" à {employe.lieu_naissance}"
    if ctx.get("age") is not None:
        naissance += f" ({ctx['age']} ans)"
    situation = employe.statut_matrimonial or ""
    if employe.nombre_enfants is not None:
        situation += (" · " if situation else "") + f"{employe.nombre_enfants} enfant{'s' if employe.nombre_enfants > 1 else ''}"
    cni = getattr(employe, "numero_cni", None)
    if cni and getattr(employe, "cni_delivree_le", None):
        cni += f" du {_d(employe.cni_delivree_le)}"
    el += _section("1. État civil", st)
    el.append(_grille([
        ("Nom", employe.nom), ("Prénom(s)", employe.prenom), ("Genre", "Femme" if employe.genre == "F" else "Homme"),
        ("Date et lieu de naissance", naissance if employe.date_naissance else None), ("Nationalité", getattr(employe, "nationalite", None)),
        ("Situation familiale", situation or None),
        ("N° de CNI", cni), ("Niveau d'études / diplôme", getattr(employe, "niveau_etudes", None)), ("", ""),
    ], st))

    # ---------- 2. Coordonnées ----------
    urgence = " · ".join(x for x in [employe.contact_urgence_nom, employe.contact_urgence_tel] if x) or None
    el += _section("2. Coordonnées", st)
    el.append(_grille([
        ("Adresse (quartier, ville)", getattr(employe, "adresse", None)), ("Téléphone professionnel", employe.telephone_pro),
        ("Téléphone personnel", employe.telephone_perso),
        ("Email professionnel", employe.email_pro), ("Email personnel", employe.email_perso), ("Contact d'urgence", urgence),
    ], st))

    # ---------- 3. Situation professionnelle ----------
    n1 = ctx.get("n_plus_1")
    el += _section("3. Situation professionnelle", st)
    el.append(_grille([
        ("Matricule", employe.matricule), ("N° CNPS", getattr(employe, "numero_cnps", None)), ("Date d'embauche", _d(employe.date_embauche)),
        ("Poste", employe.poste.intitule if employe.poste else None), ("Grade", employe.grade.libelle if employe.grade else None),
        ("Supérieur hiérarchique (N+1)", f"{n1.nom} {n1.prenom}" if n1 else None),
        ("Département", employe.departement.nom if employe.departement else None),
        ("Agence", employe.agence.nom if employe.agence else "Siège"),
        ("Départ à la retraite (60 ans)", _d(ctx.get("date_retraite")) if ctx.get("date_retraite") else None),
    ], st))

    # ---------- 4. Parcours ----------
    hist = ctx.get("historique") or []
    el += _section("4. Parcours dans l'entreprise", st)
    if hist:
        el.append(_tableau(["Mouvement", "Période", "Poste", "Affectation", "Grade"], [[
            (h.type_mouvement or "—").replace("_", " ").capitalize(),
            f"{_d(h.date_debut)} → {_d(h.date_fin) if h.date_fin else 'en cours'}",
            h.poste.intitule if h.poste else "—",
            (h.departement.nom if h.departement else "—") + (f" / {h.agence.nom}" if h.agence else ""),
            h.grade.libelle if h.grade else "—",
        ] for h in hist], [26 * mm, 40 * mm, 38 * mm, 50 * mm, 26 * mm], st))
    else:
        el.append(Paragraph("Aucun mouvement enregistré.", st["FVide"]))

    # ---------- 5. Congés et absences ----------
    s = ctx["solde"]
    bloc_conges = _section("5. Congés et absences", st)
    bloc_conges.append(ParagraphBalise(
        f"Droits acquis depuis l'embauche : <b>{_nb(s['total_alloue'])} j</b> (2 j/mois) &nbsp;·&nbsp; "
        f"Pris : <b>{_nb(s['total_pris'])} j</b> &nbsp;·&nbsp; Disponibles : <b>{_nb(s['total_restant'])} j</b>", st["FCell"]))
    bloc_conges.append(Spacer(1, 2 * mm))
    absences = (ctx.get("absences") or [])[:8]
    if absences:
        bloc_conges.append(_tableau(["Type", "Du", "Au", "Durée", "Justifiée"], [[
            a.type_absence.libelle if a.type_absence else "—", _d(a.date_debut), _d(a.date_fin),
            f"{nb_jours_ouvrables(a.date_debut, a.date_fin)} j", "Oui" if a.justifiee else "Non",
        ] for a in absences], [60 * mm, 30 * mm, 30 * mm, 30 * mm, 30 * mm], st))
        bloc_conges.append(Paragraph("8 dernières absences au maximum.", st["FPetit"]))
    el.append(KeepTogether(bloc_conges))

    # ---------- 6. Discipline ----------
    sanctions = ctx.get("sanctions") or []
    bloc_disc = _section("6. Suivi disciplinaire", st)
    if sanctions:
        bloc_disc.append(_tableau(["Date", "Sanction", "Motif", "Durée"], [[
            _d(x.date_sanction), x.type_sanction or "—", x.motif or "—", x.duree or "—",
        ] for x in sanctions], [24 * mm, 42 * mm, 94 * mm, 20 * mm], st))
    else:
        bloc_disc.append(Paragraph("Aucune sanction enregistrée.", st["FCell"]))
    el.append(KeepTogether(bloc_disc))

    # ---------- 7. Pièces du dossier ----------
    bloc_p = _section("7. Pièces du dossier", st)
    pieces = ctx.get("pieces") or []
    bloc_p.append(Table([[ParagraphBalise(
        f"{_e(lib)} : <font color='{'#166534' if ok else '#975a16'}'><b>{'fourni' if ok else 'MANQUANT'}</b></font>", st["FCell"]) for lib, ok in pieces]],
        colWidths=[LARGEUR / max(len(pieces), 1)] * max(len(pieces), 1)))
    el.append(KeepTogether(bloc_p))

    # ---------- Signatures ----------
    el.append(Spacer(1, 6 * mm))
    sig = Table([
        [Paragraph("Je certifie l'exactitude des informations ci-dessus.", st["FPetit"]), ""],
        [ParagraphBalise("<b>L'employé(e)</b> — date et signature", st["FCell"]), ParagraphBalise("<b>Le service des Ressources Humaines</b> — date, signature et cachet", st["FCell"])],
        ["", ""],
    ], colWidths=[90 * mm, 90 * mm], rowHeights=[None, None, 20 * mm])
    sig.setStyle(TableStyle([
        ("SPAN", (0, 0), (1, 0)), ("BOX", (0, 1), (0, 2), 0.3, COULEUR_BORDURE), ("BOX", (1, 1), (1, 2), 0.3, COULEUR_BORDURE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    el.append(KeepTogether(sig))

    doc.build(el, onFirstPage=_pied_de_page, onLaterPages=_pied_de_page, canvasmaker=_CanevasNumerote)
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
    """Lettre de licenciement sur le papier à en-tête PASL (logo en haut, coordonnées en pied de page).

    Décision PASL : pas de modèle imposé, car les formats varient selon les cas. Le texte est rédigé
    librement par la RH dans le dossier (champ lettre_texte) et reproduit tel quel : lieu, date,
    destinataire, objet, corps et formule de signature compris.
    Mise en forme : une ligne vide sépare deux paragraphes ; un simple retour à la ligne est conservé."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=12 * mm, bottomMargin=45 * mm,
        title=f"Lettre de licenciement - {employe.nom} {employe.prenom}",
    )
    styles = _styles()
    elements = _entete_pasl(styles)

    texte = (dossier.lettre_texte or "").replace("\r\n", "\n").strip()
    for bloc in re.split(r"\n[ \t]*\n", texte):
        bloc = bloc.strip("\n")
        if not bloc.strip():
            continue
        # Texte saisi échappé (un « < » ou un « & » ne casse pas le PDF), puis retours à la ligne conservés
        elements.append(ParagraphBalise(_e(bloc).replace("\n", "<br/>"), styles["PaslCorps"]))

    doc.build(elements, onFirstPage=_pied_de_page, onLaterPages=_pied_de_page)
    buffer.seek(0)
    return buffer.read()
