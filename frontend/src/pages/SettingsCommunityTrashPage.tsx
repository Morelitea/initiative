import { useTranslation } from "react-i18next";

import { RetentionSettingCard } from "@/components/trash/RetentionSettingCard";
import { TrashTable } from "@/components/trash/TrashTable";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const SettingsCommunityTrashPage = () => {
  const { t } = useTranslation("trash");

  // The whole community settings section is admin-gated by CommunitySettingsLayout, so
  // this is always the admin "everything in the community" view. Members manage
  // their own deletions on the personal trash page (/profile/trash).
  return (
    <div className="space-y-6">
      <RetentionSettingCard />
      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <TrashTable variant="community" showPurgeAction />
        </CardContent>
      </Card>
    </div>
  );
};

export default SettingsCommunityTrashPage;
