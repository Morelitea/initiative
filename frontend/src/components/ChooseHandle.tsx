import { useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { UsernameField } from "@/components/UsernameField";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";
import { getErrorMessage } from "@/lib/errorMessage";
import { slugifyUsername } from "@/lib/usernames";

/**
 * The screen an account meets when it was handed a handle rather than picking
 * one — provisioned from single sign-on, or carried over from before handles
 * existed. It blocks the app until they choose, because the handle is how
 * everyone else will see them.
 */
export const ChooseHandle = () => {
  const { t } = useTranslation(["auth", "common"]);
  const { user, refreshUser } = useAuth();
  const [username, setUsername] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const suggestion = slugifyUsername(user?.full_name) || user?.username || "";

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await apiClient.patch("/users/me/username", { username: username.trim().toLowerCase() });
      await refreshUser();
    } catch (err) {
      setError(getErrorMessage(err, "auth:chooseHandle.error"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>{t("chooseHandle.title")}</CardTitle>
          <CardDescription>{t("chooseHandle.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <UsernameField
              id="choose-handle"
              value={username}
              onChange={setUsername}
              suggestion={suggestion}
              disabled={submitting}
            />
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={submitting || !username.trim()}>
              {submitting ? t("common:submitting") : t("chooseHandle.submit")}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};
