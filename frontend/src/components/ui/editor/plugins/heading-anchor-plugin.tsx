import { useEffect } from "react";
import { HeadingNode } from "@lexical/rich-text";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";

import { slugify } from "@/lib/slug";

/**
 * Lexical plugin that:
 * 1. Sets `id` attributes on heading DOM elements (for anchor targets)
 * 2. Intercepts clicks on `#hash` links and scrolls to the heading
 *    (capture-phase, before ClickableLinkPlugin's bubble-phase handler)
 */
export function HeadingAnchorPlugin(): null {
  const [editor] = useLexicalComposerContext();

  useEffect(() => {
    // 1. Set id attributes on heading DOM elements
    const unregisterMutation = editor.registerMutationListener(
      HeadingNode,
      (mutations) => {
        editor.getEditorState().read(() => {
          for (const [nodeKey, type] of mutations) {
            if (type === "destroyed") continue;
            const dom = editor.getElementByKey(nodeKey);
            if (!dom) continue;
            const slug = slugify(dom.textContent || "");
            if (slug) {
              dom.id = slug;
            } else {
              dom.removeAttribute("id");
            }
          }
        });
      },
      { skipInitialization: false }
    );

    // 2. Capture-phase click handler for hash links
    const handleClick = (event: Event) => {
      const mouseEvent = event as MouseEvent;
      const target = mouseEvent.target as HTMLElement;
      const anchor = target.closest("a");
      if (!anchor) return;

      const href = anchor.getAttribute("href");
      if (!href || !href.startsWith("#")) return;

      const rootElement = editor.getRootElement();
      if (!rootElement) return;

      const targetId = href.slice(1);
      const targetElement = rootElement.querySelector(`[id="${CSS.escape(targetId)}"]`);
      if (!targetElement) return;

      mouseEvent.preventDefault();
      mouseEvent.stopPropagation();
      targetElement.scrollIntoView({ behavior: "smooth", block: "start" });
    };

    const unregisterRoot = editor.registerRootListener((rootElement, prevRootElement) => {
      if (prevRootElement) {
        prevRootElement.removeEventListener("click", handleClick, true);
      }
      if (rootElement) {
        rootElement.addEventListener("click", handleClick, true);
      }
    });

    return () => {
      unregisterMutation();
      unregisterRoot();
    };
  }, [editor]);

  return null;
}
