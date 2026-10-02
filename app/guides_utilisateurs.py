"""Guides utilisateurs PASL-RH : une page A4 par rôle (Employé, N+1, RH, Comité de direction).

- guides_vierges()       : les 4 guides, encadré « Vos accès » à remplir à la main ;
- guides_personnalises() : une page par personne, accès déjà imprimés (voir app/scripts/imprimer_identifiants.py).
"""
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, KeepInFrame, PageBreak, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle, NextPageTemplate)

LOGO = Path(__file__).resolve().parent / "static" / "logo-pasl.jpg"
BLEU = colors.HexColor("#06547A")
BLEU_CLAIR = colors.HexColor("#E8F1F6")
VERT = colors.HexColor("#B4D02E")
GRIS = colors.HexColor("#4A5568")
AMBRE = colors.HexColor("#FFF7E6")

LARGEUR, HAUTEUR = A4
MARGE = 14 * mm
HAUT_BANDEAU = 30 * mm

s_corps = ParagraphStyle("corps", fontName="Helvetica", fontSize=10, leading=13.6, textColor=colors.black)
s_puce = ParagraphStyle("puce", parent=s_corps, leftIndent=11, bulletIndent=2, spaceAfter=2.2)
s_num = ParagraphStyle("num", parent=s_corps, leftIndent=13, bulletIndent=0, spaceAfter=2.2)
s_titre = ParagraphStyle("titre", fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=BLEU,
                         spaceBefore=9, spaceAfter=4)
s_petit = ParagraphStyle("petit", parent=s_corps, fontSize=9, leading=11.8, textColor=GRIS)
s_case = ParagraphStyle("case", parent=s_corps, fontSize=10, leading=17)


PIED_STANDARD = "Pan-African Savings & Loans  ·  Document interne  ·  Ne communiquez jamais votre mot de passe."
PIED_PERSONNEL = ("DOCUMENT PERSONNEL ET CONFIDENTIEL  ·  Détruisez cette feuille dès que vous avez changé "
                  "votre mot de passe.")


def bandeau(titre, sous_titre, pied=PIED_STANDARD):
    def dessiner(c, doc):
        c.saveState()
        c.setFillColor(BLEU)
        c.rect(0, HAUTEUR - HAUT_BANDEAU, LARGEUR, HAUT_BANDEAU, stroke=0, fill=1)
        c.setFillColor(VERT)
        c.rect(0, HAUTEUR - HAUT_BANDEAU - 1.6 * mm, LARGEUR, 1.6 * mm, stroke=0, fill=1)
        # logo sur cartouche blanc
        c.setFillColor(colors.white)
        c.roundRect(MARGE, HAUTEUR - 24 * mm, 46 * mm, 18 * mm, 2 * mm, stroke=0, fill=1)
        c.drawImage(str(LOGO), MARGE + 2 * mm, HAUTEUR - 22.5 * mm, width=42 * mm, height=15 * mm,
                    preserveAspectRatio=True, anchor="c")
        c.setFillColor(colors.white)
        c.setFont("Helvetica", 9)
        c.drawString(MARGE + 52 * mm, HAUTEUR - 11 * mm, "SYSTÈME RH  ·  GUIDE D'UTILISATION")
        c.setFont("Helvetica-Bold", 17)
        c.drawString(MARGE + 52 * mm, HAUTEUR - 19 * mm, titre)
        c.setFont("Helvetica", 9.5)
        c.drawString(MARGE + 52 * mm, HAUTEUR - 25 * mm, sous_titre)
        # pied de page
        c.setStrokeColor(colors.HexColor("#CBD5E0"))
        c.line(MARGE, 12 * mm, LARGEUR - MARGE, 12 * mm)
        c.setFillColor(GRIS)
        c.setFont("Helvetica", 7.8)
        c.drawString(MARGE, 8 * mm, pied)
        c.drawRightString(LARGEUR - MARGE, 8 * mm, date.today().strftime("%m/%Y"))
        c.restoreState()
    return dessiner


def titre(texte):
    return Paragraph(texte, s_titre)


def puces(*lignes):
    return [Paragraph(l, s_puce, bulletText="•") for l in lignes]


def etapes(*lignes):
    return [Paragraph(l, s_num, bulletText=f"{i}.") for i, l in enumerate(lignes, 1)]


