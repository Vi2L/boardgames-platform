"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
# Композитный rev-id: <timestamp>_<alembic_up_revision>. Длинный ID
# защищает от коллизий при параллельной работе двух агентов: даже если
# оба передадут одинаковый --rev-id в одну секунду, шанс совпадения
# нулевой. См. docs/parallel-agents.md §10.1.
revision: str = "${create_date.strftime('%Y%m%d_%H%M%S')}_${up_revision}"
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
