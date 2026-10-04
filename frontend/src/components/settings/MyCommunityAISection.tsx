import { useTranslation } from "react-i18next";

import type { MyAIConnectionRow } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { RadioGroup } from "@/components/ui/radio-group";
import {
  useDeleteMemberKey,
  useSetMemberKey,
  useSetMemberPref,
  useTestMemberAI,
} from "@/hooks/useAISettings";
import { getErrorMessage, messageForCode } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";

import { MemberAIConnectionRow, myConnectionValue } from "./MemberAIConnectionRow";

interface MyCommunityAISectionProps {
  communityId: number;
  communityName: string;
  connections: MyAIConnectionRow[];
}

/**
 * One community's block on the personal "My AI" page: its connections (from the flat
 * `/me/ai` aggregate) plus this member's key/selection actions, which stay
 * community-scoped through the `communityId`-bound member hooks.
 */
export const MyCommunityAISection = ({
  communityId,
  communityName,
  connections,
}: MyCommunityAISectionProps) => {
  const { t } = useTranslation("settings");
  const setPref = useSetMemberPref(communityId);
  const setKey = useSetMemberKey(communityId);
  const deleteKey = useDeleteMemberKey(communityId);
  const testMember = useTestMemberAI(communityId);

  const selected = connections.find((connection) => connection.is_selected) ?? null;

  const handleSelect = (value: string) => {
    const connection = connections.find((item) => myConnectionValue(item) === value);
    if (!connection) return;
    setPref.mutate(
      { scope: connection.scope, connection_id: connection.connection_id, enabled: true },
      {
        onSuccess: () => toast.success(t("memberAI.prefSaved")),
        onError: (error) => toast.error(getErrorMessage(error, "settings:memberAI.prefError")),
      }
    );
  };

  const handleSaveKey = async (connection: MyAIConnectionRow, apiKey: string) => {
    try {
      await setKey.mutateAsync({
        scope: connection.scope,
        connection_id: connection.connection_id,
        api_key: apiKey,
      });
      toast.success(t("memberAI.keySaved"));
    } catch (error) {
      toast.error(getErrorMessage(error, "settings:memberAI.keyError"));
      throw error; // signal the row to keep its editor open
    }
  };

  const handleRemoveKey = (connection: MyAIConnectionRow) => {
    deleteKey.mutate(
      { scope: connection.scope, connectionId: connection.connection_id },
      {
        onSuccess: () => toast.success(t("memberAI.keyRemoved")),
        onError: (error) => toast.error(getErrorMessage(error, "settings:memberAI.keyRemoveError")),
      }
    );
  };

  const handleTest = () => {
    testMember.mutate(undefined, {
      onSuccess: (data) => {
        if (data.success) {
          toast.success(t("memberAI.testSuccess"));
        } else {
          toast.error(messageForCode(data.message, "settings:ai.testError"));
        }
      },
      onError: (error) => toast.error(getErrorMessage(error, "settings:ai.testError")),
    });
  };

  return (
    <section className="space-y-3">
      <h3 className="font-medium">{communityName}</h3>
      <RadioGroup
        value={selected ? myConnectionValue(selected) : ""}
        onValueChange={handleSelect}
        className="space-y-2"
      >
        {connections.map((connection) => (
          <MemberAIConnectionRow
            key={myConnectionValue(connection)}
            connection={connection}
            onSaveKey={(apiKey) => handleSaveKey(connection, apiKey)}
            onRemoveKey={() => handleRemoveKey(connection)}
            isRemovingKey={deleteKey.isPending}
          />
        ))}
      </RadioGroup>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={handleTest}
        disabled={testMember.isPending || !selected}
      >
        {testMember.isPending ? t("ai.testing") : t("memberAI.test")}
      </Button>
    </section>
  );
};
