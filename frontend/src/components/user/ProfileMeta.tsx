import { useTranslation } from "react-i18next";

import type { Presence } from "@/api/generated/initiativeAPI.schemas";
import { PresenceDot } from "@/components/user/PresenceDot";
import { formatDate } from "@/lib/formatDate";
import { presenceLabelKey } from "@/lib/presence";

/**
 * The two facts a profile states about an account rather than about a person:
 * how they are appearing, and when they joined.
 */
export const ProfileMeta = ({ presence, joinedAt }: { presence: Presence; joinedAt: string }) => {
  const { t } = useTranslation("profiles");
  return (
    <dl className="flex flex-wrap gap-x-8 gap-y-2 border-t pt-4 text-sm">
      <div className="flex items-center gap-2">
        {/* The dot and the word say it; the label is here for a reader who
            gets the list read out rather than shown. */}
        <dt className="sr-only">{t("presence.label")}</dt>
        <dd className="flex items-center gap-1.5 font-medium">
          <PresenceDot presence={presence} className="size-2" />
          {t(presenceLabelKey(presence))}
        </dd>
      </div>
      <div className="flex items-center gap-2">
        <dt className="text-muted-foreground">{t("joined.label")}</dt>
        <dd className="font-medium">{formatDate(joinedAt)}</dd>
      </div>
    </dl>
  );
};
