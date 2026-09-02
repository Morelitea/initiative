import { useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/useAuth";
import { getErrorMessage } from "@/lib/errorMessage";

/**
 * The screen an account meets when it is already in a community the whole
 * deployment can browse, without having said how old it is.
 *
 * It blocks the app for the same reason the handle screen does: the answer is
 * owed before anything else happens, and there is no version of the app that
 * works without it. Most people never see it — the directory's Join button
 * asks first, and ticking the box there is the whole of it. This is for the
 * ways in that had nobody at a keyboard to ask: an invite redeemed on the way
 * to somewhere else, a group sync, an admin adding somebody, or a guild that
 * listed itself long after they joined it.
 *
 * There is deliberately no "no" button. Declining is signing out, which the
 * account can already do, and a decline that emptied their memberships would
 * be this screen deciding something far larger than it was asked.
 */
export const ConfirmAge = () => {
  const { t } = useTranslation(["auth", "common"]);
  const { refreshUser, logout } = useAuth();
  const [checked, setChecked] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await apiClient.post("/users/me/age-confirmation", { confirmed: true });
      await refreshUser();
    } catch (err) {
      setError(getErrorMessage(err, "auth:confirmAge.error"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>{t("confirmAge.title")}</CardTitle>
          <CardDescription>{t("confirmAge.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="flex items-start gap-3">
              <Checkbox
                id="confirm-age"
                checked={checked}
                onCheckedChange={(value) => setChecked(value === true)}
                disabled={submitting}
              />
              <Label htmlFor="confirm-age" className="font-normal leading-snug">
                {t("confirmAge.checkboxLabel")}
              </Label>
            </div>
            {error && <p className="text-destructive text-sm">{error}</p>}
            <Button type="submit" className="w-full" disabled={submitting || !checked}>
              {submitting ? t("common:submitting") : t("confirmAge.submit")}
            </Button>
            <Button type="button" variant="ghost" className="w-full" onClick={() => void logout()}>
              {t("confirmAge.signOut")}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};
