/**
 * Where an app's initiative surfaces appear.
 *
 * An app that offers a surface inside an initiative offers it in every one of
 * them unless the guild says otherwise. This is where a guild admin says
 * otherwise — placement rather than permission, so it reads the same for
 * everyone afterwards, including the admin who set it.
 *
 * Absent for an app with no initiative surface to place: there would be nothing
 * for the choice to move.
 */

import { Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { GuildAppDetail } from "@/api/appConnections";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { useUpdateGuildApp } from "@/hooks/useGuildApps";
import { useInitiatives } from "@/hooks/useInitiatives";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

export interface AppPlacementPanelProps {
  app: GuildAppDetail;
}

/** The chosen initiatives, or null when the app is placed in all of them. */
const chosenIds = (placement: Record<string, unknown> | null | undefined): number[] | null => {
  const chosen = placement?.initiatives;
  return Array.isArray(chosen) ? chosen.filter((id): id is number => typeof id === "number") : null;
};

export function AppPlacementPanel({ app }: AppPlacementPanelProps) {
  const { t } = useTranslation(["apps", "common"]);
  const initiatives = useInitiatives();
  const update = useUpdateGuildApp(app.id);
  // What the admin is choosing right now. Seeded from the app and kept locally
  // so ticking several initiatives is one decision, saved per change.
  const [chosen, setChosen] = useState<number[] | null>(() => chosenIds(app.placement));
  // The last selection the server took, so a failed save falls back to
  // something true rather than to whatever the cache happens to hold.
  const settled = useRef(chosen);
  // Each save replaces the whole selection, so two in flight could land in
  // either order and leave the older one stored. Chained rather than
  // concurrent: the server sees the ticks in the order they were made.
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  // How many are still to settle. The panel is reconciled when the last one
  // does, rather than by each in turn — a save that failed behind a save that
  // worked would otherwise roll the panel back past a choice the server kept.
  const outstanding = useRef(0);

  const save = (next: number[] | null) => {
    setChosen(next);
    outstanding.current += 1;
    queue.current = queue.current
      .catch(() => undefined)
      .then(async () => {
        // Only initiatives still on the roster are sent. An initiative deleted
        // after it was chosen leaves an id nothing on screen shows, and
        // resubmitting it would fail every later edit for a reason the admin
        // cannot see.
        const live =
          next === null || !initiatives.data
            ? next
            : next.filter((id) => initiatives.data?.some((one) => one.id === id));
        await update.mutateAsync({
          placement: live === null ? {} : { initiatives: live },
        });
        settled.current = live;
      })
      .catch((error) => {
        toast.error(getErrorMessage(error, "apps:error"));
      })
      .finally(() => {
        outstanding.current -= 1;
        // Nothing else is coming, so the panel now shows what the server took:
        // the newest choice when every save landed, and the last one it
        // accepted when any did not. Either way the next edit builds on what
        // is actually stored.
        if (outstanding.current === 0) setChosen(settled.current);
      });
  };

  const toggle = (id: number, on: boolean) => {
    const current = chosen ?? [];
    save(on ? [...current, id] : current.filter((one) => one !== id));
  };

  return (
    <section className="space-y-3">
      <div>
        <h3 className="font-medium text-sm">{t("apps:placement.title")}</h3>
        <p className="text-muted-foreground text-sm">{t("apps:placement.description")}</p>
      </div>

      <RadioGroup
        value={chosen === null ? "all" : "some"}
        onValueChange={(value) => save(value === "all" ? null : [])}
        className="space-y-2"
      >
        <div className="flex items-center gap-2">
          <RadioGroupItem value="all" id={`placement-all-${app.id}`} />
          <Label htmlFor={`placement-all-${app.id}`} className="font-normal">
            {t("apps:placement.all")}
          </Label>
        </div>
        <div className="flex items-center gap-2">
          <RadioGroupItem value="some" id={`placement-some-${app.id}`} />
          <Label htmlFor={`placement-some-${app.id}`} className="font-normal">
            {t("apps:placement.some")}
          </Label>
        </div>
      </RadioGroup>

      {chosen !== null && (
        <div className="space-y-2 border-l pl-4">
          {initiatives.isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground text-sm">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("common:loading")}
            </div>
          ) : (
            (initiatives.data ?? []).map((initiative) => (
              <div key={initiative.id} className="flex items-center gap-2">
                <Checkbox
                  id={`placement-${app.id}-${initiative.id}`}
                  checked={chosen.includes(initiative.id)}
                  onCheckedChange={(state) => toggle(initiative.id, state === true)}
                />
                <Label htmlFor={`placement-${app.id}-${initiative.id}`} className="font-normal">
                  {initiative.name}
                </Label>
              </div>
            ))
          )}
          {chosen.length === 0 && (
            <p className="text-muted-foreground text-sm">{t("apps:placement.none")}</p>
          )}
        </div>
      )}
    </section>
  );
}
