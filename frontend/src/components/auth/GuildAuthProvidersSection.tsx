import { useTranslation } from "react-i18next";

import { ProviderRegistrySection } from "@/components/admin/ProviderRegistrySection";
import {
  useCreateGuildAuthProvider,
  useDeleteGuildAuthProvider,
  useGuildAuthProviders,
  useUpdateGuildAuthProvider,
} from "@/hooks/useGuildAuthPolicy";

/** The guild's own login provider registry (guild Settings → Authentication). */
export const GuildAuthProvidersSection = ({ guildId }: { guildId: number }) => {
  const { t } = useTranslation("settings");
  const providersQuery = useGuildAuthProviders(guildId);
  const createProvider = useCreateGuildAuthProvider(guildId);
  const updateProvider = useUpdateGuildAuthProvider(guildId);
  const deleteProvider = useDeleteGuildAuthProvider(guildId);

  return (
    <ProviderRegistrySection
      title={t("guildAuth.registry.title")}
      description={t("guildAuth.registry.description")}
      dialogDescription={t("guildAuth.registry.dialogDescription")}
      providers={providersQuery.data}
      isLoading={providersQuery.isLoading}
      createProvider={createProvider}
      updateProvider={updateProvider}
      deleteProvider={deleteProvider}
    />
  );
};
