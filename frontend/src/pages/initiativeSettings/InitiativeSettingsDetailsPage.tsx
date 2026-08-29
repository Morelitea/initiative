/**
 * `/settings` — an initiative's name, description, colour, how people join it,
 * and which optional tools it offers.
 *
 * The name/description/colour form saves on its button; the join policy and the
 * tool switches are single settings that save on change, each sending only the
 * field that moved.
 */

import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  InitiativeJoinPolicy,
  InitiativeUpdate,
  Tool,
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
  const { initiativeId, initiative, canManageMembers } = useInitiativeSettings();

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
  const handleChangeJoinPolicy = (value: InitiativeJoinPolicy) => {
    updateInitiative.mutate({ initiativeId, data: { join_policy: value } });
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
      canManageMembers={canManageMembers}
      isSaving={updateInitiative.isPending}
      onSaveDetails={handleSaveDetails}
    />
  );
};
