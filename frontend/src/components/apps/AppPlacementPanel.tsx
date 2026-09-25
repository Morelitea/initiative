/**
 * Where an app's initiative surfaces appear.
 *
 * An app appears in the initiatives it is placed in and no others. This is
 * where the seat places it — placement rather than permission, so it reads the
 * same for everyone afterwards, including the admin who set it. "Every current
 * initiative" places it in each initiative that exists now; one created later
 * is placed here like any other.
 *
 * Each initiative the app is placed in also says which of its roles can open
 * the app there. Those roles load when the seat opens that initiative's
 * chooser, not for the whole roster up front.
 *
 * Absent for an app with no initiative surface to place: there would be nothing
 * for the choice to move.
 */

import { ChevronDown, Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { GuildAppDetail } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { useSetAppPlacementRoles, useUpdateGuildApp } from "@/hooks/useGuildApps";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import { useInitiatives } from "@/hooks/useInitiatives";
import { declaredEmbeds } from "@/lib/appSurfaces";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

export interface AppPlacementPanelProps {
  app: GuildAppDetail;
}

/** The initiatives the app is placed in. */
const placedIds = (app: GuildAppDetail): number[] =>
  (app.placements ?? []).map((one) => one.initiative_id);

export function AppPlacementPanel({ app }: AppPlacementPanelProps) {
  const { t } = useTranslation(["apps", "common"]);
  const initiatives = useInitiatives();
  const update = useUpdateGuildApp(app.id);
  // What the admin is choosing right now. Seeded from the app and kept locally
  // so ticking several initiatives is one decision, saved per change.
  const [chosen, setChosen] = useState<number[]>(() => placedIds(app));
  // Whether the admin asked to pick initiatives one by one. Until they do, an
  // app placed in every initiative there is reads as "every current one".
  const [picking, setPicking] = useState(false);
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

  const roster = initiatives.data ?? [];
  // Roles decide who opens the app's page, so only an app with one has them.
  const hasPage = declaredEmbeds(app.definition, "initiative").length > 0;
  // The roles each stored placement allows, by initiative.
  const placedRoles = new Map(
    (app.placements ?? []).map((one) => [one.initiative_id, one.role_ids] as const)
  );
  const everywhere = roster.length > 0 && roster.every((one) => chosen.includes(one.id));
  const mode = picking || !everywhere ? "some" : "all";

  const save = (next: number[]) => {
    setChosen(next);
    outstanding.current += 1;
    queue.current = queue.current
      .catch(() => undefined)
      .then(async () => {
        // Only initiatives still on the roster are sent. An initiative deleted
        // after it was chosen leaves an id nothing on screen shows, and
        // resubmitting it would fail every later edit for a reason the admin
        // cannot see.
        const live = !initiatives.data
          ? next
          : next.filter((id) => initiatives.data?.some((one) => one.id === id));
        await update.mutateAsync({ placed_initiative_ids: live });
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
    // Ticking the last box keeps the list open rather than folding it into
    // "every current initiative" under the admin's cursor.
    setPicking(true);
    save(on ? [...chosen, id] : chosen.filter((one) => one !== id));
  };

  const choose = (value: string) => {
    if (value === "all") {
      setPicking(false);
      save(roster.map((one) => one.id));
    } else {
      // Nothing moves until a box is ticked: the current placements stay as
      // they are, shown ticked.
      setPicking(true);
    }
  };

  return (
    <section className="space-y-3">
      <div>
        <h3 className="font-medium text-sm">{t("apps:placement.title")}</h3>
        <p className="text-muted-foreground text-sm">
          {t(hasPage ? "apps:placement.description" : "apps:placement.descriptionNoPage")}
        </p>
      </div>

      <RadioGroup value={mode} onValueChange={choose} className="space-y-2">
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

      {mode === "all" && hasPage && placedRoles.size > 0 && (
        <div className="space-y-2 border-l pl-4">
          {roster
            .filter((initiative) => placedRoles.has(initiative.id))
            .map((initiative) => (
              <div key={initiative.id} className="flex items-center justify-between gap-2">
                <span className="text-sm">{initiative.name}</span>
                <PlacementRoles
                  appId={app.id}
                  initiativeId={initiative.id}
                  initiativeName={initiative.name}
                  roleIds={placedRoles.get(initiative.id) ?? []}
                />
              </div>
            ))}
        </div>
      )}

      {mode === "some" && (
        <div className="space-y-2 border-l pl-4">
          {initiatives.isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground text-sm">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("common:loading")}
            </div>
          ) : (
            roster.map((initiative) => (
              <div key={initiative.id} className="flex items-center gap-2">
                <Checkbox
                  id={`placement-${app.id}-${initiative.id}`}
                  checked={chosen.includes(initiative.id)}
                  onCheckedChange={(state) => toggle(initiative.id, state === true)}
                />
                <Label
                  htmlFor={`placement-${app.id}-${initiative.id}`}
                  className="flex-1 font-normal"
                >
                  {initiative.name}
                </Label>
                {/* Only a placement the server holds has roles to choose. */}
                {hasPage && chosen.includes(initiative.id) && placedRoles.has(initiative.id) && (
                  <PlacementRoles
                    appId={app.id}
                    initiativeId={initiative.id}
                    initiativeName={initiative.name}
                    roleIds={placedRoles.get(initiative.id) ?? []}
                  />
                )}
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

interface PlacementRolesProps {
  appId: number;
  initiativeId: number;
  initiativeName: string;
  /** The roles the stored placement allows. */
  roleIds: number[];
}

/** Who can open the app in one initiative, chosen from a popover. */
function PlacementRoles({ appId, initiativeId, initiativeName, roleIds }: PlacementRolesProps) {
  const { t } = useTranslation(["apps", "common"]);
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 gap-1 px-2 text-muted-foreground text-xs"
          aria-label={t("apps:placement.roles.open", { name: initiativeName })}
        >
          {roleIds.length === 0
            ? t("apps:placement.roles.adminsOnly")
            : t("apps:placement.roles.count", { count: roleIds.length })}
          <ChevronDown className="h-3 w-3" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 space-y-3">
        <div className="space-y-1">
          <h4 className="font-medium text-sm">{t("apps:placement.roles.title")}</h4>
          <p className="text-muted-foreground text-xs">{t("apps:placement.roles.adminsAlways")}</p>
        </div>
        {/* Mounted only while open, so the roles load for this one initiative. */}
        {open && (
          <PlacementRoleChoices appId={appId} initiativeId={initiativeId} roleIds={roleIds} />
        )}
      </PopoverContent>
    </Popover>
  );
}

function PlacementRoleChoices({
  appId,
  initiativeId,
  roleIds,
}: Omit<PlacementRolesProps, "initiativeName">) {
  const { t } = useTranslation(["apps", "common"]);
  const roles = useInitiativeRoles(initiativeId);
  const setRoles = useSetAppPlacementRoles(appId);
  // Seeded from the stored placement each time the chooser opens, then kept
  // to what each save returns.
  const [chosen, setChosen] = useState<number[]>(roleIds);

  const toggle = (roleId: number, on: boolean) => {
    const before = chosen;
    const next = on ? [...chosen, roleId] : chosen.filter((one) => one !== roleId);
    setChosen(next);
    setRoles.mutate(
      { initiativeId, roleIds: next },
      {
        onSuccess: (placement) => setChosen(placement.role_ids),
        onError: () => setChosen(before),
      }
    );
  };

  if (roles.isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("common:loading")}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {(roles.data ?? []).map((role) => (
        <div key={role.id} className="flex items-center gap-2">
          <Checkbox
            id={`placement-role-${appId}-${initiativeId}-${role.id}`}
            checked={chosen.includes(role.id)}
            // One save at a time: each sends the whole set.
            disabled={setRoles.isPending}
            onCheckedChange={(state) => toggle(role.id, state === true)}
          />
          <Label
            htmlFor={`placement-role-${appId}-${initiativeId}-${role.id}`}
            className="font-normal"
          >
            {role.display_name}
          </Label>
        </div>
      ))}
    </div>
  );
}
