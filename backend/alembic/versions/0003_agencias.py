"""agencias: tabla agencia y transportista.agencia_id

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-11 21:30:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agencia',
        sa.Column('id', sa.String(length=16), nullable=False),
        sa.Column('nombre', sa.String(length=120), nullable=False),
        sa.Column('creada_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_agencia')),
    )
    op.add_column('transportista', sa.Column('agencia_id', sa.String(length=16), nullable=True))
    op.create_index(op.f('ix_transportista_agencia_id'), 'transportista', ['agencia_id'])
    op.create_foreign_key(op.f('fk_transportista_agencia_id_agencia'), 'transportista', 'agencia',
                          ['agencia_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint(op.f('fk_transportista_agencia_id_agencia'), 'transportista', type_='foreignkey')
    op.drop_index(op.f('ix_transportista_agencia_id'), table_name='transportista')
    op.drop_column('transportista', 'agencia_id')
    op.drop_table('agencia')
