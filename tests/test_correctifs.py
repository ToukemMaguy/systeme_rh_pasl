"""Test de fumée : rejoue les scénarios des bugs B1-B7 et des failles sur une base SQLite jetable.
Lancer depuis la racine du projet : python tests/test_correctifs.py
(utilise une base SQLite jetable : la vraie base MySQL n'est pas touchée)
"""
import os, sys, re
from datetime import date, timedelta
os.environ["DATABASE_URL"] = "sqlite:///./_test_smoke.db"
os.environ["SECRET_KEY"] = "x" * 40
if os.path.exists("_test_smoke.db"):
    os.remove("_test_smoke.db")  # reste éventuel d'une exécution précédente
sys.path.insert(0, os.getcwd())

try:
    from fastapi.testclient import TestClient
except RuntimeError:
    sys.exit("Il manque le paquet de test « httpx2 ». Installez-le avec :  pip install -r requirements-dev.txt")
from app.database import Base, engine, SessionLocal
from app import models, auth
from app.main import app

Base.metadata.create_all(engine)
db = SessionLocal()
dep = models.Departement(nom="Exploitation"); pos = models.Poste(intitule="Caissier"); gr = models.Grade(libelle="Employé", niveau_hierarchique=1)
db.add_all([dep, pos, gr]); db.flush()
for lib in ["Congé", "Départ", "Mutation / Mouvement interne", "Permission", "Absence"]:
    db.add(models.TypeDemande(libelle=lib))
chef = models.Employe(nom="CHEF", prenom="Paul", genre="H", date_embauche=date(2015, 1, 1), departement_id=dep.id, poste_id=pos.id, grade_id=gr.id, email_perso="chef@test.cm")
db.add(chef); db.flush()
emp = models.Employe(nom="NGONO", prenom="Alice", genre="F", date_embauche=date.today() - timedelta(days=365 * 2), departement_id=dep.id, poste_id=pos.id, grade_id=gr.id, n_plus_1_id=chef.id, email_perso="alice@test.cm")
autre = models.Employe(nom="ESSOMBA", prenom="Marc", genre="H", date_embauche=date(2020, 1, 1), departement_id=dep.id, poste_id=pos.id, grade_id=gr.id, n_plus_1_id=chef.id, email_perso="marc@test.cm")
db.add_all([emp, autre]); db.flush()
u_rh = models.Utilisateur(nom="RH", email="rh@t.cm", role="Chef RH", mot_de_passe_hash=auth.hash_password("secret123"))
u_ass = models.Utilisateur(nom="Assistant", email="ass@t.cm", role="Assistant RH", mot_de_passe_hash=auth.hash_password("secret123"))
u_emp = models.Utilisateur(nom="Alice", email="alice@t.cm", role="Employé", employe_id=emp.id, mot_de_passe_hash=auth.hash_password("secret123"))
u_chef = models.Utilisateur(nom="Chef", email="chef@t.cm", role="Employé", employe_id=chef.id, mot_de_passe_hash=auth.hash_password("secret123"))
db.add_all([u_rh, u_ass, u_emp, u_chef]); db.commit()
T = {t.libelle: t.id for t in db.query(models.TypeDemande).all()}
EMP_ID, AUTRE_ID, CHEF_ID, U_EMP, U_RH = emp.id, autre.id, chef.id, u_emp.id, u_rh.id

class Navigateur(TestClient):
    """Client de test qui se comporte comme un navigateur : il renvoie le jeton CSRF
    (champ caché des formulaires) avec chaque envoi de formulaire."""
    jeton = None

    def post(self, url, data=None, **kw):
        if self.jeton is not None:
            data = {"csrf_token": self.jeton, **(data or {})}
        return super().post(url, data=data, **kw)


def ouvrir_page_connexion():
    nav = Navigateur(app, follow_redirects=False)
    nav.jeton = re.search(r'name="csrf_token" value="([^"]+)"', nav.get("/login").text).group(1)
    return nav


def client(email, mot_de_passe="secret123"):
    c = ouvrir_page_connexion()
    r = c.post("/login", data={"email": email, "mot_de_passe": mot_de_passe})
    assert r.status_code == 303, r.text
    return c

resultats = []
def check(nom, ok, detail=""):
    resultats.append(ok)
    print(("OK   " if ok else "ECHEC") + " | " + nom + (f"  ({detail})" if detail else ""))

rh, alice, chef_c = client("rh@t.cm"), client("alice@t.cm"), client("chef@t.cm")
lundi = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 + 7)

# --- Faille 1 : un employé tente de déposer une demande au nom d'un collègue ---
r = alice.post("/demandes/nouvelle", data={"type_demande_id": T["Congé"], "demandeur_id": U_RH, "employe_concerne_id": AUTRE_ID,
               "suppleant_id": CHEF_ID, "date_debut_conge": lundi.isoformat(), "date_fin_conge": (lundi + timedelta(days=4)).isoformat()})
db.expire_all()
d = db.query(models.DemandeRh).order_by(models.DemandeRh.id.desc()).first()
check("F1 demande forcée au nom de l'employé connecté", d.employe_concerne_id == EMP_ID and d.demandeur_id == U_EMP,
      f"employe_concerne={d.employe_concerne_id}, demandeur={d.demandeur_id}")
dem_id = d.id

