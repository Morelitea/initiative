import { useId } from "react";
import { useTranslation } from "react-i18next";

import {
  PropertyTarget,
  type QueueItemRead,
  SearchEntityType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { EntityLinkField } from "@/components/entities/EntityLinkField";
import type { useQueueItemForm } from "@/components/initiativeTools/queues/useQueueItemForm";
import { MemberSelect } from "@/components/members/MemberSearchSelect";
import { PropertyPanel } from "@/components/properties";
import { TagPicker } from "@/components/tags/TagPicker";
import { Button } from "@/components/ui/button";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

interface QueueItemFieldsProps {
  form: ReturnType<typeof useQueueItemForm>;
  queueId: number;
  initiativeId: number;
  /** The item being edited; omitted while one is being added. */
  item?: QueueItemRead;
  readOnly?: boolean;
  /** Enter in the label field; omit while the form cannot be submitted. */
  onEnter?: () => void;
}

/** The fields of the add and edit queue-item dialogs. */
export const QueueItemFields = ({
  form,
  queueId,
  initiativeId,
  item,
  readOnly = false,
  onEnter,
}: QueueItemFieldsProps) => {
  const { t } = useTranslation(["queues", "relations", "properties"]);
  const id = useId();

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor={`${id}-label`}>{t("label")}</Label>
        <Input
          id={`${id}-label`}
          value={form.label}
          onChange={(e) => form.setLabel(e.target.value)}
          placeholder={t("labelPlaceholder")}
          disabled={readOnly}
          onKeyDown={(e) => {
            if (e.key === "Enter" && onEnter) {
              e.preventDefault();
              onEnter();
            }
          }}
          autoFocus={!item}
        />
      </div>

      {/* Position (Initiative Roll) */}
      <div className="space-y-2">
        <Label htmlFor={`${id}-position`}>{t("position")}</Label>
        <Input
          id={`${id}-position`}
          type="number"
          value={form.position}
          onChange={(e) => form.setPosition(e.target.value)}
          placeholder="0"
          disabled={readOnly}
        />
        <p className="text-muted-foreground text-xs">{t("positionHelp")}</p>
      </div>

      <div className="space-y-2">
        <Label>{t("color")}</Label>
        <ColorPickerPopover
          value={form.color}
          onChange={form.setColor}
          triggerLabel={t("color")}
          className="h-9"
          disabled={readOnly}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor={`${id}-notes`}>{t("notes")}</Label>
        <Textarea
          id={`${id}-notes`}
          value={form.notes}
          onChange={(e) => form.setNotes(e.target.value)}
          placeholder={t("notesPlaceholder")}
          rows={2}
          disabled={readOnly}
        />
      </div>

      <div className="flex items-center justify-between rounded-lg border bg-muted/40 p-3">
        <div>
          <p className="font-medium text-sm">{t("visible")}</p>
          <p className="text-muted-foreground text-xs">
            {form.isVisible ? t("visible") : t("hidden")}
          </p>
        </div>
        <Switch
          checked={form.isVisible}
          onCheckedChange={form.setIsVisible}
          aria-label={t("visible")}
          disabled={readOnly}
        />
      </div>

      <div className="space-y-2">
        <Label>{t("tags")}</Label>
        <TagPicker
          selectedTags={form.selectedTags}
          onChange={form.setSelectedTags}
          placeholder={t("tags")}
          disabled={readOnly}
        />
      </div>

      {/* Saved as they change, like the links below — the dialog's Save is
          about the item itself. An item being added has none yet. */}
      {item && (
        <div className="space-y-2">
          <Label>{t("properties:title")}</Label>
          <PropertyPanel
            target={PropertyTarget.queue_item}
            entityId={item.id}
            saved={item.properties}
            initiativeId={initiativeId}
            canOpen={{ tool: Tool.queue, id: queueId }}
            disabled={readOnly}
          />
        </div>
      )}

      <div className="space-y-2">
        <Label>{t("linkedUser")}</Label>
        <div className="flex items-center gap-2">
          <MemberSelect
            scope={{ type: "canOpen", tool: Tool.queue, id: queueId }}
            value={form.userId}
            onChange={form.setUserId}
            selectedUser={form.selectedUser}
            placeholder={t("selectUser")}
            emptyMessage={t("noUser")}
            disabled={readOnly}
          />
          {form.userId !== null && !readOnly && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => form.setUserId(null)}
              className="shrink-0"
            >
              {t("clearUser")}
            </Button>
          )}
        </div>
      </div>

      {/* One list, any kind — in place of a documents-only picker beside a
          tasks-only one. An item being added is no subject yet. */}
      <EntityLinkField
        label={t("relations:groups.attached.title")}
        subject={item ? { type: SearchEntityType.queue_item, id: item.id } : undefined}
        initiativeId={initiativeId}
        value={form.links}
        onChange={form.setLinks}
        readOnly={readOnly}
      />
    </div>
  );
};
