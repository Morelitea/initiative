/**
 * Where this community places the people its providers vouch for.
 *
 * The other half of a connection. A connection says which arrivals count as
 * ours; a rule says where one of them lands — as a member or an admin, and in
 * an initiative if we say so. A community says both in one breath, so they sit
 * on one page: our people come in through this, and these of them belong here.
 *
 * Which claim carries groups is the operator's to set on the provider, so a
 * connection they have not set it on is offered with a note rather than
 * hidden: the rule would be written correctly and simply never match.
 */

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { GuildClaimRuleRead } from "@/api/generated/initiativeAPI.schemas";
import { ProviderMark } from "@/components/auth/ProviderMark";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useCreateClaimRule,
  useDeleteClaimRule,
  useGuildClaimRules,
  useGuildProviderConnections,
} from "@/hooks/useGuildAuthPolicy";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import { useInitiativesForGuild } from "@/hooks/useInitiatives";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

/** Sentinel for "the community itself", which has no initiative id. */
const COMMUNITY_ONLY = "community";

export const GuildClaimRulesSection = ({ guildId }: { guildId: number }) => {
  const { t } = useTranslation("settings");
  const rulesQuery = useGuildClaimRules(guildId);
  const connectionsQuery = useGuildProviderConnections(guildId);
  const initiativesQuery = useInitiativesForGuild(guildId);
  const createRule = useCreateClaimRule(guildId);
  const deleteRule = useDeleteClaimRule(guildId);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [providerId, setProviderId] = useState("");
  const [claimValue, setClaimValue] = useState("");
  const [guildRole, setGuildRole] = useState("member");
  const [initiativeId, setInitiativeId] = useState<string>(COMMUNITY_ONLY);
  const [initiativeRoleId, setInitiativeRoleId] = useState("");
  const [removing, setRemoving] = useState<GuildClaimRuleRead | null>(null);

  const rules = rulesQuery.data?.rules ?? [];
  const reporting = new Set(rulesQuery.data?.reporting_provider_ids ?? []);
  const connections = connectionsQuery.data ?? [];
  const initiatives = initiativesQuery.data ?? [];
  const chosenInitiative = initiativeId === COMMUNITY_ONLY ? null : Number(initiativeId);
  const rolesQuery = useInitiativeRoles(chosenInitiative);
  const roles = rolesQuery.data ?? [];

  const closeDialog = () => {
    setDialogOpen(false);
    setProviderId("");
    setClaimValue("");
    setGuildRole("member");
    setInitiativeId(COMMUNITY_ONLY);
    setInitiativeRoleId("");
  };

  const submit = () => {
    createRule.mutate(
      {
        provider_id: Number(providerId),
        claim_value: claimValue.trim(),
        guild_role: guildRole,
        // Both halves or neither: somebody placed in an initiative needs the
        // standing to hold there.
        initiative_id: chosenInitiative,
        initiative_role_id: chosenInitiative ? Number(initiativeRoleId) : null,
      },
      {
        onSuccess: () => {
          toast.success(t("guildAuth.rules.added"));
          closeDialog();
        },
        onError: (error) =>
          toast.error(getErrorMessage(error, "settings:guildAuth.rules.addError")),
      }
    );
  };

  /** Spelled out rather than interpolated into the key, so the two standings a
   *  rule may hand out are the two the translations carry. */
  const roleLabel = (role: string) =>
    role === "admin" ? t("guildAuth.rules.role.admin") : t("guildAuth.rules.role.member");

  const canSubmit =
    providerId !== "" &&
    claimValue.trim() !== "" &&
    (chosenInitiative === null || initiativeRoleId !== "");

  return (
    <Card className="shadow-sm">
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle>{t("guildAuth.rules.title")}</CardTitle>
          <CardDescription>{t("guildAuth.rules.description")}</CardDescription>
        </div>
        <Button
          type="button"
          onClick={() => setDialogOpen(true)}
          disabled={connections.length === 0}
        >
          <Plus className="h-4 w-4" />
          {t("guildAuth.rules.add")}
        </Button>
      </CardHeader>
      <CardContent>
        {rulesQuery.isLoading ? (
          <p className="text-muted-foreground text-sm">{t("authProviders.loading")}</p>
        ) : rules.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {connections.length === 0
              ? t("guildAuth.rules.connectFirst")
              : t("guildAuth.rules.empty")}
          </p>
        ) : (
          <ul className="divide-y rounded-md border">
            {rules.map((rule) => (
              <li key={rule.id} className="flex items-center justify-between gap-4 px-3 py-3">
                <div className="flex min-w-0 items-start gap-3">
                  <ProviderMark icon={rule.provider_icon} className="mt-0.5" />
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{rule.claim_value}</span>
                      {!reporting.has(rule.provider_id) && (
                        <Badge variant="outline">{t("guildAuth.rules.noGroupsBadge")}</Badge>
                      )}
                    </div>
                    <p className="text-muted-foreground text-sm">
                      {rule.initiative_name
                        ? t("guildAuth.rules.landsInInitiative", {
                            provider: rule.provider_display_name,
                            role: roleLabel(rule.guild_role),
                            initiative: rule.initiative_name,
                            initiativeRole: rule.initiative_role_name ?? "",
                          })
                        : t("guildAuth.rules.landsInCommunity", {
                            provider: rule.provider_display_name,
                            role: roleLabel(rule.guild_role),
                          })}
                    </p>
                  </div>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="shrink-0 text-destructive"
                  aria-label={t("guildAuth.rules.remove")}
                  onClick={() => setRemoving(rule)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>

      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => (open ? setDialogOpen(true) : closeDialog())}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("guildAuth.rules.add")}</DialogTitle>
            <DialogDescription>{t("guildAuth.rules.dialogDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="rule-provider">{t("guildAuth.rules.providerLabel")}</Label>
              <Select value={providerId} onValueChange={setProviderId}>
                <SelectTrigger id="rule-provider">
                  <SelectValue placeholder={t("guildAuth.rules.providerPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {connections.map((row) => (
                    <SelectItem key={row.provider_id} value={String(row.provider_id)}>
                      {row.provider_display_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {providerId !== "" && !reporting.has(Number(providerId)) && (
                <p className="text-muted-foreground text-xs">{t("guildAuth.rules.noGroupsHint")}</p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="rule-group">{t("guildAuth.rules.groupLabel")}</Label>
              <Input
                id="rule-group"
                value={claimValue}
                onChange={(event) => setClaimValue(event.target.value)}
                placeholder={t("guildAuth.rules.groupPlaceholder")}
              />
              <p className="text-muted-foreground text-xs">{t("guildAuth.rules.groupHint")}</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="rule-role">{t("guildAuth.rules.standingLabel")}</Label>
              <Select value={guildRole} onValueChange={setGuildRole}>
                <SelectTrigger id="rule-role">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="member">{t("guildAuth.rules.role.member")}</SelectItem>
                  <SelectItem value="admin">{t("guildAuth.rules.role.admin")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="rule-initiative">{t("guildAuth.rules.initiativeLabel")}</Label>
              <Select
                value={initiativeId}
                onValueChange={(value) => {
                  setInitiativeId(value);
                  setInitiativeRoleId("");
                }}
              >
                <SelectTrigger id="rule-initiative">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={COMMUNITY_ONLY}>
                    {t("guildAuth.rules.communityOnly")}
                  </SelectItem>
                  {initiatives.map((initiative) => (
                    <SelectItem key={initiative.id} value={String(initiative.id)}>
                      {initiative.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {chosenInitiative !== null && (
              <div className="space-y-2">
                <Label htmlFor="rule-initiative-role">
                  {t("guildAuth.rules.initiativeRoleLabel")}
                </Label>
                <Select value={initiativeRoleId} onValueChange={setInitiativeRoleId}>
                  <SelectTrigger id="rule-initiative-role">
                    <SelectValue placeholder={t("guildAuth.rules.initiativeRolePlaceholder")} />
                  </SelectTrigger>
                  <SelectContent>
                    {roles.map((role) => (
                      <SelectItem key={role.id} value={String(role.id)}>
                        {role.display_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={closeDialog}>
              {t("authProviders.cancel")}
            </Button>
            <Button type="button" onClick={submit} disabled={!canSubmit || createRule.isPending}>
              {t("guildAuth.rules.add")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={t("guildAuth.rules.removeTitle")}
        description={t("guildAuth.rules.removeDescription", {
          group: removing?.claim_value ?? "",
        })}
        confirmLabel={t("guildAuth.rules.remove")}
        cancelLabel={t("authProviders.cancel")}
        destructive
        isLoading={deleteRule.isPending}
        onConfirm={() => {
          if (!removing) return;
          deleteRule.mutate(removing.id, {
            onSuccess: () => {
              toast.success(t("guildAuth.rules.removed"));
              setRemoving(null);
            },
            onError: (error) => {
              toast.error(getErrorMessage(error, "settings:guildAuth.rules.removeError"));
              setRemoving(null);
            },
          });
        }}
      />
    </Card>
  );
};
