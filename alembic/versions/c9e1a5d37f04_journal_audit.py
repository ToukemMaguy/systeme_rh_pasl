"""Journal d'audit

Revision ID: c9e1a5d37f04
Revises: b4d8f2a61c93
Create Date: 2026-09-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9e1a5d37f04'
down_revision: Union[str, Sequence[str], None] = 'b4d8f2a61c93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'journal_audit',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('date_heure', sa.DateTime(), nullable=False),
        sa.Column('utilisateur_id', sa.Integer(), nullable=True),
        sa.Column('utilisateur_nom', sa.String(length=150), nullable=True),
        sa.Column('role', sa.String(length=30), nullable=True),
        sa.Column('adresse_ip', sa.String(length=45), nullable=True),
        sa.Column('action', sa.String(length=30), nullable=False),
        sa.Column('objet_type', sa.String(length=50), nullable=False),
        sa.Column('objet_id', sa.Integer(), nullable=True),
        sa.Column('employe_id', sa.Integer(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
    )
    op.create_index('ix_journal_audit_date_heure', 'journal_audit', ['date_heure'])
    op.create_index('ix_journal_audit_utilisateur_id', 'journal_audit', ['utilisateur_id'])
    op.create_index('ix_journal_audit_objet_type', 'journal_audit', ['objet_type'])
    op.create_index('ix_journal_audit_employe_id', 'journal_audit', ['employe_id'])


def downgrade() -> None:
    op.drop_table('journal_audit')
