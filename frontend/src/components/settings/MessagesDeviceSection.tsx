import { useTranslation } from "react-i18next";

import { DeviceCode } from "@/components/messages/DeviceCode";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useThisDevice } from "@/hooks/useMyMessages";

/**
 * This browser's device code for encrypted messages: the other end of the
 * comparison a new device of this account's, or a safety check, asks for.
 * Nothing is shown where this browser has not been set up for messages.
 */
export const MessagesDeviceSection = () => {
  const { t } = useTranslation("settings");
  const device = useThisDevice();
  if (!device.data) return null;

  return (
    <SettingsSection
      title={t("messagesDevice.title")}
      description={t("messagesDevice.description")}
    >
      <DeviceCode {...device.data} />
    </SettingsSection>
  );
};
