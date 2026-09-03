import { useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";
import { getErrorMessage } from "@/lib/errorMessage";

/**
 * Answering the age question, wherever it is asked.
 *
 * Two surfaces ask it — the screen an account meets when it already belongs
 * somewhere open, and the dialog the directory's Join button opens — and they
 * differ only in the chrome around them. The date, what is done with it and
 * what comes back when it is refused live here, so the two cannot drift into
 * disagreeing about any of it.
 *
 * The date is sent and not kept: the server compares it, answers, and writes
 * down only that the question was answered. Nothing here holds it after the
 * request, and the field is cleared on the way out.
 */
export const useAgeConfirmation = (onConfirmed?: () => void) => {
  const { t } = useTranslation(["auth"]);
  const { refreshUser } = useAuth();
  const [birthdate, setBirthdate] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confirm = async () => {
    if (!birthdate) {
      setError(t("auth:confirmAge.required"));
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await apiClient.post("/users/me/age-confirmation", { birthdate });
      await refreshUser();
      setBirthdate("");
      onConfirmed?.();
    } catch (err) {
      setError(getErrorMessage(err, "auth:confirmAge.error"));
    } finally {
      setSubmitting(false);
    }
  };

  return { birthdate, setBirthdate, submitting, error, confirm };
};
