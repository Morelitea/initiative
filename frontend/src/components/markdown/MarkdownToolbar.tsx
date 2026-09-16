import {
  Bold,
  Code,
  Heading,
  Italic,
  Link as LinkIcon,
  List,
  ListOrdered,
  ListTodo,
  MoreHorizontal,
  Strikethrough,
  TextQuote,
} from "lucide-react";
import {
  type ComponentType,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  BULLET_LIST,
  cycleHeading,
  insertLink,
  type MarkdownTransform,
  NUMBERED_LIST,
  QUOTE,
  TASK_LIST,
  toggleCode,
  toggleLinePrefix,
  toggleWrap,
} from "@/lib/markdownEditing";
import { cn } from "@/lib/utils";

/**
 * The edits a keyboard shortcut reaches, by the key that reaches them.
 *
 * No `k`, which GitHub gives to links: it belongs to the command centre here,
 * and a shortcut that opens the command centre *and* writes a link into the
 * comment you were typing is worse than no shortcut at all.
 */
export const MARKDOWN_SHORTCUTS: Record<string, MarkdownTransform> = {
  b: toggleWrap("**"),
  i: toggleWrap("_"),
  e: toggleCode,
};

// ``navigator.platform`` is deprecated; ``userAgent`` carries enough for a
// keyboard-hint heuristic, and matches the convention the editor toolbar uses.
const IS_APPLE =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad|iPod/.test(navigator.userAgent);

/** What the shortcut hints call the modifier on this platform. */
const MODIFIER = IS_APPLE ? "⌘" : "Ctrl+";

type ToolbarIcon = ComponentType<{ className?: string; "aria-hidden"?: boolean }>;

/**
 * One thing the toolbar can do, as data rather than as a rendered button.
 *
 * It has to be data because the same action is rendered two ways: a button
 * while it fits in the row, a menu entry once it doesn't.
 */
export interface ToolbarItem {
  id: string;
  label: string;
  icon: ToolbarIcon;
  onClick: () => void;
  /** Appended to the label in the tooltip — a keyboard shortcut, usually. */
  hint?: string;
  /** Opens a new group: a separator goes before it. */
  startsGroup?: boolean;
}

interface FormattingAction {
  id: string;
  /** Key in the `common:markdownEditor` group naming the button. */
  labelKey: string;
  icon: ToolbarIcon;
  transform: MarkdownTransform;
  shortcut?: string;
  startsGroup?: boolean;
}

/**
 * Ordered as GitHub's comment toolbar is, so the muscle memory carries over —
 * and, because the row sheds from the right, ordered by what a writer reaches
 * for most: heading, bold and italic are the last three to go.
 */
const FORMATTING_ACTIONS: FormattingAction[] = [
  { id: "heading", labelKey: "heading", icon: Heading, transform: cycleHeading },
  { id: "bold", labelKey: "bold", icon: Bold, transform: toggleWrap("**"), shortcut: "B" },
  { id: "italic", labelKey: "italic", icon: Italic, transform: toggleWrap("_"), shortcut: "I" },
  {
    id: "strikethrough",
    labelKey: "strikethrough",
    icon: Strikethrough,
    transform: toggleWrap("~~"),
  },
  { id: "quote", labelKey: "quote", icon: TextQuote, transform: toggleLinePrefix(QUOTE) },
  { id: "code", labelKey: "code", icon: Code, transform: toggleCode, shortcut: "E" },
  { id: "link", labelKey: "link", icon: LinkIcon, transform: insertLink },
  {
    id: "bulletedList",
    labelKey: "bulletedList",
    icon: List,
    transform: toggleLinePrefix(BULLET_LIST),
    startsGroup: true,
  },
  {
    id: "numberedList",
    labelKey: "numberedList",
    icon: ListOrdered,
    transform: toggleLinePrefix(NUMBERED_LIST),
  },
  { id: "taskList", labelKey: "taskList", icon: ListTodo, transform: toggleLinePrefix(TASK_LIST) },
];

/** One button in the row. */
const ToolbarButton = ({ item, disabled }: { item: ToolbarItem; disabled: boolean }) => (
  <Button
    type="button"
    variant="ghost"
    size="icon-sm"
    className="text-muted-foreground hover:text-foreground"
    disabled={disabled}
    title={item.hint ? `${item.label} (${item.hint})` : item.label}
    aria-label={item.label}
    // The field keeps the caret it had, so the edit lands where the writer
    // left off rather than at the start of the text.
    onMouseDown={(event) => event.preventDefault()}
    onClick={item.onClick}
  >
    <item.icon className="h-4 w-4" aria-hidden={true} />
  </Button>
);

