import { useTranslation } from "react-i18next";

import type { DmPolicy } from "@/api/generated/initiativeAPI.schemas";
import { ConnectionsSection } from "@/components/contacts/ConnectionsSection";
import { ContactRequestsSection } from "@/components/contacts/ContactRequestsSection";
import { DirectMessagePolicyField } from "@/components/contacts/DirectMessagePolicyField";
import { IgnoredAccountsSection } from "@/components/contacts/IgnoredAccountsSection";
import { AgeConfirmationForm } from "@/components/contacts/UnreachableEmptyState";
import { CookieChoicesSection } from "@/components/settings/CookieChoicesSection";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { Switch } from "@/components/ui/switch";
import {
  useDirectMessagesEnabled,
  useDmSettings,
  useUpdateDmSettings,
} from "@/hooks/useDirectMessages";
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
  const dmEnabled = useDirectMessagesEnabled();

  // The age question gates everything, on every deployment — there is no
  // policy to choose while it is unanswered.
  const ageConfirmed = Boolean(data?.age_confirmed_at);

  const save = (body: Parameters<typeof updateSettings.mutate>[0]["data"]) =>
    updateSettings.mutate(
      { data: body },
      { onSuccess: () => toast.success(t("privacy.dm.saved")) }
    );

  // Every section here is about who may message this account, so a deployment
  // that offers no messaging leaves nothing to set. The tab is already gone;
  // this is for somebody who arrived by address or had it open when it was
  // switched off.
  if (!dmEnabled) {
    return (
      <div className="space-y-6">
        <SettingsSection title={t("privacy.dm.title")}>
          <p className="max-w-prose text-muted-foreground text-sm">
            {t("privacy.dm.platformDisabled")}
          </p>
        </SettingsSection>
        {/* Not about messaging, so it outlives messaging being switched off. */}
        <CookieChoicesSection />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <SettingsSection title={t("privacy.dm.title")} description={t("privacy.dm.description")}>
        {/* The age question gates the policy, so it is answered here, where
            the policy is set. */}
        {!ageConfirmed && !isLoading && (
          <div className="space-y-3 rounded-md border border-dashed p-3">
            <p className="max-w-prose text-muted-foreground text-sm">{t("privacy.dm.ageLocked")}</p>
            <AgeConfirmationForm id="settings-age" />
          </div>
        )}
        <DirectMessagePolicyField
          policy={(data?.dm_policy ?? "private") as DmPolicy}
          communities={data?.communities ?? []}
          disabled={!ageConfirmed || updateSettings.isPending}
          onPolicyChange={(policy) => save({ dm_policy: policy })}
          onCommunityChange={(communityId, enabled) =>
            save({ communities: [{ community_id: communityId, enabled }] })
          }
        />
        <div className="border-t pt-4">
          <SettingsRow label={t("privacy.receipts.label")} description={t("privacy.receipts.help")}>
            <Switch
              checked={data?.send_receipts ?? true}
              disabled={isLoading || updateSettings.isPending}
              onCheckedChange={(checked) => save({ send_receipts: checked })}
              aria-label={t("privacy.receipts.label")}
            />
          </SettingsRow>
        </div>
      </SettingsSection>

      <SettingsSection
        title={t("privacy.connections.title")}
        description={t("privacy.connections.description")}
      >
        <ConnectionsSection />
        <div className="space-y-2 border-t pt-4">
          <p className="font-medium text-sm">{t("privacy.requests.title")}</p>
          <ContactRequestsSection />
        </div>
      </SettingsSection>

      <SettingsSection
        title={t("privacy.ignored.title")}
        description={t("privacy.ignored.description")}
      >
        <IgnoredAccountsSection />
      </SettingsSection>

      <CookieChoicesSection />
    </div>
  );
};
