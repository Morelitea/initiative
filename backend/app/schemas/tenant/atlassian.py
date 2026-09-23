"""The wire shapes for connecting to an Atlassian site and looking around it.

One request answers both questions the wizard's first screen asks: *are these
credentials good*, and *what is there to bring over*. They are the same
question in practice — the only honest proof that a token works is using it —
so the connect response carries the probe rather than making the browser ask
twice.

Nothing here holds a secret going out. The token travels in, once; what comes
back names the site and what is on it.
"""

from typing import Annotated, List, Optional

from pydantic import Field

from app.schemas.base import SanitizedBaseModel


class AtlassianConnectRequest(SanitizedBaseModel):
    """What somebody types into the connect step.

    ``site_url`` is the site as a person knows it —
    ``https://acme.atlassian.net``. Anything after the host is ignored: the
    products live at fixed paths under it, and a URL pasted from a browser's
    address bar is usually pointing at a board.
    """

    site_url: str = Field(min_length=1, max_length=2000)
    #: The Atlassian account the API token belongs to. Their identifier at the
    #: source, not this platform's.
    email: str = Field(min_length=1, max_length=320)
    #: An Atlassian API token. Never stored in the clear and never echoed back.
    api_token: str = Field(min_length=1, max_length=2000)


class AtlassianJiraProject(SanitizedBaseModel):
    """One Jira project the token can see."""

    id: str
    key: str
    name: str
    #: Roughly how many issues are in it, or ``None`` when the count could not
    #: be taken. Approximate by construction — Jira answers this one cheaply
    #: and inexactly, and an exact number would cost a search per project.
    issue_count: Optional[int] = None


class AtlassianConfluenceSpace(SanitizedBaseModel):
    """One Confluence space the token can see."""

    id: str
    key: str
    name: str
    #: How many pages are in it, or ``None`` when the count could not be taken.
    page_count: Optional[int] = None


class AtlassianProductProbe(SanitizedBaseModel):
    """What one product on the site turned out to hold.

    ``available`` is false when the product is not on the site, or the token
    cannot see it. That is not an error: plenty of sites run one and not the
    other, and a person importing Jira should not be stopped by a Confluence
    they do not have.
    """

    available: bool = False
    #: Why it is unavailable, as an ``IMPORT_SOURCE_*`` code, when it is.
    #: Absent when the product answered.
    reason: Optional[str] = None


class AtlassianJiraProbe(AtlassianProductProbe):
    projects: List[AtlassianJiraProject] = []


class AtlassianConfluenceProbe(AtlassianProductProbe):
    spaces: List[AtlassianConfluenceSpace] = []


#: A Jira project key as Jira itself allows one: a letter, then letters,
#: digits or underscores. Checked because a key travels into a request path
#: and a JQL clause on somebody else's server.
JIRA_PROJECT_KEY_PATTERN = r"^[A-Za-z][A-Za-z0-9_]*$"


class AtlassianJiraImportRequest(SanitizedBaseModel):
    """The choose step's answer: which projects, from which site, into which
    initiative.

    Nothing is read from the site here. The request starts a job, and the
    worker reads the projects into a bundle and parks it for review — the
    plan the wizard shows next is filled in as that fetch goes.

    It carries the same three values the connect step proved, because the job
    row is what holds them from here on: the site the projects come from, who
    the token authenticates as there, and the token itself.
    """

    site_url: str = Field(min_length=1, max_length=2000)
    #: The Atlassian account the API token belongs to. Their identifier at the
    #: source, not this platform's.
    email: str = Field(min_length=1, max_length=320)
    #: An Atlassian API token. Stored encrypted on the job and never echoed.
    api_token: str = Field(min_length=1, max_length=2000)
    #: The initiative the projects land in. It has to exist, have projects
    #: switched on, and let this person create them — checked now, and again
    #: when the fetch starts and when the bundle is applied.
    initiative_id: int
    project_keys: List[
        Annotated[
            str, Field(min_length=1, max_length=50, pattern=JIRA_PROJECT_KEY_PATTERN)
        ]
    ] = Field(max_length=200)
    #: Bring each issue's comments across. On unless somebody turns it off:
    #: it costs a call per issue whose comments run past the first page, which
    #: a large project with long threads will feel.
    include_comments: bool = True
    #: Bring each issue's images across as uploads, shown where the
    #: description or a comment embedded them. On unless turned off: each is a
    #: download, and they count against the community's storage.
    include_attachments: bool = True


class AtlassianConnectResponse(SanitizedBaseModel):
    """The connect step's answer: what is on the site.

    The request that starts an import carries the token again, so there is
    nothing to quote back here and nothing kept between the two.
    """

    #: The site as the server normalised it, which is what the job will use.
    site_url: str
    jira: AtlassianJiraProbe = AtlassianJiraProbe()
    confluence: AtlassianConfluenceProbe = AtlassianConfluenceProbe()
