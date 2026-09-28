"""Module licenciement

Revision ID: d2f7b3c8e915
Revises: c9e1a5d37f04
Create Date: 2026-09-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2f7b3c8e915'
down_revision: Union[str, Sequence[str], None] = 'c9e1a5d37f04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'licenciements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('employe_id', sa.Integer(), sa.ForeignKey('employes.id'), nullable=False),
        sa.Column('statut', sa.String(length=20), nullable=False),
        sa.Column('type_motif', sa.String(length=40), nullable=False),
        sa.Column('date_faits', sa.Date(), nullable=True),
        sa.Column('expose_faits', sa.Text(), nullable=True),
        sa.Column('sanctions_liees', sa.JSON(), nullable=True),
        sa.Column('mise_a_pied_conservatoire', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('mise_a_pied_debut', sa.Date(), nullable=True),
        sa.Column('mise_a_pied_fin', sa.Date(), nullable=True),
        sa.Column('conseil_date', sa.Date(), nullable=True),
        sa.Column('conseil_membres', sa.Text(), nullable=True),
        sa.Column('conseil_avis', sa.String(length=20), nullable=True),
        sa.Column('conseil_sanction_proposee', sa.String(length=50), nullable=True),
        sa.Column('conseil_resume', sa.Text(), nullable=True),
        sa.Column('pv_path', sa.String(length=255), nullable=True),
        sa.Column('preavis_jours', sa.Integer(), nullable=True),
        sa.Column('preavis_dispense', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('avis_rh', sa.String(length=20), nullable=True),
        sa.Column('commentaire_rh', sa.Text(), nullable=True),
        sa.Column('decision', sa.String(length=20), nullable=True),
        sa.Column('decision_commentaire', sa.Text(), nullable=True),
        sa.Column('date_notification', sa.Date(), nullable=True),
        sa.Column('mode_notification', sa.String(length=50), nullable=True),
        sa.Column('date_sortie', sa.Date(), nullable=True),
        sa.Column('jours_conges_restants', sa.Numeric(5, 1), nullable=True),
        sa.Column('lettre_signee_path', sa.String(length=255), nullable=True),
        sa.Column('motif_annulation', sa.Text(), nullable=True),
        sa.Column('depart_id', sa.Integer(), sa.ForeignKey('departs.id'), nullable=True),
        sa.Column('sanction_id', sa.Integer(), sa.ForeignKey('sanctions.id'), nullable=True),
        sa.Column('ouvert_par', sa.String(length=150), nullable=True),
        sa.Column('ouvert_le', sa.DateTime(), nullable=True),
        sa.Column('transmis_par', sa.String(length=150), nullable=True),
        sa.Column('transmis_le', sa.DateTime(), nullable=True),
        sa.Column('decide_par', sa.String(length=150), nullable=True),
        sa.Column('decide_le', sa.DateTime(), nullable=True),
        sa.Column('notifie_par', sa.String(length=150), nullable=True),
    )
    op.create_index('ix_licenciements_employe_id', 'licenciements', ['employe_id'])


def downgrade() -> None:
    op.drop_table('licenciements')
