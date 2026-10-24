"""merge official and widget migration heads

Revision ID: e6a4f9c2b7d1
Revises: 0bd252b206fb, c4f7a1b3d5e8
Create Date: 2026-10-19 00:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = 'e6a4f9c2b7d1'
down_revision: tuple[str, str] = ('0bd252b206fb', 'c4f7a1b3d5e8')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
