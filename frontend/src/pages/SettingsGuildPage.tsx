import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import type { AxiosError } from "axios";

import { useGuilds } from "@/hooks/useGuilds";
import type { Guild } from "@/types/api";
import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export const SettingsGuildPage = () => {
  const { activeGuild, refreshGuilds, updateGuildInState } = useGuilds();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [iconBase64, setIconBase64] = useState<string | null>(null);
  const [iconError, setIconError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

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
      setIconError("Please choose an image file.");
      return;
    }
    const maxBytes = 512 * 1024;
    if (file.size > maxBytes) {
      setIconError("Icon must be 512 KB or smaller.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        setIconBase64(reader.result);
        setIconError(null);
      } else {
        setIconError("Unable to read the selected file.");
      }
    };
    reader.onerror = () => {
      setIconError("Unable to read the selected file.");
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
      setSaveMessage("Guild updated successfully.");
    } catch (err) {
      console.error(err);
      const axiosError = err as AxiosError<{ detail?: string }>;
      const detail = axiosError.response?.data?.detail;
      setSaveError(detail ?? "Unable to update guild.");
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteGuild = async () => {
    if (!activeGuild) {
      return;
    }
    const confirmation = window.prompt(
      "Type DELETE to confirm removing this guild. This removes all initiatives, projects, and tasks."
    );
    if (!confirmation || confirmation.trim().toUpperCase() !== "DELETE") {
      return;
    }
    setDeleting(true);
    setSaveError(null);
    try {
      await apiClient.delete(`/guilds/${activeGuild.id}`);
      await refreshGuilds();
      window.location.replace("/");
    } catch (error) {
      console.error(error);
      setSaveError("Unable to delete guild.");
    } finally {
      setDeleting(false);
    }
  };

  if (!activeGuild) {
    return (
      <div className="space-y-4">
        <h2 className="text-2xl font-semibold">Guild Settings</h2>
        <p className="text-muted-foreground text-sm">No active guild selected.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Guild details</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSave}>
            <div className="space-y-2">
              <Label htmlFor="guild-name">Name</Label>
              <Input
                id="guild-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="guild-description">Description</Label>
              <Textarea
                id="guild-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={3}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="guild-icon">Icon</Label>
              {iconBase64 ? (
                <div className="flex items-center gap-4">
                  <img
                    src={iconBase64}
                    alt="Guild icon preview"
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
                    Remove icon
                  </Button>
                </div>
              ) : (
                <p className="text-muted-foreground text-sm">
                  Upload a square PNG or JPG up to 512 KB.
                </p>
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
              {saving ? "Saving…" : "Save changes"}
            </Button>
          </form>
        </CardContent>
      </Card>
      <Card className="border-destructive/40 bg-destructive/5">
        <CardHeader>
          <CardTitle>Danger zone</CardTitle>
          <CardDescription>
            Removing a guild permanently deletes all initiatives, projects, and tasks.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <Button variant="destructive" onClick={handleDeleteGuild} disabled={deleting}>
            {deleting ? "Deleting…" : "Delete guild"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
};
