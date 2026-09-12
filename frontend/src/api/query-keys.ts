/**
 * What a write made stale, described once and matched once.
 *
 * NAMING — the UI calls these "communities"; the code calls them guilds.
 * Communities ended up being used far more broadly than the gaming guilds the
 * name was picked for, so the product renamed them. The rename stopped at the
 * user-visible strings: the database, the API, the generated client and every
 * identifier below still say `guild`, because moving those means a schema
 * migration across every tenant. Treat `guild` in code and `community` in copy
 * as the same thing. This is deliberate and permanent, not a half-finished
 * rename -- if you are adding UI, say community; if you are adding a query,
 * follow the `guild` that is already here.
 *
 * Orval keys queries by URL (e.g. `["/api/v1/tags/"]`), so a domain question
 * ("every task list") is a question about paths. The `q.*` builders answer it
 * as a **description** — a `Spec` naming paths, prefixes and thread ids — and
 * `invalidate()` merges however many of those it is handed and walks the cache
 * ONCE.
 *
 * That single walk is the point. A predicate filter makes React Query test
 * every cached query, so the old shape — one `invalidateQueries` per helper,
 * helpers called once per changed entity — cost a full pass per call. A
 * realtime batch of 300 comments came to 2,104 passes and 367ms of blocked
 * main thread; described and merged, it is one pass and under a millisecond,
 * and the cost stops growing with the size of the batch. Repeats collapse for
 * free: merging is into sets, so one list named by three hundred changes is one
 * entry.
 *
 * There are TWO disjoint families of keys, and a match MUST NOT cross between
 * them:
 *
 *  - GUILD-scoped keys live under `/api/v1/g/{guildId}/...`. `guildExact` and
 *    `guildPrefix` reach these and ONLY for the ACTIVE guild — never another
 *    guild, and never a non-guild key. This is the tenancy boundary: a mutation
 *    in one guild can't touch another guild's (or a personal) cached data.
 *  - PERSONAL / platform keys are everything else (`/api/v1/me/*`, `/settings`,
 *    `/users`, `/guilds`, `/admin`, `/notifications`, `/version`, `/recents`).
 *    `personalExact` and `personalPrefix` reach these and ONLY these.
 *
 * A few resources genuinely span both (a guild list plus its cross-guild `/me`
 * aggregate; platform + guild AI settings). Those name a bucket from each
 * family in one `Spec` — still two boundary-respecting tests, decided in one
 * place rather than blurred into one path test. The whole rule now lives in
 * `matches()` below, the only code in the app that decides whether a cached key
 * belongs to the current guild.
 */
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { queryClient } from "@/lib/queryClient";
import { singularOf, toolIdParam } from "@/lib/tools";

// The active guild is per-tab React state in `GuildProvider`, mirrored here (a
// module var is per-JS-context, so it stays per-tab — unlike shared storage) so
// the guild matchers can scope without every call site threading a guild id.
let scopedGuildId: number | null = null;

/** Mirror this tab's active guild so guild invalidation stays scoped to it. */
export const setInvalidationGuild = (guildId: number | null) => {
  scopedGuildId = guildId && guildId > 0 ? guildId : null;
};

const GUILD_SEGMENT = /^\/api\/v1\/g\/(\d+)(\/.*)?$/;

// ── What a write made stale ──────────────────────────────────────────────────

/**
 * A description of cached queries — never an action on them.
 *
 * Every field is additive and optional, so specs merge by concatenation and a
 * builder names only the buckets it needs.
 */
