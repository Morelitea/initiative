import { useTranslation } from "react-i18next";

import { ProviderRegistrySection } from "@/components/admin/ProviderRegistrySection";
import { useServer } from "@/hooks/useServer";
import {
  useAuthProviders,
  useCreateAuthProvider,
  useDeleteAuthProvider,
  useDiscoverAuthProvider,
  useTestAuthProvider,
  useUpdateAuthProvider,
} from "@/hooks/useSettings";

/** The operator-global login provider registry (platform Settings → Authentication). */
export const AuthProvidersSection = () => {
  const { t } = useTranslation("settings");
  const { getServerOrigin } = useServer();
  const providersQuery = useAuthProviders();
  const createProvider = useCreateAuthProvider();
  const updateProvider = useUpdateAuthProvider();
  const deleteProvider = useDeleteAuthProvider();
  const testProvider = useTestAuthProvider();
  const discoverIssuer = useDiscoverAuthProvider();

  // A preview, for a provider that does not exist yet. A saved one carries the
  // address the server computed, which is the one its own callback is built
  // from; this only has to be right enough to paste while setting one up, and
  // the row corrects it afterwards.
  const origin = getServerOrigin() ?? window.location.origin;
  const callbackUrlFor = (slug: string) => `${origin}/api/v1/auth/${slug || "{slug}"}/callback`;

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
      testProvider={testProvider}
      discoverIssuer={discoverIssuer}
      callbackUrlFor={callbackUrlFor}
    />
  );
};
