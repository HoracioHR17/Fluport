"""solicitudes de alta de transportistas desde el bot

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-12 01:20:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'solicitud_alta',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('telefono', sa.String(length=20), nullable=False),
        sa.Column('nombre', sa.String(length=80), nullable=False),
        sa.Column('telegram_chat_id', sa.BigInteger(), nullable=False),
        sa.Column('agencia_id', sa.String(length=16), nullable=True),
        sa.Column('estado', sa.String(length=16), nullable=False),
        sa.Column('creada_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('resuelta_en', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['agencia_id'], ['agencia.id'], name=op.f('fk_solicitud_alta_agencia_id_agencia'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_solicitud_alta')),
    )
    op.create_index(op.f('ix_solicitud_alta_agencia_id'), 'solicitud_alta', ['agencia_id'])
    op.create_index(op.f('ix_solicitud_alta_telegram_chat_id'), 'solicitud_alta', ['telegram_chat_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_solicitud_alta_telegram_chat_id'), table_name='solicitud_alta')
    op.drop_index(op.f('ix_solicitud_alta_agencia_id'), table_name='solicitud_alta')
    op.drop_table('solicitud_alta')
