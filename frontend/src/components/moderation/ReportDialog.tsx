/**
 * Report something.
 *
 * The same dialog wherever it is opened — a comment, a notice, a profile — and
 * it never says where the report will go, because that is the server's
 * decision and the reporter has nothing to do with it.
 *
 * What comes back is an acknowledgement and nothing else: not whether somebody
 * had already reported the same thing, not who will read it, and never an
 * outcome. A report is not a conversation with the person who sent it.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ReportReason } from "@/api/generated/initiativeAPI.schemas";
import { ReportReason as Reason } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useFileReport } from "@/hooks/useReport";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

/** The reasons, in the order they are offered. */
const REASONS: ReportReason[] = [
  Reason.harassment,
  Reason.hate,
  Reason.violence,
  Reason.sexual_content,
  Reason.self_harm,
  Reason.illegal,
  Reason.spam,
  Reason.misinformation,
  Reason.other,
];

export interface ReportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** A `SearchEntityType` or a `PlatformReportTarget` value. */
  targetType: string;
  targetId: number;
  /** The community the reporter is standing in, when they are in one. */
  guildId?: number | null;
}

export const ReportDialog = ({
  open,
  onOpenChange,
  targetType,
  targetId,
  guildId,
}: ReportDialogProps) => {
  const { t } = useTranslation(["moderation", "common"]);
  const [reason, setReason] = useState<ReportReason | "">("");
  const [detail, setDetail] = useState("");

  const file = useFileReport({
    onSuccess: () => {
      toast.success(t("report.thanks"));
      onOpenChange(false);
      setReason("");
      setDetail("");
    },
    onError: (err) => toast.error(getErrorMessage(err, "moderation:report.error")),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("report.title")}</DialogTitle>
          <DialogDescription>{t("report.description")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="report-reason">{t("report.reasonLabel")}</Label>
            <Select value={reason} onValueChange={(v) => setReason(v as ReportReason)}>
              <SelectTrigger id="report-reason">
                <SelectValue placeholder={t("report.reasonPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {REASONS.map((value) => (
                  <SelectItem key={value} value={value}>
                    {t(`reasons.${value}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="report-detail">{t("report.detailLabel")}</Label>
            <Textarea
              id="report-detail"
              value={detail}
              onChange={(e) => setDetail(e.target.value)}
              placeholder={t("report.detailPlaceholder")}
              rows={4}
              maxLength={4000}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common:cancel")}
          </Button>
          <Button
            disabled={!reason || file.isPending}
            onClick={() =>
              reason &&
              file.mutate({
                target_type: targetType,
                target_id: targetId,
                reason,
                detail: detail.trim() || null,
                guild_id: guildId ?? null,
              })
            }
          >
            {t("report.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
