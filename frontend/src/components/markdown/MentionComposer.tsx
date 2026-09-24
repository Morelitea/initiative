import { AtSign, Hash } from "lucide-react";
import {
  type ComponentProps,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { CommentContent } from "@/components/comments/CommentContent";
import { CommentReferences } from "@/components/comments/CommentReferences";
import type { MentionChoice } from "@/components/comments/MentionPopover";
import { MentionPopover } from "@/components/comments/MentionPopover";
import { CreateReferencedThingDialog } from "@/components/references/CreateReferencedThingDialog";
import { getCaretCoordinates } from "@/lib/caretCoordinates";
import type { ActiveMention } from "@/lib/mentions";
import {
  activeMention,
  ENTITY_TRIGGER,
  entityMentionSyntax,
  USER_TRIGGER,
  userMentionSyntax,
} from "@/lib/mentions";

import { MarkdownComposer } from "./MarkdownComposer";
import type { ToolbarItem } from "./MarkdownToolbar";

// Matches the popover width (w-64) so it can be clamped inside the field.
const POPOVER_WIDTH = 256;

/** How long the mention popover survives a blur, so a click on it lands. */
const MENTION_BLUR_GRACE_MS = 200;

/** A mention being typed, and where in the field it starts. */
type MentionTrigger = ActiveMention & { startIndex: number };

/** The mention the caret is sitting in, if any. */
function detectMentionTrigger(text: string, cursorPosition: number): MentionTrigger | null {
  const active = activeMention(text.slice(0, cursorPosition));
  if (!active) return null;
  return { ...active, startIndex: cursorPosition - active.length };
}

/**
 * The preview of text that has not been saved yet.
 *
 * It resolves its own mentions rather than borrowing a page's: the names a
 * draft points at are, by definition, ones nothing saved has asked about.
 */
const DraftPreview = ({ content }: { content: string }) => {
  const contents = useMemo(() => [content], [content]);
  return (
    <CommentReferences contents={contents}>
      <CommentContent content={content} />
    </CommentReferences>
  );
};

const renderDraft = (draft: string) => <DraftPreview content={draft} />;

type MarkdownComposerProps = ComponentProps<typeof MarkdownComposer>;

interface MentionComposerProps
  extends Omit<MarkdownComposerProps, "overlay" | "textareaRef" | "renderPreview"> {
  /** Whose members `@` offers and whose tools `#` searches. */
  initiativeId: number;
  /** The thing being written about, as a reference (`task:12`). Never offered:
   *  text about something does not point back at it. */
  subject?: string | null;
  /** What the preview tab shows. Defaults to the comment renderer, which
   *  reads mentions. */
  renderPreview?: (value: string) => ReactNode;
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
}

/**
 * A markdown field that can name people and things: `@` for a member of the
 * initiative, `#` for anything in it, `[[` for a tool — made on the spot when
 * it does not exist yet.
 *
 * What it writes is plain markdown with the mention syntax in it, so whatever
 * stores the text stores the mentions with it, and whatever renders it with
 * mentions turned on reads them back as chips.
 *
 * While the picker is open it owns the keyboard: `onKeyDown` hears nothing
 * until it closes, so a caller's own keys — submit, dismiss — never fire
 * underneath a half-typed mention.
 */
export const MentionComposer = ({
  value,
  onChange,
  initiativeId,
  subject,
  renderPreview = renderDraft,
  textareaRef: callerRef,
  tools,
  onKeyDown,
  onSelect,
  onBlur,
  ...composerProps
}: MentionComposerProps) => {
  const { t } = useTranslation("comments");
  const ownRef = useRef<HTMLTextAreaElement>(null);
  const textareaRef = callerRef ?? ownRef;
  const [mentionTrigger, setMentionTrigger] = useState<MentionTrigger | null>(null);
  // Pixel anchor (relative to the field) for the popover, at the trigger char.
  const [mentionAnchor, setMentionAnchor] = useState<{ top: number; left: number } | null>(null);
  // A name `[[` could not find, and the stretch of text asking for it — which
  // the made thing replaces, so making something never costs the writer their
  // place in the sentence.
  const [pendingCreate, setPendingCreate] = useState<{
    name: string;
    start: number;
    end: number;
  } | null>(null);
  const blurTimer = useRef<number>(undefined);

  // A blur on the way out leaves a timer behind that would close a popover
  // belonging to a component that no longer exists.
  useEffect(() => () => window.clearTimeout(blurTimer.current), []);

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

  const handleChange = useCallback(
    (next: string) => {
      onChange(next);
      const field = textareaRef.current;
      if (field) syncMentionTrigger(field, next, field.selectionStart);
    },
    [onChange, syncMentionTrigger, textareaRef]
  );

  const handleSelect = useCallback(() => {
    onSelect?.();
    const textarea = textareaRef.current;
    if (!textarea) return;
    syncMentionTrigger(textarea, value, textarea.selectionStart);
  }, [onSelect, value, syncMentionTrigger, textareaRef]);

  /** Put `written` where the text from `start` to `end` was, caret after it. */
  const replaceRange = useCallback(
    (start: number, end: number, written: string) => {
      const before = value.slice(0, start);
      onChange(`${before}${written} ${value.slice(end)}`);
      const caret = before.length + written.length + 1;
      setTimeout(() => {
        textareaRef.current?.focus();
        textareaRef.current?.setSelectionRange(caret, caret);
      }, 0);
    },
    [value, onChange, textareaRef]
  );

  const handleMentionSelect = useCallback(
    (choice: MentionChoice) => {
      if (!mentionTrigger) return;
      const start = mentionTrigger.startIndex;
      const end = start + mentionTrigger.length;
      setMentionTrigger(null);

      // Making something is a different act from naming one: it needs a
      // dialog, which says which tools this initiative has and which the
      // writer may add.
      if (!choice.user && "create" in choice) {
        setPendingCreate({ name: choice.create, start, end });
        return;
      }

      // The label is written into the text, so the characters the syntax is
      // built from cannot appear inside it.
      const label = (choice.user ? choice.label : choice.suggestion.title).replace(/[[\]()]/g, "");
      replaceRange(
        start,
        end,
        choice.user
          ? userMentionSyntax(label, choice.id)
          : entityMentionSyntax(choice.suggestion.entity_type, label, choice.suggestion.entity_id)
      );
    },
    [mentionTrigger, replaceRange]
  );

  const handleCloseMention = useCallback(() => {
    setMentionTrigger(null);
  }, []);

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
  }, [value, syncMentionTrigger, textareaRef]);

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
    },
    [value, onChange, textareaRef]
  );

  const allTools = useMemo<ToolbarItem[]>(
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
      ...(tools ?? []),
    ],
    [insertTrigger, t, tools]
  );

  // Close popover on escape (backup handler)
  useEffect(() => {
    if (!mentionTrigger) return;
    const handleKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setMentionTrigger(null);
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [mentionTrigger]);

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (!mentionTrigger) onKeyDown?.(event);
  };

  return (
    <>
      <MarkdownComposer
        {...composerProps}
        textareaRef={textareaRef}
        value={value}
        onChange={handleChange}
        renderPreview={renderPreview}
        tools={allTools}
        onSelect={handleSelect}
        onKeyDown={handleKeyDown}
        onBlur={() => {
          onBlur?.();
          // Held open a moment so a click on the popover lands before the
          // blur closes it — and the handle is kept so an unmount can cancel
          // it. Left to run, it sets state on a component that is gone.
          window.clearTimeout(blurTimer.current);
          blurTimer.current = window.setTimeout(() => {
            setMentionTrigger(null);
          }, MENTION_BLUR_GRACE_MS);
        }}
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
      {pendingCreate !== null && (
        <CreateReferencedThingDialog
          name={pendingCreate.name}
          initiativeId={initiativeId}
          onCreated={(made) => {
            replaceRange(
              pendingCreate.start,
              pendingCreate.end,
              entityMentionSyntax(made.entityType, made.name, made.entityId)
            );
            setPendingCreate(null);
          }}
          onClose={() => setPendingCreate(null)}
        />
      )}
    </>
  );
};
