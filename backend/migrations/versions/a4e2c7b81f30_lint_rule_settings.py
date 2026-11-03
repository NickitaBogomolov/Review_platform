"""lint rule settings

Revision ID: a4e2c7b81f30
Revises: 7f3a1d92c4e1
Create Date: 2026-11-04 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a4e2c7b81f30'
down_revision = '7f3a1d92c4e1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('lint_rule_settings',
    sa.Column('rule_id', sa.String(length=50), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('rule_id')
    )


def downgrade():
    op.drop_table('lint_rule_settings')
