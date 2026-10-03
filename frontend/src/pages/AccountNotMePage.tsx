import { Link, useSearch } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { readAccountChange, signOutEverywhere } from "@/api/generated/auth/auth";
import { ServerChip } from "@/components/auth/ServerChoice";
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
import { useAuth } from "@/hooks/useAuth";
import { getErrorMessage } from "@/lib/errorMessage";

type Step = "reading" | "ready" | "done" | "invalid";

/** What each account notice was about, by the part of its name before the dot. */
const SUBJECT_KEYS = {
  address: "notMe.subject.address",
  passkey: "notMe.subject.passkey",
  secondFactor: "notMe.subject.secondFactor",
  passwordChanged: "notMe.subject.password",
  passwordRemoved: "notMe.subject.password",
} as const;

const subjectKey = (notice: string) => {
  const section = notice.split(".")[0];
  return section in SUBJECT_KEYS
    ? SUBJECT_KEYS[section as keyof typeof SUBJECT_KEYS]
    : "notMe.subject.account";
};

/**
 * Where the "This wasn't me" button in an account email lands.
 *
 * Opening the link changes nothing: mail scanners open links too. The page
 * reads the token, says what will happen, and only the button signs the
 * account out everywhere.
 */
export const AccountNotMePage = () => {
  const { t } = useTranslation("auth");
  const { token } = useSearch({ strict: false }) as { token?: string };
  const { user, refreshUser } = useAuth();
  const [step, setStep] = useState<Step>(token ? "reading" : "invalid");
  const [notice, setNotice] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    readAccountChange({ token })
      .then((answer) => {
        setNotice(answer.notice);
        setStep("ready");
      })
      .catch(() => setStep("invalid"));
  }, [token]);

  const signOut = async () => {
    if (!token) return;
    setSubmitting(true);
    setError(null);
    try {
      await signOutEverywhere({ token });
      setStep("done");
      // This browser may be one of the sessions just ended. Asking for its
      // own account finds out, and the usual expiry handling signs it out
      // here too; a browser signed in to somebody else stays as it is.
      if (user) void refreshUser().catch(() => undefined);
    } catch (err) {
      setError(getErrorMessage(err, "auth:notMe.failed"));
    } finally {
      setSubmitting(false);
    }
  };

  const subject = t(subjectKey(notice));

  return (
    <SignInFrame>
      <Card className="w-full max-w-md shadow-lg">
        {step === "done" ? (
          <CardHeader>
            <CardTitle>{t("notMe.doneTitle")}</CardTitle>
            <CardDescription>{t("notMe.doneBody")}</CardDescription>
          </CardHeader>
        ) : step === "invalid" ? (
          <CardHeader>
            <CardTitle>{t("notMe.invalidTitle")}</CardTitle>
            <CardDescription>{t("notMe.invalidBody")}</CardDescription>
          </CardHeader>
        ) : (
          <>
            <CardHeader>
              <CardTitle>{t("notMe.title")}</CardTitle>
              <CardDescription>{t("notMe.description", { subject })}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-muted-foreground text-sm">{t("notMe.whatHappens")}</p>
              {error ? <p className="text-destructive text-sm">{error}</p> : null}
              <Button
                className="w-full"
                onClick={() => void signOut()}
                disabled={step !== "ready" || submitting}
              >
                {t("notMe.confirm")}
              </Button>
            </CardContent>
          </>
        )}
        {step === "done" || step === "invalid" ? (
          <CardFooter className="flex flex-col gap-2 text-sm">
            <Button asChild className="w-full">
              <Link to="/login">{t("notMe.signIn")}</Link>
            </Button>
            <Link className="text-primary underline-offset-4 hover:underline" to="/forgot-password">
              {t("notMe.resetPassword")}
            </Link>
          </CardFooter>
        ) : null}
        <CardFooter>
          <ServerChip />
        </CardFooter>
      </Card>
    </SignInFrame>
  );
};
