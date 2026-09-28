"""Désactivation des comptes utilisateurs (départ d'un employé)

Revision ID: b4d8f2a61c93
Revises: a7c3e91f5b20
Create Date: 2026-09-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4d8f2a61c93'
down_revision: Union[str, Sequence[str], None] = 'a7c3e91f5b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('utilisateurs', sa.Column('compte_actif', sa.Boolean(), server_default='1', nullable=False))
    op.add_column('utilisateurs', sa.Column('desactive_le', sa.DateTime(), nullable=True))
    op.add_column('utilisateurs', sa.Column('motif_desactivation', sa.String(length=255), nullable=True))
    # Rattrapage : les employés DÉJÀ sortis des effectifs perdent leur accès dès maintenant.
    op.execute(
        "UPDATE utilisateurs SET compte_actif = 0, desactive_le = CURRENT_TIMESTAMP, "
        "motif_desactivation = 'Départ antérieur à la mise en place de la désactivation automatique' "
        "WHERE employe_id IN (SELECT id FROM employes WHERE statut = 'inactif')"
    )


def downgrade() -> None:
    op.drop_column('utilisateurs', 'motif_desactivation')
    op.drop_column('utilisateurs', 'desactive_le')
    op.drop_column('utilisateurs', 'compte_actif')
