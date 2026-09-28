"""Tableau de bord RH et ses exports (Excel, CSV)."""
import csv
import io
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from ..database import get_db
from .. import models
from ..outils import _date_ou_none, _entier_ou_none, _exiger_non_employe, templates
from ..regles_rh import STATUTS_EN_ATTENTE

router = APIRouter()


# ============================================================
# TABLEAU DE BORD
# ============================================================

# ============================================================
# HELPERS FILTRES / PÉRIODES
# ============================================================

PERIODES_LIBELLES = {
    "7j": "7 derniers jours",
    "30j": "30 derniers jours",
    "90j": "90 derniers jours",
    "mois": "Ce mois-ci",
    "trimestre": "Ce trimestre",
    "annee": "Cette année",
    "12m": "12 mois glissants",
    "perso": "Période personnalisée",
}

# KPI dont la période peut être surchargée individuellement
SURCHARGES_PERIODE = ("embauches", "departs", "turnover", "absences")


def _bornes_periode(cle: str, date_debut: date | None, date_fin: date | None) -> tuple[date, date]:
    """Retourne (debut, fin) pour une clé de période donnée."""
    aujourdhui = date.today()

    if cle == "7j":
        return aujourdhui - timedelta(days=7), aujourdhui
    if cle == "30j":
        return aujourdhui - timedelta(days=30), aujourdhui
    if cle == "90j":
        return aujourdhui - timedelta(days=90), aujourdhui
    if cle == "mois":
        return date(aujourdhui.year, aujourdhui.month, 1), aujourdhui
    if cle == "trimestre":
        mois_debut_trimestre = ((aujourdhui.month - 1) // 3) * 3 + 1
        return date(aujourdhui.year, mois_debut_trimestre, 1), aujourdhui
    if cle == "annee":
        return date(aujourdhui.year, 1, 1), aujourdhui
    if cle == "12m":
        return aujourdhui - timedelta(days=365), aujourdhui
    if cle == "perso":
        debut = date_debut or (aujourdhui - timedelta(days=30))
        fin = date_fin or aujourdhui
        # Sécurité : si fin < début, on inverse
        if fin < debut:
            debut, fin = fin, debut
        return debut, fin

    # Fallback : 30j
    return aujourdhui - timedelta(days=30), aujourdhui


def _libelle_periode(debut: date, fin: date) -> str:
    return f"du {debut.strftime('%d/%m/%Y')} au {fin.strftime('%d/%m/%Y')}"


def _construire_filtres_actifs(
    agence_id, departement_id, genre, poste_id, grade_id,
    periode, date_debut, date_fin,
    periode_embauches, periode_departs, periode_turnover, periode_absences,
    agences, departements, postes, grades,
) -> list[dict]:
    """Construit la liste des badges de filtres actifs avec URL de retrait."""
    filtres = []
    base_params = {
        "periode": periode,
        "date_debut": date_debut or "",
        "date_fin": date_fin or "",
        "periode_embauches": periode_embauches or "",
        "periode_departs": periode_departs or "",
        "periode_turnover": periode_turnover or "",
        "periode_absences": periode_absences or "",
        "agence_id": agence_id or "",
        "departement_id": departement_id or "",
        "genre": genre or "",
        "poste_id": poste_id or "",
        "grade_id": grade_id or "",
    }

    def url_sans(cle):
        params = {k: v for k, v in base_params.items() if k != cle and v}
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"/?{query}" if query else "/"

    if agence_id:
        nom = next((a.nom for a in agences if str(a.id) == str(agence_id)), agence_id)
        filtres.append({"label": f"Agence : {nom}", "url_retrait": url_sans("agence_id")})
    if departement_id:
        nom = next((d.nom for d in departements if str(d.id) == str(departement_id)), departement_id)
        filtres.append({"label": f"Département : {nom}", "url_retrait": url_sans("departement_id")})
    if genre:
        filtres.append({"label": f"Genre : {'Hommes' if genre == 'H' else 'Femmes'}", "url_retrait": url_sans("genre")})
    if poste_id:
        nom = next((p.intitule for p in postes if str(p.id) == str(poste_id)), poste_id)
        filtres.append({"label": f"Poste : {nom}", "url_retrait": url_sans("poste_id")})
    if grade_id:
        nom = next((g.libelle for g in grades if str(g.id) == str(grade_id)), grade_id)
        filtres.append({"label": f"Grade : {nom}", "url_retrait": url_sans("grade_id")})

    # Surcharges de période (si différentes de la globale)
    for cle, val, lib in [
        ("periode_embauches", periode_embauches, "Embauches"),
        ("periode_departs", periode_departs, "Départs"),
        ("periode_turnover", periode_turnover, "Turnover"),
        ("periode_absences", periode_absences, "Absences"),
    ]:
        if val and val != periode:
            filtres.append({
                "label": f"{lib} : {PERIODES_LIBELLES.get(val, val)}",
                "url_retrait": url_sans(cle),
            })

    return filtres


# ============================================================
# ACCUEIL / TABLEAU DE BORD
# ============================================================

@router.get("/")
def accueil(
    request: Request,
    db: Session = Depends(get_db),
    periode: str = "30j",
    date_debut: str = "",
    date_fin: str = "",
    periode_embauches: str = "",
    periode_departs: str = "",
    periode_turnover: str = "12m",
    periode_absences: str = "",
    agence_id: str = "",
    departement_id: str = "",
    genre: str = "",
    poste_id: str = "",
    grade_id: str = "",
):
    _exiger_non_employe(request)
    aujourdhui = date.today()

    # --- 1. Critères de filtrage ---
    agence_f = _entier_ou_none(agence_id)
    departement_f = _entier_ou_none(departement_id)
    poste_f = _entier_ou_none(poste_id)
    grade_f = _entier_ou_none(grade_id)
    genre_f = genre if genre in ("H", "F") else None

    # --- 2. Bornes de période ---
    date_debut_f = _date_ou_none(date_debut)
    date_fin_f = _date_ou_none(date_fin)

    # Période globale
    if periode not in PERIODES_LIBELLES:
        periode = "30j"
    p_debut, p_fin = _bornes_periode(periode, date_debut_f, date_fin_f)
    periode_active_label = _libelle_periode(p_debut, p_fin)

    # Surcharges : si vide → hérite de la période globale
    per_emb = periode_embauches if periode_embauches in PERIODES_LIBELLES else periode
    per_dep = periode_departs if periode_departs in PERIODES_LIBELLES else periode
    per_tur = periode_turnover if periode_turnover in PERIODES_LIBELLES else "12m"
    per_abs = periode_absences if periode_absences in PERIODES_LIBELLES else periode

    emb_debut, emb_fin = _bornes_periode(per_emb, date_debut_f, date_fin_f)
    dep_debut, dep_fin = _bornes_periode(per_dep, date_debut_f, date_fin_f)
    tur_debut, tur_fin = _bornes_periode(per_tur, date_debut_f, date_fin_f)
    abs_debut, abs_fin = _bornes_periode(per_abs, date_debut_f, date_fin_f)

    # --- 3. Filtrage des employés (base pour les KPI structurels) ---
    query_emp = db.query(models.Employe).filter_by(statut="actif")
    if agence_f:
        query_emp = query_emp.filter(models.Employe.agence_id == agence_f)
    if departement_f:
        query_emp = query_emp.filter(models.Employe.departement_id == departement_f)
    if genre_f:
        query_emp = query_emp.filter(models.Employe.genre == genre_f)
    if poste_f:
        query_emp = query_emp.filter(models.Employe.poste_id == poste_f)
    if grade_f:
        query_emp = query_emp.filter(models.Employe.grade_id == grade_f)

    employes_actifs = query_emp.all()
    effectif_total = len(employes_actifs)
    employes_ids = [e.id for e in employes_actifs]

    # --- 4. KPI structurels (non filtrés par période) ---
    compteur_departements: dict[str, int] = {}
    compteur_agences: dict[str, int] = {}
    for e in employes_actifs:
        nom_dept = e.departement.nom if e.departement else "Non renseigné"
        compteur_departements[nom_dept] = compteur_departements.get(nom_dept, 0) + 1
        nom_agence = e.agence.nom if e.agence else "Direction Générale"
        compteur_agences[nom_agence] = compteur_agences.get(nom_agence, 0) + 1

    # Répartition départements (avec pourcentage + largeur + couleur)
    palette_dept = ["#1a365d", "#3182ce", "#63b3ed", "#90cdf4", "#2c5282", "#4299e1", "#bee3f8", "#2b6cb0"]
    total_dept = sum(compteur_departements.values()) or 1
    repartition_departements = []
    for i, (nom, c) in enumerate(sorted(compteur_departements.items(), key=lambda x: x[1], reverse=True)):
        repartition_departements.append({
            "nom": nom,
            "count": c,
            "pourcentage": round(c / total_dept * 100, 1),
            "largeur": round(c / max(total_dept, 1) * 100, 1),
            "couleur": palette_dept[i % len(palette_dept)],
        })

    # Répartition agences
    palette_agences = ["#1a365d", "#3182ce", "#63b3ed", "#90cdf4", "#2c5282", "#4299e1", "#bee3f8", "#2b6cb0"]
    total_agences = sum(compteur_agences.values()) or 1
    segments_agences = []
    curseur = 0.0
    for i, (nom, c) in enumerate(sorted(compteur_agences.items(), key=lambda x: x[1], reverse=True)):
        part = c / total_agences * 100
        segments_agences.append({
            "nom": nom,
            "count": c,
            "couleur": palette_agences[i % len(palette_agences)],
            "pourcentage": round(part, 2),
            "debut": round(curseur, 2),
            "fin": round(curseur + part, 2),
        })
        curseur += part

    nb_agences = len(compteur_agences)
    nb_departements = len(compteur_departements)

    # --- 5. KPI flux : Embauches (période surchargeable) ---
    q_emb = db.query(models.Employe).filter(
        models.Employe.date_embauche >= emb_debut,
        models.Employe.date_embauche <= emb_fin,
    )
    if agence_f:
        q_emb = q_emb.filter(models.Employe.agence_id == agence_f)
    if departement_f:
        q_emb = q_emb.filter(models.Employe.departement_id == departement_f)
    if genre_f:
        q_emb = q_emb.filter(models.Employe.genre == genre_f)
    if poste_f:
        q_emb = q_emb.filter(models.Employe.poste_id == poste_f)
    if grade_f:
        q_emb = q_emb.filter(models.Employe.grade_id == grade_f)
    nouvelles_embauches = q_emb.count()

    # --- 6. KPI flux : Départs (période surchargeable) ---
    q_dep = db.query(models.Depart).join(models.Employe).filter(
        models.Depart.date_depart >= dep_debut,
        models.Depart.date_depart <= dep_fin,
    )
    if agence_f:
        q_dep = q_dep.filter(models.Employe.agence_id == agence_f)
    if departement_f:
        q_dep = q_dep.filter(models.Employe.departement_id == departement_f)
    if genre_f:
        q_dep = q_dep.filter(models.Employe.genre == genre_f)
    if poste_f:
        q_dep = q_dep.filter(models.Employe.poste_id == poste_f)
    if grade_f:
        q_dep = q_dep.filter(models.Employe.grade_id == grade_f)
    departs_recents = q_dep.count()

    # --- 7. Turnover (période surchargeable, défaut 12m) ---
    q_tur = db.query(models.Depart).join(models.Employe).filter(
        models.Depart.date_depart >= tur_debut,
        models.Depart.date_depart <= tur_fin,
    )
    if agence_f:
        q_tur = q_tur.filter(models.Employe.agence_id == agence_f)
    if departement_f:
        q_tur = q_tur.filter(models.Employe.departement_id == departement_f)
    if genre_f:
        q_tur = q_tur.filter(models.Employe.genre == genre_f)
    if poste_f:
        q_tur = q_tur.filter(models.Employe.poste_id == poste_f)
    if grade_f:
        q_tur = q_tur.filter(models.Employe.grade_id == grade_f)
    departs_12_mois = q_tur.count()
    effectif_moyen = effectif_total or 1
    turnover = round((departs_12_mois / effectif_moyen) * 100, 1)

    # --- 8. Absents aujourd'hui (filtrable par critères, PAS par période) ---
    q_abs_j = db.query(models.Absence).join(models.Employe).filter(
        models.Absence.date_debut <= aujourdhui,
        models.Absence.date_fin >= aujourdhui,
        models.Absence.archivee == False,
    )
    if agence_f:
        q_abs_j = q_abs_j.filter(models.Employe.agence_id == agence_f)
    if departement_f:
        q_abs_j = q_abs_j.filter(models.Employe.departement_id == departement_f)
    if genre_f:
        q_abs_j = q_abs_j.filter(models.Employe.genre == genre_f)
    if poste_f:
        q_abs_j = q_abs_j.filter(models.Employe.poste_id == poste_f)
    if grade_f:
        q_abs_j = q_abs_j.filter(models.Employe.grade_id == grade_f)
    absents_aujourdhui = q_abs_j.count()

    # --- 9. Demandes en attente ---
    q_dem_att = db.query(models.DemandeRh).filter(
        models.DemandeRh.statut.in_(STATUTS_EN_ATTENTE)
    )
    if agence_f or departement_f:
        q_dem_att = q_dem_att.join(
            models.Employe,
            models.DemandeRh.employe_concerne_id == models.Employe.id,
            isouter=True,
        )
        if agence_f:
            q_dem_att = q_dem_att.filter(models.Employe.agence_id == agence_f)
        if departement_f:
            q_dem_att = q_dem_att.filter(models.Employe.departement_id == departement_f)
    demandes_en_attente = q_dem_att.count()

    # --- 10. Cartes types de demandes (par type d'action RH) ---
    types_demande = db.query(models.TypeDemande).order_by(models.TypeDemande.id).all()
    cartes_types = []
    icones_types = {
        "Congé": ("event_available", "bg-amber-100", "text-amber-800", "Priorité haute"),
        "Recrutement": ("person_search", "bg-emerald-100", "text-emerald-800", "Priorité moyenne"),
        "Mutation / Mouvement interne": ("swap_horiz", "bg-blue-100", "text-blue-800", "Priorité moyenne"),
        "Départ": ("logout", "bg-rose-100", "text-rose-800", "Priorité haute"),
    }
    debut_mois = datetime(aujourdhui.year, aujourdhui.month, 1)
    for t in types_demande:
        # [CORRECTIF B19] « Total ce mois » comptait en réalité toutes les demandes depuis le début
        total_type = db.query(models.DemandeRh).filter(
            models.DemandeRh.type_demande_id == t.id,
            models.DemandeRh.date_demande >= debut_mois,
        ).count()
        att_type = db.query(models.DemandeRh).filter(
            models.DemandeRh.type_demande_id == t.id,
            models.DemandeRh.statut.in_(STATUTS_EN_ATTENTE),
        ).count()
        icone, bg, txt, prio = icones_types.get(t.libelle, ("assignment", "bg-slate-100", "text-slate-800", "Normale"))
        cartes_types.append({
            "libelle": t.libelle,
            "total_mois": total_type,
            "en_attente": att_type,
            "icone": icone,
            "couleur_bg": bg,
            "couleur_txt": txt,
            "priorite": prio,
            "action": "Traiter" if att_type > 0 else "Voir",
        })

    # --- 11. Demandes récentes (format enrichi pour le template) ---
    demandes_recentes_q = (
        db.query(models.DemandeRh)
        .order_by(models.DemandeRh.date_demande.desc())
        .limit(8)
        .all()
    )
    palette_avatar = ["bg-blue-100 text-blue-800", "bg-emerald-100 text-emerald-800",
                      "bg-amber-100 text-amber-800", "bg-rose-100 text-rose-800",
                      "bg-purple-100 text-purple-800"]
    icones_type_demande = {
        "Congé": ("event_available", "bg-amber-50 text-amber-700"),
        "Recrutement": ("person_search", "bg-emerald-50 text-emerald-700"),
        "Mutation / Mouvement interne": ("swap_horiz", "bg-blue-50 text-blue-700"),
        "Départ": ("logout", "bg-rose-50 text-rose-700"),
    }
    demandes_recentes = []
    for i, d in enumerate(demandes_recentes_q):
        emp = d.employe_concerne
        type_lib = d.type_demande.libelle if d.type_demande else "Autre"
        icone, coul = icones_type_demande.get(type_lib, ("assignment", "bg-slate-50 text-slate-700"))
        demandes_recentes.append({
            "id": d.id,
            "initiales": ((emp.prenom[0] if emp and emp.prenom else "?") + (emp.nom[0] if emp and emp.nom else "?")).upper(),
            "couleur_avatar": palette_avatar[i % len(palette_avatar)],
            "nom_complet": f"{emp.nom} {emp.prenom}" if emp else "—",
            "matricule": emp.matricule if emp and emp.matricule else "—",
            "poste": emp.poste.intitule if emp and emp.poste else "—",
            "type_libelle": type_lib,
            "type_icone": icone,
            "type_couleur": coul,
            "agence_nom": (emp.agence.nom if emp and emp.agence else "Direction Générale"),
            "departement_nom": emp.departement.nom if emp and emp.departement else "—",
            "date_demande": d.date_demande,
            "statut": d.statut,
        })
    demandes_recentes_total = db.query(models.DemandeRh).filter(
        models.DemandeRh.statut.in_(STATUTS_EN_ATTENTE)
    ).count()

    # --- 12. Pyramide des âges ---
    tranches = {"≤25": 0, "26-35": 0, "36-45": 0, "46-55": 0, "56+": 0}
    for e in employes_actifs:
        if e.date_naissance:
            age = aujourdhui.year - e.date_naissance.year
            if (aujourdhui.month, aujourdhui.day) < (e.date_naissance.month, e.date_naissance.day):
                age -= 1
            if age <= 25:
                tranches["≤25"] += 1
            elif age <= 35:
                tranches["26-35"] += 1
            elif age <= 45:
                tranches["36-45"] += 1
            elif age <= 55:
                tranches["46-55"] += 1
            else:
                tranches["56+"] += 1
    total_age = sum(tranches.values()) or 1
    pyramide_ages = [
        {"tranche": k, "count": v, "pourcentage": round(v / total_age * 100, 1)}
        for k, v in tranches.items()
    ]

    # --- 13. Top 5 postes ---
    compteur_postes: dict[str, int] = {}
    for e in employes_actifs:
        nom_poste = e.poste.intitule if e.poste else "Non renseigné"
        compteur_postes[nom_poste] = compteur_postes.get(nom_poste, 0) + 1
    top_postes = sorted(compteur_postes.items(), key=lambda x: x[1], reverse=True)[:5]

    # --- 14. Départs retraite dans les 6 prochains mois ---
    dans_6_mois = aujourdhui + timedelta(days=180)
    employes_retraite = []
    for e in employes_actifs:
        if e.date_naissance:
            age = aujourdhui.year - e.date_naissance.year
            if (aujourdhui.month, aujourdhui.day) < (e.date_naissance.month, e.date_naissance.day):
                age -= 1
            if 59 <= age < 60:
                try:
                    date_60 = date(e.date_naissance.year + 60, e.date_naissance.month, e.date_naissance.day)
                except ValueError:
                    continue
                if aujourdhui <= date_60 <= dans_6_mois:
                    employes_retraite.append({
                        "employe": e,
                        "date_retraite": date_60,
                        "age_actuel": age,
                        "jours_restants": (date_60 - aujourdhui).days,
                    })
    employes_retraite.sort(key=lambda x: x["date_retraite"])

    # --- 15. Données pour les filtres du template ---
    agences_filtre = db.query(models.Agence).order_by(models.Agence.nom).all()
    departements_filtre = db.query(models.Departement).order_by(models.Departement.nom).all()
    postes_filtre = db.query(models.Poste).order_by(models.Poste.intitule).all()
    grades_filtre = db.query(models.Grade).order_by(models.Grade.niveau_hierarchique).all()

    filtres_actifs = _construire_filtres_actifs(
        agence_id=agence_id, departement_id=departement_id, genre=genre,
        poste_id=poste_id, grade_id=grade_id,
        periode=periode, date_debut=date_debut, date_fin=date_fin,
        periode_embauches=periode_embauches, periode_departs=periode_departs,
        periode_turnover=periode_turnover, periode_absences=periode_absences,
        agences=agences_filtre, departements=departements_filtre,
        postes=postes_filtre, grades=grades_filtre,
    )

    # --- 16. Rendu ---
    return templates.TemplateResponse(request, "accueil.html", {
        # En-tête
        "date_aujourdhui": aujourdhui.strftime("%d/%m/%Y"),
        "nb_agences": nb_agences,
        "nb_departements": nb_departements,

        # KPI principaux
        "effectif_total": effectif_total,
        "demandes_en_attente": demandes_en_attente,
        "nouvelles_embauches": nouvelles_embauches,
        "departs_recents": departs_recents,
        "absents_aujourdhui": absents_aujourdhui,

        # KPI période surchargeable
        "turnover": turnover,
        "departs_12_mois": departs_12_mois,
        "employes_retraite": employes_retraite,
        "pyramide_ages": pyramide_ages,
        "top_postes": top_postes,
        "cartes_types": cartes_types,

        # Graphiques
        "repartition_departements": repartition_departements,
        "segments_agences": segments_agences,

        # Tableau
        "demandes_recentes": demandes_recentes,
        "demandes_recentes_total": demandes_recentes_total,

        # Filtres (valeurs actuelles)
        "periode": periode,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "periode_embauches": per_emb,
        "periode_departs": per_dep,
        "periode_turnover": per_tur,
        "periode_absences": per_abs,
        "agence_id": agence_id,
        "departement_id": departement_id,
        "genre": genre,
        "poste_id": poste_id,
        "grade_id": grade_id,

        # Listes pour les selects
        "agences_filtre": agences_filtre,
        "departements_filtre": departements_filtre,
        "postes_filtre": postes_filtre,
        "grades_filtre": grades_filtre,

        # Badges
        "filtres_actifs": filtres_actifs,

        # Libellés de période
        "periode_active_label": periode_active_label,
        "libelle_periode_embauches": PERIODES_LIBELLES.get(per_emb, per_emb),
        "libelle_periode_departs": PERIODES_LIBELLES.get(per_dep, per_dep),
        "libelle_periode_turnover": PERIODES_LIBELLES.get(per_tur, per_tur),
        "libelle_periode_absences": PERIODES_LIBELLES.get(per_abs, per_abs),
    })
    
    
# ============================================================
# HELPERS DE STYLE POUR L'EXPORT EXCEL
# ============================================================

def _style_titre(ws, cellule, texte):
    """Titre principal d'une feuille (fond bleu RH, texte blanc)."""
    ws[cellule] = texte
    ws[cellule].font = Font(bold=True, size=14, color="FFFFFF")
    ws[cellule].fill = PatternFill("solid", fgColor="06547A")
    ws[cellule].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[int(cellule[1:])].height = 26


def _style_sous_titre(ws, cellule, texte):
    """Sous-titre gris italique (contexte, filtres)."""
    ws[cellule] = texte
    ws[cellule].font = Font(italic=True, size=10, color="555555")


def _style_entete_tableau(ws, ligne, colonnes):
    """En-tête d'un tableau (fond bleu clair, texte blanc, centré)."""
    for i, nom in enumerate(colonnes, start=1):
        c = ws.cell(row=ligne, column=i, value=nom)
        c.font = Font(bold=True, color="FFFFFF", size=11)
        c.fill = PatternFill("solid", fgColor="3182CE")
        c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[ligne].height = 20


def _style_ligne_tableau(ws, ligne, valeurs, align_center_cols=()):
    """Ligne de données avec bordures fines."""
    for i, val in enumerate(valeurs, start=1):
        c = ws.cell(row=ligne, column=i, value=val)
        c.alignment = Alignment(
            horizontal="center" if i in align_center_cols else "left",
            vertical="center",
        )
        c.border = Border(
            left=Side(style="thin", color="E2E8F0"),
            right=Side(style="thin", color="E2E8F0"),
            top=Side(style="thin", color="E2E8F0"),
            bottom=Side(style="thin", color="E2E8F0"),
        )

def _ajuster_largeurs(ws, largeurs):
    """Ajuste la largeur des colonnes."""
    for i, w in enumerate(largeurs, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
        
        
# ============================================================
# EXPORT DU DASHBOARD — Rapport Excel complet
# ============================================================

@router.get("/export/dashboard.xlsx")
def export_dashboard_xlsx(
    request: Request,
    db: Session = Depends(get_db),
    periode: str = "30j",
    date_debut: str = "",
    date_fin: str = "",
    periode_embauches: str = "",
    periode_departs: str = "",
    periode_turnover: str = "12m",
    periode_absences: str = "",
    agence_id: str = "",
    departement_id: str = "",
    genre: str = "",
    poste_id: str = "",
    grade_id: str = "",
):
    _exiger_non_employe(request)
    aujourdhui = date.today()

    # --- Filtres ---
    agence_f = _entier_ou_none(agence_id)
    departement_f = _entier_ou_none(departement_id)
    poste_f = _entier_ou_none(poste_id)
    grade_f = _entier_ou_none(grade_id)
    genre_f = genre if genre in ("H", "F") else None

    date_debut_f = _date_ou_none(date_debut)
    date_fin_f = _date_ou_none(date_fin)

    if periode not in PERIODES_LIBELLES:
        periode = "30j"
    p_debut, p_fin = _bornes_periode(periode, date_debut_f, date_fin_f)

    per_emb = periode_embauches if periode_embauches in PERIODES_LIBELLES else periode
    per_dep = periode_departs if periode_departs in PERIODES_LIBELLES else periode
    per_tur = periode_turnover if periode_turnover in PERIODES_LIBELLES else "12m"

    emb_debut, emb_fin = _bornes_periode(per_emb, date_debut_f, date_fin_f)
    dep_debut, dep_fin = _bornes_periode(per_dep, date_debut_f, date_fin_f)
    tur_debut, tur_fin = _bornes_periode(per_tur, date_debut_f, date_fin_f)

    def _filtres_emp(q):
        if agence_f:
            q = q.filter(models.Employe.agence_id == agence_f)
        if departement_f:
            q = q.filter(models.Employe.departement_id == departement_f)
        if genre_f:
            q = q.filter(models.Employe.genre == genre_f)
        if poste_f:
            q = q.filter(models.Employe.poste_id == poste_f)
        if grade_f:
            q = q.filter(models.Employe.grade_id == grade_f)
        return q

    # --- Données ---
    employes_actifs = _filtres_emp(db.query(models.Employe).filter_by(statut="actif")).all()
    effectif_total = len(employes_actifs)

    nouvelles_embauches = _filtres_emp(
        db.query(models.Employe).filter(
            models.Employe.date_embauche >= emb_debut,
            models.Employe.date_embauche <= emb_fin,
        )
    ).count()

    departs_periode = _filtres_emp(
        db.query(models.Depart).join(models.Employe).filter(
            models.Depart.date_depart >= dep_debut,
            models.Depart.date_depart <= dep_fin,
        )
    ).count()

    departs_turnover = _filtres_emp(
        db.query(models.Depart).join(models.Employe).filter(
            models.Depart.date_depart >= tur_debut,
            models.Depart.date_depart <= tur_fin,
        )
    ).count()
    turnover = round((departs_turnover / (effectif_total or 1)) * 100, 1)

    absents_aujourdhui = _filtres_emp(
        db.query(models.Absence).join(models.Employe).filter(
            models.Absence.date_debut <= aujourdhui,
            models.Absence.date_fin >= aujourdhui,
            models.Absence.archivee == False,
        )
    ).count()

    demandes_en_attente = db.query(models.DemandeRh).filter(
        models.DemandeRh.statut.in_(STATUTS_EN_ATTENTE)
    ).count()

    # --- Création du classeur ---
    wb = Workbook()

    # ============================================================
    # FEUILLE 1 — SYNTHÈSE
    # ============================================================
    ws = wb.active
    ws.title = "Synthèse"
    _ajuster_largeurs(ws, [34, 28, 14, 14])

    _style_titre(ws, "A1", "Rapport Dashboard RH — Panafrican SL")
    ws.merge_cells("A1:D1")
    _style_sous_titre(ws, "A2", f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}")
    ws.merge_cells("A2:D2")

    ws["A4"] = "Filtres appliqués"
    ws["A4"].font = Font(bold=True, size=12, color="06547A")
    ligne = 5

    def _ajout_filtre(ligne, label, valeur):
        ws.cell(row=ligne, column=1, value=label).font = Font(bold=True, color="555555")
        ws.cell(row=ligne, column=2, value=valeur)

    _ajout_filtre(ligne, "Période globale", PERIODES_LIBELLES.get(periode, periode)); ligne += 1
    _ajout_filtre(ligne, "Période Embauches", PERIODES_LIBELLES.get(per_emb, per_emb)); ligne += 1
    _ajout_filtre(ligne, "Période Départs", PERIODES_LIBELLES.get(per_dep, per_dep)); ligne += 1
    _ajout_filtre(ligne, "Période Turnover", PERIODES_LIBELLES.get(per_tur, per_tur)); ligne += 1
    if agence_f:
        ag = db.query(models.Agence).get(agence_f)
        _ajout_filtre(ligne, "Agence", ag.nom if ag else ""); ligne += 1
    if departement_f:
        dp = db.query(models.Departement).get(departement_f)
        _ajout_filtre(ligne, "Département", dp.nom if dp else ""); ligne += 1
    if genre_f:
        _ajout_filtre(ligne, "Genre", "Hommes" if genre_f == "H" else "Femmes"); ligne += 1
    if poste_f:
        po = db.query(models.Poste).get(poste_f)
        _ajout_filtre(ligne, "Poste", po.intitule if po else ""); ligne += 1
    if grade_f:
        gr = db.query(models.Grade).get(grade_f)
        _ajout_filtre(ligne, "Grade", gr.libelle if gr else ""); ligne += 1

    ligne += 1
    ws.cell(row=ligne, column=1, value="Indicateurs clés").font = Font(bold=True, size=12, color="06547A")
    ligne += 1
    _style_entete_tableau(ws, ligne, ["Indicateur", "Valeur"]); ligne += 1

    kpis = [
        ("Effectif total actif", effectif_total),
        ("Demandes en attente", demandes_en_attente),
        (f"Embauches ({PERIODES_LIBELLES.get(per_emb, per_emb)})", nouvelles_embauches),
        (f"Départs ({PERIODES_LIBELLES.get(per_dep, per_dep)})", departs_periode),
        (f"Turnover ({PERIODES_LIBELLES.get(per_tur, per_tur)})", f"{turnover} %"),
        ("Absents aujourd'hui", absents_aujourdhui),
    ]
    for label, val in kpis:
        _style_ligne_tableau(ws, ligne, [label, val], align_center_cols=(2,))
        ligne += 1

    # ============================================================
    # FEUILLE 2 — DÉPARTEMENTS
    # ============================================================
    ws2 = wb.create_sheet("Départements")
    _ajuster_largeurs(ws2, [40, 14, 14])
    _style_titre(ws2, "A1", "Répartition par département"); ws2.merge_cells("A1:C1")
    _style_sous_titre(ws2, "A2", f"Total : {effectif_total} employés actifs"); ws2.merge_cells("A2:C2")

    compteur_dep: dict[str, int] = {}
    for e in employes_actifs:
        nom = e.departement.nom if e.departement else "Non renseigné"
        compteur_dep[nom] = compteur_dep.get(nom, 0) + 1

    _style_entete_tableau(ws2, 4, ["Département", "Effectif", "%"])
    lg = 5
    for nom, c in sorted(compteur_dep.items(), key=lambda x: x[1], reverse=True):
        pct = round(c / (effectif_total or 1) * 100, 1)
        _style_ligne_tableau(ws2, lg, [nom, c, f"{pct} %"], align_center_cols=(2, 3))
        lg += 1

    # ============================================================
    # FEUILLE 3 — AGENCES
    # ============================================================
    ws3 = wb.create_sheet("Agences")
    _ajuster_largeurs(ws3, [40, 14, 14])
    _style_titre(ws3, "A1", "Répartition par agence"); ws3.merge_cells("A1:C1")
    _style_sous_titre(ws3, "A2", f"Total : {effectif_total} employés actifs"); ws3.merge_cells("A2:C2")

    compteur_ag: dict[str, int] = {}
    for e in employes_actifs:
        nom = e.agence.nom if e.agence else "Direction Générale"
        compteur_ag[nom] = compteur_ag.get(nom, 0) + 1

    _style_entete_tableau(ws3, 4, ["Agence", "Effectif", "%"])
    lg = 5
    for nom, c in sorted(compteur_ag.items(), key=lambda x: x[1], reverse=True):
        pct = round(c / (effectif_total or 1) * 100, 1)
        _style_ligne_tableau(ws3, lg, [nom, c, f"{pct} %"], align_center_cols=(2, 3))
        lg += 1

    # ============================================================
    # FEUILLE 4 — PYRAMIDE DES ÂGES
    # ============================================================
    ws4 = wb.create_sheet("Pyramide des âges")
    _ajuster_largeurs(ws4, [20, 14, 14])
    _style_titre(ws4, "A1", "Pyramide des âges"); ws4.merge_cells("A1:C1")
    _style_sous_titre(ws4, "A2", f"Répartition des {effectif_total} employés actifs"); ws4.merge_cells("A2:C2")

    tranches = {"≤25 ans": 0, "26-35 ans": 0, "36-45 ans": 0, "46-55 ans": 0, "56+ ans": 0}
    for e in employes_actifs:
        if e.date_naissance:
            age = aujourdhui.year - e.date_naissance.year
            if (aujourdhui.month, aujourdhui.day) < (e.date_naissance.month, e.date_naissance.day):
                age -= 1
            if age <= 25:
                tranches["≤25 ans"] += 1
            elif age <= 35:
                tranches["26-35 ans"] += 1
            elif age <= 45:
                tranches["36-45 ans"] += 1
            elif age <= 55:
                tranches["46-55 ans"] += 1
            else:
                tranches["56+ ans"] += 1

    _style_entete_tableau(ws4, 4, ["Tranche d'âge", "Effectif", "%"])
    lg = 5
    total_age = sum(tranches.values()) or 1
    for k, v in tranches.items():
        pct = round(v / total_age * 100, 1)
        _style_ligne_tableau(ws4, lg, [k, v, f"{pct} %"], align_center_cols=(2, 3))
        lg += 1

    # ============================================================
    # FEUILLE 5 — TOP POSTES
    # ============================================================
    ws5 = wb.create_sheet("Top postes")
    _ajuster_largeurs(ws5, [45, 14])
    _style_titre(ws5, "A1", "Top 10 des postes"); ws5.merge_cells("A1:B1")
    _style_sous_titre(ws5, "A2", f"Postes les plus représentés ({effectif_total} employés)"); ws5.merge_cells("A2:B2")

    compteur_pos: dict[str, int] = {}
    for e in employes_actifs:
        nom = e.poste.intitule if e.poste else "Non renseigné"
        compteur_pos[nom] = compteur_pos.get(nom, 0) + 1
    top = sorted(compteur_pos.items(), key=lambda x: x[1], reverse=True)[:10]

    _style_entete_tableau(ws5, 4, ["Poste", "Effectif"])
    lg = 5
    for nom, c in top:
        _style_ligne_tableau(ws5, lg, [nom, c], align_center_cols=(2,))
        lg += 1

    # ============================================================
    # FEUILLE 6 — DÉPARTS RETRAITE
    # ============================================================
    ws6 = wb.create_sheet("Départs retraite")
    _ajuster_largeurs(ws6, [28, 28, 24, 16, 14])
    _style_titre(ws6, "A1", "Départs à la retraite — 6 prochains mois"); ws6.merge_cells("A1:E1")
    _style_sous_titre(ws6, "A2", "Employés atteignant 60 ans dans les 6 prochains mois"); ws6.merge_cells("A2:E2")

    dans_6_mois = aujourdhui + timedelta(days=180)
    retraites = []
    for e in employes_actifs:
        if e.date_naissance:
            age = aujourdhui.year - e.date_naissance.year
            if (aujourdhui.month, aujourdhui.day) < (e.date_naissance.month, e.date_naissance.day):
                age -= 1
            if 59 <= age < 60:
                try:
                    date_60 = date(e.date_naissance.year + 60, e.date_naissance.month, e.date_naissance.day)
                except ValueError:
                    continue
                if aujourdhui <= date_60 <= dans_6_mois:
                    retraites.append((e, date_60, (date_60 - aujourdhui).days))
    retraites.sort(key=lambda x: x[1])

    _style_entete_tableau(ws6, 4, ["Employé", "Poste", "Département", "Date retraite", "Jours restants"])
    lg = 5
    for e, d, j in retraites:
        _style_ligne_tableau(ws6, lg, [
            f"{e.nom} {e.prenom}",
            e.poste.intitule if e.poste else "—",
            e.departement.nom if e.departement else "—",
            d.strftime("%d/%m/%Y"),
            j,
        ], align_center_cols=(4, 5))
        lg += 1
    if not retraites:
        ws6.cell(row=5, column=1, value="Aucun départ retraite prévu dans les 6 prochains mois.").font = Font(italic=True, color="888888")

    # ============================================================
    # FEUILLE 7 — DEMANDES RÉCENTES
    # ============================================================
    ws7 = wb.create_sheet("Demandes récentes")
    _ajuster_largeurs(ws7, [28, 24, 22, 22, 14, 16])
    _style_titre(ws7, "A1", "Demandes récentes nécessitant validation"); ws7.merge_cells("A1:F1")
    _style_sous_titre(ws7, "A2", f"{demandes_en_attente} demandes en attente au total"); ws7.merge_cells("A2:F2")

    dr = db.query(models.DemandeRh).order_by(models.DemandeRh.date_demande.desc()).limit(30).all()
    _style_entete_tableau(ws7, 4, ["Employé", "Type", "Agence", "Département", "Date", "Statut"])
    lg = 5
    for d in dr:
        emp = d.employe_concerne
        _style_ligne_tableau(ws7, lg, [
            f"{emp.nom} {emp.prenom}" if emp else "—",
            d.type_demande.libelle if d.type_demande else "—",
            (emp.agence.nom if emp and emp.agence else "Direction Générale") if emp else "—",
            emp.departement.nom if emp and emp.departement else "—",
            d.date_demande.strftime("%d/%m/%Y") if d.date_demande else "—",
            d.statut or "—",
        ], align_center_cols=(5, 6))
        lg += 1

    # --- Sauvegarde dans un buffer ---
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    nom_fichier = f"rapport_dashboard_rh_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'},
    )
# ============================================================
# EXPORT DU DASHBOARD
# ============================================================

@router.get("/export/dashboard.csv")
def export_dashboard_csv(
    request: Request,
    db: Session = Depends(get_db),
    periode: str = "30j",
    date_debut: str = "",
    date_fin: str = "",
    periode_embauches: str = "",
    periode_departs: str = "",
    periode_turnover: str = "12m",
    periode_absences: str = "",
    agence_id: str = "",
    departement_id: str = "",
    genre: str = "",
    poste_id: str = "",
    grade_id: str = "",
):
    _exiger_non_employe(request)
    aujourdhui = date.today()

    # --- Récupérer les mêmes filtres que le dashboard ---
    agence_f = _entier_ou_none(agence_id)
    departement_f = _entier_ou_none(departement_id)
    poste_f = _entier_ou_none(poste_id)
    grade_f = _entier_ou_none(grade_id)
    genre_f = genre if genre in ("H", "F") else None

    date_debut_f = _date_ou_none(date_debut)
    date_fin_f = _date_ou_none(date_fin)

    if periode not in PERIODES_LIBELLES:
        periode = "30j"
    p_debut, p_fin = _bornes_periode(periode, date_debut_f, date_fin_f)

    per_emb = periode_embauches if periode_embauches in PERIODES_LIBELLES else periode
    per_dep = periode_departs if periode_departs in PERIODES_LIBELLES else periode
    per_tur = periode_turnover if periode_turnover in PERIODES_LIBELLES else "12m"

    emb_debut, emb_fin = _bornes_periode(per_emb, date_debut_f, date_fin_f)
    dep_debut, dep_fin = _bornes_periode(per_dep, date_debut_f, date_fin_f)
    tur_debut, tur_fin = _bornes_periode(per_tur, date_debut_f, date_fin_f)

    # --- Filtres communs ---
    def _appliquer_filtres_emp(q):
        if agence_f:
            q = q.filter(models.Employe.agence_id == agence_f)
        if departement_f:
            q = q.filter(models.Employe.departement_id == departement_f)
        if genre_f:
            q = q.filter(models.Employe.genre == genre_f)
        if poste_f:
            q = q.filter(models.Employe.poste_id == poste_f)
        if grade_f:
            q = q.filter(models.Employe.grade_id == grade_f)
        return q

    # --- Calcul des KPI (identiques au dashboard) ---
    employes_actifs = _appliquer_filtres_emp(
        db.query(models.Employe).filter_by(statut="actif")
    ).all()
    effectif_total = len(employes_actifs)

    nouvelles_embauches = _appliquer_filtres_emp(
        db.query(models.Employe).filter(
            models.Employe.date_embauche >= emb_debut,
            models.Employe.date_embauche <= emb_fin,
        )
    ).count()

    departs_periode = _appliquer_filtres_emp(
        db.query(models.Depart).join(models.Employe).filter(
            models.Depart.date_depart >= dep_debut,
            models.Depart.date_depart <= dep_fin,
        )
    ).count()

    departs_turnover = _appliquer_filtres_emp(
        db.query(models.Depart).join(models.Employe).filter(
            models.Depart.date_depart >= tur_debut,
            models.Depart.date_depart <= tur_fin,
        )
    ).count()
    turnover = round((departs_turnover / (effectif_total or 1)) * 100, 1)

    absents_aujourdhui = _appliquer_filtres_emp(
        db.query(models.Absence).join(models.Employe).filter(
            models.Absence.date_debut <= aujourdhui,
            models.Absence.date_fin >= aujourdhui,
            models.Absence.archivee == False,
        )
    ).count()

    demandes_en_attente = db.query(models.DemandeRh).filter(
        models.DemandeRh.statut.in_(STATUTS_EN_ATTENTE)
    ).count()

    # --- Construction du CSV ---
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")  # ; pour Excel FR

    # En-tête du rapport
    writer.writerow(["Rapport Dashboard RH — Panafrican SL"])
    writer.writerow(["Généré le", datetime.now().strftime("%d/%m/%Y à %H:%M")])
    writer.writerow([])

    # Filtres appliqués
    writer.writerow(["Filtres appliqués"])
    writer.writerow(["Période globale", PERIODES_LIBELLES.get(periode, periode)])
    writer.writerow(["Période Embauches", PERIODES_LIBELLES.get(per_emb, per_emb)])
    writer.writerow(["Période Départs", PERIODES_LIBELLES.get(per_dep, per_dep)])
    writer.writerow(["Période Turnover", PERIODES_LIBELLES.get(per_tur, per_tur)])
    if agence_f:
        ag = db.query(models.Agence).get(agence_f)
        writer.writerow(["Agence", ag.nom if ag else ""])
    if departement_f:
        dp = db.query(models.Departement).get(departement_f)
        writer.writerow(["Département", dp.nom if dp else ""])
    if genre_f:
        writer.writerow(["Genre", "Hommes" if genre_f == "H" else "Femmes"])
    if poste_f:
        po = db.query(models.Poste).get(poste_f)
        writer.writerow(["Poste", po.intitule if po else ""])
    if grade_f:
        gr = db.query(models.Grade).get(grade_f)
        writer.writerow(["Grade", gr.libelle if gr else ""])
    writer.writerow([])

    # KPI
    writer.writerow(["Indicateur", "Valeur"])
    writer.writerow(["Effectif total", effectif_total])
    writer.writerow(["Demandes en attente", demandes_en_attente])
    writer.writerow([f"Embauches ({PERIODES_LIBELLES.get(per_emb, per_emb)})", nouvelles_embauches])
    writer.writerow([f"Départs ({PERIODES_LIBELLES.get(per_dep, per_dep)})", departs_periode])
    writer.writerow([f"Turnover ({PERIODES_LIBELLES.get(per_tur, per_tur)})", f"{turnover}%"])
    writer.writerow(["Absents aujourd'hui", absents_aujourdhui])
    writer.writerow([])

    # Répartition par département
    writer.writerow(["Répartition par département"])
    writer.writerow(["Département", "Effectif"])
    compteur_dep: dict[str, int] = {}
    for e in employes_actifs:
        nom = e.departement.nom if e.departement else "Non renseigné"
        compteur_dep[nom] = compteur_dep.get(nom, 0) + 1
    for nom, c in sorted(compteur_dep.items(), key=lambda x: x[1], reverse=True):
        writer.writerow([nom, c])
    writer.writerow([])

    # Répartition par agence
    writer.writerow(["Répartition par agence"])
    writer.writerow(["Agence", "Effectif"])
    compteur_ag: dict[str, int] = {}
    for e in employes_actifs:
        nom = e.agence.nom if e.agence else "Direction Générale"
        compteur_ag[nom] = compteur_ag.get(nom, 0) + 1
    for nom, c in sorted(compteur_ag.items(), key=lambda x: x[1], reverse=True):
        writer.writerow([nom, c])
    writer.writerow([])

    # Pyramide des âges
    writer.writerow(["Pyramide des âges"])
    writer.writerow(["Tranche", "Effectif"])
    tranches = {"≤25": 0, "26-35": 0, "36-45": 0, "46-55": 0, "56+": 0}
    for e in employes_actifs:
        if e.date_naissance:
            age = aujourdhui.year - e.date_naissance.year
            if (aujourdhui.month, aujourdhui.day) < (e.date_naissance.month, e.date_naissance.day):
                age -= 1
            if age <= 25:
                tranches["≤25"] += 1
            elif age <= 35:
                tranches["26-35"] += 1
            elif age <= 45:
                tranches["36-45"] += 1
            elif age <= 55:
                tranches["46-55"] += 1
            else:
                tranches["56+"] += 1
    for k, v in tranches.items():
        writer.writerow([f"{k} ans", v])

    contenu = "\ufeff" + buffer.getvalue()  # BOM UTF-8 pour Excel
    nom_fichier = f"dashboard_rh_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"

    return Response(
        content=contenu,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'},
    )
