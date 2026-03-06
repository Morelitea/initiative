import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "@tanstack/react-router";

import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useUpdateCurrentUser } from "@/hooks/useUsers";
import { useInterfaceSettings } from "@/hooks/useSettings";
import { setPmTourStartCallback } from "@/components/onboarding/pmTourState";

export function usePmTour() {
  const { user } = useAuth();
  const { guilds, activeGuildId, loading: guildsLoading } = useGuilds();
  const [running, setRunning] = useState(false);
  const completedRef = useRef(false);

  const { data: interfaceSettings } = useInterfaceSettings();
  const tourGloballyEnabled = interfaceSettings?.onboarding_tour_enabled ?? true;

  const location = useLocation();
  const isGuildRoute = location.pathname.startsWith("/g/");

  // Fetch guild-scoped initiatives to check PM status in the active guild
  const { data: initiatives } = useInitiatives({ enabled: isGuildRoute });

  const isProjectManager = useMemo(() => {
    if (!activeGuildId || !initiatives || !user?.initiative_roles) return false;
    const guildInitiativeIds = new Set(
      initiatives.filter((i) => i.guild_id === activeGuildId).map((i) => i.id)
    );
    return user.initiative_roles.some(
      (r) => r.role === "project_manager" && guildInitiativeIds.has(r.initiative_id)
    );
  }, [activeGuildId, initiatives, user?.initiative_roles]);

  const shouldAutoStart =
    !!user &&
    !user.pm_tour_completed &&
    !!user.onboarding_completed &&
    isProjectManager &&
    isGuildRoute &&
    !completedRef.current &&
    !guildsLoading &&
    guilds.length > 0 &&
    tourGloballyEnabled;

  useEffect(() => {
    if (shouldAutoStart && !running) {
      setRunning(true);
    }
  }, [shouldAutoStart, running]);

  const updateUser = useUpdateCurrentUser();

  const completeTour = useCallback(() => {
    completedRef.current = true;
    setRunning(false);
    updateUser.mutate({ pm_tour_completed: true });
  }, [updateUser]);

  const [initialStep, setInitialStep] = useState(0);

  const startTour = useCallback((startStep?: number) => {
    completedRef.current = false;
    setInitialStep(startStep ?? 0);
    setRunning(true);
  }, []);

  // Register the start callback so the main tour can trigger it
  useEffect(() => {
    setPmTourStartCallback(startTour);
    return () => setPmTourStartCallback(null);
  }, [startTour]);

  return { running, completeTour, startTour, isProjectManager, initialStep };
}
