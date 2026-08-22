import { useRouter } from "@tanstack/react-router";
import { Copy } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
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
import { useDuplicateCounterGroup } from "@/hooks/useCounters";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";
import { toolSettingsRoute } from "@/lib/tools";

type DuplicateCounterGroupCardProps = {
  groupId: number;
  groupName: string;
};

/** Counter groups' only tool-specific setting: copy the group and its counters. */
export const DuplicateCounterGroupCard = ({
  groupId,
  groupName,
}: DuplicateCounterGroupCardProps) => {
  const { t } = useTranslation(["counterGroups", "common"]);
  const router = useRouter();
  const gp = useGuildPath();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [name, setName] = useState("");

  const duplicateGroup = useDuplicateCounterGroup(groupId, {
    onSuccess: (created) => {
      toast.success(t("duplicate.success"));
      setDialogOpen(false);
      router.navigate({
        to: gp(toolSettingsRoute(Tool.counter_group, created.initiative_id, created.id)),
      });
    },
  });

  const openDialog = () => {
    setName(t("duplicate.defaultName", { name: groupName }));
    setDialogOpen(true);
  };

  const handleDuplicate = () => duplicateGroup.mutate({ name: name.trim() || undefined });

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t("duplicate.title")}</CardTitle>
          <CardDescription>{t("duplicate.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button type="button" variant="outline" onClick={openDialog}>
            <Copy className="h-4 w-4" />
            {t("duplicate.action")}
          </Button>
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("duplicate.title")}</DialogTitle>
            <DialogDescription>{t("duplicate.dialogDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="duplicate-counter-group-name">{t("common:name")}</Label>
            <Input
              id="duplicate-counter-group-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("common:toolSettings.namePlaceholder")}
              onKeyDown={(e) => {
                if (e.key === "Enter" && name.trim()) handleDuplicate();
              }}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDialogOpen(false)}
              disabled={duplicateGroup.isPending}
            >
              {t("common:cancel")}
            </Button>
            <Button
              type="button"
              onClick={handleDuplicate}
              disabled={duplicateGroup.isPending || !name.trim()}
            >
              {duplicateGroup.isPending ? t("duplicate.duplicating") : t("duplicate.action")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};
