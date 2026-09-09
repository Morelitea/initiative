import { useCallback, useRef, useState } from "react";

/** Fields, compared as deep as a form's values go: values, or values in a list. */
const sameField = (a: unknown, b: unknown): boolean =>
  Array.isArray(a) && Array.isArray(b)
    ? a.length === b.length && a.every((item, index) => Object.is(item, b[index]))
    : Object.is(a, b);

const sameFields = <V extends object>(a: V, b: V): boolean => {
  const keys = Object.keys(a) as (keyof V)[];
  return keys.length === Object.keys(b).length && keys.every((key) => sameField(a[key], b[key]));
};

export interface ServerForm<V> {
  values: V;
  /** Change fields, and mark the form as holding unsaved work. */
  set: (patch: Partial<V> | ((previous: V) => Partial<V>)) => void;
  edited: boolean;
  /**
   * Go back to following the server, having saved what this says was sent.
   * It only takes effect while the fields still hold that: a save is a round
   * trip, and anything typed during one has not been saved by it. Judged by
   * the same equality the form is compared with, so a form whose values are
   * deeper than fields settles on the same terms it adopts on.
   *
   * Required rather than optional because the version that guesses is wrong
   * every time somebody is quick.
   */
  settle: (saved: V) => void;
}

interface State<V> {
  seeded: V;
  editing: unknown;
  values: V;
  edited: boolean;
}

/**
 * Form fields filled in from the server, which a later answer may correct but
 * not overwrite: refetches are not something the reader asked for, and one
 * landing mid-sentence used to take the sentence away.
 *
 * For fields behind a Save button. Anything written the moment it changes — a
 * tag picker, a switch — should keep following the server instead.
 *
 * @param source The loaded entity, or undefined while it is still coming.
 * @param derive This form's fields. Called every render and compared field by
 *   field, so give every field a value, keep each a string, number, boolean or
 *   list of those, and keep it free of anything that differs per call (a
 *   random default belongs outside the form). Deeper values need `same`.
 * @param editing What is being edited — the entity's id, and for a dialog
 *   whether it is open (`[open, item?.id]`). When this changes the fields are
 *   filled in afresh, unsaved or not: it is a different thing, or a new sitting
 *   at the same one, and last time's typing does not belong to it.
 * @param same When the values are deeper than the field rule above, or when
 *   equality is the form's own question (an order that does not count as a
 *   change), the projection that answers it.
 */
export function useServerForm<S, V extends object>(
  source: S | undefined,
  derive: (source: S | undefined) => V,
  editing: unknown,
  same: (a: V, b: V) => boolean = sameFields
): ServerForm<V> {
  const fromServer = derive(source);
  // Read through a ref so settling uses the current comparison without the
  // callback changing identity when it is passed inline.
  const sameRef = useRef(same);
  sameRef.current = same;
  const [state, setState] = useState<State<V>>(() => ({
    seeded: fromServer,
    editing,
    values: fromServer,
    edited: false,
  }));

  if (!sameField(editing, state.editing)) {
    setState({ seeded: fromServer, editing, values: fromServer, edited: false });
  } else if (!same(fromServer, state.seeded)) {
    // The same thing, said differently. Comparing the fields rather than the
    // answer they came from means a rebuilt but equal object is not news.
    setState((previous) => ({
      ...previous,
      seeded: fromServer,
      ...(previous.edited ? null : { values: fromServer }),
    }));
  }

  const set: ServerForm<V>["set"] = useCallback((patch) => {
    setState((previous) => ({
      ...previous,
      values: {
        ...previous.values,
        ...(typeof patch === "function" ? patch(previous.values) : patch),
      },
      edited: true,
    }));
  }, []);

  const settle = useCallback((saved: V) => {
    setState((previous) =>
      previous.edited && sameRef.current(previous.values, saved)
        ? { ...previous, edited: false }
        : previous
    );
  }, []);

  return { values: state.values, set, edited: state.edited, settle };
}
