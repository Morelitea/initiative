import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { MyAIConnectionRow } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroupItem } from "@/components/ui/radio-group";
import { PROVIDER_CONFIGS } from "@/lib/ai-providers";

/** RadioGroup value for a connection within one guild group. */
export const myConnectionValue = (row: Pick<MyAIConnectionRow, "scope" | "connection_id">) =>
  `${row.scope}:${row.connection_id}`;

interface MemberAIConnectionRowProps {
  connection: MyAIConnectionRow;
  /** Rejects to keep the inline editor open (e.g. the key was refused). */
  onSaveKey: (apiKey: string) => Promise<void>;
  onRemoveKey: () => void;
  isRemovingKey: boolean;
}

/**
 * One connection the member can select as active, with an inline editor for
 * their personal API key. When the connection doesn't allow member keys it's
 * shown read-only (it uses the admin's shared key), but still selectable.
 */
export const MemberAIConnectionRow = ({
  connection,
  onSaveKey,
  onRemoveKey,
  isRemovingKey,
}: MemberAIConnectionRowProps) => {
  const { t } = useTranslation("settings");
  const value = myConnectionValue(connection);
  const domId = `member-connection-${connection.guild_id}-${connection.scope}-${connection.connection_id}`;
  const [editing, setEditing] = useState(false);
  const [keyValue, setKeyValue] = useState("");
  const [saving, setSaving] = useState(false);

  const closeEditor = () => {
    setEditing(false);
    setKeyValue("");
  };

  const save = async () => {
    if (!keyValue.trim()) return;
    setSaving(true);
    try {
      await onSaveKey(keyValue);
      closeEditor();
    } catch {
      // Keep the editor open so the member can correct the key.
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3 rounded-md border px-4 py-3">
      <div className="flex items-start gap-3">
        <RadioGroupItem id={domId} value={value} className="mt-1" />
        <Label htmlFor={domId} className="flex-1 cursor-pointer space-y-1 font-normal">
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{connection.label}</span>
            {connection.is_selected && <Badge variant="secondary">{t("memberAI.selected")}</Badge>}
            {connection.requires_member_key && !connection.has_member_key && (
              <Badge variant="outline">{t("memberAI.requiresKey")}</Badge>
            )}
          </span>
          <span className="block text-muted-foreground text-sm">
            {PROVIDER_CONFIGS[connection.provider]?.label ?? connection.provider}
            {connection.model ? ` · ${connection.model}` : ""}
          </span>
        </Label>
      </div>

      <div className="space-y-2 pl-7">
        {!connection.allow_member_keys ? (
          <p className="text-muted-foreground text-xs">{t("memberAI.managedByAdmin")}</p>
        ) : editing ? (
          <div className="space-y-2">
            <Input
              type="password"
              value={keyValue}
              autoFocus
              onChange={(event) => setKeyValue(event.target.value)}
              placeholder={t("memberAI.keyPlaceholder")}
            />
            <div className="flex gap-2">
              <Button type="button" size="sm" disabled={saving || !keyValue.trim()} onClick={save}>
                {saving ? t("aiConnections.saving") : t("memberAI.saveKey")}
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={closeEditor}>
                {t("aiConnections.cancel")}
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            {connection.has_member_key && (
              <span className="text-muted-foreground text-xs">{t("memberAI.keySet")}</span>
            )}
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                setKeyValue("");
                setEditing(true);
              }}
            >
              {connection.has_member_key ? t("memberAI.replaceKey") : t("memberAI.addKey")}
            </Button>
            {connection.has_member_key && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={isRemovingKey}
                onClick={onRemoveKey}
              >
                {t("memberAI.removeKey")}
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
