/**
 * Field editors any detail shares (a task's, an event's): the title, the
 * tags and the custom properties, each saved on its own through the save of
 * the item's kind.
 */

import { useBlocker } from "@tanstack/react-router";
import { Loader2, Sparkles, X } from "lucide-react";
import { type RefObject, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  PropertyDefinitionRead,
  PropertySummary,
  TagSummary,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { MentionComposer } from "@/components/markdown/MentionComposer";
import { AddPropertyButton } from "@/components/properties/AddPropertyButton";
import { propertyStubFromDefinition } from "@/components/properties/PropertyFields";
import { PropertyInput } from "@/components/properties/PropertyInput";
import { PropertyValueCell } from "@/components/properties/PropertyValueCell";
import {
  isEmptyPropertyValue,
  normalizePropertyValue,
  userReferenceValue,
} from "@/components/properties/propertyHelpers";
import { iconForPropertyType } from "@/components/properties/propertyTypeIcons";
import { TagPicker } from "@/components/tags";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { TaskDescription } from "@/components/tasks/TaskDescription";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import {
  type FieldSaveKind,
  type FieldSaveOptions,
  type ItemEdit,
  type ItemFieldSave,
  useItemFieldSave,
} from "@/hooks/useFieldSave";
import { usePastedImages } from "@/hooks/usePastedImages";
import { getHttpStatus } from "@/lib/errorMessage";
import { currentServerKey } from "@/lib/offlineSession";
import { getItem, removeItem, setItem } from "@/lib/storage";

import { FieldFrame, useFieldDraft } from "./editing";

const sameJson = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** An item's title, which is its detail's heading. It cannot be emptied:
 *  leaving it blank puts the saved one back. A reader who cannot change it
 *  sees the heading alone. */
export const TitleField = <I extends { title: string }, P extends { title?: string | null }>({
  id,
  label,
  value,
  save,
  readOnly,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  save: ItemFieldSave<I, P>;
  readOnly: boolean;
  placeholder: string;
}) => {
  const draft = useFieldDraft(value, async (title) =>
    title.trim() ? save.save({ patch: { title } as P, shows: { title } as Partial<I> }) : false
  );
  if (readOnly) {
    return (
      <h1 className="min-w-0 flex-1 break-words font-semibold text-3xl tracking-tight">{value}</h1>
    );
  }
  return (
    <FieldFrame
      label={label}
      htmlFor={id}
      hideLabel
      statusBelow
      save={save}
      changed={draft.changed}
      keys={draft.keys}
      className="flex-1"
    >
      <h1 className="sr-only">{value}</h1>
      <Input
        id={id}
        value={draft.value}
        onChange={(event) => draft.change(event.target.value)}
        placeholder={placeholder}
        className="h-auto font-semibold text-3xl tracking-tight shadow-none focus-visible:ring-0 sm:text-3xl"
      />
    </FieldFrame>
  );
};

/** An item's tags, saved the moment they are picked. Clearing them offers
 *  Undo. A reader who cannot change them sees the tags alone, and nothing
 *  where there are none. */
export const TagsField = <
  I extends { tags: TagSummary[] },
  P extends { tag_ids?: number[] | null },
>({
  label,
  tags,
  save,
  readOnly,
  placeholder,
}: {
  label: string;
  tags: TagSummary[];
  save: ItemFieldSave<I, P>;
  readOnly: boolean;
  placeholder: string;
}) => {
  const edit = (picked: TagSummary[]): ItemEdit<I, P> => ({
    patch: { tag_ids: picked.map((tag) => tag.id) } as P,
    shows: { tags: picked } as Partial<I>,
  });
  if (readOnly) {
    return tags.length ? (
      <div className="space-y-2">
        <p className="font-medium text-sm">{label}</p>
        <TagBadgeList tags={tags} limit={tags.length} className="gap-2" />
      </div>
    ) : null;
  }
  return (
    <FieldFrame label={label} save={save}>
      <TagPicker
        selectedTags={tags}
        onChange={(picked) =>
          void save.save(edit(picked), picked.length === 0 ? edit(tags) : undefined)
        }
        placeholder={placeholder}
      />
    </FieldFrame>
  );
};

/** What the properties of an item take: its kind's save, the item, and who
 *  a person-valued property may name. */
type PropertiesProps<I extends { properties: PropertySummary[] }, P> = {
  kind: FieldSaveKind<I, P>;
  id: number;
  properties: PropertySummary[];
  readOnly: boolean;
  initiativeId: number | null;
  /** Whose people a person-valued property may name: who can open this tool. */
  canOpen: { tool: Tool; id: number | null | undefined };
};

/** How a value reads on the item until the server says: a person's own
 *  summary while they are still the one named. */
const showing = (property: PropertySummary, value: unknown): PropertySummary => ({
  ...property,
  value: value === normalizePropertyValue(property) ? property.value : value,
});

/** One custom property, saved on its own as its kind says. Only it is sent,
 *  so a change to another property meanwhile still stands. */
const PropertyField = <I extends { properties: PropertySummary[] }, P>({
  kind,
  id,
  properties,
  readOnly,
  initiativeId,
  canOpen,
  property,
}: PropertiesProps<I, P> & { property: PropertySummary }) => {
  const { t } = useTranslation("properties");
  const save = useItemFieldSave(kind, id, property.name);
  const saved = normalizePropertyValue(property);
  const edit = (value: unknown): ItemEdit<I, P> => ({
    properties: { values: [{ property_id: property.property_id, value }] },
    shows: {
      properties: properties.map((p) =>
        p.property_id === property.property_id ? showing(p, value) : p
      ),
    } as Partial<I>,
  });
  const draft = useFieldDraft(
    saved,
    (value) =>
      save.save(
        edit(value),
        isEmptyPropertyValue(value) && !isEmptyPropertyValue(saved) ? edit(saved) : undefined
      ),
    sameJson
  );
  // The property stays until it is gone, so a failed removal says so here.
  const remove = () => {
    draft.restore();
    void save.save(
      { properties: { values: [], removed: [property.property_id] }, shows: {} },
      { ...edit(saved), shows: { properties } as Partial<I> }
    );
  };
  return (
    <FieldFrame
      label={property.name}
      save={save}
      changed={draft.changed}
      keys={draft.keys}
      action={
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="text-muted-foreground"
          onClick={remove}
          disabled={readOnly}
          aria-label={t("remove")}
        >
          <X className="h-4 w-4" />
        </Button>
      }
    >
      <PropertyInput
        definition={property}
        value={draft.value}
        onChange={draft.edit}
        disabled={readOnly}
        initiativeId={initiativeId}
        canOpen={canOpen}
        selectedUser={userReferenceValue(property)}
      />
    </FieldFrame>
  );
};

/** An item's custom properties, each saved on its own, and adding one. */
export const PropertiesField = <I extends { properties: PropertySummary[] }, P>(
  props: PropertiesProps<I, P>
) => {
  const { t } = useTranslation("properties");
  const { kind, id, properties, readOnly, initiativeId } = props;
  const label = t("title");
  const save = useItemFieldSave(kind, id, label);
  const add = (definition: PropertyDefinitionRead) => {
    if (properties.some((p) => p.property_id === definition.id)) return;
    void save.save({
      properties: { values: [{ property_id: definition.id, value: null }] },
      shows: {
        properties: [...properties, propertyStubFromDefinition(definition)],
      } as Partial<I>,
    });
  };
  const sorted = [...properties].sort((a, b) => a.name.localeCompare(b.name));
  // A reader sees each value as it reads anywhere else: a link opens.
  if (readOnly) {
    return (
      <div className="space-y-2">
        <p className="font-medium text-sm">{label}</p>
        {sorted.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("noProperties")}</p>
        ) : (
          <ul className="space-y-2">
            {sorted.map((property) => {
              const Icon = iconForPropertyType(property.type);
              return (
                <li
                  key={property.property_id}
                  className="grid grid-cols-[minmax(0,8rem)_1fr] items-center gap-2"
                >
                  <span className="flex min-w-0 items-center gap-1.5 font-normal text-muted-foreground text-xs">
                    <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    <span className="truncate">{property.name}</span>
                  </span>
                  <PropertyValueCell summary={property} variant="cell" />
                </li>
              );
            })}
          </ul>
        )}
      </div>
    );
  }
  return (
    <FieldFrame label={label} save={save}>
      {sorted.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("noProperties")}</p>
      ) : (
        sorted.map((property) => (
          <PropertyField key={property.property_id} {...props} property={property} />
        ))
      )}
      <AddPropertyButton
        initiativeId={initiativeId ?? 0}
        currentPropertyIds={properties.map((p) => p.property_id)}
        onAdd={add}
        disabled={readOnly || !initiativeId}
      />
    </FieldFrame>
  );
};

