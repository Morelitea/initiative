/**
 * THE settings page every tool gets.
 *
 * Rename, describe, tag, share, and delete are identical for all six tools, so
 * they live here once. Everything the page needs is derived from the `tool`
 * value — breadcrumb labels, list/detail routes, the tag mutation — and all of
 * its copy comes from the shared `common:toolSettings.*` namespace, so adding a
 * tool costs a wrapper that names its data hooks and nothing else.
 *
 * A tool with genuinely extra settings passes them as `detailsExtra` /
 * `advancedExtra` rather than as configuration; the shell stays the same shape
 * for every tool.
 */

import { useRouter } from "@tanstack/react-router";
import { Loader2, Trash2 } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ResourceGrantSchema, TagSummary, Tool } from "@/api/generated/initiativeAPI.schemas";
import { ShareControl } from "@/components/access/ShareControl";
import { TagPicker } from "@/components/tags";
import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useSetToolTags } from "@/hooks/useToolTags";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";
import { hasWriteAccess } from "@/lib/permissions";
import { toolDetailRoute, toolListRoute } from "@/lib/tools";

/**
 * The slice of a tool's read schema this page needs. Queues, counter groups,
 * calendars, dashboards, and projects satisfy it as-is; documents map `title`
 * onto `name` in their wrapper.
 */
export interface ToolSettingsEntity {
  id: number;
  name: string;
  description?: string | null;
  initiative_id: number | null;
  my_permission_level: string | null;
  tags: TagSummary[];
  grants: ResourceGrantSchema[];
}

/** Per-call callbacks so this page — not each wrapper — owns toasts and routing. */
type MutateOptions = { onSuccess?: () => void };

interface ToolMutation<TVars> {
  mutate: (vars: TVars, options?: MutateOptions) => void;
  isPending: boolean;
}

export interface ToolSettingsPageProps {
  tool: Tool;
  entity: ToolSettingsEntity | undefined;
  isLoading: boolean;
  isError: boolean;
  /**
   * The rename/describe mutation. Omit it to drop the built-in details form —
   * projects save those fields through their own richer form, and a document's
   * name is its title, edited in the editor.
   */
  update?: ToolMutation<{ name?: string; description?: string | null }>;
  setGrants: ToolMutation<ResourceGrantSchema[]>;
  remove: ToolMutation<number>;
  /** Extra cards for the Details tab, e.g. a project's dates or a calendar's color. */
  detailsExtra?: ReactNode;
  /** Extra cards for the Advanced tab, e.g. duplicate, archive, or export. */
  advancedExtra?: ReactNode;
  /** Whole extra tabs, for settings too large to sit in a card (project task statuses). */
  extraTabs?: { value: string; label: string; content: ReactNode }[];
  /** Rendered outside the tabs — dialogs a tool's extras need. */
  children?: ReactNode;
}

