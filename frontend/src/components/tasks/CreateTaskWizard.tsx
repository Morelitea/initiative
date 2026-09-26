import { useRouter } from "@tanstack/react-router";
import { ListTodo, Loader2, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { type ProjectRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { WizardDialog } from "@/components/ui/wizard-dialog";
import { useGuildInitiativeSteps } from "@/hooks/useGuildInitiativeSteps";
import { useGlobalProjects } from "@/hooks/useProjects";
import { guildPath } from "@/lib/guildUrl";
import { getItem, removeItem, setItem } from "@/lib/storage";
import { toolDetailRoute } from "@/lib/tools";

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

export const CreateTaskWizard = () => {
  const { t } = useTranslation("tasks");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const lastUsed = useMemo(() => (open ? loadLastUsed() : null), [open]);
  const [projectSearch, setProjectSearch] = useState("");
  const [projectPage, setProjectPage] = useState(1);

  // Register module-level opener
  useEffect(() => {
    openCreateTaskWizard = () => setOpen(true);
    return () => {
      openCreateTaskWizard = null;
    };
  }, []);

  const navigateToProject = useCallback(
    (target: LastUsedProject) => {
      setItem(STORAGE_KEY, JSON.stringify(target));
      setOpen(false);
      void router.navigate({
        to: guildPath(
          target.guildId,
          toolDetailRoute(Tool.project, target.initiativeId, target.projectId)
        ),
        search: { create: "true" },
      });
    },
    [router]
  );

  // Each walk into the project step starts from an empty search.
  const startProjectStep = useCallback(() => {
    setProjectSearch("");
    setProjectPage(1);
  }, []);

  // A task is child content of a project, so the guild and initiative steps
  // offer wherever content can be written; the project step then applies the
  // precise per-project check.
  const steps = useGuildInitiativeSteps({
    ns: "tasks",
    open,
    authors: null,
    shortcut: lastUsed && {
      title: lastUsed.projectName,
      subtitle: `${lastUsed.guildName} > ${lastUsed.initiativeName}`,
      onClick: () => navigateToProject(lastUsed),
    },
    onInitiative: startProjectStep,
    next: { step: "select-project", description: t("createWizard.selectProject") },
  });
  const { guild, initiative } = steps;

  // ── Data fetching ───────────────────────────────────────────────────────

  const projectsEnabled = steps.step === "select-project" && !!guild;

  // Track a "generation" that increments when filters change, so we can
  // distinguish stale accumulated data from the current filter set.
  const [projectGen, setProjectGen] = useState(0);
  const prevFilterKey = useRef("");
  const filterKey = `${guild?.id}-${initiative?.id}-${projectSearch}`;
  if (filterKey !== prevFilterKey.current) {
    prevFilterKey.current = filterKey;
    setProjectGen((g) => g + 1);
    setProjectPage(1);
  }

  const projectsQuery = useGlobalProjects(
    {
      guild_ids: guild ? [guild.id] : undefined,
      search: projectSearch || undefined,
      page_size: 25,
      page: projectPage,
    },
    { enabled: projectsEnabled }
  );

  // Accumulate pages, keyed by generation to avoid mixing results across filters
  const [accumulatedProjects, setAccumulatedProjects] = useState<{
    gen: number;
    items: ProjectRead[];
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
        (p) => p.initiative_id === initiative?.id && p.archived_at === null && p.can.edit
      ),
    [accumulatedProjects, initiative]
  );
  const hasMoreProjects = projectsQuery.data?.has_next ?? false;

  return (
    <WizardDialog open={open} onOpenChange={setOpen} className="sm:max-w-md" {...steps.dialog}>
      {steps.body}

      {steps.step === "select-project" && guild && initiative && (
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
                  onClick={() =>
                    navigateToProject({
                      guildId: guild.id,
                      guildName: guild.name,
                      initiativeId: initiative.id,
                      initiativeName: initiative.name,
                      projectId: project.id,
                      projectName: project.name,
                    })
                  }
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
                  {projectsQuery.isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  {t("createWizard.loadMore")}
                </Button>
              )}
            </>
          )}
        </div>
      )}
    </WizardDialog>
  );
};
