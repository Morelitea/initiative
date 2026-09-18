import { useParams } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolSettingsLayout } from "@/components/tools/settings/ToolSettingsLayout";
import { useDeleteWiki, useSetWikiGrants, useUpdateWiki, useWiki } from "@/hooks/useWikis";

export const WikiSettingsPage = () => {
  const { t } = useTranslation("wikis");
  const { wikiId } = useParams({ strict: false }) as { wikiId?: string };
  const parsedId = wikiId ? Number(wikiId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const wikiQuery = useWiki(isValidId ? parsedId : null);
  const update = useUpdateWiki(parsedId);
  const setGrants = useSetWikiGrants(parsedId);
  const remove = useDeleteWiki();

  return (
    <ToolSettingsLayout
      tool={Tool.wiki}
      entity={wikiQuery.data}
      isLoading={isValidId && wikiQuery.isLoading}
      isError={!isValidId || wikiQuery.isError}
      update={update}
      setGrants={setGrants}
      remove={remove}
      // How the wiki reads and what it looks like: more than a card holds, so
      // it gets its own section, served by the route beside the shared ones.
      extraTabs={[{ value: "site", label: t("settings.tabSite") }]}
    />
  );
};
