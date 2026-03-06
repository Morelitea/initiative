import Joyride, { ACTIONS, EVENTS, STATUS } from "react-joyride";
import type { CallBackProps } from "react-joyride";
import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearch } from "@tanstack/react-router";

import { usePmTour } from "@/hooks/usePmTour";
import { useGuilds } from "@/hooks/useGuilds";
import { guildPath } from "@/lib/guildUrl";
import { ChesterTooltip } from "./ChesterTooltip";
import {
  getPmTourSteps,
  PM_INITIATIVE_SETTINGS_STEP_ID,
  PM_MEMBERS_TAB_STEP_ID,
  PM_ROLES_TAB_STEP_ID,
} from "./pmTourSteps";

export const PmTour = () => {
  const { t } = useTranslation("onboarding");
  const { running, completeTour, initialStep } = usePmTour();
  const { activeGuildId } = useGuilds();
  const location = useLocation();
  const navigate = useNavigate();
  const { tab: activeTab } = useSearch({ strict: false }) as { tab?: string };

  const steps = useMemo(() => getPmTourSteps(t), [t]);

  const [stepIndex, setStepIndex] = useState(0);
  const waitingForInitiativeSettings = useRef(false);
  const waitingForMembersTab = useRef(false);
  const waitingForRolesTab = useRef(false);
  const navigatedToGuild = useRef(false);
  const prevTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isGuildRoute = location.pathname.startsWith("/g/");

  // When the tour starts and the user isn't in a guild route,
  // navigate them into the active guild so the sidebar (and
  // initiative-settings target) is visible.
  useEffect(() => {
    if (running && !isGuildRoute && activeGuildId && !navigatedToGuild.current) {
      navigatedToGuild.current = true;
      void navigate({ to: guildPath(activeGuildId, "/") });
    }
  }, [running, isGuildRoute, activeGuildId, navigate]);

  // Clean up pending PREV timer on unmount
  useEffect(() => {
    return () => {
      if (prevTimerRef.current) clearTimeout(prevTimerRef.current);
    };
  }, []);

  // Reset state when tour restarts
  useEffect(() => {
    if (running) {
      setStepIndex(initialStep);
      waitingForInitiativeSettings.current = false;
      waitingForMembersTab.current = false;
      waitingForRolesTab.current = false;
      navigatedToGuild.current = false;
    }
  }, [running, initialStep]);

  // Set waiting flags when we're on steps that wait for navigation
  useEffect(() => {
    if (!running) return;
    const currentStep = steps[stepIndex];
    const stepId = (currentStep?.data as { id?: string })?.id;

    if (stepId === PM_INITIATIVE_SETTINGS_STEP_ID) {
      waitingForInitiativeSettings.current = true;
    }
    if (stepId === PM_MEMBERS_TAB_STEP_ID && activeTab !== "members") {
      waitingForMembersTab.current = true;
    }
    if (stepId === PM_ROLES_TAB_STEP_ID && activeTab !== "roles") {
      waitingForRolesTab.current = true;
    }
  }, [running, stepIndex, steps, activeTab]);

  // Advance when user navigates to initiative settings
  const isInitiativeSettingsRoute = /\/g\/\d+\/initiatives\/\d+\/settings/.test(location.pathname);
  useEffect(() => {
    if (waitingForInitiativeSettings.current && isInitiativeSettingsRoute) {
      waitingForInitiativeSettings.current = false;
      const timer = setTimeout(() => setStepIndex((prev) => prev + 1), 800);
      return () => clearTimeout(timer);
    }
  }, [isInitiativeSettingsRoute]);

  // Advance when user clicks the Members tab
  useEffect(() => {
    if (waitingForMembersTab.current && activeTab === "members") {
      waitingForMembersTab.current = false;
      const timer = setTimeout(() => setStepIndex((prev) => prev + 1), 300);
      return () => clearTimeout(timer);
    }
  }, [activeTab]);

  // Advance when user clicks the Roles tab
  useEffect(() => {
    if (waitingForRolesTab.current && activeTab === "roles") {
      waitingForRolesTab.current = false;
      const timer = setTimeout(() => setStepIndex((prev) => prev + 1), 300);
      return () => clearTimeout(timer);
    }
  }, [activeTab]);

  const handleCallback = useCallback(
    (data: CallBackProps) => {
      const { status, action, type, index, step } = data;

      if (status === STATUS.FINISHED || status === STATUS.SKIPPED) {
        completeTour();
        return;
      }

      // Don't close if the user just clicked the spotlight target —
      // we're waiting for navigation / tab change.
      if (action === ACTIONS.CLOSE && type === EVENTS.STEP_AFTER) {
        const stepId = step.data?.id as string | undefined;
        if (
          stepId === PM_INITIATIVE_SETTINGS_STEP_ID ||
          stepId === PM_MEMBERS_TAB_STEP_ID ||
          stepId === PM_ROLES_TAB_STEP_ID
        ) {
          return;
        }
        completeTour();
        return;
      }

      if (type === EVENTS.STEP_AFTER) {
        const stepId = step.data?.id as string | undefined;

        if (action === ACTIONS.NEXT) {
          // Initiative settings — if user clicked Next without navigating,
          // skip to farewell.
          if (stepId === PM_INITIATIVE_SETTINGS_STEP_ID) {
            if (!isInitiativeSettingsRoute) {
              setStepIndex(steps.length - 1);
              return;
            }
          }

          setStepIndex(index + 1);
        } else if (action === ACTIONS.PREV) {
          let target = Math.max(0, index - 1);

          // Skip "click tab" steps when that tab is already active (going back)
          const skipStep = steps[target];
          const skipId = (skipStep?.data as { id?: string })?.id;
          if (
            (skipId === PM_MEMBERS_TAB_STEP_ID && activeTab === "members") ||
            (skipId === PM_ROLES_TAB_STEP_ID && activeTab === "roles")
          ) {
            target = Math.max(0, target - 1);
          }

          const prevStep = steps[target];
          const sel = typeof prevStep?.target === "string" ? prevStep.target : null;

          // If target is in the DOM, just go back
          if (!sel || sel === "body" || document.querySelector(sel)) {
            setStepIndex(target);
            return;
          }

          // Target not in DOM — switch to the required tab.
          // Clear forward-waiting flags to prevent interference.
          waitingForMembersTab.current = false;
          waitingForRolesTab.current = false;

          // Tab content panels → click the corresponding tab trigger
          const tabTriggerMap: Record<string, string> = {
            '[data-tour="initiative-members-tab"]': '[data-tour="initiative-tab-members"]',
            '[data-tour="initiative-roles-tab"]': '[data-tour="initiative-tab-roles"]',
          };
          const triggerSel = tabTriggerMap[sel];
          if (triggerSel) {
            document.querySelector<HTMLElement>(triggerSel)?.click();
            if (prevTimerRef.current) clearTimeout(prevTimerRef.current);
            prevTimerRef.current = setTimeout(() => setStepIndex(target), 300);
            return;
          }

          // Other targets (e.g., advanced tools on details tab) → switch to details
          document.querySelector<HTMLElement>('[data-tour="initiative-tab-details"]')?.click();
          if (prevTimerRef.current) clearTimeout(prevTimerRef.current);
          prevTimerRef.current = setTimeout(() => setStepIndex(target), 300);
        }
      }
    },
    [completeTour, isInitiativeSettingsRoute, steps, activeTab]
  );

  if (!running) return null;

  return (
    <Joyride
      steps={steps}
      run={running}
      stepIndex={stepIndex}
      continuous
      showSkipButton
      callback={handleCallback}
      tooltipComponent={ChesterTooltip}
      disableOverlayClose
      disableScrolling={false}
      scrollOffset={80}
      spotlightClicks
      styles={{
        options: {
          zIndex: 10000,
          overlayColor: "rgba(0, 0, 0, 0.5)",
        },
      }}
      floaterProps={{
        disableAnimation: true,
      }}
      locale={{
        back: t("back"),
        close: t("finish"),
        last: t("finish"),
        next: t("next"),
        skip: t("skip"),
      }}
    />
  );
};