export type Spec = {
  /** Guild-relative paths matched whole: `/api/v1/tasks/7`. */
  guildExact?: readonly string[];
  /** Guild-relative path prefixes: `/api/v1/tasks` reaches the lists under it. */
  guildPrefix?: readonly string[];
  /** Non-guild paths matched whole: `/api/v1/version`. */
  personalExact?: readonly string[];
  /** Non-guild path prefixes: `/api/v1/me/tasks`. */
  personalPrefix?: readonly string[];
  /**
   * Comment threads, as `[parentParam, parentId]`. A thread is keyed
   * `["/api/v1/g/{g}/comments/", { task_id: 7 }]` — the id sits in the params
   * object rather than the path, so it cannot be reached by a prefix.
   */
  threads?: readonly (readonly [param: string, id: number])[];
  /**
   * Hand-written keys named by their first element and carrying their guild in
   * the second (`["guild-app", guildId, appId]`). Scoped to the active guild by
   * that element, like every other guild key.
   */
  guildNamed?: readonly string[];
  /** Hand-written keys matched by their first element alone (`["dm", …]`). */
  named?: readonly string[];
};

/** One or more specs, merged. Sets, so repeats cost nothing. */
type Matcher = {
  guildExact: Set<string>;
  guildPrefix: string[];
  personalExact: Set<string>;
  personalPrefix: string[];
  threads: Map<string, Set<number>>;
  guildNamed: Set<string>;
  named: Set<string>;
};

const merge = (specs: readonly Spec[]): Matcher => {
  const matcher: Matcher = {
    guildExact: new Set(),
    guildPrefix: [],
    personalExact: new Set(),
    personalPrefix: [],
    threads: new Map(),
    guildNamed: new Set(),
    named: new Set(),
  };
  for (const spec of specs) {
    for (const path of spec.guildExact ?? []) matcher.guildExact.add(path);
    for (const path of spec.personalExact ?? []) matcher.personalExact.add(path);
    for (const name of spec.guildNamed ?? []) matcher.guildNamed.add(name);
    for (const name of spec.named ?? []) matcher.named.add(name);
    // Prefixes stay a list: there are only ever a handful, and each has to be
    // tested against the path rather than looked up.
    for (const prefix of spec.guildPrefix ?? []) {
      if (!matcher.guildPrefix.includes(prefix)) matcher.guildPrefix.push(prefix);
    }
    for (const prefix of spec.personalPrefix ?? []) {
      if (!matcher.personalPrefix.includes(prefix)) matcher.personalPrefix.push(prefix);
    }
    for (const [param, id] of spec.threads ?? []) {
      const ids = matcher.threads.get(param);
      if (ids) ids.add(id);
      else matcher.threads.set(param, new Set([id]));
    }
  }
  return matcher;
};

/**
 * Whether one cached query is named by the merged description.
 *
 * The only place in the app that decides which family a key belongs to, and the
 * only place the active guild is compared. A key addressing a guild is answered
 * from the guild buckets and never falls through to the personal ones — another
 * guild's key matches nothing at all.
 */
const matches = (matcher: Matcher, queryKey: readonly unknown[]): boolean => {
  const first = queryKey[0];
  if (typeof first !== "string") return false;

  const guild = GUILD_SEGMENT.exec(first);
  if (guild) {
    if (scopedGuildId !== null && Number(guild[1]) !== scopedGuildId) return false;
    const path = `/api/v1${guild[2] ?? ""}`;
    if (matcher.guildExact.has(path)) return true;
    for (const prefix of matcher.guildPrefix) {
      if (path.startsWith(prefix)) return true;
    }
    if (matcher.threads.size > 0 && path === "/api/v1/comments/") {
      const params = queryKey[1];
      if (typeof params === "object" && params !== null) {
        for (const [param, ids] of matcher.threads) {
          const value = (params as Record<string, unknown>)[param];
          if (typeof value === "number" && ids.has(value)) return true;
        }
      }
    }
    return false;
  }

  if (matcher.guildNamed.has(first)) {
    return scopedGuildId === null || queryKey[1] === scopedGuildId;
  }
  if (matcher.named.has(first)) return true;
  if (matcher.personalExact.has(first)) return true;
  for (const prefix of matcher.personalPrefix) {
    if (first.startsWith(prefix)) return true;
  }
  return false;
};

/**
 * Refresh everything the given specs name, in one pass over the cache.
 *
 * Hand it as many as the caller has — a mutation's two, a realtime batch's
 * three hundred. It is one walk either way.
 */
