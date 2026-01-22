import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { MentionPopover } from "./MentionPopover";
import type { MentionEntityType, MentionSuggestion } from "@/types/api";

interface MentionTrigger {
  type: MentionEntityType;
  triggerText: string;
  query: string;
  startIndex: number;
  position: { top: number; left: number };
}

// Detect mention triggers in text
function detectMentionTrigger(
  text: string,
  cursorPosition: number,
  textareaElement: HTMLTextAreaElement
): MentionTrigger | null {
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

      // Calculate position for popover
      const position = getCaretCoordinates(textareaElement, startIndex);

      return {
        type,
        triggerText: match[0],
        query,
        startIndex,
        position: {
          top: position.top + 24, // Below the text
          left: position.left,
        },
      };
    }
  }

  return null;
}

// Get caret coordinates in a textarea
function getCaretCoordinates(
  element: HTMLTextAreaElement,
  position: number
): { top: number; left: number } {
  // Create a mirror div to measure text
  const mirror = document.createElement("div");
  const style = getComputedStyle(element);

  // Copy styles that affect text layout
  const properties = [
    "fontFamily",
    "fontSize",
    "fontWeight",
    "fontStyle",
    "letterSpacing",
    "textTransform",
    "wordSpacing",
    "textIndent",
    "whiteSpace",
    "wordWrap",
    "wordBreak",
    "padding",
    "border",
    "boxSizing",
    "lineHeight",
  ] as const;

  mirror.style.position = "absolute";
  mirror.style.visibility = "hidden";
  mirror.style.overflow = "hidden";
  mirror.style.width = `${element.offsetWidth}px`;

  for (const prop of properties) {
    mirror.style[prop] = style[prop];
  }

  document.body.appendChild(mirror);

  // Insert text up to position with a span marker
  const textContent = element.value.substring(0, position);
  const lines = textContent.split("\n");
  mirror.innerHTML = "";

  for (let i = 0; i < lines.length; i++) {
    const lineDiv = document.createElement("div");
    lineDiv.textContent = lines[i] || " ";
    mirror.appendChild(lineDiv);
  }

  const marker = document.createElement("span");
  marker.textContent = "|";
  mirror.lastElementChild?.appendChild(marker);

  const rect = element.getBoundingClientRect();
  const markerRect = marker.getBoundingClientRect();
  const mirrorRect = mirror.getBoundingClientRect();

  const top = rect.top + (markerRect.top - mirrorRect.top) - element.scrollTop;
  const left = rect.left + (markerRect.left - mirrorRect.left) - element.scrollLeft;

  document.body.removeChild(mirror);

  return { top, left };
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
  placeholder = "Share feedback or ask a question...",
  submitLabel = "Post Comment",
  isSubmitting = false,
  initiativeId,
  error,
  onClearError,
  autoFocus = false,
  compact = false,
}: CommentInputProps) => {
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
      const trigger = detectMentionTrigger(newValue, cursorPosition, e.target);
      setMentionTrigger(trigger);
    },
    [onChange, onClearError]
  );

  // Handle selection/cursor changes
  const handleSelect = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const cursorPosition = textarea.selectionStart;
    const trigger = detectMentionTrigger(value, cursorPosition, textarea);
    setMentionTrigger(trigger);
  }, [value]);

  // Handle mention selection
  const handleMentionSelect = useCallback(
    (suggestion: MentionSuggestion) => {
      if (!mentionTrigger || !textareaRef.current) return;

      // Build the mention syntax
      let mentionSyntax = "";
      switch (suggestion.type) {
        case "user":
          mentionSyntax = `@{${suggestion.id}}`;
          break;
        case "task":
          mentionSyntax = `#task:${suggestion.id}`;
          break;
        case "doc":
          mentionSyntax = `#doc:${suggestion.id}`;
          break;
        case "project":
          mentionSyntax = `#project:${suggestion.id}`;
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

  // Close popover on escape
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
    <form onSubmit={handleSubmit} className="relative space-y-2">
      <Textarea
        ref={textareaRef}
        value={value}
        onChange={handleChange}
        onSelect={handleSelect}
        onBlur={() => {
          // Delay closing to allow click on popover
          setTimeout(() => {
            if (!document.activeElement?.closest("[data-mention-popover]")) {
              setMentionTrigger(null);
            }
          }, 200);
        }}
        placeholder={placeholder}
        rows={compact ? 2 : 4}
        disabled={isSubmitting}
        autoFocus={autoFocus}
      />

      {mentionTrigger && (
        <div data-mention-popover>
          <MentionPopover
            type={mentionTrigger.type}
            query={mentionTrigger.query}
            initiativeId={initiativeId}
            onSelect={handleMentionSelect}
            onClose={handleCloseMention}
            position={mentionTrigger.position}
          />
        </div>
      )}

      {error && <p className="text-destructive text-sm">{error}</p>}

      <div className="flex justify-end">
        <Button
          type="submit"
          disabled={isSubmitting || value.trim().length === 0}
          size={compact ? "sm" : "default"}
        >
          {isSubmitting ? "Posting..." : submitLabel}
        </Button>
      </div>
    </form>
  );
};
