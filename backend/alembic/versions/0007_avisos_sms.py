"""avisos por SMS para transportistas sin smartphone (giro del reto)

- `canal` (enum) suma el valor `sms`.
- `transportista.canal_aviso` (telegram | sms): canal de avisos que elige la agencia; los existentes quedan en telegram.
- `aviso.destino` y `aviso.detalle`: a quién se envió (chat o teléfono) y el id del proveedor o el motivo del error.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-12 07:30:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CANAL_AVISO = postgresql.ENUM('telegram', 'sms', name='canal_aviso', create_type=False)


def upgrade() -> None:
    op.execute("ALTER TYPE canal ADD VALUE IF NOT EXISTS 'sms'")
    CANAL_AVISO.create(op.get_bind(), checkfirst=True)
    op.add_column('transportista', sa.Column('canal_aviso', CANAL_AVISO, nullable=False, server_default='telegram'))
    op.add_column('aviso', sa.Column('destino', sa.String(length=40), nullable=True))
    op.add_column('aviso', sa.Column('detalle', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('aviso', 'detalle')
    op.drop_column('aviso', 'destino')
    op.drop_column('transportista', 'canal_aviso')
    CANAL_AVISO.drop(op.get_bind(), checkfirst=True)
    # quitar 'sms' del enum `canal`: se recrea sin ese valor (los avisos SMS pasan a telegram)
    op.execute("ALTER TYPE canal RENAME TO canal_old")
    op.execute("CREATE TYPE canal AS ENUM ('telegram', 'web')")
    for tabla in ('mensaje_asistente', 'aviso'):
        op.execute(f"ALTER TABLE {tabla} ALTER COLUMN canal TYPE canal USING "
                   f"(CASE WHEN canal::text = 'sms' THEN 'telegram' ELSE canal::text END)::canal")
    op.execute("DROP TYPE canal_old")
