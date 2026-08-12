/**
 * One listing's page: what it is, what it looks like, and how to get it.
 *
 * The preview is the real thing — the listing's definition rendered by the same
 * canvas a live dashboard uses, read-only, over sample data. Someone deciding
 * whether to install sees what they would get rather than a description of it.
 */

import { Link, useParams } from "@tanstack/react-router";
import { Download, SearchX } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { DashboardCanvas } from "@/components/initiativeTools/dashboards/DashboardCanvas";
import { InstallListingDialog } from "@/components/marketplace/InstallListingDialog";
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
import { useMarketplaceListing } from "@/hooks/useMarketplace";
import { useGuildPath } from "@/lib/guildUrl";
import { readConfig, readDefinition } from "@/lib/widgets/definition";

export function MarketplaceListingPage() {
  const { t } = useTranslation("marketplace");
  const { publicId } = useParams({ strict: false }) as { publicId: string };
  const gp = useGuildPath();

  const listingQuery = useMarketplaceListing(publicId ?? null);
  const catalogQuery = useWidgetCatalog();
  const [installing, setInstalling] = useState(false);

  const listing = listingQuery.data;

  if (listingQuery.isError) {
    return (
      <StatusMessage
        icon={<SearchX />}
        title={t("detail.notFound")}
        description={t("detail.notFoundDescription")}
        backTo={gp("/marketplace")}
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
              <Link to={gp("/marketplace")}>{t("title")}</Link>
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
              <p className="text-muted-foreground text-sm">
                {t("detail.by", { publisher: listing.publisher })}
              </p>
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
            <Button onClick={() => setInstalling(true)} disabled={!listing.installable}>
              <Download className="mr-1.5 h-4 w-4" />
              {t("detail.install")}
            </Button>
            {!listing.installable && (
              <span className="text-muted-foreground text-xs">
                {listing.available ? t("detail.needsUpdate") : t("detail.withdrawn")}
              </span>
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

      <div className="space-y-2">
        <h2 className="font-medium text-sm">{t("detail.preview")}</h2>
        {listing?.definition ? (
          // The same canvas a live dashboard renders, read-only: `canEdit` false
          // means static tiles, no drag handles, and no layout writes.
          <DashboardCanvas
            definition={readDefinition(listing.definition)}
            config={readConfig({})}
            catalog={catalogQuery.data}
            initiativeId={undefined}
            canEdit={false}
            onLayoutChange={() => {}}
          />
        ) : (
          <Skeleton className="h-64 w-full rounded-lg" />
        )}
      </div>

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

      {listing && (
        <InstallListingDialog listing={listing} open={installing} onOpenChange={setInstalling} />
      )}
    </div>
  );
}