/** A description being written, and the one it was written over. */
interface DescriptionDraft {
  text: string;
  base: string | null;
}

const readDescriptionDraft = (key: string): DescriptionDraft | null => {
  try {
    const stored = JSON.parse(getItem(key) ?? "null") as DescriptionDraft | null;
    return stored && typeof stored.text === "string" ? stored : null;
  } catch {
    return null;
  }
};

/** The preview of a description being edited reads the way the saved one will. */
const renderDescription = (draft: string) => <TaskDescription content={draft} />;

/**
 * An item's description, in a composer that opens on its preview, saved only
 * with Save (or Ctrl/Cmd+Enter). What is typed is a draft, kept on the device
 * until it is saved or discarded. The save names the description it was
 * written over, and one written over a description that has since changed is
 * refused, so the reader sees the other version and chooses.
 */
export const DescriptionField = <
  I extends { description: string | null },
  P extends { description?: string | null; description_base?: string | null },
>({
  kind,
  id,
  options,
  label,
  htmlId,
  value,
  readOnly,
  preview = false,
  initiativeId,
  subject,
  leaving,
  placeholder,
  suggest,
}: {
  kind: FieldSaveKind<I, P>;
  id: number;
  /** What the detail adds to its saves. */
  options: FieldSaveOptions<I, P>;
  label: string;
  htmlId: string;
  /** The description as saved. */
  value: string | null;
  readOnly: boolean;
  /** Drawn in the layout editor, where nothing is changed: a draft kept on
   *  the device stays there. */
  preview?: boolean;
  initiativeId: number | null;
  /** The item, as its references name it. */
  subject: string;
  /** Set when the page is left on purpose, so an open draft does not hold it. */
  leaving: RefObject<boolean>;
  placeholder: string;
  /** Writes a description for the reader to start from (AI). */
  suggest?: { label: string; run: () => Promise<string> };
}) => {
  const { t } = useTranslation("common");
  const communityId = useActiveCommunityId();
  const { user } = useAuth();
  const uploadImage = usePastedImages();
  // Saved by Save or by Retry. What was typed while it saved stays the draft,
  // now written over the description just saved.
  const save = useItemFieldSave(kind, id, label, {
    ...options,
    onSaved: (edit) => {
      options.onSaved?.(edit);
      const now = latest.current;
      const saved = edit.shows.description ?? null;
      if (now) setDraft(now.text === (saved ?? "") ? null : { ...now, base: saved });
    },
  });
  // Each account on each server keeps its own drafts on a shared device.
  const key = `${kind.name}-description-draft:${user?.id}@${currentServerKey()}:${communityId}:${id}`;
  const [draft, setDraftState] = useState(() => readDescriptionDraft(key));
  const [discarding, setDiscarding] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  // Read by the description written for the reader, which lands later.
  const latest = useRef(draft);

  const setDraft = (next: DescriptionDraft | null) => {
    latest.current = next;
    setDraftState(next);
    void (next ? setItem(key, JSON.stringify(next)) : removeItem(key));
    // A refused save belongs to the draft, and goes with it.
    if (!next) save.reset();
  };

  const current = value ?? "";
  // A reader who can no longer edit keeps the draft on the device, but sees
  // the saved description and nothing that would write.
  const open = readOnly || preview ? null : draft;
  const conflict = open !== null && getHttpStatus(save.error) === 409;
  const dirty = open !== null && open.text !== (open.base ?? "");
  const blocker = useBlocker({
    shouldBlockFn: () => dirty && !leaving.current,
    enableBeforeUnload: () => dirty && !leaving.current,
    withResolver: true,
  });

  const submit = (base: string | null) => {
    if (!open) return;
    const description = open.text || null;
    void save.save({
      patch: { description, description_base: base } as P,
      shows: { description } as Partial<I>,
    });
  };
  const cancel = () => (dirty ? setDiscarding(true) : setDraft(null));
  const startFrom = async () => {
    if (!suggest) return;
    setSuggesting(true);
    try {
      const text = await suggest.run();
      setDraft({ text, base: latest.current?.base ?? value });
    } catch {
      // The request says what went wrong.
    } finally {
      setSuggesting(false);
    }
  };

  return (
    <FieldFrame
      label={label}
      htmlFor={htmlId}
      // The conflict below says what went wrong, and Retry would only repeat it.
      save={conflict ? { ...save, state: "idle" } : save}
      changed={
        open !== null && !conflict && save.state !== "saving" && current !== (open.base ?? "")
      }
    >
      {readOnly ? (
        <>
          {current ? (
            <div className="rounded-md border border-border/70 border-dashed bg-muted/40 px-3 py-2">
              <TaskDescription content={current} />
            </div>
          ) : (
            <p className="text-muted-foreground text-sm italic">{t("descriptionField.none")}</p>
          )}
          {draft !== null ? (
            <p className="text-muted-foreground text-xs">{t("descriptionField.draftKept")}</p>
          ) : null}
        </>
      ) : (
        <div className="space-y-2">
          <MentionComposer
            id={htmlId}
            value={open?.text ?? current}
            onChange={(text) => setDraft({ text, base: open ? open.base : value })}
            initiativeId={initiativeId ?? 0}
            subject={subject}
            renderPreview={renderDescription}
            onUploadImage={uploadImage}
            defaultMode="preview"
            placeholder={placeholder}
            onKeyDown={(event) => {
              if (!open) return;
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                submit(open.base);
              } else if (event.key === "Escape") {
                event.preventDefault();
                cancel();
              }
            }}
            actions={
              suggest ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 px-2 text-xs"
                  onClick={() => void startFrom()}
                  disabled={suggesting}
                >
                  {suggesting ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Sparkles className="h-3 w-3" />
                  )}
                  {suggest.label}
                </Button>
              ) : null
            }
          />
          {open === null ? null : conflict ? (
            <div
              role="alert"
              className="space-y-2 rounded-md border border-warning/40 bg-warning/5 px-3 py-2"
            >
              <p className="text-sm">{t("fieldSave.changed")}</p>
              <div className="rounded-md border bg-background px-3 py-2">
                <TaskDescription content={current} />
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" size="sm" onClick={() => submit(value)}>
                  {t("fieldSave.overwrite")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    save.reset();
                    setDraft({ ...open, base: value });
                  }}
                >
                  {t("fieldSave.keepEditing")}
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                disabled={save.state === "saving"}
                onClick={() => submit(open.base)}
              >
                {t("save")}
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={cancel}>
                {t("cancel")}
              </Button>
            </div>
          )}
        </div>
      )}
      <ConfirmDialog
        open={discarding}
        onOpenChange={setDiscarding}
        title={t("descriptionField.unsavedTitle")}
        confirmLabel={t("fieldSave.discard")}
        cancelLabel={t("fieldSave.keepEditing")}
        onConfirm={() => {
          setDiscarding(false);
          setDraft(null);
        }}
        destructive
      />
      <ConfirmDialog
        open={blocker.status === "blocked"}
        onOpenChange={(isOpen) => {
          if (!isOpen) blocker.reset?.();
        }}
        title={t("descriptionField.unsavedTitle")}
        description={t("descriptionField.unsavedBody")}
        confirmLabel={t("descriptionField.leave")}
        cancelLabel={t("descriptionField.stay")}
        onConfirm={() => {
          setDraft(null);
          blocker.proceed?.();
        }}
        destructive
      />
    </FieldFrame>
  );
};
