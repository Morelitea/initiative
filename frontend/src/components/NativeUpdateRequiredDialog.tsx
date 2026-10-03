import { Capacitor } from "@capacitor/core";
import { Download } from "lucide-react";
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
import { androidApkUrl, desktopInstallerUrl, RELEASES_URL } from "@/lib/links";
import { detectDesktopOs } from "@/pages/landing/platform";

interface NativeUpdateRequiredDialogProps {
  open: boolean;
  /** The server version that requires a newer native app than the one installed. */
  version: string;
  /** The app version it needs, which names the release holding the download. */
  minNativeVersion?: string;
  onClose: () => void;
}

/** The new app for this device, from the release the bundle's floor names. */
const downloadUrl = (minNativeVersion?: string): string => {
  if (!minNativeVersion) return RELEASES_URL;
  if (Capacitor.getPlatform() !== "electron") return androidApkUrl(minNativeVersion);
  const os = detectDesktopOs();
  return os ? desktopInstallerUrl(minNativeVersion, os) : RELEASES_URL;
};

/**
 * Shown on native when the server's web bundle requires a newer native shell (APK/IPA, or the
 * desktop app) than the one installed — an OTA update can't add native code, so the user must update the app
 * itself. See {@link useNativeUpdate}.
 */
export const NativeUpdateRequiredDialog = ({
  open,
  version,
  minNativeVersion,
  onClose,
}: NativeUpdateRequiredDialogProps) => {
  const { t } = useTranslation("guilds");

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("version.nativeUpdateRequiredTitle")}</DialogTitle>
          <DialogDescription>
            {Capacitor.getPlatform() === "electron"
              ? t("version.nativeUpdateRequiredDescriptionDesktop", { version })
              : t("version.nativeUpdateRequiredDescription", { version })}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("version.nativeUpdateRequiredAcknowledge")}
          </Button>
          <Button asChild>
            <a href={downloadUrl(minNativeVersion)} target="_blank" rel="noopener noreferrer">
              <Download className="h-4 w-4" aria-hidden="true" />
              {t("version.nativeUpdateDownload")}
            </a>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
