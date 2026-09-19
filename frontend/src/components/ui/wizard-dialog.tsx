/**
 * The chrome a multi-step dialog shares: the frame, the heading, where you are
 * and the way back.
 *
 * It holds no strings and no opinion about size. Both are deliberate. The
 * dialogs that use this disagree about width and scrolling — a two-question
 * picker and a four-question form are not the same shape — so `className` goes
 * straight through. And the back label stays the caller's, because each of
 * these already has its own key for it and the translations do not all agree;
 * a default here would quietly reword five dialogs.
 *
 * Pair it with {@link useWizard}, which owns which step is showing.
 */

import { ChevronLeft } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export interface WizardBackButtonProps
  extends Omit<ComponentProps<typeof Button>, "children" | "variant" | "size" | "type"> {
  /** What the button says. The caller's, not ours — see the note above. */
  label: string;
}

/**
 * Exported on its own because one wizard puts Back in a footer opposite its
 * forward button rather than above the body, and that layout is its own
 * decision to make.
 */
export const WizardBackButton = ({ label, ...props }: WizardBackButtonProps) => (
  <Button type="button" variant="ghost" size="sm" {...props}>
    <ChevronLeft className="h-4 w-4" />
    {label}
  </Button>
);

export interface WizardProgress {
  /** 1-based. */
  current: number;
  total: number;
}

/**
 * How far along, as dots plus a line of text only a screen reader gets.
 *
 * The dots are marked decorative: you cannot jump to a step by clicking one,
 * so there is nothing here to tab to or to announce as a control. The position
 * is carried by the text beside them, which is live — a dialog that swaps its
 * description as you move otherwise tells you nothing about having moved.
 */
const WizardProgressDots = ({ current, total }: WizardProgress) => {
  const { t } = useTranslation("common");
  return (
    <div className="flex items-center gap-2">
      <div className="flex items-center gap-1.5" aria-hidden="true">
        {Array.from({ length: total }, (_, index) => (
          <span
            key={index}
            className={cn(
              "h-1.5 rounded-full transition-all",
              index + 1 === current ? "w-4 bg-primary" : "w-1.5 bg-muted-foreground/30"
            )}
          />
        ))}
      </div>
      <span aria-live="polite" className="sr-only">
        {t("stepOf", { current, total })}
      </span>
    </div>
  );
};

export interface WizardDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  /** The per-step orientation line. Falsy renders no description at all. */
  description?: ReactNode;
  /** Omit where there is no position worth stating — one step, or a step
   *  arrived at and not left. */
  progress?: WizardProgress;
  /** Omit to render no back row: a first step, a step with no way out, or a
   *  wizard that draws Back somewhere else. */
  onBack?: () => void;
  backLabel?: string;
  backDisabled?: boolean;
  /** Straight onto `DialogContent`. */
  className?: string;
  children: ReactNode;
}

export const WizardDialog = ({
  open,
  onOpenChange,
  title,
  description,
  progress,
  onBack,
  backLabel,
  backDisabled,
  className,
  children,
}: WizardDialogProps) => (
  <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className={className}>
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        {description ? <DialogDescription>{description}</DialogDescription> : null}
      </DialogHeader>
      {progress ? <WizardProgressDots {...progress} /> : null}
      {onBack ? (
        <WizardBackButton
          className="w-fit"
          onClick={onBack}
          disabled={backDisabled}
          label={backLabel ?? ""}
        />
      ) : null}
      {children}
    </DialogContent>
  </Dialog>
);
