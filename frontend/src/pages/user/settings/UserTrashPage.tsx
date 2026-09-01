import { useTranslation } from "react-i18next";

import { SettingsSection } from "@/components/settings/SettingsSection";
import { TrashTable } from "@/components/trash/TrashTable";

export const UserTrashPage = () => {
  const { t } = useTranslation("trash");

  return (
    <SettingsSection title={t("title")} description={t("description")}>
      {/* Personal, cross-guild "my deletions" view (/me/trash). The
          Delete-now purge button is hidden — that action is admin-only and is
          reached through the guild Settings → Trash tab instead. */}
      <TrashTable variant="user" showPurgeAction={false} />
    </SettingsSection>
  );
};

export default UserTrashPage;
