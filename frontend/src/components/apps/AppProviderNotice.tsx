/**
 * Who an app comes from, said once before it first opens.
 *
 * Shown by the iPhone app the first time a member opens a community app that
 * did not ship with Initiative: who publishes it, that the community and that
 * publisher provide it rather than Initiative, and a way to report it.
 * Continuing is remembered per server, community and app (`appNoticeKey`).
 */

import { useTranslation } from "react-i18next";

import type { CommunityAppListingRef } from "@/api/generated/initiativeAPI.schemas";
import { ReportButton } from "@/components/moderation/ReportButton";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/** Where the acknowledgement for one app in one community is kept. */
export const appNoticeKey = (server: string, communityId: number, appId: number) =>
  `initiative-app-notice:${server}:${communityId}:${appId}`;

export interface AppProviderNoticeProps {
  name: string;
  listing: CommunityAppListingRef | null;
  onContinue: () => void;
}

export function AppProviderNotice({ name, listing, onContinue }: AppProviderNoticeProps) {
  const { t } = useTranslation("apps");

  return (
    <Card className="mx-auto mt-6 max-w-lg">
      <CardHeader>
        <CardTitle>{t("providerNotice.title", { name })}</CardTitle>
        {listing ? (
          <CardDescription>
            {t("providerNotice.madeBy", { name, publisher: listing.publisher })}
          </CardDescription>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p>{t("providerNotice.provided")}</p>
        {listing ? (
          <div className="flex items-center gap-1 text-muted-foreground">
            <span>{t("providerNotice.report")}</span>
            <ReportButton targetType="marketplace_listing" targetId={listing.id} />
          </div>
        ) : null}
      </CardContent>
      <CardFooter>
        <Button onClick={onContinue}>{t("providerNotice.continue")}</Button>
      </CardFooter>
    </Card>
  );
}
