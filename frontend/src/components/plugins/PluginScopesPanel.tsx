/**
 * What an app can reach in the community.
 *
 * The app's manifest lists the scopes it asks for, and the seat grants any of
 * them here. A requested scope this server does not allow is shown but cannot
 * be ticked. Changing something implies reading it, so granting a change
 * includes the read, and taking the read away takes the change with it.
 * Using another app, and acting as a moderator or an admin, are each a row of
 * their own, said as a sentence: none of them is reading or changing a kind of
 * thing.
 *
 * Saved as one set: the server replaces the whole grant.
 */

import { Loader2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { CommunityPluginDetail } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { useSetPluginScopes } from "@/hooks/useCommunityPlugins";
import {
  pluginScopeTarget,
  type ScopeAccess,
  STANDING_SCOPES,
  scopeResourceLabel,
  scopeSentence,
  toggleScope,
} from "@/lib/pluginScopes";
import { toast } from "@/lib/mascotToast";

export interface PluginScopesPanelProps {
  app: CommunityPluginDetail;
}

type Access = ScopeAccess;

/** One resource the app asks for, and which of its accesses. */
interface ResourceRow {
  resource: string;
  accesses: Access[];
}

const scopeOf = (resource: string, access: Access) => `${resource}:${access}`;

/** A scope said as a sentence on a row of its own rather than as an access to
 * a resource: using another app, or acting as a moderator or an admin. */
const isSentenceScope = (scope: string) =>
  pluginScopeTarget(scope) !== null || STANDING_SCOPES.has(scope);

/** The requested scopes grouped by resource, keeping their order. */
const resourceRows = (requested: string[]): ResourceRow[] => {
  const rows: ResourceRow[] = [];
  for (const scope of requested) {
    if (isSentenceScope(scope)) continue;
    const [resource, access] = scope.split(":") as [string, Access];
    const row = rows.find((one) => one.resource === resource);
    if (row) row.accesses.push(access);
    else rows.push({ resource, accesses: [access] });
  }
  return rows;
};

/** The same set, regardless of order. */
const sameSet = (a: string[], b: string[]) =>
  a.length === b.length && a.every((one) => b.includes(one));

export function PluginScopesPanel({ app }: PluginScopesPanelProps) {
  const { t } = useTranslation(["apps", "common", "nav"]);
  const setScopes = useSetPluginScopes(app.id);
  const requested = app.requested_scopes ?? [];
  const grantable = new Set(app.grantable_scopes ?? []);
  const granted = app.granted_scopes ?? [];
  // What the seat is choosing. Only grantable scopes are ever in it, so a
  // save is never refused for one the server no longer allows.
  const [chosen, setChosen] = useState<string[]>(() =>
    granted.filter((scope) => grantable.has(scope))
  );

  const resourceLabel = (resource: string): string => scopeResourceLabel(resource, t);

  const toggle = (resource: string, access: Access, on: boolean) =>
    setChosen(toggleScope(chosen, scopeOf(resource, access), on, grantable));

  const save = () =>
    setScopes.mutate(chosen, {
      onSuccess: (read) => {
        setChosen(read.granted_scopes);
        toast.success(t("apps:scopes.saved"));
      },
    });

  const rows = resourceRows(requested);
  const sentenceScopes = requested.filter(isSentenceScope);

  return (
    <section className="space-y-3">
      <div>
        <h3 className="font-medium text-sm">{t("apps:scopes.title")}</h3>
        <p className="text-muted-foreground text-sm">{t("apps:scopes.description")}</p>
      </div>

      <ul className="divide-y rounded-md border">
        {rows.map((row) => (
          <li key={row.resource} className="flex flex-wrap items-center gap-x-4 gap-y-2 p-3">
            <span className="min-w-32 flex-1 font-medium text-sm">
              {resourceLabel(row.resource)}
            </span>
            {row.accesses.map((access) => {
              const scope = scopeOf(row.resource, access);
              const allowed = grantable.has(scope);
              const id = `scope-${app.id}-${row.resource}-${access}`;
              return (
                <div key={access} className="flex items-center gap-2">
                  <Checkbox
                    id={id}
                    checked={chosen.includes(scope)}
                    disabled={!allowed || setScopes.isPending}
                    onCheckedChange={(state) => toggle(row.resource, access, state === true)}
                  />
                  <Label htmlFor={id} className="font-normal">
                    {access === "read" ? t("apps:scopes.read") : t("apps:scopes.write")}
                  </Label>
                  {!allowed && (
                    <span className="text-muted-foreground text-xs">
                      {t("apps:scopes.notAllowed")}
                    </span>
                  )}
                </div>
              );
            })}
          </li>
        ))}
        {sentenceScopes.map((scope) => {
          const allowed = grantable.has(scope);
          const id = `scope-${app.id}-${scope.replace(":", "-")}`;
          return (
            <li key={scope} className="flex flex-wrap items-center gap-2 p-3">
              <Checkbox
                id={id}
                checked={chosen.includes(scope)}
                disabled={!allowed || setScopes.isPending}
                onCheckedChange={(state) =>
                  setChosen(toggleScope(chosen, scope, state === true, grantable))
                }
              />
              <Label htmlFor={id} className="font-normal">
                {scopeSentence(scope, t, app.plugin_names)}
              </Label>
              {!allowed && (
                <span className="text-muted-foreground text-xs">{t("apps:scopes.notAllowed")}</span>
              )}
            </li>
          );
        })}
      </ul>

      <div className="flex justify-end">
        <Button size="sm" onClick={save} disabled={setScopes.isPending || sameSet(chosen, granted)}>
          {setScopes.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
          {t("common:save")}
        </Button>
      </div>
    </section>
  );
}
