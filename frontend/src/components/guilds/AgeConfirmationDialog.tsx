import { useTranslation } from "react-i18next";

import { BirthdateField } from "@/components/auth/BirthdateField";
import { useAgeConfirmation } from "@/components/auth/useAgeConfirmation";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * The age question, asked once, before a directory Join goes through.
 *
 * Asked here rather than after the click, so answering is what joins. Once
 * given it is kept on the account, so the second community somebody joins asks
 * nothing.
 *
 * ``onConfirmed`` runs after the answer is recorded and the account refreshed,
 * which is what the caller resumes its join from.
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
  const { birthdate, setBirthdate, submitting, error, confirm } = useAgeConfirmation(() => {
    onOpenChange(false);
    onConfirmed();
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("auth:confirmAge.title")}</DialogTitle>
          <DialogDescription>{t("guilds:community.ageGateBody")}</DialogDescription>
        </DialogHeader>
        <BirthdateField
          id="community-confirm-age"
          value={birthdate}
          onChange={setBirthdate}
          disabled={submitting}
        />
        <p className="text-muted-foreground text-xs">{t("auth:confirmAge.scopeNote")}</p>
        {error ? <p className="text-destructive text-sm">{error}</p> : null}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            {t("common:cancel")}
          </Button>
          <Button onClick={() => void confirm()} disabled={!birthdate || submitting}>
            {submitting ? t("common:submitting") : t("guilds:community.ageGateConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
