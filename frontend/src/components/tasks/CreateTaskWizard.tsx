import { useRouter } from "@tanstack/react-router";
import { ChevronLeft, ListTodo, Loader2, Search, Zap } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { GuildAvatar } from "@/components/guilds/GuildSidebar";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useGuilds } from "@/hooks/useGuilds";
import { useInitiativesForGuild } from "@/hooks/useInitiatives";
import { useGlobalProjects } from "@/hooks/useProjects";
import { guildPath } from "@/lib/guildUrl";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { getItem, removeItem, setItem } from "@/lib/storage";

// ── Module-level opener (same pattern as CommandCenter) ─────────────────────

let openCreateTaskWizard: (() => void) | null = null;

export function getOpenCreateTaskWizard() {
  return openCreateTaskWizard;
}

// ── Storage ─────────────────────────────────────────────────────────────────

const STORAGE_KEY = "initiative-last-task-project";

interface LastUsedProject {
  guildId: number;
  guildName: string;
  initiativeId: number;
  initiativeName: string;
  projectId: number;
  projectName: string;
}

function loadLastUsed(): LastUsedProject | null {
  try {
    const raw = getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as LastUsedProject;
    if (parsed.guildId && parsed.projectId) return parsed;
    return null;
  } catch {
    return null;
  }
}

function saveLastUsed(data: LastUsedProject) {
  setItem(STORAGE_KEY, JSON.stringify(data));
}

/**
 * Clear the stored "last used" project if it matches the given projectId.
 * Call this from error pages (404/403) to prevent stale shortcuts.
 */
export function clearLastUsedProject(projectId: number) {
  const stored = loadLastUsed();
  if (stored && stored.projectId === projectId) {
    removeItem(STORAGE_KEY);
  }
}

// ── Component ───────────────────────────────────────────────────────────────

type Step = "select-guild" | "select-initiative" | "select-project";

