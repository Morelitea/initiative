/**
 * Plans, as the billing portal describes them.
 *
 * Rendered only on a deployment with a billing portal, from the catalog that
 * portal serves — names, prices, limits and copy are all its words. This page
 * shows the basics and sends anybody who wants the full comparison to the
 * portal's own pricing page.
 *
 * Two of the plans are not plans you pick off a shelf: running it yourself is
 * a different decision from buying a subscription, and the enterprise rung is
 * a conversation rather than a price. Both are given a full-width band — above
 * and below the ones that do compare against each other — so the row in the
 * middle is a like-for-like comparison and nothing else.
 */

import { Link } from "@tanstack/react-router";
import { ArrowUpRight, Cloud, Database, Headset, Users, Zap } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { type BillingCatalog, type CatalogTier, portalPricingUrl } from "@/hooks/useBillingCatalog";
import { docsUrl } from "@/lib/links";

import { reveal, useRevealOnScroll } from "./effects";

interface PricingSectionProps {
  portalUrl: string;
  /** The portal's price book, or undefined while it is still being fetched. */
  catalog: BillingCatalog | undefined;
  isDark: boolean;
  /** Whether this deployment lets a visitor make an account — a plan whose
   *  button is "sign up" points at the login page otherwise. */
  registrationOpen: boolean;
}

/** The kinds that get a band of their own rather than a column in the row. */
const BANNER_KINDS = {
  lead: "free_self_hosted",
  trail: "enterprise",
} as const;

/** Never more than four abreast, however many the portal sells. */
const MAX_COLUMNS = 4;

const cardSurface = (isDark: boolean, highlight: boolean) => ({
  background: highlight
    ? isDark
      ? "rgba(140, 130, 255, 0.1)"
      : "rgba(100, 80, 200, 0.06)"
    : isDark
      ? "rgba(30, 25, 60, 0.45)"
      : "rgba(255, 255, 255, 0.7)",
  borderColor: highlight
    ? "var(--primary)"
    : isDark
      ? "rgba(140, 130, 255, 0.14)"
      : "rgba(100, 80, 200, 0.1)",
});

/** Where a tier's button goes. Signing up is this app's own door; buying,
 *  talking and hosting it yourself each live somewhere else. */
const TierAction = ({
  tier,
  portalUrl,
  registrationOpen,
}: {
  tier: CatalogTier;
  portalUrl: string;
  registrationOpen: boolean;
}) => {
  const variant = tier.highlight ? "default" : "outline";
  if (tier.cta.kind === "signup") {
    return (
      <Button variant={variant} className="w-full" asChild>
        <Link to={registrationOpen ? "/register" : "/login"}>{tier.cta.label}</Link>
      </Button>
    );
  }
  const href =
    tier.cta.kind === "external" ? docsUrl("admin/installation/") : portalPricingUrl(portalUrl);
  return (
    <Button variant={variant} className="w-full" asChild>
      <a href={href} target="_blank" rel="noopener noreferrer">
        {tier.cta.label}
        <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
      </a>
    </Button>
  );
};

const Limit = ({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Database;
  label: string;
  value: string | null | undefined;
}) => {
  if (!value) return null;
  return (
    <li className="flex items-center gap-2 text-sm">
      <Icon className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
      <span className="sr-only">{label}: </span>
      <span className="text-foreground/90">{value}</span>
    </li>
  );
};

/** What the plan gives you, in the portal's own words. */
const TierLimits = ({ tier, className }: { tier: CatalogTier; className: string }) => {
  const { t } = useTranslation("landing");
  return (
    <ul className={className}>
      <Limit icon={Database} label={t("pricing.storage")} value={tier.limits.storage_display} />
      <Limit icon={Zap} label={t("pricing.automations")} value={tier.limits.automations_display} />
      <Limit icon={Users} label={t("pricing.members")} value={tier.limits.members_display} />
      <Limit icon={Headset} label={t("pricing.support")} value={tier.support} />
    </ul>
  );
};

