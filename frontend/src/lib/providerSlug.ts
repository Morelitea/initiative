/**
 * What a sign-in provider's slug may be.
 *
 * Mirrors the backend's `validate_provider_slug`: lowercase ASCII letters,
 * digits, and inner dashes. Checked here so the answer arrives while somebody
 * is still typing rather than as a 422 after they submit — the server is still
 * what decides.
 *
 * An explicit character set rather than a pattern, so what is allowed reads
 * off the line.
 */

const SLUG_CHARS = new Set("abcdefghijklmnopqrstuvwxyz0123456789-");

export const isValidProviderSlug = (value: string): boolean =>
  value.length >= 1 &&
  value.length <= 64 &&
  [...value].every((char) => SLUG_CHARS.has(char)) &&
  !value.startsWith("-") &&
  !value.endsWith("-");
