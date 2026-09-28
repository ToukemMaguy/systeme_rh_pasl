"""Sécurité des comptes : blocage après échecs de connexion, mot de passe à changer

Revision ID: a7c3e91f5b20
Revises: 0d4c4bafd1d8
Create Date: 2026-09-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c3e91f5b20'
down_revision: Union[str, Sequence[str], None] = '0d4c4bafd1d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ajoute 3 colonnes à la table utilisateurs (les comptes existants ne sont pas bloqués
    et n'ont pas à changer leur mot de passe : valeurs par défaut 0)."""
    op.add_column('utilisateurs', sa.Column('tentatives_echouees', sa.Integer(), server_default='0', nullable=False))
    op.add_column('utilisateurs', sa.Column('bloque_jusqua', sa.DateTime(), nullable=True))
    op.add_column('utilisateurs', sa.Column('doit_changer_mdp', sa.Boolean(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('utilisateurs', 'doit_changer_mdp')
    op.drop_column('utilisateurs', 'bloque_jusqua')
    op.drop_column('utilisateurs', 'tentatives_echouees')
