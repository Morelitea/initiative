/**
 * The bar under a tool page's title: what the tool is (its status, its tags,
 * its properties) and what only this tool has, side by side in one strip.
 *
 * Status, tags and properties are on every tool, so they are always here, in
 * that order around whatever the tool adds. The properties open below the
 * strip. Exports and filters are not part of it; they stay with the list or
 * view they act on.
 *
 * It runs edge to edge under the page header, and on a narrow screen the strip
 * scrolls sideways rather than wrapping. The header sets `--chest-gutter` to
 * where the page's own column starts, so the first segment lines up with the
 * title above it.
 */
import { ChevronDown } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type ArchivableType,
  type PropertySummary,
  PropertyTarget,
  type TagSummary,
  type Tool,
  type ToolCan,
} from "@/api/generated/initiativeAPI.schemas";
import { PropertyPanel } from "@/components/properties";
import { TagBadge, TagPicker } from "@/components/tags";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useArchiveEntity, useUnarchiveEntity } from "@/hooks/useArchive";
import { useSetToolTags } from "@/hooks/useToolTags";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";
import { cn } from "@/lib/utils";

export interface ToolChestEntity {
  id: number;
  name: string;
  initiative_id: number | null;
  archived_at: string | null;
  tags: TagSummary[];
  properties?: PropertySummary[];
  can: Pick<ToolCan, "edit" | "unarchive">;
}

export interface ToolChestProps {
  tool: Tool;
  entity: ToolChestEntity;
  /** What only this tool has: its own data and buttons, as `ToolChestSegment`s. */
  children?: ReactNode;
}

/** One part of the strip: its label over its value, or just the tool's own
 *  buttons. */
export const ToolChestSegment = ({
  label,
  children,
}: {
  label?: ReactNode;
  children: ReactNode;
}) => (
  <div className="flex shrink-0 flex-col justify-center gap-1 px-4 py-2.5 text-sm first:pl-0 md:flex-row md:items-center md:justify-start md:gap-2 md:py-2">
    {label ? <span className="font-medium text-muted-foreground text-xs">{label}</span> : null}
    <div className="flex items-center gap-2 whitespace-nowrap">{children}</div>
  </div>
);

export const ToolChest = ({ tool, entity, children }: ToolChestProps) => {
  const { t } = useTranslation(["common", "properties"]);
  const gp = useGuildPath();
  const [propertiesOpen, setPropertiesOpen] = useState(false);
  const [tags, setTags] = useState(entity.tags);
  const setToolTags = useSetToolTags(tool);
  const canEdit = entity.can.edit;
  // Definitions belong to an initiative, so a guild-level tool has none.
  const hasProperties = entity.initiative_id !== null;
  const propertyCount = entity.properties?.length ?? 0;

  return (
    <div className="border-y bg-background/60 md:rounded-lg md:border md:bg-card">
      {/* The strip scrolls; the properties toggle stays out of it, at its end
          on a wide screen and on its own row under it on a narrow one. */}
      <div className="flex flex-col md:flex-row">
        <div
          className={cn(
            "flex min-w-0 flex-1 items-stretch divide-x overflow-x-auto overscroll-x-contain [scrollbar-width:none]",
            "pl-[var(--chest-gutter,1rem)]",
            hasProperties ? "pr-4 md:pr-0" : "pr-[var(--chest-gutter-right,1rem)]"
          )}
        >
          <ToolChestSegment label={t("toolChest.status")}>
            <ToolStatus tool={tool} entity={entity} />
          </ToolChestSegment>
          {children}
          <ToolChestSegment label={t("toolSettings.tags")}>
            {canEdit ? (
              <TagPicker
                selectedTags={tags}
                className="min-w-40 whitespace-normal"
                onChange={(next) => {
                  // Saved on pick, and put back if the write fails.
                  const previous = tags;
                  setTags(next);
                  setToolTags.mutate(
                    { id: entity.id, tagIds: next.map((tag) => tag.id) },
                    { onError: () => setTags(previous) }
                  );
                }}
              />
            ) : tags.length > 0 ? (
              <span className="flex gap-1">
                {tags.map((tag) => (
                  <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
                ))}
              </span>
            ) : (
              <span className="text-muted-foreground">{t("toolChest.none")}</span>
            )}
          </ToolChestSegment>
        </div>
        {hasProperties ? (
          <button
            type="button"
            onClick={() => setPropertiesOpen((open) => !open)}
            aria-expanded={propertiesOpen}
            className={cn(
              "flex shrink-0 items-center gap-2 border-t py-2.5 text-left text-sm hover:bg-accent/50",
              "pr-[var(--chest-gutter-right,1rem)] pl-[var(--chest-gutter,1rem)]",
              "md:border-t-0 md:border-l md:py-2 md:pl-4"
            )}
          >
            <span className="font-medium text-muted-foreground text-xs">
              {t("properties:title")}
            </span>
            <span className="flex items-center gap-1 tabular-nums">
              {propertyCount}
              <ChevronDown
                className={cn("h-4 w-4 transition-transform", propertiesOpen && "rotate-180")}
                aria-hidden
              />
            </span>
          </button>
        ) : null}
      </div>
      {hasProperties && propertiesOpen ? (
        <div className="border-t py-3 pr-[var(--chest-gutter-right,1rem)] pl-[var(--chest-gutter,1rem)]">
          <PropertyPanel
            target={PropertyTarget[tool]}
            entityId={entity.id}
            saved={entity.properties}
            initiativeId={entity.initiative_id as number}
            canOpen={{ tool, id: entity.id }}
            disabled={!canEdit}
          />
        </div>
      ) : null}
    </div>
  );
};

const StatusLabel = ({ archived }: { archived: boolean }) => {
  const { t } = useTranslation("common");
  return (
    <span className="inline-flex items-center gap-1.5 font-medium">
      <span
        className={cn("h-2 w-2 rounded-full", archived ? "bg-muted-foreground" : "bg-success")}
        aria-hidden
      />
      {archived ? t("toolChest.archived") : t("toolChest.active")}
    </span>
  );
};

/** Active or archived; someone who may change it picks the other here, the
 *  way Settings › Advanced would. Archiving is an ordinary edit, and the way
 *  back out is its own permission. */
const ToolStatus = ({ tool, entity }: { tool: Tool; entity: ToolChestEntity }) => {
  const { t } = useTranslation("common");
  const archived = entity.archived_at !== null;
  const archive = useArchiveEntity({
    onSuccess: () => toast.success(t("toolSettings.archive.archived", { name: entity.name })),
  });
  const unarchive = useUnarchiveEntity({
    onSuccess: () => toast.success(t("toolSettings.archive.unarchived", { name: entity.name })),
  });
  const canChange = archived ? entity.can.unarchive : entity.can.edit;

  if (!canChange) return <StatusLabel archived={archived} />;

  return (
    <Select
      value={archived ? "archived" : "active"}
      disabled={archive.isPending || unarchive.isPending}
      onValueChange={(next) => {
        const target = { entityType: tool as ArchivableType, entityId: entity.id };
        if (next === "archived" && !archived) archive.mutate(target);
        if (next === "active" && archived) unarchive.mutate(target);
      }}
    >
      <SelectTrigger
        aria-label={t("toolChest.status")}
        className="h-7 w-auto gap-1 border-none bg-transparent px-1.5 shadow-none"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="active">
          <StatusLabel archived={false} />
        </SelectItem>
        <SelectItem value="archived">
          <StatusLabel archived />
        </SelectItem>
      </SelectContent>
    </Select>
  );
};
