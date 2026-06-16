/**
 * Strict allowlist URL handling for editor links.
 *
 * Documents are cross-user stored content, so a link URL persisted by one user
 * is later rendered (and potentially opened) in another user's browser. To
 * prevent stored XSS via `javascript:`/`data:`/`vbscript:` URLs, every link URL
 * MUST be routed through `sanitizeUrl` at each choke point: on import/render,
 * before `window.open`, and before it is stored via TOGGLE_LINK_COMMAND.
 *
 * `validateUrl` is the gate Lexical uses to decide whether a typed/pasted string
 * may become a link at all; it is anchored and protocol-allowlisted so a
 * dangerous scheme can never be stored in the first place.
 */

// Protocols that are safe to navigate to. Anything else is neutralized.
const SUPPORTED_URL_PROTOCOLS = new Set(["http:", "https:", "mailto:", "sms:", "tel:"]);

// Inert destination used to neutralize a disallowed URL.
const SAFE_URL = "about:blank";

/**
 * Matches a string that begins with an explicit URL scheme (e.g. `javascript:`,
 * `http:`, `data:`). Follows the RFC 3986 scheme grammar:
 * ALPHA *( ALPHA / DIGIT / "+" / "-" / "." ) ":".
 */
const SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i;

/**
 * Relative references are always safe — they cannot carry a dangerous scheme.
 * Covers root-relative (`/path`), fragment (`#anchor`), current-dir (`./x`,
 * `../x`), and query-only (`?q=1`) forms.
 */
const RELATIVE_REFERENCE_RE = /^[/#.?]/;

/**
 * Removes ASCII whitespace and C0/DEL control characters (code points <= 0x20
 * and 0x7f) from a URL string. Browsers ignore these while resolving a scheme,
 * so `java\tscript:` and `java\nscript:` both execute as `javascript:`. We strip
 * them before the scheme check so obfuscated schemes can't slip past the
 * protocol allowlist.
 */
function stripControlChars(value: string): string {
  let result = "";
  for (const char of value) {
    const code = char.codePointAt(0) ?? 0;
    if (code > 0x20 && code !== 0x7f) {
      result += char;
    }
  }
  return result;
}

/**
 * Routes any link URL through a strict protocol allowlist.
 *
 * - Relative references pass through unchanged.
 * - Protocol-less strings (bare domains like `example.com/x`) pass through; the
 *   caller (Lexical's formatUrl / our matchers) prepends a safe scheme.
 * - Absolute URLs whose protocol is in the allowlist pass through unchanged.
 * - Everything else — including strings that carry an explicit but disallowed
 *   scheme (`javascript:alert(1)`, `data:...`) or that fail to parse — is
 *   neutralized to `about:blank`.
 *
 * This is the single sanitizer applied at every choke point (import/render,
 * before window.open, before storage).
 */
export function sanitizeUrl(url: string): string {
  const trimmed = url.trim();

  if (trimmed === "") {
    return SAFE_URL;
  }

  // The link-insertion UI initialises new links with this placeholder before
  // the user types a real URL (see validateUrl's matching carve-out + TODO).
  // It is inert — allowlisted scheme with no host, so nothing can navigate to
  // it — but `new URL("https://")` throws, which would fail closed to
  // about:blank and let the node transform rewrite the link mid-insertion.
  if (trimmed === "https://") {
    return trimmed;
  }

  // Relative references can never carry a dangerous scheme. Test the original
  // trimmed value so a benign leading "/" or "#" is preserved verbatim.
  if (RELATIVE_REFERENCE_RE.test(trimmed)) {
    return trimmed;
  }

  // Browsers ignore embedded control/whitespace chars when resolving a scheme,
  // so evaluate the scheme against a stripped copy to defeat obfuscation
  // (e.g. "java\tscript:alert(1)").
  const stripped = stripControlChars(trimmed);

  // No explicit scheme: a bare relative reference (e.g. "example.com/foo").
  // Safe to leave as-is — there is no protocol to exploit.
  if (!SCHEME_RE.test(stripped)) {
    return trimmed;
  }

  try {
    const parsedUrl = new URL(stripped);
    if (!SUPPORTED_URL_PROTOCOLS.has(parsedUrl.protocol)) {
      return SAFE_URL;
    }
    // Scheme is allowlisted; return the original (un-stripped) URL so legitimate
    // encoded content is preserved.
    return trimmed;
  } catch {
    // Has an explicit scheme but failed to parse as an absolute URL.
    // Fail closed: a dangerous scheme must never slip through.
    return SAFE_URL;
  }
}

// Anchored URL matcher used by validateUrl. It requires the WHOLE string to be
// one of: an allowlisted absolute URL (http/https/mailto/tel/sms), a
// "www."/email-prefixed host, or a bare domain with a path. It can NOT match a
// `javascript:`/`data:`/`vbscript:` prefix because the only scheme alternative
// permits http/https/mailto/tel/sms.
const urlRegExp = new RegExp(
  /^(?:(?:https?|mailto|tel|sms):[^\s]+|(?:www\.|[-;:&=+$,\w]+@)[A-Za-z0-9.-]+(?:\/[^\s]*)?|[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:\/[^\s]*)?)$/i
);

// Explicit deny list. Redundant with the anchored allowlist above, but documents
// intent and guards against future regex edits that might loosen the matcher.
const DANGEROUS_SCHEME_RE = /^(?:javascript|data|vbscript|file|blob):/i;

export function validateUrl(url: string): boolean {
  const trimmed = url.trim();

  // Allow hash-only links for heading anchors (e.g. #some-heading)
  if (trimmed.startsWith("#") && trimmed.length > 1) {
    return true;
  }

  // Never permit a dangerous scheme to be stored as a link. Strip embedded
  // control/whitespace chars first so obfuscated schemes are still caught.
  if (DANGEROUS_SCHEME_RE.test(stripControlChars(trimmed))) {
    return false;
  }

  // TODO Fix UI for link insertion; it should never default to an invalid URL such as https://.
  // Maybe show a dialog where the user can type the URL before inserting it.
  return trimmed === "https://" || urlRegExp.test(trimmed);
}
