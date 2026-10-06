/**
 * Platform → Integrations: everything this deployment wires up to something
 * outside itself.
 *
 * Two halves under two capabilities. The AI settings and the marketplace
 * registry belong to `config.manage` and are a couple of choices each, so they
 * come first; the plug-in service registrations belong to `plugins.manage` and are a
 * list that grows, so they sit below. An operator holding one capability is shown that half alone rather
 * than the other half's refusal.
 */

import { useTranslation } from "react-i18next";

import { MarketplaceRegistrySection } from "@/components/platform/MarketplaceRegistrySection";
import { useAuth } from "@/hooks/useAuth";
import { Capability, hasCapability } from "@/lib/permissions";
import { SettingsAIPage } from "@/pages/SettingsAIPage";
import { SettingsPluginServicesPage } from "@/pages/SettingsPluginServicesPage";

export const SettingsPlatformIntegrationsPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const canManageConfig = hasCapability(user, Capability.configManage);
  const canManagePlugins = hasCapability(user, Capability.pluginsManage);

  if (!canManageConfig && !canManagePlugins) {
    return <p className="text-muted-foreground text-sm">{t("platformAI.platformOnly")}</p>;
  }

  return (
    <div className="space-y-6">
      {canManageConfig ? <SettingsAIPage /> : null}
      {canManageConfig ? <MarketplaceRegistrySection /> : null}
      {canManagePlugins ? <SettingsPluginServicesPage /> : null}
    </div>
  );
};
