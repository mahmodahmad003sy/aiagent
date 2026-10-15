"""chat widget session lifecycle

Revision ID: b3e6f9a2c4d7
Revises: a1c4e7b9d2f3
Create Date: 2026-10-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b3e6f9a2c4d7'
down_revision: str | None = 'a1c4e7b9d2f3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names(inspector: sa.Inspector) -> set[str]:
    return set(inspector.get_table_names())


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {column['name'] for column in inspector.get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = _table_names(inspector)

    if 'chat_widget' in tables:
        columns = _column_names(inspector, 'chat_widget')
        with op.batch_alter_table('chat_widget') as batch_op:
            if 'session_idle_minutes' not in columns:
                batch_op.add_column(
                    sa.Column(
                        'session_idle_minutes',
                        sa.BigInteger(),
                        nullable=False,
                        server_default=sa.text('30'),
                    )
                )
            if 'debug_logs' not in columns:
                batch_op.add_column(
                    sa.Column(
                        'debug_logs',
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.false(),
                    )
                )

    if 'chat_widget_session' in tables:
        columns = _column_names(inspector, 'chat_widget_session')
        with op.batch_alter_table('chat_widget_session') as batch_op:
            if 'ended_at' not in columns:
                batch_op.add_column(sa.Column('ended_at', sa.BigInteger(), nullable=True))
            if 'end_reason' not in columns:
                batch_op.add_column(sa.Column('end_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = _table_names(inspector)

    if 'chat_widget_session' in tables:
        columns = _column_names(inspector, 'chat_widget_session')
        with op.batch_alter_table('chat_widget_session') as batch_op:
            if 'end_reason' in columns:
                batch_op.drop_column('end_reason')
            if 'ended_at' in columns:
                batch_op.drop_column('ended_at')

    if 'chat_widget' in tables:
        columns = _column_names(inspector, 'chat_widget')
        with op.batch_alter_table('chat_widget') as batch_op:
            if 'debug_logs' in columns:
                batch_op.drop_column('debug_logs')
            if 'session_idle_minutes' in columns:
                batch_op.drop_column('session_idle_minutes')
