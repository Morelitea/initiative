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
import { parseAllowedOrigins } from "@/lib/appServices";

/** What the operator stated, before it is shaped into a create or a patch. */
export interface AppServiceFormValues {
  publicId: string;
  /** The catalog uid of the listing this app speaks for. */
  listingUid: string;
  baseUrl: string;
  /** Where a browser loads the app, or "" when that is the base URL too. */
  embedOrigin: string;
  allowedOrigins: string[];
  /** Parsed JWKS, or null to leave the stored key set untouched. */
  jwks: Record<string, unknown> | null;
  /** Where the app publishes its key set, or "" for none. */
  jwksUri: string;
  mandatory: boolean;
}

interface FormState {
  publicId: string;
  listingUid: string;
  baseUrl: string;
  embedOrigin: string;
  allowedOrigins: string;
  jwks: string;
  jwksUri: string;
  mandatory: boolean;
}

const EMPTY_FORM: FormState = {
  publicId: "",
  listingUid: "",
  baseUrl: "",
  embedOrigin: "",
  allowedOrigins: "",
  jwks: "",
  jwksUri: "",
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
 * Nothing on a registration is secret: its keys are public keys, either
 * pasted as a key set or fetched from the address the app publishes them at.
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
  // Only whether the paste is JSON at all. Whether it is a key set we could
  // verify against is the server's answer, and it gives a message code.
  const [jwksError, setJwksError] = useState<string | null>(null);

  // Re-seed whenever the dialog opens, so a reopened form never shows the
  // previous row's values.
  useEffect(() => {
    if (!open) return;
    if (editing) {
      setForm({
        publicId: editing.public_id,
        listingUid: editing.listing_uid ?? "",
        baseUrl: editing.base_url ?? "",
        embedOrigin: editing.embed_origin ?? "",
        allowedOrigins: editing.allowed_origins.join("\n"),
        jwks: editing.jwks ? JSON.stringify(editing.jwks, null, 2) : "",
        jwksUri: editing.jwks_uri ?? "",
        mandatory: editing.mandatory,
      });
    } else {
      setForm(EMPTY_FORM);
    }
    setJwksError(null);
  }, [open, editing]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    // An emptied box clears the stored set; an untouched one on a row that
    // never had a key leaves it alone. Both arrive as {} vs null respectively,
    // which is the distinction the PATCH reads.
    const typed = form.jwks.trim();
    let jwks: Record<string, unknown> | null = null;
    if (typed) {
      try {
        jwks = JSON.parse(typed) as Record<string, unknown>;
      } catch {
        setJwksError(t("appServices.jwksInvalid"));
        return;
      }
    } else if (editing?.jwks) {
      jwks = {};
    }
    setJwksError(null);

    onSubmit({
      jwks,
      publicId: form.publicId.trim(),
      listingUid: form.listingUid.trim(),
      baseUrl: form.baseUrl.trim(),
      embedOrigin: form.embedOrigin.trim(),
      allowedOrigins: parseAllowedOrigins(form.allowedOrigins),
      jwksUri: form.jwksUri.trim(),
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
              required={!editing}
              autoComplete="off"
            />
            <p className="text-muted-foreground text-xs">
              {editing ? t("appServices.publicIdHelpEdit") : t("appServices.publicIdHelp")}
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="app-service-listing-uid">{t("appServices.listingUidLabel")}</Label>
            <Input
              id="app-service-listing-uid"
              value={form.listingUid}
              onChange={(event) => setForm((prev) => ({ ...prev, listingUid: event.target.value }))}
              placeholder={t("appServices.listingUidPlaceholder")}
              maxLength={14}
              className="font-mono"
              required
              autoComplete="off"
              spellCheck={false}
            />
            <p className="text-muted-foreground text-xs">{t("appServices.listingUidHelp")}</p>
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

          <fieldset className="rounded-md border p-3">
            {/* Floated so the legend sits inside the border like the other headings. */}
            <legend className="float-left w-full font-medium text-sm">
              {t("appServices.keysTitle")}
            </legend>
            <div className="clear-both space-y-3">
              <p className="text-muted-foreground text-xs">{t("appServices.keysHelp")}</p>

              <div className="space-y-2">
                <Label htmlFor="app-service-jwks">{t("appServices.jwksLabel")}</Label>
                <Textarea
                  id="app-service-jwks"
                  value={form.jwks}
                  onChange={(event) => setForm((prev) => ({ ...prev, jwks: event.target.value }))}
                  rows={6}
                  className="font-mono text-xs"
                  placeholder={'{\n  "keys": [ … ]\n}'}
                />
                <p className="text-muted-foreground text-xs">{t("appServices.jwksHelp")}</p>
                {jwksError && <p className="text-destructive text-xs">{jwksError}</p>}
              </div>

              <div className="space-y-2">
                <Label htmlFor="app-service-jwks-uri">{t("appServices.jwksUriLabel")}</Label>
                <Input
                  id="app-service-jwks-uri"
                  value={form.jwksUri}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, jwksUri: event.target.value }))
                  }
                  placeholder={t("appServices.jwksUriPlaceholder")}
                  maxLength={1000}
                  autoComplete="off"
                />
                <p className="text-muted-foreground text-xs">{t("appServices.jwksUriHelp")}</p>
              </div>
            </div>
          </fieldset>

          <div className="space-y-2 rounded-md border border-amber-500/50 p-3">
            <div className="flex items-start justify-between gap-3">
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
