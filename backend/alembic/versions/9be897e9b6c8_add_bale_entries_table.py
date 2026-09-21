"""add bale entries table

Revision ID: 9be897e9b6c8
Revises: ff0fdce1582a
Create Date: 2026-09-16 13:07:59.803190

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9be897e9b6c8'
down_revision: Union[str, Sequence[str], None] = 'ff0fdce1582a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('bale_entries',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('period', sa.DateTime(timezone=True), nullable=False),
    sa.Column('material_group', sa.String(length=100), nullable=False),
    sa.Column('bale_seq', sa.Integer(), nullable=True),
    sa.Column('weight_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('is_bulk', sa.Boolean(), nullable=False),
    sa.Column('bale_count', sa.Integer(), nullable=True),
    sa.Column('source', sa.String(length=30), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('bale_entries', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bale_entries_material_group'), ['material_group'], unique=False)
        batch_op.create_index(batch_op.f('ix_bale_entries_period'), ['period'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('bale_entries', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bale_entries_period'))
        batch_op.drop_index(batch_op.f('ix_bale_entries_material_group'))

    op.drop_table('bale_entries')
