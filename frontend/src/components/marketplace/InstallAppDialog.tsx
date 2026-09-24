/**
 * Adding an app to the guild, with the seat's consent.
 *
 * An app belongs to the guild, so there is no initiative to choose for it the
 * way there is for a dashboard. What the seat does choose is on this one
 * screen, and is confirmed once:
 *
 * 1. **What it can reach.** Each scope the app asks for, as a plain sentence.
 *    Everything this server allows starts ticked; a scope it does not allow is
 *    shown disabled, with the reason.
 * 2. **Where it appears.** Only for an app with a page inside initiatives:
 *    every current initiative, or the ones picked here.
 * 3. **Who can open it there.** Built-in roles, moderators by default, applied
 *    to every initiative it is placed in.
 *
 * The server installs, grants and places in one transaction, under the same
 * checks the app's settings apply afterwards.
 *
 * Guild admins only. The server enforces that; this hides the action rather
 * than offering one that would be refused.
 */

import { useNavigate } from "@tanstack/react-router";
import { Download, Loader2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { MarketplaceListingDetail } from "@/api/generated/initiativeAPI.schemas";
import { ListingProvenance } from "@/components/marketplace/ListingProvenance";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { useInstallGuildApp } from "@/hooks/useGuildApps";
import { useInitiatives } from "@/hooks/useInitiatives";
import { scopeSentence, toggleScope } from "@/lib/appScopes";
import { guildAppPath } from "@/lib/appSurfaces";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";
import type { DialogProps } from "@/types/dialog";

export interface InstallAppDialogProps extends DialogProps {
  listing: MarketplaceListingDetail;
}

/** The built-in initiative roles the seat may let open the app. */
export const ROLE_KINDS = ["moderator", "project_manager", "member"] as const;
type RoleKind = (typeof ROLE_KINDS)[number];

export function InstallAppDialog({ listing, open, onOpenChange }: InstallAppDialogProps) {
  const { t } = useTranslation(["apps", "common", "nav"]);
  const navigate = useNavigate();
  const gp = useGuildPath();

  const requested = listing.requested_scopes ?? [];
  const grantable = new Set(listing.grantable_scopes ?? []);
  const placeable = listing.has_initiative_surfaces ?? false;

  const [name, setName] = useState(listing.name);
  // Every scope the server allows starts ticked; the seat unticks.
  const [scopes, setScopes] = useState<string[]>(() =>
    requested.filter((scope) => grantable.has(scope))
  );
  const [where, setWhere] = useState<"all" | "some">("all");
  const [picked, setPicked] = useState<number[]>([]);
  const [roles, setRoles] = useState<RoleKind[]>(["moderator"]);
  const install = useInstallGuildApp();

  const submit = () =>
    install.mutate(
      {
        listing_uid: listing.uid,
        name: name.trim() || listing.name,
        granted_scopes: scopes,
        placements: !placeable ? [] : where === "all" ? "all" : picked,
        role_kinds: roles,
      },
      {
        onSuccess: (app) => {
          toast.success(t("apps:install.done", { name: app.name }));
          onOpenChange(false);
          // Straight to what it created, when it created something reachable.
          const path = guildAppPath(app);
          if (path) navigate({ to: gp(path) });
        },
        onError: (error) => {
          toast.error(getErrorMessage(error, "apps:error"));
        },
      }
    );

  const toggleRole = (role: RoleKind, on: boolean) =>
    setRoles((current) =>
      on ? [...new Set([...current, role])] : current.filter((one) => one !== role)
    );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("apps:install.title", { name: listing.name })}</DialogTitle>
          <DialogDescription>{t("apps:install.description")}</DialogDescription>
        </DialogHeader>

        {/* An app reaches the whole guild, so who wrote it is said here too —
            the same sentence the card and the listing page showed. */}
        <ListingProvenance listing={listing} />

        <div className="space-y-1.5">
          <Label htmlFor="install-app-name">{t("apps:install.name")}</Label>
          <Input
            id="install-app-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={listing.name}
          />
        </div>

        {requested.length > 0 && (
          <section className="space-y-2" aria-labelledby="install-app-reach">
            <h3 id="install-app-reach" className="font-medium text-sm">
              {t("apps:install.reachTitle")}
            </h3>
            <ul className="space-y-2">
              {requested.map((scope) => {
                const allowed = grantable.has(scope);
                const id = `install-scope-${scope.replace(":", "-")}`;
                return (
                  <li key={scope} className="flex items-start gap-2">
                    <Checkbox
                      id={id}
                      checked={scopes.includes(scope)}
                      disabled={!allowed || install.isPending}
                      onCheckedChange={(state) =>
                        setScopes((current) =>
                          toggleScope(current, scope, state === true, grantable)
                        )
                      }
                    />
                    <div className="space-y-0.5">
                      <Label htmlFor={id} className="font-normal">
                        {scopeSentence(scope, t)}
                      </Label>
                      {!allowed && (
                        <p className="text-muted-foreground text-xs">
                          {t("apps:scopes.notAllowed")}
                        </p>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {placeable && (
          <section className="space-y-2" aria-labelledby="install-app-where">
            <div>
              <h3 id="install-app-where" className="font-medium text-sm">
                {t("apps:install.whereTitle")}
              </h3>
              <p className="text-muted-foreground text-xs">{t("apps:install.whereDescription")}</p>
            </div>
            <RadioGroup
              value={where}
              onValueChange={(value) => setWhere(value === "some" ? "some" : "all")}
              className="space-y-2"
            >
              <div className="flex items-center gap-2">
                <RadioGroupItem value="all" id="install-app-where-all" />
                <Label htmlFor="install-app-where-all" className="font-normal">
                  {t("apps:placement.all")}
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="some" id="install-app-where-some" />
                <Label htmlFor="install-app-where-some" className="font-normal">
                  {t("apps:placement.some")}
                </Label>
              </div>
            </RadioGroup>
            {where === "some" && <InitiativePicker picked={picked} onChange={setPicked} />}
          </section>
        )}

        {placeable && (
          <section className="space-y-2" aria-labelledby="install-app-who">
            <div>
              <h3 id="install-app-who" className="font-medium text-sm">
                {t("apps:install.whoTitle")}
              </h3>
              <p className="text-muted-foreground text-xs">
                {t("apps:placement.roles.adminsAlways")}
              </p>
            </div>
            <div className="space-y-2">
              {ROLE_KINDS.map((role) => (
                <div key={role} className="flex items-center gap-2">
                  <Checkbox
                    id={`install-app-role-${role}`}
                    checked={roles.includes(role)}
                    disabled={install.isPending}
                    onCheckedChange={(state) => toggleRole(role, state === true)}
                  />
                  <Label htmlFor={`install-app-role-${role}`} className="font-normal">
                    {t(`apps:install.roles.${role}` as never)}
                  </Label>
                </div>
              ))}
            </div>
          </section>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common:cancel")}
          </Button>
          <Button onClick={submit} disabled={install.isPending}>
            {install.isPending ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Download className="mr-1.5 h-4 w-4" />
            )}
            {t("apps:install.action")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** The guild's initiatives, ticked one by one. Loaded only once asked for. */
function InitiativePicker({
  picked,
  onChange,
}: {
  picked: number[];
  onChange: (next: number[]) => void;
}) {
  const { t } = useTranslation(["apps", "common"]);
  const initiatives = useInitiatives();

  if (initiatives.isLoading) {
    return (
      <div className="flex items-center gap-2 border-l pl-4 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("common:loading")}
      </div>
    );
  }

  return (
    <div className="space-y-2 border-l pl-4">
      {(initiatives.data ?? []).map((initiative) => (
        <div key={initiative.id} className="flex items-center gap-2">
          <Checkbox
            id={`install-app-initiative-${initiative.id}`}
            checked={picked.includes(initiative.id)}
            onCheckedChange={(state) =>
              onChange(
                state === true
                  ? [...new Set([...picked, initiative.id])]
                  : picked.filter((one) => one !== initiative.id)
              )
            }
          />
          <Label htmlFor={`install-app-initiative-${initiative.id}`} className="font-normal">
            {initiative.name}
          </Label>
        </div>
      ))}
      {picked.length === 0 && (
        <p className="text-muted-foreground text-sm">{t("apps:placement.none")}</p>
      )}
    </div>
  );
}
