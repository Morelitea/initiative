"""an install reads its community's members, and tells them what it did

An installed app names people the way guild content does: through the account
projections (0220, 0244). Its routed role inherits ``app_install_base``, which
holds nothing on them, so the member search behind ``members:read`` and every
person a content read carries (an owner, an assignee, an author) are refused.

The install floor gains ``SELECT`` on both projections:

* ``public.current_guild_members`` — the routed community's members, which the
  member search reads.
* ``public.guild_member_profiles`` — a person by id, which every relationship
  from guild content to a person reads. For a person's request it projects any
  account, as it has since 0220. For an installed app's request it projects
  only the members of the community the request is routed into: the view
  reads ``app.current_install_id`` and, when it is set, keeps the rows whose
  id is a membership of the routed community. The membership read runs as the
  view's owner, ``app_profile_reader``, under the policy 0244 gave it for
  exactly the routed community.

The view's body is restated in full; the downgrade restores 0281's.

What an install does reaches people the way a member's work does: a bell line
written on the routed request for its named recipient (0245, 0350) and the
email appended beside it (0320). The install floor gains what the guild floor
holds for that and nothing more:

* ``SELECT``, ``INSERT``, ``UPDATE`` on ``public.notifications``, under the
  named-recipient policies (rendered from ``app.db.public_rls``, which now name
  the install floor beside the guild floor), and the id sequence;
* ``INSERT`` on ``public.email_outbox`` and its sequence;
* ``SELECT`` on ``public.app_settings``, which every request floor reads
  (``app_settings_read``) and which says whether the deployment sends mail.

Revision ID: 20260924_0386
Revises: 20260924_0385
Create Date: 2026-09-24
"""

from alembic import op

revision = "20260924_0386"
down_revision = "20260924_0385"
branch_labels = None
depends_on = None

#: The reader role that owns both projections. Created in 0214.
READER = "app_profile_reader"

PROFILES = "public.guild_member_profiles"
MEMBERS = "public.current_guild_members"

#: The guild the request is routed into, as 0281 reads it.
ROUTED_GUILD_ID = """COALESCE(
        NULLIF(current_setting('app.current_guild_id', true), '')::int,
        NULLIF(current_setting('app.pam_guild_id', true), '')::int
    )"""

#: The columns either side of the name, in the order the view has had since
#: 0220. Written out rather than imported so a replay of this revision builds
#: the view this revision built.
BEFORE = ("id", "username", "discriminator")
AFTER = (
    "avatar_url",
    "status",
    "custom_status",
    "profile_decorations",
    "created_at",
)

#: 0281's name rule, unchanged: uncorrelated, so evaluated once per statement.
NAME_FROM_THE_GUILD = f"""CASE WHEN (
    SELECT g.show_member_names FROM public.guilds g WHERE g.id = {ROUTED_GUILD_ID}
) THEN full_name END AS full_name"""

#: An installed app's request reads the routed community's members only. A
#: person's request has no install set, and reads every account as before.
INSTALL_READS_ITS_MEMBERS = f"""
    NULLIF(current_setting('app.current_install_id', true), '') IS NULL
    OR id IN (
        SELECT m.user_id FROM public.guild_memberships m
        WHERE m.guild_id = {ROUTED_GUILD_ID}
    )"""


def _view(where: str | None) -> str:
    columns = ", ".join((*BEFORE, NAME_FROM_THE_GUILD, *AFTER))
    body = f"CREATE OR REPLACE VIEW {PROFILES} AS SELECT {columns} FROM public.users"
    return body if where is None else f"{body} WHERE {where}"


def upgrade() -> None:
    op.execute(f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE')
    op.execute(_view(INSTALL_READS_ITS_MEMBERS))
    op.execute(f"GRANT SELECT ON {PROFILES} TO app_install_base")
    op.execute(f"GRANT SELECT ON {MEMBERS} TO app_install_base")

    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON TABLE public.notifications "
        "TO app_install_base"
    )
    op.execute(
        "GRANT USAGE, SELECT ON SEQUENCE public.notifications_id_seq "
        "TO app_install_base"
    )
    op.execute("GRANT INSERT ON TABLE public.email_outbox TO app_install_base")
    op.execute(
        "GRANT USAGE, SELECT ON SEQUENCE public.email_outbox_id_seq "
        "TO app_install_base"
    )
    op.execute("GRANT SELECT ON TABLE public.app_settings TO app_install_base")


def downgrade() -> None:
    op.execute(f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE')
    op.execute("REVOKE SELECT ON TABLE public.app_settings FROM app_install_base")
    op.execute(
        "REVOKE USAGE, SELECT ON SEQUENCE public.email_outbox_id_seq "
        "FROM app_install_base"
    )
    op.execute("REVOKE INSERT ON TABLE public.email_outbox FROM app_install_base")
    op.execute(
        "REVOKE USAGE, SELECT ON SEQUENCE public.notifications_id_seq "
        "FROM app_install_base"
    )
    # The named-recipient policies are the guild floor's too, so they stay;
    # boot renders them again from the registry, without the install floor.
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE ON TABLE public.notifications "
        "FROM app_install_base"
    )
    op.execute(f"REVOKE ALL ON {MEMBERS} FROM app_install_base")
    op.execute(f"REVOKE ALL ON {PROFILES} FROM app_install_base")
    op.execute(_view(None))
