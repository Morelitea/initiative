import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { AppServiceRegistrationRead } from "@/api/generated/initiativeAPI.schemas";
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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { hasGrant, parseAllowedOrigins } from "@/lib/appServices";

/** What the operator stated, before it is shaped into a create or a patch. */
export interface AppServiceFormValues {
  publicId: string;
  baseUrl: string;
  /** Where a browser loads the app, or "" when that is the base URL too. */
  embedOrigin: string;
  allowedOrigins: string[];
  /** The new shared secret, or null to leave the stored one alone. */
  secret: string | null;
  delegation: boolean;
  /** Parsed JWKS, or null to leave the stored key set untouched. */
  delegationJwks: Record<string, unknown> | null;
  appDirectory: boolean;
  mandatory: boolean;
}

interface FormState {
  publicId: string;
  baseUrl: string;
  embedOrigin: string;
  allowedOrigins: string;
  secret: string;
  delegation: boolean;
  delegationJwks: string;
  appDirectory: boolean;
  mandatory: boolean;
}

const EMPTY_FORM: FormState = {
  publicId: "",
  baseUrl: "",
  embedOrigin: "",
  allowedOrigins: "",
  secret: "",
  delegation: false,
  delegationJwks: "",
  appDirectory: false,
  mandatory: false,
};

export interface AppServiceFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The registration being edited, or null to register a new one. */
  editing: AppServiceRegistrationRead | null;
  saving: boolean;
  onSubmit: (values: AppServiceFormValues) => void;
}

/**
 * Register or edit one app service.
 *
 * The shared secret is write-only end to end: the API reports only whether one
 * is stored, so this form can say that it exists and offer to replace it, and
 * has nothing to reveal.
 */
