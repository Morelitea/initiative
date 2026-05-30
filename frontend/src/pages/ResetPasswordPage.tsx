import { Link, useRouter, useSearch } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
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
import { getErrorMessage } from "@/lib/errorMessage";
import { PASSWORD_MIN_LENGTH, validatePasswordLocal } from "@/lib/passwordPolicy";

export const ResetPasswordPage = () => {
  // Include ``errors`` so ``getErrorMessage`` can map server codes
  // like ``PASSWORD_BREACHED`` without the namespace having to
  // lazy-load mid-submit.
  const { t } = useTranslation(["auth", "errors"]);
  const searchParams = useSearch({ strict: false }) as { token?: string };
  const router = useRouter();
  const token = searchParams.token ?? "";
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [status, setStatus] = useState<"idle" | "submitting" | "success">("idle");
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token) {
      setError(t("resetPassword.missingToken"));
      return;
    }
    if (password !== confirmPassword) {
      setError(t("resetPassword.passwordMismatch"));
      return;
    }
    const policyError = validatePasswordLocal(password);
    if (policyError) {
      setError(policyError);
      return;
    }
    setStatus("submitting");
    setError(null);
    try {
      await apiClient.post("/auth/password/reset", { token, password });
      setStatus("success");
    } catch (err) {
      console.error(err);
      // ``getErrorMessage`` maps server codes like ``PASSWORD_BREACHED``
      // to the localized string from ``errors.json``; falls back to the
      // generic reset-page error when the code isn't recognized.
      setError(getErrorMessage(err, "auth:resetPassword.error"));
      setStatus("idle");
    }
  };

  if (!token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/60 px-4 py-12">
        <Card className="w-full max-w-md shadow-lg">
          <CardHeader>
            <CardTitle>{t("resetPassword.titleInvalid")}</CardTitle>
            <CardDescription>{t("resetPassword.subtitleInvalid")}</CardDescription>
          </CardHeader>
          <CardFooter className="text-muted-foreground text-sm">
            <Link className="text-primary underline-offset-4 hover:underline" to="/forgot-password">
              {t("resetPassword.requestReset")}
            </Link>
          </CardFooter>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/60 px-4 py-12">
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader>
          <CardTitle>{t("resetPassword.title")}</CardTitle>
          <CardDescription>{t("resetPassword.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent>
          {status === "success" ? (
            <div className="space-y-4 text-primary text-sm">
              <p>{t("resetPassword.success")}</p>
              <Button className="w-full" onClick={() => router.navigate({ to: "/login" })}>
                {t("resetPassword.goToSignIn")}
              </Button>
            </div>
          ) : (
            <form className="space-y-4" onSubmit={handleSubmit}>
              <div className="space-y-2">
                <Label htmlFor="new-password">{t("resetPassword.newPasswordLabel")}</Label>
                <Input
                  id="new-password"
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
              <div className="space-y-2">
                <Label htmlFor="confirm-password">{t("resetPassword.confirmPasswordLabel")}</Label>
                <Input
                  id="confirm-password"
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  required
                />
              </div>
              <Button className="w-full" type="submit" disabled={status === "submitting"}>
                {status === "submitting"
                  ? t("resetPassword.submitting")
                  : t("resetPassword.submit")}
              </Button>
              {error ? <p className="text-destructive text-sm">{error}</p> : null}
            </form>
          )}
        </CardContent>
        {status !== "success" ? (
          <CardFooter className="text-muted-foreground text-sm">
            <Link className="text-primary underline-offset-4 hover:underline" to="/forgot-password">
              {t("resetPassword.needNewLink")}
            </Link>
          </CardFooter>
        ) : null}
      </Card>
    </div>
  );
};
