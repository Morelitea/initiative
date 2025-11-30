import { useEffect, useRef, useState } from "react";
import EmojiPickerBase, { EmojiClickData, Theme } from "emoji-picker-react";

import { Button } from "@/components/ui/button";

interface EmojiPickerProps {
  id?: string;
  value?: string | null;
  onChange: (emoji: string | null) => void;
  disabled?: boolean;
  placeholder?: string;
}

export const EmojiPicker = ({
  id,
  value,
  onChange,
  disabled = false,
  placeholder = "Pick an emoji",
}: EmojiPickerProps) => {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    const handleClick = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const handleEmojiClick = (emojiData: EmojiClickData) => {
    onChange(emojiData.emoji);
    setOpen(false);
  };

  return (
    <div ref={containerRef} className="relative flex w-full flex-col gap-1">
      <Button
        type="button"
        id={id}
        variant="outline"
        className="w-full justify-start"
        onClick={() => setOpen((prev) => !prev)}
        disabled={disabled}
      >
        {value ? (
          <span className="text-xl leading-none">{value}</span>
        ) : (
          <span className="text-sm">{placeholder}</span>
        )}
      </Button>
      {value ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="self-start px-2"
          onClick={() => onChange(null)}
          disabled={disabled}
        >
          Clear
        </Button>
      ) : null}
      {open ? (
        <div className="bg-background absolute top-full left-0 z-20 mt-2 w-full min-w-[16rem] rounded-md border p-2 shadow-lg">
          <EmojiPickerBase
            onEmojiClick={handleEmojiClick}
            theme={Theme.AUTO}
            lazyLoadEmojis
            previewConfig={{ showPreview: false }}
            height={360}
            width="100%"
            skinTonesDisabled
          />
        </div>
      ) : null}
    </div>
  );
};