def encadre(contenu, fond=BLEU_CLAIR, bord=BLEU):
    t = Table([[contenu]], colWidths=[LARGEUR - 2 * MARGE])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fond), ("LINEBEFORE", (0, 0), (0, -1), 2.5, bord),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def deux_colonnes(gauche, droite):
    largeur = (LARGEUR - 2 * MARGE - 6 * mm) / 2
    t = Table([[gauche, droite]], colWidths=[largeur, largeur])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (0, -1), 6 * mm), ("RIGHTPADDING", (1, 0), (1, -1), 0)]))
    return t


def cases_identifiants(identifiant="email pro, sinon email perso, sinon matricule", acces=None):
    """acces = None : lignes à remplir à la main ; sinon dict(nom, unite, adresse, identifiant, mot_de_passe)."""
    if acces:
        code = "<font name='Courier-Bold' size=12>{}</font>"
        unite = f"  ·  {escape(acces['unite'])}" if acces.get("unite") else ""
        lignes = [
            Paragraph(f"<b>VOS ACCÈS PERSONNELS</b>  —  <b>{escape(acces['nom'])}</b>{unite}", s_corps),
            Paragraph(f"Adresse de l'application : <b>{escape(acces['adresse'])}</b> "
                      "<font size=8 color='#4A5568'>(à taper dans Chrome, Edge ou Firefox)</font>", s_case),
            Paragraph("Identifiant : " + code.format(escape(acces["identifiant"])), s_case),
            Paragraph("Mot de passe provisoire : " + code.format(escape(acces["mot_de_passe"]))
                      + " <font size=8 color='#4A5568'>(respectez majuscules et minuscules ; "
                        "à changer dès la première connexion)</font>", s_case),
        ]
        return encadre(lignes)
    lignes = [
        Paragraph("<b>VOS ACCÈS</b>  <font size=8 color='#4A5568'>(à compléter par la RH)</font>", s_corps),
        Paragraph("Adresse de l'application : <b>http://</b>_____________________________________________________", s_case),
        Paragraph("Identifiant : _____________________________________ "
                  f"<font size=8 color='#4A5568'>({identifiant})</font>", s_case),
        Paragraph("Mot de passe provisoire : ___________________________ "
                  "<font size=8 color='#4A5568'>(à changer dès la première connexion)</font>", s_case),
    ]
    return encadre(lignes)


def connexion():
    return etapes(
        "Ouvrez <b>Chrome, Edge ou Firefox</b> et tapez l'adresse indiquée ci-dessus "
        "(ajoutez-la à vos favoris).",
        "Saisissez votre <b>identifiant</b> et votre <b>mot de passe</b>, puis cliquez sur <b>Se connecter</b>.",
        "Changez tout de suite votre mot de passe : icône <b>clé</b> en bas du menu de gauche "
        "(8 caractères minimum, que vous seul connaissez).",
        "Quand vous avez fini, cliquez sur l'icône <b>Déconnexion</b> (flèche) en bas du menu, "
        "surtout sur un ordinateur partagé.",
    )


def statuts_demande():
    data = [["Statut affiché", "Signification"],
            ["Chez votre N+1", "Votre responsable doit donner son avis."],
            ["Chez les RH", "Le N+1 est favorable ; la RH va décider."],
            ["Validée", "Accordée : l'absence est enregistrée et le solde mis à jour."],
            ["Refusée par N+1 / par RH", "Non accordée : le motif est affiché sous la demande."]]
    t = Table([[Paragraph(a, s_petit), Paragraph(b, s_petit)] for a, b in data],
              colWidths=[40 * mm, None])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLEU_CLAIR), ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


