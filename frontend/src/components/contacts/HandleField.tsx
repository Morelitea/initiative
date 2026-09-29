import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { parseHandle } from "@/hooks/useDirectMessages";
import { getErrorMessage } from "@/lib/errorMessage";

interface HandleFieldProps {
  label: string;
  placeholder: string;
  hint: string;
  submitLabel: string;
  /** Error key shown when the request fails without a code of its own. */
  errorFallback: string;
  pending: boolean;
  onSubmit: (handle: { username: string; discriminator: number }) => Promise<unknown>;
}

/** A `name#1234` field and its button: cleared on success, the reason on failure. */
export const HandleField = ({
  label,
  placeholder,
  hint,
  submitLabel,
  errorFallback,
  pending,
  onSubmit,
}: HandleFieldProps) => {
  const [handle, setHandle] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    const parsed = parseHandle(handle);
    if (!parsed) {
      setError(hint);
      return;
    }
    setError(null);
    onSubmit(parsed).then(
      () => setHandle(""),
      (err: unknown) => setError(getErrorMessage(err, errorFallback))
    );
  };

  return (
    <div className="space-y-1">
      <div className="flex gap-2">
        <Input
          value={handle}
          onChange={(event) => setHandle(event.target.value)}
          placeholder={placeholder}
          aria-label={label}
          onKeyDown={(event) => {
            if (event.key === "Enter") submit();
          }}
        />
        <Button onClick={submit} disabled={pending || !handle.trim()}>
          {submitLabel}
        </Button>
      </div>
      <p className={error ? "text-destructive text-xs" : "text-muted-foreground text-xs"}>
        {error ?? hint}
      </p>
    </div>
  );
};
