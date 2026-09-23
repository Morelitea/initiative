import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  PlacementProviderRead,
  ProviderPlacementRuleRead,
} from "@/api/generated/initiativeAPI.schemas";
import { ProviderPlacementRuleDialog } from "@/components/admin/ProviderPlacementRuleDialog";
import { SettingRow } from "@/components/admin/SettingRow";
import { ProviderMark } from "@/components/auth/ProviderMark";
import {
  describePlacementMatch,
  NotApplyingBadge,
  placementRoleLabel,
} from "@/components/auth/ProviderPlacementRuleSummary";
import { SkeletonRegion, TableSkeleton } from "@/components/skeletons/PageSkeletons";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/hooks/useAuth";
import {
  useDeletePlacementRule,
  useProviderPlacement,
  useSetPlacementEverywhere,
} from "@/hooks/useProviderPlacement";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { Capability, hasCapability } from "@/lib/permissions";

/** The rule dialog's subject: a provider, and the rule on it being edited. */
type Editing = { provider: PlacementProviderRead; rule: ProviderPlacementRuleRead | null };

/**
 * Sign-in placement rules the platform writes on its providers: which of the
 * people a provider signs in land in which community, at what standing, and
 * in which initiative there.
 *
 * A rule takes effect in a community that accepted its provider's rules on
 * that community's own connection, or everywhere once the owner applies them
 * to every community — the switch at the top, recorded on every change.
 */
export const OperatorDashboardPlacementPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const canManageGuilds = hasCapability(user, Capability.guildsManage);
  const canSetEverywhere = hasCapability(user, Capability.configManage);

  const placementQuery = useProviderPlacement({ enabled: canManageGuilds });

  const [editing, setEditing] = useState<Editing | null>(null);
  const [removing, setRemoving] = useState<ProviderPlacementRuleRead | null>(null);
  const [confirmEverywhere, setConfirmEverywhere] = useState(false);

  const setEverywhere = useSetPlacementEverywhere();
  const deleteRule = useDeletePlacementRule();

  const applyEverywhere = (enabled: boolean) =>
    setEverywhere.mutate(enabled, {
      onSuccess: () =>
        toast.success(
          enabled
            ? t("providerPlacement.everywhere.enabled")
            : t("providerPlacement.everywhere.disabled")
        ),
      onError: (error) =>
        toast.error(getErrorMessage(error, "settings:providerPlacement.everywhere.error")),
      // Close the confirm dialog only once the save settles, so its in-flight
      // state shows while it runs.
      onSettled: () => setConfirmEverywhere(false),
    });

  const removeRule = (rule: ProviderPlacementRuleRead) =>
    deleteRule.mutate(rule.id, {
      onSuccess: () => toast.success(t("providerPlacement.removed")),
      onError: (error) =>
        toast.error(getErrorMessage(error, "settings:providerPlacement.removeError")),
      onSettled: () => setRemoving(null),
    });

  if (!canManageGuilds) {
    return <p className="text-muted-foreground text-sm">{t("providerPlacement.adminOnly")}</p>;
  }

  if (placementQuery.isLoading) {
    return (
      <SkeletonRegion label={t("providerPlacement.loading")}>
        <TableSkeleton rows={4} columns={3} />
      </SkeletonRegion>
    );
  }

  if (placementQuery.isError || !placementQuery.data) {
    return <p className="text-destructive text-sm">{t("providerPlacement.loadError")}</p>;
  }

  const { placement_everywhere: everywhere, providers, rules } = placementQuery.data;

  const changeEverywhere = (enabled: boolean) => {
    // Turning it on reaches communities that never accepted, so it is
    // confirmed first; turning it off applies at once.
    if (enabled) {
      setConfirmEverywhere(true);
      return;
    }
    applyEverywhere(false);
  };

  return (
    <div className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("providerPlacement.title")}</CardTitle>
          <CardDescription>{t("providerPlacement.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <SettingRow
            htmlFor="placement-everywhere"
            label={t("providerPlacement.everywhere.label")}
            help={
              canSetEverywhere
                ? t("providerPlacement.everywhere.help")
                : `${t("providerPlacement.everywhere.help")} ${t("providerPlacement.everywhere.ownerOnly")}`
            }
            control={
              <Switch
                id="placement-everywhere"
                checked={everywhere}
                disabled={!canSetEverywhere || setEverywhere.isPending}
                onCheckedChange={(checked) => changeEverywhere(Boolean(checked))}
              />
            }
          />
        </CardContent>
      </Card>

      {providers.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("providerPlacement.noProviders")}</p>
      ) : (
        providers.map((provider) => (
          <ProviderRulesCard
            key={provider.id}
            provider={provider}
            rules={rules.filter((rule) => rule.provider_id === provider.id)}
            onAdd={() => setEditing({ provider, rule: null })}
            onEdit={(rule) => setEditing({ provider, rule })}
            onRemove={setRemoving}
          />
        ))
      )}

      {editing ? (
        <ProviderPlacementRuleDialog
          key={`${editing.provider.id}-${editing.rule?.id ?? "new"}`}
          provider={editing.provider}
          rule={editing.rule}
          onClose={() => setEditing(null)}
        />
      ) : null}

      <ConfirmDialog
        open={confirmEverywhere}
        onOpenChange={(open) => !open && setConfirmEverywhere(false)}
        title={t("providerPlacement.everywhere.confirmTitle")}
        description={t("providerPlacement.everywhere.confirmDescription")}
        confirmLabel={t("providerPlacement.everywhere.confirm")}
        cancelLabel={t("authProviders.cancel")}
        isLoading={setEverywhere.isPending}
        onConfirm={() => applyEverywhere(true)}
      />

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={t("providerPlacement.removeTitle")}
        description={t("providerPlacement.removeDescription", {
          community: removing?.guild_name ?? "",
        })}
        confirmLabel={t("providerPlacement.remove")}
        cancelLabel={t("authProviders.cancel")}
        destructive
        isLoading={deleteRule.isPending}
        onConfirm={() => removing && removeRule(removing)}
      />
    </div>
  );
};

