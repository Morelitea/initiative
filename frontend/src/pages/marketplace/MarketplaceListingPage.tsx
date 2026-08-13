/**
 * One listing's page: what it is, what it looks like, and how to get it.
 *
 * The preview runs the real pipeline — the listing's definition through the same
 * canvas, sandbox, and renderer a live dashboard uses — over **sample rows**.
 * A listing is not installed, so it has no initiative to read and is given
 * none: the canvas is told to draw samples, which fetches nothing at all.
 *
 * That is the point rather than a convenience. What someone shopping needs to
 * see is the *shape* of the dashboard, and a preview drawn from their own data
 * would be misleading twice over: it would look empty for a new initiative that
 * has nothing yet, and it would read as if the listing already knew about
 * their work.
 */

import { Link, useParams, useSearch } from "@tanstack/react-router";
import { Download, SearchX } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ListingKind } from "@/api/generated/initiativeAPI.schemas";
import { DashboardCanvas } from "@/components/initiativeTools/dashboards/DashboardCanvas";
import { InstallAppDialog } from "@/components/marketplace/InstallAppDialog";
import { InstallListingDialog } from "@/components/marketplace/InstallListingDialog";
import { ListingProvenance } from "@/components/marketplace/ListingProvenance";
import { StatusMessage } from "@/components/StatusMessage";
import { Badge } from "@/components/ui/badge";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useWidgetCatalog } from "@/hooks/useDashboards";
import { useGuildApps } from "@/hooks/useGuildApps";
import { useGuilds } from "@/hooks/useGuilds";
import { useMarketplaceListing } from "@/hooks/useMarketplace";
import { useGuildPath } from "@/lib/guildUrl";
import { readConfig, readDefinition } from "@/lib/widgets/definition";

