/**
 * Module-level callback for triggering the PM tour start
 * from the main onboarding tour (or anywhere else) without prop drilling.
 */
let pmTourStartCallback: ((startStep?: number) => void) | null = null;

export function setPmTourStartCallback(cb: ((startStep?: number) => void) | null) {
  pmTourStartCallback = cb;
}

export function triggerPmTourStart(startStep?: number) {
  pmTourStartCallback?.(startStep);
}
