import { Link } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { recoverWithCode } from "@/api/generated/auth/auth";
import { SignInFrame } from "@/components/auth/SignInFrame";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAppConfig } from "@/hooks/useAppConfig";
import { getErrorMessage } from "@/lib/errorMessage";
import { PASSWORD_MIN_LENGTH, validatePasswordLocal } from "@/lib/passwordPolicy";

/**
 * Two ways back in, on one card.
 *
 * The mailed link is the usual one. An account that signs in with a passkey
 * has no password to reset and may be on a deployment that sends no mail at
 * all, so the other way is a recovery code: it sets a password rather than
 * opening a session, and that password is what signs the account in next.
 */
export const ForgotPasswordPage = () => {
  // ``errors`` comes along so a server code — a code that did not match, a
  // password the policy refuses — is localized without a mid-submit load.
  const { t } = useTranslation(["auth", "common", "errors"]);
  const { passwordLoginEnabled } = useAppConfig();
  const [mode, setMode] = useState<"reset" | "recover">("reset");
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  const [recoveryCode, setRecoveryCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [recoverStatus, setRecoverStatus] = useState<"idle" | "submitting" | "success">("idle");

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setStatus("sending");
    setError(null);
    try {
      await apiClient.post("/auth/password/forgot", { email: email.toLowerCase().trim() });
      setStatus("sent");
    } catch (err) {
      console.error(err);
      setError(t("forgotPassword.error"));
      setStatus("idle");
    }
  };

  const handleRecover = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (password !== confirmPassword) {
      setError(t("resetPassword.passwordMismatch"));
      return;
    }
    const policyError = validatePasswordLocal(password);
    if (policyError) {
      setError(policyError);
      return;
    }
    setRecoverStatus("submitting");
    setError(null);
    try {
      await recoverWithCode({
        email: email.toLowerCase().trim(),
        recovery_code: recoveryCode.trim(),
        password,
      });
      setRecoverStatus("success");
    } catch (err) {
      console.error(err);
      setError(getErrorMessage(err, "auth:forgotPassword.recoverError"));
      setRecoverStatus("idle");
    }
  };

  const switchMode = (next: "reset" | "recover") => {
    setMode(next);
    setError(null);
    setStatus("idle");
    setRecoverStatus("idle");
    setRecoveryCode("");
    setPassword("");
    setConfirmPassword("");
  };

  return (
    <SignInFrame>
      <Card className="w-full max-w-md shadow-lg">
        {/* Both ways end in a password, which this deployment may not take:
          the server refuses them then, so the page says so instead. */}
        {!passwordLoginEnabled ? (
          <CardHeader>
            <CardTitle>{t("passwordsOff.title")}</CardTitle>
            <CardDescription>{t("passwordsOff.description")}</CardDescription>
          </CardHeader>
        ) : (
          <CardHeader>
            <CardTitle>
              {mode === "recover" ? t("forgotPassword.recoverTitle") : t("forgotPassword.title")}
            </CardTitle>
            <CardDescription>
              {mode === "recover"
                ? t("forgotPassword.recoverSubtitle")
                : t("forgotPassword.subtitle")}
            </CardDescription>
          </CardHeader>
        )}
        {passwordLoginEnabled ? (
          <CardContent>
            {mode === "reset" ? (
              <form className="space-y-4" onSubmit={handleSubmit}>
                <div className="space-y-2">
                  <Label htmlFor="forgot-email">{t("forgotPassword.emailLabel")}</Label>
                  <Input
                    id="forgot-email"
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    required
                    autoComplete="email"
                    autoCapitalize="none"
                  />
                </div>
                <Button className="w-full" type="submit" disabled={status === "sending"}>
                  {status === "sending"
                    ? t("forgotPassword.submitting")
                    : t("forgotPassword.submit")}
                </Button>
                {error ? <p className="text-destructive text-sm">{error}</p> : null}
                {status === "sent" ? (
                  <p className="text-primary text-sm">{t("forgotPassword.sent")}</p>
                ) : null}
                <button
                  type="button"
                  className="text-primary text-sm underline-offset-4 hover:underline"
                  onClick={() => switchMode("recover")}
                >
                  {t("forgotPassword.useRecoveryCode")}
                </button>
              </form>
            ) : recoverStatus === "success" ? (
              <div className="space-y-4 text-primary text-sm">
                <p>{t("forgotPassword.recovered")}</p>
                <Button className="w-full" asChild>
                  <Link to="/login">{t("resetPassword.goToSignIn")}</Link>
                </Button>
              </div>
            ) : (
              <form className="space-y-4" onSubmit={handleRecover}>
                <div className="space-y-2">
                  <Label htmlFor="recover-email">{t("forgotPassword.emailLabel")}</Label>
                  <Input
                    id="recover-email"
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    required
                    autoComplete="email"
                    autoCapitalize="none"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="recovery-code">{t("forgotPassword.recoveryCodeLabel")}</Label>
                  <Input
                    id="recovery-code"
                    value={recoveryCode}
                    onChange={(event) => setRecoveryCode(event.target.value)}
                    placeholder={t("forgotPassword.recoveryCodePlaceholder")}
                    autoComplete="one-time-code"
                    autoCapitalize="none"
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="recover-password">{t("resetPassword.newPasswordLabel")}</Label>
                  <Input
                    id="recover-password"
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete="new-password"
                    minLength={PASSWORD_MIN_LENGTH}
                    required
                  />
                  <p
                    className={
                      password.length > 0 && password.length < PASSWORD_MIN_LENGTH
                        ? "text-destructive text-xs"
                        : "text-muted-foreground text-xs"
                    }
                  >
                    {t("passwordPolicy.minLengthHelp")}
                  </p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="recover-confirm-password">
                    {t("resetPassword.confirmPasswordLabel")}
                  </Label>
                  <Input
                    id="recover-confirm-password"
                    type="password"
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    autoComplete="new-password"
                    required
                  />
                </div>
                <Button className="w-full" type="submit" disabled={recoverStatus === "submitting"}>
                  {recoverStatus === "submitting"
                    ? t("forgotPassword.recovering")
                    : t("forgotPassword.recoverSubmit")}
                </Button>
                {error ? <p className="text-destructive text-sm">{error}</p> : null}
                <button
                  type="button"
                  className="text-primary text-sm underline-offset-4 hover:underline"
                  onClick={() => switchMode("reset")}
                >
                  {t("forgotPassword.backToReset")}
                </button>
              </form>
            )}
          </CardContent>
        ) : null}
        <CardFooter className="text-muted-foreground text-sm">
          {passwordLoginEnabled ? `${t("forgotPassword.remembered")} ` : null}
          <Link className="ml-1 text-primary underline-offset-4 hover:underline" to="/login">
            {t("forgotPassword.backToSignIn")}
          </Link>
        </CardFooter>
      </Card>
    </SignInFrame>
  );
};