export const invalidate = (...specs: readonly Spec[]) => {
  const matcher = merge(specs);
  return queryClient.invalidateQueries({
    predicate: (query) => matches(matcher, query.queryKey),
  });
};

// ── Builders ─────────────────────────────────────────────────────────────────
// Pure descriptions, grouped under `q` so a call site reads
// `invalidate(q.allTasks(), q.task(id))`, and so adding one cannot collide with
// a local name in any of the fifty-odd files that invalidate something.

const compose = (...specs: Spec[]): Spec => ({
  guildExact: specs.flatMap((spec) => spec.guildExact ?? []),
  guildPrefix: specs.flatMap((spec) => spec.guildPrefix ?? []),
  personalExact: specs.flatMap((spec) => spec.personalExact ?? []),
  personalPrefix: specs.flatMap((spec) => spec.personalPrefix ?? []),
  threads: specs.flatMap((spec) => spec.threads ?? []),
  guildNamed: specs.flatMap((spec) => spec.guildNamed ?? []),
  named: specs.flatMap((spec) => spec.named ?? []),
});

/**
 * A resource's guild-scoped list AND its cross-guild "my" aggregate.
 *
 * The `/api/v1/me/<r>` read is personal, so a guild prefix never reaches it and
 * it has to be named explicitly or the "my <resource>" list goes stale until
 * remount.
 */
const resourceAndMe = (resource: string): Spec => ({
  guildPrefix: [`/api/v1/${resource}`],
  personalPrefix: [`/api/v1/me/${resource}`],
});

// ── Announcements (platform) ─────────────────────────────────────────────────

/** Both the reader's queue and the authoring list — one write moves both. */
const announcements = (): Spec => ({ personalPrefix: ["/api/v1/announcements"] });

// ── Tags (guild) ─────────────────────────────────────────────────────────────

const allTags = (): Spec => ({ guildPrefix: ["/api/v1/tags"] });

const tag = (tagId: number): Spec => ({ guildExact: [`/api/v1/tags/${tagId}`] });

const tagEntities = (tagId: number): Spec => ({ guildExact: [`/api/v1/tags/${tagId}/entities`] });

// ── Tasks (guild + me) ───────────────────────────────────────────────────────

// Also names the calendar-entries aggregate (a derived events+tasks view), so a
// task mutation reflects on the calendar surfaces.
const allTasks = (): Spec => compose(resourceAndMe("tasks"), resourceAndMe("calendar-entries"));

const task = (taskId: number): Spec => ({ guildExact: [`/api/v1/tasks/${taskId}`] });

// ── Projects (guild + me) ────────────────────────────────────────────────────

const allProjects = (): Spec => resourceAndMe("projects");

const project = (projectId: number): Spec => ({ guildExact: [`/api/v1/projects/${projectId}`] });

const projectTaskStatuses = (projectId: number): Spec => ({
  guildExact: [`/api/v1/projects/${projectId}/task-statuses/`],
});

const projectFilterPresets = (projectId: number): Spec => ({
  guildExact: [`/api/v1/projects/${projectId}/filter-presets/`],
});

const projectActivity = (projectId: number): Spec => ({
  guildExact: [`/api/v1/projects/${projectId}/activity`],
});

// Recents list is a cross-guild personal endpoint (`/api/v1/recents/`, no /g/).
const recents = (): Spec => ({ personalExact: ["/api/v1/recents/"] });

const favoriteProjects = (): Spec => ({ guildExact: ["/api/v1/projects/favorites"] });

const writableProjects = (): Spec => ({ guildExact: ["/api/v1/projects/writable"] });

// ── Documents (guild + me) ───────────────────────────────────────────────────

const allDocuments = (): Spec => resourceAndMe("documents");

const document = (documentId: number): Spec => ({
  guildExact: [`/api/v1/documents/${documentId}`],
});

/** Every read of the graph. One path serves them all, so one bucket does. */
const relationships = (): Spec => ({
  guildPrefix: ["/api/v1/relationships"],
});

