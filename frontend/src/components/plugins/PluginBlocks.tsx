/**
 * Plug-in blocks: a plug-in's template drawn in one of a section's block areas.
 *
 * A block area draws the blocks offered there, each by its kind: an inline
 * block is a span on the card's badge row, a panel a section of its own, and a
 * menu block a group of items under one menu. A block carries its plug-in's
 * name in an accessible label, and a block that cannot be drawn hides (inline,
 * menu) or says it is unavailable (panel); the task around it never waits.
 *
 * Everything a block needs that the screen could ask for once, the screen asks
 * for (`useTaskBlocks`) and hands down in `BlockShared`.
 */

import { Link } from "@tanstack/react-router";
import { Copy, Puzzle } from "lucide-react";
import {
  createContext,
  createElement,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import type { PluginBlockRequest } from "@/api/pluginData";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import type { WidthClass } from "@/hooks/useWidthClass";
import { toast } from "@/lib/mascotToast";
import type { CompileResult } from "@/lib/templates/compile";
import { renderTemplate } from "@/lib/templates/render";
import type { BlockAreaKind } from "@/lib/templates/sections";
import { PLUGIN_CLASSES } from "@/lib/templates/vocabulary";
import { cn } from "@/lib/utils";
import type { TranslateFn } from "@/types/i18n";

/** A block offered on this screen, compiled and with its words in the reader's language. */
export interface OfferedBlock {
  key: string;
  request: PluginBlockRequest;
  /** The section's areas it is offered in, such as `inline` or `aside`. */
  areas: ReadonlySet<string>;
  name: string;
  /** Names the block and its plug-in, for assistive technology. */
  label: string;
  strings: Readonly<Record<string, string>>;
  compiled: CompileResult;
  /** It reads an endpoint, so it waits for its rows. */
  reads: boolean;
  /** Where `<open page>` leads in the tasks' initiative, or null where it cannot open. */
  pagePath: (pageId: string) => string | null;
}

/** One block's rows: by task id, as its read answered them. */
export interface BlockRows {
  rows: Readonly<Record<string, Record<string, unknown>>> | undefined;
  pending: boolean;
  failed: boolean;
}

/** What every block on the screen shares, worked out once for it. */
export interface BlockShared {
  t: TranslateFn;
  width: WidthClass;
  /** The minute the screen is drawn for. */
  now: number;
  /** Run one of a block's actions for a task, and keep the row it answers. */
  run: (block: OfferedBlock, actionKey: string, taskId: number) => Promise<void>;
}

/** Where a block element sits: which block, for which task, in what kind of area. */
interface BlockPlace {
  block: OfferedBlock;
  taskId: number;
  kind: BlockAreaKind;
  shared: BlockShared;
}

const Place = createContext<BlockPlace | null>(null);

const usePlace = (): BlockPlace => {
  const place = useContext(Place);
  if (!place) throw new Error("A block element is drawn only inside a block");
  return place;
};

const pad = (value: number) => String(value).padStart(2, "0");

/** Elapsed time as `h:mm:ss`. */
const elapsed = (milliseconds: number): string => {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return `${Math.floor(seconds / 3600)}:${pad(Math.floor(seconds / 60) % 60)}:${pad(seconds % 60)}`;
};

/** Time since a moment, ticked here each second rather than by drawing the template again. */
function Timer({ props }: { props: Record<string, unknown> }) {
  const since = typeof props.since === "string" ? props.since : null;
  const start = since ? Date.parse(since) : Number.NaN;
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!Number.isFinite(start)) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [start]);
  if (!since || !Number.isFinite(start)) return null;
  return (
    <time dateTime={since} className="tabular-nums">
      {elapsed(now - start)}
    </time>
  );
}

function CopyValue({ props }: { props: Record<string, unknown> }) {
  const { shared } = usePlace();
  const value = props.value;
  if (typeof value !== "string" && typeof value !== "number") return null;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(String(value));
      toast.success(shared.t("blocks.copied"));
    } catch {
      toast.error(shared.t("blocks.copyFailed"));
    }
  };
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      className="size-6"
      aria-label={shared.t("blocks.copy")}
      onClick={() => void copy()}
    >
      <Copy className="h-3.5 w-3.5" />
    </Button>
  );
}

/** Runs one of the block's actions, and says whether it is under way. */
const useAction = (action: unknown): [boolean, () => void] => {
  const { block, taskId, shared } = usePlace();
  const [running, setRunning] = useState(false);
  const run = () => {
    if (running || typeof action !== "string") return;
    setRunning(true);
    void shared.run(block, action, taskId).finally(() => setRunning(false));
  };
  return [running, run];
};

function ActionButton({
  props,
  children,
}: {
  props: Record<string, unknown>;
  children?: ReactNode;
}) {
  const [running, run] = useAction(props.action);
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="h-7"
      disabled={running}
      aria-busy={running}
      onClick={run}
    >
      {children}
    </Button>
  );
}

