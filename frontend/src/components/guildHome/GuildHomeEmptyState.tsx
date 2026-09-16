/**
 * What a guild member sees before they are in any initiative.
 *
 * Initiatives are the containers every piece of content lives in, so a member
 * with no membership row sees an empty sidebar and an empty table — correctly,
 * since RLS hides what they aren't in. This says why, and offers the directory
 * as the way in; when the guild lists nothing, it says that instead of implying
 * an action the reader doesn't have.
 *
 * Two readers land here, and they need opposite sentences. A member is waiting
 * to be let in, so the copy points at the directory. An admin in a community
 * that has just been made is the person the waiting is *for* — telling them a
 * community admin could add them to one would be telling them to ask
 * themselves. `onCreate` already carries that distinction (passing one IS the
 * guild-admin gate), so the copy keys off the same prop the button does.
 */

import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { InitiativeDirectoryEntry } from "@/api/generated/initiativeAPI.schemas";
import { InitiativeDirectory } from "@/components/guildHome/InitiativeDirectory";
import { Markdown } from "@/components/Markdown";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export interface GuildHomeEmptyStateProps {
  /** The guild's own description, so the page still says where you are. */
  guildDescription?: string | null;
  entries: InitiativeDirectoryEntry[];
  /** Whether the directory actually answered. "Nothing on offer" is a claim
   *  only a successful lookup can support; a failed or pending one says so
   *  rather than reporting an emptiness it never established. */
  directoryStatus?: "pending" | "error" | "success";
  /** Opens the create dialog; present only for a reader who may create one. */
  onCreate?: () => void;
}

export const GuildHomeEmptyState = ({
  guildDescription,
  entries,
  directoryStatus = "success",
  onCreate,
}: GuildHomeEmptyStateProps) => {
  const { t } = useTranslation(["guildHome", "initiatives"]);
  const canCreate = Boolean(onCreate);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t(canCreate ? "emptyState.adminTitle" : "emptyState.title")}</CardTitle>
          <CardDescription>
            {t(canCreate ? "emptyState.adminDescription" : "emptyState.description")}
          </CardDescription>
        </CardHeader>
        {guildDescription ? (
          <CardContent>
            <Markdown content={guildDescription} className="text-sm" />
          </CardContent>
        ) : null}
      </Card>

      {entries.length > 0 ? (
        <InitiativeDirectory entries={entries} onCreate={onCreate} />
      ) : directoryStatus === "pending" ? (
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          {t("loading")}
        </div>
      ) : directoryStatus === "error" ? (
        <p className="text-destructive text-sm">{t("directory.loadError")}</p>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>
              {t(
                canCreate ? "emptyState.adminNothingListedTitle" : "emptyState.nothingListedTitle"
              )}
            </CardTitle>
            <CardDescription>
              {t(
                canCreate
                  ? "emptyState.adminNothingListedDescription"
                  : "emptyState.nothingListedDescription"
              )}
            </CardDescription>
          </CardHeader>
          {/* An admin's way out of an empty guild is to start the first one. */}
          {onCreate ? (
            <CardFooter>
              <Button onClick={onCreate}>{t("initiatives:createInitiative")}</Button>
            </CardFooter>
          ) : null}
        </Card>
      )}
    </div>
  );
};
