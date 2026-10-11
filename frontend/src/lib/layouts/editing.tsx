import { type FocusEvent, type KeyboardEvent, type ReactNode, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

/** Where one field's save stands. */
export type FieldSaveState = "idle" | "saving" | "saved" | "error";

/** What a field shows of its own save, and how to send it again. */
export interface FieldSave {
  state: FieldSaveState;
  retry: () => void;
}

// The inputs a value is typed into, as against picked with. A combobox's
// search box is typed into too, but what it changes is a pick.
const TYPED_INPUTS = new Set([
  "text",
  "number",
  "url",
  "email",
  "search",
  "tel",
  "date",
  "time",
  "datetime-local",
]);

/** Whether an element is one a value is typed into. */
export const isTyping = (element: EventTarget | null): boolean =>
  element instanceof HTMLTextAreaElement ||
  (element instanceof HTMLInputElement &&
    TYPED_INPUTS.has(element.type) &&
    element.getAttribute("role") !== "combobox");

interface Draft<V> {
  value: V;
  /** The saved value when the change began. */
  from: V;
  saving: boolean;
}

export interface FieldDraft<V> {
  /** What the field shows: the change in progress, or the saved value. */
  value: V;
  /** Hold a typed change until Enter or leaving the field. */
  change: (value: V) => void;
  /** Save what is held, when it differs from the saved value. */
  finish: () => void;
  /** Put the saved value back. */
  restore: () => void;
  /** A change from the field's editor: a pick saves at once, typing waits. */
  edit: (value: V) => void;
  /** The saved value moved while this one was being changed. */
  changed: boolean;
  /** For the element around the editor: Enter in a typed input or leaving it
   *  saves, and Esc puts the saved value back. */
  keys: {
    onBlur: (event: FocusEvent) => void;
    onKeyDown: (event: KeyboardEvent) => void;
  };
}

/**
 * One field's value while it is being changed, saved by the kind of change:
 * a pick the moment it is made, typing on Enter or on leaving the field.
 *
 * What was saved stays shown until the save settles, so the field never shows
 * the old value in between; anything typed meanwhile is kept. A save that
 * fails puts the saved value back, and the field says so.
 *
 * @param saved The value as the item has it now.
 * @param commit Saves a value, settling when the save does. It is given the
 *   saved value the change began from, for a save that names what it was
 *   written over.
 * @param same When a value is not compared by identity.
 * @param valid Held back from saving while false, as dates the wrong way round.
 */
export const useFieldDraft = <V,>(
  saved: V,
  commit: (value: V, from: V) => Promise<unknown>,
  same: (a: V, b: V) => boolean = Object.is,
  valid: (value: V) => boolean = () => true
): FieldDraft<V> => {
  const [draft, setDraft] = useState<Draft<V> | null>(null);
  // Read by the handlers rather than the render, as two can run in one event:
  // a picker that commits on Enter, then the Enter itself.
  const held = useRef(draft);
  const set = (next: Draft<V> | null) => {
    held.current = next;
    setDraft(next);
  };

  const change = (value: V) => {
    const current = held.current;
    set({ value, from: current && !current.saving ? current.from : saved, saving: false });
  };
  const restore = () => set(null);
  const finish = () => {
    const current = held.current;
    if (!current || current.saving || !valid(current.value)) return;
    if (same(current.value, saved)) {
      restore();
      return;
    }
    const saving = { ...current, saving: true };
    set(saving);
    void commit(current.value, current.from).finally(() => {
      if (held.current === saving) set(null);
    });
  };

  return {
    value: draft ? draft.value : saved,
    change,
    finish,
    restore,
    edit: (value) => {
      change(value);
      if (!isTyping(document.activeElement)) finish();
    },
    changed: draft !== null && !draft.saving && !same(draft.from, saved),
    keys: {
      onBlur: (event) => {
        if (isTyping(event.target)) finish();
      },
      onKeyDown: (event) => {
        if (!isTyping(event.target)) return;
        if (event.key === "Enter" && !(event.target instanceof HTMLTextAreaElement)) {
          event.preventDefault();
          finish();
        } else if (event.key === "Escape") {
          restore();
        }
      },
    },
  };
};

const FieldSaveStatus = ({ save }: { save: FieldSave }) => {
  const { t } = useTranslation("common");
  if (save.state === "error") {
    return (
      <span
        role="alert"
        className="ml-auto inline-flex items-center gap-1 text-destructive text-xs"
      >
        {t("fieldSave.failed")}
        <Button
          type="button"
          variant="link"
          size="sm"
          className="h-auto p-0 text-xs"
          onClick={save.retry}
        >
          {t("tryAgain")}
        </Button>
      </span>
    );
  }
  return (
    <span role="status" className="ml-auto text-muted-foreground text-xs">
      {save.state === "saving" ? t("fieldSave.saving") : null}
      {save.state === "saved" ? t("fieldSave.saved") : null}
    </span>
  );
};

/**
 * One field on a detail: its label, its own save state with Retry, a
 * note when it changed underneath an edit, and the editor.
 *
 * A field whose label is hidden has no row for its save state, so the state
 * floats instead, where it moves nothing: level with the top of the editor
 * (beside a label the editor draws itself), or just under it.
 */
export const FieldFrame = ({
  label,
  htmlFor,
  save,
  changed = false,
  keys,
  hideLabel = false,
  statusBelow = false,
  action,
  className,
  children,
}: {
  label: string;
  htmlFor?: string;
  save: FieldSave;
  changed?: boolean;
  keys?: FieldDraft<unknown>["keys"];
  hideLabel?: boolean;
  /** With the label hidden, the save state sits under the editor. */
  statusBelow?: boolean;
  /** Beside the label. */
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) => {
  const { t } = useTranslation("common");
  return (
    <fieldset aria-label={label} className={cn("relative min-w-0 space-y-2", className)} {...keys}>
      {hideLabel ? (
        <>
          <Label htmlFor={htmlFor} className="sr-only">
            {label}
          </Label>
          <div
            className={cn(
              "absolute right-0 flex h-5 items-center",
              statusBelow ? "top-full mt-2" : "-top-0.5"
            )}
          >
            <FieldSaveStatus save={save} />
          </div>
        </>
      ) : (
        <div className="flex min-h-5 items-center gap-2">
          <Label htmlFor={htmlFor}>{label}</Label>
          {action}
          <FieldSaveStatus save={save} />
        </div>
      )}
      {children}
      {changed ? (
        <p role="status" className="text-muted-foreground text-xs">
          {t("fieldSave.changed")}
        </p>
      ) : null}
    </fieldset>
  );
};
