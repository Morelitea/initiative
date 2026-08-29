import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

interface UsernameFieldProps {
  value: string;
  onChange: (value: string) => void;
  /** Seeds the field the first time the person types a name, if it is empty. */
  suggestion?: string;
  disabled?: boolean;
  id?: string;
}

type Availability =
  | { state: "idle" }
  | { state: "checking" }
  | { state: "available" }
  | { state: "taken"; reason: string };

/**
 * The name part of a handle, with the number explained rather than asked for.
 *
 * A name is almost always free — ten thousand numbers sit behind each one — so
 * this reassures rather than negotiates. It says no only for a reserved or
 * malformed name, or the rare one whose numbers are all spoken for.
 */
export const UsernameField = ({
  value,
  onChange,
  suggestion,
  disabled,
  id = "username",
}: UsernameFieldProps) => {
  const { t } = useTranslation("auth");
  const [availability, setAvailability] = useState<Availability>({ state: "idle" });
  const [touched, setTouched] = useState(false);

  // Seed from the name they already typed, until they edit the field
  // themselves — after that it is theirs.
  useEffect(() => {
    if (!touched && suggestion && !value) onChange(suggestion);
  }, [suggestion, touched, value, onChange]);

  useEffect(() => {
    const candidate = value.trim();
    if (!candidate) {
      setAvailability({ state: "idle" });
      return;
    }
    setAvailability({ state: "checking" });
    const timer = setTimeout(() => {
      let ignore = false;
      apiClient
        .get<{ available: boolean; reason?: string | null }>("/auth/username-available", {
          params: { username: candidate },
        })
        .then(({ data }) => {
          if (ignore) return;
          setAvailability(
            data.available
              ? { state: "available" }
              : { state: "taken", reason: data.reason ?? "USERNAME_UNAVAILABLE" }
          );
        })
        .catch(() => {
          if (!ignore) setAvailability({ state: "idle" });
        });
      return () => {
        ignore = true;
      };
    }, 350);
    return () => clearTimeout(timer);
  }, [value]);

  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{t("register.usernameLabel")}</Label>
      <Input
        id={id}
        value={value}
        onChange={(event) => {
          setTouched(true);
          onChange(event.target.value.toLowerCase());
        }}
        autoCapitalize="none"
        autoComplete="username"
        disabled={disabled}
        required
      />
      <p
        className={cn(
          "text-xs",
          availability.state === "taken" ? "text-destructive" : "text-muted-foreground"
        )}
      >
        {availability.state === "taken"
          ? t(`register.usernameError.${availability.reason}`, {
              defaultValue: t("register.usernameError.USERNAME_UNAVAILABLE"),
            })
          : t("register.usernameHint")}
      </p>
    </div>
  );
};
