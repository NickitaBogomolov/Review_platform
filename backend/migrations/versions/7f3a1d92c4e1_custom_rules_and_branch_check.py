"""custom lint rules and branch check

Revision ID: 7f3a1d92c4e1
Revises: c9864345ab62
Create Date: 2026-11-03 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '7f3a1d92c4e1'
down_revision = 'c9864345ab62'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('custom_lint_rules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('pattern', sa.String(length=500), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('severity', sa.String(length=20), nullable=False),
    sa.Column('scope', sa.String(length=10), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.add_column('reviews', sa.Column('branch_check', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True))


def downgrade():
    op.drop_column('reviews', 'branch_check')
    op.drop_table('custom_lint_rules')
