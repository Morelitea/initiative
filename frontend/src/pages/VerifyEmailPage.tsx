import { useEffect, useState } from "react";
import { Link, useSearch } from "@tanstack/react-router";
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

type VerificationStatus = "pending" | "success" | "error";

export const VerifyEmailPage = () => {
  const { t } = useTranslation("auth");
  const searchParams = useSearch({ strict: false }) as { token?: string };
  const token = searchParams.token;
  const [status, setStatus] = useState<VerificationStatus>("pending");
  const [message, setMessage] = useState(t("verifyEmail.verifying"));

  useEffect(() => {
    const verify = async () => {
      if (!token) {
        setStatus("error");
        setMessage(t("verifyEmail.missingLink"));
        return;
      }
      try {
        await apiClient.post("/auth/verification/confirm", { token });
        setStatus("success");
        setMessage(t("verifyEmail.success"));
      } catch (err) {
        console.error(err);
        setStatus("error");
        setMessage(t("verifyEmail.error"));
      }
    };
    void verify();
  }, [token, t]);

  return (
    <div className="bg-muted/60 flex min-h-screen items-center justify-center px-4 py-12">
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader>
          <CardTitle>{t("verifyEmail.title")}</CardTitle>
          <CardDescription>{message}</CardDescription>
        </CardHeader>
        <CardContent>
          {status === "pending" ? (
            <p className="text-muted-foreground text-sm">{t("verifyEmail.hangTight")}</p>
          ) : null}
        </CardContent>
        <CardFooter className="text-muted-foreground flex flex-col gap-2 text-sm">
          {status === "success" ? (
            <Button asChild className="w-full">
              <Link to="/login">{t("verifyEmail.goToSignIn")}</Link>
            </Button>
          ) : (
            <Link className="text-primary underline-offset-4 hover:underline" to="/register">
              {t("verifyEmail.needToRegister")}
            </Link>
          )}
        </CardFooter>
      </Card>
    </div>
  );
};
