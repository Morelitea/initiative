import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useGuilds } from "@/hooks/useGuilds";
import { getErrorMessage } from "@/lib/errorMessage";
import type { Guild } from "@/types/api";
import { apiClient } from "@/api/client";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export const SettingsGuildPage = () => {
  const { activeGuild, refreshGuilds, updateGuildInState } = useGuilds();
  const { t } = useTranslation("guilds");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [iconBase64, setIconBase64] = useState<string | null>(null);
  const [iconError, setIconError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");

  useEffect(() => {
    if (!activeGuild) {
      setName("");
      setDescription("");
      setIconBase64(null);
      return;
    }
    setName(activeGuild.name);
    setDescription(activeGuild.description ?? "");
    setIconBase64(activeGuild.icon_base64 ?? null);
  }, [activeGuild]);

  const handleIconInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    if (!file.type.startsWith("image/")) {
      setIconError(t("settings.iconErrorNotImage"));
      return;
    }
    const maxBytes = 512 * 1024;
    if (file.size > maxBytes) {
      setIconError(t("settings.iconErrorTooLarge"));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        setIconBase64(reader.result);
        setIconError(null);
      } else {
        setIconError(t("settings.iconErrorReadFailed"));
      }
    };
    reader.onerror = () => {
      setIconError(t("settings.iconErrorReadFailed"));
    };
    reader.readAsDataURL(file);
  };

  const handleSave = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!activeGuild) {
      return;
    }
    setSaving(true);
    setSaveError(null);
    setSaveMessage(null);
    try {
      const response = await apiClient.patch<Guild>(`/guilds/${activeGuild.id}`, {
        name,
        description,
        icon_base64: iconBase64 ?? null,
      });
      updateGuildInState(response.data);
      await refreshGuilds();
      setSaveMessage(t("settings.updatedSuccessfully"));
    } catch (err) {
      console.error(err);
      setSaveError(getErrorMessage(err, "guilds:settings.unableToUpdate"));
    } finally {
      setSaving(false);
    }
  };

  const confirmDeleteGuild = async () => {
    if (!activeGuild) {
      return;
    }
    setDeleting(true);
    setSaveError(null);
    setShowDeleteConfirm(false);
    setDeleteConfirmText("");
    try {
      await apiClient.delete(`/guilds/${activeGuild.id}`);
      await refreshGuilds();
      window.location.replace("/");
    } catch (error) {
      console.error(error);
      setSaveError(t("settings.unableToDelete"));
    } finally {
      setDeleting(false);
    }
  };

  const canConfirmDelete = deleteConfirmText === activeGuild?.name;

  if (!activeGuild) {
    return (
      <div className="space-y-4">
        <h2 className="text-2xl font-semibold">{t("settings.title")}</h2>
        <p className="text-muted-foreground text-sm">{t("settings.noActiveGuild")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.detailsTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSave}>
            <div className="space-y-2">
              <Label htmlFor="guild-name">{t("settings.nameLabel")}</Label>
              <Input
                id="guild-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="guild-description">{t("settings.descriptionLabel")}</Label>
              <Textarea
                id="guild-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={3}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="guild-icon">{t("settings.iconLabel")}</Label>
              {iconBase64 ? (
                <div className="flex items-center gap-4">
                  <img
                    src={iconBase64}
                    alt={t("settings.iconPreviewAlt")}
                    className="h-16 w-16 rounded-lg border object-cover"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      setIconBase64(null);
                      setIconError(null);
                    }}
                  >
                    {t("settings.removeIcon")}
                  </Button>
                </div>
              ) : (
                <p className="text-muted-foreground text-sm">{t("settings.iconHint")}</p>
              )}
              <Input
                id="guild-icon"
                type="file"
                accept="image/*"
                onChange={handleIconInputChange}
              />
              {iconError ? <p className="text-destructive text-sm">{iconError}</p> : null}
            </div>
            {saveError ? <p className="text-destructive text-sm">{saveError}</p> : null}
            {saveMessage ? <p className="text-primary text-sm">{saveMessage}</p> : null}
            <Button type="submit" disabled={saving}>
              {saving ? t("settings.saving") : t("settings.saveChanges")}
            </Button>
          </form>
        </CardContent>
      </Card>
      <Card className="border-destructive/40 bg-destructive/5">
        <CardHeader>
          <CardTitle>{t("settings.dangerZone")}</CardTitle>
          <CardDescription>{t("settings.dangerDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <Button
            variant="destructive"
            onClick={() => {
              setDeleteConfirmText("");
              setShowDeleteConfirm(true);
            }}
            disabled={deleting}
          >
            {deleting ? t("settings.deleting") : t("settings.deleteGuild")}
          </Button>
        </CardContent>
      </Card>

      <AlertDialog
        open={showDeleteConfirm}
        onOpenChange={(open) => {
          setShowDeleteConfirm(open);
          if (!open) setDeleteConfirmText("");
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.deleteConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("settings.deleteConfirmDescription", { name: activeGuild?.name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2 py-2">
            <Label htmlFor="delete-guild-confirm-input">
              {t("settings.deleteConfirmLabel", { name: activeGuild?.name })}
            </Label>
            <Input
              id="delete-guild-confirm-input"
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              placeholder={activeGuild?.name}
              autoComplete="off"
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>{t("common:cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => void confirmDeleteGuild()}
              disabled={!canConfirmDelete || deleting}
              className="bg-destructive hover:bg-destructive/90 text-white"
            >
              {deleting ? t("settings.deleting") : t("common:delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};