const documentVersions = (documentId: number): Spec => ({
  guildExact: [`/api/v1/documents/${documentId}/versions`],
});

// ── Comments (guild) ─────────────────────────────────────────────────────────

const allComments = (): Spec => ({ guildPrefix: ["/api/v1/comments"] });

/**
 * One comment thread: the list query keyed by the parent it hangs off.
 *
 * A thread is addressed by exactly one `{parent}_id` param, so the description
 * is that param rather than a builder per parent — the backend declares the
 * same set once in `_COMMENT_PARENTS`.
 */
const commentsByParent = (param: string, id: number): Spec => ({ threads: [[param, id]] });

const taskComments = (taskId: number): Spec => commentsByParent("task_id", taskId);

const documentComments = (documentId: number): Spec => commentsByParent("document_id", documentId);

/** The comment thread on one tool entity — a post, a queue, a dashboard. */
const toolComments = (which: Tool, id: number): Spec => commentsByParent(toolIdParam(which), id);

/**
 * The comment thread on one parent, named by the parent's own resource type.
 *
 * The bus names a parent by its table (`tasks`, `counter_groups`), and a thread
 * is keyed by that parent's singular `{parent}_id` — the same derivation the
 * backend makes to report a junction against its owner. So this covers the task
 * and every tool without a branch per parent.
 */
const commentsOnResource = (resourceType: string, id: number): Spec =>
  commentsByParent(`${singularOf(resourceType)}_id`, id);

const recentComments = (): Spec => ({ guildPrefix: ["/api/v1/comments/recent"] });

// ── Notifications (personal) ─────────────────────────────────────────────────

const notifications = (): Spec => ({ personalPrefix: ["/api/v1/notifications"] });

// ── Contacts: who may reach you, and who you have agreed with ────────────────

/** The policy and its per-community toggles. */
const dmSettings = (): Spec => ({ personalExact: ["/api/v1/me/dm-settings"] });

/** Connections and message requests — one channel moves both. */
const contactGrants = (): Spec => ({
  personalPrefix: ["/api/v1/me/connections", "/api/v1/me/message-requests"],
});

/** The accounts this person has chosen not to hear from. */
const ignoredAccounts = (): Spec => ({ personalPrefix: ["/api/v1/me/ignored"] });

/** Everyone the reader may reach: the community sections and the starred list. */
const contacts = (): Spec => ({ personalPrefix: ["/api/v1/me/contacts"] });

/**
 * The direct-message mailbox.
 *
 * Keyed on `["dm", …]` rather than a path, because a thread is read out of this
 * device's own store rather than from an endpoint — the server deletes a
 * message once it has been collected.
 */
const directMessages = (): Spec => ({ named: ["dm"] });

// ── Initiatives (guild) ──────────────────────────────────────────────────────

const allInitiatives = (): Spec => ({ guildPrefix: ["/api/v1/initiatives"] });

const initiative = (initiativeId: number): Spec => ({
  guildExact: [`/api/v1/initiatives/${initiativeId}`],
});

const initiativeRoles = (initiativeId: number): Spec => ({
  guildExact: [`/api/v1/initiatives/${initiativeId}/roles`],
});

const myPermissions = (initiativeId: number): Spec => ({
  guildExact: [`/api/v1/initiatives/${initiativeId}/my-permissions`],
});

const initiativeMembers = (initiativeId: number): Spec => ({
  guildExact: [`/api/v1/initiatives/${initiativeId}/members`],
});

// One prefix reaches every reader of the queue: the manager's list (keyed with
// its `status` filter), the requester's own `/me` rows, and any narrower status
// view — so a request or an answer never leaves one of them showing the old
// truth. The directory's own badge rides on `allInitiatives`.
const initiativeJoinRequests = (initiativeId: number): Spec => ({
  guildPrefix: [`/api/v1/initiatives/${initiativeId}/join-requests`],
});

// ── Settings (personal / platform) ───────────────────────────────────────────

