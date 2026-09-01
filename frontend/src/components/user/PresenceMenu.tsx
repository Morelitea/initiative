import { Check } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { Presence, UserSelfUpdate } from "@/api/generated/initiativeAPI.schemas";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { PresenceDot } from "@/components/user/PresenceDot";
import { useUpdateCurrentUser } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { PRESENCE_ORDER, presenceHelpKey, presenceLabelKey } from "@/lib/presence";

interface PresenceMenuProps {
  /** What the account is set to — the choice, not what a reader is shown. */
  presence: Presence;
  /** The control this hangs off: the dot on your avatar, or a chip beside it. */
  children: ReactNode;
  align?: "start" | "center" | "end";
  side?: "top" | "right" | "bottom" | "left";
  /** Re-read the account once the new choice is saved. */
  onChanged?: () => Promise<void> | void;
}

/**
 * Picking how you appear.
 *
 * The same menu wherever it is opened from, because there is one setting: the
 * sidebar is where you already are when it changes, and the profile card is
 * where you are looking at the dot when you decide it is wrong.
 *
 * Idle is offered even though it is also worked out on its own — a person who
 * would rather look like they stepped away can say so, and saying it means it
 * holds however busy their keyboard is.
 */
export const PresenceMenu = ({
  presence,
  children,
  align = "start",
  side,
  onChanged,
}: PresenceMenuProps) => {
  const { t } = useTranslation("profiles");

  const save = useUpdateCurrentUser({
    onSuccess: async () => {
      await onChanged?.();
    },
    onError: (error: unknown) => toast.error(getErrorMessage(error, "profiles:presence.failed")),
  });

  return (
    // modal={false}: a modal dropdown nested in the non-modal mobile sidebar
    // drawer dismisses the drawer on open.
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>{children}</DropdownMenuTrigger>
      <DropdownMenuContent align={align} side={side} className="w-60">
        <DropdownMenuLabel>{t("presence.edit")}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {PRESENCE_ORDER.map((option) => (
          <DropdownMenuItem
            key={option}
            className="items-start gap-2.5"
            disabled={save.isPending}
            onSelect={() => save.mutate({ presence: option } as UserSelfUpdate)}
          >
            <PresenceDot presence={option} className="mt-1 size-2.5 shrink-0" />
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="font-medium">{t(presenceLabelKey(option))}</span>
              <span className="text-muted-foreground text-xs">{t(presenceHelpKey(option))}</span>
            </span>
            {option === presence ? (
              <Check className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            ) : null}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
