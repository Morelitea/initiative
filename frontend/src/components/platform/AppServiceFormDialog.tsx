import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  AppServicePublishedKeyRead,
  AppServiceRegistrationRead,
} from "@/api/generated/initiativeAPI.schemas";
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
import { useAppServiceKeys, useConnectAppService } from "@/hooks/useAppServices";
import { parseAllowedOrigins } from "@/lib/appServices";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { localized } from "@/lib/widgets/widgetMeta";

/** What the operator stated, before it is shaped into a create or a patch. */
export interface AppServiceFormValues {
  publicId: string;
  baseUrl: string;
  /** Where a browser loads the app, or "" when that is the base URL too. */
  embedOrigin: string;
  allowedOrigins: string[];
  /** Parsed JWKS, or null to leave the stored key set untouched. */
  jwks: Record<string, unknown> | null;
  /** Where the app publishes its key set, or "" for none. */
  jwksUri: string;
  mandatory: boolean;
  /** Vendor values that were typed, by key. "" clears one; a key left out is kept. */
  vendorValues: Record<string, string>;
}

interface FormState {
  publicId: string;
  baseUrl: string;
  embedOrigin: string;
  allowedOrigins: string;
  jwks: string;
  jwksUri: string;
  mandatory: boolean;
  vendorValues: Record<string, string>;
}