// "All settings" is a blunt flush spanning two DELIBERATELY separate backend
// scopes: app/platform config (`/api/v1/settings/*`, owner-only) and a guild's
// AI settings (`/api/v1/g/{id}/settings/ai/*`, RLS-scoped). They live on
// different paths by design — app config isn't guild-specific, and guild AI
// settings must carry guild context — so name a bucket in each family rather
// than let one path test cross the boundary. (Not a backend inconsistency.)
const allSettings = (): Spec => ({
  personalPrefix: ["/api/v1/settings"],
  guildPrefix: ["/api/v1/settings"],
});

const interfaceSettings = (): Spec => ({ personalExact: ["/api/v1/settings/interface"] });

const emailSettings = (): Spec => ({ personalExact: ["/api/v1/settings/email"] });

const authSettings = (): Spec => ({ personalExact: ["/api/v1/settings/auth"] });

const authProviders = (): Spec => ({ personalExact: ["/api/v1/settings/auth/providers/"] });

const storageSettings = (): Spec => ({ personalExact: ["/api/v1/settings/storage"] });

// The community-directory switch is written under /settings but read from the
// SPA's boot config, so an owner's write has to reach the config key rather
// than a settings one.
const appConfig = (): Spec => ({ personalExact: ["/api/v1/config"] });

/** The owner's own read of the three community-wide decisions. */
const communitySettings = (): Spec => ({ personalExact: ["/api/v1/settings/community"] });

const oidcMappings = (): Spec => ({ personalPrefix: ["/api/v1/settings/oidc-mappings"] });

// The platform Guilds tab reads/writes only shared public tables (owner-only),
// so its list lives in the personal/platform family, not under any /g/ key.
const platformGuilds = (): Spec => ({ personalExact: ["/api/v1/settings/guilds"] });

// ── App services (personal / platform) ───────────────────────────────────────
// Orval keys the list as `/api/v1/app-services/` (trailing slash) and each row
// as `/api/v1/app-services/{id}` (no slash), so they are siblings rather than a
// prefix pair. Name the shared path so one description reaches the list and
// every detail read.
const appServices = (): Spec => ({ personalPrefix: ["/api/v1/app-services"] });

// ── Installed apps (guild) ───────────────────────────────────────────────────
// The other half of the same domain: a service is the platform's registration
// of an app, an install is one community's copy of it.
//
// One description for every read of an install, because one write moves all of
// them — the sidebar's list, the settings dialog's detail, the members view —
// and because the bus names the install guild-wide, with no parent to carry it.
// Two key shapes: the list is Orval's URL key, while the detail and members
// reads are hand-written and keyed by name. The named pair carries its guild in
// element 1, so it is scoped like every other guild key rather than by name.
const apps = (): Spec => ({
  guildPrefix: ["/api/v1/apps"],
  guildNamed: ["guild-app", "guild-app-members"],
});

// ── AI Settings (platform config is personal; guild/member/resolved are guild) ──

const allAISettings = (): Spec => ({
  personalPrefix: ["/api/v1/settings/ai"],
  guildPrefix: ["/api/v1/settings/ai"],
});

/** The platform owner's global mode + `allow_member_keys`. */
const platformAIMode = (): Spec => ({ personalExact: ["/api/v1/settings/ai/platform/mode"] });

/** The operator-defined connections list. */
const platformAIConnections = (): Spec => ({
  personalExact: ["/api/v1/settings/ai/platform/connections"],
});

/** A guild admin's own connections list (`/g/{id}/settings/ai/connections`). */
const guildAIConnections = (): Spec => ({ guildExact: ["/api/v1/settings/ai/connections"] });

/** The member's own view: selected connection, per-connection key state, on/off. */
const memberAI = (): Spec => ({ guildExact: ["/api/v1/settings/ai/me"] });

const resolvedAISettings = (): Spec => ({ guildExact: ["/api/v1/settings/ai/resolved"] });

