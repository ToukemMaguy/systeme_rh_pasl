"""Lettre de licenciement en saisie libre (texte imprimé sur le papier à en-tête PASL)

Revision ID: e5a8c1f94b27
Revises: d2f7b3c8e915
Create Date: 2026-09-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a8c1f94b27'
down_revision: Union[str, Sequence[str], None] = 'd2f7b3c8e915'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('licenciements', sa.Column('lettre_texte', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('licenciements', 'lettre_texte')
