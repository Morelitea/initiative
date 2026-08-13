/**
 * What `/settings/platform` shows when no tab is named.
 *
 * Authentication is the landing page for the operator who configures the
 * platform, and stays that way. But the area is no longer reachable by
 * `config.manage` alone — `apps.manage` reaches it too, for app services and
 * nothing else — and rendering authentication settings to that operator would
 * contradict the tab their own capability just selected.
 *
 * So the index sends whoever cannot manage configuration to the first tab they
 * actually hold, rather than to a page they will be refused.
 */

import { Navigate } from "@tanstack/react-router";

import { useAuth } from "@/hooks/useAuth";
import { Capability, hasCapability } from "@/lib/permissions";
import { SettingsAuthPage } from "@/pages/SettingsAuthPage";

export function SettingsPlatformIndexPage() {
  const { user } = useAuth();

  if (!hasCapability(user, Capability.configManage)) {
    return <Navigate to="/settings/platform/app-services" replace />;
  }
  return <SettingsAuthPage />;
}
