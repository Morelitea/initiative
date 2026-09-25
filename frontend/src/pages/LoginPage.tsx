import { Browser } from "@capacitor/browser";
import { Device } from "@capacitor/device";
import { Link, useRouter, useSearch } from "@tanstack/react-router";
import { KeyRound, Mail } from "lucide-react";
import {
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import type {
  LoginProviderEntry,
  LoginProvidersResponse,
} from "@/api/generated/initiativeAPI.schemas";
import { EmailOtpCard } from "@/components/auth/EmailOtpCard";
import { PasskeyRelayCard } from "@/components/auth/PasskeyRelayCard";
import { ProviderMark } from "@/components/auth/ProviderMark";
import { LogoIcon } from "@/components/LogoIcon";
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
import { SecondFactorRequiredError, useAuth } from "@/hooks/useAuth";
import { useResumeAfterSignIn } from "@/hooks/useResumeAfterSignIn";
import { useServer } from "@/hooks/useServer";
import { getErrorCode } from "@/lib/errorMessage";
import { beginNativeSignIn } from "@/lib/nativeSignIn";
import { passkeyFailureMessage } from "@/lib/passkeyFailure";
import {
  browserOffersPasskeyAutofill,
  browserOffersPasskeys,
  cancelPendingPasskeyPrompt,
  signInWithPasskey,
} from "@/lib/passkeys";
import { returnPath } from "@/lib/returnPath";
import { compactCode } from "@/lib/secondFactorAnswer";

import { RegisterPage } from "./RegisterPage";

/** Where an app sends a phone so a browser can run the ceremony for it. */
const RELAY_PATH = "/login?passkey=1&mobile=true";

/** What to call a phone in the sign-in record when it will not say. */
const FALLBACK_DEVICE_NAME = "Mobile Device";

/** The ground every version of the sign-in card sits on. */
const SignInFrame = ({ children }: { children: ReactNode }) => {
  const { t } = useTranslation("common");
  const isDark = document.documentElement.classList.contains("dark");

  return (
    <div
      style={{
        backgroundImage: `url(${isDark ? "/images/hexWhite.svg" : "/images/hexBlack.svg"})`,
        backgroundPosition: "center",
        backgroundBlendMode: "screen",
        backgroundSize: "67px 116px",
      }}
    >
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-muted/60 px-4 py-12">
        <div className="flex items-center gap-3 font-semibold text-3xl text-primary tracking-tight">
          <LogoIcon className="h-12 w-12" aria-hidden="true" focusable="false" />
          <span className="pride-wordmark">{t("appName")}</span>
        </div>
        {children}
      </div>
    </div>
  );
};

/** The value of a URL flag, whatever the router made of it: `passkey=1` can
 *  arrive as a number and `mobile=true` as a boolean. */
const flag = (value: unknown): string => String(value ?? "");

export const LoginPage = () => {
  const { t } = useTranslation(["auth", "common", "errors"]);
  const router = useRouter();
  const searchParams = useSearch({ strict: false }) as {
    invite_code?: string;
    next?: string;
    passkey?: string | number;
    mobile?: string | boolean;
    device_name?: string;
    code_challenge?: string;
  };
  const { login, completeSecondFactor, applyPasskeySignIn } = useAuth();
  const resumeAfterSignIn = useResumeAfterSignIn();
  const {
    isNativePlatform,
    isServerConfigured,
    getServerHostname,
    getServerOrigin,
    clearServerUrl,
  } = useServer();
  const { passwordLoginEnabled, passkeyLoginEnabled, emailOtpLoginEnabled } = useAppConfig();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Set when the password was right and the account holds a second factor. The
  // card swaps to asking for the code; the challenge is held in memory only.
  const [challenge, setChallenge] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [useRecoveryCode, setUseRecoveryCode] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [passkeyBusy, setPasskeyBusy] = useState(false);
  // The emailed-code card takes the whole frame while it is open: it asks for
  // one thing at a time, and the other ways in are not among them.
  const [emailOtpOpen, setEmailOtpOpen] = useState(false);
  const [providers, setProviders] = useState<LoginProviderEntry[]>([]);
  const [bootstrapStatus, setBootstrapStatus] = useState<"loading" | "required" | "ready">(
    "loading"
  );
  const inviteCodeParam = useMemo(() => {
    const code = searchParams.invite_code;
    return code && code.trim().length > 0 ? code.trim() : null;
  }, [searchParams]);

  // This page, opened in a system browser by an app that cannot hold the
  // conversation itself: one press, then back to where it came from.
  const relayMode = flag(searchParams.passkey) === "1" && flag(searchParams.mobile) === "true";
  const relayDeviceName =
    typeof searchParams.device_name === "string" ? searchParams.device_name : "";
  const relayChallenge =
    typeof searchParams.code_challenge === "string" ? searchParams.code_challenge : "";

  // A phone's Add-a-passkey equivalent: the browser decides which site it is
  // on, so on native the button opens one rather than prompting in the webview.
  const passkeyOffered = passkeyLoginEnabled && (isNativePlatform || browserOffersPasskeys());

  // Fetch the sign-in providers the server offers (one button per provider).
  // Re-runs when the server becomes configured: on native the base URL is
  // hydrated after mount, and a fetch before that returns nothing.
  useEffect(() => {
    const fetchProviders = async () => {
      try {
        const response = await apiClient.get<LoginProvidersResponse>("/auth/providers");
        setProviders(response.data.providers);
      } catch {
        setProviders([]);
      }
    };
    void fetchProviders();
  }, [isServerConfigured]);

  const resolveDeviceName = async (): Promise<string> => {
    try {
      const info = await Device.getInfo();
      return info.name || info.model || FALLBACK_DEVICE_NAME;
    } catch {
      // Fall back to default device name
      return FALLBACK_DEVICE_NAME;
    }
  };

  const handleProviderLogin = async (provider: LoginProviderEntry) => {
    const origin = getServerOrigin();
    if (isNativePlatform && origin) {
      // The phone's browser runs the provider's sign-in and hands back a code
      // for this app to redeem.
      const params = new URLSearchParams({
        mobile: "true",
        device_name: await resolveDeviceName(),
        code_challenge: await beginNativeSignIn(origin),
      });
      await Browser.open({ url: `${origin}${provider.login_url}?${params}` });
    } else {
      // On web, redirect directly — carrying where they were headed, so an
      // account that only signs in through a provider finishes the trip it
      // started. The server reads `next` back on its callback.
      const next = returnPath(searchParams.next);
      window.location.href = next
        ? `${provider.login_url}?next=${encodeURIComponent(next)}`
        : provider.login_url;
    }
  };

  // Fetch bootstrap status
  useEffect(() => {
    const fetchBootstrapStatus = async () => {
      try {
        const response = await apiClient.get<{ has_users: boolean }>("/auth/bootstrap");
        setBootstrapStatus(response.data.has_users ? "ready" : "required");
      } catch {
        setBootstrapStatus("ready");
      }
    };
    void fetchBootstrapStatus();
  }, [isServerConfigured]);

  // Memoized, along with the two below it: the autofill ceremony is started
  // from an effect, and a handler that is a new function every render would
  // have that effect chasing its own tail.
  const goWhereTheySignedInFor = useCallback(async () => {
    // An invite wins over the page they were headed for: it is why they are here.
    if (inviteCodeParam) {
      router.navigate({
        to: "/invite/$code",
        params: { code: encodeURIComponent(inviteCodeParam) },
        replace: true,
      });
      return;
    }
    await resumeAfterSignIn(searchParams.next);
  }, [inviteCodeParam, resumeAfterSignIn, router, searchParams.next]);

  /** What to put on the card when a passkey sign-in the person asked for did
   *  not finish. Nothing is said for a prompt this page stood down itself. */
  const reportPasskeyFailure = useCallback(
    (err: unknown) => {
      const message = passkeyFailureMessage(err, t);
      if (message) setError(message);
    },
    [t]
  );

  /** Adopt a session the browser's own autofill or the button produced. */
  const adoptPasskeySession = useCallback(
    async (result: Awaited<ReturnType<typeof signInWithPasskey>>) => {
      await applyPasskeySignIn(result);
      await goWhereTheySignedInFor();
    },
    [applyPasskeySignIn, goWhereTheySignedInFor]
  );

  // The browser can offer a passkey inside its own autofill, beside the saved
  // passwords, so the ceremony waits there from the moment the page opens.
  // Nothing is drawn for it and nothing is reported from it: nobody pressed
  // anything to start it, so it either produces a credential or it is quietly
  // still waiting when the page goes. It needs the address field to surface
  // in, so a deployment with no password form gets no quiet prompt either.
  //
  // The ref, not the dependencies, is what makes it happen once: a config
  // answer arriving late re-runs this, and a prompt that is already up must
  // not be restarted under the person.
  const autofillStartedRef = useRef(false);
  // Set once a lapsed challenge has already bought one fresh turn.
  const autofillRestartedRef = useRef(false);
  useEffect(() => {
    if (autofillStartedRef.current) return;
    if (relayMode || isNativePlatform || !passkeyOffered || !passwordLoginEnabled) return;
    autofillStartedRef.current = true;

    /** One turn waiting in the autofill. The server's challenge lapses after a
     *  few minutes while the browser's prompt stands as long as the tab does,
     *  so a turn the server refuses for that reason takes one fresh turn —
     *  one, and then it rests. The start ref stays set across that: this is
     *  the same ceremony carrying on, not a second one alongside it. */
    const waitInAutofill = async (): Promise<void> => {
      if (!(await browserOffersPasskeyAutofill())) return;
      try {
        await adoptPasskeySession(await signInWithPasskey({ conditional: true }));
      } catch (err) {
        // A ceremony this page put down itself — stood aside for the button's
        // prompt, or gone with the page — is not worth a line.
        if (!(err instanceof Error && err.name === "AbortError")) {
          console.debug("Passkey autofill ceremony ended without a session", err);
        }
        if (autofillRestartedRef.current) return;
        if (getErrorCode(err) !== "PASSKEY_SIGN_IN_INVALID") return;
        autofillRestartedRef.current = true;
        await waitInAutofill();
      }
    };
    void waitInAutofill();
  }, [relayMode, isNativePlatform, passkeyOffered, passwordLoginEnabled, adoptPasskeySession]);

  // Whatever is still waiting goes with the page.
  useEffect(() => () => cancelPendingPasskeyPrompt(), []);

  /** Send a phone to a browser, which is what knows the site the passkey
   *  belongs to. The app takes over again at the callback link. */
  const openPasskeyRelay = async () => {
    const origin = getServerOrigin();
    if (!origin) return;
    const params = new URLSearchParams({
      device_name: await resolveDeviceName(),
      code_challenge: await beginNativeSignIn(origin),
    });
    await Browser.open({ url: `${origin}${RELAY_PATH}&${params}` });
  };

  const handlePasskeyLogin = async () => {
    if (isNativePlatform) {
      await openPasskeyRelay();
      return;
    }
    setPasskeyBusy(true);
    setError(null);
    try {
      // Only one ceremony runs at a time, so the one waiting in autofill stands
      // aside for the one the person just asked for.
      cancelPendingPasskeyPrompt();
      await adoptPasskeySession(await signInWithPasskey({ conditional: false }));
    } catch (err) {
      reportPasskeyFailure(err);
    } finally {
      setPasskeyBusy(false);
    }
  };

  const handleChangeServer = () => {
    clearServerUrl();
    router.navigate({ to: "/connect", replace: true });
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const deviceName = isNativePlatform ? await resolveDeviceName() : undefined;
      await login({ email: email.toLowerCase().trim(), password, deviceName });
      await goWhereTheySignedInFor();
    } catch (err) {
      if (err instanceof SecondFactorRequiredError) {
        // Not a failure — the sign-in is half done. Drop the password; it has
        // served its purpose and the code is what is asked for now.
        setChallenge(err.challenge);
        setPassword("");
        setError(null);
        return;
      }
      console.error(err);
      setError(err instanceof Error ? err.message : t("login.defaultError"));
    } finally {
      setSubmitting(false);
    }
  };

  const handleCodeSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!challenge) return;
    setSubmitting(true);
    setError(null);
    try {
      const entered = code.trim();
      await completeSecondFactor({
        challenge,
        ...(useRecoveryCode ? { recoveryCode: entered } : { code: compactCode(entered) }),
      });
      await goWhereTheySignedInFor();
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : t("login.defaultError"));
      setCode("");
    } finally {
      setSubmitting(false);
    }
  };

  const startOver = () => {
    setChallenge(null);
    setCode("");
    setUseRecoveryCode(false);
    setError(null);
  };

  // The relay browser was opened for one thing, so it is asked for one thing —
  // before the first-run and provider questions, which are not its business.
  if (relayMode) {
    return (
      <SignInFrame>
        <PasskeyRelayCard
          deviceName={relayDeviceName || FALLBACK_DEVICE_NAME}
          codeChallenge={relayChallenge}
        />
      </SignInFrame>
    );
  }

  if (bootstrapStatus === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/60 px-4 py-12">
        <p className="text-muted-foreground text-sm">{t("common:loading")}</p>
      </div>
    );
  }

  if (bootstrapStatus === "required") {
    return <RegisterPage bootstrapMode />;
  }

  if (emailOtpOpen) {
    return (
      <SignInFrame>
        <EmailOtpCard
          inviteCode={inviteCodeParam}
          onCancel={() => setEmailOtpOpen(false)}
          onSignedIn={goWhereTheySignedInFor}
        />
      </SignInFrame>
    );
  }

  return (
    <SignInFrame>
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader>
          <CardTitle>{challenge ? t("secondFactor.title") : t("login.title")}</CardTitle>
          <CardDescription>
            {challenge
              ? useRecoveryCode
                ? t("secondFactor.recoverySubtitle")
                : t("secondFactor.subtitle")
              : t("login.subtitle")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {challenge ? (
            <form className="space-y-4" onSubmit={handleCodeSubmit}>
              <div className="space-y-2">
                <Label htmlFor="second-factor-code">
                  {useRecoveryCode ? t("secondFactor.recoveryLabel") : t("secondFactor.codeLabel")}
                </Label>
                <Input
                  id="second-factor-code"
                  name="second-factor-code"
                  // A recovery code carries letters and dashes; a live code
                  // is six digits, and the numeric keypad is what a phone
                  // should offer for it.
                  inputMode={useRecoveryCode ? "text" : "numeric"}
                  autoComplete="one-time-code"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  // The only field on a step the person was just sent to,
                  // mid-sign-in.
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
              <Button className="w-full" type="submit" disabled={submitting || !code.trim()}>
                {submitting ? t("login.submitting") : t("secondFactor.submit")}
              </Button>
              <div className="flex items-center justify-between text-sm">
                <button
                  type="button"
                  className="text-primary underline-offset-4 hover:underline"
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
                <button
                  type="button"
                  className="text-muted-foreground underline-offset-4 hover:underline"
                  onClick={startOver}
                >
                  {t("secondFactor.startOver")}
                </button>
              </div>
              {error ? <p className="text-destructive text-sm">{error}</p> : null}
            </form>
          ) : (
            <form className="space-y-4" onSubmit={handleSubmit} autoComplete="on">
              {/* Offered only where the deployment permits it. The server
                  refuses the sign-in either way; this keeps the page from
                  presenting a form that cannot work. */}
              {passwordLoginEnabled ? (
                <>
                  <div className="space-y-2">
                    <Label htmlFor="email">{t("login.emailLabel")}</Label>
                    <Input
                      id="email"
                      name="email"
                      type="email"
                      placeholder={t("login.emailPlaceholder")}
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      // The second word is what lets the browser put a passkey
                      // in the same list as the saved addresses.
                      autoComplete="username webauthn"
                      autoCapitalize="none"
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="password">{t("login.passwordLabel")}</Label>
                    <Input
                      id="password"
                      name="password"
                      type="password"
                      placeholder={t("login.passwordPlaceholder")}
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      autoComplete="current-password"
                      required
                    />
                    <div className="text-right">
                      <Link
                        className="text-primary text-sm underline-offset-4 hover:underline"
                        to="/forgot-password"
                      >
                        {t("login.forgotPassword")}
                      </Link>
                    </div>
                  </div>
                  <Button className="w-full" type="submit" disabled={submitting}>
                    {submitting ? t("login.submitting") : t("login.submit")}
                  </Button>
                </>
              ) : null}
              {passkeyOffered ? (
                <Button
                  type="button"
                  // The way in where it is the only one, an alternative where
                  // there is a password form above it.
                  variant={passwordLoginEnabled ? "outline" : "default"}
                  className="w-full"
                  disabled={passkeyBusy}
                  onClick={() => void handlePasskeyLogin()}
                >
                  <KeyRound className="h-4 w-4" />
                  {passkeyBusy ? t("login.passkeyWorking") : t("login.passkey")}
                </Button>
              ) : null}
              {emailOtpLoginEnabled ? (
                <Button
                  type="button"
                  variant={passwordLoginEnabled ? "outline" : "default"}
                  className="w-full"
                  onClick={() => setEmailOtpOpen(true)}
                >
                  <Mail className="h-4 w-4" />
                  {t("login.emailOtp")}
                </Button>
              ) : null}
              {providers.map((provider) => (
                <Button
                  key={provider.slug}
                  type="button"
                  variant="outline"
                  className="w-full"
                  onClick={() => void handleProviderLogin(provider)}
                >
                  <ProviderMark icon={provider.icon} className="h-4 w-4" />
                  {t("login.continueWith", { provider: provider.display_name })}
                </Button>
              ))}
              {error ? <p className="text-destructive text-sm">{error}</p> : null}
            </form>
          )}
        </CardContent>
        <CardFooter className="flex flex-col items-start gap-2 text-muted-foreground text-sm">
          {isNativePlatform && (
            <p className="text-xs">
              {t("login.connectedTo")} <span className="font-medium">{getServerHostname()}</span>
              {" · "}
              <button
                type="button"
                className="text-primary underline-offset-4 hover:underline"
                onClick={handleChangeServer}
              >
                {t("login.changeServer")}
              </button>
            </p>
          )}
          {passwordLoginEnabled ? (
            <p>
              {t("login.needAccount")}{" "}
              <Link
                className="text-primary underline-offset-4 hover:underline"
                to="/register"
                search={inviteCodeParam ? { invite_code: inviteCodeParam } : undefined}
              >
                {t("login.register")}
              </Link>
            </p>
          ) : null}
        </CardFooter>
      </Card>
    </SignInFrame>
  );
};
