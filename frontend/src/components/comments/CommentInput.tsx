import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { MentionPopover } from "./MentionPopover";
import type { MentionSuggestion } from "@/api/generated/initiativeAPI.schemas";
import type { MentionEntityType } from "@/types/api";

interface MentionTrigger {
  type: MentionEntityType;
  triggerText: string;
  query: string;
  startIndex: number;
}

// Detect mention triggers in text
function detectMentionTrigger(text: string, cursorPosition: number): MentionTrigger | null {
  // Get text before cursor
  const textBeforeCursor = text.slice(0, cursorPosition);

  // Check for triggers (in order of specificity)
  const triggers = [
    { pattern: /#project:(\w*)$/, type: "project" as const },
    { pattern: /#task:(\w*)$/, type: "task" as const },
    { pattern: /#doc:(\w*)$/, type: "doc" as const },
    { pattern: /@(\w*)$/, type: "user" as const },
  ];

  for (const { pattern, type } of triggers) {
    const match = textBeforeCursor.match(pattern);
    if (match) {
      const query = match[1] || "";
      const startIndex = cursorPosition - match[0].length;

      return {
        type,
        triggerText: match[0],
        query,
        startIndex,
      };
    }
  }

  return null;
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
}: CommentInputProps) => {
  const { t } = useTranslation("documents");
  const resolvedPlaceholder = placeholder ?? t("comments.placeholder");
  const resolvedSubmitLabel = submitLabel ?? t("comments.postComment");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [mentionTrigger, setMentionTrigger] = useState<MentionTrigger | null>(null);

  // Handle text changes and detect mention triggers
  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const newValue = e.target.value;
      onChange(newValue);
      onClearError?.();

      // Detect mention trigger
      const cursorPosition = e.target.selectionStart;
      const trigger = detectMentionTrigger(newValue, cursorPosition);
      setMentionTrigger(trigger);
    },
    [onChange, onClearError]
  );

  // Handle selection/cursor changes
  const handleSelect = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const cursorPosition = textarea.selectionStart;
    const trigger = detectMentionTrigger(value, cursorPosition);
    setMentionTrigger(trigger);
  }, [value]);

  // Handle mention selection
  const handleMentionSelect = useCallback(
    (suggestion: MentionSuggestion) => {
      if (!mentionTrigger || !textareaRef.current) return;

      // Build the mention syntax with embedded display text
      // Format: @[Display Name](id) or #type[Display Text](id)
      let mentionSyntax = "";
      const displayText = suggestion.display_text.replace(/[[\]()]/g, ""); // Sanitize brackets
      switch (suggestion.type) {
        case "user":
          mentionSyntax = `@[${displayText}](${suggestion.id})`;
          break;
        case "task":
          mentionSyntax = `#task[${displayText}](${suggestion.id})`;
          break;
        case "doc":
          mentionSyntax = `#doc[${displayText}](${suggestion.id})`;
          break;
        case "project":
          mentionSyntax = `#project[${displayText}](${suggestion.id})`;
          break;
      }

      // Replace the trigger text with the mention syntax
      const beforeTrigger = value.slice(0, mentionTrigger.startIndex);
      const afterTrigger = value.slice(
        mentionTrigger.startIndex + mentionTrigger.triggerText.length
      );
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
    [mentionTrigger, value, onChange]
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
            type={mentionTrigger.type}
            query={mentionTrigger.query}
            initiativeId={initiativeId}
            onSelect={handleMentionSelect}
            onClose={handleCloseMention}
          />
        )}
      </div>

      {error && <p className="text-destructive text-sm">{error}</p>}

      <div className="flex justify-end">
        <Button
          type="submit"
          disabled={isSubmitting || value.trim().length === 0}
          size={compact ? "sm" : "default"}
        >
          {isSubmitting ? t("comments.posting") : resolvedSubmitLabel}
        </Button>
      </div>
    </form>
  );
};