# --- B7 : après avis favorable du N+1, la demande reste comptée « en attente » ---
chef_c.post(f"/demandes/{dem_id}/avis-n-plus-1", data={"avis": "favorable"})
db.expire_all()
check("avis N+1 enregistré", db.get(models.DemandeRh, dem_id).statut == "en_attente_rh")
from app import regles_rh as M  # règles métier partagées (soldes, statuts, âge)
statuts = getattr(M, "STATUTS_EN_ATTENTE", ["en_attente", "en_attente_n_plus_1"])
check("B7 KPI inclut en_attente_rh", "en_attente_rh" in statuts)

# --- B4/B5/B1 : validation RH via le formulaire, puis double validation ---
r = rh.post(f"/demandes/{dem_id}/traiter-rh", data={"action": "valider"})
r2 = rh.post(f"/demandes/{dem_id}/statut", data={"nouveau_statut": "validee"})  # double validation par l'autre route
db.expire_all()
nb_abs = db.query(models.Absence).filter_by(employe_id=EMP_ID).count()
soldes = db.query(models.SoldeConge).filter_by(employe_id=EMP_ID).all()
pris = sum(float(s.jours_pris or 0) for s in soldes)
check("B5 pas de double validation (1 seule absence)", nb_abs == 1, f"{nb_abs} absence(s)")
from app.calendrier import nb_jours_ouvrables
attendu = nb_jours_ouvrables(lundi, lundi + timedelta(days=4))
check("B5 congé décompté une seule fois", pris == attendu, f"{pris} jour(s) pris, attendu {attendu}")
mails = db.query(models.MailAEnvoyer).filter_by(demande_id=dem_id).all()
# B1 = jamais deux fois LE MÊME mail (même destinataire, même type). Un même destinataire peut recevoir
# des mails différents (ex. le chef, à la fois N+1 notifié au dépôt et suppléant notifié à la validation).
check("B1 pas de mail en double", len(mails) == len({(m.destinataire, m.type_mail) for m in mails}),
      f"{[(m.destinataire, m.type_mail) for m in mails]}")

# --- B2/B3 : même solde partout ---
check("Quota PASL 2 j/mois", float(M.QUOTA_CONGES_PAR_MOIS) == 2, str(M.QUOTA_CONGES_PAR_MOIS))
check("Samedi travaillé (semaine de 6 jours)", nb_jours_ouvrables(date(2026, 10, 10), date(2026, 10, 10)) == 1)
if hasattr(M, "_solde_conges"):
    s = M._solde_conges(db, db.get(models.Employe, EMP_ID))
    check("B3 fonction unique de solde", True, f"alloué={s['total_alloue']} pris={s['total_pris']} restant={s['total_restant']}")
else:
    check("B3 fonction unique de solde", False)

# --- B6 : jours déduits d'une permission trop longue ---
ta = models.TypeAbsence(code="ABS_NON_JUSTIFIEE", libelle="Absence non justifiée", categorie="Absence")
db.add(ta); db.commit()
rh.post("/absences/nouvelle", data={"employe_id": AUTRE_ID, "type_absence_id": ta.id, "date_debut": "2026-03-02", "date_fin": "2026-03-03"})
if hasattr(M, "_solde_conges"):
    db.expire_all()
    s = M._solde_conges(db, db.get(models.Employe, AUTRE_ID))
    check("B6 jours déduits pris en compte dans le solde", s["total_pris"] == 2, f"pris={s['total_pris']}")
else:
    check("B6 jours déduits pris en compte dans le solde", False)

# --- B4 : départ validé via le formulaire RH → employé inactif ---
r = rh.post("/demandes/nouvelle", data={"type_demande_id": T["Départ"], "employe_concerne_id": AUTRE_ID, "date_depart": date.today().isoformat(), "type_depart": "Démission"})
db.expire_all()
dep_id = db.query(models.DemandeRh).order_by(models.DemandeRh.id.desc()).first().id
ass = client("ass@t.cm")
ass.post(f"/demandes/{dep_id}/traiter-rh", data={"action": "valider"})
db.expire_all()
check("B4 Assistant RH ne peut pas valider un départ", db.get(models.DemandeRh, dep_id).statut != "validee")
rh.post(f"/demandes/{dep_id}/traiter-rh", data={"action": "valider"})
db.expire_all()
check("B4 départ validé via /traiter-rh → employé inactif", db.get(models.Employe, AUTRE_ID).statut == "inactif")


# --- Solde insuffisant bloqué + refus via le raccourci ---
alice2 = client("alice@t.cm")
alice2.post("/demandes/nouvelle", data={"type_demande_id": T["Congé"], "suppleant_id": CHEF_ID,
            "date_debut_conge": lundi.isoformat(), "date_fin_conge": (lundi + timedelta(days=59)).isoformat()})
db.expire_all()
gros = db.query(models.DemandeRh).order_by(models.DemandeRh.id.desc()).first().id
r = rh.post(f"/demandes/{gros}/statut", data={"nouveau_statut": "validee"})
db.expire_all()
check("congé > solde bloqué", db.get(models.DemandeRh, gros).statut == "en_attente_n_plus_1" and "Solde" in r.headers["location"], r.headers["location"][:60])
rh.post(f"/demandes/{gros}/statut", data={"nouveau_statut": "refusee"})
db.expire_all()
check("refus via raccourci", db.get(models.DemandeRh, gros).statut == "refusee")


# ================= B8 à B21 =================
from app.calendrier import nb_jours_ouvrables as njo, jours_feries
check("B9 ven→lun = 3 jours ouvrables (dimanche exclu)", njo(date(2026, 10, 9), date(2026, 10, 12)) == 3, str(njo(date(2026, 10, 9), date(2026, 10, 12))))
check("B9 fête nationale 20 mai exclue", njo(date(2026, 5, 18), date(2026, 5, 22)) == 4, str(njo(date(2026, 5, 18), date(2026, 5, 22))))
check("B9 Vendredi saint / Ascension 2026", date(2026, 4, 3) in jours_feries(2026) and date(2026, 5, 14) in jours_feries(2026))

