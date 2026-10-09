/**
 * Plug-in blocks: a plug-in's template inserted into one of a section's block
 * areas, as it is.
 *
 * Initiative draws nothing of a block's own: its template is the whole of it,
 * inside a group naming its plug-in for assistive technology. A menu area
 * hosts its blocks' items in a menu of its own. Until a block's read has
 * answered, and when it could not, the block draws nothing; the task around
 * it never waits.
 *
 * Everything a block needs that the screen could ask for once, the screen asks
 * for (`useTaskBlocks`) and hands down in `BlockShared`.
 */

import { Puzzle } from "lucide-react";
import { createContext, type ReactNode, useContext, useMemo, useState } from "react";

import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import type { PluginBlockRequest } from "@/api/pluginData";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { WidthClass } from "@/hooks/useWidthClass";
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
  // On a card's badge row, the height of the badges beside it.
  const inline = usePlace().kind === "inline";
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className={inline ? "h-6 px-2 text-xs" : "h-7"}
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

/** The block elements as components, by the names a block's template writes. */
const BLOCK_ELEMENT_COMPONENTS = {
  button: ActionButton,
  "menu-item": ActionMenuItem,
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
  if (!template || rows?.pending || rows?.failed) return null;
  const body = renderTemplate(template, {
    data,
    context: undefined,
    parts: {},
    communityId: block.request.communityId,
    elements: BLOCK_ELEMENT_COMPONENTS,
    classes: PLUGIN_CLASSES,
  });

  return (
    <Place.Provider value={place}>
      {kind === "menu" ? (
        <DropdownMenuGroup aria-label={block.label}>{body}</DropdownMenuGroup>
      ) : (
        // biome-ignore lint/a11y/useSemanticElements: a fieldset belongs to a form; this names the plug-in a block came from.
        <span role="group" aria-label={block.label} className={cn("contents", className)}>
          {body}
        </span>
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
