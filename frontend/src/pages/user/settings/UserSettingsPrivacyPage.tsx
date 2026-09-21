import { useTranslation } from "react-i18next";

import type { DmPolicy } from "@/api/generated/initiativeAPI.schemas";
import { ConnectionsSection } from "@/components/contacts/ConnectionsSection";
import { ContactRequestsSection } from "@/components/contacts/ContactRequestsSection";
import { DirectMessagePolicyField } from "@/components/contacts/DirectMessagePolicyField";
import { IgnoredAccountsSection } from "@/components/contacts/IgnoredAccountsSection";
import { AgeConfirmationForm } from "@/components/contacts/UnreachableEmptyState";
import { CookieChoicesSection } from "@/components/settings/CookieChoicesSection";
import { SettingsSection } from "@/components/settings/SettingsSection";
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
      <SettingsSection title={t("privacy.dm.title")}>
        {/* The rule, and the answer to it. This tab is where somebody comes to
            change who may reach them, so it has to be able to take the one
            answer that gates all of it — a notice saying the controls are
            locked, with the key on another page, is not an answer. */}
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
          onCommunityChange={(guildId, enabled) =>
            save({ communities: [{ guild_id: guildId, enabled }] })
          }
        />
      </SettingsSection>

      <SettingsSection title={t("privacy.receipts.title")}>
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1">
            <p className="font-medium text-sm">{t("privacy.receipts.label")}</p>
            <p className="max-w-prose text-muted-foreground text-sm">
              {t("privacy.receipts.help")}
            </p>
          </div>
          <Switch
            checked={data?.send_receipts ?? true}
            disabled={isLoading || updateSettings.isPending}
            onCheckedChange={(checked) => save({ send_receipts: checked })}
            aria-label={t("privacy.receipts.label")}
          />
        </div>
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

      <CookieChoicesSection />
    </div>
  );
};
