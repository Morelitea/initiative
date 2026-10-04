import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useCompleteVendorSetup } from "@/hooks/useAppServices";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";

/**
 * Where an app vendor's own setup sends the operator back.
 *
 * The vendor returns with a code and the state the setup began with; this page
 * hands both to the server, which exchanges the code and writes the vendor
 * values, and then returns to the app services list.
 */
export const SettingsVendorSetupPage = () => {
  const { t } = useTranslation("settings");
  const navigate = useNavigate();
  const { registrationId } = useParams({ strict: false }) as { registrationId?: string };
  const { code, state } = useSearch({ strict: false }) as { code?: string; state?: string };
  const complete = useCompleteVendorSetup();
  const [error, setError] = useState<string | null>(null);
  // A state is spent by the first completion, so it is sent once.
  const sent = useRef(false);

  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    const id = Number(registrationId);
    if (!code || !state || !Number.isInteger(id)) {
      setError(t("appServices.vendorSetupFailed"));
      return;
    }
    complete.mutate(
      { registrationId: id, code, state },
      {
        onSuccess: () => {
          toast.success(t("appServices.vendorSetupDone"));
          void navigate({ to: "/settings/platform/integrations", replace: true });
        },
        onError: (err) => setError(getErrorMessage(err, "settings:appServices.vendorSetupFailed")),
      }
    );
  }, [code, state, registrationId, complete, navigate, t]);

  return (
    <div className="space-y-3">
      <h2 className="font-semibold text-lg">{t("appServices.vendorSetupTitle")}</h2>
      {error ? (
        <>
          <p className="text-destructive text-sm" role="alert">
            {error}
          </p>
          <Button asChild variant="outline" size="sm">
            <Link to="/settings/platform/integrations">{t("appServices.vendorSetupBack")}</Link>
          </Button>
        </>
      ) : (
        <p className="text-muted-foreground text-sm">{t("appServices.vendorSetupFinishing")}</p>
      )}
    </div>
  );
};
