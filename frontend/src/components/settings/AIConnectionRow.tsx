import { Pencil, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { AIConnectionResponse } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PROVIDER_CONFIGS } from "@/lib/ai-providers";

interface AIConnectionRowProps {
  connection: AIConnectionResponse;
  isTesting: boolean;
  testDisabled: boolean;
  onTest: () => void;
  onEdit: () => void;
  onDelete: () => void;
}

export const AIConnectionRow = ({
  connection,
  isTesting,
  testDisabled,
  onTest,
  onEdit,
  onDelete,
}: AIConnectionRowProps) => {
  const { t } = useTranslation("settings");

  return (
    <li className="flex flex-col gap-3 rounded-md border px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{connection.label}</span>
          {connection.is_default && (
            <Badge variant="secondary">{t("aiConnections.defaultBadge")}</Badge>
          )}
          <Badge variant={connection.enabled ? "default" : "outline"}>
            {connection.enabled ? t("ai.enabled") : t("ai.disabled")}
          </Badge>
        </div>
        <p className="text-muted-foreground text-sm">
          {PROVIDER_CONFIGS[connection.provider]?.label ?? connection.provider}
          {connection.model ? ` · ${connection.model}` : ""}
        </p>
        <p className="text-muted-foreground text-xs">
          {connection.has_api_key ? t("aiConnections.keySet") : t("aiConnections.noKey")}
          {connection.base_url ? ` · ${connection.base_url}` : ""}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onTest} disabled={testDisabled}>
          {isTesting ? t("ai.testing") : t("ai.testConnection")}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("aiConnections.edit")}
          onClick={onEdit}
        >
          <Pencil className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("aiConnections.delete")}
          onClick={onDelete}
        >
          <Trash2 className="h-4 w-4 text-destructive" />
        </Button>
      </div>
    </li>
  );
};
