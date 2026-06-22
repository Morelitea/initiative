import { useTranslation } from "react-i18next";

import type { DocumentRead } from "@/api/generated/initiativeAPI.schemas";
import { ShareControl } from "@/components/access/ShareControl";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TabsContent } from "@/components/ui/tabs";
import { useSetDocumentGrants } from "@/hooks/useDocuments";
import { toast } from "@/lib/chesterToast";

interface DocumentSettingsAccessTabProps {
  document: DocumentRead;
  documentId: number;
}

export const DocumentSettingsAccessTab = ({
  document,
  documentId,
}: DocumentSettingsAccessTabProps) => {
  const { t } = useTranslation(["documents", "access"]);

  const setGrants = useSetDocumentGrants(documentId, {
    onSuccess: () => toast.success(t("settings.accessUpdated")),
  });

  const canManage = document.my_permission_level === "owner";
  const ownerId = document.grants.find((g) => g.level === "owner")?.user_id ?? null;

  return (
    <TabsContent value="access" className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.tabAccess")}</CardTitle>
          <CardDescription>{t("access:share.settingsDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <ShareControl
            initiativeId={document.initiative_id ?? null}
            grants={document.grants}
            onChange={(grants) => setGrants.mutate(grants)}
            ownerId={ownerId}
            disabled={!canManage || setGrants.isPending}
          />
        </CardContent>
      </Card>
    </TabsContent>
  );
};