const TierBadge = ({ tier }: { tier: CatalogTier }) =>
  tier.badge ? (
    <span className="rounded-full bg-primary/10 px-2.5 py-0.5 font-medium text-primary text-xs leading-tight">
      {tier.badge}
    </span>
  ) : null;

interface TierProps {
  tier: CatalogTier;
  portalUrl: string;
  registrationOpen: boolean;
  isDark: boolean;
  visible: boolean;
  index: number;
}

/** One of the plans that compare against each other: a column in the row. */
const TierCard = ({ tier, portalUrl, registrationOpen, isDark, visible, index }: TierProps) => (
  <li
    className={`flex flex-col rounded-2xl border p-6 backdrop-blur-sm transition-all duration-700 ${
      tier.highlight ? "shadow-lg shadow-primary/15 lg:-translate-y-2" : ""
    } ${reveal(visible, "translate-y-10 opacity-0")}`}
    style={{ ...cardSurface(isDark, tier.highlight), transitionDelay: `${index * 90}ms` }}
    data-tier={tier.id}
    data-layout="card"
  >
    {/* The badge gets the card's full width on a row of its own: beside the
        name it had only the gap left over, and a pill is not a paragraph —
        "Where most communities start" broke across two lines inside it. The
        row is reserved even when empty so every name sits on the same line. */}
    <div className="mb-3 flex min-h-[1.375rem] items-start">
      <TierBadge tier={tier} />
    </div>
    <h3 className="mb-4 font-bold text-foreground text-xl">{tier.name}</h3>
    <p className="font-black text-4xl text-foreground tracking-tight">{tier.price.display}</p>
    {tier.price.sub_display && (
      <p className="mt-1 text-muted-foreground text-sm">{tier.price.sub_display}</p>
    )}
    <p className="mt-4 font-medium text-foreground/90">{tier.tagline}</p>
    <p className="mt-1 text-muted-foreground text-sm leading-relaxed">{tier.audience}</p>

    <TierLimits tier={tier} className="mt-5 space-y-2 border-t pt-5" />

    <div className="mt-6 flex flex-1 flex-col justify-end gap-2">
      <TierAction tier={tier} portalUrl={portalUrl} registrationOpen={registrationOpen} />
      {tier.cta.note && (
        <p className="text-center text-muted-foreground text-xs">{tier.cta.note}</p>
      )}
    </div>
  </li>
);

/** One of the plans that doesn't belong in the row — a band across the width,
 *  laid out along it rather than down a column. */
const TierBanner = ({ tier, portalUrl, registrationOpen, isDark, visible, index }: TierProps) => (
  <li
    className={`col-span-full flex flex-col gap-6 rounded-2xl border p-6 backdrop-blur-sm transition-all duration-700 md:flex-row md:items-center md:gap-10 md:p-8 ${reveal(
      visible,
      "translate-y-10 opacity-0"
    )}`}
    style={{ ...cardSurface(isDark, tier.highlight), transitionDelay: `${index * 90}ms` }}
    data-tier={tier.id}
    data-layout="banner"
  >
    <div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="font-bold text-2xl text-foreground">{tier.name}</h3>
        <TierBadge tier={tier} />
      </div>
      <p className="mt-2 font-medium text-foreground/90">{tier.tagline}</p>
      <p className="mt-1 text-muted-foreground text-sm leading-relaxed">{tier.audience}</p>
      <TierLimits tier={tier} className="mt-4 flex flex-wrap gap-x-6 gap-y-2" />
    </div>

    <div className="flex shrink-0 flex-col gap-3 md:w-60 md:items-end">
      <div className="md:text-right">
        <p className="font-black text-3xl text-foreground tracking-tight">{tier.price.display}</p>
        {tier.price.sub_display && (
          <p className="mt-1 text-muted-foreground text-sm">{tier.price.sub_display}</p>
        )}
      </div>
      <TierAction tier={tier} portalUrl={portalUrl} registrationOpen={registrationOpen} />
      {tier.cta.note && (
        <p className="text-muted-foreground text-xs md:text-right">{tier.cta.note}</p>
      )}
    </div>
  </li>
);

