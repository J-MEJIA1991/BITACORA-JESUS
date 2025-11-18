"""Renombrar columna entrada a entradas"""

from alembic import op
import sqlalchemy as sa


# revisiones
revision = 'fix_renombrar_entradas'
down_revision = '67d755eaa4d7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("liquidacion") as batch_op:
        batch_op.alter_column("entrada", new_column_name="entradas")


def downgrade():
    with op.batch_alter_table("liquidacion") as batch_op:
        batch_op.alter_column("entradas", new_column_name="entrada")
