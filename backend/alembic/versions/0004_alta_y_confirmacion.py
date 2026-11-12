"""alta de transportistas con placas y confirmación de citas asignadas

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-11 22:50:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('transportista', sa.Column('placas', sa.String(length=20), nullable=True))
    op.add_column('cita', sa.Column('confirmada_en', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('cita', 'confirmada_en')
    op.drop_column('transportista', 'placas')
