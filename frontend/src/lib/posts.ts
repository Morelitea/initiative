/**
 * What a notice may be, mirrored from the server.
 *
 * The backend is the authority — `app/schemas/tenant/post.py` holds the same
 * number and the endpoint refuses anything over it. This copy exists so the
 * composer can show a remaining count while somebody types, rather than
 * letting them finish and then rejecting the whole thing.
 */
export const MAX_POST_TEXT_CHARS = 10_000;

/**
 * How many choices a poll may offer, and how long each may be — mirrored from
 * `app/models/tenant/post_poll.py` for the same reason the length above is:
 * the composer has to stop offering "add a choice" at the ceiling rather than
 * letting somebody write an eleventh and have the save refused.
 */
export const MIN_POLL_OPTIONS = 2;
export const MAX_POLL_OPTIONS = 10;
export const MAX_POLL_OPTION_CHARS = 200;

/**
 * Whether a stored body is something an editor can be handed.
 *
 * A notice may be only a headline — and, now, only a headline and a poll — and
 * that is stored as an empty object. Lexical refuses an editor state whose root
 * has no children, so an empty object is not "an empty document" to it: it is a
 * crash. Every surface that mounts an editor over a post asks this first, and
 * either renders nothing or lets the editor build its own empty document.
 */
export const hasBody = (body: unknown): boolean =>
  Boolean(body) && typeof body === "object" && Object.keys(body as object).length > 0;

/**
 * The instant a board sorts a notice by — the client's side of the server's
 * `board_time()`.
 *
 * Its publication for a live notice; for a draft, which only its writers see,
 * the time it is due, so a scheduled notice previews where it will land. The
 * moment it was written is the floor. Written here rather than inline so the
 * feed, the timeline rail and anything else that groups notices by date cannot
 * disagree with the order the server sent them in.
 */
export const postBoardTime = (post: {
  published_at?: string | null;
  scheduled_for?: string | null;
  created_at: string;
}): string => post.published_at ?? post.scheduled_for ?? post.created_at;

/** The `YYYY-MM` a notice falls in, in the reader's own zone — the same
 *  boundary the timeline endpoint cuts its months on. */
export const postPeriod = (post: Parameters<typeof postBoardTime>[0]): string => {
  const at = new Date(postBoardTime(post));
  return `${at.getFullYear()}-${String(at.getMonth() + 1).padStart(2, "0")}`;
};
