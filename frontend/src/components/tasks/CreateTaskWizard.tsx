import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { ChevronLeft, ListTodo, Loader2, Search, Zap } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { GuildAvatar } from "@/components/guilds/GuildSidebar";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { guildPath } from "@/lib/guildUrl";
import { getItem, setItem } from "@/lib/storage";
import { useGuilds } from "@/hooks/useGuilds";
import { useInitiativesForGuild } from "@/hooks/useInitiatives";
import { useGlobalProjects } from "@/hooks/useProjects";

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
  const initiatives = initiativesQuery.data ?? [];

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

  // ── Auto-advance when only 1 option ────────────────────────────────────

  // Auto-advance guild step
  useEffect(() => {
    if (
      step === "select-guild" &&
      guilds.length === 1 &&
      !lastUsed &&
      autoAdvancedRef.current !== "guild"
    ) {
      autoAdvancedRef.current = "guild";
      handleGuildSelect(guilds[0].id, guilds[0].name);
    }
  }, [step, guilds, lastUsed, handleGuildSelect]); // stable callback, safe to include

  // Auto-advance initiative step
  useEffect(() => {
    if (
      step === "select-initiative" &&
      !initiativesQuery.isLoading &&
      initiatives.length === 1 &&
      autoAdvancedRef.current !== "initiative"
    ) {
      autoAdvancedRef.current = "initiative";
      handleInitiativeSelect(initiatives[0].id, initiatives[0].name);
    }
  }, [step, initiatives, initiativesQuery.isLoading]); // eslint-disable-line react-hooks/exhaustive-deps

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
                className="border-primary/30 bg-primary/5 hover:bg-primary/10 flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors"
                onClick={handleLastUsedClick}
              >
                <Zap className="text-primary h-5 w-5 shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{lastUsed.projectName}</p>
                  <p className="text-muted-foreground truncate text-xs">
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
                className="hover:bg-accent flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors"
                onClick={() => handleGuildSelect(guild.id, guild.name)}
              >
                <GuildAvatar name={guild.name} icon={guild.icon_base64} active={false} size="sm" />
                <span className="text-sm font-medium">{guild.name}</span>
              </button>
            ))}
          </div>
        )}

        {/* Step 2: Select Initiative */}
        {step === "select-initiative" && (
          <div className="space-y-2">
            {initiativesQuery.isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="text-muted-foreground h-6 w-6 animate-spin" />
              </div>
            ) : initiatives.length === 0 ? (
              <p className="text-muted-foreground py-4 text-center text-sm">
                {t("createWizard.noInitiatives")}
              </p>
            ) : (
              initiatives.map((initiative) => (
                <button
                  key={initiative.id}
                  type="button"
                  className="hover:bg-accent flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors"
                  onClick={() => handleInitiativeSelect(initiative.id, initiative.name)}
                >
                  <InitiativeColorDot color={initiative.color} />
                  <span className="text-sm font-medium">{initiative.name}</span>
                </button>
              ))
            )}
          </div>
        )}

        {/* Step 3: Select Project */}
        {step === "select-project" && (
          <div className="space-y-2">
            <div className="relative">
              <Search className="text-muted-foreground absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2" />
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
                <Loader2 className="text-muted-foreground h-6 w-6 animate-spin" />
              </div>
            ) : filteredProjects.length === 0 && !hasMoreProjects ? (
              <p className="text-muted-foreground py-4 text-center text-sm">
                {t("createWizard.noProjects")}
              </p>
            ) : (
              <>
                {filteredProjects.map((project) => (
                  <button
                    key={project.id}
                    type="button"
                    className="hover:bg-accent flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors"
                    onClick={() => handleProjectSelect(project.id, project.name)}
                  >
                    <ListTodo className="text-muted-foreground h-4 w-4 shrink-0" />
                    <span className="text-sm font-medium">{project.name}</span>
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
