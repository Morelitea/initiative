import { useTranslation } from "react-i18next";

import { BirthdateField } from "@/components/auth/BirthdateField";
import { useAgeConfirmation } from "@/components/auth/useAgeConfirmation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";

/**
 * The screen an account meets when it is already in a community the whole
 * deployment can browse, without having answered how old it is.
 *
 * It blocks the app for the same reason the handle screen does: the answer is
 * owed before anything else happens. Most people never see it — the directory's
 * Join button asks first, and answering there is the whole of it. This is for
 * the ways in that had nobody at a keyboard to ask: an invite redeemed on the
 * way to somewhere else, a group sync, an admin adding somebody, or a community
 * that listed itself long after they joined it.
 *
 * There is deliberately no "no" button. Declining is signing out, which the
 * account can already do, and a decline that emptied their memberships would be
 * this screen deciding something far larger than it was asked.
 */
export const ConfirmAge = () => {
  const { t } = useTranslation(["auth", "common"]);
  const { logout } = useAuth();
  const { birthdate, setBirthdate, submitting, error, confirm } = useAgeConfirmation();

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void confirm();
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
            <BirthdateField
              id="confirm-age-birthdate"
              value={birthdate}
              onChange={setBirthdate}
              disabled={submitting}
            />
            <p className="text-muted-foreground text-xs">{t("confirmAge.scopeNote")}</p>
            {error && <p className="text-destructive text-sm">{error}</p>}
            <Button type="submit" className="w-full" disabled={submitting || !birthdate}>
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
