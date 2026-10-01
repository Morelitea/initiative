import { useParams } from "@tanstack/react-router";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { SettingsTab } from "@/components/settings/SettingsTabsNav";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useGuilds } from "@/hooks/useGuilds";
import { guildPath } from "@/lib/guildUrl";

/**
 * The community settings tabs this person may open, in order, with
 * guild-scoped paths.
 *
 * One list for the tab bar and for where `/settings` itself sends you: the
 * first tab here is the landing page, so nobody is sent to a tab they would be
 * refused.
 */
export const useGuildSettingsTabs = (): SettingsTab[] => {
  const { t } = useTranslation(["settings"]);
  const { activeGuild, activeGuildId } = useGuilds();
  // Reaching the work inside the community, which a settings grant does not —
  // the tabs built on content are dropped below rather than rendered into
  // refusals.
  const reachesContent = Boolean(activeGuild?.can.content);
  // The seat above admin, which holds this community's sign-in and its
  // integrations — held outright, or lent for a window by a settings grant.
  const onTheGrantedSeat = activeGuild?.grantSettingsLevel === "superadmin";
  const isSuperadmin = Boolean(activeGuild?.can.seat);
  // Where the deployment has a billing portal, the plan sits with the usage.
  const { billing } = useAppConfig();
  // Where the community has a sign-in of its own to configure, that is. Most
  // never do: the operator grants each half of the surface separately, and
  // with neither there is nothing on the tab to show anybody. A grantee's
  // entry carries no options — the page reads the real ones and shows nothing
  // where there are none.
  const authOptions = activeGuild?.auth_options ?? [];
  const configuresItsOwnSignIn =
    isSuperadmin &&
    (onTheGrantedSeat || authOptions.includes("providers") || authOptions.includes("restrictions"));
  const params = useParams({ strict: false }) as { guildId?: string };
  // Get guild ID from URL params or active guild
  const urlGuildId = params.guildId ? Number(params.guildId) : activeGuildId;

  return useMemo(() => {
    const tabs: SettingsTab[] = [
      // First, so the seat lands on it: what the community uses against its
      // caps, and — where there is a portal — the plan those caps come with.
      // Both are the seat's, like its sign-in; an ordinary admin runs the
      // community without holding its card.
      ...(isSuperadmin
        ? [
            {
              value: "usage",
              label: billing ? t("guildLayout.tabs.planAndUsage") : t("guildLayout.tabs.usage"),
              path: urlGuildId ? guildPath(urlGuildId, "/settings/usage") : "/settings/usage",
            },
          ]
        : []),
      {
        value: "guild",
        label: t("guildLayout.tabs.guild"),
        path: urlGuildId ? guildPath(urlGuildId, "/settings/community") : "/settings/community",
      },
      {
        value: "users",
        label: t("guildLayout.tabs.users"),
        path: urlGuildId ? guildPath(urlGuildId, "/settings/users") : "/settings/users",
      },
      ...(configuresItsOwnSignIn
        ? [
            {
              // Everything on this tab is the superadmin's to set, so the
              // tab is theirs too — an ordinary admin has nothing to do on it.
              value: "security",
              label: t("guildLayout.tabs.security"),
              path: urlGuildId ? guildPath(urlGuildId, "/settings/security") : "/settings/security",
            },
          ]
        : []),
      ...(reachesContent
        ? [
            {
              value: "initiatives",
              label: t("guildLayout.tabs.initiatives"),
              path: urlGuildId
                ? guildPath(urlGuildId, "/settings/initiatives")
                : "/settings/initiatives",
            },
          ]
        : []),
      // What the community hands to somebody outside it — an AI provider, an
      // app — is the seat's to decide, the way its sign-in is. An ordinary
      // admin runs the community; these say who else gets to see it.
      ...(isSuperadmin
        ? [
            {
              value: "integrations",
              label: t("guildLayout.tabs.integrations"),
              path: urlGuildId
                ? guildPath(urlGuildId, "/settings/integrations")
                : "/settings/integrations",
            },
          ]
        : []),
      ...(reachesContent
        ? [
            {
              value: "trash",
              label: t("guildLayout.tabs.trash"),
              path: urlGuildId ? guildPath(urlGuildId, "/settings/trash") : "/settings/trash",
            },
          ]
        : []),
      // Taking the community's every initiative out in one file, or putting
      // one back, reaches as far as deleting it does — so it sits with the
      // same seat. An ordinary admin runs the community; this one moves it.
      ...(isSuperadmin
        ? [
            {
              value: "data",
              label: t("guildLayout.tabs.data"),
              path: urlGuildId ? guildPath(urlGuildId, "/settings/data") : "/settings/data",
            },
          ]
        : []),
    ];
    // Danger zone lives last — destructive guild deletion is deliberately
    // tucked behind its own tab rather than the first screen — and only the
    // seat sees it. Deleting a community is the one action an admin could not
    // undo and could not have undone for them; it belongs with the seat a
    // restore needs, which is also the seat the receipt is written to.
    if (isSuperadmin) {
      tabs.push({
        value: "danger-zone",
        label: t("guildLayout.tabs.dangerZone"),
        path: urlGuildId ? guildPath(urlGuildId, "/settings/danger-zone") : "/settings/danger-zone",
      });
    }
    return tabs;
  }, [urlGuildId, t, configuresItsOwnSignIn, isSuperadmin, reachesContent, billing]);
};
