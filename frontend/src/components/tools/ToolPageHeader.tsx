/**
 * The head of every tool page: a band in the initiative's colour that runs the
 * width of the content area and up under the shell's sticky bar, fading into
 * the page. On it, three rows: the breadcrumb with Settings across from it and
 * nothing else; the name and description; and the tool chest, the strip of
 * what the tool is and what only it has.
 *
 * The breadcrumb names where the page lives and the title names the page, so
 * neither repeats the other. The colour is the initiative's on every tool, so
 * it says which initiative you are in; a tool's own colour or emoji is the
 * `mark` in front of its name.
 */
import { Link } from "@tanstack/react-router";
import { Settings } from "lucide-react";
import { type CSSProperties, type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useFullBleed } from "@/components/PageBanner";
import { ToolBreadcrumb, type ToolBreadcrumbSegment } from "@/components/tools/ToolBreadcrumb";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useListedInitiative } from "@/hooks/useInitiatives";
import { useCommunityPath } from "@/lib/communityUrl";
import { hexToRgba, resolveInitiativeColor } from "@/lib/initiativeColors";
import { cn } from "@/lib/utils";

const TITLE_CLASS = "font-semibold text-3xl tracking-tight";

export interface ToolPageHeaderProps {
  tool: Tool;
  /** The initiative the page belongs to; null for a community-level calendar. */
  initiativeId?: number | null;
  /** Ancestors after the tool-list crumb: a task's project, a setting's entity. */
  trail?: ToolBreadcrumbSegment[];
  /** The page's settings (community-relative), for someone who may change them:
   *  the one thing across from the breadcrumb. */
  settingsTo?: string;
  /** Search params the settings link carries (an event's occurrence). */
  settingsSearch?: Record<string, string>;
  /** The entity's own emoji or colour dot, in front of its name. */
  mark?: ReactNode;
  /** The page's title. With `onRename`, the name a person can click to change. */
  title: ReactNode;
  /** Saves a new name; given only to someone who may rename. Resolves once
   *  saved, so the field stays open on a failure. */
  onRename?: (name: string) => Promise<unknown>;
  /** Beside the title: a favourite star, a status. */
  titleExtras?: ReactNode;
  /** Under the title: the description, a byline. */
  children?: ReactNode;
  /** The tool chest under the name and description. */
  chest?: ReactNode;
}

export const ToolPageHeader = ({
  tool,
  initiativeId,
  trail,
  settingsTo,
  settingsSearch,
  mark,
  title,
  onRename,
  titleExtras,
  children,
  chest,
}: ToolPageHeaderProps) => {
  const { t } = useTranslation("common");
  const gp = useCommunityPath();
  const box = useFullBleed<HTMLElement>();
  const color = resolveInitiativeColor(useListedInitiative(initiativeId)?.color);

  return (
    <header
      ref={box.ref}
      style={{
        ...box.style,
        // Up behind the sticky bar, and back down by as much inside, so the
        // colour runs to the top of the page and the words stay put.
        ...(box.header ? { marginTop: -box.header, paddingTop: box.header } : null),
        backgroundImage: `linear-gradient(to bottom, ${hexToRgba(color, 0.28)} 0%, ${hexToRgba(color, 0.12)} 55%, transparent 100%)`,
      }}
      className="-mx-4 -mt-4 md:-mx-8 md:-mt-8"
    >
      <div
        // Lines the copy back up with the page's own column below it.
        style={{ paddingLeft: box.inset.left, paddingRight: box.inset.right }}
        className={cn("space-y-4 px-4 pt-4 md:px-8 md:pt-8", chest ? "pb-4" : "pb-6")}
      >
        {/* The breadcrumb and Settings, and nothing else: one row, always,
            the crumb wrapping inside its own share. */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1 pt-1.5">
            <ToolBreadcrumb tool={tool} initiativeId={initiativeId} trail={trail} />
          </div>
          {settingsTo ? (
            <Button asChild variant="outline" size="sm" className="shrink-0">
              <Link to={gp(settingsTo)} search={settingsSearch ?? {}}>
                <Settings className="h-4 w-4" aria-hidden />
                {t("toolSettings.title")}
              </Link>
            </Button>
          ) : null}
        </div>
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            {mark}
            {onRename && typeof title === "string" ? (
              <EditableTitle name={title} onRename={onRename} />
            ) : (
              <h1 className={cn("min-w-0 break-words", TITLE_CLASS)}>{title}</h1>
            )}
            {titleExtras}
          </div>
          {children}
        </div>
      </div>
      {chest ? (
        <div
          // On a phone the chest runs edge to edge and its first segment
          // lines up with the page's column; from `md` up it is a card inside
          // that column.
          style={
            {
              "--inset-l": `${box.inset.left}px`,
              "--inset-r": `${box.inset.right}px`,
            } as CSSProperties
          }
          className={cn(
            "[--chest-gutter-right:var(--inset-r)] [--chest-gutter:var(--inset-l)]",
            "md:pr-(--inset-r) md:pb-6 md:pl-(--inset-l)",
            "md:[--chest-gutter-right:0.75rem] md:[--chest-gutter:0.75rem]"
          )}
        >
          {chest}
        </div>
      ) : null}
    </header>
  );
};

/** A heading that turns into a field when clicked: Enter or leaving it saves,
 *  Escape puts the name back. */
const EditableTitle = ({
  name,
  onRename,
}: {
  name: string;
  onRename: (name: string) => Promise<unknown>;
}) => {
  const { t } = useTranslation("common");
  const [draft, setDraft] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    const trimmed = draft?.trim();
    if (!trimmed || trimmed === name) {
      setDraft(null);
      return;
    }
    setSaving(true);
    try {
      await onRename(trimmed);
      setDraft(null);
    } catch {
      // The mutation reports its own error; the field stays open to retry.
    } finally {
      setSaving(false);
    }
  };

  if (draft !== null) {
    return (
      <Input
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        aria-label={t("toolHeader.rename")}
        className={cn("h-auto min-w-0 flex-1 md:text-3xl", TITLE_CLASS)}
        disabled={saving}
        autoFocus
        onKeyDown={(event) => {
          if (event.key === "Enter") void save();
          if (event.key === "Escape") setDraft(null);
        }}
        onBlur={() => void save()}
      />
    );
  }

  return (
    <h1 className={cn("min-w-0 break-words", TITLE_CLASS)}>
      <button
        type="button"
        title={t("toolHeader.rename")}
        onClick={() => setDraft(name)}
        className="cursor-text rounded-md text-left hover:bg-foreground/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {name}
      </button>
    </h1>
  );
};
