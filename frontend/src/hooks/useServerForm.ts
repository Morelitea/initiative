import { useCallback, useState } from "react";

/**
 * Form fields seeded from something the server said, which a later answer may
 * correct but never overwrite.
 *
 * Every settings form here reads the same way: local state per field, and an
 * effect that copies the loaded entity into all of them whenever that entity
 * changes. Refetching is not something the reader asks for — a realtime signal
 * about the thing being edited, a window brought back to the front, another
 * query's mutation — so that effect lands on half-written text, and used to
 * replace it.
 *
 * The rule here is the one `TaskEditPage` arrived at on its own: a new answer
 * is adopted while nothing is unsaved, and ignored once something is. It reads
 * the new value either way, so a form left alone goes on tracking the server,
 * and a form being typed in is left alone until it is saved.
 *
 * This is for fields behind a Save button. Anything written the moment it is
 * changed — a tag picker, a switch — should keep following the server, because
 * there the server is the truth and the local copy is only the preview.
 *
 * ```ts
 * const form = useServerForm(entity, (e) => ({
 *   name: e?.name ?? "",
 *   description: e?.description ?? "",
 * }));
 *
 * <Input value={form.values.name} onChange={(e) => form.set({ name: e.target.value })} />
 * <Button onClick={() => save(form.values, { onSuccess: form.settle })}>Save</Button>
 * ```
 */
export interface ServerForm<V> {
  /** What the fields currently hold — the server's answer, or what was typed over it. */
  values: V;
  /** Change one or more fields. Marks the form as holding unsaved work. */
  set: (patch: Partial<V>) => void;
  /** Whether anything has been typed and not yet saved. */
  edited: boolean;
  /**
   * The typed values are the server's now — call this when a save succeeds, so
   * the form goes back to following later answers.
   */
  settle: () => void;
}

interface State<V> {
  /** The values last read off the server, to notice when they move. */
  seeded: V;
  values: V;
  edited: boolean;
}

/**
 * One field's worth of comparison: the value itself, or the values in it when
 * the field is a list (a set of chosen ids is rebuilt on every render, so
 * comparing the list objects would read as news every time).
 */
const sameField = (a: unknown, b: unknown): boolean => {
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((item, index) => Object.is(item, b[index]));
  }
  return Object.is(a, b);
};

/** Field by field, which is as deep as a form's values go. */
const sameFields = <V extends object>(a: V, b: V): boolean => {
  const keys = Object.keys(a) as (keyof V)[];
  if (keys.length !== Object.keys(b).length) return false;
  return keys.every((key) => sameField(a[key], b[key]));
};

/**
 * @param source The loaded entity, or `undefined` while it is still coming.
 * @param derive The fields this form holds, read off that entity. Called on
 *   every render and compared field by field, so give every field a value —
 *   including before the entity lands. A field may be a string, number,
 *   boolean, or a list of those; anything deeper is compared by identity and
 *   would read as news on every render.
 */
export function useServerForm<S, V extends object>(
  source: S | undefined,
  derive: (source: S | undefined) => V
): ServerForm<V> {
  const fromServer = derive(source);
  const [state, setState] = useState<State<V>>(() => ({
    seeded: fromServer,
    values: fromServer,
    edited: false,
  }));

  // What the server says has moved since these fields were filled in. Comparing
  // the fields rather than the answer they came from means a re-render that
  // rebuilds an equal object is not mistaken for news.
  if (!sameFields(fromServer, state.seeded)) {
    setState((previous) =>
      previous.edited
        ? // Note it as seen, so the next render is not asked about it again,
          // and leave the unsaved work alone.
          { ...previous, seeded: fromServer }
        : { seeded: fromServer, values: fromServer, edited: false }
    );
  }

  const set = useCallback((patch: Partial<V>) => {
    setState((previous) => ({
      ...previous,
      values: { ...previous.values, ...patch },
      edited: true,
    }));
  }, []);

  const settle = useCallback(() => {
    setState((previous) => (previous.edited ? { ...previous, edited: false } : previous));
  }, []);

  return { values: state.values, set, edited: state.edited, settle };
}
