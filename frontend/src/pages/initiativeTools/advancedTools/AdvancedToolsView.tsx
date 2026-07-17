import { ExternalLink, Loader2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllAdvancedTools } from "@/api/query-keys";
import { BulkAccessBar, canManageSharing } from "@/components/access/BulkAccessBar";
import { BulkEditAccessDialog } from "@/components/access/BulkEditAccessDialog";
import { SelectableGridItem } from "@/components/access/SelectableGridItem";
import { AdvancedToolCard } from "@/components/initiativeTools/advancedTools/AdvancedToolCard";
import { ToolCreateButton } from "@/components/tools/ToolCreateButton";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAdvancedToolsList } from "@/hooks/useAdvancedTools";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useGridSelection } from "@/hooks/useGridSelection";

type AdvancedToolsViewProps = {
  /** Initiative whose advanced tools to list (this view is initiative-scoped;
   * guild-wide tools are managed from guild settings instead). */
  fixedInitiativeId: number;
  /** Whether the user may author new tools — surfaces the "New" button, which
   * hands off to the connected service where creation happens. */
  canCreate?: boolean;
};

/**
 * Lists an initiative's advanced tools with the standard Select → Edit access
 * bulk-sharing flow. Create is a hand-off, not an in-app dialog: tool content
 * is authored in the external service (rows sync back into the advanced_tools
 * table), so the "New" button opens the embedded page with a "new" intent
 * instead of POSTing a row here.
 */
export const AdvancedToolsView = ({ fixedInitiativeId, canCreate }: AdvancedToolsViewProps) => {
  const { t } = useTranslation(["advancedTools", "access"]);
  const { advancedTool } = useAppConfig();
  const serviceName = advancedTool?.name ?? t("title");

  // "Create" is a hand-off: authoring happens fully in the external service, so
  // the shared button opens the embedded page with a create intent rather than
  // POSTing a row here (our table only stores what that service builds).
  const createButton = (
    <ToolCreateButton tool={Tool.advanced_tool} initiativeId={fixedInitiativeId} variant="button" />
  );

  const toolsQuery = useAdvancedToolsList({
    initiative_id: fixedInitiativeId,
    page: 1,
    page_size: 50,
  });
  const tools = toolsQuery.data?.items ?? [];

  const selection = useGridSelection<(typeof tools)[number]>();
  const [bulkAccessOpen, setBulkAccessOpen] = useState(false);

  return (
    <div className="space-y-6">
      {/* Header note + button only when tools exist; the empty state below
          carries its own note + button, so exactly one shows in every case. */}
      {canCreate && tools.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="flex items-center gap-2 text-muted-foreground text-sm">
            <ExternalLink className="h-4 w-4" />
            {t("createdExternally", { name: serviceName })}
          </p>
          {createButton}
        </div>
      )}

      {toolsQuery.isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("loading")}
        </div>
      ) : toolsQuery.isError ? (
        <p className="text-destructive text-sm">{t("loadError")}</p>
      ) : tools.length > 0 ? (
        <>
          {selection.active ? (
            <BulkAccessBar
              count={selection.selectedItems.length}
              canManage={canManageSharing(selection.selectedItems)}
              onEditAccess={() => setBulkAccessOpen(true)}
              onExit={selection.exit}
            />
          ) : (
            <div className="flex justify-end">
              <Button variant="outline" size="sm" onClick={selection.enter}>
                {t("access:bulkBar.select")}
              </Button>
            </div>
          )}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {tools.map((tool) => (
              <SelectableGridItem
                key={tool.id}
                active={selection.active}
                selected={selection.selectedIds.has(tool.id)}
                onToggle={() => selection.toggle(tool)}
                label={tool.name}
              >
                <AdvancedToolCard tool={tool} />
              </SelectableGridItem>
            ))}
          </div>
        </>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t("noTools")}</CardTitle>
            <CardDescription>{t("noToolsDescription", { name: serviceName })}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-muted-foreground text-sm">
              {t("createdExternally", { name: serviceName })}
            </p>
            {canCreate && createButton}
          </CardContent>
        </Card>
      )}

      <BulkEditAccessDialog
        open={bulkAccessOpen}
        onOpenChange={setBulkAccessOpen}
        // This view is initiative-scoped, so every listed row carries this
        // initiative's id (guild-wide rows have NULL and are not listed here —
        // the backend rejects sharing them anyway).
        items={selection.selectedItems.map((item) => ({
          ...item,
          initiative_id: item.initiative_id ?? fixedInitiativeId,
        }))}
        resourceType={Tool.advanced_tool}
        invalidate={invalidateAllAdvancedTools}
        onSuccess={selection.exit}
      />
    </div>
  );
};