/** One provider and the rules written on it. */
const ProviderRulesCard = ({
  provider,
  rules,
  onAdd,
  onEdit,
  onRemove,
}: {
  provider: PlacementProviderRead;
  rules: ProviderPlacementRuleRead[];
  onAdd: () => void;
  onEdit: (rule: ProviderPlacementRuleRead) => void;
  onRemove: (rule: ProviderPlacementRuleRead) => void;
}) => {
  const { t } = useTranslation("settings");
  return (
    <Card className="shadow-sm">
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div className="flex min-w-0 items-start gap-3">
          <ProviderMark icon={provider.icon} className="mt-1" />
          <div className="min-w-0 space-y-1.5">
            <CardTitle>{provider.display_name}</CardTitle>
            {!provider.reports_groups && (
              <CardDescription>{t("providerPlacement.noGroups")}</CardDescription>
            )}
          </div>
        </div>
        <Button
          type="button"
          onClick={onAdd}
          aria-label={t("providerPlacement.addFor", { provider: provider.display_name })}
        >
          <Plus className="h-4 w-4" />
          {t("providerPlacement.add")}
        </Button>
      </CardHeader>
      <CardContent>
        {rules.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("providerPlacement.empty")}</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {rules.map((rule) => (
              <li key={rule.id} className="flex items-center justify-between gap-4 px-3 py-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{describePlacementMatch(rule, t)}</span>
                    {!rule.applies && <NotApplyingBadge />}
                  </div>
                  <p className="text-muted-foreground text-sm">
                    {rule.initiative_name
                      ? t("providerPlacement.landsInInitiative", {
                          community: rule.guild_name,
                          role: placementRoleLabel(rule.guild_role, t),
                          initiative: rule.initiative_name,
                          initiativeRole: rule.initiative_role_name ?? "",
                        })
                      : t("providerPlacement.landsInCommunity", {
                          community: rule.guild_name,
                          role: placementRoleLabel(rule.guild_role, t),
                        })}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={t("providerPlacement.editLabel")}
                    onClick={() => onEdit(rule)}
                  >
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="text-destructive"
                    aria-label={t("providerPlacement.remove")}
                    onClick={() => onRemove(rule)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
};
