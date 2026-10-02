"""Registre du personnel mis à disposition (MAD) : pas des employés, mais suivis par la RH

Revision ID: b7e2d4f81c63
Revises: a1c4e7b90d32
Create Date: 2026-09-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e2d4f81c63'
down_revision: Union[str, Sequence[str], None] = 'a1c4e7b90d32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'personnel_mad',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('nom_complet', sa.String(200), nullable=False),
        sa.Column('fonction', sa.String(150), nullable=True),
        sa.Column('departement_id', sa.Integer(), sa.ForeignKey('departements.id'), nullable=True),
        sa.Column('agence_id', sa.Integer(), sa.ForeignKey('agences.id'), nullable=True),
        sa.Column('societe', sa.String(150), nullable=True),
        sa.Column('telephone', sa.String(30), nullable=True),
        sa.Column('email', sa.String(150), nullable=True),
        sa.Column('date_debut', sa.Date(), nullable=True),
        sa.Column('date_fin', sa.Date(), nullable=True),
        sa.Column('actif', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('observations', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('personnel_mad')
