import { useTranslation } from "react-i18next";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TrashTable } from "@/components/trash/TrashTable";

export const UserTrashPage = () => {
  const { t } = useTranslation("trash");

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {/* Personal "my deletions" view. Always scope=mine. The Delete-now
            purge button is hidden — that action is admin-only and is reached
            through the guild Settings → Trash tab instead. */}
        <TrashTable scope="mine" showPurgeAction={false} />
      </CardContent>
    </Card>
  );
};

export default UserTrashPage;