# ---------------------------------------------------------------- Contenus
def page_employe(acces=None):
    gauche = [
        titre("1. Se connecter"), *connexion(),
        titre("2. Mon espace"),
        Paragraph("Menu <b>Mon espace</b> : tout ce qui vous concerne, en un seul endroit.", s_corps), Spacer(1, 2),
        *puces("<b>Ma fiche</b> : matricule, agence, poste, date d'embauche, ancienneté, N+1.",
               "<b>Mon solde de congés</b> : jours alloués, pris et restants depuis votre embauche.",
               "<b>Mes absences</b>, <b>mes demandes</b> et leur avancement.",
               "<b>Voir ma fiche</b> : consultez et téléchargez votre fiche (PDF).",
               "<b>Modifier mes informations</b> : téléphone et email personnels, situation familiale, "
               "contact d'urgence, photo. Pour le reste (poste, CNI, CNPS…), adressez-vous à la RH."),
    ]
    droite = [
        titre("3. Demander un congé, une permission, une absence"),
        *etapes("Cliquez sur <b>+ Nouvelle demande</b> (en haut du menu).",
                "Choisissez le <b>type</b> : Congé, Permission ou Absence.",
                "<b>Congé</b> : dates de début et de fin, et votre <b>suppléant</b> (obligatoire).<br/>"
                "<b>Permission / Absence</b> : type, dates, motif ; joignez le justificatif "
                "(certificat médical, acte…) pour un traitement plus rapide.",
                "Cliquez sur <b>Envoyer la demande</b>."),
        Spacer(1, 3),
        Paragraph("<b>Le circuit</b> : vous &#8594; votre <b>N+1</b> (avis) &#8594; la <b>RH</b> (décision). "
                  "Vous recevez un <b>email</b> à chaque décision.", s_corps),
        Spacer(1, 4), statuts_demande(),
    ]
    bas = [
        titre("Bon à savoir"),
        encadre([
            *puces("Vous acquérez <b>2 jours de congé par mois</b> (24 par an). Le samedi compte comme jour travaillé ; "
                   "les dimanches et jours fériés ne sont pas décomptés.",
                   "Un congé n'est validé que si votre <b>solde est suffisant</b> : vérifiez-le avant de demander.",
                   "Un <b>avis défavorable du N+1 est définitif</b> : parlez-en avec lui, puis déposez une nouvelle demande.",
                   "Après <b>5 mots de passe erronés</b>, le compte est bloqué 15 minutes. "
                   "Mot de passe oublié : demandez un mot de passe provisoire à la RH.",
                   "Une information de votre fiche est fausse ? Signalez-le à la RH."),
        ], fond=AMBRE, bord=VERT),
    ]
    return [cases_identifiants(acces=acces), Spacer(1, 2), deux_colonnes(gauche, droite), *bas]


def page_n_plus_1(acces=None):
    intro = encadre([Paragraph(
        "Vous êtes <b>N+1</b> (responsable hiérarchique) si des collaborateurs vous sont rattachés dans l'application : "
        "chef d'agence, directeur, chef de service… Ce guide <b>complète le guide Employé</b> : vous gardez votre propre "
        "espace et vos propres demandes, qui partent vers <b>votre</b> N+1.", s_corps)])
    gauche = [
        titre("1. Être prévenu"),
        *puces("Vous recevez un email <b>« Demande de … à examiner »</b> avec le lien direct.",
               "Ou ouvrez le menu <b>Mes validations</b> : toutes les demandes qui attendent votre avis."),
        titre("2. Donner votre avis"),
        *etapes("Dans <b>Mes validations</b>, cliquez sur <b>Traiter</b>.",
                "Lisez la demande : employé, type, période, <b>suppléant</b>, motif.",
                "Regardez l'<b>alerte de présence</b> : elle signale si l'absence fait passer votre équipe "
                "sous le nombre minimum d'agents présents fixé par la RH.",
                "Choisissez <b>Favorable</b> (vous pouvez ajuster la période accordée) ou <b>Défavorable</b>.",
                "Ajoutez un <b>commentaire</b> (indispensable en cas de refus : l'employé le lira), "
                "puis <b>Enregistrer mon avis</b>."),
    ]
    droite = [
        titre("3. Ce qui se passe ensuite"),
        *puces("<b>Favorable</b> : la demande part à la <b>RH</b>, qui prend la décision finale "
               "(elle vérifie notamment le solde de congés).",
               "<b>Défavorable</b> : la demande est <b>refusée définitivement</b> et l'employé est prévenu par email.",
               "Le bas de la page <b>Mes validations</b> garde l'historique de vos 10 derniers avis et leur suite."),
        titre("4. Calendrier de mon équipe"),
        *puces("Menu <b>Calendrier de mon équipe</b> : qui est absent, jour par jour, sur le mois.",
               "Les jours où l'équipe passe <b>sous le minimum d'agents présents</b> sont signalés : "
               "tenez-en compte avant d'accorder une nouvelle absence."),
    ]
    bas = [
        titre("Bon à savoir"),
        encadre([*puces(
            "<b>Répondez rapidement</b> : tant que vous n'avez pas donné votre avis, la demande est bloquée chez vous.",
            "En cas d'urgence ou d'absence de votre part, la RH peut décider directement ; c'est tracé dans la demande.",
            "Un collaborateur manque dans votre équipe, ou ne devrait pas y être ? Signalez-le à la RH : "
            "c'est elle qui enregistre les rattachements N+1.",
            "Votre avis et vos commentaires sont enregistrés et consultables par la RH.")],
            fond=AMBRE, bord=VERT),
    ]
    return [cases_identifiants(acces=acces), Spacer(1, 4), intro, Spacer(1, 2), deux_colonnes(gauche, droite), *bas]


