/**
 * Asking whoever runs this deployment for help.
 *
 * Only reachable where the community has switched support on — the button
 * shows the FAQ otherwise, so this dialog never has to explain its own
 * absence. Where the request lands is the deployment's own arrangement and is
 * deliberately not named here.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
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
import { Textarea } from "@/components/ui/textarea";
import { FAQ_URL, useAskForHelp } from "@/hooks/useSupport";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

/** Matches the columns behind them, so the field stops where the server would. */
const SUBJECT_MAX = 200;
const BODY_MAX = 5000;

export interface AskForHelpDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  guildId: number;
}

export const AskForHelpDialog = ({ open, onOpenChange, guildId }: AskForHelpDialogProps) => {
  const { t } = useTranslation(["intake", "common"]);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  const ask = useAskForHelp(guildId, {
    onSuccess: () => {
      toast.success(t("help.thanks"));
      onOpenChange(false);
      setSubject("");
      setBody("");
    },
    onError: (err) => toast.error(getErrorMessage(err, "intake:help.error")),
  });

  const ready = subject.trim().length > 0 && body.trim().length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("help.title")}</DialogTitle>
          <DialogDescription>{t("help.description")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="help-subject">{t("help.subjectLabel")}</Label>
            <Input
              id="help-subject"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder={t("help.subjectPlaceholder")}
              maxLength={SUBJECT_MAX}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="help-body">{t("help.bodyLabel")}</Label>
            <Textarea
              id="help-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder={t("help.bodyPlaceholder")}
              rows={6}
              maxLength={BODY_MAX}
            />
          </div>

          {/* The FAQ is still the faster answer for most of what gets asked,
              so it stays one click away from the form rather than only being
              what a community without support offers. */}
          <p className="text-muted-foreground text-xs">
            <a
              href={FAQ_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2 hover:text-foreground"
            >
              {t("help.browseFaq")}
            </a>
          </p>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common:cancel")}
          </Button>
          <Button
            disabled={!ready || ask.isPending}
            onClick={() => ready && ask.mutate({ subject: subject.trim(), body: body.trim() })}
          >
            {t("help.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
