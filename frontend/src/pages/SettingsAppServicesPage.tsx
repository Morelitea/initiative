import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { AppServiceRegistrationRead } from "@/api/generated/initiativeAPI.schemas";
import {
  AppServiceFormDialog,
  type AppServiceFormValues,
} from "@/components/platform/AppServiceFormDialog";
import { ListSkeleton, SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  useAppServices,
  useCreateAppService,
  useDeleteAppService,
  useUpdateAppService,
} from "@/hooks/useAppServices";
import { useAuth } from "@/hooks/useAuth";
import { hasGrant, mergeGrants } from "@/lib/appServices";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { Capability, hasCapability } from "@/lib/permissions";

/** Whether a registration carries a key set, pasted or by address. */
const hasKeys = (registration: AppServiceRegistrationRead): boolean =>
  Boolean(registration.jwks_uri) ||
  (registration.jwks !== null && Object.keys(registration.jwks).length > 0);

/**
 * Deployment-level app service registrations (`apps.manage`).
 *
 * A registration is the only place an app's listing, addresses, keys, and
 * operator-conferred powers are recorded, so this page is where an operator
 * reviews what each app may do and where the kill switch lives.
 */
export const SettingsAppServicesPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const canManageApps = hasCapability(user, Capability.appsManage);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<AppServiceRegistrationRead | null>(null);
  const [disabling, setDisabling] = useState<AppServiceRegistrationRead | null>(null);
  const [deleting, setDeleting] = useState<AppServiceRegistrationRead | null>(null);

  const servicesQuery = useAppServices({ enabled: canManageApps });
  const createService = useCreateAppService();
  const updateService = useUpdateAppService();
  const deleteService = useDeleteAppService();

  const closeDialog = () => {
    setDialogOpen(false);
    setEditing(null);
  };

  const openCreate = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  const openEdit = (registration: AppServiceRegistrationRead) => {
    setEditing(registration);
    setDialogOpen(true);
  };

  const handleSubmit = (values: AppServiceFormValues) => {
    const origins = values.allowedOrigins.length > 0 ? values.allowedOrigins : null;
    // A PATCH replaces the whole list, so it is built from every control the
    // form shows and then merged with anything stored that it does not.
    const grants = mergeGrants(
      [
        ...(values.delegation ? (["delegation"] as const) : []),
        ...(values.appDirectory ? (["app_directory"] as const) : []),
      ],
      editing?.grants
    );

    if (editing) {
      updateService.mutate(
        {
          registrationId: editing.id,
          data: {
            listing_uid: values.listingUid,
            base_url: values.baseUrl,
            // Always sent, so emptying the field clears it and puts both
            // surfaces back on the base URL.
            embed_origin: values.embedOrigin,
            allowed_origins: origins,
            grants,
            // Null leaves the stored key set alone; {} clears it.
            ...(values.jwks === null ? {} : { jwks: values.jwks }),
            // Always sent, so emptying the field clears the address.
            jwks_uri: values.jwksUri,
            mandatory: values.mandatory,
          },
        },
        {
          onSuccess: () => {
            toast.success(t("appServices.saved"));
            closeDialog();
          },
          onError: (error) => toast.error(getErrorMessage(error, "settings:appServices.saveError")),
        }
      );
      return;
    }

    createService.mutate(
      {
        public_id: values.publicId,
        listing_uid: values.listingUid,
        base_url: values.baseUrl,
        embed_origin: values.embedOrigin || null,
        allowed_origins: origins,
        grants,
        jwks: values.jwks,
        jwks_uri: values.jwksUri || null,
        mandatory: values.mandatory,
      },
      {
        onSuccess: () => {
          toast.success(t("appServices.created"));
          closeDialog();
        },
        onError: (error) => toast.error(getErrorMessage(error, "settings:appServices.saveError")),
      }
    );
  };

  const setEnabled = (registration: AppServiceRegistrationRead, enabled: boolean) => {
    updateService.mutate(
      { registrationId: registration.id, data: { enabled } },
      {
        onSuccess: () => {
          setDisabling(null);
          toast.success(
            enabled
              ? t("appServices.enabledToast", { name: registration.public_id })
              : t("appServices.disabledToast", { name: registration.public_id })
          );
        },
        onError: (error) => toast.error(getErrorMessage(error, "settings:appServices.toggleError")),
      }
    );
  };

  if (!canManageApps) {
    return <p className="text-muted-foreground text-sm">{t("appServices.platformOnly")}</p>;
  }
  if (servicesQuery.isLoading) {
    return (
      <SkeletonRegion label={t("appServices.loading")}>
        <ListSkeleton rows={3} avatar={false} rowClassName="rounded-lg border bg-card p-4" />
      </SkeletonRegion>
    );
  }
  if (servicesQuery.isError || !servicesQuery.data) {
    return <p className="text-destructive text-sm">{t("appServices.loadError")}</p>;
  }

  const registrations = servicesQuery.data;

  return (
    <Card className="shadow-sm">
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle>{t("appServices.title")}</CardTitle>
          <CardDescription>{t("appServices.description")}</CardDescription>
        </div>
        <Button type="button" onClick={openCreate}>
          {t("appServices.addService")}
        </Button>
      </CardHeader>
      <CardContent>
        {registrations.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("appServices.empty")}</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {registrations.map((registration) => {
              const delegation = hasGrant(registration, "delegation");
              const appDirectory = hasGrant(registration, "app_directory");
              const keysMissing = !hasKeys(registration);

              return (
                <li key={registration.id} className="space-y-3 px-3 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <code className="rounded bg-muted px-1.5 py-0.5 font-medium text-sm">
                          {registration.public_id}
                        </code>
                        {registration.live ? (
                          <Badge
                            variant="outline"
                            className="border-transparent bg-emerald-600 text-white"
                          >
                            {t("appServices.liveBadge")}
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="border-dashed text-muted-foreground">
                            {t("appServices.notLiveBadge")}
                          </Badge>
                        )}
                        {!registration.enabled && (
                          <Badge variant="outline" className="border-destructive text-destructive">
                            {t("appServices.disabledBadge")}
                          </Badge>
                        )}
                        {!registration.publisher_enabled && (
                          <Badge variant="outline" className="border-destructive text-destructive">
                            {t("appServices.publisherDisabledBadge")}
                          </Badge>
                        )}
                        {registration.source === "registry" && (
                          <Badge variant="secondary">{t("appServices.registryBadge")}</Badge>
                        )}
                        {registration.mandatory && (
                          <Badge variant="secondary">{t("appServices.mandatoryBadge")}</Badge>
                        )}
                        {delegation && (
                          <Badge variant="secondary">{t("appServices.delegationBadge")}</Badge>
                        )}
                        {appDirectory && (
                          <Badge variant="secondary">{t("appServices.appDirectoryBadge")}</Badge>
                        )}
                      </div>
                      {registration.base_url ? (
                        <p className="truncate text-muted-foreground text-sm">
                          {registration.base_url}
                        </p>
                      ) : (
                        <p className="text-muted-foreground text-sm">
                          {t("appServices.needsAddress")}
                        </p>
                      )}
                      {registration.image_digest && (
                        <p className="break-all text-muted-foreground text-xs">
                          {t("appServices.imageSummary", { image: registration.image_digest })}
                        </p>
                      )}
                      {registration.embed_origin && (
                        <p className="truncate text-muted-foreground text-sm">
                          {t("appServices.embedOriginSummary", {
                            origin: registration.embed_origin,
                          })}
                        </p>
                      )}
                    </div>

                    <div className="flex shrink-0 flex-wrap items-center gap-2">
                      <div className="flex items-center gap-2">
                        <Label
                          htmlFor={`app-service-enabled-${registration.id}`}
                          className="text-muted-foreground text-xs"
                        >
                          {t("appServices.enabledLabel")}
                        </Label>
                        <Switch
                          id={`app-service-enabled-${registration.id}`}
                          checked={registration.enabled}
                          disabled={updateService.isPending}
                          onCheckedChange={(checked) => {
                            // Turning it back on is safe; turning it off stops
                            // the app for every guild, so that side confirms.
                            if (checked) setEnabled(registration, true);
                            else setDisabling(registration);
                          }}
                        />
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => openEdit(registration)}
                      >
                        {t("appServices.edit")}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="text-destructive"
                        onClick={() => setDeleting(registration)}
                      >
                        {t("appServices.delete")}
                      </Button>
                    </div>
                  </div>

                  <div className="space-y-1 text-muted-foreground text-xs">
                    <p>
                      {t("appServices.publisherSummary", { name: registration.publisher_name })}
                      {" · "}
                      {registration.listing_uid ? (
                        <>
                          {t("appServices.listingSummary")}{" "}
                          <code className="font-mono">{registration.listing_uid}</code>
                        </>
                      ) : (
                        t("appServices.noListing")
                      )}
                    </p>
                    {registration.allowed_origins.length > 0 && (
                      <p className="truncate">
                        {t("appServices.allowedOriginsSummary", {
                          origins: registration.allowed_origins.join(", "),
                        })}
                      </p>
                    )}
                    {!registration.enabled && (
                      <p className="text-destructive">{t("appServices.disabledHelp")}</p>
                    )}
                    {!registration.publisher_enabled && (
                      <p className="text-destructive">
                        {t("appServices.publisherDisabledHelp", {
                          name: registration.publisher_name,
                        })}
                      </p>
                    )}
                    {keysMissing && <p>{t("appServices.noKeysHelp")}</p>}
                    {registration.mandatory && <p>{t("appServices.mandatoryHelp")}</p>}
                    {delegation && <p>{t("appServices.delegationHelp")}</p>}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>

      <AppServiceFormDialog
        open={dialogOpen}
        onOpenChange={(open) => (open ? setDialogOpen(true) : closeDialog())}
        editing={editing}
        saving={createService.isPending || updateService.isPending}
        onSubmit={handleSubmit}
      />

      <ConfirmDialog
        open={disabling !== null}
        onOpenChange={(open) => {
          if (!open) setDisabling(null);
        }}
        title={t("appServices.disableTitle", { name: disabling?.public_id ?? "" })}
        description={t("appServices.disableDescription")}
        confirmLabel={t("appServices.disableConfirm")}
        cancelLabel={t("appServices.cancel")}
        destructive
        isLoading={updateService.isPending}
        onConfirm={() => {
          if (disabling) setEnabled(disabling, false);
        }}
      />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={t("appServices.deleteTitle", { name: deleting?.public_id ?? "" })}
        description={t("appServices.deleteDescription")}
        confirmLabel={t("appServices.delete")}
        cancelLabel={t("appServices.cancel")}
        destructive
        confirmationText={deleting?.public_id}
        confirmationLabel={t("appServices.deleteConfirmLabel")}
        isLoading={deleteService.isPending}
        onConfirm={() => {
          if (deleting) {
            deleteService.mutate(deleting.id, {
              onSuccess: () => {
                setDeleting(null);
                toast.success(t("appServices.deleted"));
              },
              onError: (error) =>
                toast.error(getErrorMessage(error, "settings:appServices.deleteError")),
            });
          }
        }}
      />
    </Card>
  );
};
