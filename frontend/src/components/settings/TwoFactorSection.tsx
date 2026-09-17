import { QRCodeSVG } from "qrcode.react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useBeginSecondFactorApiV1AuthTotpEnrollPost,
  useConfirmSecondFactorApiV1AuthTotpConfirmPost,
  useDisableSecondFactorApiV1AuthTotpDisablePost,
  useReadSecondFactorApiV1AuthTotpGet,
  useRegenerateRecoveryCodesApiV1AuthRecoveryCodesRegeneratePost,
} from "@/api/generated/auth/auth";
import { Badge } from "@/components/ui/badge";
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
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { formatDateTime } from "@/lib/formatDate";
import { queryClient } from "@/lib/queryClient";

/** Below this, the set is worth replacing before it runs out. */
const LOW_ON_CODES = 3;

type EnrolStep = "password" | "scan" | "codes";
/** The password step serves two errands, and they part ways after it. */
type Errand = "enrol" | "regenerate";

/**
 * Two-factor authentication, on the account's own security page.
 *
 * Three things happen here and each asks for the password again, because each
 * changes how the account is signed into. An account provisioned through an
 * identity provider has no password to re-check; the server is what decides
 * that, and `has_federated_identity` is the hint the form uses so it does not
 * insist on a field nobody can fill.
 */