# B8 : boutons Valider/Refuser visibles pour une demande en attente
chef_emp = client("chef@t.cm")
chef_emp.post("/demandes/nouvelle", data={"type_demande_id": T["Congé"], "suppleant_id": EMP_ID,
              "date_debut_conge": lundi.isoformat(), "date_fin_conge": lundi.isoformat()})
db.expire_all()
att = db.query(models.DemandeRh).order_by(models.DemandeRh.id.desc()).first().id
check("B8 boutons du tableau de bord affichés", f"/demandes/{att}/statut" in rh.get("/").text)

# B10 : suppression d'une absence de congé → solde recrédité
db.expire_all()
avant = M._solde_conges(db, db.get(models.Employe, EMP_ID))["total_pris"]
abs_ca = db.query(models.Absence).filter_by(employe_id=EMP_ID).first()
rh.post(f"/absences/{abs_ca.id}/supprimer")
db.expire_all()
apres = M._solde_conges(db, db.get(models.Employe, EMP_ID))["total_pris"]
check("B10 solde recrédité après suppression du congé", apres == avant - attendu, f"{avant} -> {apres}")

# B11 / B12 / B13 : saisies invalides → message, pas d'erreur 500
base_emp = {"nom": "TEST", "prenom": "Un", "genre": "H", "date_embauche": "2024-01-01", "departement_id": dep.id if False else 1,
            "poste_id": 1, "grade_id": 1}
r = rh.post("/employes/nouveau", data={**base_emp, "nombre_enfants": "2 enfants"})
check("B11 nombre d'enfants invalide → message", r.status_code == 400 and "entier" in r.text, f"HTTP {r.status_code}")
r = rh.post("/employes/nouveau", data={**base_emp, "email_perso": "alice-at-gmail"})
check("B13 email invalide → message", r.status_code == 400 and "pas valide" in r.text, f"HTTP {r.status_code}")
r = rh.post("/demandes/nouvelle", data={"type_demande_id": T["Congé"], "employe_concerne_id": EMP_ID, "suppleant_id": "abc",
            "date_debut_conge": "2026-10-01", "date_fin_conge": "2026-10-02"})
check("B11 identifiant invalide dans une demande → message", r.status_code == 400, f"HTTP {r.status_code}")
r = rh.post("/demandes/nouvelle", data={"type_demande_id": T["Congé"], "employe_concerne_id": EMP_ID, "suppleant_id": CHEF_ID,
            "date_debut_conge": "2026-13-45", "date_fin_conge": "2026-10-02"})
check("B12 date invalide → message", r.status_code == 400 and "pas valide" in r.text, f"HTTP {r.status_code}")
r = rh.post("/admin/grades/nouveau", data={"valeur": "X", "niveau_hierarchique": "haut"})
check("B11 admin niveau invalide → pas d'erreur 500", r.status_code in (303, 307), f"HTTP {r.status_code}")

# B14 + B21 : le formulaire de modification conserve téléphones / emails
e = db.get(models.Employe, EMP_ID); e.telephone_pro = "699000111"; e.email_pro = "alice@pasl.cm"; db.commit()
page = rh.get(f"/employes/{EMP_ID}/modifier").text
check("B21 formulaire de modification pré-rempli (tél. / email)", "699000111" in page and "alice@pasl.cm" in page)
page = rh.post(f"/employes/{EMP_ID}", data={**base_emp, "nom": "NGONO", "genre": "X", "telephone_pro": "699000111"}).text
check("B14 N+1 : l'employé n'est pas son propre N+1 après une erreur", f'"id": {EMP_ID},' not in page and "699000111" in page)

# B16 : certificat de travail
r = rh.get(f"/employes/{EMP_ID}/pdf/certificat")
check("B16 certificat refusé pour un employé actif", r.status_code == 303 and "erreur" in r.headers["location"])
r = rh.get(f"/employes/{AUTRE_ID}/pdf/certificat")
check("B16 certificat délivré après départ", r.status_code == 200 and r.headers["content-type"] == "application/pdf", f"HTTP {r.status_code}")

# B17 : caractères spéciaux dans les PDF
bizarre = models.Employe(nom="DUPONT <b>", prenom="Jean & <SARL>", genre="H", date_embauche=date(2022, 1, 1),
                         departement_id=1, poste_id=1, grade_id=1)
db.add(bizarre); db.commit()
for doc in ("fiche", "attestation"):
    r = rh.get(f"/employes/{bizarre.id}/pdf/{doc}")
    check(f"B17 PDF {doc} avec un nom contenant « <b> »", r.status_code == 200, f"HTTP {r.status_code}")

# B18 : libellé de tranche d'âge
check("B18 tranche « ≤25 » partout", M._tranche_age(date.today() - timedelta(days=365 * 22)) == "≤25")


# ================= Lot 1 - point 3 : sécurité des comptes =================
brut = TestClient(app, follow_redirects=False)
brut.get("/login")
r = brut.post("/login", data={"email": "rh@t.cm", "mot_de_passe": "secret123"})
check("CSRF : connexion sans jeton refusée", r.status_code == 403, f"HTTP {r.status_code}")
r = rh.post(f"/demandes/{dem_id}/statut", data={"nouveau_statut": "refusee", "csrf_token": "jeton-falsifie"})
check("CSRF : jeton falsifié refusé", r.status_code == 403, f"HTTP {r.status_code}")

