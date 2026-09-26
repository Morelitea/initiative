import { Loader2, Zap } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { GuildAvatar } from "@/components/guilds/GuildSidebar";
import { useGuilds } from "@/hooks/useGuilds";
import {
  guildMayAuthorTools,
  guildMayWriteContent,
  useCreatableInitiatives,
} from "@/hooks/useInitiativeAccess";
import { useWizard } from "@/hooks/useWizard";
import { InitiativeColorDot } from "@/lib/initiativeColors";

type Step = "select-guild" | "select-initiative";

export interface Choice {
  id: number;
  name: string;
}

interface Options<Next extends string> {
  /** The wizard's own namespace, which holds its `createWizard.*` strings. */
  ns: "documents" | "tasks";
  open: boolean;
  /**
   * The tool the wizard creates: only communities it could be authored in are
   * offered, and only initiatives that allow it. Null for a wizard that writes
   * into existing content — a task in a project — which a `read_write` grant
   * may do, and where every live initiative is offered.
   */
  authors: Tool | null;
  /** The place last used, offered above the community list. */
  shortcut: { title: string; subtitle: string; onClick: () => void } | null;
  onInitiative: (guild: Choice, initiative: Choice) => void;
  /** The wizard's own step after these two, if it has one. */
  next?: { step: Next; description: string };
  /** Drawn at the end of each initiative's row. */
  initiativeIcon?: ReactNode;
}

/**
 * The first two steps of the global create wizards: a community, then an
 * initiative in it. `dialog` is what the `WizardDialog` takes of them, and
 * `body` is their content — null on the wizard's own step.
 *
 * A step with one answer, and no shortcut beside it, is walked past on its
 * own — once per opening, so Back to it stays there.
 */
export function useGuildInitiativeSteps<Next extends string = never>({
  ns,
  open,
  authors,
  shortcut,
  onInitiative,
  next,
  initiativeIcon,
}: Options<Next>) {
  const { t } = useTranslation(ns);
  const { guilds: allGuilds } = useGuilds();
  const guilds = useMemo(
    () => allGuilds.filter(authors ? guildMayAuthorTools : guildMayWriteContent),
    [allGuilds, authors]
  );

  const { step, go, back, canGoBack, reset } = useWizard<Step | Next>("select-guild");
  const [guild, setGuild] = useState<Choice | null>(null);
  const [initiative, setInitiative] = useState<Choice | null>(null);
  const walkedPast = useRef(new Set<string>());

  useEffect(() => {
    if (!open) {
      reset();
      walkedPast.current.clear();
    }
  }, [open, reset]);

  const { initiatives, isLoading } = useCreatableInitiatives(
    authors,
    step === "select-guild" ? null : (guild?.id ?? null)
  );

  const chooseGuild = useCallback(
    (choice: Choice) => {
      setGuild(choice);
      go("select-initiative");
    },
    [go]
  );

  const nextStep = next?.step;
  const chooseInitiative = useCallback(
    (choice: Choice) => {
      if (!guild) return;
      setInitiative(choice);
      onInitiative(guild, choice);
      if (nextStep) go(nextStep);
    },
    [guild, onInitiative, nextStep, go]
  );

  // Somebody with one community and no shortcut never sees the first step,
  // so it is not one of the steps they walk.
  const skipsGuildStep = guilds.length === 1 && !shortcut;
  useEffect(() => {
    if (!open || walkedPast.current.has(step)) return;
    if (step === "select-guild" && skipsGuildStep) {
      walkedPast.current.add(step);
      chooseGuild(guilds[0]);
    } else if (step === "select-initiative" && !isLoading && initiatives.length === 1) {
      walkedPast.current.add(step);
      chooseInitiative(initiatives[0]);
    }
  }, [open, step, skipsGuildStep, guilds, isLoading, initiatives, chooseGuild, chooseInitiative]);

  const walked: string[] = [
    ...(skipsGuildStep ? [] : ["select-guild"]),
    "select-initiative",
    ...(nextStep ? [nextStep] : []),
  ];
  // The frame before a step is walked past still shows it, and a step outside
  // the count has no position to state.
  const position = walked.indexOf(step);

  const dialog = {
    title: t("createWizard.title"),
    description:
      step === "select-guild"
        ? t("createWizard.selectGuild")
        : step === "select-initiative"
          ? t("createWizard.selectInitiative")
          : next?.description,
    progress:
      position < 0 || walked.length < 2
        ? undefined
        : { current: position + 1, total: walked.length },
    onBack: canGoBack ? back : undefined,
    backLabel: t("createWizard.back"),
  };

  const body =
    step === "select-guild" ? (
      <div className="space-y-2">
        {shortcut && (
          <button
            type="button"
            className="flex w-full items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 p-3 text-left transition-colors hover:bg-primary/10"
            onClick={shortcut.onClick}
          >
            <Zap className="h-5 w-5 shrink-0 text-primary" />
            <div className="min-w-0 flex-1">
              <p className="font-medium text-sm">{shortcut.title}</p>
              <p className="truncate text-muted-foreground text-xs">{shortcut.subtitle}</p>
            </div>
            <span className="text-muted-foreground text-xs">{t("createWizard.lastUsed")}</span>
          </button>
        )}
        {guilds.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className="flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent"
            onClick={() => chooseGuild(entry)}
          >
            <GuildAvatar name={entry.name} icon={entry.icon_url} active={false} size="sm" />
            <span className="font-medium text-sm">{entry.name}</span>
          </button>
        ))}
      </div>
    ) : step === "select-initiative" ? (
      <div className="space-y-2">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : initiatives.length === 0 ? (
          <p className="py-4 text-center text-muted-foreground text-sm">
            {t("createWizard.noInitiatives")}
          </p>
        ) : (
          initiatives.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className="flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent"
              onClick={() => chooseInitiative(entry)}
            >
              <InitiativeColorDot color={entry.color} />
              <span className="font-medium text-sm">{entry.name}</span>
              {initiativeIcon}
            </button>
          ))
        )}
      </div>
    ) : null;

  return { step, guild, initiative, dialog, body };
}
