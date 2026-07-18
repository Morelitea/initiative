import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CounterCreate,
  CounterRead,
  CounterUpdate,
  CounterViewMode,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAddCounter, useUpdateCounter } from "@/hooks/useCounters";
import { pickRandomCounterColor } from "@/lib/counter-color";
import type { DialogProps } from "@/types/dialog";

type CounterFormDialogProps = DialogProps & {
  groupId: number;
  /** Existing counter to edit; if omitted, this is an add dialog. */
  counter?: CounterRead;
  /** Default position for newly added counters (e.g. lastPosition + 1). */
  defaultPosition?: string;
};

export const CounterFormDialog = ({
  open,
  onOpenChange,
  groupId,
  counter,
  defaultPosition,
}: CounterFormDialogProps) => {
  const { t } = useTranslation(["counterGroups", "common"]);
  const isEdit = !!counter;

  const [name, setName] = useState("");
  const [color, setColor] = useState<string>(() => pickRandomCounterColor());
  const [count, setCount] = useState("0");
  const [minValue, setMinValue] = useState("");
  const [maxValue, setMaxValue] = useState("");
  const [step, setStep] = useState("1");
  const [initialCount, setInitialCount] = useState("0");
  const [viewMode, setViewMode] = useState<CounterViewMode>("number");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    if (counter) {
      setName(counter.name);
      setColor(counter.color ?? pickRandomCounterColor());
      setCount(counter.count);
      setMinValue(counter.min ?? "");
      setMaxValue(counter.max ?? "");
      setStep(counter.step);
      setInitialCount(counter.initial_count);
      setViewMode(counter.view_mode);
    } else {
      setName("");
      setColor(pickRandomCounterColor());
      setCount("0");
      setMinValue("");
      setMaxValue("");
      setStep("1");
      setInitialCount("0");
      setViewMode("number");
    }
    setError(null);
  }, [open, counter]);

  const addCounter = useAddCounter(groupId, {
    onSuccess: () => onOpenChange(false),
  });
  const updateCounter = useUpdateCounter(groupId, {
    onSuccess: () => onOpenChange(false),
  });

  const isSubmitting = addCounter.isPending || updateCounter.isPending;
  const hasBounds = minValue.trim() !== "" && maxValue.trim() !== "";
  const requiresBounds = viewMode !== "number";
  const canSubmit =
    !!name.trim() && !isSubmitting && Number(step) > 0 && (!requiresBounds || hasBounds);

  const handleSubmit = () => {
    const trimmedName = name.trim();
    if (!trimmedName) return;
    if (requiresBounds && !hasBounds) {
      setError(t("viewModeRequiresBounds"));
      return;
    }
    setError(null);

    if (isEdit && counter) {
      const update: CounterUpdate = {
        name: trimmedName,
        color,
        step,
        initial_count: initialCount,
        view_mode: viewMode,
        min: minValue.trim() === "" ? null : minValue,
        max: maxValue.trim() === "" ? null : maxValue,
      };
      updateCounter.mutate({ counterId: counter.id, data: update });
    } else {
      const payload: CounterCreate = {
        name: trimmedName,
        color,
        count,
        step,
        initial_count: initialCount,
        view_mode: viewMode,
        position: defaultPosition ?? "0",
      };
      if (minValue.trim() !== "") payload.min = minValue;
      if (maxValue.trim() !== "") payload.max = maxValue;
      addCounter.mutate(payload);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-screen w-full max-w-lg overflow-y-auto rounded-2xl border bg-card shadow-2xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? t("editCounter") : t("addCounter")}</DialogTitle>
          <DialogDescription>{t("counterFormDescription")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="counter-name">{t("name")}</Label>
            <Input
              id="counter-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("counterNamePlaceholder")}
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="counter-color">{t("color")}</Label>
            <ColorPickerPopover id="counter-color" value={color} onChange={setColor} />
          </div>

          {!isEdit && (
            <div className="space-y-2">
              <Label htmlFor="counter-count">{t("count")}</Label>
              <Input
                id="counter-count"
                type="number"
                inputMode="decimal"
                value={count}
                onChange={(e) => setCount(e.target.value)}
              />
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="counter-min">{t("min")}</Label>
              <Input
                id="counter-min"
                type="number"
                inputMode="decimal"
                value={minValue}
                onChange={(e) => setMinValue(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="counter-max">{t("max")}</Label>
              <Input
                id="counter-max"
                type="number"
                inputMode="decimal"
                value={maxValue}
                onChange={(e) => setMaxValue(e.target.value)}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="counter-step">{t("step")}</Label>
              <Input
                id="counter-step"
                type="number"
                inputMode="decimal"
                value={step}
                onChange={(e) => setStep(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="counter-initial">{t("initialCount")}</Label>
              <Input
                id="counter-initial"
                type="number"
                inputMode="decimal"
                value={initialCount}
                onChange={(e) => setInitialCount(e.target.value)}
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="counter-view-mode">{t("viewMode")}</Label>
            <Select value={viewMode} onValueChange={(v) => setViewMode(v as CounterViewMode)}>
              <SelectTrigger id="counter-view-mode">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="number">{t("viewModeNumber")}</SelectItem>
                <SelectItem value="progress_bar" disabled={!hasBounds}>
                  {t("viewModeProgressBar")}
                </SelectItem>
                <SelectItem value="segmented_clock" disabled={!hasBounds}>
                  {t("viewModeSegmentedClock")}
                </SelectItem>
              </SelectContent>
            </Select>
            {requiresBounds && !hasBounds && (
              <p className="text-destructive text-xs">{t("viewModeRequiresBounds")}</p>
            )}
          </div>

          {error && <p className="text-destructive text-sm">{error}</p>}
        </div>

        <DialogFooter>
          <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
            {isSubmitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {isEdit ? t("saving") : t("adding")}
              </>
            ) : isEdit ? (
              t("common:save")
            ) : (
              t("addCounter")
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
