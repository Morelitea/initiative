"""remove active_guild_id from users"""

revision = 'b80896e96c1b'
down_revision = '20260204_0039'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.drop_constraint('fk_users_active_guild_id', 'users', type_='foreignkey')
    op.drop_column('users', 'active_guild_id')


def downgrade() -> None:
    op.add_column('users', sa.Column('active_guild_id', sa.INTEGER(), nullable=True))
    op.create_foreign_key(
        'fk_users_active_guild_id', 'users', 'guilds',
        ['active_guild_id'], ['id'], ondelete='SET NULL',
    )
