import { useEffect, useState } from "react";

/**
 * Subscribe to a CSS media query. SSR-safe: reports `false` when there is no
 * `window` to measure, then corrects on the first client effect.
 */
export const useMediaQuery = (query: string): boolean => {
  const [matches, setMatches] = useState(() => {
    if (typeof window === "undefined") {
      return false;
    }
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const mediaQuery = window.matchMedia(query);
    const handleChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    setMatches(mediaQuery.matches);
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [query]);

  return matches;
};

/**
 * Below Tailwind's `sm` breakpoint — the width at which list surfaces trade
 * their inline filter panel for a sheet and drop control labels for icons.
 * Keyed to the same 640px value the `sm:` classes use, so the JS and the CSS
 * can't disagree about which layout is showing.
 */
export const useIsCompactViewport = (): boolean => useMediaQuery("(max-width: 639px)");
