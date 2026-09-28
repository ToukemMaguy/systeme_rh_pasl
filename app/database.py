from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
import os

# Charge les variables du fichier .env (dont DATABASE_URL)
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Le "moteur" : gère la connexion technique à MySQL
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # teste la connexion avant chaque requête, la reconnecte si besoin
    pool_recycle=280,     # referme et renouvelle les connexions inactives après ~5 min
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