const EMPTY_FORM: FormState = {
  publicId: "",
  baseUrl: "",
  embedOrigin: "",
  allowedOrigins: "",
  jwks: "",
  jwksUri: "",
  mandatory: false,
  vendorValues: {},
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
 * Give one app service its deployment facts. What the app is and may do comes
 * from its listing, and is not edited here.
 *
 * Its keys are public keys, either pasted as a key set or fetched from the
 * address the app publishes them at. Connect reads the set the app serves at
 * its saved base URL, shows each key's fingerprint, and pins the set once the
 * operator confirms it. The one secret a registration holds is
 * what the operator supplies for the app's vendor client, as the app's listing
 * asks for it: a secret value is written here and never shown again.
 */
export const AppServiceFormDialog = ({
  open,
  onOpenChange,
  editing,
  saving,
  onSubmit,
}: AppServiceFormDialogProps) => {
  const { t, i18n } = useTranslation("settings");
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  // Only whether the paste is JSON at all. Whether it is a key set we could
  // verify against is the server's answer, and it gives a message code.
  const [jwksError, setJwksError] = useState<string | null>(null);
  // The keys Connect read, waiting for the operator to confirm them.
  const [servedKeys, setServedKeys] = useState<AppServicePublishedKeyRead[] | null>(null);
  const [connectError, setConnectError] = useState<string | null>(null);
  const readKeys = useAppServiceKeys();
  const connect = useConnectAppService();

  // Re-seed whenever the dialog opens, so a reopened form never shows the
  // previous row's values.
  useEffect(() => {
    if (!open) return;
    if (editing) {
      setForm({
        publicId: editing.public_id,
        baseUrl: editing.base_url ?? "",
        embedOrigin: editing.embed_origin ?? "",
        allowedOrigins: editing.allowed_origins.join("\n"),
        jwks: editing.jwks ? JSON.stringify(editing.jwks, null, 2) : "",
        jwksUri: editing.jwks_uri ?? "",
        mandatory: editing.mandatory,
        vendorValues: {},
      });
    } else {
      setForm(EMPTY_FORM);
    }
    setJwksError(null);
    setServedKeys(null);
    setConnectError(null);
  }, [open, editing]);

  const handleReadKeys = () => {
    if (!editing) return;
    setServedKeys(null);
    setConnectError(null);
    readKeys.mutate(editing.id, {
      onSuccess: setServedKeys,
      onError: (error) =>
        setConnectError(getErrorMessage(error, "settings:appServices.connectError")),
    });
  };

  const handleConnect = () => {
    if (!editing || !servedKeys) return;
    connect.mutate(
      { registrationId: editing.id, fingerprints: servedKeys.map((key) => key.fingerprint) },
      {
        onSuccess: (registration) => {
          setForm((prev) => ({
            ...prev,
            jwks: registration.jwks ? JSON.stringify(registration.jwks, null, 2) : "",
          }));
          setServedKeys(null);
          toast.success(t("appServices.connected"));
        },
        onError: (error) => {
          // A set that changed has to be read and checked again.
          setServedKeys(null);
          setConnectError(getErrorMessage(error, "settings:appServices.connectError"));
        },
      }
    );
  };

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
      baseUrl: form.baseUrl.trim(),
      embedOrigin: form.embedOrigin.trim(),
      allowedOrigins: parseAllowedOrigins(form.allowedOrigins),
      jwksUri: form.jwksUri.trim(),
      mandatory: form.mandatory,
      vendorValues: Object.fromEntries(
        Object.entries(form.vendorValues).map(([key, value]) => [key, value.trim()])
      ),
    });
  };

  const vendorFields = editing?.vendor_fields ?? [];

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

              {editing?.base_url && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-muted-foreground text-xs">{t("appServices.connectHelp")}</p>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={handleReadKeys}
                      disabled={readKeys.isPending || connect.isPending}
                    >
                      {readKeys.isPending
                        ? t("appServices.connectReading")
                        : t("appServices.connect")}
                    </Button>
                  </div>
                  {servedKeys && (
                    <section
                      className="space-y-2 rounded-md border p-3"
                      aria-label={t("appServices.connectKeysTitle")}
                    >
                      <p className="font-medium text-sm">{t("appServices.connectKeysTitle")}</p>
                      <p className="text-muted-foreground text-xs">
                        {t("appServices.connectKeysHelp")}
                      </p>
                      <ul className="space-y-1">
                        {servedKeys.map((key) => (
                          <li key={`${key.kid}:${key.fingerprint}`} className="text-xs">
                            <span className="text-muted-foreground">
                              {t("appServices.connectKid", { kid: key.kid })}
                            </span>
                            <code className="block break-all font-mono">{key.fingerprint}</code>
                          </li>
                        ))}
                      </ul>
                      <div className="flex justify-end gap-2">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => setServedKeys(null)}
                          disabled={connect.isPending}
                        >
                          {t("appServices.connectDismiss")}
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          onClick={handleConnect}
                          disabled={connect.isPending}
                        >
                          {connect.isPending
                            ? t("appServices.connectPinning")
                            : t("appServices.connectConfirm")}
                        </Button>
                      </div>
                    </section>
                  )}
                  {connectError && <p className="text-destructive text-xs">{connectError}</p>}
                </div>
              )}

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

          {editing && vendorFields.length > 0 && (
            <fieldset className="rounded-md border p-3">
              <legend className="float-left w-full font-medium text-sm">
                {t("appServices.vendorTitle")}
              </legend>
              <div className="clear-both space-y-3">
                <p className="text-muted-foreground text-xs">{t("appServices.vendorHelp")}</p>

                {vendorFields.map((field) => {
                  const id = `app-service-vendor-${field.key}`;
                  const isSecret = field.type === "secret";
                  const isSet = editing.vendor_set.includes(field.key);
                  const typed = form.vendorValues[field.key];
                  const value = typed ?? (isSecret ? "" : (editing.vendor_values[field.key] ?? ""));
                  return (
                    <div key={field.key} className="space-y-2">
                      <Label htmlFor={id}>
                        {localized(field.label, i18n.language) ?? field.key}
                        {field.required && <span aria-hidden> *</span>}
                      </Label>
                      {/* A secret may be a PEM key, which spans lines. */}
                      {isSecret ? (
                        <Textarea
                          id={id}
                          value={value}
                          onChange={(event) =>
                            setForm((prev) => ({
                              ...prev,
                              vendorValues: {
                                ...prev.vendorValues,
                                [field.key]: event.target.value,
                              },
                            }))
                          }
                          rows={3}
                          className="font-mono text-xs"
                          placeholder={
                            isSet ? t("appServices.vendorSecretSet") : t("appServices.vendorEmpty")
                          }
                          autoComplete="off"
                          spellCheck={false}
                        />
                      ) : (
                        <Input
                          id={id}
                          type={field.type === "url" ? "url" : "text"}
                          value={value}
                          onChange={(event) =>
                            setForm((prev) => ({
                              ...prev,
                              vendorValues: {
                                ...prev.vendorValues,
                                [field.key]: event.target.value,
                              },
                            }))
                          }
                          placeholder={t("appServices.vendorEmpty")}
                          autoComplete="off"
                          spellCheck={false}
                        />
                      )}
                    </div>
                  );
                })}

                <div className="space-y-2">
                  <p className="font-medium text-sm">{t("appServices.redirectTitle")}</p>
                  <p className="text-muted-foreground text-xs">{t("appServices.redirectHelp")}</p>
                  <Label htmlFor="app-service-callback-url">
                    {t("appServices.callbackUrlLabel")}
                  </Label>
                  <Input
                    id="app-service-callback-url"
                    value={editing.connection_callback_url}
                    readOnly
                    className="font-mono text-xs"
                    onFocus={(event) => event.target.select()}
                  />
                  <Label htmlFor="app-service-setup-url">{t("appServices.setupUrlLabel")}</Label>
                  <Input
                    id="app-service-setup-url"
                    value={editing.connection_setup_url}
                    readOnly
                    className="font-mono text-xs"
                    onFocus={(event) => event.target.select()}
                  />
                  <Label htmlFor="app-service-webhook-url">
                    {t("appServices.webhookUrlLabel")}
                  </Label>
                  <Input
                    id="app-service-webhook-url"
                    value={editing.webhook_url}
                    readOnly
                    className="font-mono text-xs"
                    onFocus={(event) => event.target.select()}
                  />
                </div>
              </div>
            </fieldset>
          )}

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
