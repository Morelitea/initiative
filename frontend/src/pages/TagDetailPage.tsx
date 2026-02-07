import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Navigate, useParams, useRouter } from "@tanstack/react-router";
import {
  Loader2,
  ScrollText,
  ListTodo,
  SquareCheckBig,
  Settings,
  Trash2,
  TagIcon,
} from "lucide-react";

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
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-muted-foreground">Tag not found</p>
      </div>
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
      toast.success("Tag deleted");
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
                  {updateTagMutation.isPending ? "Saving..." : "Save"}
                </Button>
                <Button size="sm" variant="ghost" onClick={handleCancelEdit}>
                  Cancel
                </Button>
              </div>
            ) : (
              <>
                <h1 className="text-3xl font-semibold tracking-tight">{tag.name}</h1>
                <p className="text-muted-foreground text-sm">
                  {totalCount} tagged item{totalCount === 1 ? "" : "s"}
                </p>
              </>
            )}
          </div>
        </div>

        {!isEditing && (
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={handleStartEdit}>
              <Settings className="mr-1 h-4 w-4" />
              Edit
            </Button>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="destructive" size="sm">
                  <Trash2 className="mr-1 h-4 w-4" />
                  Delete
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete tag?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This will remove the tag &quot;{tag.name}&quot; from all tasks, projects, and
                    documents. This action cannot be undone.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => void handleDelete()}
                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  >
                    Delete
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
            Tasks ({taskCount})
          </TabsTrigger>
          <TabsTrigger value="projects" className="inline-flex items-center gap-2">
            <ListTodo className="h-4 w-4" />
            Projects ({projectCount})
          </TabsTrigger>
          <TabsTrigger value="documents" className="inline-flex items-center gap-2">
            <ScrollText className="h-4 w-4" />
            Documents ({documentCount})
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
