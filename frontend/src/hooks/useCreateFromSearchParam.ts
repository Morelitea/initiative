import { useRouter, useSearch } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

type Options = {
  /** Called when the dialog opens from `?create=true`, with any `?initiativeId`. */
  onOpenFromUrl?: (urlInitiativeId?: string) => void;
  /** Called whenever the dialog closes (whether opened from the URL or a button). */
  onClose?: () => void;
};

/**
 * The "open a create dialog from `?create=true`" behavior every tool list page
 * needs, in one place: open the dialog when the param is present, and strip the
 * param (without immediately re-opening) once the dialog closes.
 *
 * Returns the `open`/`onOpenChange` a dialog binds to, plus `setOpen` for
 * header/empty-state "New X" buttons. Alias them to a page's existing names to
 * drop in with no other changes, e.g.
 * `const { open: createOpen, setOpen: setCreateOpen, onOpenChange } = useCreateFromSearchParam()`.
 */
export function useCreateFromSearchParam(options?: Options) {
  const router = useRouter();
  const search = useSearch({ strict: false }) as { create?: string; initiativeId?: string };
  const [open, setOpen] = useState(false);
  // Prevents the close → clear-param → effect chain from re-opening the dialog.
  const isClosing = useRef(false);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  useEffect(() => {
    const shouldCreate = search.create === "true";
    if (shouldCreate && !open && !isClosing.current) {
      setOpen(true);
      optionsRef.current?.onOpenFromUrl?.(search.initiativeId);
    }
    if (!shouldCreate) {
      isClosing.current = false;
    }
  }, [search, open]);

  const onOpenChange = (next: boolean) => {
    setOpen(next);
    if (next) return;
    optionsRef.current?.onClose?.();
    if (search.create) {
      isClosing.current = true;
      void router.navigate({ to: ".", search: { ...search, create: undefined }, replace: true });
    }
  };

  return { open, setOpen, onOpenChange };
}
