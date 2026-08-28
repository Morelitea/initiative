/**
 * What a guild member sees before they are in any initiative.
 *
 * Initiatives are the containers every piece of content lives in, so a member
 * with no membership row sees an empty sidebar and an empty table — correctly,
 * since RLS hides what they aren't in. This says why, and offers the directory
 * as the way in; when the guild lists nothing, it says that instead of implying
 * an action the reader doesn't have.
 */

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
  /** Opens the create dialog; present only for a reader who may create one. */
  onCreate?: () => void;
}

export const GuildHomeEmptyState = ({
  guildDescription,
  entries,
  onCreate,
}: GuildHomeEmptyStateProps) => {
  const { t } = useTranslation(["guildHome", "initiatives"]);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("emptyState.title")}</CardTitle>
          <CardDescription>{t("emptyState.description")}</CardDescription>
        </CardHeader>
        {guildDescription ? (
          <CardContent>
            <Markdown content={guildDescription} className="text-sm" />
          </CardContent>
        ) : null}
      </Card>

      {entries.length > 0 ? (
        <InitiativeDirectory entries={entries} onCreate={onCreate} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t("emptyState.nothingListedTitle")}</CardTitle>
            <CardDescription>{t("emptyState.nothingListedDescription")}</CardDescription>
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
