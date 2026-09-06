/**
 * What a notice may be, mirrored from the server.
 *
 * The backend is the authority — `app/schemas/tenant/post.py` holds the same
 * number and the endpoint refuses anything over it. This copy exists so the
 * composer can show a remaining count while somebody types, rather than
 * letting them finish and then rejecting the whole thing.
 */
export const MAX_POST_TEXT_CHARS = 10_000;
