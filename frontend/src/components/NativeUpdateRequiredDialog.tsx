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

interface NativeUpdateRequiredDialogProps {
  open: boolean;
  /** The server version that requires a newer native app than the one installed. */
  version: string;
  onClose: () => void;
}

/**
 * Shown on native when the server's web bundle requires a newer native shell (APK/IPA) than
 * the one installed — an OTA update can't add native code, so the user must update the app
 * itself. See {@link useNativeUpdate}.
 */
export const NativeUpdateRequiredDialog = ({
  open,
  version,
  onClose,
}: NativeUpdateRequiredDialogProps) => {
  const { t } = useTranslation("guilds");

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("version.nativeUpdateRequiredTitle")}</DialogTitle>
          <DialogDescription>
            {t("version.nativeUpdateRequiredDescription", { version })}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button onClick={onClose}>{t("version.nativeUpdateRequiredAcknowledge")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
