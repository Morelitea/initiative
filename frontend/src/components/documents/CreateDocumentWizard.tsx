import { useRouter } from "@tanstack/react-router";
import { FileText } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { WizardDialog } from "@/components/ui/wizard-dialog";
import { type Choice, useGuildInitiativeSteps } from "@/hooks/useGuildInitiativeSteps";
import { guildPath } from "@/lib/guildUrl";
import { getItem, setItem } from "@/lib/storage";
import { toolListRoute } from "@/lib/tools";

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

// ── Component ───────────────────────────────────────────────────────────────

export const CreateDocumentWizard = () => {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const lastUsed = useMemo(() => (open ? loadLastUsed() : null), [open]);

  // Register module-level opener
  useEffect(() => {
    openCreateDocumentWizard = () => setOpen(true);
    return () => {
      openCreateDocumentWizard = null;
    };
  }, []);

  const handoff = useCallback(
    (guild: Choice, initiative: Choice) => {
      setItem(
        STORAGE_KEY,
        JSON.stringify({
          guildId: guild.id,
          guildName: guild.name,
          initiativeId: initiative.id,
          initiativeName: initiative.name,
        } satisfies LastUsedInitiative)
      );
      setOpen(false);
      // The initiative's documents tab reads ?create=true and opens its
      // existing <CreateDocumentDialog>, so the wizard hands off the rest of
      // the flow without re-mounting the creation UI. The initiative is in the
      // path now rather than a search param.
      void router.navigate({
        to: guildPath(guild.id, toolListRoute(Tool.document, initiative.id)),
        search: { create: "true" },
      });
    },
    [router]
  );

  const steps = useGuildInitiativeSteps({
    ns: "documents",
    open,
    authors: Tool.document,
    shortcut: lastUsed && {
      title: lastUsed.initiativeName,
      subtitle: lastUsed.guildName,
      onClick: () =>
        handoff(
          { id: lastUsed.guildId, name: lastUsed.guildName },
          { id: lastUsed.initiativeId, name: lastUsed.initiativeName }
        ),
    },
    onInitiative: handoff,
    initiativeIcon: <FileText className="ml-auto h-4 w-4 shrink-0 text-muted-foreground" />,
  });

  return (
    <WizardDialog open={open} onOpenChange={setOpen} className="sm:max-w-md" {...steps.dialog}>
      {steps.body}
    </WizardDialog>
  );
};
