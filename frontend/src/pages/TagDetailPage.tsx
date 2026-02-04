import { useState } from "react";
import { toast } from "sonner";
import { Navigate, useParams, Link, useRouter } from "@tanstack/react-router";
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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const TagDetailPage = () => {
  const { tagId: tagIdParam } = useParams({ strict: false }) as { tagId: string };
  const parsedTagId = Number(tagIdParam);
  const hasValidTagId = Number.isFinite(parsedTagId) && parsedTagId > 0;
  const tagId = hasValidTagId ? parsedTagId : null;

  const router = useRouter();

  const { data: tag, isLoading: tagLoading, error: tagError } = useTag(tagId);
  const { data: entities, isLoading: entitiesLoading } = useTagEntities(tagId);
  const deleteTagMutation = useDeleteTag();
  const updateTagMutation = useUpdateTag();

  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [editColor, setEditColor] = useState("");

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
                <h1 className="text-2xl font-bold">{tag.name}</h1>
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

      {/* Content */}
      {entitiesLoading ? (
        <div className="flex h-32 items-center justify-center">
          <Loader2 className="text-muted-foreground h-6 w-6 animate-spin" />
        </div>
      ) : (
        <div className="grid gap-6 md:grid-cols-3">
          {/* Tasks */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <SquareCheckBig className="h-4 w-4" />
                Tasks
              </CardTitle>
              <CardDescription>
                {taskCount} task{taskCount === 1 ? "" : "s"}
              </CardDescription>
            </CardHeader>
            <CardContent className="max-h-64 space-y-2 overflow-y-auto">
              {taskCount === 0 ? (
                <p className="text-muted-foreground text-sm">No tasks with this tag</p>
              ) : (
                entities?.tasks.map((task) => (
                  <Link
                    key={task.id}
                    to="/tasks/$taskId"
                    params={{ taskId: String(task.id) }}
                    className="hover:bg-accent block rounded-md p-2 transition-colors"
                  >
                    <p className="text-sm font-medium">{task.title}</p>
                    {task.project_name && (
                      <p className="text-muted-foreground text-xs">{task.project_name}</p>
                    )}
                  </Link>
                ))
              )}
            </CardContent>
          </Card>

          {/* Projects */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <ListTodo className="h-4 w-4" />
                Projects
              </CardTitle>
              <CardDescription>
                {projectCount} project{projectCount === 1 ? "" : "s"}
              </CardDescription>
            </CardHeader>
            <CardContent className="max-h-64 space-y-2 overflow-y-auto">
              {projectCount === 0 ? (
                <p className="text-muted-foreground text-sm">No projects with this tag</p>
              ) : (
                entities?.projects.map((project) => (
                  <Link
                    key={project.id}
                    to="/projects/$projectId"
                    params={{ projectId: String(project.id) }}
                    className="hover:bg-accent block rounded-md p-2 transition-colors"
                  >
                    <p className="text-sm font-medium">{project.name}</p>
                    {project.initiative_name && (
                      <p className="text-muted-foreground text-xs">{project.initiative_name}</p>
                    )}
                  </Link>
                ))
              )}
            </CardContent>
          </Card>

          {/* Documents */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <ScrollText className="h-4 w-4" />
                Documents
              </CardTitle>
              <CardDescription>
                {documentCount} document{documentCount === 1 ? "" : "s"}
              </CardDescription>
            </CardHeader>
            <CardContent className="max-h-64 space-y-2 overflow-y-auto">
              {documentCount === 0 ? (
                <p className="text-muted-foreground text-sm">No documents with this tag</p>
              ) : (
                entities?.documents.map((doc) => (
                  <Link
                    key={doc.id}
                    to="/documents/$documentId"
                    params={{ documentId: String(doc.id) }}
                    className="hover:bg-accent block rounded-md p-2 transition-colors"
                  >
                    <p className="text-sm font-medium">{doc.title}</p>
                    {doc.initiative_name && (
                      <p className="text-muted-foreground text-xs">{doc.initiative_name}</p>
                    )}
                  </Link>
                ))
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
};
