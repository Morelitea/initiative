import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { getCaretCoordinates } from "@/lib/caretCoordinates";
import type { ActiveMention } from "@/lib/mentions";
import { activeMention, entityMentionSyntax, userMentionSyntax } from "@/lib/mentions";

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

export const CommentInput = ({
  value,
  onChange,
  onSubmit,
  placeholder,
  submitLabel,
  isSubmitting = false,
  initiativeId,
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
  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const newValue = e.target.value;
      onChange(newValue);
      onClearError?.();
      syncMentionTrigger(e.target, newValue, e.target.selectionStart);
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
      <div className="relative">
        <Textarea
          ref={textareaRef}
          value={value}
          onChange={handleChange}
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
            // Delay closing to allow click on popover
            setTimeout(() => {
              setMentionTrigger(null);
            }, 200);
          }}
          placeholder={resolvedPlaceholder}
          rows={compact ? 2 : 4}
          disabled={isSubmitting}
          autoFocus={autoFocus}
        />

        {mentionTrigger && (
          <MentionPopover
            active={mentionTrigger}
            initiativeId={initiativeId}
            anchor={mentionAnchor}
            onSelect={handleMentionSelect}
            onClose={handleCloseMention}
          />
        )}
      </div>

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