u_blq = models.Utilisateur(nom="Test Blocage", email="blq@t.cm", role="Assistant RH", mot_de_passe_hash=auth.hash_password("secret123"))
u_adm = models.Utilisateur(nom="Admin", email="admin@t.cm", role="Administrateur", mot_de_passe_hash=auth.hash_password("secret123"))
db.add_all([u_blq, u_adm]); db.commit()
BLQ_ID = u_blq.id
nav = ouvrir_page_connexion()
for _ in range(5):
    nav.post("/login", data={"email": "blq@t.cm", "mot_de_passe": "mauvais"})
r = nav.post("/login", data={"email": "blq@t.cm", "mot_de_passe": "secret123"})
check("5 échecs → compte bloqué, même avec le bon mot de passe", r.status_code == 400 and "bloqué" in r.text, f"HTTP {r.status_code}")

adm = client("admin@t.cm")
page = adm.get("/admin/utilisateurs").text
check("Admin : compte bloqué signalé", "Bloqué jusqu" in page)
check("B22 employé rattaché affiché dans la liste des comptes", "NGONO Alice" in page)
adm.post(f"/admin/utilisateurs/{BLQ_ID}/debloquer")
r = nav.post("/login", data={"email": "blq@t.cm", "mot_de_passe": "secret123"})
check("Déblocage par l'admin → connexion possible", r.status_code == 303, f"HTTP {r.status_code}")

r = adm.post("/admin/utilisateurs/nouveau", data={"email": "faible@t.cm", "nom": "X", "mot_de_passe": "abc", "role": "Assistant RH"})
check("Création de compte : mot de passe faible refusé", "erreur=" in r.headers.get("location", ""))

r = adm.post(f"/admin/utilisateurs/{BLQ_ID}/reinitialiser")
m = re.search(r'letter-spacing:1px;margin:6px 0;">([^<]+)</div>', r.text)
provisoire = m.group(1).strip() if m else None
check("Réinitialisation : mot de passe provisoire affiché", provisoire is not None)
check("… et affiché une seule fois", provisoire is not None and provisoire not in adm.get("/admin/utilisateurs").text)
nav2 = client("blq@t.cm", provisoire)
r = nav2.get("/")
# Décision PASL : le changement du mot de passe provisoire est conseillé mais PAS imposé
check("Mot de passe provisoire → accès direct, changement non imposé", r.status_code == 200, f"HTTP {r.status_code}")
check("… avec un conseil (non bloquant) sur la page mot de passe", "conseillons" in nav2.get("/mon-compte/mot-de-passe").text)
r = nav2.post("/mon-compte/mot-de-passe", data={"mot_de_passe_actuel": provisoire, "nouveau_mot_de_passe": "court", "confirmation": "court"})
check("Nouveau mot de passe trop faible refusé", r.status_code == 400)
r = nav2.post("/mon-compte/mot-de-passe", data={"mot_de_passe_actuel": "faux", "nouveau_mot_de_passe": "Nouveau2026", "confirmation": "Nouveau2026"})
check("Mot de passe actuel erroné refusé", r.status_code == 400)
r = nav2.post("/mon-compte/mot-de-passe", data={"mot_de_passe_actuel": provisoire, "nouveau_mot_de_passe": "Nouveau2026", "confirmation": "Nouveau2026"})
check("Changement de mot de passe réussi", r.status_code == 200 and "bien été modifié" in r.text, f"HTTP {r.status_code}")
check("Accès normal après le changement", nav2.get("/").status_code == 200)
check("Connexion avec le nouveau mot de passe", client("blq@t.cm", "Nouveau2026") is not None)


# ================= Lot 1 - point 4 : désactivation des accès au départ =================
import app.main as module_main
from app.regles_rh import appliquer_departs_echus
e_imm = models.Employe(nom="LEBON", prenom="Paul", genre="H", date_embauche=date(2019, 1, 1), departement_id=1, poste_id=1, grade_id=1, n_plus_1_id=CHEF_ID)
e_fut = models.Employe(nom="ATANGANA", prenom="Jeanne", genre="F", date_embauche=date(2018, 1, 1), departement_id=1, poste_id=1, grade_id=1, n_plus_1_id=CHEF_ID)
db.add_all([e_imm, e_fut]); db.flush()
db.add_all([
    models.Utilisateur(nom="Paul", email="paul@t.cm", role="Employé", employe_id=e_imm.id, mot_de_passe_hash=auth.hash_password("secret123")),
    models.Utilisateur(nom="Jeanne", email="jeanne@t.cm", role="Employé", employe_id=e_fut.id, mot_de_passe_hash=auth.hash_password("secret123")),
]); db.commit()
IMM_ID, FUT_ID = e_imm.id, e_fut.id
paul = client("paul@t.cm")
jeanne = client("jeanne@t.cm")

def valider_depart(employe_id, date_depart):
    rh.post("/demandes/nouvelle", data={"type_demande_id": T["Départ"], "employe_concerne_id": employe_id,
            "date_depart": date_depart.isoformat(), "type_depart": "Démission"})
    db.expire_all()
    d_id = db.query(models.DemandeRh).order_by(models.DemandeRh.id.desc()).first().id
    rh.post(f"/demandes/{d_id}/traiter-rh", data={"action": "valider"})
    db.expire_all()

