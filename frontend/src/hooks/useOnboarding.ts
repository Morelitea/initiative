import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { useUpdateCurrentUser } from "@/hooks/useUsers";
import { useInterfaceSettings } from "@/hooks/useSettings";
import { setTourRestartCallback } from "@/components/onboarding/onboardingState";

export function useOnboarding() {
  const { user } = useAuth();
  const { guilds, loading: guildsLoading } = useGuilds();
  const [running, setRunning] = useState(false);
  // Prevent the tour from restarting after completion (before the user object refreshes)
  const completedRef = useRef(false);

  const { data: interfaceSettings } = useInterfaceSettings();
  const tourGloballyEnabled = interfaceSettings?.onboarding_tour_enabled ?? true;

  const shouldStart =
    !!user &&
    !user.onboarding_completed &&
    !completedRef.current &&
    !guildsLoading &&
    guilds.length > 0 &&
    tourGloballyEnabled;

  useEffect(() => {
    if (shouldStart && !running) {
      setRunning(true);
    }
  }, [shouldStart, running]);

  const updateUser = useUpdateCurrentUser();

  const completeTour = useCallback(() => {
    completedRef.current = true;
    setRunning(false);
    updateUser.mutate({ onboarding_completed: true });
  }, [updateUser]);

  const restartTour = useCallback(() => {
    completedRef.current = false;
    setRunning(true);
  }, []);

  // Register the restart callback so settings page can trigger it
  useEffect(() => {
    setTourRestartCallback(restartTour);
    return () => setTourRestartCallback(null);
  }, [restartTour]);

  return { running, completeTour, restartTour };
}
