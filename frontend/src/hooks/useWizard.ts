/**
 * Which step of a multi-step dialog is showing, and how to get back.
 *
 * The step a wizard is on is the easy part; where Back goes is the part every
 * one of these dialogs used to answer for itself, by restating its own step
 * order in a ternary next to the render. That restatement is a second copy of
 * the graph, and the two drift.
 *
 * So the trail is kept instead: `go` pushes the step you are leaving, `back`
 * pops it. Where Back goes is then a fact about the route somebody actually
 * walked rather than a rule somebody wrote down, which is what makes it
 * correct for a wizard that branches.
 *
 * `commit` is the other half. Some steps are arrived at and not left — an
 * upload that has staged a job on the server, a run in progress, a final
 * report. Committing to one drops the trail, so `canGoBack` answers false and
 * the shell draws no Back row, without the render site restating which steps
 * those are.
 *
 * The four callbacks are stable; the returned object is a fresh literal each
 * render. Destructure it (`const { step, go, back } = useWizard("pick")`) and
 * depend on the callbacks.
 */

import { useCallback, useState } from "react";

interface WizardState<S> {
  step: S;
  trail: S[];
}

export interface Wizard<S extends string> {
  step: S;
  /** Walk forward to `next`. `back()` returns to the step you left. */
  go: (next: S) => void;
  /** Walk to `next` and drop the trail: `back()` becomes a no-op there. */
  commit: (next: S) => void;
  /** Return to the previous step. Does nothing on an empty trail. */
  back: () => void;
  canGoBack: boolean;
  /** The first step, empty trail — what closing the dialog does. */
  reset: () => void;
}

export function useWizard<S extends string>(initial: S): Wizard<S> {
  const [state, setState] = useState<WizardState<S>>({ step: initial, trail: [] });

  const go = useCallback(
    (next: S) => setState((prev) => ({ step: next, trail: [...prev.trail, prev.step] })),
    []
  );

  const commit = useCallback((next: S) => setState({ step: next, trail: [] }), []);

  const back = useCallback(
    () =>
      setState((prev) =>
        prev.trail.length === 0
          ? prev
          : { step: prev.trail[prev.trail.length - 1], trail: prev.trail.slice(0, -1) }
      ),
    []
  );

  const reset = useCallback(() => setState({ step: initial, trail: [] }), [initial]);

  return {
    step: state.step,
    go,
    commit,
    back,
    canGoBack: state.trail.length > 0,
    reset,
  };
}