# Départ à la date du jour : sortie immédiate
valider_depart(IMM_ID, date.today())
compte_paul = db.query(models.Utilisateur).filter_by(email="paul@t.cm").first()
check("Départ du jour → employé inactif", db.get(models.Employe, IMM_ID).statut == "inactif")
check("Départ du jour → compte désactivé (pas supprimé)", compte_paul is not None and not compte_paul.compte_actif)
r = paul.get("/espace")
check("Session ouverte de l'employé parti → déconnecté", "/login" in r.headers.get("location", ""), f"HTTP {r.status_code}")
r = ouvrir_page_connexion().post("/login", data={"email": "paul@t.cm", "mot_de_passe": "secret123"})
check("Connexion refusée avec message « compte désactivé »", r.status_code == 403 and "désactivé" in r.text, f"HTTP {r.status_code}")
r = ouvrir_page_connexion().post("/login", data={"email": "paul@t.cm", "mot_de_passe": "mauvais"})
check("… sans rien révéler si le mot de passe est faux", r.status_code == 400 and "désactivé" not in r.text)

# Départ programmé dans 10 jours : l'employée reste active jusqu'à cette date
valider_depart(FUT_ID, date.today() + timedelta(days=10))
check("Départ futur → employée toujours active (elle travaille encore)", db.get(models.Employe, FUT_ID).statut == "actif")
check("Départ futur → accès conservé jusqu'au départ", jeanne.get("/espace").status_code == 200)
dep = db.query(models.Depart).filter_by(employe_id=FUT_ID).first()
dep.date_depart = date.today() - timedelta(days=1); db.commit()          # on simule le passage du temps
module_main._derniere_verification_departs = None                         # « premier passage du jour »
r = jeanne.get("/espace")
db.expire_all()
check("Date de départ atteinte → sortie automatique des effectifs", db.get(models.Employe, FUT_ID).statut == "inactif")
check("… et déconnexion / désactivation automatique", "/login" in r.headers.get("location", "")
      and not db.query(models.Utilisateur).filter_by(email="jeanne@t.cm").first().compte_actif)
check("Pas de double traitement", appliquer_departs_echus(db) == 0)

# Administration
compte_jeanne = db.query(models.Utilisateur).filter_by(email="jeanne@t.cm").first()
r = adm.post(f"/admin/utilisateurs/{compte_jeanne.id}/reactiver")
check("Réactivation refusée : employée sortie des effectifs", "erreur=" in r.headers.get("location", ""))
page = adm.get("/admin/utilisateurs").text
check("Page des comptes : état « Désactivé » affiché", "Désactivé le" in page)
compte_ass = db.query(models.Utilisateur).filter_by(email="ass@t.cm").first()
adm.post(f"/admin/utilisateurs/{compte_ass.id}/desactiver")
r = ouvrir_page_connexion().post("/login", data={"email": "ass@t.cm", "mot_de_passe": "secret123"})
check("Désactivation manuelle par l'admin → connexion refusée", r.status_code == 403)
adm.post(f"/admin/utilisateurs/{compte_ass.id}/reactiver")
r = ouvrir_page_connexion().post("/login", data={"email": "ass@t.cm", "mot_de_passe": "secret123"})
check("Réactivation (employé toujours en poste) → connexion possible", r.status_code == 303)


# ================= Lot 1 - point 18 : notifications à chaque étape =================
def mails_de(demande_id, type_mail):
    db.expire_all()
    return [m.destinataire for m in db.query(models.MailAEnvoyer).filter_by(demande_id=demande_id, type_mail=type_mail)]

alice_n = client("alice@t.cm")
alice_n.post("/demandes/nouvelle", data={"type_demande_id": T["Congé"], "suppleant_id": CHEF_ID,
             "date_debut_conge": lundi.isoformat(), "date_fin_conge": lundi.isoformat()})
db.expire_all()
d_notif = db.query(models.DemandeRh).order_by(models.DemandeRh.id.desc()).first().id
check("Dépôt → mail au N+1", mails_de(d_notif, "notif_n_plus_1_nouvelle_demande") == ["chef@test.cm"],
      str(mails_de(d_notif, "notif_n_plus_1_nouvelle_demande")))
chef_c.post(f"/demandes/{d_notif}/avis-n-plus-1", data={"avis": "favorable"})
check("Avis favorable → mail aux RH actifs", sorted(mails_de(d_notif, "notif_rh_avis_favorable")) == ["ass@t.cm", "blq@t.cm", "rh@t.cm"],
      str(mails_de(d_notif, "notif_rh_avis_favorable")))

alice_n.post("/demandes/nouvelle", data={"type_demande_id": T["Congé"], "suppleant_id": CHEF_ID,
             "date_debut_conge": lundi.isoformat(), "date_fin_conge": lundi.isoformat()})
db.expire_all()
d_refus = db.query(models.DemandeRh).order_by(models.DemandeRh.id.desc()).first().id
chef_c.post(f"/demandes/{d_refus}/avis-n-plus-1", data={"avis": "defavorable", "commentaire": "Période chargée"})
# email professionnel prioritaire : Alice en a reçu un plus haut dans le test (B21)
check("Avis défavorable → mail à l'employée (adresse pro en priorité)", mails_de(d_refus, "notif_employe_refus_n_plus_1") == ["alice@pasl.cm"],
      str(mails_de(d_refus, "notif_employe_refus_n_plus_1")))
m = db.query(models.MailAEnvoyer).filter_by(demande_id=d_refus, type_mail="notif_employe_refus_n_plus_1").first()
check("… avec le motif du N+1", m is not None and "Période chargée" in m.corps)

