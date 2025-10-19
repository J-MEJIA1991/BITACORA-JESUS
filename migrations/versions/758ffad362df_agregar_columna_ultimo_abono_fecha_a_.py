"""Agregar columna ultimo_abono_fecha a Cliente y frecuencia a Prestamo

Revision ID: 758ffad362df
Revises: 
Create Date: 2025-10-19 03:25:41.944858
"""

from alembic import op
import sqlalchemy as sa

# Identificadores de la revisión
revision = '758ffad362df'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ✅ Solo agregamos las columnas necesarias
    op.add_column('cliente', sa.Column('ultimo_abono_fecha', sa.Date(), nullable=True))
    op.add_column('prestamo', sa.Column('frecuencia', sa.String(length=20), nullable=True))


def downgrade():
    # 🔁 Revertir si fuera necesario
    op.drop_column('cliente', 'ultimo_abono_fecha')
    op.drop_column('prestamo', 'frecuencia')
