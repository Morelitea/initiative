import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Navigate, useParams, useRouter } from "@tanstack/react-router";
import {
  Loader2,
  ScrollText,
  ListTodo,
  SearchX,
  SquareCheckBig,
  Settings,
  Trash2,
  TagIcon,
} from "lucide-react";
import { StatusMessage } from "@/components/StatusMessage";

import { useTag, useTagEntities, useDeleteTag, useUpdateTag } from "@/hooks/useTags";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TagTasksTable } from "@/components/tasks/TagTasksTable";
import { ProjectsView } from "@/pages/ProjectsPage";
import { DocumentsView } from "@/pages/DocumentsPage";

export const TagDetailPage = () => {
  const { t } = useTranslation(["tags", "common"]);
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
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="text-muted-foreground h-8 w-8 animate-spin" />
      </div>
    );
  }

  if (tagError || !tag) {
    return <StatusMessage icon={<SearchX />} title={t("detail.notFound")} description={t("detail.notFoundDescription")} backTo="/" backLabel={t("detail.backToTags")} />;
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

  const taskCount = entities?.tasks.length ?? 0;
  const projectCount = entities?.projects.length ?? 0;
  const documentCount = entities?.documents.length ?? 0;
  const totalCount = taskCount + projectCount + documentCount;

  return (
    <div className="container mx-auto space-y-6 p-6">
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
                <h1 className="text-3xl font-semibold tracking-tight">{tag.name}</h1>
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
              <Settings className="mr-1 h-4 w-4" />
              {t("detail.edit")}
            </Button>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="destructive" size="sm">
                  <Trash2 className="mr-1 h-4 w-4" />
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

      {/* Tabbed Content */}
      <Tabs defaultValue="tasks" className="space-y-4">
        <TabsList>
          <TabsTrigger value="tasks" className="inline-flex items-center gap-2">
            <SquareCheckBig className="h-4 w-4" />
            {t("detail.tasksTab", { count: taskCount })}
          </TabsTrigger>
          <TabsTrigger value="projects" className="inline-flex items-center gap-2">
            <ListTodo className="h-4 w-4" />
            {t("detail.projectsTab", { count: projectCount })}
          </TabsTrigger>
          <TabsTrigger value="documents" className="inline-flex items-center gap-2">
            <ScrollText className="h-4 w-4" />
            {t("detail.documentsTab", { count: documentCount })}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="tasks">
          <TagTasksTable tagId={parsedTagId} />
        </TabsContent>
        <TabsContent value="projects">
          <ProjectsView fixedTagIds={[parsedTagId]} canCreate={false} />
        </TabsContent>
        <TabsContent value="documents">
          <DocumentsView fixedTagIds={[parsedTagId]} canCreate={false} />
        </TabsContent>
      </Tabs>
    </div>
  );
};
