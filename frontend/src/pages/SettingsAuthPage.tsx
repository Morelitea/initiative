import { useTranslation } from "react-i18next";

import { AuthProvidersSection } from "@/components/admin/AuthProvidersSection";
import { OidcClaimMappingsSection } from "@/components/admin/OidcClaimMappingsSection";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { FormSkeleton, SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/hooks/useAuth";
import { useOidcSettings } from "@/hooks/useSettings";
import { Capability, hasCapability } from "@/lib/permissions";

/**
 * Platform → Authentication.
 *
 * Providers are a list and nothing else: the one an install started with is a
 * row like any other, added and edited the same way as the fifth. What is left
 * on this page beside the list belongs to the deployment rather than to any
 * provider — the posture it runs in, and the two addresses every provider
 * shares.
 */
export const SettingsAuthPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const isPlatformAdmin = hasCapability(user, Capability.configManage);
  const oidcQuery = useOidcSettings({ enabled: isPlatformAdmin });

  if (!isPlatformAdmin) {
    return <p className="text-muted-foreground text-sm">{t("auth.adminOnly")}</p>;
  }

  if (oidcQuery.isLoading) {
    return (
      <SkeletonRegion label={t("auth.loading")}>
        <FormSkeleton fields={5} />
      </SkeletonRegion>
    );
  }

  if (oidcQuery.isError || !oidcQuery.data) {
    return <p className="text-destructive text-sm">{t("auth.loadError")}</p>;
  }

  const guildScoped = oidcQuery.data.auth_scope === "guild";

  return (
    <div className="space-y-6">
      <SettingsSection
        title={
          <span className="flex items-center gap-2">
            {t("auth.deploymentTitle")}
            <Badge variant="secondary">
              {guildScoped ? t("auth.scope.guildLabel") : t("auth.scope.platformLabel")}
            </Badge>
          </span>
        }
        description={
          guildScoped ? t("auth.scope.guildExplained") : t("auth.scope.platformExplained")
        }
      >
        {/* Shared by every provider, so stated once rather than on each. The
            per-provider callback lives on its row in the list below. */}
        <dl className="space-y-2 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <dt className="text-muted-foreground">{t("auth.postLoginRedirect")}</dt>
            <dd>
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                {oidcQuery.data.post_login_redirect}
              </code>
            </dd>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <dt className="text-muted-foreground">{t("auth.mobileCallback")}</dt>
            <dd>
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                {oidcQuery.data.mobile_redirect_uri}
              </code>
            </dd>
          </div>
        </dl>
      </SettingsSection>

      <AuthProvidersSection />
      <OidcClaimMappingsSection />
    </div>
  );
};
