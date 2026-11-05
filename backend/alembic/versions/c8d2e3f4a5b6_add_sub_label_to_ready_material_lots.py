"""add sub_label to ready material lots

Revision ID: c8d2e3f4a5b6
Revises: b7a1c2d3e4f5
Create Date: 2026-11-05 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b7a1c2d3e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: νέα στήλη (κενή για όλες τις υπάρχουσες εξαγωγές). Αν υπάρχει ήδη (νέα βάση από create_all) δεν γίνεται τίποτα."""
    cols = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('ready_material_lots')}
    if 'sub_label' in cols:
        return
    with op.batch_alter_table('ready_material_lots') as batch:
        batch.add_column(sa.Column('sub_label', sa.String(length=200), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('ready_material_lots') as batch:
        batch.drop_column('sub_label')
