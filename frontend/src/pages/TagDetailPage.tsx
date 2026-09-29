import { Navigate, useParams, useRouter } from "@tanstack/react-router";
import { SearchX, Settings, TagIcon, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { StatusMessage } from "@/components/StatusMessage";
import { SearchResultRow } from "@/components/search/SearchResultRow";
import { TagDetailSkeleton } from "@/components/skeletons/PageSkeletons";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { Input } from "@/components/ui/input";
import { Tabs, TabsBar, TabsContent, TabsTrigger } from "@/components/ui/tabs";
import { useDeleteTag, useTag, useTagEntities, useUpdateTag } from "@/hooks/useTags";
import { toast } from "@/lib/chesterToast";
import { TOOL_ICONS, TOOLS, toolNavLabelKey } from "@/lib/tools";

export const TagDetailPage = () => {
  const { t } = useTranslation(["tags", "common", "nav"]);
  const { tagId: tagIdParam } = useParams({ strict: false }) as { tagId: string };
  const parsedTagId = Number(tagIdParam);
  const hasValidTagId = Number.isFinite(parsedTagId) && parsedTagId > 0;
  const tagId = hasValidTagId ? parsedTagId : null;

  const router = useRouter();

  const { data: tag, isLoading: tagLoading, error: tagError } = useTag(tagId);
  const { data: entities } = useTagEntities(tagId);
  const deleteTagMutation = useDeleteTag();
  const updateTagMutation = useUpdateTag();

  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [editColor, setEditColor] = useState("");

  // Reset edit state when navigating between tags
  useEffect(() => {
    setIsEditing(false);
    setEditName("");
    setEditColor("");
  }, [parsedTagId]);

  if (!hasValidTagId) {
    return <Navigate to="/" replace />;
  }

  if (tagLoading) {
    return <TagDetailSkeleton />;
  }

  if (tagError || !tag) {
    return (
      <StatusMessage
        icon={<SearchX />}
        title={t("detail.notFound")}
        description={t("detail.notFoundDescription")}
        backTo="/"
        backLabel={t("detail.backToTags")}
      />
    );
  }

  const handleStartEdit = () => {
    setEditName(tag.name);
    setEditColor(tag.color);
    setIsEditing(true);
  };

  const handleCancelEdit = () => {
    setIsEditing(false);
    setEditName("");
    setEditColor("");
  };

  const handleSaveEdit = async () => {
    if (!editName.trim()) return;

    try {
      await updateTagMutation.mutateAsync({
        tagId: tag.id,
        data: {
          name: editName.trim(),
          color: editColor,
        },
      });
      setIsEditing(false);
    } catch {
      // Error handled by mutation
    }
  };

  const handleDelete = async () => {
    try {
      await deleteTagMutation.mutateAsync(tag.id);
      toast.success(t("detail.deleted"));
      router.navigate({ to: "/" });
    } catch {
      // Error handled by mutation
    }
  };

  const items = entities?.items ?? [];
  const totalCount = items.length;
  // One tab per tool holding something with this tag. Every row names the tool
  // it lives in, so a task sits under Projects and a page under Wikis.
  const groups = TOOLS.map((tool) => ({
    tool,
    hits: items.filter((item) => item.tool === tool),
  })).filter(({ hits }) => hits.length > 0);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <TagIcon className="h-8 w-8 shrink-0" style={{ color: tag.color }} />
          <div>
            {isEditing ? (
              <div className="flex items-center gap-2">
                <Input
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="h-9 w-64"
                  autoFocus
                />
                <ColorPickerPopover value={editColor} onChange={setEditColor} className="h-9" />
                <Button
                  size="sm"
                  onClick={() => void handleSaveEdit()}
                  disabled={!editName.trim() || updateTagMutation.isPending}
                >
                  {updateTagMutation.isPending ? t("detail.saving") : t("detail.save")}
                </Button>
                <Button size="sm" variant="ghost" onClick={handleCancelEdit}>
                  {t("common:cancel")}
                </Button>
              </div>
            ) : (
              <>
                <h1 className="font-semibold text-3xl tracking-tight">{tag.name}</h1>
                <p className="text-muted-foreground text-sm">
                  {t("detail.taggedItems", { count: totalCount })}
                </p>
              </>
            )}
          </div>
        </div>

        {!isEditing && (
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={handleStartEdit}>
              <Settings className="h-4 w-4" />
              {t("detail.edit")}
            </Button>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="destructive" size="sm">
                  <Trash2 className="h-4 w-4" />
                  {t("detail.delete")}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>{t("detail.deleteTitle")}</AlertDialogTitle>
                  <AlertDialogDescription>
                    {t("detail.deleteDescription", { name: tag.name })}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>{t("common:cancel")}</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => void handleDelete()}
                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  >
                    {t("detail.delete")}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        )}
      </div>

      {groups.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("detail.empty")}</p>
      ) : (
        <Tabs defaultValue={groups[0].tool} className="space-y-4">
          <TabsBar>
            {groups.map(({ tool, hits }) => {
              const Icon = TOOL_ICONS[tool];
              return (
                <TabsTrigger key={tool} value={tool} className="inline-flex items-center gap-2">
                  <Icon className="h-4 w-4" />
                  {t("detail.toolTab", {
                    tool: t(toolNavLabelKey(tool), { ns: "nav" }),
                    count: hits.length,
                  })}
                </TabsTrigger>
              );
            })}
          </TabsBar>
          {groups.map(({ tool, hits }) => (
            <TabsContent key={tool} value={tool}>
              {hits.map((hit) => (
                <SearchResultRow key={`${hit.entity_type}-${hit.entity_id}`} hit={hit} />
              ))}
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
  );
};
