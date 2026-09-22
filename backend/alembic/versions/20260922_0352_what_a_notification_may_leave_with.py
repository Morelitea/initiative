"""what a notification may leave the app with

Six columns, three questions, asked once of the deployment and once of each
community: may a notification reach a phone, may it reach a mailbox, and may
what it says name the thing it is about.

``app_settings`` holds the deployment's answers and ``guilds`` each community's.
The stricter of the two applies, so a community can restrict what the operator
permits and never the other way round.

Every column ships with the behaviour the app already had — notifications reach
both channels and say what they are about — so an upgrade changes nothing until
somebody sets one.

No grant or policy moves. Both tables are already read by the roles that need
them, at table level.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260922_0352"
down_revision = "20260922_0351"
branch_labels = None
depends_on = None


#: (table, column, server default) for every column this revision adds.
COLUMNS = (
    ("app_settings", "push_notifications_enabled", "true"),
    ("app_settings", "email_notifications_enabled", "true"),
    ("app_settings", "redact_notification_content", "false"),
    ("guilds", "allow_push_notifications", "true"),
    ("guilds", "allow_email_notifications", "true"),
    ("guilds", "redact_notification_content", "false"),
)


def upgrade() -> None:
    for table, column, default in COLUMNS:
        op.add_column(
            table,
            sa.Column(
                column,
                sa.Boolean(),
                nullable=False,
                server_default=sa.text(default),
            ),
            schema="public",
        )


def downgrade() -> None:
    for table, column, _default in reversed(COLUMNS):
        op.drop_column(table, column, schema="public")
