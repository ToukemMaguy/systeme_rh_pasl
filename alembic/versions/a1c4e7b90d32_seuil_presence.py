"""Point 10 : seuil de présence (nombre minimum d'agents) par agence et par département

Revision ID: a1c4e7b90d32
Revises: f3b9d2c61a58
Create Date: 2026-09-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c4e7b90d32'
down_revision: Union[str, Sequence[str], None] = 'f3b9d2c61a58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Sans valeur = pas de contrôle : rien ne change tant que la RH n'a pas fixé de seuil
    op.add_column('agences', sa.Column('seuil_presence_min', sa.Integer(), nullable=True))
    op.add_column('departements', sa.Column('seuil_presence_min', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('departements', 'seuil_presence_min')
    op.drop_column('agences', 'seuil_presence_min')
