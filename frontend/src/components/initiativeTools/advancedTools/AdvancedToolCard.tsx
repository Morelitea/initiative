import { Sparkles, Tag as TagIcon } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { AdvancedToolRead } from "@/api/generated/initiativeAPI.schemas";
import { TagBadge } from "@/components/tags/TagBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useGuildPath } from "@/lib/guildUrl";

import { EditAdvancedToolTagsDialog } from "./EditAdvancedToolTagsDialog";

interface AdvancedToolCardProps {
  tool: AdvancedToolRead;
}

export const AdvancedToolCard = ({ tool }: AdvancedToolCardProps) => {
  const { t } = useTranslation("advancedTools");
  const gp = useGuildPath();
  const [tagsDialogOpen, setTagsDialogOpen] = useState(false);

  const canWrite = tool.my_permission_level === "owner" || tool.my_permission_level === "write";

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="h-4 w-4 shrink-0" />
            <span className="min-w-0 truncate">{tool.name}</span>
          </CardTitle>
          <CardDescription>
            {t("updated", { date: new Date(tool.updated_at).toLocaleDateString() })}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 pt-0">
          {tool.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {tool.tags.slice(0, 3).map((tag) => (
                <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
              ))}
              {tool.tags.length > 3 && (
                <span className="text-muted-foreground text-xs">+{tool.tags.length - 3}</span>
              )}
            </div>
          )}
          {canWrite && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-muted-foreground"
              onClick={() => setTagsDialogOpen(true)}
            >
              <TagIcon className="h-4 w-4" />
              {t("manageTags")}
            </Button>
          )}
        </CardContent>
      </Card>

      {canWrite && (
        <EditAdvancedToolTagsDialog
          open={tagsDialogOpen}
          onOpenChange={setTagsDialogOpen}
          tool={tool}
        />
      )}
    </>
  );
};