export const PricingSection = ({
  portalUrl,
  catalog,
  isDark,
  registrationOpen,
}: PricingSectionProps) => {
  const { t } = useTranslation("landing");
  const { ref, isVisible } = useRevealOnScroll<HTMLElement>(0.05);

  const tiers = catalog?.tiers ?? [];
  const lead = tiers.filter((tier) => tier.kind === BANNER_KINDS.lead);
  const trail = tiers.filter((tier) => tier.kind === BANNER_KINDS.trail);
  const row = tiers.filter(
    (tier) => tier.kind !== BANNER_KINDS.lead && tier.kind !== BANNER_KINDS.trail
  );
  // The row sets the grid, and the bands span whatever it came to.
  const columns = Math.min(Math.max(row.length, 1), MAX_COLUMNS);

  const render = (tier: CatalogTier, index: number, banner: boolean) => {
    const Component = banner ? TierBanner : TierCard;
    return (
      <Component
        key={tier.id}
        tier={tier}
        portalUrl={portalUrl}
        registrationOpen={registrationOpen}
        isDark={isDark}
        visible={isVisible}
        index={index}
      />
    );
  };

  return (
    <section
      ref={ref}
      id="pricing"
      className="relative scroll-mt-20 overflow-hidden py-24 md:py-32"
      aria-labelledby="landing-pricing-title"
    >
      <div
        className="absolute inset-0"
        style={{
          background: isDark
            ? "linear-gradient(180deg, transparent 0%, rgba(100, 80, 240, 0.05) 50%, transparent 100%)"
            : "linear-gradient(180deg, transparent 0%, rgba(100, 80, 200, 0.03) 50%, transparent 100%)",
        }}
        aria-hidden="true"
      />
      <div className="relative z-10 mx-auto max-w-7xl px-6">
        <div className={`mb-12 text-center transition-all duration-1000 ${reveal(isVisible)}`}>
          <span className="mb-4 inline-flex items-center gap-2 font-semibold text-primary text-sm uppercase tracking-[0.2em]">
            <Cloud className="h-4 w-4" aria-hidden="true" />
            {t("pricing.sectionLabel")}
          </span>
          <h2
            id="landing-pricing-title"
            className="mb-4 font-bold text-3xl text-foreground tracking-tight md:text-5xl"
          >
            {catalog?.headline ?? t("pricing.sectionLabel")}
          </h2>
          {catalog?.subhead && (
            <p className="mx-auto max-w-3xl text-lg text-muted-foreground">{catalog.subhead}</p>
          )}
        </div>

        {catalog ? (
          <ul
            className="grid grid-cols-1 gap-4 lg:grid-cols-[var(--tier-columns)] lg:gap-6"
            style={
              { "--tier-columns": `repeat(${columns}, minmax(0, 1fr))` } as React.CSSProperties
            }
            aria-label={t("pricing.tierListAria")}
          >
            {lead.map((tier, i) => render(tier, i, true))}
            {row.map((tier, i) => render(tier, lead.length + i, false))}
            {trail.map((tier, i) => render(tier, lead.length + row.length + i, true))}
          </ul>
        ) : (
          <p className="text-center text-muted-foreground text-sm" aria-live="polite">
            {t("pricing.loading")}
          </p>
        )}

        <div className="mt-10 text-center">
          <Button variant="link" className="text-base" asChild>
            <a href={portalPricingUrl(portalUrl)} target="_blank" rel="noopener noreferrer">
              {t("pricing.seeAll")}
              <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
            </a>
          </Button>
        </div>
      </div>
    </section>
  );
};
