import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { type AppServiceStatus, isAppServiceStatus } from "@/lib/appServices";
import { cn } from "@/lib/utils";

// Written out rather than interpolated so every key is statically checked
// against the `settings` namespace.
const STATUS_LABEL_KEYS = {
  ok: "appServices.status.ok",
  unverified: "appServices.status.unverified",
  unreachable: "appServices.status.unreachable",
  manifest_mismatch: "appServices.status.manifest_mismatch",
  signature_mismatch: "appServices.status.signature_mismatch",
} as const;

/**
 * One tone per state, distinct enough to sort a list at a glance. `unverified`
 * stays neutral on purpose — a registration waiting on its container has not
 * failed at anything. The label carries the meaning for anyone the colour
 * doesn't reach.
 */
const STATUS_TONES: Record<AppServiceStatus, string> = {
  ok: "border-transparent bg-emerald-600 text-white",
  unverified: "border-dashed text-muted-foreground",
  unreachable: "border-transparent bg-amber-500 text-amber-950",
  manifest_mismatch: "border-transparent bg-orange-500 text-orange-950",
  signature_mismatch: "border-transparent bg-destructive text-destructive-foreground",
};

export interface AppServiceStatusBadgeProps {
  status: string;
  className?: string;
}

/** The verification state of an app service registration. */
export const AppServiceStatusBadge = ({ status, className }: AppServiceStatusBadgeProps) => {
  const { t } = useTranslation("settings");

  // A server newer than this build may report a state we have no label for;
  // show it verbatim rather than mislabelling it.
  if (!isAppServiceStatus(status)) {
    return (
      <Badge variant="outline" className={className}>
        {status}
      </Badge>
    );
  }

  return (
    <Badge variant="outline" className={cn(STATUS_TONES[status], className)}>
      {t(STATUS_LABEL_KEYS[status])}
    </Badge>
  );
};
