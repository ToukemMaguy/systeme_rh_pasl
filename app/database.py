from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
import os

# Charge les variables du fichier .env (dont DATABASE_URL)
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Le "moteur" : gère la connexion technique à MySQL
# [PRODUCTION - POINT 7] Jusqu'à 30 connexions simultanées à MySQL (10 permanentes + 20 en pointe) :
# le serveur traite jusqu'à 40 requêtes en parallèle ; avec les 5+10 par défaut, un pic d'activité
# (lundi matin, 210 utilisateurs) pouvait faire attendre ou échouer des pages.
_options_pool = {} if DATABASE_URL and DATABASE_URL.startswith("sqlite") else {"pool_size": 10, "max_overflow": 20, "pool_timeout": 30}
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # teste la connexion avant chaque requête, la reconnecte si besoin
    pool_recycle=280,     # referme et renouvelle les connexions inactives après ~5 min
    **_options_pool,
)

# Fabrique de "sessions" : une session = une conversation avec la base
# pour une requête donnée (lire, ajouter, modifier des données)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Classe de base dont hériteront tous tes modèles (employes, departements...)
# C'est elle qui fait le lien entre une classe Python et une table SQL
Base = declarative_base()

# Fonction utilitaire que FastAPI appellera à chaque requête HTTP
# pour ouvrir une session, puis la refermer proprement après usage
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()