import { useTranslation } from "react-i18next";

import { ProviderRegistrySection } from "@/components/admin/ProviderRegistrySection";
import {
  useAuthProviders,
  useCreateAuthProvider,
  useDeleteAuthProvider,
  useUpdateAuthProvider,
} from "@/hooks/useSettings";

/** The operator-global login provider registry (platform Settings → Authentication). */
export const AuthProvidersSection = () => {
  const { t } = useTranslation("settings");
  const providersQuery = useAuthProviders();
  const createProvider = useCreateAuthProvider();
  const updateProvider = useUpdateAuthProvider();
  const deleteProvider = useDeleteAuthProvider();

  return (
    <ProviderRegistrySection
      title={t("authProviders.title")}
      description={t("authProviders.description")}
      dialogDescription={t("authProviders.dialogDescription")}
      providers={providersQuery.data}
      isLoading={providersQuery.isLoading}
      createProvider={createProvider}
      updateProvider={updateProvider}
      deleteProvider={deleteProvider}
    />
  );
};
