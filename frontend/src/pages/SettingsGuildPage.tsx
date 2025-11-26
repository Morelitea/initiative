import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import type { AxiosError } from "axios";
import { formatDistanceToNow } from "date-fns";

import { useGuilds } from "@/hooks/useGuilds";
import type { Guild, GuildInviteRead } from "@/types/api";
import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Copy, RefreshCcw, Trash2 } from "lucide-react";

const inviteLinkForCode = (code: string) => {
  const base = import.meta.env.VITE_APP_URL?.trim() || window.location.origin;
  const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;
  return `${normalizedBase}/invite/${encodeURIComponent(code)}`;
};

export const SettingsGuildPage = () => {
  const { activeGuild, refreshGuilds, updateGuildInState } = useGuilds();
  const activeGuildId = activeGuild?.id ?? null;
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [iconBase64, setIconBase64] = useState<string | null>(null);
  const [iconError, setIconError] = useState<string | null>(null);

  const [invites, setInvites] = useState<GuildInviteRead[]>([]);
  const [invitesLoading, setInvitesLoading] = useState(false);
  const [invitesError, setInvitesError] = useState<string | null>(null);
  const [inviteSubmitting, setInviteSubmitting] = useState(false);
  const [inviteMaxUses, setInviteMaxUses] = useState<number>(1);
  const [inviteExpiresDays, setInviteExpiresDays] = useState<number>(7);

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

  const loadInvites = useCallback(async () => {
    if (!activeGuildId) {
      setInvites([]);
      return;
    }
    setInvitesLoading(true);
    setInvitesError(null);
    try {
      const response = await apiClient.get<GuildInviteRead[]>(`/guilds/${activeGuildId}/invites`);
      setInvites(response.data);
    } catch (error) {
      console.error("Failed to load invites", error);
      setInvitesError("Unable to load invites.");
    } finally {
      setInvitesLoading(false);
    }
  }, [activeGuildId]);

  useEffect(() => {
    void loadInvites();
  }, [loadInvites]);

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

  const createInvite = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!activeGuild) {
      return;
    }
    setInviteSubmitting(true);
    setInvitesError(null);
    try {
      const expiresAt =
        inviteExpiresDays > 0
          ? new Date(Date.now() + inviteExpiresDays * 24 * 60 * 60 * 1000).toISOString()
          : null;
      const payload: Record<string, unknown> = {
        max_uses: inviteMaxUses > 0 ? inviteMaxUses : null,
        expires_at: expiresAt,
      };
      await apiClient.post(`/guilds/${activeGuild.id}/invites`, payload);
      await loadInvites();
    } catch (error) {
      console.error(error);
      setInvitesError("Unable to create invite.");
    } finally {
      setInviteSubmitting(false);
    }
  };

  const deleteInvite = async (inviteId: number) => {
    if (!activeGuild) {
      return;
    }
    try {
      await apiClient.delete(`/guilds/${activeGuild.id}/invites/${inviteId}`);
      await loadInvites();
    } catch (error) {
      console.error(error);
      setInvitesError("Unable to delete invite.");
    }
  };

  const copyInviteLink = async (code: string) => {
    try {
      await navigator.clipboard.writeText(inviteLinkForCode(code));
      setSaveMessage("Invite link copied to clipboard.");
      setTimeout(() => setSaveMessage(null), 3000);
    } catch (error) {
      console.error(error);
    }
  };

  const inviteRows = useMemo(() => invites, [invites]);

  if (!activeGuild) {
    return (
      <div className="space-y-4">
        <h2 className="text-2xl font-semibold">Guild Settings</h2>
        <p className="text-sm text-muted-foreground">No active guild selected.</p>
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
                <p className="text-sm text-muted-foreground">Upload a square PNG or JPG up to 512 KB.</p>
              )}
              <Input
                id="guild-icon"
                type="file"
                accept="image/*"
                onChange={handleIconInputChange}
              />
              {iconError ? <p className="text-sm text-destructive">{iconError}</p> : null}
            </div>
            {saveError ? <p className="text-sm text-destructive">{saveError}</p> : null}
            {saveMessage ? <p className="text-sm text-primary">{saveMessage}</p> : null}
            <Button type="submit" disabled={saving}>
              {saving ? "Saving…" : "Save changes"}
            </Button>
          </form>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Invites</CardTitle>
            <p className="text-sm text-muted-foreground">
              Generate single-use invite links to onboard members.
            </p>
          </div>
          <Button variant="ghost" size="icon" onClick={() => loadInvites()}>
            <RefreshCcw className="h-4 w-4" />
            <span className="sr-only">Refresh invites</span>
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <form className="grid gap-4 md:grid-cols-3" onSubmit={createInvite}>
            <div className="space-y-2">
              <Label htmlFor="invite-uses">Max uses</Label>
              <Input
                id="invite-uses"
                type="number"
                min={1}
                value={inviteMaxUses}
                onChange={(event) => setInviteMaxUses(Number(event.target.value))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="invite-days">Expires in (days)</Label>
              <Input
                id="invite-days"
                type="number"
                min={0}
                value={inviteExpiresDays}
                onChange={(event) => setInviteExpiresDays(Number(event.target.value))}
              />
            </div>
            <div className="flex items-end">
              <Button type="submit" disabled={inviteSubmitting}>
                {inviteSubmitting ? "Creating…" : "Generate invite"}
              </Button>
            </div>
          </form>
          <div className="h-px bg-border" />
          {invitesLoading ? <p className="text-sm text-muted-foreground">Loading invites…</p> : null}
          {invitesError ? <p className="text-sm text-destructive">{invitesError}</p> : null}
          {!invitesLoading && !inviteRows.length ? (
            <p className="text-sm text-muted-foreground">No active invites.</p>
          ) : null}
          <div className="space-y-3">
            {inviteRows.map((invite) => {
              const link = inviteLinkForCode(invite.code);
              const expires =
                invite.expires_at != null
                  ? formatDistanceToNow(new Date(invite.expires_at), { addSuffix: true })
                  : "Never";
              return (
                <div
                  key={invite.id}
                  className="flex flex-col gap-3 rounded border bg-muted/30 p-4 text-sm md:flex-row md:items-center md:justify-between"
                >
                  <div>
                    <p className="font-medium">{link}</p>
                    <p className="text-muted-foreground">
                      Uses: {invite.uses}/{invite.max_uses ?? "∞"} · Expires: {expires}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="outline" size="icon" onClick={() => copyInviteLink(invite.code)}>
                      <Copy className="h-4 w-4" />
                      <span className="sr-only">Copy invite link</span>
                    </Button>
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => deleteInvite(invite.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                      <span className="sr-only">Delete invite</span>
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