export const AppServiceFormDialog = ({
  open,
  onOpenChange,
  editing,
  saving,
  onSubmit,
}: AppServiceFormDialogProps) => {
  const { t } = useTranslation("settings");
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [replaceSecret, setReplaceSecret] = useState(false);
  // Only whether the paste is JSON at all. Whether it is a key set we could
  // verify against is the server's answer, and it gives a message code.
  const [jwksError, setJwksError] = useState<string | null>(null);

  // Re-seed whenever the dialog opens, so a reopened form never shows the
  // previous row's values (and never carries a typed secret forward).
  useEffect(() => {
    if (!open) return;
    if (editing) {
      setForm({
        publicId: editing.public_id,
        baseUrl: editing.base_url,
        embedOrigin: editing.embed_origin ?? "",
        allowedOrigins: editing.allowed_origins.join("\n"),
        secret: "",
        delegation: hasGrant(editing, "delegation"),
        delegationJwks: editing.delegation_jwks
          ? JSON.stringify(editing.delegation_jwks, null, 2)
          : "",
        appDirectory: hasGrant(editing, "app_directory"),
        mandatory: editing.mandatory,
      });
      setJwksError(null);
      // A registration with no secret cannot complete a handshake, so go
      // straight to the input rather than hiding it behind an opt-in.
      setReplaceSecret(!editing.has_secret);
    } else {
      setForm(EMPTY_FORM);
      setReplaceSecret(true);
      setJwksError(null);
    }
  }, [open, editing]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    // An emptied box clears the stored set; an untouched one on a row that
    // never had a key leaves it alone. Both arrive as {} vs null respectively,
    // which is the distinction the PATCH reads. Switching delegation off
    // clears it too — the box is hidden then, and a key set the form no longer
    // shows is not one it should keep sending.
    const typed = form.delegation ? form.delegationJwks.trim() : "";
    let delegationJwks: Record<string, unknown> | null = null;
    if (typed) {
      try {
        delegationJwks = JSON.parse(typed) as Record<string, unknown>;
      } catch {
        setJwksError(t("appServices.delegationJwksInvalid"));
        return;
      }
    } else if (editing?.delegation_jwks) {
      delegationJwks = {};
    }
    setJwksError(null);

    onSubmit({
      delegationJwks,
      publicId: form.publicId.trim(),
      baseUrl: form.baseUrl.trim(),
      embedOrigin: form.embedOrigin.trim(),
      allowedOrigins: parseAllowedOrigins(form.allowedOrigins),
      secret: replaceSecret && form.secret ? form.secret : null,
      delegation: form.delegation,
      appDirectory: form.appDirectory,
      mandatory: form.mandatory,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {editing ? t("appServices.editTitle") : t("appServices.createTitle")}
          </DialogTitle>
          <DialogDescription>
            {editing ? t("appServices.editDescription") : t("appServices.createDescription")}
          </DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="app-service-public-id">{t("appServices.publicIdLabel")}</Label>
            <Input
              id="app-service-public-id"
              value={form.publicId}
              onChange={(event) => setForm((prev) => ({ ...prev, publicId: event.target.value }))}
              placeholder={t("appServices.publicIdPlaceholder")}
              maxLength={120}
              disabled={Boolean(editing)}
              autoComplete="off"
            />
            <p className="text-muted-foreground text-xs">
              {editing ? t("appServices.publicIdHelpEdit") : t("appServices.publicIdHelp")}
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="app-service-base-url">{t("appServices.baseUrlLabel")}</Label>
            <Input
              id="app-service-base-url"
              value={form.baseUrl}
              onChange={(event) => setForm((prev) => ({ ...prev, baseUrl: event.target.value }))}
              placeholder={t("appServices.baseUrlPlaceholder")}
              maxLength={1000}
              required
            />
            <p className="text-muted-foreground text-xs">{t("appServices.baseUrlHelp")}</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="app-service-embed-origin">{t("appServices.embedOriginLabel")}</Label>
            <Input
              id="app-service-embed-origin"
              value={form.embedOrigin}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, embedOrigin: event.target.value }))
              }
              placeholder={t("appServices.embedOriginPlaceholder")}
              maxLength={1000}
            />
            <p className="text-muted-foreground text-xs">{t("appServices.embedOriginHelp")}</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="app-service-origins">{t("appServices.allowedOriginsLabel")}</Label>
            <Textarea
              id="app-service-origins"
              value={form.allowedOrigins}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, allowedOrigins: event.target.value }))
              }
              placeholder={t("appServices.allowedOriginsPlaceholder")}
              rows={3}
            />
            <p className="text-muted-foreground text-xs">
              {editing
                ? t("appServices.allowedOriginsHelpEdit")
                : t("appServices.allowedOriginsHelp")}
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="app-service-secret">{t("appServices.secretLabel")}</Label>
            {editing && (
              <p className="text-muted-foreground text-xs">
                {editing.has_secret
                  ? t("appServices.secretStored")
                  : t("appServices.secretMissing")}
              </p>
            )}
            {editing?.has_secret && (
              <label className="flex items-center gap-2 text-muted-foreground text-xs">
                <input
                  type="checkbox"
                  checked={replaceSecret}
                  onChange={(event) => {
                    setReplaceSecret(event.target.checked);
                    if (!event.target.checked) setForm((prev) => ({ ...prev, secret: "" }));
                  }}
                />
                {t("appServices.replaceSecret")}
              </label>
            )}
            {replaceSecret && (
              <>
                <Input
                  id="app-service-secret"
                  type="password"
                  value={form.secret}
                  onChange={(event) => setForm((prev) => ({ ...prev, secret: event.target.value }))}
                  placeholder={t("appServices.secretPlaceholder")}
                  autoComplete="new-password"
                  required={!editing}
                />
                <p className="text-muted-foreground text-xs">{t("appServices.secretHelp")}</p>
              </>
            )}
          </div>

          <div className="space-y-2 rounded-md border border-amber-500/50 p-3">
            <div>
              <p className="font-medium text-sm">{t("appServices.grantsTitle")}</p>
              <p className="text-muted-foreground text-xs">{t("appServices.grantsHelp")}</p>
            </div>
            <div className="flex items-start justify-between gap-3 pt-1">
              <div>
                <Label htmlFor="app-service-delegation" className="font-medium">
                  {t("appServices.delegationLabel")}
                </Label>
                <p className="text-muted-foreground text-xs">{t("appServices.delegationHelp")}</p>
              </div>
              <Switch
                id="app-service-delegation"
                checked={form.delegation}
                onCheckedChange={(checked) =>
                  setForm((prev) => ({ ...prev, delegation: Boolean(checked) }))
                }
              />
            </div>
            {form.delegation && (
              <div className="space-y-2 pt-1">
                <Label htmlFor="app-service-delegation-jwks">
                  {t("appServices.delegationJwksLabel")}
                </Label>
                <Textarea
                  id="app-service-delegation-jwks"
                  value={form.delegationJwks}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, delegationJwks: event.target.value }))
                  }
                  rows={6}
                  className="font-mono text-xs"
                  placeholder={'{\n  "keys": [ … ]\n}'}
                />
                <p className="text-muted-foreground text-xs">
                  {t("appServices.delegationJwksHelp")}
                </p>
                {jwksError && <p className="text-destructive text-xs">{jwksError}</p>}
              </div>
            )}
            <div className="flex items-start justify-between gap-3 pt-1">
              <div>
                <Label htmlFor="app-service-app-directory" className="font-medium">
                  {t("appServices.appDirectoryLabel")}
                </Label>
                <p className="text-muted-foreground text-xs">{t("appServices.appDirectoryHelp")}</p>
              </div>
              <Switch
                id="app-service-app-directory"
                checked={form.appDirectory}
                onCheckedChange={(checked) =>
                  setForm((prev) => ({ ...prev, appDirectory: Boolean(checked) }))
                }
              />
            </div>

            <div className="flex items-start justify-between gap-3 pt-1">
              <div>
                <Label htmlFor="app-service-mandatory" className="font-medium">
                  {t("appServices.mandatoryLabel")}
                </Label>
                <p className="text-muted-foreground text-xs">{t("appServices.mandatoryHelp")}</p>
              </div>
              <Switch
                id="app-service-mandatory"
                checked={form.mandatory}
                onCheckedChange={(checked) =>
                  setForm((prev) => ({ ...prev, mandatory: Boolean(checked) }))
                }
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={saving}
            >
              {t("appServices.cancel")}
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? t("appServices.saving") : t("appServices.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
