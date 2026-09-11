import type { TableOfContentsEntry } from "@lexical/react/LexicalTableOfContentsPlugin";
import { TableOfContentsPlugin } from "@lexical/react/LexicalTableOfContentsPlugin";
import type { LexicalEditor } from "lexical";
import { ChevronRight } from "lucide-react";
import {
  createContext,
  type JSX,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { useTranslation } from "react-i18next";

import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-mobile";
import { getItem, setItem } from "@/lib/storage";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "document-outline-open";

/** How far below the top of the visible area a heading still counts as the one
 *  being read. */
const ACTIVE_HEADING_SLACK_PX = 24;

/** One heading, with the headings it contains. */
export interface OutlineNode {
  /** The Lexical node key, which is how the heading is found again. */
  key: string;
  text: string;
  /** 1–6, from the heading tag. */
  level: number;
  children: OutlineNode[];
}

/**
 * The document's headings as a tree.
 *
 * Lexical hands out a flat, ordered list; the nesting is inferred from the
 * levels alone. A shallower heading closes every deeper one still open, so a
 * document that starts at `h2` puts its `h2`s at the top level, and one that
 * jumps `h1` → `h3` files the `h3` under the `h1` rather than inventing an
 * empty `h2` to sit between them.
 */
export const buildOutlineTree = (entries: readonly TableOfContentsEntry[]): OutlineNode[] => {
  const roots: OutlineNode[] = [];
  const open: OutlineNode[] = [];

  for (const [key, text, tag] of entries) {
    const level = Number.parseInt(tag.slice(1), 10);
    const node: OutlineNode = {
      key,
      text,
      level: Number.isNaN(level) ? 1 : level,
      children: [],
    };

    while (open.length > 0 && open[open.length - 1].level >= node.level) {
      open.pop();
    }
    const parent = open[open.length - 1];
    if (parent) {
      parent.children.push(node);
    } else {
      roots.push(node);
    }
    open.push(node);
  }

  return roots;
};

interface OutlineSnapshot {
  entries: readonly TableOfContentsEntry[];
  editor: LexicalEditor | null;
}

const EMPTY_SNAPSHOT: OutlineSnapshot = { entries: [], editor: null };

interface OutlineStore {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => OutlineSnapshot;
  publish: (entries: readonly TableOfContentsEntry[], editor: LexicalEditor) => void;
}

const createOutlineStore = (): OutlineStore => {
  let snapshot = EMPTY_SNAPSHOT;
  const listeners = new Set<() => void>();

  return {
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getSnapshot: () => snapshot,
    publish: (entries, editor) => {
      snapshot = { entries, editor };
      for (const listener of listeners) {
        listener();
      }
    },
  };
};

const DocumentOutlineContext = createContext<OutlineStore | null>(null);

const NO_SUBSCRIBE = () => () => {};
const NO_SNAPSHOT = () => EMPTY_SNAPSHOT;

/**
 * Where the document's headings are published, above the editor that finds them
 * and the list that shows them.
 *
 * A store rather than plain context state on purpose: the headings change on
 * every keystroke inside one, and re-rendering the whole editor to move a word
 * in the list beside it is a cost nobody is asking for. Only what reads the
 * outline re-renders.
 */
export const DocumentOutlineScope = ({ children }: { children: ReactNode }) => {
  const storeRef = useRef<OutlineStore | null>(null);
  storeRef.current ??= createOutlineStore();

  return (
    <DocumentOutlineContext.Provider value={storeRef.current}>
      {children}
    </DocumentOutlineContext.Provider>
  );
};

const OutlinePublisher = ({
  entries,
  editor,
  store,
}: {
  entries: readonly TableOfContentsEntry[];
  editor: LexicalEditor;
  store: OutlineStore;
}): JSX.Element => {
  useEffect(() => {
    store.publish(entries, editor);
  }, [entries, editor, store]);

  return <></>;
};

/**
 * Reports the editor's headings up to the surrounding {@link DocumentOutlineScope}.
 *
 * Rendered among the plugins because only something inside the composer can see
 * the document. With no scope above it there is nothing listening, so on every
 * other surface an editor appears on it tracks nothing at all.
 */
export const DocumentOutlineTracker = () => {
  const store = useContext(DocumentOutlineContext);
  if (!store) {
    return null;
  }

  return (
    <TableOfContentsPlugin>
      {(entries, editor) => <OutlinePublisher entries={entries} editor={editor} store={store} />}
    </TableOfContentsPlugin>
  );
};

/** The nearest ancestor that scrolls, whose visible top is the reading line. */
const scrollPortTop = (element: HTMLElement): number => {
  let node = element.parentElement;
  while (node) {
    const overflowY = window.getComputedStyle(node).overflowY;
    if (overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay") {
      return node.getBoundingClientRect().top;
    }
    node = node.parentElement;
  }
  return 0;
};

/** The heading the reader is under — the last one to have passed the top of the
 *  visible area. */
const useActiveHeadingKey = (
  editor: LexicalEditor | null,
  keys: readonly string[]
): string | null => {
  const [activeKey, setActiveKey] = useState<string | null>(null);

  useEffect(() => {
    if (!editor || keys.length === 0) {
      setActiveKey(null);
      return;
    }

    let frame = 0;

    const measure = () => {
      frame = 0;
      const root = editor.getRootElement();
      if (!root) {
        return;
      }
      const line = scrollPortTop(root) + ACTIVE_HEADING_SLACK_PX;

      let current: string | null = null;
      for (const key of keys) {
        const element = editor.getElementByKey(key);
        if (!element) {
          continue;
        }
        if (element.getBoundingClientRect().top > line) {
          break;
        }
        current = key;
      }
      setActiveKey(current ?? keys[0] ?? null);
    };

    const schedule = () => {
      if (frame === 0) {
        frame = window.requestAnimationFrame(measure);
      }
    };

    measure();
    // Capture, because what scrolls is the editor's own scrollport in one
    // layout and the page itself in another.
    window.addEventListener("scroll", schedule, true);
    window.addEventListener("resize", schedule);
    return () => {
      if (frame !== 0) {
        window.cancelAnimationFrame(frame);
      }
      window.removeEventListener("scroll", schedule, true);
      window.removeEventListener("resize", schedule);
    };
  }, [editor, keys]);

  return activeKey;
};

const flattenKeys = (nodes: readonly OutlineNode[], into: string[] = []): string[] => {
  for (const node of nodes) {
    into.push(node.key);
    flattenKeys(node.children, into);
  }
  return into;
};

const OutlineBranch = ({
  nodes,
  depth,
  activeKey,
  collapsed,
  onToggle,
  onSelect,
}: {
  nodes: readonly OutlineNode[];
  depth: number;
  activeKey: string | null;
  collapsed: ReadonlySet<string>;
  onToggle: (key: string) => void;
  onSelect: (key: string) => void;
}) => {
  const { t } = useTranslation("documents");

  return (
    <ul className="space-y-px">
      {nodes.map((node) => {
        const hasChildren = node.children.length > 0;
        const isCollapsed = collapsed.has(node.key);
        const label = node.text.trim();
        const isActive = node.key === activeKey;

        return (
          <li key={node.key}>
            <div
              className={cn("flex items-start gap-0.5 rounded-md", isActive && "bg-accent")}
              style={{ marginInlineStart: `${depth * 0.75}rem` }}
            >
              {hasChildren ? (
                <button
                  type="button"
                  onClick={() => onToggle(node.key)}
                  aria-expanded={!isCollapsed}
                  aria-label={t(isCollapsed ? "outline.expand" : "outline.collapse", {
                    heading: label || t("outline.untitled"),
                  })}
                  className="mt-1.5 shrink-0 rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  <ChevronRight
                    className={cn("h-3.5 w-3.5 transition-transform", !isCollapsed && "rotate-90")}
                  />
                </button>
              ) : (
                <span aria-hidden="true" className="w-[1.125rem] shrink-0" />
              )}
              <button
                type="button"
                onClick={() => onSelect(node.key)}
                title={label || undefined}
                aria-current={isActive ? "location" : undefined}
                className={cn(
                  "min-w-0 flex-1 truncate rounded-md px-1 py-1 text-left text-sm hover:text-foreground",
                  isActive ? "font-medium text-foreground" : "text-muted-foreground"
                )}
              >
                {label || <span className="italic opacity-70">{t("outline.untitled")}</span>}
              </button>
            </div>
            {hasChildren && !isCollapsed ? (
              <OutlineBranch
                nodes={node.children}
                depth={depth + 1}
                activeKey={activeKey}
                collapsed={collapsed}
                onToggle={onToggle}
                onSelect={onSelect}
              />
            ) : null}
          </li>
        );
      })}
    </ul>
  );
};

const OutlineTree = ({ onNavigate }: { onNavigate?: () => void }) => {
  const { t } = useTranslation("documents");
  const store = useContext(DocumentOutlineContext);
  const snapshot = useSyncExternalStore(
    store?.subscribe ?? NO_SUBSCRIBE,
    store?.getSnapshot ?? NO_SNAPSHOT
  );
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set());

  const tree = useMemo(() => buildOutlineTree(snapshot.entries), [snapshot.entries]);
  const keys = useMemo(() => flattenKeys(tree), [tree]);
  const activeKey = useActiveHeadingKey(snapshot.editor, keys);

  const toggle = useCallback((key: string) => {
    setCollapsed((current) => {
      const next = new Set(current);
      if (!next.delete(key)) {
        next.add(key);
      }
      return next;
    });
  }, []);

  const select = useCallback(
    (key: string) => {
      snapshot.editor?.getElementByKey(key)?.scrollIntoView({ behavior: "smooth", block: "start" });
      onNavigate?.();
    },
    [snapshot.editor, onNavigate]
  );

  if (tree.length === 0) {
    return <p className="px-1 text-muted-foreground text-sm">{t("outline.empty")}</p>;
  }

  return (
    <nav aria-label={t("outline.title")}>
      <OutlineBranch
        nodes={tree}
        depth={0}
        activeKey={activeKey}
        collapsed={collapsed}
        onToggle={toggle}
        onSelect={select}
      />
    </nav>
  );
};

