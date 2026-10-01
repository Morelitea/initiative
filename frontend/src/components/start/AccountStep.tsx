import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { CaptchaWidget } from "@/components/auth/CaptchaWidget";
import { LegalNotice } from "@/components/auth/LegalNotice";
import { StepField } from "@/components/start/stepParts";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAppConfig } from "@/hooks/useAppConfig";
import { browserOffersPasskeys } from "@/lib/passkeys";
import { PASSWORD_MIN_LENGTH, validatePasswordLocal } from "@/lib/passwordPolicy";

/**
 * The ways in this deployment offers: an address with a password and/or a
 * passkey, or a code sent to the address.
 */
export const AccountStep = ({
  email,
  onEmailChange,
  busy,
  blocked,
  onPassword,
  onPasskey,
  onEmailCode,
  onError,
}: {
  email: string;
  onEmailChange: (email: string) => void;
  busy: boolean;
  /** Something earlier in the flow still needs fixing (an invite that no
   *  longer works). */
  blocked: boolean;
  onPassword: (password: string, captchaToken: string) => Promise<void>;
  onPasskey: (captchaToken: string) => Promise<void>;
  onEmailCode: () => void;
  onError: (message: string) => void;
}) => {
  const { t } = useTranslation("auth");
  const { captcha, passwordLoginEnabled, passkeyLoginEnabled, emailOtpLoginEnabled } =
    useAppConfig();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [captchaToken, setCaptchaToken] = useState("");
  // A captcha token is spent by being checked, so every attempt gets a fresh
  // widget: bumping this remounts it.
  const [captchaKey, setCaptchaKey] = useState(0);
  const keysOffered = passkeyLoginEnabled && browserOffersPasskeys();
  const formDoor = passwordLoginEnabled || keysOffered;
  const incomplete = !email.trim() || (captcha !== null && !captchaToken) || blocked;

  const attempt = async (run: () => Promise<void>) => {
    try {
      await run();
    } finally {
      if (captcha) {
        setCaptchaToken("");
        setCaptchaKey((key) => key + 1);
      }
    }
  };

  const submitPassword = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (password !== confirmPassword) {
      onError(t("register.passwordMismatch"));
      return;
    }
    const policyError = validatePasswordLocal(password);
    if (policyError) {
      onError(policyError);
      return;
    }
    void attempt(() => onPassword(password, captchaToken));
  };

  return (
    <form className="space-y-4" onSubmit={submitPassword}>
      {formDoor ? (
        <StepField id="start-email" label={t("register.emailLabel")}>
          <Input
            id="start-email"
            type="email"
            value={email}
            onChange={(event) => onEmailChange(event.target.value)}
            autoComplete="email"
            autoCapitalize="none"
            required
          />
        </StepField>
      ) : null}
      {passwordLoginEnabled ? (
        <>
          <StepField
            id="start-password"
            label={t("register.passwordLabel")}
            hint={t("passwordPolicy.minLengthHelp")}
          >
            <Input
              id="start-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
              minLength={PASSWORD_MIN_LENGTH}
              required
            />
          </StepField>
          <StepField id="start-confirm-password" label={t("register.confirmPasswordLabel")}>
            <Input
              id="start-confirm-password"
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              autoComplete="new-password"
              required
            />
          </StepField>
        </>
      ) : null}
      {formDoor && captcha ? (
        <CaptchaWidget key={captchaKey} config={captcha} onToken={setCaptchaToken} />
      ) : null}
      {/* Immediately above the buttons: pressing one is the agreement. */}
      {formDoor ? <LegalNotice /> : null}
      {passwordLoginEnabled ? (
        <Button type="submit" className="w-full" disabled={busy || incomplete}>
          {busy ? t("register.submitting") : t("register.submit")}
        </Button>
      ) : null}
      {keysOffered ? (
        <Button
          type="button"
          className="w-full"
          variant={passwordLoginEnabled ? "outline" : "default"}
          onClick={() => void attempt(() => onPasskey(captchaToken))}
          disabled={busy || incomplete}
        >
          {busy ? t("register.submitting") : t("register.submitPasskey")}
        </Button>
      ) : null}
      {emailOtpLoginEnabled ? (
        <Button
          type="button"
          className="w-full"
          variant={formDoor ? "ghost" : "default"}
          onClick={onEmailCode}
          disabled={busy || blocked}
        >
          {t("start.account.emailCode")}
        </Button>
      ) : null}
      {!formDoor && !emailOtpLoginEnabled ? (
        <p className="text-muted-foreground text-sm">{t("register.noDoorHere")}</p>
      ) : null}
    </form>
  );
};
