import { Lock } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAccountTimeOut } from "@/hooks/useAccountTimeOut";
import { useAuth } from "@/hooks/useAuth";

/**
 * The screen a suspended account meets in place of the app. It is in time out:
 * it reaches no community and changes nothing until the suspension is lifted,
 * and everything it had is kept for when it is. What it can do here is read
 * why, see whom to contact, and sign out.
 */
export const AccountTimeOut = () => {
  const { t } = useTranslation("auth");
  const { logout } = useAuth();
  const { data } = useAccountTimeOut();

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-muted">
            <Lock className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
          </div>
          <CardTitle>{t("timeOut.title")}</CardTitle>
          <CardDescription>{t("timeOut.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {data?.reason ? (
            <p className="rounded-md bg-muted p-3 text-sm">
              {t("timeOut.reason", { reason: data.reason })}
            </p>
          ) : null}
          <p className="text-sm">
            {data?.contact_email
              ? t("timeOut.contact", { email: data.contact_email })
              : t("timeOut.contactNobody")}
          </p>
          <Button variant="outline" className="w-full" onClick={() => void logout()}>
            {t("timeOut.signOut")}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
};
