/**
 * Where the deployment's operations work lands in this community (Community
 * settings → Intake).
 *
 * Offered only in the community the platform names to receive operations
 * work, and only to its superadmin: the server answers 404 everywhere else,
 * which is what the settings layout asks before it shows the tab. The platform
 * owner names the community and the contact addresses; which project each
 * stream lands in is decided here.
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
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import {
  useDeleteIntakeBinding,
  useGuildIntake,
  useGuildIntakeOptions,
  useImportIntakeBlueprint,
  useUpsertIntakeBinding,
} from "@/hooks/useGuildIntake";
import { useGuilds } from "@/hooks/useGuilds";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage, getHttpStatus } from "@/lib/errorMessage";
import { formatDateTime } from "@/lib/formatDate";
import { holdsGuildSeat } from "@/lib/permissions";

/** Sentinel for "the project's default status", which a Select cannot express with "". */
const NONE = "none";

export const SettingsGuildIntakePage = () => {
  const { t } = useTranslation("intake");
  const guildId = useActiveGuildId();
  const { activeGuild } = useGuilds();
  const isSeat = holdsGuildSeat(activeGuild);

  const bindings = useGuildIntake(guildId, { enabled: isSeat && guildId > 0 });
  // Asked only once the community has answered that it is the operations
  // community, so a direct visit elsewhere makes one request rather than two.
  const options = useGuildIntakeOptions(guildId, {
    enabled: isSeat && guildId > 0 && bindings.isSuccess,
  });

  // The two reads describe one community between them — where each stream
  // lands, and what it could land in — so the page acts on both or neither.
  const failed = bindings.isError || options.isError;
  const settled = !failed && !bindings.isFetching && !options.isFetching;

  if (!isSeat) {
    return <p className="text-muted-foreground text-sm">{t("community.seatOnly")}</p>;
  }

  if (bindings.isError && getHttpStatus(bindings.error) === 404) {
    return <p className="text-muted-foreground text-sm">{t("community.notOperations")}</p>;
  }

  // A read that failed is a different state from a community that has set
  // nothing up, and says so.
  if (failed) {
    return (
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("loadFailed.title")}</CardTitle>
          <CardDescription>{t("loadFailed.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            variant="outline"
            onClick={() => {
              bindings.refetch();
              options.refetch();
            }}
          >
            {t("loadFailed.retry")}
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h2 className="font-semibold text-xl">{t("community.title")}</h2>
        <p className="text-muted-foreground text-sm">{t("community.description")}</p>
      </div>
      <div className="space-y-4">
        {(bindings.data?.bindings ?? []).map((binding) => (
          <StreamCard
            key={binding.stream}
            guildId={guildId}
            binding={binding}
            initiatives={options.data?.initiatives ?? []}
            settled={settled}
          />
        ))}
      </div>
    </div>
  );
};

interface StreamCardProps {
  guildId: number;
  binding: IntakeBindingRead;
  initiatives: IntakeInitiativeOption[];
  /** Both reads have settled, so bindings and options describe one community. */
  settled: boolean;
}

const StreamCard = ({ guildId, binding, initiatives, settled }: StreamCardProps) => {
  const { t } = useTranslation("intake");
  const stream = binding.stream as IntakeStream;

  const [initiativeId, setInitiativeId] = useState<string>("");
  const [unbinding, setUnbinding] = useState(false);

  const importBlueprint = useImportIntakeBlueprint(guildId, {
    onSuccess: (result) => toast.success(t("stream.createdToast", { name: result.project_name })),
    onError: (err) => toast.error(getErrorMessage(err, "intake:stream.saveError")),
  });
  const upsert = useUpsertIntakeBinding(guildId, {
    onError: (err) => toast.error(getErrorMessage(err, "intake:stream.saveError")),
  });
  const remove = useDeleteIntakeBinding(guildId, {
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
