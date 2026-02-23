/**
 * Base props shared by all modal/dialog components.
 */
export interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Dialog that reports a success action back to its parent.
 * Used by dialogs that perform a mutation (create, edit, delete, etc.).
 */
export interface DialogWithSuccessProps extends DialogProps {
  onSuccess: () => void;
}