const Divider = () => <span aria-hidden="true" className="mx-1 h-4 w-px shrink-0 bg-border" />;

/**
 * How many items of a single row fit, keeping room for the control that holds
 * the rest.
 *
 * Widths are read from the laid-out row and remembered, because an item that
 * has been put away measures nothing — and putting items away is the whole
 * point. Where there is no layout to read (a row that has not been painted, a
 * test environment), everything stays in the row: showing too much is a far
 * better failure than hiding something with nowhere to reach it.
 */
const useRowCapacity = (count: number) => {
  const rowRef = useRef<HTMLDivElement>(null);
  const widths = useRef<number[]>([]);
  const [fits, setFits] = useState(count);

  const measure = useCallback(() => {
    const row = rowRef.current;
    if (!row) return;

    const children = Array.from(row.children) as HTMLElement[];
    for (let index = 0; index < count; index++) {
      const width = children[index]?.offsetWidth ?? 0;
      if (width > 0) widths.current[index] = width;
    }

    const known = widths.current.slice(0, count);
    if (known.length < count || known.some((width) => !width)) {
      setFits(count);
      return;
    }

    const gap = Number.parseFloat(getComputedStyle(row).columnGap) || 0;
    const available = row.clientWidth;
    const total = known.reduce((sum, width) => sum + width + gap, -gap);
    if (total <= available) {
      setFits(count);
      return;
    }

    // The overflow control is the same button as the first item, which never
    // carries a separator — so that item's width is the control's width.
    let used = known[0] + gap;
    let fitted = 0;
    for (const width of known) {
      if (used + width > available) break;
      used += width + gap;
      fitted += 1;
    }
    setFits(fitted);
  }, [count]);

  useLayoutEffect(measure, [measure]);

  useEffect(() => {
    const row = rowRef.current;
    if (!row || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(row);
    return () => observer.disconnect();
  }, [measure]);

  return { rowRef, fits };
};

interface MarkdownToolbarProps {
  onApply: (transform: MarkdownTransform) => void;
  disabled?: boolean;
  className?: string;
  /** A surface's own actions, in a group of their own at the end — what a
   *  comment puts its mention triggers in. */
  tools?: ToolbarItem[];
}

/**
 * The formatting buttons over a markdown field.
 *
 * The row never wraps. As it narrows, the buttons that no longer fit move into
 * a menu at its end rather than pushing the field down the screen, so the same
 * toolbar serves a phone and a wide editor.
 *
 * Every button is a plain `button` rather than a submit control: the composer
 * often sits inside a form, and formatting a word must never post it.
 */
export const MarkdownToolbar = ({
  onApply,
  disabled = false,
  className,
  tools,
}: MarkdownToolbarProps) => {
  const { t } = useTranslation("common");

  const items: ToolbarItem[] = [
    ...FORMATTING_ACTIONS.map((action) => ({
      id: action.id,
      label: t(`markdownEditor.${action.labelKey}` as never) as string,
      icon: action.icon,
      hint: action.shortcut ? `${MODIFIER}${action.shortcut}` : undefined,
      startsGroup: action.startsGroup,
      onClick: () => onApply(action.transform),
    })),
    ...(tools ?? []).map((tool, index) => ({ ...tool, startsGroup: index === 0 })),
  ];

  const { rowRef, fits } = useRowCapacity(items.length);
  const overflowed = items.slice(fits);

  return (
    <div
      ref={rowRef}
      role="toolbar"
      aria-label={t("markdownEditor.toolbar")}
      className={cn("flex items-center justify-end gap-0.5 overflow-hidden", className)}
    >
      {items.map((item, index) => (
        // One element per item, its separator included, so the row's children
        // line up one-to-one with what is being measured.
        <span key={item.id} hidden={index >= fits} className="flex shrink-0 items-center">
          {item.startsGroup && index > 0 && <Divider />}
          <ToolbarButton item={item} disabled={disabled} />
        </span>
      ))}

      <span hidden={overflowed.length === 0} className="flex shrink-0 items-center">
        <Divider />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="text-muted-foreground hover:text-foreground"
              disabled={disabled}
              title={t("markdownEditor.more")}
              aria-label={t("markdownEditor.more")}
              onMouseDown={(event) => event.preventDefault()}
            >
              <MoreHorizontal className="h-4 w-4" aria-hidden={true} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {overflowed.map((item, index) => (
              <div key={item.id}>
                {item.startsGroup && index > 0 && <DropdownMenuSeparator />}
                <DropdownMenuItem onSelect={item.onClick}>
                  <item.icon className="h-4 w-4" aria-hidden={true} />
                  {item.label}
                </DropdownMenuItem>
              </div>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </span>
    </div>
  );
};
