# PASL-RH — Système de gestion RH

Application RH de Pan-African Savings & Loans (FastAPI + Jinja2 + MySQL).

## Installation

```bash
python -m venv venv
venv\Scripts\activate            # Windows  (Linux/Mac : source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # puis remplir les valeurs
alembic upgrade head             # crée / met à jour les tables
python -m app.scripts.create_admin
uvicorn app.main:app --reload
```

## Base de données : compte MySQL dédié

L'application ne doit pas se connecter avec `root`. Créer un compte limité à la base RH :

```sql
CREATE USER 'pasl_rh'@'localhost' IDENTIFIED BY 'un-mot-de-passe-solide';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON systeme_rh.* TO 'pasl_rh'@'localhost';
FLUSH PRIVILEGES;
```

Puis renseigner ce compte dans `DATABASE_URL` du fichier `.env`.

## Envoi des mails

Les mails sont mis en file d'attente par l'application et envoyés par :

```bash
python -m app.scripts.envoyer_mails
```

(à planifier toutes les 5 minutes avec le Planificateur de tâches Windows).

## Organisation du code

```
app/
├── main.py            Démarrage : création de l'application, sécurité (session, clé secrète), assemblage des modules
├── outils.py          Outils web communs : gabarits HTML, contrôles d'accès par rôle, lecture des formulaires, fichiers envoyés
├── regles_rh.py       Règles métier partagées : calcul des soldes de congés, statuts des demandes, âge, ancienneté
├── calendrier.py      Jours ouvrables et jours fériés du Cameroun
├── securite.py        Protection CSRF, règles de mot de passe, blocage après échecs
├── journal.py         Journal d'audit automatique (qui a fait quoi, quand, avant → après)
├── notifications.py   Mails à chaque étape du circuit de validation
├── models.py          Tables de la base de données
├── pdf.py             Documents PDF (fiche employé, attestation, certificat)
└── routes/            Une page = un fichier, par domaine fonctionnel
    ├── auth.py            Connexion / déconnexion
    ├── tableau_de_bord.py Tableau de bord et exports Excel / CSV
    ├── employes.py        Employés, fiche, sanctions, PDF
    ├── demandes.py        Demandes RH et circuit de validation (N+1 puis RH)
    ├── espace.py          Espace personnel de l'employé
    ├── absences.py        Suivi des absences
    ├── conges.py          Congés et soldes
    ├── compte.py          Changement de mot de passe
    ├── licenciements.py   Procédure de licenciement (conseil de discipline → Comité de direction)
    └── admin.py           Comptes utilisateurs et référentiels
```

## Calendrier des congés (`app/calendrier.py`)

Chaque employé acquiert **2 jours de congé par mois** de service (24 jours par an), constante
`QUOTA_CONGES_PAR_MOIS` dans `app/regles_rh.py`. La semaine de travail PASL compte **6 jours
(lundi au samedi)** : les congés sont décomptés en **jours ouvrables** (dimanches et jours fériés exclus).
Chaque année, la RH doit ajouter les dates des fêtes musulmanes (Aïd el-Fitr, Tabaski) dans
`FETES_A_DATE_VARIABLE` dès leur annonce officielle.

## Tests

```bash
pip install -r requirements-dev.txt   # une seule fois : ajoute httpx2, nécessaire aux tests
python tests/test_correctifs.py
```
(utilise une base SQLite temporaire : la base MySQL n'est pas touchée)
