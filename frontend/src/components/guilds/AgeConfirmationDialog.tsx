import { useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
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
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/useAuth";
import { getErrorMessage } from "@/lib/errorMessage";

/**
 * The box a directory Join asks to have ticked, once per account.
 *
 * Asked here, before the join, so the answer is what joins rather than
 * something the server comes back and demands. Once given it is kept on the
 * account, so the second community somebody joins asks nothing.
 *
 * ``onConfirmed`` runs after the confirmation is recorded and the account has
 * been refreshed, which is what the caller resumes its join from.
 */
export const AgeConfirmationDialog = ({
  open,
  onOpenChange,
  onConfirmed,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirmed: () => void;
}) => {
  const { t } = useTranslation(["guilds", "auth", "common"]);
  const { refreshUser } = useAuth();
  const [checked, setChecked] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confirm = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await apiClient.post("/users/me/age-confirmation", { confirmed: true });
      await refreshUser();
      onOpenChange(false);
      setChecked(false);
      onConfirmed();
    } catch (err) {
      setError(getErrorMessage(err, "auth:confirmAge.error"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("auth:confirmAge.title")}</DialogTitle>
          <DialogDescription>{t("guilds:community.ageGateBody")}</DialogDescription>
        </DialogHeader>
        <div className="flex items-start gap-3">
          <Checkbox
            id="community-confirm-age"
            checked={checked}
            onCheckedChange={(value) => setChecked(value === true)}
            disabled={submitting}
          />
          <Label htmlFor="community-confirm-age" className="font-normal leading-snug">
            {t("auth:confirmAge.checkboxLabel")}
          </Label>
        </div>
        {error ? <p className="text-destructive text-sm">{error}</p> : null}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            {t("common:cancel")}
          </Button>
          <Button onClick={() => void confirm()} disabled={!checked || submitting}>
            {submitting ? t("common:submitting") : t("guilds:community.ageGateConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
