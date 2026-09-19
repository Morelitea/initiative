import { Link } from "@tanstack/react-router";
import { isAxiosError } from "axios";
import { KeyRound } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { AUTH_FACTOR_REQUIRED_EVENT, type FactorChallengeDetail } from "@/api/client";
import {
  useListPasskeysApiV1AuthPasskeysGet,
  useReadSecondFactorApiV1AuthTotpGet,
} from "@/api/generated/auth/auth";
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
import { useAuth } from "@/hooks/useAuth";
import { useAuthChallenge } from "@/hooks/useAuthChallenge";
import { useServer } from "@/hooks/useServer";
import { getErrorMessage } from "@/lib/errorMessage";
import { describePasskeyPromptError } from "@/lib/passkeys";
import { queryClient } from "@/lib/queryClient";

/**
 * Global handler for a community that requires a factor of the account's own.
 *
 * When any request is refused for want of one (dispatched by the API client as
 * a window event), this asks for it and adds it to the session already open.
 * The requests that were refused are refetched once it succeeds, so the page
 * the person was on fills in behind the dialog rather than needing a reload.
 *
 * Two factors can be asked for, and the event says which: a code from the
 * account's authenticator app, or a passkey. The code branch works on native
 * too — the answer is typed against the live session, which the app holds just
 * as a browser does. The passkey branch does not: the ceremony belongs to the
 * browser the credential is registered to, so the app says where to go instead.
 */
