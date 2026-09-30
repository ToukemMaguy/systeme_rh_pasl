"""Journal d'audit (lot 1, point 1) : qui a fait quoi, quand, et avec quelles valeurs avant / après.

Fonctionnement AUTOMATIQUE : à chaque enregistrement en base (création, modification, suppression)
d'un objet suivi (employé, demande, absence, sanction, compte...), une ligne est ajoutée dans la table
journal_audit, dans la même transaction. Aucune page n'a besoin d'y penser : on ne peut pas « oublier »
de tracer une action.

L'auteur de l'action est connu grâce à un « contexte de requête » rempli par le middleware
d'authentification (main.py) : identifiant, nom, rôle et adresse IP de l'utilisateur connecté.

Le journal est en lecture seule dans l'application : aucune page ne permet de le modifier ou de le vider.
"""
import contextvars
import datetime as dt
from decimal import Decimal

from sqlalchemy import event, inspect, insert
from sqlalchemy.orm import Session

from . import models

# --- Auteur de l'action en cours (rempli par le middleware à chaque requête) ---
_contexte = contextvars.ContextVar("contexte_audit", default=None)

UTILISATEUR_SYSTEME = {"id": None, "nom": "Système (tâche automatique)", "role": None, "ip": None}


def definir_auteur(user_id=None, nom=None, role=None, ip=None):
    _contexte.set({"id": user_id, "nom": nom, "role": role, "ip": ip})


def auteur_courant() -> dict:
    return _contexte.get() or UTILISATEUR_SYSTEME


# --- Objets suivis : nom lisible par table ---
OBJETS_SUIVIS = {
    models.Employe: "Employé",
    models.Affectation: "Affectation",
    models.Absence: "Absence",
    models.SoldeConge: "Solde de congés",
    models.Depart: "Départ",
    models.DemandeRh: "Demande RH",
    models.Sanction: "Sanction",
    models.Utilisateur: "Compte utilisateur",
    models.Departement: "Département",
    models.Agence: "Agence",
    models.Poste: "Poste",
    models.Grade: "Grade",
    models.TypeAbsence: "Type d'absence",
    models.TypeDemande: "Type de demande",
    models.Licenciement: "Dossier de licenciement",
}

# Colonnes jamais journalisées (bruit) ou masquées (secret)
COLONNES_IGNOREES = {"created_at", "updated_at", "date_enregistrement", "tentatives_echouees"}
COLONNES_MASQUEES = {"mot_de_passe_hash"}


def _valeur(v):
    """Rend une valeur enregistrable en JSON."""
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (str, int, float, bool, dict, list)) or v is None:
        return v
    return str(v)


def _employe_concerne(obj):
    """Employé auquel se rapporte l'objet (pour retrouver l'historique d'un employé)."""
    if isinstance(obj, models.Employe):
        return obj.id
    return getattr(obj, "employe_id", None) or getattr(obj, "employe_concerne_id", None)


def _changements(obj, action):
    """Dictionnaire {colonne: [avant, après]} (création : avant = None ; suppression : après = None)."""
    etat = inspect(obj)
    resultat = {}
    for colonne in etat.mapper.column_attrs:
        nom = colonne.key
        if nom in COLONNES_IGNOREES:
            continue
        historique = etat.attrs[nom].history
        if action == "modification":
            if not historique.has_changes():
                continue
            avant = historique.deleted[0] if historique.deleted else None
            apres = historique.added[0] if historique.added else None
        elif action == "creation":
            avant, apres = None, getattr(obj, nom)
            if apres is None:
                continue
        else:  # suppression
            avant, apres = getattr(obj, nom), None
        if nom in COLONNES_MASQUEES:
            avant, apres = ("***" if avant else None), "*** modifié ***" if apres else None
        resultat[nom] = [_valeur(avant), _valeur(apres)]
    return resultat


@event.listens_for(Session, "after_flush")
def _journaliser_modifications(session, contexte_flush):
    """Appelé automatiquement après chaque écriture en base : ajoute les lignes du journal."""
    auteur = auteur_courant()
    lignes = []
    for action, objets in (("creation", session.new), ("modification", session.dirty), ("suppression", session.deleted)):
        for obj in objets:
            libelle = OBJETS_SUIVIS.get(type(obj))
            if not libelle:
                continue
            if action == "modification" and not session.is_modified(obj, include_collections=False):
                continue
            details = _changements(obj, action)
            if action == "modification" and not details:
                continue
            lignes.append({
                "date_heure": dt.datetime.now(),
                "utilisateur_id": auteur["id"],
                "utilisateur_nom": auteur["nom"],
                "role": auteur["role"],
                "adresse_ip": auteur["ip"],
                "action": action,
                "objet_type": libelle,
                "objet_id": inspect(obj).mapper.primary_key_from_instance(obj)[0],
                "employe_id": _employe_concerne(obj),
                "description": None,
                "details": details,
            })
    if lignes:
        # Écriture directe dans la même transaction (sans repasser par la session : pas de boucle)
        session.connection().execute(insert(models.JournalAudit.__table__), lignes)


def journaliser_evenement(db: Session, action: str, description: str, utilisateur=None, ip: str | None = None):
    """Événements qui ne sont pas des modifications de données : connexion, échec, déconnexion."""
    db.add(models.JournalAudit(
        date_heure=dt.datetime.now(),
        utilisateur_id=getattr(utilisateur, "id", None),
        utilisateur_nom=getattr(utilisateur, "nom", None),
        role=getattr(utilisateur, "role", None),
        adresse_ip=ip,
        action=action,
        objet_type="Session",
        description=description,
    ))


# ------------------------------------------------------------------
# Affichage : noms lisibles des colonnes les plus courantes
# ------------------------------------------------------------------
LIBELLES_COLONNES = {
    "nom": "Nom", "prenom": "Prénom", "matricule": "Matricule", "genre": "Genre", "statut": "Statut",
    "date_embauche": "Date d'embauche", "date_naissance": "Date de naissance",
    "telephone_pro": "Téléphone pro", "telephone_perso": "Téléphone perso",
    "email_pro": "Email pro", "email_perso": "Email perso", "email": "Email",
    "departement_id": "Département", "agence_id": "Agence", "poste_id": "Poste", "grade_id": "Grade",
    "n_plus_1_id": "N+1", "statut_matrimonial": "Situation matrimoniale", "nombre_enfants": "Nombre d'enfants",
    "date_debut": "Début", "date_fin": "Fin", "motif": "Motif", "justifiee": "Justifiée", "archivee": "Archivée",
    "jours_deduits_conges": "Jours déduits", "jours_pris": "Jours pris", "jours_restants": "Jours restants",
    "jours_alloues": "Jours alloués", "type_sanction": "Type de sanction", "date_sanction": "Date de la sanction",
    "avis_n_plus_1": "Avis du N+1", "periode_accordee_debut": "Début accordé", "periode_accordee_fin": "Fin accordée",
    "role": "Rôle", "mot_de_passe_hash": "Mot de passe", "compte_actif": "Compte actif",
    "doit_changer_mdp": "Mot de passe à changer", "bloque_jusqua": "Bloqué jusqu'à",
    "lettre_texte": "Texte de la lettre", "date_depart": "Date de départ", "type_depart": "Type de départ", "commentaire": "Commentaire",
}
