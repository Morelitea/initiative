import { AutoLinkNode, LinkNode } from "@lexical/link";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { mergeRegister } from "@lexical/utils";
import { useEffect } from "react";

import { sanitizeUrl } from "@/components/ui/editor/utils/url";

/**
 * Neutralizes dangerous link URLs in the editor state itself.
 *
 * Documents are cross-user stored content. Lexical's LinkNode only runs its
 * built-in URL sanitizer at the DOM/render boundary (`createDOM`), so the raw
 * `__url` (e.g. `javascript:alert(1)`) survives in the serialized state and is
 * returned verbatim by `getURL()`. Any code path that reads `getURL()` and acts
 * on it (e.g. `window.open`) would then execute the unsanitized scheme.
 *
 * Registering a node transform sanitizes the stored URL on every import path
 * (importJSON, importDOM, paste) and on any programmatic mutation, so the value
 * persisted in state is always allowlist-clean. This is the single import/render
 * choke point required by the security hardening — it complements (and does not
 * rely on) Lexical's own render-time sanitization.
 */
export function LinkSanitizePlugin(): null {
  const [editor] = useLexicalComposerContext();

  useEffect(() => {
    // AutoLinkNode extends LinkNode, so one transform body serves both
    // registrations; registerNodeTransform only ever passes the matching type.
    const sanitizeNode = (node: LinkNode) => {
      const url = node.getURL();
      const safe = sanitizeUrl(url);
      if (safe !== url) {
        node.setURL(safe);
      }
    };

    return mergeRegister(
      editor.registerNodeTransform(LinkNode, sanitizeNode),
      editor.registerNodeTransform(AutoLinkNode, sanitizeNode)
    );
  }, [editor]);

  return null;
}
