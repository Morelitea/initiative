import { KeyRound } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { DeviceCode } from "@/components/messages/DeviceCode";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { useAnswerNewDevice, useOwnDeviceWaiting } from "@/hooks/useMyMessages";

/**
 * A device that signed in to this account after this browser did.
 *
 * It is held until somebody here says it is theirs: nothing this browser sends
 * reaches it, and nothing it sends is read, until then. Its code is shown as
 * well as its name: the name is whatever its browser reported, and the
 * pictures are what the new device is showing at the same moment, so the two
 * can be compared. Sending it this account's history is offered in the same
 * answer, ticked already when the device has asked for it.
 */
export const NewDevicePrompt = () => {
  const { t } = useTranslation("messages");
  const waiting = useOwnDeviceWaiting();
  const answer = useAnswerNewDevice();
  const change = waiting.data;
  // Keyed on the device, so a second prompt starts from its own default.
  const [choice, setChoice] = useState<{ deviceId: string; sendHistory: boolean } | null>(null);

  if (!change) return null;
  const sendHistory =
    choice?.deviceId === change.deviceId ? choice.sendHistory : Boolean(change.asked);

  return (
    <section className="space-y-3 border-b bg-muted/40 px-6 py-4">
      <div className="flex items-start gap-2">
        <KeyRound className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="space-y-3">
          <div className="space-y-1">
            <h2 className="font-medium text-sm">{t("newDevice.title")}</h2>
            <p className="max-w-prose text-muted-foreground text-sm">
              {t("newDevice.body", { device: change.label ?? t("newDevice.unknownDevice") })}
            </p>
          </div>
          <DeviceCode
            userId={change.userId}
            fingerprintKey={change.now.fingerprint}
            identityKey={change.now.identityKey}
          />
          <div className="flex items-center gap-2">
            <Checkbox
              id="new-device-history"
              checked={sendHistory}
              onCheckedChange={(checked) =>
                setChoice({ deviceId: change.deviceId, sendHistory: checked === true })
              }
            />
            <Label htmlFor="new-device-history" className="font-normal text-sm">
              {t("newDevice.sendHistory")}
            </Label>
          </div>
        </div>
      </div>
      <div className="flex flex-wrap gap-2 pl-6">
        <Button
          type="button"
          size="sm"
          disabled={answer.isPending}
          onClick={() => answer.mutate({ change, mine: true, sendHistory })}
        >
          {t("newDevice.confirm")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={answer.isPending}
          onClick={() => answer.mutate({ change, mine: false, sendHistory: false })}
        >
          {t("newDevice.remove")}
        </Button>
      </div>
    </section>
  );
};
