/**
 * The public pricing catalog, read straight from the billing portal.
 *
 * Billing is the source of truth for plans: this repository holds no tier
 * names, no prices and no limits, only the shape of what the portal serves.
 * The portal's catalog endpoint is public and revalidates on a content hash,
 * so a landing page anywhere renders the same price book the portal does.
 *
 * Nothing is asked until the deployment names a portal (`useAppConfig().billing`),
 * and a portal that cannot be reached simply leaves the pricing section out —
 * a visitor is not owed an error about somebody else's service.
 */

import { useQuery } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Shape (mirrors the portal's catalog schema; fields the landing page reads)
// ---------------------------------------------------------------------------

export interface CatalogTierPrice {
  base_monthly: number | null;
  display: string;
  sub_display: string | null;
}

export interface CatalogTierLimits {
  storage_display?: string | null;
  automations_display?: string | null;
  members_display?: string | null;
}

export interface CatalogTierCta {
  kind: "signup" | "checkout" | "contact" | "external";
  label: string;
  note: string | null;
}

export interface CatalogTier {
  id: string;
  name: string;
  kind: "free_self_hosted" | "free_hosted" | "paid" | "enterprise";
  tagline: string;
  audience: string;
  highlight: boolean;
  badge: string | null;
  price: CatalogTierPrice;
  limits: CatalogTierLimits;
  support: string;
  features: string[];
  cta: CatalogTierCta;
}

export interface BillingCatalog {
  catalog_version: number;
  currency: string;
  headline: string;
  subhead: string;
  tiers: CatalogTier[];
  footnotes: Record<string, string>;
}

// ---------------------------------------------------------------------------
// Portal addresses
// ---------------------------------------------------------------------------

const trimSlash = (url: string) => url.replace(/\/+$/, "");

/** The portal's catalog endpoint, next to the portal itself. */
export const catalogUrl = (portalUrl: string) => `${trimSlash(portalUrl)}/api/v1/catalog`;

/** The portal's own pricing page, where every plan is laid out in full. */
export const portalPricingUrl = (portalUrl: string) => `${trimSlash(portalUrl)}/upgrade`;

// ---------------------------------------------------------------------------
// Fetch + hook
// ---------------------------------------------------------------------------

const isCatalog = (value: unknown): value is BillingCatalog =>
  typeof value === "object" &&
  value !== null &&
  Array.isArray((value as BillingCatalog).tiers) &&
  typeof (value as BillingCatalog).headline === "string";

export async function fetchBillingCatalog(portalUrl: string): Promise<BillingCatalog> {
  const response = await fetch(catalogUrl(portalUrl), {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`catalog responded ${response.status}`);
  }
  const body: unknown = await response.json();
  if (!isCatalog(body)) {
    throw new Error("response is not a pricing catalog");
  }
  return body;
}

/** How long a price book is trusted before the page asks again. Edits to it
 *  are rare and a reload is the ordinary way to see one. */
const CATALOG_STALE_MS = 10 * 60 * 1000;

export const useBillingCatalog = (portalUrl: string | null | undefined) =>
  useQuery<BillingCatalog>({
    queryKey: ["billing-catalog", portalUrl ?? null],
    queryFn: () => fetchBillingCatalog(portalUrl as string),
    enabled: Boolean(portalUrl),
    staleTime: CATALOG_STALE_MS,
    retry: false,
  });
