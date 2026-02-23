import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useCreateProject, useTemplateProjects } from "@/hooks/useProjects";
import { EmojiPicker } from "@/components/EmojiPicker";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  CreateAccessControl,
  type RoleGrant,
  type UserGrant,
} from "@/components/access/CreateAccessControl";
import type { InitiativeRead } from "@/api/generated/initiativeAPI.schemas";

const NO_TEMPLATE_VALUE = "template-none";

type CreateProjectDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  lockedInitiativeId: number | null;
  lockedInitiativeName: string | null;
  creatableInitiatives: InitiativeRead[];
  initiativesQuery: { isLoading: boolean; isError: boolean };
  defaultInitiativeId: string | null;
  onCreated: () => void;
};

export const CreateProjectDialog = ({
  open,
  onOpenChange,
  lockedInitiativeId,
  lockedInitiativeName,
  creatableInitiatives,
  initiativesQuery,
  defaultInitiativeId,
  onCreated,
}: CreateProjectDialogProps) => {
  const { t } = useTranslation(["projects", "common"]);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [icon, setIcon] = useState("");
  const [initiativeId, setInitiativeId] = useState<string | null>(defaultInitiativeId);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>(NO_TEMPLATE_VALUE);
  const [isTemplateProject, setIsTemplateProject] = useState(false);
  const [roleGrants, setRoleGrants] = useState<RoleGrant[]>([]);
  const [userGrants, setUserGrants] = useState<UserGrant[]>([]);
  const [accessLoading, setAccessLoading] = useState(false);

  const templatesQuery = useTemplateProjects();

  // Sync initiative ID from parent when dialog opens or default changes
  useEffect(() => {
    if (defaultInitiativeId) {
      setInitiativeId(defaultInitiativeId);
    }
  }, [defaultInitiativeId]);

  // Sync description from selected template
  useEffect(() => {
    if (isTemplateProject) {
      return;
    }
    if (selectedTemplateId === NO_TEMPLATE_VALUE) {
      return;
    }
    const templateId = Number(selectedTemplateId);
    if (!Number.isFinite(templateId)) {
      return;
    }
    const template = templatesQuery.data?.items?.find((item) => item.id === templateId);
    if (!template) {
      return;
    }
    setDescription(template.description ?? "");
  }, [selectedTemplateId, templatesQuery.data, isTemplateProject]);

  const createProjectMutation = useCreateProject();
  const createProject = {
    ...createProjectMutation,
    mutate: () => {
      const payload: Record<string, unknown> = { name, description };
      const trimmedIcon = icon.trim();
      if (trimmedIcon) {
        payload.icon = trimmedIcon;
      }
      const selectedInitiativeId = initiativeId ? Number(initiativeId) : undefined;
      if (!selectedInitiativeId || Number.isNaN(selectedInitiativeId)) {
        return;
      }
      payload.initiative_id = selectedInitiativeId;
      payload.is_template = isTemplateProject;
      if (!isTemplateProject && selectedTemplateId !== NO_TEMPLATE_VALUE) {
        payload.template_id = Number(selectedTemplateId);
      }
      if (roleGrants.length > 0) {
        payload.role_permissions = roleGrants;
      }
      if (userGrants.length > 0) {
        payload.user_permissions = userGrants;
      }
      createProjectMutation.mutate(
        payload as unknown as Parameters<typeof createProjectMutation.mutate>[0],
        {
          onSuccess: () => {
            setName("");
            setDescription("");
            setIcon("");
            setInitiativeId(null);
            setSelectedTemplateId(NO_TEMPLATE_VALUE);
            setIsTemplateProject(false);
            setRoleGrants([]);
            setUserGrants([]);
            onCreated();
          },
        }
      );
    },
    isPending: createProjectMutation.isPending,
    isError: createProjectMutation.isError,
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    createProject.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-card max-h-screen overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("createDialog.title")}</DialogTitle>
          <DialogDescription>{t("createDialog.description")}</DialogDescription>
        </DialogHeader>
        <form className="w-full max-w-lg" onSubmit={handleSubmit}>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="project-icon">{t("createDialog.iconLabel")}</Label>
              <EmojiPicker
                id="project-icon"
                value={icon || undefined}
                onChange={(emoji) => setIcon(emoji ?? "")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="project-name">{t("createDialog.nameLabel")}</Label>
              <Input
                id="project-name"
                placeholder={t("createDialog.namePlaceholder")}
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="project-description">{t("createDialog.descriptionLabel")}</Label>
              <Textarea
                id="project-description"
                placeholder={t("createDialog.descriptionPlaceholder")}
                rows={3}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>{t("createDialog.initiativeLabel")}</Label>
              {lockedInitiativeId ? (
                <div className="rounded-md border px-3 py-2 text-sm">
                  {lockedInitiativeName ?? t("filters.selectedInitiative")}
                </div>
              ) : initiativesQuery.isLoading ? (
                <p className="text-muted-foreground text-sm">
                  {t("createDialog.loadingInitiatives")}
                </p>
              ) : initiativesQuery.isError ? (
                <p className="text-destructive text-sm">{t("createDialog.initiativeLoadError")}</p>
              ) : creatableInitiatives.length > 0 ? (
                <Select value={initiativeId ?? ""} onValueChange={setInitiativeId}>
                  <SelectTrigger>
                    <SelectValue placeholder={t("createDialog.selectInitiative")} />
                  </SelectTrigger>
                  <SelectContent>
                    {creatableInitiatives.map((initiative) => (
                      <SelectItem key={initiative.id} value={String(initiative.id)}>
                        {initiative.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <p className="text-muted-foreground text-sm">{t("createDialog.noInitiatives")}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="project-template">{t("createDialog.templateLabel")}</Label>
              {templatesQuery.isLoading ? (
                <p className="text-muted-foreground text-sm">
                  {t("createDialog.loadingTemplates")}
                </p>
              ) : templatesQuery.isError ? (
                <p className="text-destructive text-sm">{t("createDialog.templateLoadError")}</p>
              ) : (
                <Select
                  value={selectedTemplateId}
                  onValueChange={setSelectedTemplateId}
                  disabled={isTemplateProject}
                >
                  <SelectTrigger id="project-template">
                    <SelectValue placeholder={t("createDialog.noTemplate")} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_TEMPLATE_VALUE}>
                      {t("createDialog.noTemplate")}
                    </SelectItem>
                    {templatesQuery.data?.items?.map((template) => (
                      <SelectItem key={template.id} value={String(template.id)}>
                        {template.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              {isTemplateProject ? (
                <p className="text-muted-foreground text-xs">
                  {t("createDialog.disableTemplateHint")}
                </p>
              ) : null}
            </div>
            <div className="bg-muted/20 flex items-center justify-between rounded-lg border p-3">
              <div>
                <Label htmlFor="create-as-template" className="text-base">
                  {t("createDialog.saveAsTemplate")}
                </Label>
                <p className="text-muted-foreground text-xs">
                  {t("createDialog.saveAsTemplateHint")}
                </p>
              </div>
              <Switch
                id="create-as-template"
                checked={isTemplateProject}
                onCheckedChange={(checked) => {
                  const nextStatus = Boolean(checked);
                  setIsTemplateProject(nextStatus);
                  if (nextStatus) {
                    setSelectedTemplateId(NO_TEMPLATE_VALUE);
                  }
                }}
              />
            </div>
            <Accordion type="single" collapsible defaultValue="advanced">
              <AccordionItem value="advanced" className="border-b-0">
                <AccordionTrigger>{t("common:createAccess.advancedOptions")}</AccordionTrigger>
                <AccordionContent>
                  <CreateAccessControl
                    initiativeId={initiativeId ? Number(initiativeId) : null}
                    roleGrants={roleGrants}
                    onRoleGrantsChange={setRoleGrants}
                    userGrants={userGrants}
                    onUserGrantsChange={setUserGrants}
                    addAllMembersDefault
                    onLoadingChange={setAccessLoading}
                  />
                </AccordionContent>
              </AccordionItem>
            </Accordion>
            <div className="flex flex-wrap items-center gap-2">
              {createProject.isError ? (
                <p className="text-destructive text-sm">{t("createDialog.createError")}</p>
              ) : null}
              <div className="ml-auto flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={createProject.isPending}
                  onClick={() => onOpenChange(false)}
                >
                  {t("common:cancel")}
                </Button>
                <Button type="submit" disabled={createProject.isPending || accessLoading}>
                  {createProject.isPending
                    ? t("createDialog.creating")
                    : t("createDialog.createProject")}
                </Button>
              </div>
            </div>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
};
