# Mise en production de PASL-RH sur le serveur de la PASL

> Principe : l'application est installée **une seule fois, sur le serveur**. Les employés n'installent
> **rien** : ils ouvrent simplement leur navigateur (Chrome, Edge, Firefox) à l'adresse
> `http://NOM-DU-SERVEUR:8000`. Il n'y a donc qu'une seule base de données, partagée par tous.

Durée estimée : 1 h 30 à 2 h, avec l'aide du service informatique (droits administrateur sur le serveur).

---

## 1. Préparer le serveur (une fois)

1. **Python** : installer la même version que sur le poste de développement
   (python.org → « Download for Windows »). Cocher **« Add python.exe to PATH »**.
2. **XAMPP** (pour MySQL/MariaDB) : l'installer, puis ouvrir le *XAMPP Control Panel* **en tant
   qu'administrateur** et cocher la case **« Service »** à gauche de **MySQL**. MySQL démarrera alors
   tout seul avec le serveur, même quand personne n'est connecté.
   - Arrêter MySQL **toujours** avec le bouton *Stop* (jamais en coupant brutalement) : c'est ce qui
     avait abîmé la base en développement.
   - **Ne pas** ouvrir le port 3306 dans le pare-feu : seule l'application doit parler à la base.
3. Choisir le dossier de l'application, par exemple **`C:\PASL-RH`**.

## 2. Installer l'application

Dans PowerShell :

```powershell
cd C:\
git clone https://github.com/ToukemMaguy/systeme_rh_pasl.git PASL-RH   # dépôt privé : connexion GitHub demandée
cd C:\PASL-RH
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

(Sans Git sur le serveur : copier le dossier du projet **sans** `venv`, `.env`, `logs`, `sauvegardes`,
puis faire les commandes à partir de `python -m venv venv`.)

## 3. Créer la base et son compte dédié

Dans phpMyAdmin (`http://localhost/phpmyadmin` sur le serveur) → onglet **SQL** :

```sql
CREATE DATABASE systeme_rh CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'pasl_rh'@'localhost' IDENTIFIED BY 'UN-MOT-DE-PASSE-SOLIDE';
GRANT ALL PRIVILEGES ON systeme_rh.* TO 'pasl_rh'@'localhost';
FLUSH PRIVILEGES;
```

## 4. Configurer le fichier `.env` du serveur

```powershell
copy .env.example .env
notepad .env
```

