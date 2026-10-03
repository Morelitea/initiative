import { Link, useRouter } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { LegalNotice } from "@/components/auth/LegalNotice";
import { ServerPicker } from "@/components/auth/ServerChoice";
import { SignInFrame } from "@/components/auth/SignInFrame";
import { RecoveryCodesPanel } from "@/components/settings/RecoveryCodesPanel";
import { type HandleCheck, UsernameField } from "@/components/UsernameField";
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
import { useAuth } from "@/hooks/useAuth";
import { getErrorMessage } from "@/lib/errorMessage";
import {
  browserOffersPasskeys,
  describePasskeyPromptError,
  signUpWithPasskey,
} from "@/lib/passkeys";
import { PASSWORD_MIN_LENGTH, validatePasswordLocal } from "@/lib/passwordPolicy";

/**
 * The first account on a fresh deployment, which becomes its owner. Everyone
 * after that signs up through the start flow.
 */
export const RegisterPage = () => {
  const { t } = useTranslation(["auth", "common", "errors"]);
  const router = useRouter();
  const { register, login, applyPasskeySignIn } = useAuth();
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [handle, setHandle] = useState<HandleCheck>({ usable: true, offer: null });
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { passwordLoginEnabled, passkeyLoginEnabled } = useAppConfig();
  // Which doors this deployment leaves open. A key can make an account on its
  // own, so a deployment that has withdrawn passwords still has a way in that
  // is its own rather than an identity provider's.
  const keysOffered = passkeyLoginEnabled && browserOffersPasskeys();
  const passwordsOffered = passwordLoginEnabled;
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);

  /** What both doors send about the person registering. */
  const details = () => ({
    email: email.toLowerCase().trim(),
    username: username.trim().toLowerCase(),
    username_offer: handle.offer ?? undefined,
    // Resolve the browser's IANA timezone (e.g. "America/Los_Angeles") so the
    // new account starts on the user's wall clock instead of the backend's
    // "UTC" default.
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || undefined,
  });

  /**
   * Register with a key instead of a password.
   *
   * The account is signed in by the ceremony that made it, so there is no
   * second sign-in here. Its recovery codes come back with it and are shown
   * once — an account with no password cannot be sent a reset, so they are
   * how it gets one later.
   */
  const registerWithPasskey = async () => {
    setSubmitting(true);
    setError(null);
    setInfoMessage(null);
    try {
      const made = await signUpWithPasskey(details());
      // The ceremony that made the account signed it in, so it is adopted the
      // way any passkey sign-in is. The codes go on screen before anything
      // else is awaited: they are shown once.
      setRecoveryCodes(made.codes ?? []);
      await applyPasskeySignIn({ access_token: made.access_token });
    } catch (err) {
      const prompt = describePasskeyPromptError(err);
      setError(prompt ? t(prompt) : getErrorMessage(err, "auth:register.defaultError"));
    } finally {
      setSubmitting(false);
    }
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setInfoMessage(null);
    try {
      if (password !== confirmPassword) {
        setError(t("register.passwordMismatch"));
        return;
      }
      const policyError = validatePasswordLocal(password);
      if (policyError) {
        setError(policyError);
        return;
      }
      // Resolve the browser's IANA timezone (e.g. "America/Los_Angeles")
      // so the new account starts on the user's wall clock instead of
      // the backend's "UTC" default. ``Intl.DateTimeFormat`` is
      // available everywhere this SPA already supports; the optional
      // chain + ``|| undefined`` guard handles the unusual case where
      // the resolved name comes back falsy, in which case we just
      // omit the field and let the backend default apply.
      const createdUser = await register({ ...details(), password });
      const isActive = createdUser.status === "active";
      if (isActive && createdUser.email_verified) {
        await login({ email: email.toLowerCase().trim(), password });
        router.navigate({ to: "/", replace: true });
      } else if (isActive && !createdUser.email_verified) {
        setInfoMessage(t("register.verifyEmailMessage"));
        setPassword("");
        setConfirmPassword("");
      } else {
        setInfoMessage(t("register.pendingApproval"));
        setPassword("");
        setConfirmPassword("");
      }
    } catch (err) {
      console.error(err);
      setError(getErrorMessage(err, "auth:register.defaultError"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SignInFrame pickServer={!recoveryCodes}>
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader>
          <CardTitle>{t("register.titleBootstrap")}</CardTitle>
          <CardDescription>{t("register.subtitleBootstrap")}</CardDescription>
        </CardHeader>
        <CardContent>
          {recoveryCodes ? (
            // The account exists and is signed in; what is left is the one
            // sight of the codes that are now its way back to a password.
            <RecoveryCodesPanel
              codes={recoveryCodes}
              note={t("register.recoveryCodesNote")}
              onDone={() => router.navigate({ to: "/", replace: true })}
            />
          ) : (
            <form className="space-y-4" onSubmit={handleSubmit}>
              <UsernameField
                id="register-username"
                value={username}
                onChange={setUsername}
                onChecked={setHandle}
                disabled={submitting}
              />
              <div className="space-y-2">
                <Label htmlFor="register-email">{t("register.emailLabel")}</Label>
                <Input
                  id="register-email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoCapitalize="none"
                  required
                />
              </div>
              {passwordsOffered ? (
                <div className="space-y-2">
                  <Label htmlFor="register-password">{t("register.passwordLabel")}</Label>
                  <Input
                    id="register-password"
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
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
                    {t("auth:passwordPolicy.minLengthHelp")}
                  </p>
                </div>
              ) : null}
              {passwordsOffered ? (
                <div className="space-y-2">
                  <Label htmlFor="confirm-password">{t("register.confirmPasswordLabel")}</Label>
                  <Input
                    id="confirm-password"
                    type="password"
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    required
                  />
                </div>
              ) : null}
              {/* Immediately above the button, because pressing the button is
                  the agreement. Renders nothing where the deployment has no
                  terms of its own. */}
              <LegalNotice />
              {passwordsOffered ? (
                <Button className="w-full" type="submit" disabled={submitting}>
                  {submitting ? t("register.submitting") : t("register.submit")}
                </Button>
              ) : null}
              {keysOffered ? (
                <Button
                  className="w-full"
                  type="button"
                  variant={passwordsOffered ? "outline" : "default"}
                  onClick={() => void registerWithPasskey()}
                  disabled={submitting}
                >
                  {submitting ? t("register.submitting") : t("register.submitPasskey")}
                </Button>
              ) : null}
              {!passwordsOffered && !keysOffered ? (
                <p className="text-muted-foreground text-sm">{t("register.noDoorHere")}</p>
              ) : null}
              {error ? <p className="text-destructive text-sm">{error}</p> : null}
              {infoMessage ? <p className="text-primary text-sm">{infoMessage}</p> : null}
            </form>
          )}
          {recoveryCodes ? null : <ServerPicker className="mt-6 border-t pt-4" />}
        </CardContent>
        <CardFooter className="text-muted-foreground text-sm">
          {t("register.haveAccount")}{" "}
          <Link className="ml-1 text-primary underline-offset-4 hover:underline" to="/login">
            {t("register.signIn")}
          </Link>
        </CardFooter>
      </Card>
    </SignInFrame>
  );
};
