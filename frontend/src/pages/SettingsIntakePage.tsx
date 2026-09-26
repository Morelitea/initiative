/**
 * Where this deployment's operations work lands (platform settings → Intake).
 *
 * Who to contact comes first, and stands on its own: a deployment that routes
 * nothing anywhere still tells people whom to write to.
 *
 * Then two levels of decision, in the order an owner makes them: name the
 * community that receives operations work, then say which project each stream
 * lands in. Nothing below the first is offered until it is answered, because
 * every id in it belongs to that community.
 *
 * Each stream offers the same two routes: import the blueprint, which produces
 * a ready-made project, or point at a project the team already has. Both end in
 * the same binding — the blueprint is a convenience, not a different mechanism.
 */

import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  IntakeBindingRead,
  IntakeInitiativeOption,
  IntakeSettingsRead,
  IntakeStream,
} from "@/api/generated/initiativeAPI.schemas";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
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
  useUpdateIntakeGeneralContact,
  useUpdateIntakeStreamContact,
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
    isError: settingsFailed,
    refetch: refetchSettings,
  } = useIntakeSettings({ enabled: isOwner });
  const {
    data: options,
    isFetching: optionsFetching,
    isError: optionsFailed,
    refetch: refetchOptions,
  } = useIntakeOptions({ enabled: isOwner });
  // Searched on the server while the picker is open, rather than every
  // community on the deployment loaded up front.
  const [guildSearch, setGuildSearch] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const guildsQuery = usePlatformGuilds(
    { search: guildSearch || undefined, sort_by: "name", page_size: 25 },
    { enabled: isOwner && pickerOpen }
  );

  // The two reads describe one community between them — where each stream
  // lands, and what it could land in — so the page acts on both or neither.
  const failed = settingsFailed || optionsFailed;
  const settled = !failed && !settingsFetching && !optionsFetching;

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
              refetchSettings();
              refetchOptions();
            }}
          >
            {t("loadFailed.retry")}
          </Button>
        </CardContent>
      </Card>
    );
  }

  const boundGuildId = settings?.operations_guild_id ?? null;

  return (
    <div className="space-y-6">
      {settings ? <ContactsCard settings={settings} settled={settled} /> : null}

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("guild.title")}</CardTitle>
          <CardDescription>{t("guild.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Label>{t("guild.label")}</Label>
          <AsyncCombobox
            className="max-w-md"
            aria-label={t("guild.label")}
            value={boundGuildId === null ? NONE : String(boundGuildId)}
            selectedLabel={
              boundGuildId === null ? t("guild.none") : (settings?.operations_guild_name ?? null)
            }
            items={[
              { value: NONE, label: t("guild.none") },
              ...(guildsQuery.data?.items ?? []).map((guild) => ({
                value: String(guild.id),
                label: guild.name,
              })),
            ]}
            onSearchChange={setGuildSearch}
            onOpenChange={setPickerOpen}
            loading={guildsQuery.isFetching}
            placeholder={t("guild.placeholder")}
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
          />
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

/**
 * Who a notice tells somebody to contact: one general address, and one per
 * stream. A stream left blank uses the general address — never another
 * stream's — and with neither set the notice names nobody.
 */
const ContactsCard = ({
  settings,
  settled,
}: {
  settings: IntakeSettingsRead;
  settled: boolean;
}) => {
  const { t } = useTranslation("intake");
  const streams = useMemo(
    () => settings.bindings.map((binding) => binding.stream as IntakeStream),
    [settings.bindings]
  );
  const saved = useMemo(
    () => ({
      general: settings.general_contact_email ?? "",
      streams: Object.fromEntries(
        streams.map((stream) => [stream, settings.contact_emails?.[stream] ?? ""])
      ) as Record<IntakeStream, string>,
    }),
    [settings, streams]
  );
  const [draft, setDraft] = useState(saved);
  // A save, or another tab's, replaces what the form started from.
  useEffect(() => setDraft(saved), [saved]);

  const updateGeneral = useUpdateIntakeGeneralContact();
  const updateStream = useUpdateIntakeStreamContact();
  const saving = updateGeneral.isPending || updateStream.isPending;
  const changed =
    draft.general.trim() !== saved.general ||
    streams.some((stream) => draft.streams[stream].trim() !== saved.streams[stream]);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const email = (value: string) => value.trim() || null;
    try {
      if (draft.general.trim() !== saved.general) {
        await updateGeneral.mutateAsync({ email: email(draft.general) });
      }
      for (const stream of streams) {
        if (draft.streams[stream].trim() !== saved.streams[stream]) {
          await updateStream.mutateAsync({ stream, body: { email: email(draft.streams[stream]) } });
        }
      }
      toast.success(t("contacts.saved"));
    } catch (err) {
      toast.error(getErrorMessage(err, "intake:contacts.saveError"));
    }
  };

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("contacts.title")}</CardTitle>
        <CardDescription>{t("contacts.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="max-w-md space-y-4" onSubmit={onSubmit}>
          <div className="space-y-2">
            <Label htmlFor="intake-contact-general">{t("contacts.generalLabel")}</Label>
            <Input
              id="intake-contact-general"
              type="email"
              value={draft.general}
              placeholder={t("contacts.generalPlaceholder")}
              disabled={!settled || saving}
              onChange={(event) => setDraft({ ...draft, general: event.target.value })}
            />
          </div>
          {streams.map((stream) => (
            <div key={stream} className="space-y-2">
              <Label htmlFor={`intake-contact-${stream}`}>{t(`streams.${stream}.title`)}</Label>
              <Input
                id={`intake-contact-${stream}`}
                type="email"
                value={draft.streams[stream]}
                placeholder={t("contacts.streamPlaceholder")}
                disabled={!settled || saving}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    streams: { ...draft.streams, [stream]: event.target.value },
                  })
                }
              />
            </div>
          ))}
          <Button type="submit" disabled={!settled || saving || !changed}>
            {saving ? t("contacts.saving") : t("contacts.save")}
          </Button>
        </form>
      </CardContent>
    </Card>
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