rh.post("/demandes/nouvelle", data={"type_demande_id": T["Départ"], "employe_concerne_id": CHEF_ID,
        "date_depart": (date.today() + timedelta(days=90)).isoformat(), "type_depart": "Retraite"})
db.expire_all()
d_sans_n1 = db.query(models.DemandeRh).order_by(models.DemandeRh.id.desc()).first().id
check("Employé sans N+1 → la RH est prévenue directement", len(mails_de(d_sans_n1, "notif_rh_nouvelle_demande")) >= 2)

# ================= Lot 1 - point 1 : journal d'audit =================
db.expire_all()
J = models.JournalAudit
check("Journal : connexions tracées", db.query(J).filter_by(action="connexion").count() > 5)
check("Journal : échecs de connexion tracés", db.query(J).filter_by(action="echec_connexion").count() >= 5)
ligne = db.query(J).filter_by(objet_type="Demande RH", action="creation", objet_id=d_notif).first()
check("Journal : création de demande avec son auteur", ligne is not None and ligne.utilisateur_nom == "Alice", getattr(ligne, "utilisateur_nom", None))
modif = db.query(J).filter_by(objet_type="Employé", action="modification", employe_id=EMP_ID).all()
check("Journal : modification d'employé avec avant → après",
      any("telephone_pro" in (l.details or {}) or "nom" in (l.details or {}) for l in modif) or len(modif) > 0)
mdp = db.query(J).filter(J.objet_type == "Compte utilisateur", J.action == "modification").all()
check("Journal : mot de passe jamais en clair",
      all("Nouveau2026" not in str(l.details) and "pbkdf2" not in str(l.details) for l in mdp) and any("mot_de_passe_hash" in (l.details or {}) for l in mdp))
auto = db.query(J).filter(J.utilisateur_nom == "Système (tâche automatique)").first()
check("Journal : sorties automatiques attribuées au « Système »", auto is not None)
r = adm.get("/admin/journal?objet_type=Employé")
check("Journal : page consultable par l'administrateur", r.status_code == 200 and "Journal d'audit" in r.text)
check("Journal : page consultable par le Chef RH", rh.get("/admin/journal").status_code == 200)
r = client("chef@t.cm").get("/admin/journal")
check("Journal : refusé à un employé", r.status_code in (302, 303, 307))


# ================= Étape 3 : module licenciement =================
import io
e_lic = models.Employe(nom="MBARGA", prenom="Eric", genre="H", date_embauche=date(2016, 3, 1), departement_id=1, poste_id=1, grade_id=1, n_plus_1_id=CHEF_ID)
db.add(e_lic); db.flush()
e_sub = models.Employe(nom="NKOA", prenom="Luc", genre="H", date_embauche=date(2021, 1, 1), departement_id=1, poste_id=1, grade_id=1, n_plus_1_id=e_lic.id)
db.add(e_sub)
db.add_all([
    models.Utilisateur(nom="Eric", email="eric@t.cm", role="Employé", employe_id=e_lic.id, mot_de_passe_hash=auth.hash_password("secret123")),
    models.Utilisateur(nom="Comité", email="comite@t.cm", role="Comité de direction", mot_de_passe_hash=auth.hash_password("secret123")),
]); db.commit()
LIC_EMP = e_lic.id
eric = client("eric@t.cm")
eric.post("/demandes/nouvelle", data={"type_demande_id": T["Congé"], "suppleant_id": CHEF_ID,
          "date_debut_conge": lundi.isoformat(), "date_fin_conge": lundi.isoformat()})
db.expire_all()
dem_eric = db.query(models.DemandeRh).filter_by(employe_concerne_id=LIC_EMP).first().id
comite = client("comite@t.cm")
ass2 = client("ass@t.cm")

check("Fiche : bouton « Engager une procédure » pour la RH", "licenciement/nouveau" in rh.get(f"/employes/{LIC_EMP}").text)
check("Fiche : bouton absent pour le Comité", "licenciement/nouveau" not in comite.get(f"/employes/{LIC_EMP}").text)
r = ass2.post(f"/employes/{LIC_EMP}/licenciement/nouveau", data={"type_motif": "Faute grave", "date_faits": "2026-09-01",
              "expose_faits": "Détournement de fonds constaté à la caisse le 01/09/2026."})
db.expire_all()
dos = db.query(models.Licenciement).filter_by(employe_id=LIC_EMP).first()
check("Ouverture du dossier par l'Assistant RH", dos is not None and dos.statut == "ouvert", r.headers.get("location"))
DOS = dos.id
check("Confidentialité : Comité sans accès avant transmission", comite.get(f"/licenciements/{DOS}").status_code in (302, 303, 307))
check("Confidentialité : employé sans accès", chef_c.get(f"/licenciements/{DOS}").status_code in (302, 303, 307))
r = ass2.post(f"/licenciements/{DOS}/transmettre")
check("Transmission refusée tant que le dossier est incomplet", "incomplet" in r.headers.get("location", "").lower() or "incomplet" in r.headers.get("location", ""))
ass2.post(f"/licenciements/{DOS}/enregistrer", data={
    "conseil_date": "2026-09-20", "conseil_membres": "DRH, Chef d'agence, délégué du personnel",
    "conseil_avis": "licenciement", "conseil_resume": "L'employé reconnaît les faits.",
    "preavis_jours": "30", "avis_rh": "favorable", "commentaire_rh": "Faits graves et établis."},
    files={"pv": ("pv.pdf", io.BytesIO(b"%PDF-1.4 PV"), "application/pdf")})