export function MarketplaceListingPage() {
  const { t } = useTranslation(["marketplace", "apps"]);
  const { publicId } = useParams({ strict: false }) as { publicId: string };
  const { kind: shelf } = useSearch({ strict: false }) as { kind?: ListingKind };
  const gp = useGuildPath();

  const listingQuery = useMarketplaceListing(publicId ?? null);
  const catalogQuery = useWidgetCatalog();
  const [installing, setInstalling] = useState(false);
  const { activeGuild } = useGuilds();

  const listing = listingQuery.data;
  const isApp = listing?.kind === "app";
  // Back to the shelf this listing was found on, falling back to the listing's
  // own kind when someone arrived by direct link. Both can be unknown when the
  // listing failed to load — there is nothing to infer a shelf from then, and
  // the browse route normalizes an absent kind to dashboards.
  const backToShelf = { kind: shelf ?? listing?.kind };
  // Installing an app is a guild-admin action; the server enforces it, and the
  // button says so rather than failing after the click.
  const isGuildAdmin = activeGuild?.role === "admin";
  // Whether this guild already has it. Every member may read the installs, so
  // this answers for the person asking as well as the one who could act.
  //
  // Three states, not two: undefined while the answer is still loading or the
  // request failed. "We do not know" and "you do not have it" would otherwise
  // render identically — as an install button and a note telling a member to go
  // ask for something they may already have.
  const appInstalls = useGuildApps({ enabled: isApp });
  const isInstalled: boolean | undefined =
    isApp && !appInstalls.isLoading && !appInstalls.isError
      ? (appInstalls.data?.items ?? []).some((app) => app.listing_uid === listing?.uid)
      : undefined;

  if (listingQuery.isError) {
    return (
      <StatusMessage
        icon={<SearchX />}
        title={t("detail.notFound")}
        description={t("detail.notFoundDescription")}
        backTo={gp("/marketplace")}
        backSearch={backToShelf}
        backLabel={t("backToMarketplace")}
      />
    );
  }

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp("/marketplace")} search={backToShelf}>
                {t("title")}
              </Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            {listing ? (
              <BreadcrumbPage>{listing.name}</BreadcrumbPage>
            ) : (
              <Skeleton className="h-4 w-32" />
            )}
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="flex flex-wrap items-start gap-4">
        {listing ? (
          <img
            src={listing.avatar_url}
            alt=""
            aria-hidden
            className="h-16 w-16 shrink-0 rounded-xl object-cover"
          />
        ) : (
          <Skeleton className="h-16 w-16 rounded-xl" />
        )}

        <div className="min-w-0 flex-1 space-y-1">
          {listing ? (
            <>
              <h1 className="font-semibold text-3xl tracking-tight">{listing.name}</h1>
              <ListingProvenance listing={listing} className="text-sm" />
              <div className="flex flex-wrap items-center gap-2 pt-1">
                {listing.latest_version && (
                  <Badge variant="secondary">
                    {t("card.version", { version: listing.latest_version.version })}
                  </Badge>
                )}
                <span className="text-muted-foreground text-xs">
                  {t("detail.installs", { count: listing.installs_count })}
                </span>
              </div>
            </>
          ) : (
            <Skeleton className="h-9 w-56" />
          )}
        </div>

        {listing && (
          <div className="flex flex-col items-end gap-1">
            {isInstalled ? (
              <Badge variant="secondary">{t("card.installed")}</Badge>
            ) : (
              <Button
                onClick={() => setInstalling(true)}
                // Unknown installed state disables it too: offering to add
                // something the guild may already have is the one action this
                // page should not take on a guess.
                disabled={
                  !listing.installable || (isApp && (!isGuildAdmin || isInstalled === undefined))
                }
              >
                <Download className="mr-1.5 h-4 w-4" />
                {isApp ? t("apps:install.action") : t("detail.install")}
              </Button>
            )}
            {!listing.installable ? (
              <span className="text-muted-foreground text-xs">
                {listing.available ? t("detail.needsUpdate") : t("detail.withdrawn")}
              </span>
            ) : isApp && appInstalls.isError ? (
              <span className="text-muted-foreground text-xs">
                {t("apps:install.unknownState")}
              </span>
            ) : (
              isApp &&
              !isGuildAdmin &&
              isInstalled === false && (
                <span className="text-muted-foreground text-xs">{t("apps:install.adminOnly")}</span>
              )
            )}
          </div>
        )}
      </div>

      {listing?.long_description && (
        <p className="max-w-3xl whitespace-pre-line text-sm leading-relaxed">
          {listing.long_description}
        </p>
      )}

      {listing?.images?.length ? (
        <div className="flex gap-3 overflow-x-auto pb-2">
          {listing.images.map((image) => (
            <img
              key={image}
              src={image}
              alt=""
              aria-hidden
              className="h-48 shrink-0 rounded-lg border object-cover"
              loading="lazy"
            />
          ))}
        </div>
      ) : null}

      {/* An app mounts one of this build's tools; there is no canvas to draw,
          so the preview is a dashboard-only affordance. */}
      {!isApp && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <h2 className="font-medium text-sm">{t("detail.preview")}</h2>
            <p className="text-muted-foreground text-xs">{t("detail.previewIsSample")}</p>
          </div>
          {listing?.definition ? (
            // The same canvas a live dashboard renders, read-only: `canEdit` false
            // means static tiles, no drag handles, and no layout writes.
            <DashboardCanvas
              definition={readDefinition(listing.definition)}
              config={readConfig({})}
              catalog={catalogQuery.data}
              // Sample rows, and therefore no initiative: an uninstalled
              // listing reads nothing from this guild.
              sampleData
              initiativeId={undefined}
              canEdit={false}
              onLayoutChange={() => {}}
            />
          ) : (
            <Skeleton className="h-64 w-full rounded-lg" />
          )}
        </div>
      )}

      {listing && listing.versions.length > 1 && (
        <div className="space-y-2">
          <h2 className="font-medium text-sm">{t("detail.versions")}</h2>
          <ul className="space-y-2 text-sm">
            {listing.versions.map((version) => (
              <li key={version.version} className="flex flex-wrap items-baseline gap-2">
                <span className="font-medium">{version.version}</span>
                {version.release_notes && (
                  <span className="text-muted-foreground">{version.release_notes}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {listing &&
        (isApp ? (
          <InstallAppDialog listing={listing} open={installing} onOpenChange={setInstalling} />
        ) : (
          <InstallListingDialog listing={listing} open={installing} onOpenChange={setInstalling} />
        ))}
    </div>
  );
}
