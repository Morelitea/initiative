/**
 * What the front door's three pages need to know about the deployment they
 * are on, asked once and shared: whether somebody may make an account here,
 * and whether plans may be shown at all.
 *
 * Plans show only where a billing portal is configured and never in the
 * phone app, which may not point anyone at a purchase outside the stores.
 */

import { useBootstrapStatus } from "@/api/generated/auth/auth";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useBillingCatalog } from "@/hooks/useBillingCatalog";
import { useServer } from "@/hooks/useServer";

export const useFrontDoor = () => {
  const appConfig = useAppConfig();
  const { billing } = appConfig;

  const bootstrap = useBootstrapStatus({ query: { staleTime: 60_000 } });
  // Until the server answers, the page offers sign-up: most deployments allow
  // it, and the button leaving is better than the button arriving late.
  const registrationOpen = bootstrap.data?.public_registration_enabled !== false;

  const { isNativePlatform } = useServer();
  const sellsPlans = billing != null && !isNativePlatform;
  const catalog = useBillingCatalog(sellsPlans ? billing?.url : undefined);
  // The header offers Pricing only once there is a price book to show.
  const showsPricing = sellsPlans && catalog.data != null && !catalog.isError;

  return { ...appConfig, registrationOpen, sellsPlans, catalog, showsPricing };
};