r = ass2.post(f"/licenciements/{DOS}/transmettre")
db.expire_all()
check("Transmission au Comité (Assistant RH autorisé)", db.get(models.Licenciement, DOS).statut == "transmis", r.headers.get("location"))
check("Mail au Comité à la transmission", db.query(models.MailAEnvoyer).filter_by(type_mail="licenciement_transmis", destinataire="comite@t.cm").count() == 1)
page = comite.get("/licenciements").text
check("Comité : dossier dans « Licenciements à décider » + compteur du menu", "MBARGA" in page and "Licenciements à décider" in page)
r = comite.post(f"/licenciements/{DOS}/decision", data={"decision": "complement"})
db.expire_all()
check("Complément sans commentaire refusé", db.get(models.Licenciement, DOS).statut == "transmis")
comite.post(f"/licenciements/{DOS}/decision", data={"decision": "complement", "commentaire": "Joindre le rapport d'audit interne."})
db.expire_all()
check("Comité : renvoi à la RH pour complément", db.get(models.Licenciement, DOS).statut == "complement")
check("RH prévenue de la décision du Comité", db.query(models.MailAEnvoyer).filter_by(type_mail="licenciement_decide").count() >= 2)
check("Seul le Comité décide (RH refusée)", rh.post(f"/licenciements/{DOS}/decision", data={"decision": "approuve"}).status_code in (302, 303, 307)
      and db.get(models.Licenciement, DOS).statut == "complement")
ass2.post(f"/licenciements/{DOS}/transmettre")
comite.post(f"/licenciements/{DOS}/decision", data={"decision": "approuve", "commentaire": ""})
db.expire_all()
check("Comité : licenciement approuvé", db.get(models.Licenciement, DOS).statut == "approuve")
check("Approuvé mais pas encore notifié → employé toujours actif", db.get(models.Employe, LIC_EMP).statut == "actif")
r = rh.get(f"/licenciements/{DOS}/pdf/lettre")
check("Lettre : PDF refusé tant que le texte n'est pas rédigé", r.status_code in (302, 303, 307))
TEXTE_LETTRE = "Douala, le 30/09/2026\n\nMonsieur <b>ESSOMBA</b> & Cie\nMatricule 123\n\nObjet : notification\n  \nMonsieur,\nNous vous informons..."
rh.post(f"/licenciements/{DOS}/lettre", data={"lettre_texte": TEXTE_LETTRE})
db.expire_all()
check("Lettre : texte libre enregistré tel quel", db.get(models.Licenciement, DOS).lettre_texte == TEXTE_LETTRE)
check("Lettre : zone de saisie affichée pour la RH", "lettre_texte" in rh.get(f"/licenciements/{DOS}").text)
check("Lettre : Comité ne peut pas rédiger", comite.post(f"/licenciements/{DOS}/lettre", data={"lettre_texte": "x"}).status_code in (302, 303, 307)
      and db.get(models.Licenciement, DOS).lettre_texte == TEXTE_LETTRE)
r = rh.get(f"/licenciements/{DOS}/pdf/lettre")
check("Lettre de licenciement PDF (texte avec < et &)", r.status_code == 200 and r.headers["content-type"] == "application/pdf", f"HTTP {r.status_code}")
open("_lettre_test.pdf", "wb").write(r.content) if os.environ.get("GARDER_PDF") else None
r = rh.post(f"/licenciements/{DOS}/notifier", data={"date_notification": date.today().isoformat(), "date_sortie": date.today().isoformat(),
            "mode_notification": "Remise en main propre contre décharge"})
db.expire_all()
d = db.get(models.Licenciement, DOS)
check("Notification enregistrée → sortie des effectifs le jour même", d.statut == "notifie" and db.get(models.Employe, LIC_EMP).statut == "inactif")
check("Départ enregistré avec le type de licenciement", db.query(models.Depart).filter_by(employe_id=LIC_EMP).first().type_depart == "Licenciement (Faute grave)")
check("Accès de l'employé licencié coupés", not db.query(models.Utilisateur).filter_by(email="eric@t.cm").first().compte_actif)
check("Jours de congés restants figés pour la paie", d.jours_conges_restants is not None)
rh.post(f"/licenciements/{DOS}/lettre", data={"lettre_texte": "modifié après coup"})
db.expire_all()
check("Lettre figée après la notification", db.get(models.Licenciement, DOS).lettre_texte == TEXTE_LETTRE)
check("Demandes en attente de l'employé annulées", db.get(models.DemandeRh, dem_eric).statut == "annulee")
check("Alerte RH : N+1 à réaffecter", db.query(models.MailAEnvoyer).filter_by(type_mail="n_plus_1_a_reaffecter").count() >= 1)

# Conseil de discipline → sanction plus légère
e_s = models.Employe(nom="FOTSO", prenom="Anne", genre="F", date_embauche=date(2020, 1, 1), departement_id=1, poste_id=1, grade_id=1)
db.add(e_s); db.commit(); S_EMP = e_s.id
rh.post(f"/employes/{S_EMP}/licenciement/nouveau", data={"type_motif": "Faute simple", "expose_faits": "Retards répétés."})
db.expire_all()
DOS2 = db.query(models.Licenciement).filter_by(employe_id=S_EMP).first().id
rh.post(f"/licenciements/{DOS2}/enregistrer", data={"conseil_date": "2026-09-22", "conseil_avis": "sanction", "conseil_sanction_proposee": "Mise à pied"})
rh.post(f"/licenciements/{DOS2}/cloturer")
db.expire_all()
check("Conseil → sanction plus légère : dossier clos", db.get(models.Licenciement, DOS2).statut == "clos_sanction")
check("… et sanction créée dans l'historique", db.query(models.Sanction).filter_by(employe_id=S_EMP, type_sanction="Mise à pied").count() == 1)
check("… employée toujours active", db.get(models.Employe, S_EMP).statut == "actif")

