"""chat widget session hidden_at (page navigation grace period)

Revision ID: c4f7a1b3d5e8
Revises: b3e6f9a2c4d7
Create Date: 2026-10-16 00:00:01.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4f7a1b3d5e8'
down_revision: str | None = 'b3e6f9a2c4d7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {column['name'] for column in inspector.get_columns(table)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if 'chat_widget_session' not in set(inspector.get_table_names()):
        return
    if 'hidden_at' not in _column_names(inspector, 'chat_widget_session'):
        with op.batch_alter_table('chat_widget_session') as batch_op:
            batch_op.add_column(sa.Column('hidden_at', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if 'chat_widget_session' not in set(inspector.get_table_names()):
        return
    if 'hidden_at' in _column_names(inspector, 'chat_widget_session'):
        with op.batch_alter_table('chat_widget_session') as batch_op:
            batch_op.drop_column('hidden_at')
