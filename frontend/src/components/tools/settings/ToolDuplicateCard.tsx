/**
 * Copying a tool, with everything inside it, into an initiative.
 *
 * One card for every tool that can be copied, because a copy is one route for
 * every kind (`POST /{tool}/{id}/duplicate`): the server takes the same steps
 * for all of them, and the only choices left are where the copy goes and what
 * it is called.
 */

import { useRouter } from "@tanstack/react-router";
import { Copy } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  type ToolSettingsEntity,
  useToolSettings,
} from "@/components/tools/settings/ToolSettingsContext";
import { Button } from "@/components/ui/button";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { TOOL_HOOKS, useDuplicateTool } from "@/hooks/toolHooks";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";
import { toolDetailRoute } from "@/lib/tools";

/** Whether this viewer may copy it: write on it, or read on a template, which
 *  is made to be copied. Where the copy may go is the dialog's question. */
export const canUseDuplicateCard = (tool: Tool, entity: ToolSettingsEntity): boolean =>
  Boolean(TOOL_HOOKS[tool].duplicate) && (entity.can.edit || Boolean(entity.is_template));

export const ToolDuplicateCard = () => {
  const { t } = useTranslation("common");
  const router = useRouter();
  const gp = useGuildPath();
  const { tool, entity } = useToolSettings();
  const { creatableInitiatives } = useToolCreateAccess(tool);

  const [open, setOpen] = useState(false);
  const [initiativeId, setInitiativeId] = useState("");
  const [name, setName] = useState("");

  const suggestedName = (id: string) =>
    id === String(entity.initiative_id)
      ? t("toolSettings.duplicate.defaultName", { name: entity.name })
      : entity.name;

  const duplicate = useDuplicateTool(tool, {
    onSuccess: (copy) => {
      const initiative = creatableInitiatives.find((i) => i.id === copy.initiative_id);
      toast.success(t("toolSettings.duplicate.duplicated", { initiative: initiative?.name }));
      setOpen(false);
      router.navigate({ to: gp(toolDetailRoute(tool, copy.initiative_id, copy.id)) });
    },
  });

  if (!canUseDuplicateCard(tool, entity) || creatableInitiatives.length === 0) {
    return null;
  }

  const openDialog = () => {
    const here = creatableInitiatives.some((i) => i.id === entity.initiative_id);
    const id = String(here ? entity.initiative_id : creatableInitiatives[0].id);
    setInitiativeId(id);
    setName(suggestedName(id));
    setOpen(true);
  };

  // A name still the suggestion follows the initiative; one typed stays.
  const chooseInitiative = (id: string) => {
    if (name === suggestedName(initiativeId)) setName(suggestedName(id));
    setInitiativeId(id);
  };

  const submit = () => {
    if (!name.trim()) return;
    duplicate.mutate({
      id: entity.id,
      data: { name: name.trim(), target_initiative_id: Number(initiativeId) },
    });
  };

  return (
    <>
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("toolSettings.duplicate.title")}</CardTitle>
          <CardDescription>{t("toolSettings.duplicate.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button type="button" variant="outline" onClick={openDialog}>
            <Copy className="h-4 w-4" />
            {t("toolSettings.duplicate.action")}
          </Button>
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-card">
          <DialogHeader>
            <DialogTitle>
              {t("toolSettings.duplicate.dialogTitle", { name: entity.name })}
            </DialogTitle>
            <DialogDescription>{t("toolSettings.duplicate.description")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="duplicate-initiative">{t("toolSettings.duplicate.initiative")}</Label>
              <Select value={initiativeId} onValueChange={chooseInitiative}>
                <SelectTrigger id="duplicate-initiative">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {creatableInitiatives.map((initiative) => (
                    <SelectItem key={initiative.id} value={String(initiative.id)}>
                      {initiative.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="duplicate-name">{t("name")}</Label>
              <Input
                id="duplicate-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t("toolSettings.namePlaceholder")}
                onKeyDown={(event) => {
                  if (event.key === "Enter") submit();
                }}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={duplicate.isPending}
            >
              {t("cancel")}
            </Button>
            <Button type="button" onClick={submit} disabled={duplicate.isPending || !name.trim()}>
              {duplicate.isPending
                ? t("toolSettings.duplicate.duplicating")
                : t("toolSettings.duplicate.action")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};
