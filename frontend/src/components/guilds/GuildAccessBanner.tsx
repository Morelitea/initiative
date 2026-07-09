import { Clock } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useGuilds } from "@/hooks/useGuilds";

const minutesLeft = (expiresAt?: string | null): number | null => {
  if (!expiresAt) return null;
  return Math.max(0, Math.round((new Date(expiresAt).getTime() - Date.now()) / 60000));
};

/**
 * Banner shown across guild pages when the active guild is reached via a
 * time-bound PAM access grant (not real membership). Sets expectations that
 * access is temporary and, for read grants, read-only.
 */
export const GuildAccessBanner = () => {
  const { t } = useTranslation("guilds");
  const { activeGuild, activeGuildReadOnly } = useGuilds();

  if (activeGuild?.accessType !== "grant") {
    return null;
  }

  const left = minutesLeft(activeGuild.grantExpiresAt);
  const message = activeGuildReadOnly
    ? t("grantBanner.readOnly", { guild: activeGuild.name })
    : t("grantBanner.readWrite", { guild: activeGuild.name });
  // Operational context for the operator: this guild is under a moderation hold.
  const statusNote =
    activeGuild.status === "suspended"
      ? t("grantBanner.guildSuspended")
      : activeGuild.status === "read_only"
        ? t("grantBanner.guildReadOnly")
        : null;

  return (
    <div className="flex items-center gap-2 border-amber-500/30 border-b bg-amber-500/10 px-4 py-2 text-amber-700 text-sm dark:text-amber-300">
      <Clock className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span>
        {message}
        {statusNote !== null ? ` · ${statusNote}` : ""}
        {left !== null ? ` · ${t("expiresInMinutes", { minutes: left })}` : ""}
      </span>
    </div>
  );
};
