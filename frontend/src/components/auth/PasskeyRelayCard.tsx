/**
 * The card an app sends a phone's browser to.
 *
 * A passkey belongs to the deployment's domain and the browser is what decides
 * which domain it is in, so an app that cannot hold that conversation itself
 * opens this page instead. It is asked for one thing, and what it gets back is
 * the way back to the app.
 */
import { KeyRound } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { passkeyFailureMessage } from "@/lib/passkeyFailure";
import { signInWithPasskey } from "@/lib/passkeys";

export interface PasskeyRelayCardProps {
  /** What to call the phone the app is running on, for the sign-in record. */
  deviceName: string;
  /** The app's challenge, which the code handed back to it is bound to. */
  codeChallenge: string;
}

export const PasskeyRelayCard = ({ deviceName, codeChallenge }: PasskeyRelayCardProps) => {
  const { t } = useTranslation(["auth", "common", "errors"]);
  const [busy, setBusy] = useState(false);
  // The ceremony is done and the app has been handed the way back.
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Nothing starts on its own here: a prompt wants a press behind it.
  const handleSignIn = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await signInWithPasskey({ mobile: true, deviceName, codeChallenge });
      if (!result.redirect_to) {
        setError(t("auth:login.passkeyFailed"));
        return;
      }
      setDone(true);
      window.location.assign(result.redirect_to);
    } catch (err) {
      const message = passkeyFailureMessage(err, t);
      if (message) setError(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="w-full max-w-md shadow-lg">
      <CardHeader>
        <CardTitle>{t("auth:login.passkeyRelayTitle")}</CardTitle>
        <CardDescription>{t("auth:login.passkeyRelaySubtitle")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Button
          className="w-full"
          type="button"
          disabled={busy}
          onClick={() => void handleSignIn()}
        >
          <KeyRound className="h-4 w-4" />
          {busy ? t("auth:login.passkeyWorking") : t("auth:login.passkeyContinue")}
        </Button>
        {done ? (
          <p className="text-muted-foreground text-sm">{t("auth:login.passkeyReturnToApp")}</p>
        ) : null}
        {error ? <p className="text-destructive text-sm">{error}</p> : null}
      </CardContent>
    </Card>
  );
};