export const ToolSettingsPage = ({
  tool,
  entity,
  isLoading,
  isError,
  update,
  setGrants,
  remove,
  detailsExtra,
  advancedExtra,
  extraTabs = [],
  children,
}: ToolSettingsPageProps) => {
  const { t } = useTranslation(["common", "nav", "access"]);
  const router = useRouter();
  const gp = useGuildPath();

  const [nameValue, setNameValue] = useState("");
  const [descriptionValue, setDescriptionValue] = useState("");
  const [tags, setTags] = useState<TagSummary[]>([]);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  useEffect(() => {
    if (!entity) return;
    setNameValue(entity.name);
    setDescriptionValue(entity.description ?? "");
    setTags(entity.tags ?? []);
  }, [entity]);

  const setToolTags = useSetToolTags(tool);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("common:loading")}
      </div>
    );
  }

  if (isError || !entity) {
    return <p className="text-destructive">{t("common:toolSettings.notFound")}</p>;
  }

  const canManage = hasWriteAccess(entity.my_permission_level);
  const isOwner = entity.my_permission_level === "owner";
  const ownerId = entity.grants.find((g) => g.level === "owner")?.user_id ?? null;

  const handleDetailsSave = () => {
    const trimmedName = nameValue.trim();
    if (!trimmedName) return;
    update?.mutate(
      { name: trimmedName, description: descriptionValue.trim() || null },
      { onSuccess: () => toast.success(t("common:toolSettings.detailsUpdated")) }
    );
  };

  const handleDelete = () => {
    remove.mutate(entity.id, {
      onSuccess: () => {
        toast.success(t("common:toolSettings.deleted", { name: entity.name }));
        setDeleteDialogOpen(false);
        router.navigate({ to: gp(toolListRoute(tool)) });
      },
    });
  };

  return (
    <div className="space-y-6">
      <ToolBreadcrumb
        tool={tool}
        initiativeId={entity.initiative_id}
        trail={[
          { label: entity.name, to: toolDetailRoute(tool, entity.id) },
          { label: t("common:toolSettings.title") },
        ]}
      />

      <div className="space-y-1">
        <h1 className="font-semibold text-3xl tracking-tight">{t("common:toolSettings.title")}</h1>
        <p className="text-muted-foreground text-sm">{t("common:toolSettings.description")}</p>
      </div>

      <Tabs defaultValue="details" className="space-y-4">
        <TabsList className="w-full max-w-xl justify-start">
          <TabsTrigger value="details">{t("common:toolSettings.tabDetails")}</TabsTrigger>
          {canManage && (
            <TabsTrigger value="access">{t("common:toolSettings.tabAccess")}</TabsTrigger>
          )}
          {extraTabs.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}>
              {tab.label}
            </TabsTrigger>
          ))}
          <TabsTrigger value="advanced">{t("common:toolSettings.tabAdvanced")}</TabsTrigger>
        </TabsList>

        <TabsContent value="details" className="space-y-6">
          {update && (
            <Card>
              <CardHeader>
                <CardTitle>{t("common:toolSettings.tabDetails")}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="tool-settings-name">{t("common:name")}</Label>
                  <Input
                    id="tool-settings-name"
                    value={nameValue}
                    onChange={(e) => setNameValue(e.target.value)}
                    placeholder={t("common:toolSettings.namePlaceholder")}
                    disabled={!canManage}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="tool-settings-description">{t("common:description")}</Label>
                  <Textarea
                    id="tool-settings-description"
                    value={descriptionValue}
                    onChange={(e) => setDescriptionValue(e.target.value)}
                    placeholder={t("common:toolSettings.descriptionPlaceholder")}
                    disabled={!canManage}
                    rows={3}
                  />
                </div>
                {canManage && (
                  <Button
                    onClick={handleDetailsSave}
                    disabled={update.isPending || !nameValue.trim()}
                  >
                    {update.isPending ? t("common:toolSettings.saving") : t("common:save")}
                  </Button>
                )}
              </CardContent>
            </Card>
          )}

          {detailsExtra}

          <Card>
            <CardHeader>
              <CardTitle>{t("common:toolSettings.tags")}</CardTitle>
              <CardDescription>{t("common:toolSettings.tagsDescription")}</CardDescription>
            </CardHeader>
            <CardContent>
              {canManage ? (
                <TagPicker
                  selectedTags={tags}
                  onChange={(newTags) => {
                    // Tags persist on pick rather than with a Save button, so the
                    // picker shows the new selection immediately and puts the old
                    // one back if the write fails.
                    const previous = tags;
                    setTags(newTags);
                    setToolTags.mutate(
                      { id: entity.id, tagIds: newTags.map((tag) => tag.id) },
                      { onError: () => setTags(previous) }
                    );
                  }}
                />
              ) : (
                <p className="text-muted-foreground text-sm">
                  {t("common:toolSettings.tagsNoAccess")}
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {canManage && (
          <TabsContent value="access" className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>{t("common:toolSettings.tabAccess")}</CardTitle>
                <CardDescription>{t("access:share.settingsDescription")}</CardDescription>
              </CardHeader>
              <CardContent>
                <ShareControl
                  initiativeId={entity.initiative_id ?? 0}
                  grants={entity.grants}
                  ownerId={ownerId}
                  onChange={(grants) =>
                    setGrants.mutate(grants, {
                      onSuccess: () => toast.success(t("common:toolSettings.permissionsUpdated")),
                    })
                  }
                  disabled={!isOwner || setGrants.isPending}
                />
              </CardContent>
            </Card>
          </TabsContent>
        )}

        {extraTabs.map((tab) => (
          <TabsContent key={tab.value} value={tab.value} className="space-y-6">
            {tab.content}
          </TabsContent>
        ))}

        <TabsContent value="advanced" className="space-y-6">
          {advancedExtra}

          {isOwner && (
            <Card className="border-destructive/40 bg-destructive/5 shadow-sm">
              <CardHeader>
                <CardTitle>{t("common:toolSettings.dangerZone")}</CardTitle>
                <CardDescription>{t("common:toolSettings.dangerZoneDescription")}</CardDescription>
              </CardHeader>
              <CardContent>
                <Button
                  type="button"
                  variant="destructive"
                  onClick={() => setDeleteDialogOpen(true)}
                >
                  <Trash2 className="h-4 w-4" />
                  {t("common:delete")}
                </Button>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>

      <ConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        title={t("common:toolSettings.deleteConfirmTitle", { name: entity.name })}
        description={t("common:toolSettings.deleteConfirmDescription")}
        confirmLabel={t("common:delete")}
        cancelLabel={t("common:cancel")}
        onConfirm={handleDelete}
        isLoading={remove.isPending}
        destructive
      />

      {children}
    </div>
  );
};
