import { type Dispatch, type SetStateAction, useEffect, useState } from "react";

/**
 * Default "filters panel open" state for list surfaces: open on screens ≥ 640px,
 * collapsed below. SSR-safe — defaults to open when there is no window to measure.
 */
export const getDefaultFiltersVisibility = (): boolean => {
  if (typeof window === "undefined") {
    return true;
  }
  return window.matchMedia("(min-width: 640px)").matches;
};

/**
 * Filters-panel open state that initializes from the viewport width and stays in
 * sync with it: subscribes to the 640px media query and mirrors `matches` into
 * state. Returns a `[open, setOpen]` tuple like `useState`, so callers can still
 * toggle it manually.
 */
export const useDefaultFiltersOpen = (): [boolean, Dispatch<SetStateAction<boolean>>] => {
  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const mediaQuery = window.matchMedia("(min-width: 640px)");
    const handleChange = (event: MediaQueryListEvent) => {
      setFiltersOpen(event.matches);
    };
    setFiltersOpen(mediaQuery.matches);
    if (typeof mediaQuery.addEventListener === "function") {
      mediaQuery.addEventListener("change", handleChange);
      return () => mediaQuery.removeEventListener("change", handleChange);
    }
    mediaQuery.addListener(handleChange);
    return () => mediaQuery.removeListener(handleChange);
  }, []);

  return [filtersOpen, setFiltersOpen];
};