// The cross-guild personal aggregate powering the "My AI" page (a flat `/me/ai`
// list across every guild the user belongs to) — personal, never guild-scoped.
const myAI = (): Spec => ({ personalExact: ["/api/v1/me/ai"] });

// ── Users / Admin (personal / platform) ──────────────────────────────────────

const currentUser = (): Spec => ({ personalExact: ["/api/v1/users/me"] });

const userStats = (): Spec => ({ personalPrefix: ["/api/v1/me/stats"] });

const adminUsers = (): Spec => ({ personalPrefix: ["/api/v1/admin"] });

// ── Guild Members (guild) ────────────────────────────────────────────────────
// The member roster is guild-scoped (`/api/v1/g/{id}/users/`), even though the
// membership *mutations* go through the platform `/api/v1/guilds/{id}/members/…`
// path. It must stay in the guild bucket.

const guildMembers = (): Spec => ({ guildExact: ["/api/v1/users/"] });

// ── Guilds (personal / platform) ─────────────────────────────────────────────

const allGuilds = (): Spec => ({ personalPrefix: ["/api/v1/guilds"] });

const guildInvites = (guildId: number): Spec => ({
  personalExact: [`/api/v1/guilds/${guildId}/invites`],
});

// ── Queues (guild) ───────────────────────────────────────────────────────────

const allQueues = (): Spec => ({ guildPrefix: ["/api/v1/queues"] });

const queue = (queueId: number): Spec => ({ guildExact: [`/api/v1/queues/${queueId}`] });

// ── Counter Groups (guild) ───────────────────────────────────────────────────

const allCounterGroups = (): Spec => ({ guildPrefix: ["/api/v1/counter-groups"] });

const counterGroup = (groupId: number): Spec => ({
  guildExact: [`/api/v1/counter-groups/${groupId}`],
});

// ── Calendars & Calendar Events (guild + me) ─────────────────────────────────

// The calendar-entries aggregate unions events + task markers; name it too so
// event mutations reflect on the calendar surfaces.
const allCalendarEntries = (): Spec => resourceAndMe("calendar-entries");

const allCalendarEvents = (): Spec =>
  compose(resourceAndMe("calendar-events"), allCalendarEntries());

const calendarEvent = (eventId: number): Spec => ({
  guildExact: [`/api/v1/calendar-events/${eventId}`],
});

// Calendar (the container) mutations also reach the events + entries views —
// renames/colors/sharing change what those surfaces show.
const allCalendars = (): Spec =>
  compose({ guildPrefix: ["/api/v1/calendars"] }, allCalendarEvents());

const calendar = (calendarId: number): Spec => ({
  guildExact: [`/api/v1/calendars/${calendarId}`],
});

// ── Dashboards (guild) ───────────────────────────────────────────────────────

const allDashboards = (): Spec => ({ guildPrefix: ["/api/v1/dashboards"] });

const dashboard = (dashboardId: number): Spec => ({
  guildExact: [`/api/v1/dashboards/${dashboardId}`],
});

// ── Posts (guild) ────────────────────────────────────────────────────────────

const allPosts = (): Spec => ({ guildPrefix: ["/api/v1/posts"] });

const post = (postId: number): Spec => ({ guildExact: [`/api/v1/posts/${postId}`] });

/**
 * The board's timeline rail only.
 *
 * Read state is patched into the post caches rather than refetched, because
 * refetching the feed mid-scroll moves rows under the cursor. The rail is a
 * separate, cheap aggregate — and with the unread filter on it is *made of*
 * read state, so leaving it alone would show months that have since emptied.
 * This names that one query and nothing else.
 */
const postTimeline = (): Spec => ({ guildPrefix: ["/api/v1/posts/timeline"] });

// ── Galleries (guild) ────────────────────────────────────────────────────────

const allGalleries = (): Spec => ({ guildPrefix: ["/api/v1/galleries"] });

const gallery = (galleryId: number): Spec => ({
  guildExact: [`/api/v1/galleries/${galleryId}`],
});

