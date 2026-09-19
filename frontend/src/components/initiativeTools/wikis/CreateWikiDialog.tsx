import type { WikiRead } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  type CreateToolConfig,
  CreateToolDialog,
  type CreateToolDialogProps,
} from "@/components/initiativeTools/shared/CreateToolDialog";
import { useCreateWiki } from "@/hooks/useWikis";

const config: CreateToolConfig<WikiRead> = {
  tool: Tool.wiki,
  namespace: "wikis",
  titleKey: "createWiki",
  descriptionKey: "createWikiDescription",
  idPrefix: "create-wiki",
  useCreate: useCreateWiki,
};

/**
 * Naming an empty wiki. The pages come afterwards, on its own page, where the
 * tree is — which is why this is the shared name-and-describe dialog rather
 * than anything that asks about structure up front.
 */
export const CreateWikiDialog = (props: Omit<CreateToolDialogProps<WikiRead>, "config">) => (
  <CreateToolDialog {...props} config={config} />
);
