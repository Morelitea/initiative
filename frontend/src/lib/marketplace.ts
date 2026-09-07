import { ListingKind } from "@/api/generated/initiativeAPI.schemas";

/**
 * Which marketplace offers a listing.
 *
 * Every kind but one installs to a **community** — a dashboard lands in an
 * initiative, an app mounts in a community, and installing is something a
 * community's admins do. A profile pack installs to a **person**: its
 * decorations land in one account's library and belong to that person across
 * every community they are in.
 *
 * That is why there are two marketplaces rather than one with a filter. They
 * have different shelves, different buyers and different answers to "do I
 * already have this" — a community's install is shared, a person's is theirs.
 *
 * Mirrors ``KIND_AUDIENCE`` in ``backend/app/services/marketplace/
 * definitions.py``, which is the source of truth; a kind missing from both
 * lists here is offered by neither, which the test below refuses.
 */
export const USER_SHELVES = [ListingKind.profile_pack] as const;

export const COMMUNITY_SHELVES = [
  ListingKind.dashboard,
  ListingKind.app,
  ListingKind.auto,
] as const;

/** A shelf a community installs from — the values `?kind=` may name under
 *  `/c/{id}/marketplace`. Derived from the list above so a shelf added there is
 *  a shelf the URL accepts, with nothing else to update. */
export type CommunityShelf = (typeof COMMUNITY_SHELVES)[number];

/** Where the community marketplace opens when the URL names no shelf, and what
 *  a `kind` it does not sell normalizes to. */
export const DEFAULT_COMMUNITY_SHELF: CommunityShelf = ListingKind.dashboard;

const LISTING_KINDS: ReadonlySet<string> = new Set(Object.values(ListingKind));
const COMMUNITY_SHELF_KINDS: ReadonlySet<string> = new Set(COMMUNITY_SHELVES);
const USER_SHELF_KINDS: ReadonlySet<string> = new Set(USER_SHELVES);

const isListingKind = (value: unknown): value is ListingKind =>
  typeof value === "string" && LISTING_KINDS.has(value);

const isCommunityShelf = (value: unknown): value is CommunityShelf =>
  typeof value === "string" && COMMUNITY_SHELF_KINDS.has(value);

/**
 * A `kind` URL param as the kind the server named, or undefined when it names
 * none.
 *
 * Both marketplace routes read `kind` through this rather than each spelling
 * out the values it accepts: the enum the API generates is the list, so a kind
 * added server-side is one the URL understands as soon as the types are
 * regenerated.
 */
export const parseListingKind = (value: unknown): ListingKind | undefined =>
  isListingKind(value) ? value : undefined;

/** The same, narrowed to what a community's marketplace sells. Anything else —
 *  a person's shelf, a typo, nothing at all — opens the default shelf. */
export const parseCommunityShelf = (value: unknown): CommunityShelf =>
  isCommunityShelf(value) ? value : DEFAULT_COMMUNITY_SHELF;

/** Whether this kind is bought by a person rather than by a community. */
export const isUserShelf = (kind: ListingKind): boolean => USER_SHELF_KINDS.has(kind);
