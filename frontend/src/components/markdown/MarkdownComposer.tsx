import {
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { Markdown } from "@/components/Markdown";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import type { MarkdownSelection, MarkdownTransform } from "@/lib/markdownEditing";
import { cn } from "@/lib/utils";

import { MARKDOWN_SHORTCUTS, MarkdownToolbar, type ToolbarItem } from "./MarkdownToolbar";

type ComposerMode = "write" | "preview";

interface MarkdownComposerProps {
  value: string;
  onChange: (value: string) => void;
  /** What the preview tab shows. Defaults to the same markdown renderer the
   *  rest of the product reads prose with. */
  renderPreview?: (value: string) => ReactNode;
  id?: string;
  placeholder?: string;
  rows?: number;
  disabled?: boolean;
  autoFocus?: boolean;
  /** The caller's own handle on the field — for caret measurement, focus, and
   *  anything else that needs the element itself. */
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
  /** Absolutely positioned against the field, so it can anchor to the caret.
   *  The mention popover lives here. */
  overlay?: ReactNode;
  /** Extra controls beside the tabs — an AI action, say. */
  actions?: ReactNode;
  /** A surface's own toolbar actions, which share the row's overflow menu.
   *  A comment's mention triggers are these. */
  tools?: ToolbarItem[];
  /** Shrinks the chrome for a reply box or an inline edit. */
  compact?: boolean;
  className?: string;
  onKeyDown?: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  onSelect?: () => void;
  onBlur?: () => void;
}

/**
 * A markdown field with the two things writing markdown needs: buttons for the
 * syntax nobody remembers, and a way to see what it will look like before
 * committing to it.
 *
 * The field itself stays plain markdown source — switching to Preview hides it
 * rather than replacing it, so the caret, the scroll position, and anything
 * anchored to them survive the round trip.
 */
export const MarkdownComposer = ({
  value,
  onChange,
  renderPreview,
  id,
  placeholder,
  rows,
  disabled = false,
  autoFocus = false,
  textareaRef,
  overlay,
  actions,
  tools,
  compact = false,
  className,
  onKeyDown,
  onSelect,
  onBlur,
}: MarkdownComposerProps) => {
  const { t } = useTranslation("common");
  const [mode, setMode] = useState<ComposerMode>("write");
  const innerRef = useRef<HTMLTextAreaElement>(null);
  // Where the caret goes once the edited text has rendered. Applying it in an
  // effect rather than straight after `onChange` is what keeps it correct: the
  // field still holds the old text until the owner re-renders with the new.
  const pendingSelection = useRef<[number, number] | null>(null);

  const assignRef = useCallback(
    (node: HTMLTextAreaElement | null) => {
      innerRef.current = node;
      if (textareaRef) textareaRef.current = node;
    },
    [textareaRef]
  );

  useEffect(() => {
    const field = innerRef.current;
    const pending = pendingSelection.current;
    if (!field || !pending) return;
    pendingSelection.current = null;
    field.focus();
    field.setSelectionRange(pending[0], pending[1]);
  });

  const apply = useCallback(
    (transform: MarkdownTransform) => {
      const field = innerRef.current;
      if (!field || disabled) return;
      const state: MarkdownSelection = {
        value,
        start: field.selectionStart,
        end: field.selectionEnd,
      };
      const next = transform(state);
      pendingSelection.current = [next.start, next.end];
      onChange(next.value);
    },
    [disabled, onChange, value]
  );

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    onKeyDown?.(event);
    if (event.defaultPrevented) return;
    if (!(event.metaKey || event.ctrlKey) || event.altKey) return;
    const transform = MARKDOWN_SHORTCUTS[event.key.toLowerCase()];
    if (!transform) return;
    event.preventDefault();
    apply(transform);
  };

  const preview = renderPreview ? renderPreview(value) : <Markdown content={value} />;
  // Nothing in the toolbar acts on text that is not on screen.
  const toolbarDisabled = disabled || mode === "preview";

  return (
    <Tabs
      value={mode}
      onValueChange={(next) => setMode(next as ComposerMode)}
      className={cn(
        "rounded-md border border-input bg-transparent shadow-sm focus-within:ring-1 focus-within:ring-ring",
        className
      )}
    >
      {/* One row that never wraps: the tabs and any action keep their size and
          the toolbar takes what is left, shedding buttons into its own menu
          rather than pushing the field down the screen. */}
      <div className="flex items-center gap-2 border-input border-b px-2 py-1.5">
        <TabsList className="h-8 shrink-0">
          <TabsTrigger value="write" className="text-xs">
            {t("markdownEditor.write")}
          </TabsTrigger>
          <TabsTrigger value="preview" className="text-xs">
            {t("markdownEditor.preview")}
          </TabsTrigger>
        </TabsList>
        <MarkdownToolbar
          onApply={apply}
          disabled={toolbarDisabled}
          className="min-w-0 flex-1"
          tools={tools}
        />
        {actions && <div className="shrink-0">{actions}</div>}
      </div>

      {/* Kept mounted so switching tabs doesn't throw away the caret, the
          scroll position, or a mention being typed — but `forceMount` alone
          also keeps it *shown*, so the panel is hidden explicitly. */}
      <TabsContent value="write" forceMount hidden={mode !== "write"} className="mt-0">
        <div className="relative">
          <Textarea
            id={id}
            ref={assignRef}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
            onSelect={onSelect}
            onBlur={onBlur}
            placeholder={placeholder}
            rows={rows ?? (compact ? 3 : 6)}
            disabled={disabled}
            autoFocus={autoFocus}
            className="resize-y rounded-none rounded-b-md border-0 shadow-none focus-visible:ring-0"
          />
          {overlay}
        </div>
      </TabsContent>

      <TabsContent value="preview" className="mt-0">
        <div
          className={cn(
            "overflow-x-auto px-3 py-2",
            compact ? "min-h-16" : "min-h-24",
            !value.trim() && "text-muted-foreground text-sm italic"
          )}
        >
          {value.trim() ? preview : t("markdownEditor.nothingToPreview")}
        </div>
      </TabsContent>
    </Tabs>
  );
};
