import { useRouter } from "@tanstack/react-router";
import { ChevronLeft, FileText, Loader2, Zap } from "lucide-react";
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
import { useGuilds } from "@/hooks/useGuilds";
import { useInitiativesForGuild } from "@/hooks/useInitiatives";
import { guildPath } from "@/lib/guildUrl";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { getItem, removeItem, setItem } from "@/lib/storage";

// ── Module-level opener (same pattern as CreateTaskWizard) ──────────────────

let openCreateDocumentWizard: (() => void) | null = null;

export function getOpenCreateDocumentWizard() {
  return openCreateDocumentWizard;
}

// ── Storage ─────────────────────────────────────────────────────────────────

const STORAGE_KEY = "initiative-last-doc-initiative";

interface LastUsedInitiative {
  guildId: number;
  guildName: string;
  initiativeId: number;
  initiativeName: string;
}

function loadLastUsed(): LastUsedInitiative | null {
  try {
    const raw = getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as LastUsedInitiative;
    if (parsed.guildId && parsed.initiativeId) return parsed;
    return null;
  } catch {
    return null;
  }
}

function saveLastUsed(data: LastUsedInitiative) {
  setItem(STORAGE_KEY, JSON.stringify(data));
}

/**
 * Clear the stored "last used" initiative if it matches the given id.
 * Call this from error pages (404/403) to prevent stale shortcuts.
 */
export function clearLastUsedInitiative(initiativeId: number) {
  const stored = loadLastUsed();
  if (stored && stored.initiativeId === initiativeId) {
    removeItem(STORAGE_KEY);
  }
}

// ── Component ───────────────────────────────────────────────────────────────

type Step = "select-guild" | "select-initiative";

export const CreateDocumentWizard = () => {
  const { t } = useTranslation("documents");
  const router = useRouter();
  const { guilds } = useGuilds();

  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<Step>("select-guild");
  const [selectedGuildId, setSelectedGuildId] = useState<number | null>(null);
  const [selectedGuildName, setSelectedGuildName] = useState("");
  const [lastUsed, setLastUsed] = useState<LastUsedInitiative | null>(null);

  // Track whether we've already auto-advanced for the current step to avoid loops
  const autoAdvancedRef = useRef<string | null>(null);

  // Register module-level opener
  useEffect(() => {
    openCreateDocumentWizard = () => setOpen(true);
    return () => {
      openCreateDocumentWizard = null;
    };
  }, []);

  // Reset state when dialog closes
  useEffect(() => {
    if (!open) {
      setStep("select-guild");
      setSelectedGuildId(null);
      setSelectedGuildName("");
      autoAdvancedRef.current = null;
    } else {
      setLastUsed(loadLastUsed());
    }
  }, [open]);

  // ── Data fetching ───────────────────────────────────────────────────────

  const initiativesQuery = useInitiativesForGuild(
    step === "select-initiative" ? selectedGuildId : null
  );
  const initiatives = useMemo(() => initiativesQuery.data ?? [], [initiativesQuery.data]);

  // ── Handlers ────────────────────────────────────────────────────────────

  const handleGuildSelect = useCallback((guildId: number, guildName: string) => {
    setSelectedGuildId(guildId);
    setSelectedGuildName(guildName);
    setStep("select-initiative");
  }, []);

  const handoffToDocuments = useCallback(
    (gId: number, gName: string, iId: number, iName: string) => {
      saveLastUsed({
        guildId: gId,
        guildName: gName,
        initiativeId: iId,
        initiativeName: iName,
      });
      setOpen(false);
      // DocumentsPage reads ?create=true&initiativeId=<id> and opens its
      // existing <CreateDocumentDialog> with the initiative pre-selected, so
      // the wizard hands off the rest of the flow without re-mounting the
      // creation UI.
      void router.navigate({
        to: guildPath(gId, "/documents"),
        search: { create: "true", initiativeId: String(iId) },
      });
    },
    [router]
  );

  const handleInitiativeSelect = useCallback(
    (initiativeId: number, initiativeName: string) => {
      handoffToDocuments(selectedGuildId!, selectedGuildName, initiativeId, initiativeName);
    },
    [handoffToDocuments, selectedGuildId, selectedGuildName]
  );

  const handleLastUsedClick = useCallback(() => {
    if (!lastUsed) return;
    handoffToDocuments(
      lastUsed.guildId,
      lastUsed.guildName,
      lastUsed.initiativeId,
      lastUsed.initiativeName
    );
  }, [lastUsed, handoffToDocuments]);

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
  }, [step, guilds, lastUsed, handleGuildSelect]);

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
  }, [step, initiatives, initiativesQuery.isLoading, handleInitiativeSelect]);

  const handleBack = useCallback(() => {
    autoAdvancedRef.current = null;
    if (step === "select-initiative") {
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
                  <p className="font-medium text-sm">{lastUsed.initiativeName}</p>
                  <p className="truncate text-muted-foreground text-xs">{lastUsed.guildName}</p>
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
                  <FileText className="ml-auto h-4 w-4 shrink-0 text-muted-foreground" />
                </button>
              ))
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};
