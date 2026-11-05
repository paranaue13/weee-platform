"""add material tabs table

Revision ID: b7a1c2d3e4f5
Revises: 9be897e9b6c8
Create Date: 2026-11-05 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7a1c2d3e4f5'
down_revision: Union[str, Sequence[str], None] = '9be897e9b6c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Ο πίνακας μπορεί να έχει ήδη δημιουργηθεί από το create_all της εκκίνησης· τότε δεν γίνεται τίποτα."""
    if sa.inspect(op.get_bind()).has_table('material_tabs'):
        return
    op.create_table('material_tabs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('is_system', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_material_tabs_code'), 'material_tabs', ['code'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_material_tabs_code'), table_name='material_tabs')
    op.drop_table('material_tabs')
