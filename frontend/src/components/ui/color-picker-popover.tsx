import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  ColorPicker,
  ColorPickerAlpha,
  ColorPickerEyeDropper,
  ColorPickerFormat,
  ColorPickerHue,
  ColorPickerOutput,
  ColorPickerSelection,
} from "@/components/ui/shadcn-io/color-picker";
import { cn } from "@/lib/utils";

const rgbaToHex = (rgba: number[]) => {
  const clamp = (value: number) => Math.max(0, Math.min(255, Math.round(value)));
  const [r = 0, g = 0, b = 0] = rgba;
  return (
    "#" +
    [clamp(r), clamp(g), clamp(b)]
      .map((channel) => channel.toString(16).padStart(2, "0"))
      .join("")
      .toUpperCase()
  );
};

interface ColorPickerPopoverProps {
  id?: string;
  value: string;
  onChange?: (value: string) => void;
  onChangeComplete?: (value: string) => void;
  disabled?: boolean;
  triggerLabel?: string;
  className?: string;
}

export const ColorPickerPopover = ({
  id,
  value,
  onChange,
  onChangeComplete,
  disabled,
  triggerLabel = "Pick color",
  className,
}: ColorPickerPopoverProps) => {
  const [open, setOpen] = useState(false);
  const [draftColor, setDraftColor] = useState(value);

  useEffect(() => {
    if (!open) {
      setDraftColor(value);
    }
  }, [open, value]);

  const handleColorChange = useCallback(
    (rgba: number[]) => {
      const nextColor = rgbaToHex(rgba);
      setDraftColor(nextColor);
      onChange?.(nextColor);
    },
    [onChange]
  );

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen && draftColor !== value) {
        onChangeComplete?.(draftColor);
      }
      setOpen(nextOpen);
    },
    [draftColor, onChangeComplete, value]
  );

  const swatchStyle = useMemo(() => ({ backgroundColor: draftColor }), [draftColor]);

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          className={cn(
            "h-11 w-full justify-between gap-3 font-mono text-xs tracking-wide uppercase",
            className
          )}
          disabled={disabled}
          aria-label={triggerLabel}
        >
          <span className="flex items-center gap-2">
            <span aria-hidden="true" className="h-6 w-6 rounded-md border" style={swatchStyle} />
            {draftColor}
          </span>
          <span className="text-muted-foreground text-[11px] font-normal uppercase">
            {triggerLabel}
          </span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 space-y-3" align="start">
        <ColorPicker value={draftColor} onChange={handleColorChange}>
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <div className="flex-1 rounded-md border px-3 py-2 font-mono text-xs">
                {draftColor}
              </div>
              <ColorPickerOutput />
              <ColorPickerEyeDropper />
            </div>
            <ColorPickerSelection className="h-48 w-full rounded-md border" />
            <ColorPickerHue />
            <ColorPickerAlpha />
            <ColorPickerFormat className="w-full" />
          </div>
        </ColorPicker>
      </PopoverContent>
    </Popover>
  );
};
