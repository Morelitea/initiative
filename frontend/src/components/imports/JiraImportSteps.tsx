import { AlertTriangle, ExternalLink, Loader2 } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useCancelImportJobApiV1GGuildIdImportsJobsJobIdDelete,
  useConnectAtlassianApiV1GGuildIdImportsAtlassianConnectPost,
  useGetImportJobApiV1GGuildIdImportsJobsJobIdGet,
  useStartJiraImportApiV1GGuildIdImportsAtlassianJiraPost,
} from "@/api/generated/imports/imports";
import type { AtlassianJiraProject, ImportJobRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { getErrorMessage, messageForCode } from "@/lib/errorMessage";
import { formatBytes } from "@/lib/fileUtils";

/** Where somebody makes the token the connect step asks for. */
const API_TOKEN_URL = "https://id.atlassian.com/manage-profile/security/api-tokens";

const FETCH_POLL_MS = 2000;

/** Statuses a fetch is still working through. Anything else is an answer:
 * ``staged`` is ready for review, the rest are how it ended. */
const FETCHING = new Set(["queued", "fetching"]);

/** What the site was reached with. Held in memory for the length of the
 * wizard and sent again when the import starts — the job row is what keeps
 * it from there, and nothing here writes it anywhere. */
export interface JiraCredentials {
  site_url: string;
  email: string;
  api_token: string;
}

export interface JiraConnection {
  credentials: JiraCredentials;
  projects: AtlassianJiraProject[];
}

/** The plan's ``atlassian`` block. Declared here for the same reason
 * ``PlanPerson`` is: a job's plan crosses the wire as a free-form object. */
export interface AtlassianPlanSummary {
  projects?: number;
  tasks?: number;
  dropped_nodes?: number;
  skipped_issues?: number;
  unreadable_projects?: string[];
  links?: number;
  links_outside_selection?: number;
  properties?: Array<{ name: string; type: string; issue_count: number }>;
  dropped_fields?: string[];
  sprints?: number;
  sprint_calendars?: number;
  sprints_undated?: number;
  sprints_skipped?: string | null;
  comments?: number;
  comments_restricted?: number;
  images?: number;
  image_bytes?: number;
  images_oversize?: number;
  images_unreadable?: number;
  other_attachments?: number;
}

export function atlassianSummary(job: ImportJobRead | null | undefined): AtlassianPlanSummary {
  const plan = job?.plan as { atlassian?: AtlassianPlanSummary } | null | undefined;
  return plan?.atlassian ?? {};
}

// ---------------------------------------------------------------------------
// Connect
// ---------------------------------------------------------------------------

export interface JiraConnectStepProps {
  onConnected: (connection: JiraConnection) => void;
}

/** The site, the account, and a token for it — proved by using it. The
 * answer is also the list of what the token can see, so connecting and
 * looking around are one request. */
export function JiraConnectStep({ onConnected }: JiraConnectStepProps) {
  const { t } = useTranslation("imports");
  const guildId = useActiveGuildId();
  const connect = useConnectAtlassianApiV1GGuildIdImportsAtlassianConnectPost();
  const [siteUrl, setSiteUrl] = useState("");
  const [email, setEmail] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      const response = await connect.mutateAsync({
        guildId,
        data: { site_url: siteUrl.trim(), email: email.trim(), api_token: apiToken },
      });
      if (!response.jira?.available) {
        setError(
          messageForCode(response.jira?.reason ?? null, "imports:wizard.jira.connect.noJira")
        );
        return;
      }
      onConnected({
        // The site as the server normalised it — what the import will call.
        credentials: { site_url: response.site_url, email: email.trim(), api_token: apiToken },
        projects: response.jira.projects ?? [],
      });
    } catch (err) {
      setError(getErrorMessage(err, "imports:wizard.jira.connect.failed"));
    }
  };

  const ready = siteUrl.trim() !== "" && email.trim() !== "" && apiToken !== "";

  return (
    <form className="space-y-4" onSubmit={(event) => void handleSubmit(event)}>
      <div className="space-y-2">
        <Label htmlFor="jira-site">{t("wizard.jira.connect.siteLabel")}</Label>
        <Input
          id="jira-site"
          value={siteUrl}
          placeholder={t("wizard.jira.connect.sitePlaceholder")}
          autoComplete="url"
          onChange={(event) => setSiteUrl(event.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="jira-email">{t("wizard.jira.connect.emailLabel")}</Label>
        <Input
          id="jira-email"
          type="email"
          value={email}
          autoComplete="email"
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="jira-token">{t("wizard.jira.connect.tokenLabel")}</Label>
        <Input
          id="jira-token"
          type="password"
          value={apiToken}
          autoComplete="off"
          onChange={(event) => setApiToken(event.target.value)}
        />
        <a
          href={API_TOKEN_URL}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-primary text-xs hover:underline"
        >
          {t("wizard.jira.connect.tokenLink")}
          <ExternalLink className="h-3 w-3" />
        </a>
      </div>
      <p className="text-muted-foreground text-xs">{t("wizard.jira.connect.note")}</p>
      {error && <p className="text-destructive text-sm">{error}</p>}
      <Button type="submit" className="w-full" disabled={!ready || connect.isPending}>
        {connect.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
        {t("wizard.jira.connect.submit")}
      </Button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Choose
// ---------------------------------------------------------------------------

export interface JiraChooseStepProps {
  connection: JiraConnection;
  initiatives: Array<{ id: number; name: string }>;
  onStarted: (job: ImportJobRead) => void;
}

/** Which projects, into which initiative, and whether their comments and
 * images come too. Starting reads nothing yet — it queues the job that
 * does. */
export function JiraChooseStep({ connection, initiatives, onStarted }: JiraChooseStepProps) {
  const { t } = useTranslation("imports");
  const guildId = useActiveGuildId();
  const start = useStartJiraImportApiV1GGuildIdImportsAtlassianJiraPost();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [initiativeId, setInitiativeId] = useState<string>(
    initiatives.length === 1 ? String(initiatives[0].id) : ""
  );
  const [includeComments, setIncludeComments] = useState(true);
  const [includeAttachments, setIncludeAttachments] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { projects } = connection;
  const allSelected = projects.length > 0 && selected.size === projects.length;

  const toggle = (key: string, on: boolean) => {
    setSelected((current) => {
      const next = new Set(current);
      if (on) {
        next.add(key);
      } else {
        next.delete(key);
      }
      return next;
    });
  };

  const handleStart = async () => {
    setError(null);
    try {
      const job = await start.mutateAsync({
        guildId,
        data: {
          ...connection.credentials,
          initiative_id: Number(initiativeId),
          // In the order the site listed them, whatever order they were ticked.
          project_keys: projects.map((p) => p.key).filter((key) => selected.has(key)),
          include_comments: includeComments,
          include_attachments: includeAttachments,
        },
      });
      onStarted(job);
    } catch (err) {
      setError(getErrorMessage(err, "imports:wizard.jira.choose.failed"));
    }
  };

  if (projects.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("wizard.jira.choose.noProjects")}</p>;
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label>{t("wizard.jira.choose.projectsLabel")}</Label>
          {projects.length > 1 && (
            <Button
              type="button"
              variant="link"
              size="sm"
              className="h-auto p-0 text-xs"
              onClick={() =>
                setSelected(allSelected ? new Set() : new Set(projects.map((p) => p.key)))
              }
            >
              {allSelected ? t("wizard.jira.choose.selectNone") : t("wizard.jira.choose.selectAll")}
            </Button>
          )}
        </div>
        <ul className="max-h-60 space-y-1 overflow-y-auto rounded-lg border p-2">
          {projects.map((project) => {
            const id = `jira-project-${project.key}`;
            return (
              <li key={project.key} className="flex items-center gap-2 rounded px-1 py-1.5">
                <Checkbox
                  id={id}
                  checked={selected.has(project.key)}
                  onCheckedChange={(checked) => toggle(project.key, checked === true)}
                />
                <Label htmlFor={id} className="flex flex-1 items-baseline gap-2 font-normal">
                  <span className="text-sm">{project.name}</span>
                  <span className="font-mono text-muted-foreground text-xs">{project.key}</span>
                  <span className="ml-auto text-muted-foreground text-xs">
                    {project.issue_count == null
                      ? t("wizard.jira.choose.notCounted")
                      : t("wizard.jira.choose.issues", { count: project.issue_count })}
                  </span>
                </Label>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="space-y-2">
        <Label htmlFor="jira-initiative">{t("wizard.choose.initiativeLabel")}</Label>
        <Select value={initiativeId} onValueChange={setInitiativeId}>
          <SelectTrigger id="jira-initiative">
            <SelectValue placeholder={t("wizard.choose.initiativePlaceholder")} />
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

      <div className="space-y-3 rounded-lg border p-3">
        <div className="flex items-center justify-between gap-3">
          <Label htmlFor="jira-comments" className="font-normal text-sm">
            {t("wizard.jira.choose.includeComments")}
          </Label>
          <Switch
            id="jira-comments"
            checked={includeComments}
            onCheckedChange={setIncludeComments}
          />
        </div>
        <div className="flex items-center justify-between gap-3">
          <Label htmlFor="jira-attachments" className="font-normal text-sm">
            {t("wizard.jira.choose.includeAttachments")}
          </Label>
          <Switch
            id="jira-attachments"
            checked={includeAttachments}
            onCheckedChange={setIncludeAttachments}
          />
        </div>
      </div>

      <p className="text-muted-foreground text-xs">{t("wizard.jira.choose.note")}</p>
      {error && <p className="text-destructive text-sm">{error}</p>}
      <Button
        className="w-full"
        disabled={selected.size === 0 || initiativeId === "" || start.isPending}
        onClick={() => void handleStart()}
      >
        {t("wizard.jira.choose.submit")}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Fetching
// ---------------------------------------------------------------------------

export interface JiraFetchingStepProps {
  jobId: number;
  /** The site has been read and the job is waiting for review. */
  onStaged: (job: ImportJobRead) => void;
  /** The fetch is over without a bundle — cancelled, or failed and dismissed. */
  onStopped: () => void;
}

/** The worker reading the site. Counts climb as each project is read; the
 * job keeps going if the dialog is closed, and the wizard picks it up again
 * when it is reopened. */
export function JiraFetchingStep({ jobId, onStaged, onStopped }: JiraFetchingStepProps) {
  const { t } = useTranslation("imports");
  const guildId = useActiveGuildId();
  const cancel = useCancelImportJobApiV1GGuildIdImportsJobsJobIdDelete();
  const jobQuery = useGetImportJobApiV1GGuildIdImportsJobsJobIdGet(guildId, jobId, {
    query: {
      refetchInterval: (query) =>
        FETCHING.has(query.state.data?.status ?? "queued") ? FETCH_POLL_MS : false,
    },
  });
  const job = jobQuery.data;

  useEffect(() => {
    if (job?.status === "staged") {
      onStaged(job);
    }
  }, [job, onStaged]);

  const handleCancel = async () => {
    try {
      await cancel.mutateAsync({ guildId, jobId });
    } catch {
      // Already over; stopping is still the right answer.
    }
    onStopped();
  };

  if (job && !FETCHING.has(job.status) && job.status !== "staged") {
    return (
      <div className="space-y-4">
        <div className="flex items-start gap-2 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
          <p>
            {job.status === "failed"
              ? messageForCode(job.error, "imports:wizard.jira.fetch.failed")
              : t("wizard.jira.fetch.stopped")}
          </p>
        </div>
        <Button className="w-full" variant="outline" onClick={onStopped}>
          {t("wizard.jira.fetch.startOver")}
        </Button>
      </div>
    );
  }

  const summary = atlassianSummary(job);
  return (
    <div className="flex flex-col items-center gap-3 py-6 text-center">
      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      <p className="font-medium text-sm">{t("wizard.jira.fetch.title")}</p>
      <p className="text-muted-foreground text-xs">
        {t("wizard.jira.fetch.progress", {
          projects: summary.projects ?? 0,
          tasks: summary.tasks ?? 0,
        })}
      </p>
      <p className="text-muted-foreground text-xs">{t("wizard.jira.fetch.note")}</p>
      <Button variant="outline" size="sm" onClick={() => void handleCancel()}>
        {t("wizard.jira.fetch.cancel")}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Review
// ---------------------------------------------------------------------------

/** What the fetch found, before anything is written: what will arrive, and —
 * said as plainly — what will not. */
export function JiraReviewSummary({ job }: { job: ImportJobRead }) {
  const { t } = useTranslation("imports");
  const summary = atlassianSummary(job);
  const properties = summary.properties ?? [];

  const arriving = [
    t("wizard.jira.review.tasks", { count: summary.tasks ?? 0, projects: summary.projects ?? 0 }),
    (summary.links ?? 0) > 0 ? t("wizard.jira.review.links", { count: summary.links }) : null,
    (summary.comments ?? 0) > 0
      ? t("wizard.jira.review.comments", { count: summary.comments })
      : null,
    (summary.images ?? 0) > 0
      ? t("wizard.jira.review.images", {
          count: summary.images,
          size: formatBytes(summary.image_bytes ?? 0),
        })
      : null,
    (summary.sprint_calendars ?? 0) > 0
      ? t("wizard.jira.review.sprints", {
          count: (summary.sprints ?? 0) - (summary.sprints_undated ?? 0),
          calendars: summary.sprint_calendars,
        })
      : null,
  ].filter((line): line is string => line !== null);

  const leftBehind = [
    (summary.unreadable_projects?.length ?? 0) > 0
      ? t("wizard.jira.review.unreadableProjects", {
          keys: (summary.unreadable_projects ?? []).join(", "),
        })
      : null,
    summary.sprints_skipped && (summary.sprints ?? 0) > 0
      ? t("wizard.jira.review.sprintsSkipped", {
          count: summary.sprints,
          reason: messageForCode(summary.sprints_skipped, "imports:wizard.jira.review.noCalendar"),
        })
      : null,
    (summary.sprints_undated ?? 0) > 0 && !summary.sprints_skipped
      ? t("wizard.jira.review.sprintsUndated", { count: summary.sprints_undated })
      : null,
    (summary.links_outside_selection ?? 0) > 0
      ? t("wizard.jira.review.linksOutside", { count: summary.links_outside_selection })
      : null,
    (summary.comments_restricted ?? 0) > 0
      ? t("wizard.jira.review.commentsRestricted", { count: summary.comments_restricted })
      : null,
    (summary.images_oversize ?? 0) + (summary.images_unreadable ?? 0) > 0
      ? t("wizard.jira.review.imagesSkipped", {
          count: (summary.images_oversize ?? 0) + (summary.images_unreadable ?? 0),
        })
      : null,
    (summary.other_attachments ?? 0) > 0
      ? t("wizard.jira.review.otherAttachments", { count: summary.other_attachments })
      : null,
    (summary.dropped_fields?.length ?? 0) > 0
      ? t("wizard.jira.review.droppedFields", {
          fields: (summary.dropped_fields ?? []).join(", "),
        })
      : null,
    (summary.skipped_issues ?? 0) > 0
      ? t("wizard.jira.review.skippedIssues", { count: summary.skipped_issues })
      : null,
  ].filter((line): line is string => line !== null);

  return (
    <div className="space-y-4">
      <ul className="space-y-1 rounded-lg border p-3 text-sm">
        {arriving.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>

      {properties.length > 0 && (
        <div className="space-y-1">
          <p className="font-medium text-sm">{t("wizard.jira.review.propertiesTitle")}</p>
          <ul className="max-h-40 space-y-0.5 overflow-y-auto rounded-lg border p-2 text-xs">
            {properties.map((property) => (
              <li key={property.name} className="flex justify-between gap-2">
                <span>{property.name}</span>
                <span className="text-muted-foreground">
                  {t("wizard.jira.review.propertyCount", { count: property.issue_count })}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {leftBehind.length > 0 && (
        <div className="space-y-1">
          <p className="font-medium text-sm">{t("wizard.jira.review.leftBehindTitle")}</p>
          <ul className="space-y-1">
            {leftBehind.map((line) => (
              <li key={line} className="flex items-start gap-2 text-muted-foreground text-xs">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
