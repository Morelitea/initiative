import { Link } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { AUTH_FACTOR_REQUIRED_EVENT, type FactorChallengeDetail } from "@/api/client";
import { useReadSecondFactorApiV1AuthTotpGet } from "@/api/generated/auth/auth";
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
import { getErrorMessage } from "@/lib/errorMessage";
import { queryClient } from "@/lib/queryClient";

/**
 * Global handler for a community that requires the account's second factor.
 *
 * When any request is refused with `GUILD_AUTH_FACTOR_REQUIRED` (dispatched by
 * the API client as a window event), this asks for a code and adds the factor
 * to the session already open. The requests that were refused are refetched
 * once it succeeds, so the page the person was on fills in behind the dialog
 * rather than needing a reload.
 *
 * Unlike the provider step-up beside it, this works on native too: the answer
 * is a code presented against the live session, which the app holds just as a
 * browser does.
 */
export const SecondFactorStepUpDialog = () => {
  const { t } = useTranslation("auth");
  const { stepUpWithFactor } = useAuth();
  const { clear, open } = useAuthChallenge<FactorChallengeDetail>(
    AUTH_FACTOR_REQUIRED_EVENT,
    () => true
  );

  const [code, setCode] = useState("");
  const [useRecoveryCode, setUseRecoveryCode] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Only asked once there is something to answer. The status route is
  // platform-scoped, so it is not itself refused by the community that raised
  // the challenge.
  const statusQuery = useReadSecondFactorApiV1AuthTotpGet({
    query: { enabled: open },
  });
  // Three states, not two. While the answer is in flight, offer the form: the
  // refusal that opened this dialog is the common case and a form is what it
  // wants. Only a definite "no factor" swaps it for the way to get one — and
  // when the status cannot be read at all, the form stays but the way to get
  // one is offered beside it, so neither audience is stranded.
  const hasNoFactor = statusQuery.data?.enrolled === false;
  const statusUnknown = statusQuery.isError;

  const dismiss = () => {
    clear();
    setCode("");
    setUseRecoveryCode(false);
    setError(null);
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
      // The session changed, and every query that was refused while it lacked
      // the factor should ask again.
      await queryClient.invalidateQueries();
      dismiss();
    } catch (err) {
      setError(getErrorMessage(err, "auth:factorStepUp.error"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && dismiss()}>
      <DialogContent>
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
                {useRecoveryCode ? t("secondFactor.recoveryLabel") : t("secondFactor.codeLabel")}
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
      </DialogContent>
    </Dialog>
  );
};