| Ligne | Valeur en production |
|---|---|
| `DATABASE_URL` | `mysql+pymysql://pasl_rh:UN-MOT-DE-PASSE-SOLIDE@localhost:3306/systeme_rh` (un `@` dans le mot de passe s'écrit `%40`) |
| `SECRET_KEY` | une **nouvelle** clé : `python -c "import secrets; print(secrets.token_hex(32))"` |
| `APP_URL` | `http://NOM-DU-SERVEUR:8000` (le nom est donné par la commande `hostname`) |
| `SMTP_…` | le **vrai** serveur de mail de la PASL (pas Mailtrap), fourni par l'informatique |
| `MYSQLDUMP` | `C:\xampp\mysql\bin\mysqldump.exe` |
| `SAUVEGARDE_DOSSIER` | de préférence un **autre disque** ou un partage réseau, ex. `D:\Sauvegardes\PASL-RH` |

Puis mettre la base au niveau de l'application :

```powershell
venv\Scripts\python.exe -m alembic upgrade head
```

### Charger le personnel depuis le fichier Excel de la RH

On ne recopie **pas** la base de développement : on charge le fichier de la RH (même présentation que
`fixhiier_r.xlsx`). Copier ce fichier dans `C:\PASL-RH\data\`, puis :

```powershell
# 1. Simulation : rien n'est enregistré, un rapport détaillé est écrit dans data\rapport_import_....xlsx
venv\Scripts\python.exe -m app.scripts.import_fichier_rh data\fixhiier_r.xlsx

# 2. Lire le rapport (feuille « À vérifier »), puis charger pour de bon :
venv\Scripts\python.exe -m app.scripts.import_fichier_rh data\fixhiier_r.xlsx --appliquer
```

`--repartir-de-zero --appliquer` efface d'abord toutes les données du personnel (à n'utiliser qu'**avant**
l'ouverture aux utilisateurs, par exemple pour recharger un fichier corrigé ; il demande de taper OUI).

Ensuite, la RH met l'application à jour **elle-même** depuis le menu **« Mise à jour depuis le fichier RH »**
(dépôt du fichier, vérification, puis application).

## 5. Vérifier avant d'ouvrir

```powershell
venv\Scripts\python.exe -m app.scripts.sauvegarder          # 1re sauvegarde (test)
venv\Scripts\python.exe -m app.scripts.verifier_production  # liste OK / ATTENTION / ERREUR
```

Corriger toutes les lignes **[ERREUR]** avant de continuer.

## 6. Démarrage automatique, mails, sauvegardes, pare-feu

PowerShell **en tant qu'administrateur** :

```powershell
cd C:\PASL-RH
powershell -ExecutionPolicy Bypass -File deploiement\installer_taches.ps1
```

Ce script crée trois tâches planifiées (visibles dans le *Planificateur de tâches* Windows) :

| Tâche | Rôle |
|---|---|
| **PASL-RH Serveur** | démarre l'application avec Windows et la relance automatiquement si elle s'arrête |
| **PASL-RH Mails** | envoie les mails en attente toutes les 10 minutes |
| **PASL-RH Sauvegarde** | sauvegarde la base et les pièces jointes chaque soir à 20 h 30 (30 jours gardés) |

…et ouvre le port 8000 dans le pare-feu. Il affiche à la fin l'adresse à communiquer aux utilisateurs.

**Test** : depuis un **autre** poste, ouvrir `http://NOM-DU-SERVEUR:8000`. Si la page ne s'ouvre pas :
pare-feu du serveur, ou nom du serveur (essayer avec son adresse IP : commande `ipconfig`).

## 7. Créer les comptes des employés

1. Se connecter avec un compte **Administrateur** → *Comptes utilisateurs*.
2. Bouton **« Créer les comptes manquants »** : un compte est créé pour chaque employé actif.
   Identifiant : email professionnel, sinon email personnel, sinon matricule. **Chacun peut aussi se
   connecter avec son matricule.**
3. Un fichier Excel est téléchargé avec les **mots de passe provisoires** : c'est le seul endroit où
   ils figurent. L'enregistrer dans `C:\PASL-RH\data\comptes.xlsx`.
4. Imprimer **une page par employé** (guide Employé avec ses accès déjà remplis, plus la page « Guide N+1 »
   pour les responsables qui ont des collaborateurs) :

   ```powershell
   venv\Scripts\python.exe -m app.scripts.imprimer_identifiants data\comptes.xlsx --adresse http://NOM-DU-SERVEUR:8000
   ```

   Le PDF `data\acces_personnels_....pdf` est classé par agence / direction puis par nom. L'imprimer, remettre
   chaque page en main propre, puis **supprimer le PDF et le fichier Excel** (ils contiennent les mots de passe).
5. Les comptes RH, Comité et Administrateur se créent un par un sur la même page (bon rôle à choisir).
   Leurs guides (accès à remplir à la main) : `venv\Scripts\python.exe -m app.scripts.imprimer_identifiants --vierges`
   → `data\guides_utilisateurs.pdf`.

## 8. Lancement conseillé

- **Vendredi** : RH + N+1 (une vingtaine de personnes) → corriger les premiers retours.
- **Semaine suivante** : tous les employés.
- Prévoir une courte démonstration (15 min) : se connecter, faire une demande, suivre sa validation.

---

## Au quotidien

| Besoin | Où / comment |
|---|---|
| L'application ne répond plus | Planificateur de tâches → *PASL-RH Serveur* → *Exécuter*. Puis lire `logs\app.log` et `logs\serveur.log` |
| Un utilisateur signale une erreur avec une **référence** (ex. `A1B2C3D4`) | chercher cette référence dans `logs\app.log` : la cause exacte y est |
| Les mails ne partent pas | `logs\mails.log` ; vérifier les paramètres `SMTP_` du `.env` |
| Vérifier les sauvegardes | `logs\sauvegardes.log` (une ligne « OK » par soir) |
| Mot de passe oublié | Administrateur → *Comptes utilisateurs* → *Réinitialiser* |

## Mettre à jour l'application (nouvelle version)

```powershell
cd C:\PASL-RH
Stop-ScheduledTask -TaskName "PASL-RH Serveur"
venv\Scripts\python.exe -m app.scripts.sauvegarder     # sauvegarde AVANT la mise à jour
git pull
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe -m alembic upgrade head
Start-ScheduledTask -TaskName "PASL-RH Serveur"
```

Si des pages HTML ont reçu de **nouvelles** classes de mise en forme : lancer
`outils_front\construire_css.bat` (voir les instructions en tête du fichier).

## Restaurer une sauvegarde (en cas d'incident)

```powershell
Stop-ScheduledTask -TaskName "PASL-RH Serveur"
# (PowerShell ne connaît pas « < » : on passe par cmd)
cmd /c "C:\xampp\mysql\bin\mysql.exe -u pasl_rh -p systeme_rh < D:\Sauvegardes\PASL-RH\AAAA-MM-JJ_HHMM\base_systeme_rh.sql"
# puis décompresser pieces_jointes.zip dans C:\PASL-RH\app\static\uploads\employes
Start-ScheduledTask -TaskName "PASL-RH Serveur"
```

**Tester une restauration une fois** (sur un PC de test) avant d'en avoir besoin pour de vrai.