/**
 * The document's contents, as a list of its headings.
 *
 * Two presentations of the same tree. Beside the document there is room for a
 * column; on a phone there is not, so it takes the document view over entirely
 * rather than squeezing the words it exists to navigate into a gutter.
 */
export const DocumentOutlinePanel = ({
  isOpen,
  onOpenChange,
  className,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  className?: string;
}) => {
  const { t } = useTranslation("documents");
  const isMobile = useIsMobile();

  if (isMobile) {
    return (
      <Sheet open={isOpen} onOpenChange={onOpenChange}>
        <SheetContent
          side="left"
          className="flex w-full flex-col overflow-hidden p-0 sm:max-w-none"
        >
          <SheetHeader
            className="border-b px-4"
            style={{
              paddingTop: "calc(var(--safe-area-inset-top) + 0.75rem)",
              paddingBottom: "0.75rem",
            }}
          >
            <SheetTitle className="text-base">{t("outline.title")}</SheetTitle>
          </SheetHeader>
          <div className="flex-1 overflow-y-auto p-4">
            <OutlineTree onNavigate={() => onOpenChange(false)} />
          </div>
        </SheetContent>
      </Sheet>
    );
  }

  if (!isOpen) {
    return null;
  }

  return (
    <aside
      className={cn(
        "flex min-h-0 flex-col overflow-hidden rounded-lg border bg-card shadow",
        className
      )}
    >
      <div className="border-b px-3 py-2 font-medium text-sm">{t("outline.title")}</div>
      <div className="flex-1 overflow-y-auto p-2">
        <OutlineTree />
      </div>
    </aside>
  );
};

/** Whether the outline is showing. Closed until somebody opens it, and then
 *  remembered, the same as the document's other panels. */
export const useDocumentOutline = () => {
  const [isOpen, setIsOpen] = useState(() => getItem(STORAGE_KEY) === "true");

  useEffect(() => {
    setItem(STORAGE_KEY, String(isOpen));
  }, [isOpen]);

  return {
    isOpen,
    setIsOpen,
    toggle: useCallback(() => setIsOpen((current) => !current), []),
  };
};
