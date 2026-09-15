/**
 * Where this deployment's operations work lands (platform settings → Intake).
 *
 * Two levels of decision, in the order an owner makes them: name the community
 * that receives operations work, then say which project each stream lands in.
 * Nothing below the first is offered until it is answered, because every id in
 * it belongs to that community.
 *
 * Each stream offers the same two routes: import the blueprint, which produces
 * a ready-made project, or point at a project the team already has. Both end in
 * the same binding — the blueprint is a convenience, not a different mechanism.
 */

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  IntakeBindingRead,
  IntakeInitiativeOption,
  IntakeStream,
} from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/hooks/useAuth";
import {
  useDeleteIntakeBinding,
  useImportIntakeBlueprint,
  useIntakeOptions,
  useIntakeSettings,
  useUpdateOperationsGuild,
  useUpsertIntakeBinding,
} from "@/hooks/useIntakeSettings";
import { usePlatformGuilds } from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { formatDateTime } from "@/lib/formatDate";
import { Capability, hasCapability } from "@/lib/permissions";

/** Sentinel for "no community", which a Select cannot express with "". */
const NONE = "none";

export const SettingsIntakePage = () => {
  const { t } = useTranslation("intake");
  const { user } = useAuth();
  const isOwner = hasCapability(user, Capability.configManage);

  const {
    data: settings,
    isLoading,
    isFetching: settingsFetching,
    isError,
    refetch,
  } = useIntakeSettings({ enabled: isOwner });
  const { data: options, isFetching: optionsFetching } = useIntakeOptions({
    enabled: isOwner,
  });
  const { data: guilds } = usePlatformGuilds({ enabled: isOwner });

  // Until both reads agree, the bindings and the projects they could name can
  // be from different communities, so nothing that writes one is offered.
  const settled = !settingsFetching && !optionsFetching;

  const [clearing, setClearing] = useState(false);

  const updateGuild = useUpdateOperationsGuild({
    onError: (err) => toast.error(getErrorMessage(err, "intake:guild.saveError")),
  });

  if (!isOwner) {
    return <p className="text-muted-foreground text-sm">{t("ownerOnly")}</p>;
  }

  // A read that failed is a different state from a deployment that has
  // configured nothing, and says so. The picker stays out of reach until the
  // current value is known.
  if (isError) {
    return (
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("loadFailed.title")}</CardTitle>
          <CardDescription>{t("loadFailed.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" onClick={() => refetch()}>
            {t("loadFailed.retry")}
          </Button>
        </CardContent>
      </Card>
    );
  }

  const boundGuildId = settings?.operations_guild_id ?? null;

  return (
    <div className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("guild.title")}</CardTitle>
          <CardDescription>{t("guild.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Label htmlFor="operations-guild">{t("guild.label")}</Label>
          <Select
            value={boundGuildId === null ? NONE : String(boundGuildId)}
            disabled={isLoading || !settled || updateGuild.isPending}
            onValueChange={(value) => {
              // Clearing it stops every stream at once, so it is confirmed;
              // choosing a different one is an ordinary change.
              if (value === NONE) {
                setClearing(true);
                return;
              }
              updateGuild.mutate({ guild_id: Number(value) });
            }}
          >
            <SelectTrigger id="operations-guild" className="max-w-md">
              <SelectValue placeholder={t("guild.placeholder")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>{t("guild.none")}</SelectItem>
              {(guilds ?? []).map((guild) => (
                <SelectItem key={guild.id} value={String(guild.id)}>
                  {guild.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-muted-foreground text-sm">{t("guild.helpText")}</p>
        </CardContent>
      </Card>

      {boundGuildId === null ? (
        <p className="text-muted-foreground text-sm">{t("streams.chooseGuildFirst")}</p>
      ) : (
        <div className="space-y-4">
          {(settings?.bindings ?? []).map((binding) => (
            <StreamCard
              key={binding.stream}
              binding={binding}
              initiatives={options?.initiatives ?? []}
              settled={settled}
            />
          ))}
        </div>
      )}

      <ConfirmDialog
        open={clearing}
        onOpenChange={setClearing}
        title={t("guild.clearTitle")}
        description={t("guild.clearBody")}
        confirmLabel={t("guild.clearConfirm")}
        onConfirm={() => updateGuild.mutate({ guild_id: null })}
      />
    </div>
  );
};

interface StreamCardProps {
  binding: IntakeBindingRead;
  initiatives: IntakeInitiativeOption[];
  /** Both reads have settled, so bindings and options describe one community. */
  settled: boolean;
}

const StreamCard = ({ binding, initiatives, settled }: StreamCardProps) => {
  const { t } = useTranslation("intake");
  const stream = binding.stream as IntakeStream;

  const [initiativeId, setInitiativeId] = useState<string>("");
  const [unbinding, setUnbinding] = useState(false);

  const importBlueprint = useImportIntakeBlueprint({
    onSuccess: (result) => toast.success(t("stream.createdToast", { name: result.project_name })),
    onError: (err) => toast.error(getErrorMessage(err, "intake:stream.saveError")),
  });
  const upsert = useUpsertIntakeBinding({
    onError: (err) => toast.error(getErrorMessage(err, "intake:stream.saveError")),
  });
  const remove = useDeleteIntakeBinding({
    onSuccess: () => toast.success(t("stream.unboundToast")),
    onError: (err) => toast.error(getErrorMessage(err, "intake:stream.saveError")),
  });

  // Every project in the community, flattened, labelled by its initiative —
  // the picker is a list of destinations, and the initiative is context on
  // each rather than a second choice to make first.
  const projects = useMemo(
    () =>
      initiatives.flatMap((initiative) =>
        initiative.projects.map((project) => ({
          ...project,
          initiativeName: initiative.name,
        }))
      ),
    [initiatives]
  );
  const statuses = useMemo(
    () => projects.find((project) => project.id === binding.project_id)?.statuses ?? [],
    [projects, binding.project_id]
  );

  const busy = !settled || importBlueprint.isPending || upsert.isPending || remove.isPending;

  // Each stream's card is a landmark named by its own title, so a screen
  // reader announces which stream a control belongs to rather than reading
  // four identical sets of pickers.
  const titleId = `intake-stream-${stream}`;

  return (
    <Card className="shadow-sm" role="region" aria-labelledby={titleId}>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle id={titleId}>{t(`streams.${stream}.title`)}</CardTitle>
            <CardDescription>{t(`streams.${stream}.description`)}</CardDescription>
          </div>
          {binding.project_id === null ? (
            <Badge variant="outline">{t("stream.notSetUp")}</Badge>
          ) : binding.project_archived ? (
            // Archived content takes no writes, so this stream receives
            // nothing however its own switch is set. Say that, rather than
            // "Receiving".
            <Badge variant="destructive">{t("stream.destinationArchived")}</Badge>
          ) : (
            <Badge variant={binding.enabled ? "default" : "secondary"}>
              {binding.enabled ? t("stream.receiving") : t("stream.paused")}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {binding.project_id === null ? (
          <div className="space-y-3">
            <p className="text-muted-foreground text-sm">{t("stream.setUpHelp")}</p>
            <div className="flex flex-wrap items-end gap-2">
              <div className="space-y-2">
                <Label htmlFor={`initiative-${stream}`}>{t("stream.initiativeLabel")}</Label>
                <Select value={initiativeId} onValueChange={setInitiativeId} disabled={busy}>
                  <SelectTrigger id={`initiative-${stream}`} className="w-64">
                    <SelectValue placeholder={t("stream.initiativePlaceholder")} />
                  </SelectTrigger>
                  <SelectContent>
                    {initiatives.map((initiative) => (
                      <SelectItem key={initiative.id} value={String(initiative.id)}>
                        {initiative.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button
                disabled={busy || !initiativeId}
                onClick={() =>
                  importBlueprint.mutate({ stream, initiativeId: Number(initiativeId) })
                }
              >
                {t("stream.setUpForMe")}
              </Button>
            </div>
            <div className="space-y-2 border-t pt-4">
              <Label htmlFor={`project-${stream}`}>{t("stream.existingProjectLabel")}</Label>
              <Select
                value=""
                disabled={busy || projects.length === 0}
                onValueChange={(value) =>
                  upsert.mutate({ stream, body: { project_id: Number(value), enabled: true } })
                }
              >
                <SelectTrigger id={`project-${stream}`} className="max-w-md">
                  <SelectValue placeholder={t("stream.existingProjectPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {projects.map((project) => (
                    <SelectItem key={project.id} value={String(project.id)}>
                      {project.initiativeName} › {project.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor={`bound-project-${stream}`}>{t("stream.landsInLabel")}</Label>
              <Select
                value={String(binding.project_id)}
                disabled={busy}
                onValueChange={(value) =>
                  upsert.mutate({
                    stream,
                    body: { project_id: Number(value), enabled: binding.enabled },
                  })
                }
              >
                <SelectTrigger id={`bound-project-${stream}`} className="max-w-md">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {/* An archived project is not offered as a destination, so
                      the one already bound has to name itself or the control
                      would render blank. */}
                  {binding.project_archived && (
                    <SelectItem value={String(binding.project_id)} disabled>
                      {t("stream.archivedOption", { name: binding.project_name ?? "" })}
                    </SelectItem>
                  )}
                  {projects.map((project) => (
                    <SelectItem key={project.id} value={String(project.id)}>
                      {project.initiativeName} › {project.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {binding.project_archived ? (
                <p className="text-destructive text-sm">{t("stream.archivedNote")}</p>
              ) : (
                /* Repointing starts fresh in the new project: an incident still
                   open in the old one stays where the work on it is. */
                <p className="text-muted-foreground text-xs">{t("stream.repointNote")}</p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor={`status-${stream}`}>{t("stream.landingStatusLabel")}</Label>
              <Select
                value={binding.default_status_id ? String(binding.default_status_id) : NONE}
                disabled={busy || statuses.length === 0}
                onValueChange={(value) =>
                  upsert.mutate({
                    stream,
                    body: {
                      project_id: binding.project_id as number,
                      default_status_id: value === NONE ? null : Number(value),
                      enabled: binding.enabled,
                    },
                  })
                }
              >
                <SelectTrigger id={`status-${stream}`} className="max-w-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>{t("stream.landingStatusDefault")}</SelectItem>
                  {statuses.map((status) => (
                    <SelectItem key={status.id} value={String(status.id)}>
                      {status.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-center gap-3 border-t pt-4">
              <Switch
                id={`enabled-${stream}`}
                checked={binding.enabled}
                disabled={busy}
                onCheckedChange={(checked) =>
                  upsert.mutate({
                    stream,
                    body: {
                      project_id: binding.project_id as number,
                      default_status_id: binding.default_status_id,
                      enabled: Boolean(checked),
                    },
                  })
                }
              />
              <Label htmlFor={`enabled-${stream}`}>{t("stream.enabledLabel")}</Label>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-4">
              <p className="text-muted-foreground text-sm">
                {binding.last_case_at
                  ? t("stream.lastCase", { when: formatDateTime(binding.last_case_at) })
                  : t("stream.noCasesYet")}
              </p>
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => setUnbinding(true)}>
                {t("stream.unbind")}
              </Button>
            </div>
          </div>
        )}

        <ConfirmDialog
          open={unbinding}
          onOpenChange={setUnbinding}
          title={t("stream.unbindTitle")}
          description={t("stream.unbindBody")}
          confirmLabel={t("stream.unbindConfirm")}
          onConfirm={() => remove.mutate(stream)}
        />
      </CardContent>
    </Card>
  );
};