/** An item in the block's menu; drawn outside a menu area, a button. */
function ActionMenuItem(element: { props: Record<string, unknown>; children?: ReactNode }) {
  const { kind } = usePlace();
  const [running, run] = useAction(element.props.action);
  if (kind !== "menu") return <ActionButton {...element} />;
  return (
    <DropdownMenuItem disabled={running} onSelect={run}>
      {element.children}
    </DropdownMenuItem>
  );
}

function OpenPage({ props, children }: { props: Record<string, unknown>; children?: ReactNode }) {
  const { block } = usePlace();
  const page = typeof props.page === "string" ? props.page : null;
  const path = page ? block.pagePath(page) : null;
  if (!path) return null;
  // The path is built at run time, so the router cannot type it.
  return createElement(
    Link,
    {
      to: path,
      search: { page },
      className: "font-medium text-primary underline-offset-4 hover:underline",
    } as never,
    children
  );
}

/** The block elements as components, by the names a block's template writes. */
const BLOCK_ELEMENT_COMPONENTS = {
  timer: Timer,
  copy: CopyValue,
  button: ActionButton,
  "menu-item": ActionMenuItem,
  open: OpenPage,
};

interface PluginBlockProps {
  block: OfferedBlock;
  task: TaskListRead;
  rows: BlockRows | undefined;
  kind: BlockAreaKind;
  className: string | undefined;
  shared: BlockShared;
}

function PluginBlock({ block, task, rows, kind, className, shared }: PluginBlockProps) {
  const row = rows?.rows?.[task.id] ?? null;
  // What the template reads, the same object while nothing it reads changes.
  const data = useMemo(
    () => ({
      task,
      answer: row,
      strings: block.strings,
      now: shared.now,
      area: kind,
      width: shared.width,
    }),
    [task, row, block.strings, shared.now, shared.width, kind]
  );
  const place = useMemo(
    () => ({ block, taskId: task.id, kind, shared }),
    [block, task.id, kind, shared]
  );

  const template = block.compiled.template;
  const failed = !template || rows?.failed;
  if (kind === "menu") {
    if (failed || rows?.pending) return null;
  } else if (kind === "inline") {
    if (failed) return null;
    if (rows?.pending) {
      return <Skeleton aria-hidden className={cn("h-5 w-12", className)} />;
    }
  }

  const body =
    failed || !template ? (
      <p className="text-muted-foreground text-sm">{shared.t("blocks.unavailable")}</p>
    ) : rows?.pending ? (
      <Skeleton className="h-12 w-full" />
    ) : (
      renderTemplate(template, {
        data,
        context: undefined,
        parts: {},
        communityId: block.request.communityId,
        elements: BLOCK_ELEMENT_COMPONENTS,
        classes: PLUGIN_CLASSES,
      })
    );

  return (
    <Place.Provider value={place}>
      {kind === "inline" ? (
        // biome-ignore lint/a11y/useSemanticElements: a fieldset belongs to a form; this names one plug-in's block on a line of badges.
        <span
          role="group"
          aria-label={block.label}
          className={cn("inline-flex min-w-0 max-w-full items-center gap-1 text-xs", className)}
        >
          {body}
        </span>
      ) : kind === "panel" ? (
        <section
          aria-label={block.label}
          aria-busy={rows?.pending}
          className={cn("space-y-2 rounded-xl border bg-card p-4 text-card-foreground", className)}
        >
          <h3 className="font-medium text-sm">{block.name}</h3>
          {body}
        </section>
      ) : (
        <DropdownMenuGroup aria-label={block.label}>
          <DropdownMenuLabel>{block.name}</DropdownMenuLabel>
          {body}
        </DropdownMenuGroup>
      )}
    </Place.Provider>
  );
}

export interface PluginBlockAreaProps {
  kind: BlockAreaKind;
  blocks: readonly OfferedBlock[];
  rows: ReadonlyMap<string, BlockRows>;
  task: TaskListRead;
  className: string | undefined;
  shared: BlockShared;
}

/** One block area's blocks for one task. No element of its own, except a menu's trigger. */
export function PluginBlockArea({
  kind,
  blocks,
  rows,
  task,
  className,
  shared,
}: PluginBlockAreaProps) {
  const drawn = blocks.map((block) => (
    <PluginBlock
      key={block.key}
      block={block}
      task={task}
      rows={rows.get(block.key)}
      kind={kind}
      className={kind === "menu" ? undefined : className}
      shared={shared}
    />
  ));
  if (kind !== "menu") return drawn;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="icon"
          className={className}
          aria-label={shared.t("blocks.menu")}
        >
          <Puzzle className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">{drawn}</DropdownMenuContent>
    </DropdownMenu>
  );
}
