from sqlalchemy import (
    Column, Integer, String, Date, DateTime, Text, Numeric, ForeignKey,
    CheckConstraint, UniqueConstraint, JSON, func, Boolean
)
from sqlalchemy.orm import relationship
from .database import Base
from datetime import datetime

class Departement(Base):
    __tablename__ = "departements"
    id = Column(Integer, primary_key=True)
    nom = Column(String(150), unique=True, nullable=False)
    code = Column(String(20), unique=True, nullable=True)


class Agence(Base):
    __tablename__ = "agences"
    id = Column(Integer, primary_key=True)
    nom = Column(String(150), unique=True, nullable=False)
    ville = Column(String(100))
    region = Column(String(100))


class Grade(Base):
    __tablename__ = "grades"
    id = Column(Integer, primary_key=True)
    libelle = Column(String(100), unique=True, nullable=False)
    niveau_hierarchique = Column(Integer)


class Poste(Base):
    __tablename__ = "postes"
    id = Column(Integer, primary_key=True)
    intitule = Column(String(200), unique=True, nullable=False)


class TypeAbsence(Base):
    __tablename__ = "types_absence"
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    libelle = Column(String(150), nullable=False)
    categorie = Column(String(20), nullable=False, default="Absence")
    genre_requis = Column(String(1), nullable=True)
    plafond_jours = Column(Integer, nullable=True)
    deductible_conge = Column(Boolean, default=False)
    duree_standard_jours = Column(Integer, nullable=True)


class TypeDemande(Base):
    __tablename__ = "types_demande"
    id = Column(Integer, primary_key=True)
    libelle = Column(String(100), unique=True, nullable=False)


