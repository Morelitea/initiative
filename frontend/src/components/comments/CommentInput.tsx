import { AtSign, Hash } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { MarkdownComposer } from "@/components/markdown/MarkdownComposer";
import type { ToolbarItem } from "@/components/markdown/MarkdownToolbar";
import { Button } from "@/components/ui/button";
import { getCaretCoordinates } from "@/lib/caretCoordinates";
import type { ActiveMention } from "@/lib/mentions";
import {
  activeMention,
  ENTITY_TRIGGER,
  entityMentionSyntax,
  USER_TRIGGER,
  userMentionSyntax,
} from "@/lib/mentions";

import { CommentContent } from "./CommentContent";
import { CommentReferences } from "./CommentReferences";
import type { MentionChoice } from "./MentionPopover";
import { MentionPopover } from "./MentionPopover";

// Matches the popover width (w-64) so it can be clamped inside the field.
const POPOVER_WIDTH = 256;

/** A mention being typed, and where in the field it starts. */
type MentionTrigger = ActiveMention & { startIndex: number };

/** The mention the caret is sitting in, if any. */
function detectMentionTrigger(text: string, cursorPosition: number): MentionTrigger | null {
  const active = activeMention(text.slice(0, cursorPosition));
  if (!active) return null;
  return { ...active, startIndex: cursorPosition - active.length };
}

interface CommentInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (content: string) => void;
  placeholder?: string;
  submitLabel?: string;
  isSubmitting?: boolean;
  initiativeId: number;
  /** The thing being commented on, as a reference (`document:12`). A comment
   *  does not point at what it is a remark about — that is the page it is
   *  already on — so it is never offered. */
  subject?: string | null;
  error?: string | null;
  onClearError?: () => void;
  autoFocus?: boolean;
  compact?: boolean;
  /** Asked to make something `[[ ]]` could not find, by the name typed. The
   *  composer does not create: it says what was asked for. */
  onCreateRequest?: (name: string) => void;
  /** When set, a Cancel button sits beside Submit and Escape dismisses. */
  onCancel?: () => void;
  cancelLabel?: string;
}

/** How long the mention popover survives a blur, so a click on it lands. */
const MENTION_BLUR_GRACE_MS = 200;

/**
 * The preview of a comment that has not been posted yet.
 *
 * It resolves its own mentions rather than borrowing the thread's: the names a
 * draft points at are, by definition, ones no posted comment has asked about.
 */
const DraftPreview = ({ content }: { content: string }) => {
  const contents = useMemo(() => [content], [content]);
  return (
    <CommentReferences contents={contents}>
      <CommentContent content={content} />
    </CommentReferences>
  );
};

