/**
 * Derive the active tab from the current pathname using longest-path-first,
 * exact-or-prefix matching. Shared by the settings/admin tabbed layouts.
 *
 * @param tabs Tab descriptors carrying the `path` each tab maps to.
 * @param normalizedPath The current pathname, trailing slashes already trimmed.
 * @param fallback The tab value to use when nothing matches.
 */
export function matchActiveTab(
  tabs: readonly { value: string; path: string }[],
  normalizedPath: string,
  fallback: string
): string {
  return (
    [...tabs]
      .sort((a, b) => b.path.length - a.path.length)
      .find((tab) => normalizedPath === tab.path || normalizedPath.startsWith(`${tab.path}/`))
      ?.value ?? fallback
  );
}
