import { INSERT_EMBED_COMMAND } from "@lexical/react/LexicalAutoEmbedPlugin";
import { useTranslation } from "react-i18next";

import { useToolbarContext } from "@/components/ui/editor/context/toolbar-context";
import { EmbedConfigs } from "@/components/ui/editor/plugins/embeds/auto-embed-plugin";
import { SelectItem } from "@/components/ui/select";

export function InsertEmbeds() {
  const { activeEditor } = useToolbarContext();
  const { t } = useTranslation("documents");
  return EmbedConfigs.map((embedConfig) => (
    <SelectItem
      key={embedConfig.type}
      value={embedConfig.type}
      onPointerUp={() => {
        activeEditor.dispatchCommand(INSERT_EMBED_COMMAND, embedConfig.type);
      }}
      className=""
    >
      <div className="flex items-center gap-1">
        {embedConfig.icon}
        <span>
          {embedConfig.contentNameKey ? t(embedConfig.contentNameKey) : embedConfig.contentName}
        </span>
      </div>
    </SelectItem>
  ));
}
