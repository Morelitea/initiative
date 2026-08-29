/**
 * `/settings` — an initiative's name, description, colour, how people join it,
 * and which optional tools it offers.
 *
 * The name/description/colour form saves on its button; the join policy, the
 * auto-join switch, and the tool switches are single settings that save on
 * change, each sending only the field that moved — with the one coupling the
 * server enforces (auto-join needs an open policy) resolved before the request.
 */

import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  InitiativeJoinPolicy,
  type InitiativeUpdate,
  type Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { InitiativeSettingsDetailsTab } from "@/components/initiatives/settings/InitiativeSettingsDetailsTab";
import { InitiativeSettingsPermissionRequired } from "@/components/initiatives/settings/InitiativeSettingsGuard";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";
import { useUpdateInitiative } from "@/hooks/useInitiatives";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { isToolEnabled, TOGGLEABLE_TOOLS, toolViewPermission } from "@/lib/tools";

const DEFAULT_INITIATIVE_COLOR = "#6366F1";

export const InitiativeSettingsDetailsPage = () => {
  const { t } = useTranslation(["initiatives", "common"]);
  const { initiativeId, initiative, canManageMembers, isGuildAdmin } = useInitiativeSettings();

  const [name, setName] = useState(initiative?.name ?? "");
  const [description, setDescription] = useState(initiative?.description ?? "");
  const [color, setColor] = useState(initiative?.color ?? DEFAULT_INITIATIVE_COLOR);

  useEffect(() => {
    if (initiative) {
      setName(initiative.name);
      setDescription(initiative.description ?? "");
      setColor(initiative.color ?? DEFAULT_INITIATIVE_COLOR);
    }
  }, [initiative]);

  const updateInitiative = useUpdateInitiative({
    onSuccess: () => {
      toast.success(t("settings.updated"));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:settings.updateError"));
    },
  });

  const handleSaveDetails = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      toast.error(t("settings.nameRequired"));
      return;
    }
    updateInitiative.mutate({
      initiativeId,
      data: {
        name: trimmedName,
        description: description.trim() || undefined,
        color,
      },
    });
  };

  // Only the field the manager touched is sent, so an unrelated save never
  // rewrites a policy this screen wasn't asked about.
  //
  // The one exception is auto-join, which is not an independent field: it is
  // valid only alongside `open`, so a guild admin closing the initiative sends
  // both halves at once rather than being handed a refusal for a pair the UI
  // let them assemble. A manager who is not a guild admin cannot send the field
  // at all, so for them the section locks the other policies instead.
  const handleChangeJoinPolicy = (value: InitiativeJoinPolicy) => {
    const clearsAutoJoin =
      isGuildAdmin && Boolean(initiative?.auto_join) && value !== InitiativeJoinPolicy.open;
    updateInitiative.mutate(
      {
        initiativeId,
        data: clearsAutoJoin ? { join_policy: value, auto_join: false } : { join_policy: value },
      },
      clearsAutoJoin
        ? { onSuccess: () => toast.info(t("initiatives:settings.autoJoin.turnedOff")) }
        : undefined
    );
  };

  const handleChangeAutoJoin = (next: boolean) => {
    updateInitiative.mutate({ initiativeId, data: { auto_join: next } });
  };

  // One handler for every toggleable tool's master switch — the update field
  // is the tool's derived `{plural}_enabled` name.
  const handleToggleTool = (tool: Tool, value: boolean) => {
    updateInitiative.mutate({
      initiativeId,
      data: { [toolViewPermission(tool)]: value } as InitiativeUpdate,
    });
  };

  if (!canManageMembers) {
    return <InitiativeSettingsPermissionRequired />;
  }

  if (!initiative) {
    return null;
  }

  return (
    <InitiativeSettingsDetailsTab
      name={name}
      setName={setName}
      description={description}
      setDescription={setDescription}
      color={color}
      setColor={setColor}
      toolSwitches={Object.fromEntries(
        TOGGLEABLE_TOOLS.map((tool) => [tool, Boolean(isToolEnabled(tool, initiative))])
      )}
      onToggleTool={handleToggleTool}
      joinPolicy={initiative.join_policy}
      onChangeJoinPolicy={handleChangeJoinPolicy}
      autoJoin={initiative.auto_join}
      onChangeAutoJoin={handleChangeAutoJoin}
      canManageAutoJoin={isGuildAdmin}
      canManageMembers={canManageMembers}
      isSaving={updateInitiative.isPending}
      onSaveDetails={handleSaveDetails}
    />
  );
};
