import { useCallback, useState } from "react";

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
   * Go back to following the server, having saved. Pass what was sent and it
   * only takes effect while the fields still hold it — a save that started
   * before the last keystroke must not mark that keystroke saved.
   */
  settle: (saved?: Partial<V>) => void;
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

  const settle = useCallback((saved?: Partial<V>) => {
    setState((previous) => {
      if (!previous.edited) return previous;
      const stillHolds =
        !saved ||
        (Object.keys(saved) as (keyof V)[]).every((key) =>
          sameField(previous.values[key], saved[key])
        );
      return stillHolds ? { ...previous, edited: false } : previous;
    });
  }, []);

  return { values: state.values, set, edited: state.edited, settle };
}
