import Joyride, { ACTIONS, EVENTS, STATUS } from "react-joyride";
import type { CallBackProps } from "react-joyride";
import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "@tanstack/react-router";

import { useOnboarding } from "@/hooks/useOnboarding";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { useInitiatives } from "@/hooks/useInitiatives";
import { ChesterTooltip } from "./ChesterTooltip";
import {
  getTourSteps,
  GUILD_LIST_STEP_ID,
  GUILD_SETTINGS_STEP_ID,
  PM_HANDOFF_STEP_ID,
  PLATFORM_SETTINGS_STEP_ID,
  TASKS_STEP_ID,
} from "./tourSteps";
import { triggerPmTourStart } from "./pmTourState";
import { PM_TOUR_SETTINGS_START_INDEX } from "./pmTourSteps";
import { guildPath } from "@/lib/guildUrl";
import type { TourVariant } from "./tourSteps";

export const OnboardingTour = () => {
  const { t } = useTranslation("onboarding");
  const { running, completeTour } = useOnboarding();
  const { user } = useAuth();
  const { activeGuild } = useGuilds();
  const location = useLocation();
  const navigate = useNavigate();

  const isGuildRoute = location.pathname.startsWith("/g/");
  const { data: initiatives } = useInitiatives({ enabled: isGuildRoute });

  const variant: TourVariant =
    user?.role === "admin"
      ? "superadmin"
      : activeGuild?.role === "admin"
        ? "guild_admin"
        : "new_user";
  const isGuildAdmin = activeGuild?.role === "admin";
  const isProjectManager = useMemo(() => {
    if (!activeGuild?.id || !initiatives || !user?.initiative_roles) return false;
    const guildInitiativeIds = new Set(
      initiatives.filter((i) => i.guild_id === activeGuild.id).map((i) => i.id)
    );
    return user.initiative_roles.some(
      (r) => r.role === "project_manager" && guildInitiativeIds.has(r.initiative_id)
    );
  }, [activeGuild?.id, initiatives, user?.initiative_roles]);
  const steps = useMemo(
    () => getTourSteps(t, variant, isGuildAdmin, isProjectManager),
    [t, variant, isGuildAdmin, isProjectManager]
  );

  const [stepIndex, setStepIndex] = useState(0);
  const waitingForGuild = useRef(false);
  const waitingForGuildSettings = useRef(false);
  const waitingForAdminSettings = useRef(false);
  const waitingForProject = useRef(false);
  const waitingForPmHandoff = useRef(false);
  const waitingForBackNav = useRef<number | null>(null);

  // Keep completeTour in a ref so the PM-handoff effect doesn't re-run
  // (and cancel its setTimeout) when completeTour's reference changes.
  const completeTourRef = useRef(completeTour);
  useEffect(() => {
    completeTourRef.current = completeTour;
  }, [completeTour]);

  // Reset state when tour restarts
  useEffect(() => {
    if (running) {
      setStepIndex(0);
      waitingForGuild.current = false;
      waitingForGuildSettings.current = false;
      waitingForAdminSettings.current = false;
      waitingForProject.current = false;
      waitingForPmHandoff.current = false;
      waitingForBackNav.current = null;
    }
  }, [running]);

  // Auto-advance when the user navigates into a guild
  useEffect(() => {
    if (waitingForGuild.current && isGuildRoute) {
      waitingForGuild.current = false;
      const timer = setTimeout(() => setStepIndex((prev) => prev + 1), 800);
      return () => clearTimeout(timer);
    }
  }, [isGuildRoute]);

  // Set waiting flags when we're on optional detour steps
  const isGuildSettingsRoute = /\/g\/\d+\/settings/.test(location.pathname);
  useEffect(() => {
    if (!running) return;
    const currentStep = steps[stepIndex];
    const stepId = (currentStep?.data as { id?: string })?.id;
    if (stepId === GUILD_LIST_STEP_ID) {
      waitingForGuild.current = true;
    }
    if (stepId === GUILD_SETTINGS_STEP_ID) {
      waitingForGuildSettings.current = true;
    }
    if (stepId === PLATFORM_SETTINGS_STEP_ID) {
      waitingForAdminSettings.current = true;
    }
    if (stepId === TASKS_STEP_ID) {
      waitingForProject.current = true;
    }
    if (stepId === PM_HANDOFF_STEP_ID) {
      waitingForPmHandoff.current = true;
    }
  }, [running, stepIndex, steps]);

  // Advance when the user navigates to guild settings (clicked the icon)
  useEffect(() => {
    if (waitingForGuildSettings.current && isGuildSettingsRoute) {
      waitingForGuildSettings.current = false;
      const timer = setTimeout(() => setStepIndex((prev) => prev + 1), 800);
      return () => clearTimeout(timer);
    }
  }, [isGuildSettingsRoute]);

  // Advance when the user navigates to /settings/admin
  const isAdminSettingsRoute = location.pathname.startsWith("/settings/admin");
  useEffect(() => {
    if (waitingForAdminSettings.current && isAdminSettingsRoute) {
      waitingForAdminSettings.current = false;
      const timer = setTimeout(() => setStepIndex((prev) => prev + 1), 800);
      return () => clearTimeout(timer);
    }
  }, [isAdminSettingsRoute]);

  // When PM clicks the initiative settings icon during handoff, complete
  // the main tour and start the standalone PM tour after a short delay.
  // Uses completeTourRef to avoid re-running (and cancelling the timeout)
  // when the completeTour callback reference changes after the state update.
  const isInitiativeSettingsRoute = /\/g\/\d+\/initiatives\/\d+\/settings/.test(location.pathname);
  useEffect(() => {
    if (waitingForPmHandoff.current && isInitiativeSettingsRoute) {
      waitingForPmHandoff.current = false;
      completeTourRef.current();
      // No cleanup — the timer must survive component unmount (completeTour
      // sets running=false which unmounts OnboardingTour).
      setTimeout(() => triggerPmTourStart(PM_TOUR_SETTINGS_START_INDEX), 800);
    }
  }, [isInitiativeSettingsRoute]);

  // Advance when the user clicks a project from the initiatives section
  const isProjectRoute = /\/g\/\d+\/projects\/\d+/.test(location.pathname);
  useEffect(() => {
    if (waitingForProject.current && isProjectRoute) {
      waitingForProject.current = false;
      const timer = setTimeout(() => setStepIndex((prev) => prev + 1), 800);
      return () => clearTimeout(timer);
    }
  }, [isProjectRoute]);

  // Complete back-navigation: after navigate() changes the route,
  // wait for lazy-loaded content then jump to the target step.
  useEffect(() => {
    if (waitingForBackNav.current !== null) {
      const targetIndex = waitingForBackNav.current;
      waitingForBackNav.current = null;
      const timer = setTimeout(() => setStepIndex(targetIndex), 800);
      return () => clearTimeout(timer);
    }
  }, [location.pathname]);

  const handleCallback = useCallback(
    (data: CallBackProps) => {
      const { status, action, type, index, step } = data;

      if (status === STATUS.FINISHED || status === STATUS.SKIPPED) {
        completeTour();
        return;
      }

      if (action === ACTIONS.CLOSE && type === EVENTS.STEP_AFTER) {
        const stepId = step.data?.id as string | undefined;
        // Don't close if the user just clicked the spotlight target
        // on a step that waits for navigation.
        if (
          stepId === GUILD_LIST_STEP_ID ||
          stepId === TASKS_STEP_ID ||
          stepId === GUILD_SETTINGS_STEP_ID ||
          stepId === PLATFORM_SETTINGS_STEP_ID ||
          stepId === PM_HANDOFF_STEP_ID
        ) {
          return;
        }
        completeTour();
        return;
      }

      if (type === EVENTS.STEP_AFTER) {
        const stepId = step.data?.id as string | undefined;

        if (action === ACTIONS.NEXT) {
          // Guild settings — if user clicked Next without navigating,
          // skip the overview step. If they're already on guild settings
          // (clicked the link), advance normally to the overview.
          if (stepId === GUILD_SETTINGS_STEP_ID) {
            if (!isGuildSettingsRoute) {
              setStepIndex(index + 2);
              return;
            }
          }

          // Guild-list — wait for the user to click a guild
          if (stepId === GUILD_LIST_STEP_ID && !isGuildRoute) {
            waitingForGuild.current = true;
            return;
          }

          // Tasks/initiatives — wait for the user to click a project
          if (stepId === TASKS_STEP_ID && !isProjectRoute) {
            waitingForProject.current = true;
            return;
          }

          // Platform Settings — wait for /settings/admin navigation
          if (stepId === PLATFORM_SETTINGS_STEP_ID) {
            if (!isAdminSettingsRoute) {
              waitingForAdminSettings.current = true;
              return;
            }
          }

          setStepIndex(index + 1);
        } else if (action === ACTIONS.PREV) {
          const target = Math.max(0, index - 1);
          const prevStep = steps[target];
          const sel = typeof prevStep?.target === "string" ? prevStep.target : null;

          // If the previous step's target is in the DOM, just go back
          if (!sel || sel === "body" || document.querySelector(sel)) {
            setStepIndex(target);
            return;
          }

          // Target not in DOM — navigate back to the route where it lives.
          // Clear forward-waiting flags so they don't interfere.
          waitingForGuild.current = false;
          waitingForGuildSettings.current = false;
          waitingForAdminSettings.current = false;
          waitingForProject.current = false;
          waitingForPmHandoff.current = false;
          waitingForBackNav.current = target;

          if ((isProjectRoute || isGuildSettingsRoute) && activeGuild) {
            // Back from project or guild-settings → guild landing
            void navigate({ to: guildPath(activeGuild.id, "/") });
          } else {
            // Back from guild or admin-settings → home
            void navigate({ to: "/" });
          }
        }
      }
    },
    [
      completeTour,
      isGuildRoute,
      isGuildSettingsRoute,
      isAdminSettingsRoute,
      isProjectRoute,
      activeGuild,
      navigate,
      steps,
    ]
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
