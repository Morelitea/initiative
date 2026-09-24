import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { $findMatchingParent } from "@lexical/utils";
import { $getNodeByKey, $getSelection, $isRangeSelection } from "lexical";
import { ChevronDown, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  $isCalloutNode,
  CALLOUT_VARIANTS,
  type CalloutVariant,
} from "@/components/ui/editor/nodes/callout-node";
import { CalloutIcon } from "@/components/ui/editor/plugins/callout-icon";

interface Anchor {
  key: string;
  top: number;
  left: number;
}

/** A small menu at the corner of the callout the caret is in: change its
 * kind, or take the callout away and keep what it says. */
function CalloutActionMenu({ anchorElem }: { anchorElem: HTMLElement }) {
  const { t } = useTranslation("documents");
  const [editor] = useLexicalComposerContext();
  const [anchor, setAnchor] = useState<Anchor | null>(null);

  const update = useCallback(() => {
    let key: string | null = null;
    editor.getEditorState().read(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) return;
      const callout = $findMatchingParent(selection.anchor.getNode(), $isCalloutNode);
      key = callout ? callout.getKey() : null;
    });
    const element = key ? editor.getElementByKey(key) : null;
    if (!key || !element) {
      setAnchor(null);
      return;
    }
    const rect = element.getBoundingClientRect();
    const host = anchorElem.getBoundingClientRect();
    setAnchor({ key, top: rect.top - host.top + 6, left: rect.right - host.left - 30 });
  }, [editor, anchorElem]);

  useEffect(() => editor.registerUpdateListener(() => update()), [editor, update]);

  const setVariant = (variant: CalloutVariant) => {
    if (!anchor) return;
    editor.update(() => {
      const node = $getNodeByKey(anchor.key);
      if ($isCalloutNode(node)) {
        node.setVariant(variant);
      }
    });
  };

  const remove = () => {
    if (!anchor) return;
    editor.update(() => {
      const node = $getNodeByKey(anchor.key);
      if ($isCalloutNode(node)) {
        for (const child of node.getChildren()) {
          node.insertBefore(child);
        }
        node.remove();
      }
    });
  };

  if (!anchor) {
    return null;
  }
  return (
    <div className="absolute z-10" style={{ top: anchor.top, left: anchor.left }}>
      <DropdownMenu>
        <DropdownMenuTrigger
          className="flex h-6 w-6 items-center justify-center rounded bg-background/80 text-muted-foreground hover:bg-accent"
          aria-label={t("editor.calloutActions")}
        >
          <ChevronDown className="h-4 w-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {CALLOUT_VARIANTS.map((variant) => (
            <DropdownMenuItem key={variant} onSelect={() => setVariant(variant)}>
              <CalloutIcon variant={variant} className="size-4" />
              {t(`editor.calloutKinds.${variant}`)}
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={remove}>
            <Trash2 className="size-4" />
            {t("editor.removeCallout")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export function CalloutActionMenuPlugin({ anchorElem }: { anchorElem: HTMLElement | null }) {
  if (!anchorElem) {
    return null;
  }
  return createPortal(<CalloutActionMenu anchorElem={anchorElem} />, anchorElem);
}