/** A gallery's pictures — every page of the list, the timeline rail, and
 *  each picture's own reads and versions — without the gallery row itself. */
const galleryImages = (galleryId: number): Spec => ({
  guildPrefix: [`/api/v1/galleries/${galleryId}/images`],
});

// ── Version (personal) ───────────────────────────────────────────────────────

const version = (): Spec => ({ personalExact: ["/api/v1/version"] });

const latestVersion = (): Spec => ({ personalExact: ["/api/v1/version/latest"] });

// ── Task Statuses (guild) ────────────────────────────────────────────────────

const allTaskStatuses = (): Spec => ({ guildPrefix: ["/api/v1/projects"] });

// ── Properties (guild) ───────────────────────────────────────────────────────

const allProperties = (): Spec => ({ guildPrefix: ["/api/v1/property-definitions"] });

// ── One tool entity (guild, cross-tool) ──────────────────────────────────────
// What every generic per-tool mutation — set tags, flip the comment switch —
// makes stale: that tool's list and detail queries. `Record<Tool, …>` so a new
// Tool member fails to compile until it declares its invalidation.

const TOOL_SPECS: Record<Tool, (id: number) => Spec> = {
  [Tool.project]: (id) => compose(project(id), allProjects()),
  [Tool.document]: (id) => compose(document(id), allDocuments()),
  [Tool.queue]: (id) => compose(queue(id), allQueues()),
  [Tool.counter_group]: (id) => compose(counterGroup(id), allCounterGroups()),
  [Tool.calendar]: (id) => compose(calendar(id), allCalendars()),
  [Tool.dashboard]: (id) => compose(dashboard(id), allDashboards()),
  [Tool.post]: (id) => compose(post(id), allPosts()),
  [Tool.gallery]: (id) => compose(gallery(id), allGalleries()),
};

const tool = (which: Tool, id: number): Spec => TOOL_SPECS[which](id);

// ── Everything this guild shows (cross-tool) ─────────────────────────────────
// Two callers, one description. Gaining (or losing) a membership row changes
// what the guild returns for every tool, not just the initiative list: the
// sidebar tree, the discovery directory, and each tool's guild-wide list all
// read differently afterwards. And a realtime frame for a write too large to
// name its rows one by one says so instead, and this is the answer.

const guildContent = (): Spec =>
  compose(
    allInitiatives(),
    allProjects(),
    allDocuments(),
    allQueues(),
    allCounterGroups(),
    allCalendars(),
    allDashboards(),
    allPosts(),
    allGalleries(),
    allTasks(),
    allComments()
  );

/** Every description, by name. The only export a call site needs beside `invalidate`. */
export const q = {
  adminUsers,
  allAISettings,
  allCalendarEntries,
  allCalendarEvents,
  allCalendars,
  allComments,
  allCounterGroups,
  allDashboards,
  allDocuments,
  allGalleries,
  allGuilds,
  allInitiatives,
  allPosts,
  allProjects,
  allProperties,
  allQueues,
  allSettings,
  allTags,
  allTaskStatuses,
  allTasks,
  announcements,
  appConfig,
  appServices,
  apps,
  authProviders,
  authSettings,
  calendar,
  calendarEvent,
  commentsOnResource,
  communitySettings,
  contactGrants,
  contacts,
  counterGroup,
  currentUser,
  dashboard,
  directMessages,
  dmSettings,
  document,
  documentComments,
  documentVersions,
  emailSettings,
  favoriteProjects,
  guildAIConnections,
  guildContent,
  guildInvites,
  guildMembers,
  ignoredAccounts,
  initiative,
  initiativeJoinRequests,
  initiativeMembers,
  initiativeRoles,
  interfaceSettings,
  latestVersion,
  memberAI,
  myAI,
  myPermissions,
  notifications,
  oidcMappings,
  platformAIConnections,
  platformAIMode,
  platformGuilds,
  gallery,
  galleryImages,
  post,
  postTimeline,
  project,
  projectActivity,
  projectFilterPresets,
  projectTaskStatuses,
  queue,
  recentComments,
  recents,
  relationships,
  resolvedAISettings,
  storageSettings,
  tag,
  tagEntities,
  task,
  taskComments,
  tool,
  toolComments,
  userStats,
  version,
  writableProjects,
};