export const CreateTaskWizard = () => {
  const { t } = useTranslation("tasks");
  const router = useRouter();
  const { guilds } = useGuilds();

  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<Step>("select-guild");
  const [selectedGuildId, setSelectedGuildId] = useState<number | null>(null);
  const [selectedGuildName, setSelectedGuildName] = useState("");
  const [selectedInitiativeId, setSelectedInitiativeId] = useState<number | null>(null);
  const [selectedInitiativeName, setSelectedInitiativeName] = useState("");
  const [lastUsed, setLastUsed] = useState<LastUsedProject | null>(null);
  const [projectSearch, setProjectSearch] = useState("");
  const [projectPage, setProjectPage] = useState(1);

  // Track whether we've already auto-advanced for the current step to avoid loops
  const autoAdvancedRef = useRef<string | null>(null);

  // Register module-level opener
  useEffect(() => {
    openCreateTaskWizard = () => setOpen(true);
    return () => {
      openCreateTaskWizard = null;
    };
  }, []);

  // Reset state when dialog closes
  useEffect(() => {
    if (!open) {
      setStep("select-guild");
      setSelectedGuildId(null);
      setSelectedGuildName("");
      setSelectedInitiativeId(null);
      setSelectedInitiativeName("");
      setProjectSearch("");
      setProjectPage(1);
      autoAdvancedRef.current = null;
    } else {
      setLastUsed(loadLastUsed());
    }
  }, [open]);

  // ── Data fetching ───────────────────────────────────────────────────────

  const initiativesQuery = useInitiativesForGuild(
    step === "select-initiative" || step === "select-project" ? selectedGuildId : null
  );
  const initiatives = useMemo(() => initiativesQuery.data ?? [], [initiativesQuery.data]);

  const projectsEnabled = step === "select-project" && !!selectedGuildId;

  // Track a "generation" that increments when filters change, so we can
  // distinguish stale accumulated data from the current filter set.
  const [projectGen, setProjectGen] = useState(0);
  const prevFilterKey = useRef("");
  const filterKey = `${selectedGuildId}-${selectedInitiativeId}-${projectSearch}`;
  if (filterKey !== prevFilterKey.current) {
    prevFilterKey.current = filterKey;
    setProjectGen((g) => g + 1);
    setProjectPage(1);
  }

  const projectsQuery = useGlobalProjects(
    {
      guild_ids: selectedGuildId ? [selectedGuildId] : undefined,
      search: projectSearch || undefined,
      page_size: 25,
      page: projectPage,
    },
    { enabled: projectsEnabled }
  );

  // Accumulate pages, keyed by generation to avoid mixing results across filters
  const [accumulatedProjects, setAccumulatedProjects] = useState<{
    gen: number;
    items: import("@/api/generated/initiativeAPI.schemas").ProjectRead[];
  }>({ gen: 0, items: [] });

  useEffect(() => {
    if (!projectsQuery.data) return;
    const items = projectsQuery.data.items;
    setAccumulatedProjects((prev) =>
      prev.gen !== projectGen
        ? { gen: projectGen, items }
        : { gen: projectGen, items: projectPage === 1 ? items : [...prev.items, ...items] }
    );
  }, [projectsQuery.data, projectPage, projectGen]);

  const filteredProjects = useMemo(
    () =>
      accumulatedProjects.items.filter(
        (p) =>
          p.initiative_id === selectedInitiativeId &&
          !p.is_archived &&
          (p.my_permission_level === "owner" || p.my_permission_level === "write")
      ),
    [accumulatedProjects, selectedInitiativeId]
  );
  const hasMoreProjects = projectsQuery.data?.has_next ?? false;

  // ── Handlers ────────────────────────────────────────────────────────────

  const handleGuildSelect = useCallback((guildId: number, guildName: string) => {
    setSelectedGuildId(guildId);
    setSelectedGuildName(guildName);
    setStep("select-initiative");
  }, []);

  const handleInitiativeSelect = useCallback((initiativeId: number, initiativeName: string) => {
    setSelectedInitiativeId(initiativeId);
    setSelectedInitiativeName(initiativeName);
    setStep("select-project");
  }, []);

  // ── Auto-advance when only 1 option ────────────────────────────────────

  // Auto-advance guild step
  useEffect(() => {
    if (
      open &&
      step === "select-guild" &&
      guilds.length === 1 &&
      !lastUsed &&
      autoAdvancedRef.current !== "guild"
    ) {
      autoAdvancedRef.current = "guild";
      handleGuildSelect(guilds[0].id, guilds[0].name);
    }
  }, [open, step, guilds, lastUsed, handleGuildSelect]);

  // Auto-advance initiative step
  useEffect(() => {
    if (
      open &&
      step === "select-initiative" &&
      !initiativesQuery.isLoading &&
      initiatives.length === 1 &&
      autoAdvancedRef.current !== "initiative"
    ) {
      autoAdvancedRef.current = "initiative";
      handleInitiativeSelect(initiatives[0].id, initiatives[0].name);
    }
  }, [open, step, initiatives, initiativesQuery.isLoading, handleInitiativeSelect]);

  const navigateToProject = useCallback(
    (
      projectId: number,
      projectName: string,
      gId: number,
      gName: string,
      iId: number,
      iName: string
    ) => {
      saveLastUsed({
        guildId: gId,
        guildName: gName,
        initiativeId: iId,
        initiativeName: iName,
        projectId,
        projectName,
      });
      setOpen(false);
      void router.navigate({
        to: guildPath(gId, `/projects/${projectId}`),
        search: { create: "true" },
      });
    },
    [router]
  );

  const handleProjectSelect = useCallback(
    (projectId: number, projectName: string) => {
      navigateToProject(
        projectId,
        projectName,
        selectedGuildId!,
        selectedGuildName,
        selectedInitiativeId!,
        selectedInitiativeName
      );
    },
    [
      navigateToProject,
      selectedGuildId,
      selectedGuildName,
      selectedInitiativeId,
      selectedInitiativeName,
    ]
  );

  const handleLastUsedClick = useCallback(() => {
    if (!lastUsed) return;
    navigateToProject(
      lastUsed.projectId,
      lastUsed.projectName,
      lastUsed.guildId,
      lastUsed.guildName,
      lastUsed.initiativeId,
      lastUsed.initiativeName
    );
  }, [lastUsed, navigateToProject]);

  const handleBack = useCallback(() => {
    autoAdvancedRef.current = null;
    if (step === "select-project") {
      setSelectedInitiativeId(null);
      setSelectedInitiativeName("");
      setProjectSearch("");
      setProjectPage(1);
      setStep("select-initiative");
    } else if (step === "select-initiative") {
      setSelectedGuildId(null);
      setSelectedGuildName("");
      setStep("select-guild");
    }
  }, [step]);

  // ── Render helpers ──────────────────────────────────────────────────────

  const stepTitle = useMemo(() => {
    switch (step) {
      case "select-guild":
        return t("createWizard.selectGuild");
      case "select-initiative":
        return t("createWizard.selectInitiative");
      case "select-project":
        return t("createWizard.selectProject");
    }
  }, [step, t]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("createWizard.title")}</DialogTitle>
          <DialogDescription>{stepTitle}</DialogDescription>
        </DialogHeader>

        {/* Back button */}
        {step !== "select-guild" && (
          <Button variant="ghost" size="sm" className="w-fit" onClick={handleBack}>
            <ChevronLeft className="mr-1 h-4 w-4" />
            {t("createWizard.back")}
          </Button>
        )}

        {/* Step 1: Select Guild */}
        {step === "select-guild" && (
          <div className="space-y-2">
            {/* Last used shortcut */}
            {lastUsed && (
              <button
                type="button"
                className="flex w-full items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 p-3 text-left transition-colors hover:bg-primary/10"
                onClick={handleLastUsedClick}
              >
                <Zap className="h-5 w-5 shrink-0 text-primary" />
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-sm">{lastUsed.projectName}</p>
                  <p className="truncate text-muted-foreground text-xs">
                    {lastUsed.guildName} &gt; {lastUsed.initiativeName}
                  </p>
                </div>
                <span className="text-muted-foreground text-xs">{t("createWizard.lastUsed")}</span>
              </button>
            )}

            {/* Guild list */}
            {guilds.map((guild) => (
              <button
                key={guild.id}
                type="button"
                className="flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent"
                onClick={() => handleGuildSelect(guild.id, guild.name)}
              >
                <GuildAvatar name={guild.name} icon={guild.icon_base64} active={false} size="sm" />
                <span className="font-medium text-sm">{guild.name}</span>
              </button>
            ))}
          </div>
        )}

        {/* Step 2: Select Initiative */}
        {step === "select-initiative" && (
          <div className="space-y-2">
            {initiativesQuery.isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : initiatives.length === 0 ? (
              <p className="py-4 text-center text-muted-foreground text-sm">
                {t("createWizard.noInitiatives")}
              </p>
            ) : (
              initiatives.map((initiative) => (
                <button
                  key={initiative.id}
                  type="button"
                  className="flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent"
                  onClick={() => handleInitiativeSelect(initiative.id, initiative.name)}
                >
                  <InitiativeColorDot color={initiative.color} />
                  <span className="font-medium text-sm">{initiative.name}</span>
                </button>
              ))
            )}
          </div>
        )}

        {/* Step 3: Select Project */}
        {step === "select-project" && (
          <div className="space-y-2">
            <div className="relative">
              <Search className="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={projectSearch}
                onChange={(e) => setProjectSearch(e.target.value)}
                placeholder={t("createWizard.searchProjects")}
                className="pl-9"
                autoFocus
              />
            </div>
            {projectsQuery.isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : filteredProjects.length === 0 && !hasMoreProjects ? (
              <p className="py-4 text-center text-muted-foreground text-sm">
                {t("createWizard.noProjects")}
              </p>
            ) : (
              <>
                {filteredProjects.map((project) => (
                  <button
                    key={project.id}
                    type="button"
                    className="flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent"
                    onClick={() => handleProjectSelect(project.id, project.name)}
                  >
                    <ListTodo className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="font-medium text-sm">{project.name}</span>
                  </button>
                ))}
                {hasMoreProjects && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="w-full"
                    onClick={() => setProjectPage((p) => p + 1)}
                    disabled={projectsQuery.isFetching}
                  >
                    {projectsQuery.isFetching ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : null}
                    {t("createWizard.loadMore")}
                  </Button>
                )}
              </>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};
