import type { TooltipRenderProps } from "react-joyride";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { ChesterMimic } from "./ChesterMimic";
import type { ChesterMood } from "./ChesterMimic";
import { SIDEBAR_STEP_ID } from "./tourSteps";

export const ChesterTooltip = ({
  continuous,
  index,
  step,
  size,
  backProps,
  primaryProps,
  skipProps,
  isLastStep,
}: TooltipRenderProps) => {
  const { t } = useTranslation("onboarding");

  const stepData = step.data as { id?: string; mood?: ChesterMood; hideNext?: boolean } | undefined;

  const getMood = (): ChesterMood => {
    // Allow steps to specify their own mood
    if (stepData?.mood) return stepData.mood;
    if (index === 0) return "excited";
    if (isLastStep) return "farewell";
    return "talking";
  };

  return (
    <div className="bg-card border-border w-[360px] max-w-[90vw] rounded-lg border shadow-xl">
      <div className="flex items-start gap-4 p-4">
        <div className="shrink-0">
          <ChesterMimic mood={getMood()} size={64} />
        </div>
        <div className="min-w-0 flex-1">
          {step.title && (
            <h3 className="text-foreground mb-1 text-sm font-semibold">{step.title as string}</h3>
          )}
          <p className="text-muted-foreground text-sm leading-relaxed">{step.content as string}</p>
        </div>
      </div>

      <div className="border-border flex items-center justify-between border-t px-4 py-3">
        <span className="text-muted-foreground text-xs">
          {t("stepCounter", { current: index + 1, total: size })}
        </span>
        <div className="flex items-center gap-2">
          {!isLastStep && (
            <Button variant="ghost" size="sm" {...skipProps}>
              {stepData?.id === SIDEBAR_STEP_ID ? t("exploreSelf") : t("skip")}
            </Button>
          )}
          {index > 0 && (
            <Button variant="outline" size="sm" {...backProps}>
              {t("back")}
            </Button>
          )}
          {continuous && !stepData?.hideNext && (
            <Button size="sm" {...primaryProps}>
              {isLastStep ? t("finish") : t("next")}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};