def page_rh(acces=None):
    gauche = [
        titre("1. Traiter les demandes"),
        *etapes("Menu <b>Demandes à traiter</b> (un email vous prévient aussi).",
                "Cliquez sur <b>Traiter</b> : consultez l'avis du N+1 et l'<b>alerte de présence</b>.",
                "Ajustez si besoin la <b>période accordée</b>, ajoutez un commentaire, puis <b>Valider</b> ou <b>Refuser</b>."),
        *puces("Un congé n'est validé que si le <b>solde suffit</b> (jours ouvrables, samedi compris).",
               "Une demande validée crée l'absence et met le solde à jour automatiquement.",
               "Seul le <b>Chef RH</b> valide un départ. Un refus du N+1 est définitif."),
        titre("2. Employés et absences"),
        *puces("<b>Employés</b> : fiche, modification, pièces (CNI, photo… PDF, JPG ou PNG, 5 Mo max), "
               "N+1, sanctions, <b>fiche signalétique PDF</b>.",
               "<b>Suivi des absences</b> : enregistrer une absence qui n'est pas passée par une demande.",
               "<b>Congés &amp; Soldes</b> : soldes de tous les employés.",
               "<b>Calendrier d'équipe</b> : fixer le <b>minimum d'agents présents</b> par agence et par direction.",
               "<b>Mis à disposition</b> : registre des agents des entreprises de placement."),
    ]
    droite = [
        titre("3. Mise à jour depuis le fichier RH"),
        *etapes("Menu <b>Mise à jour depuis le fichier RH</b> : déposez votre fichier Excel habituel (.xlsx).",
                "Lisez la <b>vérification</b> : rien n'est encore enregistré.",
                "Téléchargez le <b>Rapport détaillé</b> : la feuille « À corriger dans le fichier » donne la cellule "
                "exacte (Ctrl+G dans Excel).",
                "Cliquez sur <b>Appliquer ces changements</b>."),
        Paragraph("Une case vide n'efface rien ; un employé absent du fichier n'est jamais supprimé, il est seulement signalé.",
                  s_petit),
        titre("4. Procédure de licenciement"),
        *etapes("Depuis la fiche : <b>Engager une procédure de licenciement</b>.",
                "Renseignez les faits, le conseil de discipline et son <b>PV</b>, le préavis et l'avis de la RH.",
                "Quand la liste de contrôle est complète : <b>Transmettre au Comité</b>.",
                "Après la décision du Comité : notifiez, puis saisissez la <b>lettre</b> (texte libre, imprimée sur "
                "papier à en-tête PASL)."),
    ]
    bas = [
        titre("Bon à savoir"),
        encadre([*puces(
            "Chaque création, modification ou suppression est enregistrée dans le <b>journal d'audit</b> "
            "(consultable par le Chef RH).",
            "Comptes et mots de passe oubliés : <b>Administration &gt; Utilisateurs</b> (administrateur), "
            "qui génère un mot de passe provisoire.",
            "Les données du personnel sont <b>confidentielles</b> : ne laissez pas de fiche PDF ou d'export sur un "
            "poste partagé, et déconnectez-vous en quittant votre poste.")],
            fond=AMBRE, bord=VERT),
    ]
    return [cases_identifiants("votre email professionnel", acces), Spacer(1, 2), deux_colonnes(gauche, droite), *bas]


