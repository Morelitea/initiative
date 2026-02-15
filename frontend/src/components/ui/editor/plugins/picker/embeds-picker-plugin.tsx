import { INSERT_EMBED_COMMAND } from "@lexical/react/LexicalAutoEmbedPlugin";
import { useTranslation } from "react-i18next";

import {
  CustomEmbedConfig,
  EmbedConfigs,
} from "@/components/ui/editor/plugins/embeds/auto-embed-plugin";
import { ComponentPickerOption } from "@/components/ui/editor/plugins/picker/component-picker-option";

export function EmbedsPickerPlugin({ embed }: { embed: "tweet" | "youtube-video" }) {
  const { t } = useTranslation("documents");
  const embedConfig = EmbedConfigs.find((config) => config.type === embed) as CustomEmbedConfig;
  const contentName = embedConfig.contentNameKey
    ? t(embedConfig.contentNameKey as never)
    : embedConfig.contentName;

  return new ComponentPickerOption(t("editor.embedContent", { contentName }), {
    icon: embedConfig.icon,
    keywords: [...embedConfig.keywords, "embed"],
    onSelect: (_, editor) => editor.dispatchCommand(INSERT_EMBED_COMMAND, embedConfig.type),
  });
}