class Employe(Base):
    __tablename__ = "employes"
    id = Column(Integer, primary_key=True)
    matricule = Column(String(20), unique=True, nullable=True)
    nom = Column(String(100), nullable=False)
    prenom = Column(String(100), nullable=False)
    genre = Column(String(1))
    date_embauche = Column(Date, nullable=False)
    telephone_pro = Column(String(30))
    telephone_perso = Column(String(30))
    email_pro = Column(String(150), nullable=True)
    email_perso = Column(String(150))
    date_naissance = Column(Date, nullable=True)
    photo_path = Column(String(255), nullable=True)
    cni_path = Column(String(255), nullable=True)
    plan_localisation_path = Column(String(255), nullable=True)
    statut = Column(String(20), default="actif")
    departement_id = Column(Integer, ForeignKey("departements.id"), nullable=False)
    agence_id = Column(Integer, ForeignKey("agences.id"), nullable=True)
    poste_id = Column(Integer, ForeignKey("postes.id"), nullable=False)
    grade_id = Column(Integer, ForeignKey("grades.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    statut_matrimonial = Column(String(30), nullable=True)
    nombre_enfants = Column(Integer, nullable=True)
    contact_urgence_nom = Column(String(100), nullable=True)
    contact_urgence_tel = Column(String(30), nullable=True)
    n_plus_1_id = Column(Integer, ForeignKey("employes.id"), nullable=True)

    __table_args__ = (CheckConstraint("genre IN ('H','F')", name="ck_employe_genre"),)

    departement = relationship("Departement")
    agence = relationship("Agence")
    poste = relationship("Poste")
    grade = relationship("Grade")
    sanctions = relationship("Sanction", back_populates="employe", cascade="all, delete-orphan")
    n_plus_1 = relationship("Employe", remote_side=[id], foreign_keys=[n_plus_1_id])


class Affectation(Base):
    __tablename__ = "affectations"
    id = Column(Integer, primary_key=True)
    employe_id = Column(Integer, ForeignKey("employes.id"), nullable=False)
    departement_id = Column(Integer, ForeignKey("departements.id"), nullable=True)
    agence_id = Column(Integer, ForeignKey("agences.id"), nullable=True)
    poste_id = Column(Integer, ForeignKey("postes.id"), nullable=False)
    grade_id = Column(Integer, ForeignKey("grades.id"), nullable=False)
    date_debut = Column(Date, nullable=False)
    date_fin = Column(Date, nullable=True)
    type_mouvement = Column(String(30))
    motif = Column(Text)

    employe = relationship("Employe")
    departement = relationship("Departement")
    agence = relationship("Agence")
    poste = relationship("Poste")
    grade = relationship("Grade")


class Absence(Base):
    __tablename__ = "absences"
    id = Column(Integer, primary_key=True)
    employe_id = Column(Integer, ForeignKey("employes.id"), nullable=False)
    type_absence_id = Column(Integer, ForeignKey("types_absence.id"), nullable=False)
    date_debut = Column(Date, nullable=False)
    date_fin = Column(Date, nullable=False)
    motif = Column(Text)
    justifiee = Column(Boolean, default=False, nullable=False)
    justificatif_path = Column(String(255), nullable=True)
    enregistre_par = Column(String(100), nullable=True)
    jours_deduits_conges = Column(Numeric(5, 1), nullable=True)

    archivee = Column(Boolean, default=False, nullable=False)
    employe = relationship("Employe")
    type_absence = relationship("TypeAbsence")
    date_enregistrement = Column(DateTime, default=datetime.utcnow, nullable=False)


class SoldeConge(Base):
    __tablename__ = "solde_conges"
    id = Column(Integer, primary_key=True)
    employe_id = Column(Integer, ForeignKey("employes.id"), nullable=False)
    annee = Column(Integer, nullable=False)
    jours_alloues = Column(Numeric(5, 1))
    jours_pris = Column(Numeric(5, 1))
    jours_restants = Column(Numeric(5, 1))

    __table_args__ = (UniqueConstraint("employe_id", "annee", name="uq_solde_employe_annee"),)

    employe = relationship("Employe")


class Depart(Base):
    __tablename__ = "departs"
    id = Column(Integer, primary_key=True)
    employe_id = Column(Integer, ForeignKey("employes.id"), nullable=False)
    date_depart = Column(Date, nullable=False)
    motif = Column(Text)
    type_depart = Column(String(50))


class Utilisateur(Base):
    __tablename__ = "utilisateurs"
    id = Column(Integer, primary_key=True)
    nom = Column(String(150), nullable=False)
    email = Column(String(150), unique=True, nullable=False)
    mot_de_passe_hash = Column(String(255), nullable=False)
    role = Column(String(20))
    employe_id = Column(Integer, ForeignKey("employes.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    # --- Sécurité des comptes (lot 1, point 3) ---
    # Nombre de mots de passe erronés consécutifs ; remis à 0 après une connexion réussie.
    tentatives_echouees = Column(Integer, default=0, server_default="0", nullable=False)
    # Si renseigné et dans le futur : connexion refusée jusqu'à cette date/heure.
    bloque_jusqua = Column(DateTime, nullable=True)
    # True après une création ou une réinitialisation par l'administrateur :
    # l'utilisateur doit choisir son propre mot de passe à la connexion suivante.
    doit_changer_mdp = Column(Boolean, default=False, server_default="0", nullable=False)

    # --- Désactivation des accès (lot 1, point 4) ---
    # Un compte n'est jamais supprimé au départ d'un employé : il est désactivé (historique conservé).
    compte_actif = Column(Boolean, default=True, server_default="1", nullable=False)
    desactive_le = Column(DateTime, nullable=True)
    motif_desactivation = Column(String(255), nullable=True)

    # [CORRECTIF B22] lien vers la fiche employé : la page « Comptes utilisateurs » l'utilisait
    # (u.employe) mais il n'existait pas, la colonne « Employé rattaché » restait donc toujours vide.
    employe = relationship("Employe")


class DemandeRh(Base):
    __tablename__ = "demandes_rh"
    id = Column(Integer, primary_key=True)
    type_demande_id = Column(Integer, ForeignKey("types_demande.id"), nullable=False)
    employe_concerne_id = Column(Integer, ForeignKey("employes.id"), nullable=True)
    demandeur_id = Column(Integer, ForeignKey("utilisateurs.id"), nullable=False)
    date_demande = Column(DateTime, server_default=func.now())
    statut = Column(String(30), default="en_attente_n_plus_1")
    valide_par_id = Column(Integer, ForeignKey("utilisateurs.id"), nullable=True)
    date_validation = Column(DateTime, nullable=True)
    commentaire = Column(Text)
    donnees_specifiques = Column(JSON)

    # --- Workflow N+1 ---
    suppleant_id = Column(Integer, ForeignKey("employes.id"), nullable=True)
    avis_n_plus_1 = Column(String(20), default="en_attente")  # en_attente / favorable / defavorable
    commentaire_n_plus_1 = Column(Text, nullable=True)
    date_avis_n_plus_1 = Column(DateTime, nullable=True)

    # --- Périodes ---
    periode_sollicitee_debut = Column(Date, nullable=True)
    periode_sollicitee_fin = Column(Date, nullable=True)
    periode_accordee_debut = Column(Date, nullable=True)
    periode_accordee_fin = Column(Date, nullable=True)

    type_demande = relationship("TypeDemande")
    employe_concerne = relationship("Employe", foreign_keys=[employe_concerne_id])
    suppleant = relationship("Employe", foreign_keys=[suppleant_id])
    demandeur = relationship("Utilisateur", foreign_keys=[demandeur_id])
    valide_par = relationship("Utilisateur", foreign_keys=[valide_par_id])

class Sanction(Base):
    __tablename__ = "sanctions"

    id = Column(Integer, primary_key=True, index=True)
    employe_id = Column(Integer, ForeignKey("employes.id"), nullable=False)
    type_sanction = Column(String(50), nullable=False)
    motif = Column(Text, nullable=True)
    date_sanction = Column(Date, nullable=False)
    duree = Column(String(30), nullable=True)
    commentaire = Column(Text, nullable=True)
    enregistre_par = Column(String(100), nullable=True)
    date_enregistrement = Column(DateTime, default=datetime.utcnow)

    employe = relationship("Employe", back_populates="sanctions")


class MailAEnvoyer(Base):
    __tablename__ = "mails_a_envoyer"

    id = Column(Integer, primary_key=True)
    destinataire = Column(String(255), nullable=False)
    sujet = Column(String(255), nullable=False)
    corps = Column(Text, nullable=False)
    statut = Column(String(20), default="en_attente", nullable=False)
    message_erreur = Column(Text, nullable=True)
    date_creation = Column(DateTime, default=datetime.utcnow, nullable=False)
    date_envoi = Column(DateTime, nullable=True)
    demande_id = Column(Integer, ForeignKey("demandes_rh.id"), nullable=True)
    type_mail = Column(String(50), nullable=True)

    demande = relationship("DemandeRh")


class JournalAudit(Base):
    """Journal d'audit (lot 1, point 1). Alimenté automatiquement par app/journal.py.
    Aucune page de l'application ne permet de le modifier ou de le supprimer."""
    __tablename__ = "journal_audit"

    id = Column(Integer, primary_key=True)
    date_heure = Column(DateTime, nullable=False, index=True)
    utilisateur_id = Column(Integer, nullable=True, index=True)   # pas de clé étrangère : la trace survit au compte
    utilisateur_nom = Column(String(150), nullable=True)
    role = Column(String(30), nullable=True)
    adresse_ip = Column(String(45), nullable=True)
    action = Column(String(30), nullable=False)                    # creation / modification / suppression / connexion...
    objet_type = Column(String(50), nullable=False, index=True)    # Employé, Demande RH, Absence...
    objet_id = Column(Integer, nullable=True)
    employe_id = Column(Integer, nullable=True, index=True)        # employé concerné (historique d'un employé)
    description = Column(Text, nullable=True)
    details = Column(JSON, nullable=True)                          # {colonne: [avant, après]}


class Licenciement(Base):
    """Dossier de licenciement (étape 3).

    Circuit : ouverture (RH) → conseil de discipline + PV (saisie RH) → transmission au Comité de direction
    → décision du Comité (approuver / rejeter / renvoyer pour complément) → notification (RH) → sortie
    automatique à la date prévue. Si le conseil propose une sanction plus légère, la RH clôt le dossier et
    la sanction est créée automatiquement.
    Aucun salaire ni montant n'est enregistré : le dossier fournit les durées (préavis, congés restants),
    les montants sont calculés par le service paie.
    """
    __tablename__ = "licenciements"

    id = Column(Integer, primary_key=True)
    employe_id = Column(Integer, ForeignKey("employes.id"), nullable=False, index=True)
    # ouvert / transmis / complement / approuve / notifie / rejete / clos_sanction / annule
    statut = Column(String(20), nullable=False, default="ouvert")

    # --- 1. Ouverture ---
    type_motif = Column(String(40), nullable=False)
    date_faits = Column(Date, nullable=True)
    expose_faits = Column(Text, nullable=True)
    sanctions_liees = Column(JSON, nullable=True)            # identifiants de sanctions antérieures
    mise_a_pied_conservatoire = Column(Boolean, default=False, nullable=False)
    mise_a_pied_debut = Column(Date, nullable=True)
    mise_a_pied_fin = Column(Date, nullable=True)

    # --- 2. Conseil de discipline ---
    conseil_date = Column(Date, nullable=True)
    conseil_membres = Column(Text, nullable=True)
    conseil_avis = Column(String(20), nullable=True)         # licenciement / sanction / relaxe
    conseil_sanction_proposee = Column(String(50), nullable=True)
    conseil_resume = Column(Text, nullable=True)
    pv_path = Column(String(255), nullable=True)

    # --- 3. Dossier RH ---
    preavis_jours = Column(Integer, nullable=True)
    preavis_dispense = Column(Boolean, default=False, nullable=False)
    avis_rh = Column(String(20), nullable=True)              # favorable / defavorable
    commentaire_rh = Column(Text, nullable=True)

    # --- 4. Décision du Comité de direction ---
    decision = Column(String(20), nullable=True)             # approuve / rejete / complement
    decision_commentaire = Column(Text, nullable=True)

    # --- 5. Notification et sortie ---
    date_notification = Column(Date, nullable=True)
    mode_notification = Column(String(50), nullable=True)
    date_sortie = Column(Date, nullable=True)
    jours_conges_restants = Column(Numeric(5, 1), nullable=True)   # figé au moment de la notification
    lettre_signee_path = Column(String(255), nullable=True)
    motif_annulation = Column(Text, nullable=True)
    depart_id = Column(Integer, ForeignKey("departs.id"), nullable=True)
    sanction_id = Column(Integer, ForeignKey("sanctions.id"), nullable=True)

    # --- Traçabilité des étapes (qui / quand) ---
    ouvert_par = Column(String(150), nullable=True)
    ouvert_le = Column(DateTime, nullable=True)
    transmis_par = Column(String(150), nullable=True)
    transmis_le = Column(DateTime, nullable=True)
    decide_par = Column(String(150), nullable=True)
    decide_le = Column(DateTime, nullable=True)
    notifie_par = Column(String(150), nullable=True)

    employe = relationship("Employe")