export const SecondFactorStepUpDialog = () => {
  // The array form, so the line a put-down prompt deserves — named by
  // `describePasskeyPromptError` as a fully qualified key — is one `t` accepts.
  const { t } = useTranslation(["auth", "common"]);
  const { stepUpWithFactor, stepUpWithPasskey } = useAuth();
  const { isNativePlatform } = useServer();
  const { challenge, clear, open } = useAuthChallenge<FactorChallengeDetail>(
    AUTH_FACTOR_REQUIRED_EVENT,
    () => true
  );
  const wantsPasskey = challenge?.kind === "passkey";

  const [code, setCode] = useState("");
  const [useRecoveryCode, setUseRecoveryCode] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Only asked once there is something to answer, and only for the factor that
  // was asked for. Both routes are platform-scoped, so neither is itself
  // refused by the community that raised the challenge.
  const statusQuery = useReadSecondFactorApiV1AuthTotpGet({
    query: { enabled: open && !wantsPasskey },
  });
  const passkeyQuery = useListPasskeysApiV1AuthPasskeysGet({
    query: { enabled: open && wantsPasskey && !isNativePlatform },
  });
  // Three states, not two. While the answer is in flight, offer the way in:
  // the refusal that opened this dialog is the common case and an account that
  // can answer is what it assumes. Only a definite "nothing to present with"
  // swaps it for the way to get one — and when the account cannot be read at
  // all, the way in stays but the way to get one is offered beside it, so
  // neither audience is stranded.
  const hasNoFactor = statusQuery.data?.enrolled === false;
  const statusUnknown = statusQuery.isError;
  const hasNoPasskey = passkeyQuery.isSuccess && (passkeyQuery.data.passkeys ?? []).length === 0;
  const passkeysUnknown = passkeyQuery.isError;

  const dismiss = () => {
    clear();
    setCode("");
    setUseRecoveryCode(false);
    setError(null);
  };

  /** What both answers do once the session carries the factor: every query
   *  refused while it did not should ask again, and the dialog is done. */
  const settle = async () => {
    await queryClient.invalidateQueries();
    dismiss();
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const entered = code.trim();
      await stepUpWithFactor(
        useRecoveryCode ? { recoveryCode: entered } : { code: entered.replace(/\s+/g, "") }
      );
      await settle();
    } catch (err) {
      setError(getErrorMessage(err, "auth:factorStepUp.error"));
    } finally {
      setSubmitting(false);
    }
  };

  const presentPasskey = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await stepUpWithPasskey();
      await settle();
    } catch (err) {
      if (isAxiosError(err)) {
        setError(getErrorMessage(err, "auth:factorStepUp.passkeyError"));
      } else {
        // A prompt that produced nothing is the browser's news, not the
        // server's — and one this page put down itself has no line at all.
        const key = describePasskeyPromptError(err);
        setError(key ? t(key) : null);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const passkeyDescription = isNativePlatform
    ? t("factorStepUp.passkeyNative")
    : hasNoPasskey
      ? t("factorStepUp.passkeyNone")
      : t("factorStepUp.passkeyDescription");

  return (
    <Dialog open={open} onOpenChange={(next) => !next && dismiss()}>
      <DialogContent>
        {wantsPasskey ? (
          <>
            <DialogHeader>
              <DialogTitle>{t("factorStepUp.passkeyTitle")}</DialogTitle>
              <DialogDescription>{passkeyDescription}</DialogDescription>
            </DialogHeader>

            {error && <p className="text-destructive text-sm">{error}</p>}

            <DialogFooter>
              <Button variant="outline" onClick={dismiss}>
                {t("factorStepUp.dismiss")}
              </Button>
              {!isNativePlatform &&
                (hasNoPasskey ? (
                  <Button asChild>
                    <Link to="/profile/security" onClick={dismiss}>
                      {t("factorStepUp.passkeyAdd")}
                    </Link>
                  </Button>
                ) : (
                  <Button type="button" onClick={presentPasskey} disabled={submitting}>
                    <KeyRound className="h-4 w-4" aria-hidden="true" />
                    {submitting
                      ? t("factorStepUp.passkeyWorking")
                      : t("factorStepUp.passkeyPresent")}
                  </Button>
                ))}
            </DialogFooter>

            {!isNativePlatform && passkeysUnknown && (
              <p className="text-muted-foreground text-sm">
                <Link
                  to="/profile/security"
                  onClick={dismiss}
                  className="text-primary underline-offset-4 hover:underline"
                >
                  {t("factorStepUp.passkeyAdd")}
                </Link>
              </p>
            )}
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>{t("factorStepUp.title")}</DialogTitle>
              <DialogDescription>
                {hasNoFactor
                  ? t("factorStepUp.notEnrolled")
                  : useRecoveryCode
                    ? t("factorStepUp.recoveryDescription")
                    : t("factorStepUp.description")}
              </DialogDescription>
            </DialogHeader>

            {hasNoFactor ? (
              <DialogFooter>
                <Button variant="outline" onClick={dismiss}>
                  {t("factorStepUp.dismiss")}
                </Button>
                <Button asChild>
                  <Link to="/profile/security" onClick={dismiss}>
                    {t("factorStepUp.setUp")}
                  </Link>
                </Button>
              </DialogFooter>
            ) : (
              <form className="space-y-4" onSubmit={handleSubmit}>
                <div className="space-y-2">
                  <Label htmlFor="step-up-code">
                    {useRecoveryCode
                      ? t("secondFactor.recoveryLabel")
                      : t("secondFactor.codeLabel")}
                  </Label>
                  <Input
                    id="step-up-code"
                    name="step-up-code"
                    // A recovery code carries letters and dashes; a live code is
                    // six digits, and the numeric keypad is what a phone should
                    // offer for it.
                    inputMode={useRecoveryCode ? "text" : "numeric"}
                    autoComplete="one-time-code"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    autoFocus
                    placeholder={
                      useRecoveryCode
                        ? t("secondFactor.recoveryPlaceholder")
                        : t("secondFactor.codePlaceholder")
                    }
                    value={code}
                    onChange={(event) => setCode(event.target.value)}
                    required
                  />
                </div>
                {error && <p className="text-destructive text-sm">{error}</p>}
                <button
                  type="button"
                  className="text-primary text-sm underline-offset-4 hover:underline"
                  onClick={() => {
                    setUseRecoveryCode((previous) => !previous);
                    setCode("");
                    setError(null);
                  }}
                >
                  {useRecoveryCode
                    ? t("secondFactor.useAuthenticator")
                    : t("secondFactor.useRecoveryCode")}
                </button>
                <DialogFooter>
                  <Button type="button" variant="outline" onClick={dismiss}>
                    {t("factorStepUp.dismiss")}
                  </Button>
                  <Button type="submit" disabled={submitting || !code.trim()}>
                    {submitting ? t("login.submitting") : t("factorStepUp.submit")}
                  </Button>
                </DialogFooter>
                {statusUnknown && (
                  <p className="text-muted-foreground text-sm">
                    {t("factorStepUp.noFactorHint")}{" "}
                    <Link
                      to="/profile/security"
                      onClick={dismiss}
                      className="text-primary underline-offset-4 hover:underline"
                    >
                      {t("factorStepUp.setUp")}
                    </Link>
                  </p>
                )}
              </form>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
};
