import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { updateCommunity } from "@/api/generated/communities/communities";
import type { CommunityRead } from "@/api/generated/initiativeAPI.schemas";
import { CommunityArtworkPanel } from "@/components/communities/CommunityArtworkPanel";
import { CommunityDiscoveryPanel } from "@/components/communities/CommunityDiscoveryPanel";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useCommunities } from "@/hooks/useCommunities";
import { getErrorMessage } from "@/lib/errorMessage";

export const SettingsCommunityPage = () => {
  const { activeCommunity, refreshCommunities, updateCommunityInState } = useCommunities();
  const { t } = useTranslation(["communities", "common"]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!activeCommunity) {
      setName("");
      setDescription("");
      return;
    }
    setName(activeCommunity.name);
    setDescription(activeCommunity.description ?? "");
  }, [activeCommunity]);

  const handleSave = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!activeCommunity) {
      return;
    }
    setSaving(true);
    setSaveError(null);
    setSaveMessage(null);
    try {
      const result = await (updateCommunity(activeCommunity.id, {
        name,
        description,
      } as Parameters<typeof updateCommunity>[1]) as unknown as Promise<CommunityRead>);
      updateCommunityInState(result);
      await refreshCommunities();
      setSaveMessage(t("settings.updatedSuccessfully"));
    } catch (err) {
      console.error(err);
      setSaveError(getErrorMessage(err, "communities:settings.unableToUpdate"));
    } finally {
      setSaving(false);
    }
  };

  if (!activeCommunity) {
    return (
      <div className="space-y-6">
        <h2 className="font-semibold text-xl tracking-tight">{t("settings.title")}</h2>
        <p className="text-muted-foreground text-sm">{t("settings.noActiveCommunity")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="pt-6">
          <form className="space-y-4" onSubmit={handleSave}>
            <div className="space-y-2">
              <Label htmlFor="community-name">{t("settings.nameLabel")}</Label>
              <Input
                id="community-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={255}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="community-description">{t("settings.descriptionLabel")}</Label>
              <Textarea
                id="community-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={3}
              />
            </div>
            {saveError ? <p className="text-destructive text-sm">{saveError}</p> : null}
            {saveMessage ? <p className="text-primary text-sm">{saveMessage}</p> : null}
            <Button type="submit" disabled={saving}>
              {saving ? t("settings.saving") : t("settings.saveChanges")}
            </Button>
          </form>
        </CardContent>
      </Card>
      <CommunityArtworkPanel community={activeCommunity} />
      <CommunityDiscoveryPanel />
    </div>
  );
};
