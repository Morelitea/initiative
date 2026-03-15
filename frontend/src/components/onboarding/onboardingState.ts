/**
 * Module-level callback for triggering the onboarding tour restart
 * from anywhere in the app (e.g., settings page) without prop drilling.
 * Follows the same pattern as CommandCenter.tsx.
 */
let tourRestartCallback: (() => void) | null = null;

export function setTourRestartCallback(cb: (() => void) | null) {
  tourRestartCallback = cb;
}

export function triggerTourRestart() {
  tourRestartCallback?.();
}
