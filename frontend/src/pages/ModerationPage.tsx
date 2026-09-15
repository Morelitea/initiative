/**
 * A community's moderation: what was reported, and what was done about it.
 *
 * Not a board. Each report is one thing to look at and decide, so the page is
 * a list with the outcomes as the actions — there is no status to drag between
 * and nothing to assign. Settled reports stay, on their own tab, because "what
 * did we do about this" is the question the row exists to answer.
 *
 * Who may see any of it is the database's decision: the tables admit the
 * people who already reach every item in the initiative, plus guild admins. A
 * reader who is not one of them gets an empty list, which is the same answer
 * they get for any content they are not in.
 */

import { useParams } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ModerationReportRead, ReportOutcome } from "@/api/generated/initiativeAPI.schemas";
import { ReportOutcome as Outcome } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useModerationReports, useSettleReport } from "@/hooks/useModeration";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { formatDateTime } from "@/lib/formatDate";

/** The outcomes, in the order a moderator usually reaches for them. */
const OUTCOMES: ReportOutcome[] = [
  Outcome.dismissed,
  Outcome.content_removed,
  Outcome.member_warned,
  Outcome.escalated,
];

export const ModerationPage = () => {
  const { t } = useTranslation(["moderation", "common"]);
  const guildId = useActiveGuildId();
  const { initiativeId } = useParams({ strict: false }) as { initiativeId?: string };
  const initiative = Number(initiativeId);
  const [tab, setTab] = useState<"open" | "settled">("open");

  const { data, isLoading } = useModerationReports(
    { guildId: guildId ?? 0, initiativeId: initiative, settled: tab === "settled" },
    { enabled: Boolean(guildId) && Number.isFinite(initiative) }
  );

  const reports = data?.items ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>
        <p className="text-muted-foreground">{t("subtitle")}</p>
      </div>

      <Tabs value={tab} onValueChange={(v) => setTab(v as "open" | "settled")}>
        <TabsList>
          <TabsTrigger value="open">{t("tabs.open")}</TabsTrigger>
          <TabsTrigger value="settled">{t("tabs.settled")}</TabsTrigger>
        </TabsList>
      </Tabs>

      {isLoading ? (
        <p className="text-muted-foreground text-sm">{t("common:loading")}</p>
      ) : reports.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          {tab === "open" ? t("empty.open") : t("empty.settled")}
        </p>
      ) : (
        <div className="space-y-4">
          {reports.map((report) => (
            <ReportCard
              key={report.id}
              report={report}
              guildId={guildId ?? 0}
              initiativeId={initiative}
            />
          ))}
        </div>
      )}
    </div>
  );
};

interface ReportCardProps {
  report: ModerationReportRead;
  guildId: number;
  initiativeId: number;
}

const ReportCard = ({ report, guildId, initiativeId }: ReportCardProps) => {
  const { t } = useTranslation("moderation");
  const [note, setNote] = useState("");

  const settle = useSettleReport(guildId, initiativeId, {
    onSuccess: () => toast.success(t("settledToast")),
    onError: (err) => toast.error(getErrorMessage(err, "moderation:settleError")),
  });

  // Bound once: the schema makes it optional as well as nullable, and the
  // rendered key has to know it is neither.
  const settledAs = report.outcome ?? null;
  const open = settledAs === null;

  return (
    <Card className="shadow-sm" role="region" aria-labelledby={`report-${report.id}`}>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle id={`report-${report.id}`}>
              {t(`targets.${report.target_type}`, {
                defaultValue: report.target_type,
              })}
            </CardTitle>
            <CardDescription>
              {t("reportedCount", { count: report.reporter_count })} ·{" "}
              {t(`reasons.${report.reason}`)} · {formatDateTime(report.reported_at)}
            </CardDescription>
          </div>
          {settledAs === null ? (
            <Badge variant="outline">{t("open")}</Badge>
          ) : (
            <Badge variant="secondary">{t(`outcomes.${settledAs}`)}</Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {report.details.length > 0 && (
          <div className="space-y-2">
            {/* Unattributed on purpose: the count is what a decision rests on,
                and reporting stays confidential inside the community. */}
            <p className="font-medium text-sm">{t("whatTheySaid")}</p>
            {report.details.map((detail, i) => (
              // A real key would mean serving a per-reporter id, which is the
              // one thing this payload withholds; the list is read-only and
              // append-only, so the index is stable.
              // biome-ignore lint/suspicious/noArrayIndexKey: no id is served here
              <p key={`${report.id}-${i}`} className="rounded-md bg-muted px-3 py-2 text-sm">
                {detail}
              </p>
            ))}
          </div>
        )}

        {open ? (
          <div className="space-y-3 border-t pt-4">
            {/* Review the thing where it lives — this page decides, it does not
                act on content. */}
            <p className="text-muted-foreground text-sm">{t("reviewElsewhere")}</p>
            <Textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t("notePlaceholder")}
              rows={2}
            />
            <div className="flex flex-wrap gap-2">
              {OUTCOMES.map((outcome) => (
                <Button
                  key={outcome}
                  variant={outcome === Outcome.escalated ? "destructive" : "outline"}
                  size="sm"
                  disabled={settle.isPending}
                  onClick={() =>
                    settle.mutate({
                      reportId: report.id,
                      body: { outcome, note: note.trim() || null },
                    })
                  }
                >
                  {t(`outcomes.${outcome}`)}
                </Button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-1 border-t pt-4 text-muted-foreground text-sm">
            {report.note && <p>{report.note}</p>}
            <p>
              {t("settledAt", {
                when: report.decided_at ? formatDateTime(report.decided_at) : "",
              })}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