def page_comite(acces=None):
    gauche = [
        titre("1. Suivre l'activité"),
        Paragraph("<b>Tableau de bord</b> : effectif actif, demandes en attente, embauches, départs, absents du jour, "
                  "turnover, départs à la retraite des 6 prochains mois.", s_corps), Spacer(1, 2),
        *puces("Filtrez par <b>période</b>, agence, direction, genre, poste ou grade.",
               "<b>Exporter le rapport</b> &#8594; Rapport Excel complet."),
        titre("2. Consulter"),
        *puces("<b>Employés</b> : fiches du personnel.",
               "<b>Suivi des absences</b> et <b>Congés &amp; Soldes</b>.",
               "<b>Calendrier d'équipe</b> : absences jour par jour, par agence ou direction.",
               "<b>Mis à disposition</b> : nombre d'agents par entreprise de placement."),
    ]
    droite = [
        titre("3. Décider d'un licenciement"),
        *etapes("Un email vous prévient quand la RH <b>transmet un dossier</b> ; le menu "
                "<b>Licenciements à décider</b> affiche leur nombre.",
                "Ouvrez le dossier : faits, sanctions antérieures, conseil de discipline et son <b>PV</b>, "
                "préavis, avis et commentaire de la RH.",
                "Décidez : <b>Approuver le licenciement</b>, <b>Rejeter</b>, ou <b>Renvoyer à la RH pour "
                "complément</b>. Un commentaire est obligatoire pour rejeter ou renvoyer."),
        Spacer(1, 3),
        Paragraph("La RH est prévenue de votre décision. En cas d'approbation, c'est elle qui notifie l'employé "
                  "et lui remet la lettre.", s_corps),
    ]
    bas = [
        titre("Bon à savoir"),
        encadre([*puces(
            "Votre accès est un accès de <b>consultation et de décision</b> : la saisie (employés, demandes, absences) "
            "reste à la RH.",
            "Chaque décision est datée, signée de votre nom et enregistrée dans le journal d'audit.",
            "Les informations consultées sont <b>confidentielles</b> : déconnectez-vous en quittant votre poste.")],
            fond=AMBRE, bord=VERT),
    ]
    return [cases_identifiants("votre email professionnel", acces), Spacer(1, 2), deux_colonnes(gauche, droite), *bas]


GUIDES = {
    "employe": ("Guide Employé", "Mon espace, mes congés et mes demandes", page_employe),
    "n_plus_1": ("Guide N+1 (responsable hiérarchique)", "Donner son avis sur les demandes de son équipe", page_n_plus_1),
    "rh": ("Guide Ressources Humaines", "Chef RH et Assistant(e) RH", page_rh),
    "comite": ("Guide Comité de direction", "Pilotage et décisions", page_comite),
}


def _construire(chemin, pages, titre_pdf):
    """pages = [(cle_guide, acces ou None), ...] : une page A4 chacune."""
    doc = BaseDocTemplate(str(chemin), pagesize=A4, title=titre_pdf, author="PASL — Ressources Humaines")
    cadre = Frame(MARGE, 14 * mm, LARGEUR - 2 * MARGE, HAUTEUR - HAUT_BANDEAU - 18 * mm, id="c",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    modeles = []
    for cle, (titre_g, sous_titre, _) in GUIDES.items():
        modeles.append(PageTemplate(id=cle, frames=[cadre], onPage=bandeau(titre_g, sous_titre)))
        modeles.append(PageTemplate(id=cle + "_perso", frames=[cadre], onPage=bandeau(titre_g, sous_titre, PIED_PERSONNEL)))
    # la première page prend le premier modèle de la liste : on y place celui de la première page
    premier = pages[0][0] + ("_perso" if pages[0][1] else "")
    doc.addPageTemplates(sorted(modeles, key=lambda m: m.id != premier))
    histoire = []
    for i, (cle, acces) in enumerate(pages):
        modele = cle + ("_perso" if acces else "")
        histoire += [NextPageTemplate(modele)] + ([PageBreak()] if i else [])
        histoire.append(KeepInFrame(cadre._width, cadre._height, GUIDES[cle][2](acces), mode="shrink"))
    doc.build(histoire)


def guides_vierges(chemin, cles=tuple(GUIDES)):
    _construire(chemin, [(cle, None) for cle in cles], "Guides utilisateurs — Système RH PASL")


def guides_personnalises(chemin, pages):
    """pages = [(cle_guide, dict(nom, unite, adresse, identifiant, mot_de_passe)), ...]"""
    _construire(chemin, pages, "Accès personnels — Système RH PASL (CONFIDENTIEL)")
