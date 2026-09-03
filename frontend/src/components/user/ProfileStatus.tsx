import { MessageCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CustomStatusOutput, UserSelfUpdate } from "@/api/generated/initiativeAPI.schemas";
import { EmojiPicker } from "@/components/EmojiPicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useUpdateCurrentUser } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { cn } from "@/lib/utils";

/** Mirrors ``STATUS_TEXT_MAX_LENGTH`` on the server. */
const STATUS_MAX_LENGTH = 40;

const isEmpty = (status: CustomStatusOutput) => !status.emoji && !status.text;

/** Which way the dots run: toward the picture, wherever it is. */
export type Tail = "up" | "down";

/**
 * The bubble itself, which is all a reader of someone else's profile gets.
 *
 * A thought bubble rather than a speech one: a status is what someone is
 * thinking about, not something they said to you. So the tail is two dots
 * shrinking toward whoever is thinking it, and which way they run depends on
 * where the picture is — above the bubble in the sidebar, below it everywhere
 * the bubble leads.
 */
const Bubble = ({
  status,
  muted,
  tail,
  className,
}: {
  status: CustomStatusOutput;
  muted?: boolean;
  tail: Tail;
  className?: string;
}) => {
  const { t } = useTranslation("profiles");
  // Offset from the left edge so it reads as coming from the picture rather
  // than from the corner of the box, and set on a diagonal so the pair points
  // at the face instead of running flat beside the bubble. The near dot tucks
  // into the bubble's edge — the bubble is positioned, so it paints over what
  // it covers — because a tail that clears the body reads as three loose
  // circles rather than one thought.
  const dots = (
    <span
      aria-hidden="true"
      className={cn("flex items-center gap-0.5 pl-4", tail === "down" ? "-mt-1" : "-mb-1")}
    >
      <span
        className={cn(
          "block size-1.5 rounded-full border bg-card",
          tail === "down" ? "translate-y-1" : "-translate-y-1"
        )}
      />
      <span className="block size-2.5 rounded-full border bg-card" />
    </span>
  );
  return (
    <span className={cn("inline-block max-w-full text-left", className)}>
      {tail === "up" ? dots : null}
      <span
        className={cn(
          "relative flex max-w-full items-center gap-2 rounded-[1.25rem] border bg-card px-3.5 py-2",
          muted && "text-muted-foreground"
        )}
      >
        {status.emoji ? (
          <span className="text-lg leading-none" aria-hidden="true">
            {status.emoji}
          </span>
        ) : (
          <MessageCircle className="size-4 shrink-0 opacity-60" aria-hidden="true" />
        )}
        <span className="min-w-0 break-words">{status.text || t("status.empty")}</span>
      </span>
      {tail === "down" ? dots : null}
    </span>
  );
};

/**
 * What someone is up to, in their own words.
 *
 * A bubble rather than a line of text, because it is a thing a person said
 * rather than a field of their record — and on your own profile it is the
 * control too: the whole point of a status is that you change it as often as
 * it changes, so it is edited where it is read instead of on a form somewhere
 * else. The emoji and the line are set together, in one popover, because they
 * are one thing and either half may be left out.
 */
export const ProfileStatus = ({
  status,
  editable = false,
  tail = "down",
  onSaved,
  className,
}: {
  status: CustomStatusOutput;
  /** Whether this is your own profile, and the bubble opens an editor. */
  editable?: boolean;
  /** Where the picture this belongs to is. Down — below the bubble — by default. */
  tail?: Tail;
  onSaved?: () => Promise<void> | void;
  className?: string;
}) => {
  const { t } = useTranslation(["profiles", "common"]);
  const [open, setOpen] = useState(false);
  const [emoji, setEmoji] = useState(status.emoji ?? null);
  const [text, setText] = useState(status.text ?? "");

  useEffect(() => {
    setEmoji(status.emoji ?? null);
    setText(status.text ?? "");
  }, [status.emoji, status.text]);

  const save = useUpdateCurrentUser({
    onSuccess: async () => {
      setOpen(false);
      await onSaved?.();
    },
    onError: (error: unknown) => toast.error(getErrorMessage(error, "profiles:status.failed")),
  });

  const commit = (next: { emoji: string | null; text: string | null }) =>
    save.mutate({ custom_status: next } as UserSelfUpdate);

  if (!editable) {
    if (isEmpty(status)) return null;
    return <Bubble status={status} tail={tail} className={className} />;
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "rounded-2xl text-left transition-opacity hover:opacity-80 focus-visible:outline-2 focus-visible:outline-ring",
            className
          )}
          aria-label={t("profiles:status.edit")}
        >
          <Bubble status={status} muted={isEmpty(status)} tail={tail} />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 space-y-3">
        <div className="space-y-1">
          <p className="font-medium text-sm">{t("profiles:status.edit")}</p>
          <p className="text-muted-foreground text-xs">{t("profiles:status.help")}</p>
        </div>
        <div className="flex gap-2">
          <div className="w-28 shrink-0">
            <EmojiPicker
              id="profile-status-emoji"
              value={emoji}
              onChange={setEmoji}
              placeholder={t("profiles:status.emojiPlaceholder")}
            />
          </div>
          <Input
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder={t("profiles:status.placeholder")}
            maxLength={STATUS_MAX_LENGTH}
            aria-label={t("profiles:status.placeholder")}
          />
        </div>
        <div className="flex justify-between gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={save.isPending || isEmpty(status)}
            onClick={() => commit({ emoji: null, text: null })}
          >
            {t("profiles:status.clear")}
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={save.isPending}
            onClick={() => commit({ emoji, text: text || null })}
          >
            {save.isPending ? t("common:submitting") : t("profiles:status.save")}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
};
