import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import type { NodeKey } from "lexical";
import { Settings2 } from "lucide-react";
import { lazy, Suspense } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useEditorModal } from "@/components/ui/editor/editor-hooks/use-modal";
import { Skeleton } from "@/components/ui/skeleton";

// Lazy because the dialog builds embed nodes, and the node is what draws this
// button: importing it here would make the two modules each other's.
const EmbedDialog = lazy(() =>
  import("@/components/ui/editor/plugins/embed-dialog").then((m) => ({ default: m.EmbedDialog }))
);

/** The button that reopens an embed's settings, where the page can be edited. */
export function EmbedSettingsButton({ nodeKey }: { nodeKey: NodeKey }) {
  const { t } = useTranslation("editor");
  const [editor] = useLexicalComposerContext();
  const [modal, showModal] = useEditorModal();
  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="-my-1 size-7 shrink-0"
        onClick={() =>
          showModal(t("embeds.settings"), (onClose) => (
            <Suspense fallback={<Skeleton className="h-40 w-full" />}>
              <EmbedDialog activeEditor={editor} nodeKey={nodeKey} onClose={onClose} />
            </Suspense>
          ))
        }
        aria-label={t("embeds.settings")}
        title={t("embeds.settings")}
      >
        <Settings2 className="size-3.5" />
      </Button>
      {modal}
    </>
  );
}