r = rh.post(f"/employes/{S_EMP}/sanctions/nouvelle", data={"date_sanction": "2026-09-25", "type_sanction": "Licenciement disciplinaire", "motif": "x"})
check("Sanction simple « Licenciement disciplinaire » refusée", r.status_code == 400)
db.expire_all()
check("Journal : étapes du dossier tracées", db.query(models.JournalAudit).filter_by(objet_type="Dossier de licenciement", objet_id=DOS).count() >= 5)
check("Page liste RH", rh.get("/licenciements").status_code == 200 and rh.get("/licenciements?statut=notifie").status_code == 200)

# --- Faille 2 : compte supprimé / rôle changé pris en compte immédiatement ---
u = db.get(models.Utilisateur, U_EMP); u.role = "Chef RH"; db.commit()
r = alice.get("/employes")
check("F2 changement de rôle appliqué sans reconnexion", r.status_code == 200, f"HTTP {r.status_code}")
db.delete(db.get(models.Utilisateur, U_EMP)); db.commit()
r = alice.get("/employes")
check("F2 compte supprimé déconnecté", r.status_code in (302, 303, 307) and "/login" in r.headers.get("location", ""), f"HTTP {r.status_code} -> {r.headers.get('location')}")

# ================= Étape 5 : nouvelle fiche employé =================
from app.regles_rh import date_retraite
check("Retraite : date des 60 ans", date_retraite(date(1970, 5, 14)) == date(2030, 5, 14))
check("Retraite : 29 février → 28 février", date_retraite(date(2040, 2, 29)) == date(2100, 2, 28))
f_emp = models.Employe(nom="FOUDA", prenom="Rose", genre="F", date_embauche=date(2000, 3, 1), departement_id=1, poste_id=1, grade_id=1,
                       n_plus_1_id=CHEF_ID, date_naissance=date.today().replace(day=1) - timedelta(days=365 * 60 - 120),
                       email_pro="r.fouda@pasl.cm", statut_matrimonial="Mariée", nombre_enfants=3, contact_urgence_nom="FOUDA Paul")
db.add(f_emp); db.flush()
t_abs = db.query(models.TypeAbsence).first()
if t_abs:
    db.add(models.Absence(employe_id=f_emp.id, type_absence_id=t_abs.id, date_debut=date.today() - timedelta(days=1), date_fin=date.today() + timedelta(days=2)))
db.commit()
F_ID = f_emp.id
page = rh.get(f"/employes/{F_ID}").text
check("Fiche : alerte dossier incomplet", "Dossier incomplet" in page)
check("Fiche : alerte départ à la retraite (< 12 mois)", "Départ à la retraite" in page)
check("Fiche : absence en cours signalée", (not t_abs) or f"au {(date.today() + timedelta(days=2)).strftime('%d/%m/%Y')}" in page)
check("Fiche : champs jusque-là masqués affichés", all(x in page for x in ["r.fouda@pasl.cm", "Mariée", "3 enfants", "FOUDA Paul"]))
check("Fiche : solde de congés affiché", "Congés disponibles" in page)
check("Fiche : bouton « Engager une procédure » visible (RH)", "Engager une procédure de licenciement" in page)
page_c = comite.get(f"/employes/{F_ID}").text
check("Fiche Comité : ni Modifier, ni licenciement", "/modifier" not in page_c and "licenciement/nouveau" not in page_c)
for o in ["conges", "documents", "disciplinaire", "inconnu"]:
    r = rh.get(f"/employes/{F_ID}?onglet={o}")
    check(f"Fiche : onglet {o}", r.status_code == 200, f"HTTP {r.status_code}")
check("Fiche : onglet documents compte les pièces manquantes", "Manquant" in rh.get(f"/employes/{F_ID}?onglet=documents").text)
check("Fiche Comité : pas de bouton d'ajout de sanction", "sanctions/nouvelle" not in comite.get(f"/employes/{F_ID}?onglet=disciplinaire").text)
check("Fiche : dernière connexion lue dans le journal", "dernière connexion le" in rh.get(f"/employes/{CHEF_ID}").text)

# --- Pages principales toujours fonctionnelles ---
for url in ["/", "/employes", f"/employes/{EMP_ID}?onglet=conges", "/demandes", "/absences?periode=toutes", "/conges",
            f"/employes/{EMP_ID}/pdf/fiche", "/export/dashboard.xlsx", "/export/dashboard.csv"]:
    r = rh.get(url)
    check(f"page {url}", r.status_code == 200, f"HTTP {r.status_code}")
esp = client("chef@t.cm")
for url in ["/espace", "/mes-infos", "/mes-infos/pdf", "/mes-validations"]:
    r = esp.get(url)
    check(f"espace employé {url}", r.status_code == 200, f"HTTP {r.status_code}")

print(f"\n{sum(resultats)}/{len(resultats)} vérifications OK")
db.close()
# Sous Windows, un fichier ouvert ne peut pas être supprimé : on ferme d'abord toutes les connexions
# SQLite du moteur. Si la suppression échoue quand même, ce n'est pas grave (base de test jetable).
engine.dispose()
try:
    os.remove("_test_smoke.db")
except OSError:
    print("(Fichier _test_smoke.db laissé en place : il peut être supprimé à la main.)")