// ── Guild Switch ─────────────────────────────────────────────────────────────
// Keys that are NOT guild-scoped and should survive a guild switch.
// `/api/v1/recents` is one of them: the recents bar is a cross-guild personal
// list, so switching community neither changes its contents nor invalidates
// them. Resetting it made the bar blank and refetch on every switch, dropping
// tabs that belong to the community being left as well as the one arriving.
const GLOBAL_KEY_PREFIXES = [
  "/api/v1/guilds",
  "/api/v1/users/me",
  "/api/v1/version",
  "/api/v1/recents",
];

/**
 * Remove guild-scoped query data so stale cross-guild results are never shown.
 *
 * `arrivingGuildId` names the guild being entered, and that guild's own keys
 * are left alone: they hold its data, not the departing guild's, so there is
 * nothing stale about them. Online this changes nothing observable — those
 * queries are stale on mount and refetch anyway — but it is the difference
 * between showing a cached page and showing an empty one when the device has
 * no connection to refetch from.
 */
export const resetGuildScopedQueries = (arrivingGuildId?: number | null) =>
  queryClient.resetQueries({
    predicate: (query) => {
      const first = query.queryKey[0];
      if (typeof first !== "string") return true;
      if (GLOBAL_KEY_PREFIXES.some((prefix) => first.startsWith(prefix))) return false;
      if (arrivingGuildId != null) {
        const match = GUILD_SEGMENT.exec(first);
        if (match && Number(match[1]) === arrivingGuildId) return false;
      }
      return true;
    },
  });

// ── Rewriting a cached post in place (not an invalidation) ───────────────────

type CachedPost = Record<string, unknown>;
type CachedPage = { items?: CachedPost[] };

/**
 * One page of posts, with this post rewritten. Returns the SAME object when
 * the page does not hold it, so the caches that do not change keep their
 * identity and the cards on them do not re-render.
 */
const patchPostPage = (
  page: unknown,
  postId: number,
  update: (post: CachedPost) => CachedPost
): unknown => {
  const asList = page as CachedPage;
  if (!Array.isArray(asList.items)) return page;
  if (!asList.items.some((item) => item.id === postId)) return page;
  return {
    ...asList,
    items: asList.items.map((item) => (item.id === postId ? update(item) : item)),
  };
};

/**
 * Rewrite one post wherever it is already cached, without refetching.
 *
 * Read state changes as somebody scrolls, and invalidating for it would refetch
 * the board mid-scroll — moving rows under the cursor, and with the unread
 * filter on, deleting the one being read. The server is already told; this is
 * only the copy on screen catching up.
 *
 * Three shapes hold a post, and the board is the one that is easy to miss: it
 * scrolls rather than pages, so its cache is an infinite query's
 * `{ pages: [...] }` rather than a single page of items. Patching only the
 * other two would leave every optimistic update invisible on the surface it
 * was made from.
 */
export const patchCachedPost = (postId: number, update: (post: CachedPost) => CachedPost) => {
  const matcher = merge([allPosts()]);
  queryClient.setQueriesData<unknown>(
    { predicate: (query) => matches(matcher, query.queryKey) },
    (data: unknown) => {
      if (!data || typeof data !== "object") return data;

      const asInfinite = data as { pages?: unknown[] };
      if (Array.isArray(asInfinite.pages)) {
        const pages = asInfinite.pages.map((page) => patchPostPage(page, postId, update));
        if (pages.every((page, index) => page === asInfinite.pages?.[index])) return data;
        return { ...asInfinite, pages };
      }

      const patched = patchPostPage(data, postId, update);
      if (patched !== data) return patched;

      const asPost = data as CachedPost;
      return asPost.id === postId ? update(asPost) : data;
    }
  );
};
