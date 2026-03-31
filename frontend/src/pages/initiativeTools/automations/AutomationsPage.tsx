import { useCallback, useState } from "react";
import { Link, Navigate, useRouter, useSearch } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { formatDistanceToNow } from "date-fns";
import { Plus, Trash2, Zap } from "lucide-react";

import { useAutomationFlow } from "@/hooks/useAutomationFlow";
import { useGuildPath } from "@/lib/guildUrl";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

export const AutomationsPage = () => {
  const { t } = useTranslation(["automations", "initiatives", "nav", "common"]);
  const gp = useGuildPath();
  const router = useRouter();
  const search = useSearch({ strict: false }) as { initiativeId?: string };
  const initiativeId = search.initiativeId ?? "";

  const { flows, createFlow, deleteFlow } = useAutomationFlow(initiativeId);

  // Create dialog state
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");

  // Delete confirmation state
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const handleCreate = useCallback(() => {
    if (!newName.trim()) return;
    const flowId = createFlow(newName.trim(), newDescription.trim() || undefined);
    setCreateDialogOpen(false);
    setNewName("");
    setNewDescription("");
    void router.navigate({
      to: gp(`/automations/${flowId}`),
      search: { initiativeId },
    });
  }, [newName, newDescription, createFlow, router, gp, initiativeId]);

  const handleDelete = useCallback(() => {
    if (!deleteTarget) return;
    deleteFlow(deleteTarget);
    setDeleteTarget(null);
  }, [deleteTarget, deleteFlow]);

  if (!__ENABLE_AUTOMATIONS__) {
    return <Navigate to={gp("/initiatives")} replace />;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h1 className="text-3xl font-semibold tracking-tight">{t("nav:automations")}</h1>
          {search.initiativeId && (
            <p className="text-muted-foreground text-sm">{t("initiatives:automationsScoped")}</p>
          )}
        </div>
        <Button onClick={() => setCreateDialogOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          {t("automations:createAutomation")}
        </Button>
      </div>

      {/* Empty state */}
      {flows.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16">
          <div className="bg-primary/10 mb-4 flex h-16 w-16 items-center justify-center rounded-full">
            <Zap className="text-primary h-8 w-8" />
          </div>
          <h2 className="text-lg font-semibold">{t("automations:emptyState.title")}</h2>
          <p className="text-muted-foreground mt-1 max-w-md text-center text-sm">
            {t("automations:emptyState.description")}
          </p>
          <Button className="mt-6" onClick={() => setCreateDialogOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            {t("automations:createAutomation")}
          </Button>
        </div>
      )}

      {/* Flow cards grid */}
      {flows.length > 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {flows.map((flow) => (
            <Card key={flow.id} className="group hover:bg-accent/50 relative transition-colors">
              <Link
                to={gp(`/automations/${flow.id}`)}
                search={{ initiativeId }}
                className="absolute inset-0 z-0"
                aria-label={flow.name}
              />
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between">
                  <CardTitle className="text-base">{flow.name}</CardTitle>
                  <div className="flex items-center gap-2">
                    <Badge variant={flow.enabled ? "default" : "secondary"}>
                      {flow.enabled
                        ? t("automations:status.enabled")
                        : t("automations:status.disabled")}
                    </Badge>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="relative z-10 h-8 w-8 opacity-0 transition-opacity group-hover:opacity-100"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setDeleteTarget(flow.id);
                      }}
                      aria-label={t("automations:deleteAutomation")}
                    >
                      <Trash2 className="text-destructive h-4 w-4" />
                    </Button>
                  </div>
                </div>
                {flow.description && (
                  <CardDescription className="line-clamp-2">{flow.description}</CardDescription>
                )}
              </CardHeader>
              <CardContent>
                <div className="text-muted-foreground flex items-center justify-between text-xs">
                  <span>{t("automations:nodeCount", { count: flow.nodes.length })}</span>
                  <span>
                    {t("automations:lastUpdated", {
                      time: formatDistanceToNow(new Date(flow.updatedAt), {
                        addSuffix: true,
                      }),
                    })}
                  </span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Create dialog */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("automations:createDialog.title")}</DialogTitle>
            <DialogDescription>{t("automations:createDialog.description")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="automation-name">{t("automations:createDialog.nameLabel")}</Label>
              <Input
                id="automation-name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder={t("automations:createDialog.namePlaceholder")}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCreate();
                }}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="automation-description">
                {t("automations:createDialog.descriptionLabel")}
              </Label>
              <Textarea
                id="automation-description"
                value={newDescription}
                onChange={(e) => setNewDescription(e.target.value)}
                placeholder={t("automations:createDialog.descriptionPlaceholder")}
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateDialogOpen(false)}>
              {t("common:cancel")}
            </Button>
            <Button onClick={handleCreate} disabled={!newName.trim()}>
              {t("common:create")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation */}
      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title={t("automations:deleteDialog.title")}
        description={t("automations:deleteDialog.description")}
        confirmLabel={t("common:delete")}
        cancelLabel={t("common:cancel")}
        onConfirm={handleDelete}
        destructive
      />
    </div>
  );
};
