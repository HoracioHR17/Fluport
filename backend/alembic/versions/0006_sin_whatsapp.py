"""quita el canal WhatsApp: solo Telegram (y web para pruebas)

Los enums `canal` y `origen_cita` se recrean sin el valor `whatsapp`. Las conversaciones guardadas de ese canal
se eliminan (el asistente ya no puede continuarlas); los avisos y las citas que lo usaban pasan a `telegram`.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-12 02:00:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _recrear(tipo: str, valores: list[str], columnas: list[tuple[str, str]], reemplazo: str | None) -> None:
    op.execute(f"ALTER TYPE {tipo} RENAME TO {tipo}_old")
    op.execute(f"CREATE TYPE {tipo} AS ENUM ({', '.join(repr(v) for v in valores)})")
    for tabla, columna in columnas:
        uso = f"{columna}::text"
        if reemplazo:
            uso = f"CASE WHEN {columna}::text = 'whatsapp' THEN '{reemplazo}' ELSE {columna}::text END"
        op.execute(f"ALTER TABLE {tabla} ALTER COLUMN {columna} TYPE {tipo} USING ({uso})::{tipo}")
    op.execute(f"DROP TYPE {tipo}_old")


def upgrade() -> None:
    op.execute("DELETE FROM mensaje_asistente WHERE canal = 'whatsapp'")
    _recrear('canal', ['telegram', 'web'], [('mensaje_asistente', 'canal'), ('aviso', 'canal')], 'telegram')
    _recrear('origen_cita', ['web', 'telegram', 'asistente', 'simulador'], [('cita', 'origen')], 'telegram')


def downgrade() -> None:
    _recrear('canal', ['whatsapp', 'telegram', 'web'], [('mensaje_asistente', 'canal'), ('aviso', 'canal')], None)
    _recrear('origen_cita', ['web', 'whatsapp', 'telegram', 'asistente', 'simulador'], [('cita', 'origen')], None)