export const TwoFactorSection = () => {
  const { t } = useTranslation(["settings", "errors"]);
  const { user } = useAuth();
  const mayHaveNoPassword = user?.has_federated_identity ?? false;

  const status = useReadSecondFactorApiV1AuthTotpGet();
  const refreshStatus = () => queryClient.invalidateQueries({ queryKey: ["/api/v1/auth/totp"] });

  const [enrolOpen, setEnrolOpen] = useState(false);
  const [step, setStep] = useState<EnrolStep>("password");
  const [errand, setErrand] = useState<Errand>("enrol");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [uri, setUri] = useState<string | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [offOpen, setOffOpen] = useState(false);
  const [offPassword, setOffPassword] = useState("");
  const [offCode, setOffCode] = useState("");

  const closeEnrol = () => {
    setEnrolOpen(false);
    // The seed and the codes exist here and nowhere else the page can reach;
    // dropping them on close is the point.
    setStep("password");
    setErrand("enrol");
    setPassword("");
    setCode("");
    setSecret(null);
    setUri(null);
    setCodes(null);
    setError(null);
  };

  const begin = useBeginSecondFactorApiV1AuthTotpEnrollPost({
    mutation: {
      onSuccess: (data) => {
        setSecret(data.secret);
        setUri(data.otpauth_uri);
        setStep("scan");
        setError(null);
      },
      onError: (err) => setError(getErrorMessage(err, "settings:twoFactor.enrolError")),
    },
  });

  const confirm = useConfirmSecondFactorApiV1AuthTotpConfirmPost({
    mutation: {
      onSuccess: (data) => {
        setCodes(data.codes);
        setStep("codes");
        setError(null);
        void refreshStatus();
      },
      onError: (err) => {
        setError(getErrorMessage(err, "settings:twoFactor.confirmError"));
        setCode("");
      },
    },
  });

  const regenerate = useRegenerateRecoveryCodesApiV1AuthRecoveryCodesRegeneratePost({
    mutation: {
      onSuccess: (data) => {
        setCodes(data.codes);
        setStep("codes");
        setError(null);
        void refreshStatus();
      },
      onError: (err) => setError(getErrorMessage(err, "settings:twoFactor.regenerateError")),
    },
  });

  const disable = useDisableSecondFactorApiV1AuthTotpDisablePost({
    mutation: {
      onSuccess: () => {
        toast.success(t("twoFactor.turnedOff"));
        setOffOpen(false);
        setOffPassword("");
        setOffCode("");
        void refreshStatus();
      },
      onError: (err) => setError(getErrorMessage(err, "settings:twoFactor.disableError")),
    },
  });

  const submitPassword = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const body = { data: { current_password: password || null } };
    if (errand === "regenerate") {
      regenerate.mutate(body);
      return;
    }
    begin.mutate(body);
  };

  const submitCode = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    confirm.mutate({ data: { code: code.trim() } });
  };

  const submitDisable = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const entered = offCode.trim();
    disable.mutate({
      data: {
        current_password: offPassword || null,
        // Six digits is a live code; anything else is one of the written ones.
        ...(/^\d{6}$/.test(entered) ? { code: entered } : { recovery_code: entered }),
      },
    });
  };

  const copyCodes = () => {
    if (!codes || !navigator?.clipboard) return;
    void navigator.clipboard.writeText(codes.join("\n")).then(() => {
      toast.success(t("twoFactor.codesCopied"));
    });
  };

  const enrolled = status.data?.enrolled ?? false;
  const remaining = status.data?.recovery_codes_remaining ?? 0;

  return (
    <div className="space-y-4">
      {status.isLoading ? (
        <p className="text-muted-foreground text-sm">{t("twoFactor.loading")}</p>
      ) : enrolled ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge>{t("twoFactor.on")}</Badge>
            {status.data?.confirmed_at ? (
              <span className="text-muted-foreground text-sm">
                {t("twoFactor.addedOn", {
                  date: formatDateTime(status.data.confirmed_at),
                })}
              </span>
            ) : null}
          </div>
          <p className="text-muted-foreground text-sm">
            {status.data?.last_used_at
              ? t("twoFactor.lastUsed", { date: formatDateTime(status.data.last_used_at) })
              : t("twoFactor.neverUsed")}
          </p>
          <p className={remaining <= LOW_ON_CODES ? "text-destructive text-sm" : "text-sm"}>
            {t("twoFactor.codesLeft", { count: remaining })}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => {
                setErrand("regenerate");
                setPassword("");
                setError(null);
                setStep("password");
                setCodes(null);
                setEnrolOpen(true);
              }}
            >
              {t("twoFactor.regenerate")}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                setError(null);
                setOffOpen(true);
              }}
            >
              {t("twoFactor.turnOff")}
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-muted-foreground text-sm">{t("twoFactor.notSetUp")}</p>
          <Button
            onClick={() => {
              setErrand("enrol");
              setError(null);
              setEnrolOpen(true);
            }}
          >
            {t("twoFactor.setUp")}
          </Button>
        </div>
      )}

      <Dialog open={enrolOpen} onOpenChange={(open) => (open ? setEnrolOpen(true) : closeEnrol())}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {step === "codes"
                ? t("twoFactor.codesTitle")
                : errand === "regenerate"
                  ? t("twoFactor.regenerateTitle")
                  : t("twoFactor.setUpTitle")}
            </DialogTitle>
            <DialogDescription>
              {step === "password"
                ? errand === "regenerate"
                  ? t("twoFactor.regeneratePrompt")
                  : t("twoFactor.passwordPrompt")
                : step === "scan"
                  ? t("twoFactor.scanPrompt")
                  : t("twoFactor.codesPrompt")}
            </DialogDescription>
          </DialogHeader>

          {step === "password" ? (
            <form className="space-y-4" onSubmit={submitPassword}>
              <div className="space-y-2">
                <Label htmlFor="two-factor-password">{t("twoFactor.passwordLabel")}</Label>
                <Input
                  id="two-factor-password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required={!mayHaveNoPassword}
                />
              </div>
              {error ? <p className="text-destructive text-sm">{error}</p> : null}
              <DialogFooter>
                <Button type="submit" disabled={begin.isPending || regenerate.isPending}>
                  {t("twoFactor.continue")}
                </Button>
              </DialogFooter>
            </form>
          ) : null}

          {step === "scan" && uri && secret ? (
            <form className="space-y-4" onSubmit={submitCode}>
              {/* Always dark on white: a scanner wants contrast, not the page's
                  palette. */}
              <div className="flex justify-center rounded-md bg-white p-4">
                <QRCodeSVG value={uri} size={176} />
              </div>
              <div className="space-y-1">
                <p className="text-muted-foreground text-sm">{t("twoFactor.cannotScan")}</p>
                <code className="block break-all rounded bg-muted px-2 py-1 font-mono text-sm">
                  {secret}
                </code>
              </div>
              <div className="space-y-2">
                <Label htmlFor="two-factor-code">{t("twoFactor.codeLabel")}</Label>
                <Input
                  id="two-factor-code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="123456"
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                  required
                />
              </div>
              {error ? <p className="text-destructive text-sm">{error}</p> : null}
              <DialogFooter>
                <Button type="submit" disabled={confirm.isPending || !code.trim()}>
                  {t("twoFactor.turnOn")}
                </Button>
              </DialogFooter>
            </form>
          ) : null}

          {step === "codes" && codes ? (
            <div className="space-y-4">
              <ul className="grid grid-cols-2 gap-1 rounded bg-muted p-3 font-mono text-sm">
                {codes.map((recoveryCode) => (
                  <li key={recoveryCode}>{recoveryCode}</li>
                ))}
              </ul>
              <p className="text-muted-foreground text-sm">{t("twoFactor.codesWarning")}</p>
              <DialogFooter className="gap-2">
                <Button variant="outline" onClick={copyCodes} type="button">
                  {t("twoFactor.copyCodes")}
                </Button>
                <Button onClick={closeEnrol} type="button">
                  {t("twoFactor.done")}
                </Button>
              </DialogFooter>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog open={offOpen} onOpenChange={setOffOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("twoFactor.turnOffTitle")}</DialogTitle>
            <DialogDescription>{t("twoFactor.turnOffPrompt")}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={submitDisable}>
            <div className="space-y-2">
              <Label htmlFor="two-factor-off-password">{t("twoFactor.passwordLabel")}</Label>
              <Input
                id="two-factor-off-password"
                type="password"
                autoComplete="current-password"
                value={offPassword}
                onChange={(event) => setOffPassword(event.target.value)}
                required={!mayHaveNoPassword}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="two-factor-off-code">{t("twoFactor.codeOrRecoveryLabel")}</Label>
              <Input
                id="two-factor-off-code"
                autoComplete="one-time-code"
                value={offCode}
                onChange={(event) => setOffCode(event.target.value)}
                required
              />
            </div>
            {error ? <p className="text-destructive text-sm">{error}</p> : null}
            <DialogFooter>
              <Button type="submit" variant="destructive" disabled={disable.isPending}>
                {t("twoFactor.turnOff")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
};
