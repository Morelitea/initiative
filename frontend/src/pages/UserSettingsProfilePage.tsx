import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { updateUsersMeApiV1UsersMePatch } from "@/api/generated/users/users";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { User } from "@/types/api";

const dataUrl = (value?: string | null) => {
  if (!value) {
    return "";
  }
  if (value.startsWith("data:")) {
    return value;
  }
  return `data:image/png;base64,${value}`;
};

interface UserSettingsProfilePageProps {
  user: User;
  refreshUser: () => Promise<void>;
}

export const UserSettingsProfilePage = ({ user, refreshUser }: UserSettingsProfilePageProps) => {
  const { t } = useTranslation("settings");
  const [fullName, setFullName] = useState(user.full_name ?? "");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [avatarMode, setAvatarMode] = useState<"upload" | "url">(
    user.avatar_url ? "url" : "upload"
  );
  const [avatarUrl, setAvatarUrl] = useState(user.avatar_url ?? "");
  const [avatarBase64, setAvatarBase64] = useState(user.avatar_base64 ?? "");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setFullName(user.full_name ?? "");
    setAvatarUrl(user.avatar_url ?? "");
    setAvatarBase64(user.avatar_base64 ?? "");
    setAvatarMode(user.avatar_url ? "url" : "upload");
  }, [user]);

  const avatarPreview = useMemo(() => {
    if (avatarMode === "url") {
      return avatarUrl || user.avatar_url || "";
    }
    return avatarBase64 || user.avatar_base64 || "";
  }, [avatarMode, avatarUrl, avatarBase64, user.avatar_url, user.avatar_base64]);

  const updateProfile = useMutation({
    mutationFn: async () => {
      if (password && password !== confirmPassword) {
        throw new Error(t("profile.passwordsMismatch"));
      }
      const payload: Record<string, unknown> = {};
      if (fullName !== user.full_name) {
        payload.full_name = fullName;
      }
      if (password) {
        payload.password = password;
      }
      if (avatarMode === "upload") {
        payload.avatar_base64 = avatarBase64 || null;
        payload.avatar_url = null;
      } else {
        payload.avatar_url = avatarUrl || null;
        payload.avatar_base64 = null;
      }
      await updateUsersMeApiV1UsersMePatch(
        payload as Parameters<typeof updateUsersMeApiV1UsersMePatch>[0]
      );
    },
    onSuccess: async () => {
      setPassword("");
      setConfirmPassword("");
      setError(null);
      await refreshUser();
      toast.success(t("profile.updateSuccess"));
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : t("profile.updateError"));
    },
  });

  const handleAvatarUpload = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      setAvatarMode("upload");
      setAvatarBase64(result);
    };
    reader.readAsDataURL(file);
  };

  const initials =
    (user.full_name ?? user.email ?? "User")
      .split(/\s+/)
      .map((part) => part.charAt(0).toUpperCase())
      .slice(0, 2)
      .join("") || "PP";

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Avatar className="h-16 w-16">
          {avatarPreview ? (
            <AvatarImage src={dataUrl(avatarPreview)} alt={fullName || user.email} />
          ) : null}
          <AvatarFallback>{initials}</AvatarFallback>
        </Avatar>
        <div>
          <p className="text-lg font-semibold">{user.full_name || user.email}</p>
          <p className="text-muted-foreground text-sm">{t("profile.subtitle")}</p>
        </div>
      </div>
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("profile.cardTitle")}</CardTitle>
          <CardDescription>{t("profile.cardDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-6"
            onSubmit={(event) => {
              event.preventDefault();
              updateProfile.mutate();
            }}
          >
            <div className="space-y-2">
              <Label>{t("profile.emailLabel")}</Label>
              <Input value={user.email} disabled readOnly />
              <p className="text-muted-foreground text-xs">{t("profile.emailHelp")}</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="full-name">{t("profile.fullNameLabel")}</Label>
              <Input
                id="full-name"
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
                placeholder={t("profile.fullNamePlaceholder")}
              />
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="password">{t("profile.newPasswordLabel")}</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder={t("profile.passwordPlaceholder")}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirm-password">{t("profile.confirmPasswordLabel")}</Label>
                <Input
                  id="confirm-password"
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  placeholder={t("profile.passwordPlaceholder")}
                />
              </div>
            </div>

            <div className="space-y-3">
              <Label>{t("profile.avatarLabel")}</Label>
              <Tabs
                value={avatarMode}
                onValueChange={(value) => setAvatarMode(value as "upload" | "url")}
              >
                <TabsList>
                  <TabsTrigger value="upload">{t("profile.avatarUploadTab")}</TabsTrigger>
                  <TabsTrigger value="url">{t("profile.avatarUrlTab")}</TabsTrigger>
                </TabsList>
                <TabsContent value="upload" className="space-y-2">
                  <Input type="file" accept="image/*" onChange={handleAvatarUpload} />
                  {avatarBase64 ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setAvatarBase64("")}
                    >
                      {t("profile.removeUploadedAvatar")}
                    </Button>
                  ) : null}
                </TabsContent>
                <TabsContent value="url" className="space-y-2">
                  <Input
                    type="url"
                    placeholder={t("profile.avatarUrlPlaceholder")}
                    value={avatarUrl}
                    onChange={(event) => setAvatarUrl(event.target.value)}
                  />
                  {avatarUrl ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setAvatarUrl("")}
                    >
                      {t("profile.clearAvatarUrl")}
                    </Button>
                  ) : null}
                </TabsContent>
              </Tabs>
            </div>

            {error ? <p className="text-destructive text-sm">{error}</p> : null}

            <div className="flex flex-wrap gap-3">
              <Button type="submit" disabled={updateProfile.isPending}>
                {updateProfile.isPending ? t("profile.saving") : t("profile.saveChanges")}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={updateProfile.isPending}
                onClick={() => {
                  setFullName(user.full_name ?? "");
                  setPassword("");
                  setConfirmPassword("");
                  setAvatarUrl(user.avatar_url ?? "");
                  setAvatarBase64(user.avatar_base64 ?? "");
                  setAvatarMode(user.avatar_url ? "url" : "upload");
                  setError(null);
                }}
              >
                {t("profile.reset")}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};
