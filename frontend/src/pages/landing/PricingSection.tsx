/**
 * Plans, as the billing portal describes them.
 *
 * Rendered only on a deployment with a billing portal, from the catalog that
 * portal serves — names, prices, limits and copy are all its words. This page
 * shows the basics and sends anybody who wants the full comparison to the
 * portal's own pricing page.
 */

import { Link } from "@tanstack/react-router";
import { ArrowUpRight, Cloud, Database, Headset, Users, Zap } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { type CatalogTier, portalPricingUrl, useBillingCatalog } from "@/hooks/useBillingCatalog";
import { docsUrl } from "@/lib/links";

import { reveal, useRevealOnScroll } from "./effects";

interface PricingSectionProps {
  portalUrl: string;
  isDark: boolean;
  /** Whether this deployment lets a visitor make an account — a plan whose
   *  button is "sign up" points at the login page otherwise. */
  registrationOpen: boolean;
}

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

const TierCard = ({
  tier,
  portalUrl,
  registrationOpen,
  isDark,
  visible,
  index,
}: {
  tier: CatalogTier;
  portalUrl: string;
  registrationOpen: boolean;
  isDark: boolean;
  visible: boolean;
  index: number;
}) => {
  const { t } = useTranslation("landing");
  return (
    <li
      className={`flex w-[min(85vw,20rem)] shrink-0 snap-center flex-col rounded-2xl border p-6 backdrop-blur-sm transition-all duration-700 lg:w-auto ${
        tier.highlight ? "shadow-lg shadow-primary/15 lg:-translate-y-2" : ""
      } ${reveal(visible, "translate-y-10 opacity-0")}`}
      style={{ ...cardSurface(isDark, tier.highlight), transitionDelay: `${index * 90}ms` }}
      data-tier={tier.id}
    >
      <div className="mb-4 flex min-h-6 items-start justify-between gap-3">
        <h3 className="font-bold text-foreground text-xl">{tier.name}</h3>
        {tier.badge && (
          <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-right font-medium text-primary text-xs leading-tight">
            {tier.badge}
          </span>
        )}
      </div>
      <p className="font-black text-4xl text-foreground tracking-tight">{tier.price.display}</p>
      {tier.price.sub_display && (
        <p className="mt-1 text-muted-foreground text-sm">{tier.price.sub_display}</p>
      )}
      <p className="mt-4 font-medium text-foreground/90">{tier.tagline}</p>
      <p className="mt-1 text-muted-foreground text-sm leading-relaxed">{tier.audience}</p>

      <ul className="mt-5 space-y-2 border-t pt-5" style={{ borderColor: "inherit" }}>
        <Limit icon={Database} label={t("pricing.storage")} value={tier.limits.storage_display} />
        <Limit
          icon={Zap}
          label={t("pricing.automations")}
          value={tier.limits.automations_display}
        />
        <Limit icon={Users} label={t("pricing.members")} value={tier.limits.members_display} />
        <Limit icon={Headset} label={t("pricing.support")} value={tier.support} />
      </ul>

      <div className="mt-6 flex flex-1 flex-col justify-end gap-2">
        <TierAction tier={tier} portalUrl={portalUrl} registrationOpen={registrationOpen} />
        {tier.cta.note && (
          <p className="text-center text-muted-foreground text-xs">{tier.cta.note}</p>
        )}
      </div>
    </li>
  );
};

export const PricingSection = ({ portalUrl, isDark, registrationOpen }: PricingSectionProps) => {
  const { t } = useTranslation("landing");
  const catalog = useBillingCatalog(portalUrl);
  const { ref, isVisible } = useRevealOnScroll<HTMLElement>(0.05);

  // A portal that cannot be reached, or answers with something else, means no
  // pricing on this page today — not a broken page.
  if (catalog.isError) return null;

  return (
    <section
      ref={ref}
      id="pricing"
      className="relative overflow-hidden py-24 md:py-32"
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
            {catalog.data?.headline ?? t("pricing.sectionLabel")}
          </h2>
          {catalog.data?.subhead && (
            <p className="mx-auto max-w-3xl text-lg text-muted-foreground">
              {catalog.data.subhead}
            </p>
          )}
        </div>

        {catalog.data ? (
          <ul
            className="-mx-6 flex snap-x snap-mandatory gap-4 overflow-x-auto px-6 pb-4 lg:mx-0 lg:grid lg:grid-cols-3 lg:gap-6 lg:overflow-visible lg:px-0"
            aria-label={t("pricing.tierListAria")}
          >
            {catalog.data.tiers.map((tier, i) => (
              <TierCard
                key={tier.id}
                tier={tier}
                portalUrl={portalUrl}
                registrationOpen={registrationOpen}
                isDark={isDark}
                visible={isVisible}
                index={i}
              />
            ))}
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
