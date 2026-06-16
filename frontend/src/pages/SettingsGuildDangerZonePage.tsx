import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import { deleteGuildApiV1GuildsGuildIdDelete } from "@/api/generated/guilds/guilds";
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
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { getErrorMessage } from "@/lib/errorMessage";

export const SettingsGuildDangerZonePage = () => {
  const { activeGuild, guilds, refreshGuilds, switchGuild } = useGuilds();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation(["guilds", "common"]);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [password, setPassword] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // OIDC-provisioned accounts have no usable password (the random hash
  // assigned at SSO callback was never shown to the user). The backend
  // skips the password gate for these users, so we hide the field.
  const isOidcUser = user?.oidc_sub != null;

  // The whole phrase is uppercased, including the guild name, so casing
  // never trips up the confirmation. Mirrors the backend check.
  const expectedPhrase = activeGuild ? `DELETE GUILD ${activeGuild.name.toUpperCase()}` : "";
  const canConfirmDelete =
    deleteConfirmText === expectedPhrase && (isOidcUser || password.length > 0);

  const resetDialog = () => {
    setDeleteConfirmText("");
    setPassword("");
    setDeleteError(null);
  };

  const confirmDeleteGuild = async () => {
    if (!activeGuild) {
      return;
    }
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteGuildApiV1GuildsGuildIdDelete(activeGuild.id, {
        password,
        confirmation_text: deleteConfirmText,
      });
    } catch (error) {
      console.error(error);
      setDeleteError(getErrorMessage(error, "guilds:settings.unableToDelete"));
      setDeleting(false);
      return;
    }
    // Deletion is confirmed (204) and irreversible. Move off the deleted guild's
    // URL onto a surviving guild: switchGuild updates the active-guild context +
    // storage, so we never land on (or reload into) the now-dangling guild id —
    // which is what produced the blank "not a member" screen. Best-effort — a
    // refresh hiccup must not surface a misleading "unable to delete" for a guild
    // that is already gone. SPA navigation (not window.location) avoids racing the
    // storage write that a full reload would re-read.
    const nextGuild = guilds.find((g) => g.id !== activeGuild.id);
    try {
      if (nextGuild) {
        await switchGuild(nextGuild.id);
      } else {
        await refreshGuilds();
      }
    } catch (error) {
      console.error(error);
    }
    void navigate({ to: "/" });
  };

  if (!activeGuild) {
    return (
      <div className="space-y-4">
        <h2 className="font-semibold text-2xl">{t("settings.dangerZone")}</h2>
        <p className="text-muted-foreground text-sm">{t("settings.noActiveGuild")}</p>
      </div>
    );
  }

  const deletionList = (
    <ul className="list-inside list-disc space-y-1 text-sm">
      <li>{t("settings.deleteWhatInitiatives")}</li>
      <li>{t("settings.deleteWhatProjects")}</li>
      <li>{t("settings.deleteWhatTasks")}</li>
      <li>{t("settings.deleteWhatDocuments")}</li>
      <li>{t("settings.deleteWhatMembers")}</li>
      <li>{t("settings.deleteWhatSettings")}</li>
    </ul>
  );

  return (
    <div className="space-y-6">
      <Card className="border-destructive/40 bg-destructive/5">
        <CardHeader>
          <CardTitle>{t("settings.deleteGuildTitle")}</CardTitle>
          <CardDescription>{t("settings.dangerDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm">
            <Trans
              i18nKey="settings.deleteGuildIntro"
              ns="guilds"
              values={{ name: activeGuild.name }}
              components={{ bold: <strong /> }}
            />
          </p>
          {deletionList}
          <Button
            variant="destructive"
            onClick={() => {
              resetDialog();
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
          if (!open) resetDialog();
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.deleteConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              <Trans
                i18nKey="settings.deleteConfirmDescription"
                ns="guilds"
                values={{ name: activeGuild.name }}
                components={{ bold: <strong /> }}
              />
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-4 py-2">
            {!isOidcUser && (
              <div className="space-y-2">
                <Label htmlFor="delete-guild-password">
                  {t("settings.deleteConfirmPasswordLabel")}
                </Label>
                <Input
                  id="delete-guild-password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t("settings.deleteConfirmPasswordPlaceholder")}
                  autoComplete="current-password"
                />
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="delete-guild-confirm-input">
                <Trans
                  i18nKey="settings.deleteConfirmLabel"
                  ns="guilds"
                  values={{ phrase: expectedPhrase }}
                  components={{ bold: <strong /> }}
                />
              </Label>
              <Input
                id="delete-guild-confirm-input"
                value={deleteConfirmText}
                onChange={(e) => setDeleteConfirmText(e.target.value)}
                placeholder={expectedPhrase}
                autoComplete="off"
              />
            </div>
            {deleteError ? <p className="text-destructive text-sm">{deleteError}</p> : null}
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>{t("common:cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                // Keep the dialog open so inline errors (wrong password)
                // stay visible; AlertDialogAction closes on click by default.
                e.preventDefault();
                void confirmDeleteGuild();
              }}
              disabled={!canConfirmDelete || deleting}
              className="bg-destructive text-white hover:bg-destructive/90"
            >
              {deleting ? t("settings.deleting") : t("common:delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};
