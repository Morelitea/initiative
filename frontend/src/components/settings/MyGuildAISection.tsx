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
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

import { MemberAIConnectionRow, myConnectionValue } from "./MemberAIConnectionRow";

interface MyGuildAISectionProps {
  guildId: number;
  guildName: string;
  connections: MyAIConnectionRow[];
}

/**
 * One guild's block on the personal "My AI" page: its connections (from the flat
 * `/me/ai` aggregate) plus this member's key/selection actions, which stay
 * guild-scoped through the `guildId`-bound member hooks.
 */
export const MyGuildAISection = ({ guildId, guildName, connections }: MyGuildAISectionProps) => {
  const { t } = useTranslation("settings");
  const setPref = useSetMemberPref(guildId);
  const setKey = useSetMemberKey(guildId);
  const deleteKey = useDeleteMemberKey(guildId);
  const testMember = useTestMemberAI(guildId);

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
          toast.success(data.message || t("memberAI.testSuccess"));
        } else {
          toast.error(data.message || t("ai.testError"));
        }
      },
      onError: (error) => toast.error(getErrorMessage(error, "settings:ai.testError")),
    });
  };

  return (
    <section className="space-y-3">
      <h3 className="font-medium">{guildName}</h3>
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
