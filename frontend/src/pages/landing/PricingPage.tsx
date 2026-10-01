/**
 * Plans, as the billing portal describes them.
 *
 * Only on a deployment with a billing portal, and never in the phone app;
 * anywhere else the address goes back to the front page. Names, prices,
 * limits and copy are all the portal's words, from the catalog it serves.
 *
 * The free plan every account comes with leads, as a band across the width:
 * it is where most people start. The plans that compare against each other
 * sit in the row under it, the enterprise conversation follows, and running
 * it yourself closes the list as one quiet line.
 */

import { Link, Navigate } from "@tanstack/react-router";
import type { LucideIcon } from "lucide-react";
import {
  ArrowUpRight,
  Code2,
  Database,
  Headset,
  Layers,
  Server,
  ShieldCheck,
  Users,
  Zap,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { type CatalogTier, portalPricingUrl } from "@/hooks/useBillingCatalog";
import { docsUrl } from "@/lib/links";
import { cn } from "@/lib/utils";

import { DarkBand } from "./DarkBand";
import { LandingShell } from "./LandingShell";
import { useFrontDoor } from "./useFrontDoor";
import { usePageMeta } from "./usePageMeta";

/** Never more than four abreast, however many the portal sells. */
const MAX_COLUMNS = 4;

const SELF_HOST_GUIDE = docsUrl("running-a-server/installation/");

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
        <Link to={registrationOpen ? "/start" : "/login"}>{tier.cta.label}</Link>
      </Button>
    );
  }
  const href = tier.cta.kind === "external" ? SELF_HOST_GUIDE : portalPricingUrl(portalUrl);
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
  icon: LucideIcon;
  label: string;
  value: string | null | undefined;
}) => {
  if (!value) return null;
  return (
    <li className="flex items-center gap-2 text-sm">
      <Icon className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
      <span className="sr-only">{label}: </span>
      <span>{value}</span>
    </li>
  );
};

/** What the plan gives you, in the portal's own words. */
const TierLimits = ({ tier, className }: { tier: CatalogTier; className: string }) => {
  const { t } = useTranslation("landing");
  return (
    <ul className={className}>
      <Limit icon={Users} label={t("pricing.members")} value={tier.limits.members_display} />
      <Limit icon={Database} label={t("pricing.storage")} value={tier.limits.storage_display} />
      <Limit icon={Zap} label={t("pricing.automations")} value={tier.limits.automations_display} />
      <Limit icon={Headset} label={t("pricing.support")} value={tier.support} />
    </ul>
  );
};

const TierBadge = ({ tier }: { tier: CatalogTier }) =>
  tier.badge ? (
    <span className="rounded-full bg-amber-100 px-2.5 py-0.5 font-bold text-amber-800 text-xs leading-tight dark:bg-amber-900/40 dark:text-amber-200">
      {tier.badge}
    </span>
  ) : null;

interface TierProps {
  tier: CatalogTier;
  portalUrl: string;
  registrationOpen: boolean;
}

/** One of the plans that compare against each other: a column in the row. */
const TierCard = ({ tier, portalUrl, registrationOpen }: TierProps) => (
  <li
    className={cn(
      "flex flex-col rounded-2xl border bg-card p-6",
      tier.highlight && "border-2 border-primary shadow-primary/20 shadow-xl"
    )}
    data-tier={tier.id}
    data-layout="card"
  >
    {/* The badge row is reserved even when empty so every name sits on the
        same line. */}
    <div className="mb-3 flex min-h-[1.375rem] items-start">
      <TierBadge tier={tier} />
    </div>
    <h3 className="font-bold text-xl">{tier.name}</h3>
    <p className="mt-3 font-extrabold text-4xl tracking-tight">{tier.price.display}</p>
    {tier.price.sub_display && (
      <p className="mt-1 text-muted-foreground text-sm">{tier.price.sub_display}</p>
    )}
    <p className="mt-4 font-semibold">{tier.tagline}</p>
    <p className="mt-1 text-muted-foreground text-sm">{tier.audience}</p>
    <TierLimits tier={tier} className="mt-5 space-y-2 border-t pt-5" />
    <div className="mt-6 flex flex-1 flex-col justify-end gap-2">
      <TierAction tier={tier} portalUrl={portalUrl} registrationOpen={registrationOpen} />
      {tier.cta.note && (
        <p className="text-center text-muted-foreground text-xs">{tier.cta.note}</p>
      )}
    </div>
  </li>
);

