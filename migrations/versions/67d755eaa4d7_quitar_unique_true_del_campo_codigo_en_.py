
"""Quitar unique=True del campo codigo en Cliente"""

from alembic import op


# Revisiones
revision = '67d755eaa4d7'
down_revision = '214ed53e4b8c'
branch_labels = None
depends_on = None


def upgrade():
    # ✅ Solo eliminar la restricción de unicidad y crear índice normal
    op.drop_constraint('cliente_codigo_key', 'cliente', type_='unique')
    op.create_index(op.f('ix_cliente_codigo'), 'cliente', ['codigo'], unique=False)


def downgrade():
    # ✅ Revertir el cambio si se baja la versión
    op.drop_index(op.f('ix_cliente_codigo'), table_name='cliente')
    op.create_unique_constraint('cliente_codigo_key', 'cliente', ['codigo'])