export const CommentInput = ({
  value,
  onChange,
  onSubmit,
  placeholder,
  submitLabel,
  isSubmitting = false,
  initiativeId,
  subject,
  error,
  onClearError,
  autoFocus = false,
  compact = false,
  onCreateRequest,
  onCancel,
  cancelLabel,
}: CommentInputProps) => {
  const { t } = useTranslation(["comments", "common"]);
  const resolvedPlaceholder = placeholder ?? t("placeholder");
  const resolvedSubmitLabel = submitLabel ?? t("postComment");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [mentionTrigger, setMentionTrigger] = useState<MentionTrigger | null>(null);
  const blurTimer = useRef<number>(undefined);

  // A blur on the way out leaves a timer behind that would close a popover
  // belonging to a component that no longer exists.
  useEffect(() => () => window.clearTimeout(blurTimer.current), []);
  // Pixel anchor (relative to the field) for the popover, at the trigger char.
  const [mentionAnchor, setMentionAnchor] = useState<{ top: number; left: number } | null>(null);

  // Detect a mention trigger and, when present, compute the caret anchor so the
  // popover sits under the word being typed rather than under the whole field.
  const syncMentionTrigger = useCallback(
    (textarea: HTMLTextAreaElement, text: string, cursorPosition: number) => {
      const trigger = detectMentionTrigger(text, cursorPosition);
      setMentionTrigger(trigger);
      if (trigger) {
        const caret = getCaretCoordinates(textarea, trigger.startIndex);
        const maxLeft = Math.max(0, textarea.offsetWidth - POPOVER_WIDTH);
        setMentionAnchor({
          top: caret.top + caret.height + 4,
          left: Math.min(caret.left, maxLeft),
        });
      } else {
        setMentionAnchor(null);
      }
    },
    []
  );

  // Handle text changes and detect mention triggers
  const handleComposerChange = useCallback(
    (newValue: string) => {
      onChange(newValue);
      onClearError?.();
      const field = textareaRef.current;
      if (field) syncMentionTrigger(field, newValue, field.selectionStart);
    },
    [onChange, onClearError, syncMentionTrigger]
  );

  // Handle selection/cursor changes
  const handleSelect = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    syncMentionTrigger(textarea, value, textarea.selectionStart);
  }, [value, syncMentionTrigger]);

  // Handle mention selection
  const handleMentionSelect = useCallback(
    (choice: MentionChoice) => {
      if (!mentionTrigger || !textareaRef.current) return;

      // Making something is a different act from naming one, and it is the
      // caller's to do — it needs a dialog, and the composer has no business
      // opening one.
      if (!choice.user && "create" in choice) {
        onCreateRequest?.(choice.create);
        setMentionTrigger(null);
        return;
      }

      // The label is written into the text, so the characters the syntax is
      // built from cannot appear inside it.
      const label = (choice.user ? choice.label : choice.suggestion.title).replace(/[[\]()]/g, "");
      const mentionSyntax = choice.user
        ? userMentionSyntax(label, choice.id)
        : entityMentionSyntax(choice.suggestion.entity_type, label, choice.suggestion.entity_id);

      // Replace the trigger text with the mention syntax
      const beforeTrigger = value.slice(0, mentionTrigger.startIndex);
      const afterTrigger = value.slice(mentionTrigger.startIndex + mentionTrigger.length);
      const newValue = beforeTrigger + mentionSyntax + " " + afterTrigger;

      onChange(newValue);
      setMentionTrigger(null);

      // Focus and set cursor position after the mention
      const newCursorPosition = beforeTrigger.length + mentionSyntax.length + 1;
      setTimeout(() => {
        textareaRef.current?.focus();
        textareaRef.current?.setSelectionRange(newCursorPosition, newCursorPosition);
      }, 0);
    },
    [mentionTrigger, value, onChange, onCreateRequest]
  );

  // Close popover
  const handleCloseMention = useCallback(() => {
    setMentionTrigger(null);
  }, []);

  const renderDraft = useCallback((draft: string) => <DraftPreview content={draft} />, []);

  // A trigger the toolbar inserted, waiting for the new text to reach the
  // field before the caret can go after it.
  const pendingTrigger = useRef<number | null>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    const caret = pendingTrigger.current;
    if (!textarea || caret === null) return;
    pendingTrigger.current = null;
    textarea.focus();
    textarea.setSelectionRange(caret, caret);
    // Nothing was typed, so open the picker on the trigger that was placed.
    syncMentionTrigger(textarea, value, caret);
  }, [value, syncMentionTrigger]);

  /** Write a bare trigger at the caret and open the picker on it. */
  const insertTrigger = useCallback(
    (trigger: string) => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      const { selectionStart, selectionEnd } = textarea;
      const before = value.slice(0, selectionStart);
      // A trigger only counts at a word boundary, so one landing against a
      // word brings its own space — otherwise it reads as part of the word.
      const written = before === "" || /[\s([{]$/.test(before) ? trigger : ` ${trigger}`;
      pendingTrigger.current = selectionStart + written.length;
      onChange(before + written + value.slice(selectionEnd));
      onClearError?.();
    },
    [value, onChange, onClearError]
  );

  const mentionTools = useMemo<ToolbarItem[]>(
    () => [
      {
        id: "mention-user",
        label: t("insertUserMention"),
        icon: AtSign,
        onClick: () => insertTrigger(USER_TRIGGER),
      },
      {
        id: "mention-entity",
        label: t("insertEntityMention"),
        icon: Hash,
        onClick: () => insertTrigger(ENTITY_TRIGGER),
      },
    ],
    [insertTrigger, t]
  );

  // Handle form submit
  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) return;
    onSubmit(trimmed);
  };

  // Close popover on escape (backup handler)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && mentionTrigger) {
        setMentionTrigger(null);
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [mentionTrigger]);

  return (
    <form onSubmit={handleSubmit} className="space-y-2">
      <MarkdownComposer
        textareaRef={textareaRef}
        value={value}
        onChange={handleComposerChange}
        renderPreview={renderDraft}
        tools={mentionTools}
        onSelect={handleSelect}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !mentionTrigger) {
            e.preventDefault();
            const trimmed = value.trim();
            if (trimmed && !isSubmitting) {
              onSubmit(trimmed);
            }
            return;
          }
          // The mention popover claims Escape first; a second press dismisses
          // the whole field.
          if (e.key === "Escape" && !mentionTrigger && onCancel) {
            e.preventDefault();
            onCancel();
          }
        }}
        onBlur={() => {
          // Held open a moment so a click on the popover lands before the
          // blur closes it — and the handle is kept so an unmount can cancel
          // it. Left to run, it sets state on a component that is gone.
          window.clearTimeout(blurTimer.current);
          blurTimer.current = window.setTimeout(() => {
            setMentionTrigger(null);
          }, MENTION_BLUR_GRACE_MS);
        }}
        placeholder={resolvedPlaceholder}
        rows={compact ? 2 : 4}
        disabled={isSubmitting}
        autoFocus={autoFocus}
        compact={compact}
        overlay={
          mentionTrigger ? (
            <MentionPopover
              active={mentionTrigger}
              initiativeId={initiativeId}
              subject={subject}
              anchor={mentionAnchor}
              onSelect={handleMentionSelect}
              onClose={handleCloseMention}
            />
          ) : null
        }
      />

      {error && <p className="text-destructive text-sm">{error}</p>}

      <div className="flex items-center justify-end gap-2">
        {onCancel && (
          <Button
            type="button"
            variant="ghost"
            size={compact ? "sm" : "default"}
            onClick={onCancel}
            disabled={isSubmitting}
          >
            {cancelLabel ?? t("common:cancel")}
          </Button>
        )}
        <Button
          type="submit"
          disabled={isSubmitting || value.trim().length === 0}
          size={compact ? "sm" : "default"}
        >
          {isSubmitting ? t("posting") : resolvedSubmitLabel}
        </Button>
      </div>
    </form>
  );
};
