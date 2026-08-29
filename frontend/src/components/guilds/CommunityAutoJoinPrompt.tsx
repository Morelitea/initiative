/**
 * What a listed guild is missing when nobody has set up auto-join.
 *
 * A community guild is findable by anyone signed in, but joining it only
 * creates a guild membership — every initiative is still entered one membership
 * row at a time. So a guild that lists itself with no auto-join initiative
 * publishes a front door onto an empty room: the arrival sees a bare sidebar and
 * RLS (correctly) hides everything behind it.
 *
 * The prompt is the fix rather than a pointer to it: the admin picks one of the
 * guild's initiatives and this turns it into the landing place — opened to the
 * guild and flagged for auto-join in a single request, which is also the only
 * pair the server accepts.
 *
 * Guild admins only; its one caller is already admin-gated.
 */

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { InitiativeJoinPolicy } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { useInitiatives, useUpdateInitiative } from "@/hooks/useInitiatives";
import { toast } from "@/lib/chesterToast";

export const CommunityAutoJoinPrompt = () => {
  const { t } = useTranslation(["guilds", "common"]);
  const [choice, setChoice] = useState("");

  // "Does this guild land its arrivals anywhere?" is answered here from the
  // guild's own initiative list rather than the directory, which also carries
  // `auto_join`. The directory lists only `open`/`request` initiatives, and the
  // guild this prompt exists for is typically a fresh one whose single
  // initiative is still private — the very initiative the admin needs to pick.
  // The list is complete for this caller (a guild admin sees every initiative)
  // and answers both halves, the flag and the candidates, in one query.
  const initiativesQuery = useInitiatives();

  const candidates = useMemo(
    () =>
      (initiativesQuery.data ?? [])
        .filter((initiative) => !initiative.is_archived)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [initiativesQuery.data]
  );
  const hasAutoJoin = candidates.some((initiative) => initiative.auto_join);

  const updateInitiative = useUpdateInitiative({
    onSuccess: (initiative) => {
      toast.success(t("guilds:settings.autoJoinPromptDone", { name: initiative.name }));
      setChoice("");
    },
  });

  // Nothing to say until the answer is known, and nothing to say once the guild
  // has somewhere to land people.
  if (initiativesQuery.isLoading || hasAutoJoin) {
    return null;
  }

  const apply = () => {
    const initiativeId = Number(choice);
    if (!initiativeId) return;
    updateInitiative.mutate({
      initiativeId,
      // Both halves together: auto-join is only valid on an open initiative.
      data: { join_policy: InitiativeJoinPolicy.open, auto_join: true },
    });
  };

  return (
    <div className="space-y-3 rounded-md border border-amber-500/50 bg-amber-500/5 p-4">
      <div className="space-y-1">
        <p className="font-medium text-sm">{t("guilds:settings.autoJoinPromptTitle")}</p>
        <p className="text-muted-foreground text-sm">{t("guilds:settings.autoJoinPromptBody")}</p>
      </div>

      {candidates.length > 0 ? (
        <>
          <RadioGroup
            value={choice}
            onValueChange={setChoice}
            aria-label={t("guilds:settings.autoJoinPromptChooseLabel")}
            className="max-h-48 gap-2 overflow-y-auto"
          >
            {candidates.map((initiative) => {
              const id = `auto-join-candidate-${initiative.id}`;
              return (
                <div key={initiative.id} className="flex items-center gap-3">
                  <RadioGroupItem id={id} value={String(initiative.id)} />
                  <Label htmlFor={id} className="min-w-0 truncate font-normal">
                    {initiative.name}
                  </Label>
                </div>
              );
            })}
          </RadioGroup>
          <p className="text-muted-foreground text-xs">
            {t("guilds:settings.autoJoinPromptEffect")}
          </p>
          <Button
            type="button"
            size="sm"
            className="w-full sm:w-auto"
            disabled={!choice || updateInitiative.isPending}
            onClick={apply}
          >
            {t("guilds:settings.autoJoinPromptAction")}
          </Button>
        </>
      ) : null}

      <p className="text-muted-foreground text-xs">
        {t("guilds:settings.autoJoinPromptCreateHint")}
      </p>
    </div>
  );
};