/** A plan that doesn't belong in the row: a band across the width. */
const TierBanner = ({ tier, portalUrl, registrationOpen }: TierProps) => (
  <li
    className="col-span-full flex flex-col gap-6 rounded-2xl border bg-card p-6 shadow-lg md:flex-row md:items-center md:gap-10 md:p-8"
    data-tier={tier.id}
    data-layout="banner"
  >
    <div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="font-bold text-2xl">{tier.name}</h3>
        <TierBadge tier={tier} />
      </div>
      <p className="mt-2 font-semibold">{tier.tagline}</p>
      <p className="mt-1 text-muted-foreground text-sm">{tier.audience}</p>
      <TierLimits tier={tier} className="mt-4 flex flex-wrap gap-x-6 gap-y-2" />
    </div>
    <div className="flex shrink-0 flex-col gap-3 md:w-60 md:items-end">
      <div className="md:text-right">
        <p className="font-extrabold text-3xl tracking-tight">{tier.price.display}</p>
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

/** Running it yourself: one line at the foot of the list. */
const SelfHostLine = ({ tier }: { tier: CatalogTier }) => {
  const { t } = useTranslation("landing");
  return (
    <li
      className="col-span-full flex flex-wrap items-center gap-4 rounded-2xl border border-dashed bg-muted/40 px-5 py-4 md:flex-nowrap md:px-6"
      data-tier={tier.id}
      data-layout="line"
    >
      <Server className="h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <h3 className="font-bold">
          {tier.name}, {tier.price.display}
        </h3>
        <p className="text-muted-foreground text-sm">{t("pricing.selfHostBody")}</p>
      </div>
      <a
        href={SELF_HOST_GUIDE}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1.5 font-semibold text-primary hover:underline"
      >
        {tier.cta.label}
        <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
      </a>
    </li>
  );
};

const Fact = ({ icon: Icon, title, body }: { icon: LucideIcon; title: string; body: string }) => (
  <li className="flex items-start gap-3.5 rounded-2xl bg-muted/60 p-5">
    <Icon className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
    <div>
      <h3 className="font-bold">{title}</h3>
      <p className="mt-0.5 text-muted-foreground text-sm">{body}</p>
    </div>
  </li>
);

export const PricingPage = () => {
  const { t } = useTranslation("landing");
  const { billing, isLoading, sellsPlans, catalog, registrationOpen } = useFrontDoor();
  usePageMeta(t("meta.pricingTitle"), catalog.data?.subhead ?? t("meta.pricingDescription"));

  // Nothing to sell here (no portal, or the phone app): the front page instead.
  if (!isLoading && !sellsPlans) {
    return <Navigate to="/welcome" replace />;
  }

  const tiers = catalog.data?.tiers ?? [];
  const lead = tiers.filter((tier) => tier.kind === "free_hosted");
  const row = tiers.filter((tier) => tier.kind === "paid");
  const trail = tiers.filter((tier) => tier.kind === "enterprise");
  const selfHosted = tiers.filter((tier) => tier.kind === "free_self_hosted");
  // The row sets the grid, and the bands span whatever it came to.
  const columns = Math.min(Math.max(row.length, 1), MAX_COLUMNS);
  const portalUrl = billing?.url ?? "";

  return (
    <LandingShell current="pricing">
      <DarkBand stars aria-labelledby="landing-pricing-title">
        <div className="relative mx-auto max-w-6xl px-4 pt-10 pb-24 md:px-8 md:pt-18 md:pb-28">
          <h1
            id="landing-pricing-title"
            className="font-extrabold text-[2.6rem] leading-tight tracking-tight md:text-6xl"
          >
            {catalog.data?.headline ?? t("pricing.sectionLabel")}
          </h1>
          {catalog.data?.subhead ? (
            <p className="mt-4 max-w-3xl text-lg text-slate-300">{catalog.data.subhead}</p>
          ) : null}
        </div>
      </DarkBand>

      <div className="mx-auto max-w-6xl px-4 md:px-8">
        {catalog.isError ? (
          <div
            className="relative -mt-12 rounded-3xl border bg-card p-8 text-center shadow-xl"
            role="status"
          >
            <h2 className="font-bold text-xl">{t("pricing.unavailableTitle")}</h2>
            <p className="mt-2 text-muted-foreground">{t("pricing.unavailableBody")}</p>
            <Button variant="outline" className="mt-5" asChild>
              <Link to="/welcome">{t("pricing.back")}</Link>
            </Button>
          </div>
        ) : catalog.data ? (
          <ul
            className="relative -mt-12 grid grid-cols-1 gap-4 lg:grid-cols-[var(--tier-columns)] lg:gap-5"
            style={
              { "--tier-columns": `repeat(${columns}, minmax(0, 1fr))` } as React.CSSProperties
            }
            aria-label={t("pricing.tierListAria")}
          >
            {lead.map((tier) => (
              <TierBanner
                key={tier.id}
                tier={tier}
                portalUrl={portalUrl}
                registrationOpen={registrationOpen}
              />
            ))}
            {row.map((tier) => (
              <TierCard
                key={tier.id}
                tier={tier}
                portalUrl={portalUrl}
                registrationOpen={registrationOpen}
              />
            ))}
            {trail.map((tier) => (
              <TierBanner
                key={tier.id}
                tier={tier}
                portalUrl={portalUrl}
                registrationOpen={registrationOpen}
              />
            ))}
            {selfHosted.map((tier) => (
              <SelfHostLine key={tier.id} tier={tier} />
            ))}
          </ul>
        ) : (
          <p
            className="relative -mt-8 text-center text-muted-foreground text-sm"
            aria-live="polite"
          >
            {t("pricing.loading")}
          </p>
        )}

        <ul
          className="mt-12 grid gap-3 md:grid-cols-3 md:gap-4"
          aria-label={t("pricing.everyPlanAria")}
        >
          <Fact icon={Layers} title={t("pricing.sameTitle")} body={t("pricing.sameBody")} />
          <Fact icon={Code2} title={t("pricing.openTitle")} body={t("pricing.openBody")} />
          <Fact icon={ShieldCheck} title={t("pricing.dataTitle")} body={t("pricing.dataBody")} />
        </ul>
        {portalUrl ? (
          <p className="mt-8 mb-20 text-center md:mb-24">
            <a
              href={portalPricingUrl(portalUrl)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 font-semibold text-primary hover:underline"
            >
              {t("pricing.seeAll")}
              <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
            </a>
          </p>
        ) : null}
      </div>
    </LandingShell>
  );
};
