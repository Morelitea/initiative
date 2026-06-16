import { useTranslation } from "react-i18next";

import { TrashTable } from "@/components/trash/TrashTable";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const UserTrashPage = () => {
  const { t } = useTranslation("trash");

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {/* Personal, cross-guild "my deletions" view (/me/trash). The
            Delete-now purge button is hidden — that action is admin-only and is
            reached through the guild Settings → Trash tab instead. */}
        <TrashTable variant="user" showPurgeAction={false} />
      </CardContent>
    </Card>
  );
};

export default UserTrashPage;
