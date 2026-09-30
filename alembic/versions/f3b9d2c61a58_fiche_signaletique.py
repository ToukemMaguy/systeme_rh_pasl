"""Fiche signalétique : lieu de naissance, nationalité, CNI, adresse, CNPS, niveau d'études

Revision ID: f3b9d2c61a58
Revises: e5a8c1f94b27
Create Date: 2026-09-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3b9d2c61a58'
down_revision: Union[str, Sequence[str], None] = 'e5a8c1f94b27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLONNES = [
    ('lieu_naissance', sa.String(100)),
    ('nationalite', sa.String(60)),
    ('numero_cni', sa.String(30)),
    ('cni_delivree_le', sa.Date()),
    ('adresse', sa.String(255)),
    ('numero_cnps', sa.String(30)),
    ('niveau_etudes', sa.String(150)),
]


def upgrade() -> None:
    # Toutes facultatives : les fiches existantes restent valides
    for nom, type_ in COLONNES:
        op.add_column('employes', sa.Column(nom, type_, nullable=True))


def downgrade() -> None:
    for nom, _ in reversed(COLONNES):
        op.drop_column('employes', nom)
