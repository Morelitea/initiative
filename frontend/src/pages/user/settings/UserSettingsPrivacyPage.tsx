import { useTranslation } from "react-i18next";

import type { DmPolicy } from "@/api/generated/initiativeAPI.schemas";
import { ConnectionsSection } from "@/components/contacts/ConnectionsSection";
import { ContactRequestsSection } from "@/components/contacts/ContactRequestsSection";
import { DirectMessagePolicyField } from "@/components/contacts/DirectMessagePolicyField";
import { IgnoredAccountsSection } from "@/components/contacts/IgnoredAccountsSection";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useDmSettings, useUpdateDmSettings } from "@/hooks/useDirectMessages";
import { toast } from "@/lib/chesterToast";

/**
 * Who may reach this account.
 *
 * The policy says who may ask; the three lists under it are the standing
 * exceptions to it — connections ask whatever it says, pending requests are
 * asking to become one of those, and ignored accounts are the refusal that
 * outranks all of it. Read top to bottom the tab answers one question.
 */
export const UserSettingsPrivacyPage = () => {
  const { t } = useTranslation("settings");
  const { data, isLoading } = useDmSettings();
  const updateSettings = useUpdateDmSettings();

  // The age question gates everything, on every deployment — there is no
  // policy to choose while it is unanswered.
  const ageConfirmed = Boolean(data?.age_confirmed_at);

  const save = (body: Parameters<typeof updateSettings.mutate>[0]["data"]) =>
    updateSettings.mutate(
      { data: body },
      { onSuccess: () => toast.success(t("privacy.dm.saved")) }
    );

  return (
    <div className="space-y-6">
      <SettingsSection title={t("privacy.dm.title")}>
        {!ageConfirmed && !isLoading && (
          <p className="rounded-md border border-dashed p-3 text-muted-foreground text-sm">
            {t("privacy.dm.ageLocked")}
          </p>
        )}
        <DirectMessagePolicyField
          policy={(data?.dm_policy ?? "private") as DmPolicy}
          communities={data?.communities ?? []}
          disabled={!ageConfirmed || updateSettings.isPending}
          onPolicyChange={(policy) => save({ dm_policy: policy })}
          onCommunityChange={(guildId, enabled) =>
            save({ communities: [{ guild_id: guildId, enabled }] })
          }
        />
      </SettingsSection>

      <SettingsSection title={t("privacy.connections.title")}>
        <ConnectionsSection />
        <div className="space-y-2 border-t pt-4">
          <p className="font-medium text-sm">{t("privacy.requests.title")}</p>
          <ContactRequestsSection />
        </div>
      </SettingsSection>

      <SettingsSection title={t("privacy.ignored.title")}>
        <IgnoredAccountsSection />
      </SettingsSection>
    </div>
  );
};
