import { useTranslation } from "react-i18next";

import { ProviderRegistrySection } from "@/components/admin/ProviderRegistrySection";
import {
  useCreateGuildAuthProvider,
  useDeleteGuildAuthProvider,
  useDiscoverGuildAuthProvider,
  useGuildAuthProviders,
  useTestGuildAuthProvider,
  useUpdateGuildAuthProvider,
} from "@/hooks/useGuildAuthPolicy";
import { useServer } from "@/hooks/useServer";

/** The guild's own login provider registry (guild Settings → Authentication). */
export const GuildAuthProvidersSection = ({ guildId }: { guildId: number }) => {
  const { t } = useTranslation("settings");
  const { getServerOrigin } = useServer();
  const providersQuery = useGuildAuthProviders(guildId);
  const createProvider = useCreateGuildAuthProvider(guildId);
  const updateProvider = useUpdateGuildAuthProvider(guildId);
  const deleteProvider = useDeleteGuildAuthProvider(guildId);
  const testProvider = useTestGuildAuthProvider(guildId);
  const discoverIssuer = useDiscoverGuildAuthProvider(guildId);

  // Addressed through the community, because a slug is only unique inside one.
  // A preview only — a saved provider carries the server's own answer.
  const origin = getServerOrigin() ?? window.location.origin;
  const callbackUrlFor = (slug: string) =>
    `${origin}/api/v1/auth/g/${guildId}/${slug || "{slug}"}/callback`;

  return (
    <ProviderRegistrySection
      title={t("guildAuth.registry.title")}
      description={t("guildAuth.registry.description")}
      dialogDescription={t("guildAuth.registry.dialogDescription", { guildId })}
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
