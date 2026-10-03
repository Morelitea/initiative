/**
 * Who to write to, where there is no form.
 *
 * What a filing surface shows when the deployment has nothing set up to
 * receive that kind of ticket — or the reader may not file one from where they
 * are — but has said who to contact. An address and a way to use it, and
 * nothing to fill in.
 */

import { Mail } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export interface ContactDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The address to write to. */
  contact: string;
}

export const ContactDialog = ({ open, onOpenChange, contact }: ContactDialogProps) => {
  const { t } = useTranslation(["intake", "common"]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("contact.title")}</DialogTitle>
          <DialogDescription>{t("contact.description")}</DialogDescription>
        </DialogHeader>
        <p className="break-all font-medium text-sm">{contact}</p>
        <DialogFooter>
          <CopyButton value={contact} label={t("contact.copy")} />
          <Button asChild>
            <a href={`mailto:${contact}`}>
              <Mail className="h-4 w-4" aria-hidden="true" />
              {t("contact.write")}
            </a>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
