import { useCallback, useEffect, useRef } from "react";

import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { discardPastedImage, uploadPastedImage } from "@/lib/attachmentUtils";

/**
 * Stores the pictures pasted into a task's description or a comment, and
 * throws away the ones that were never saved.
 *
 * A picture is stored the moment it is pasted, before anything is saved, so
 * leaving the page — cancelling the form, closing the dialog, walking off an
 * edit — would otherwise leave it behind. On the way out the page asks about
 * every picture it pasted, and the server deletes only the ones nothing saved
 * shows. A tab closed outright never gets to ask; the server's
 * sweep takes those a day later.
 */
export function usePastedImages(): (file: File) => Promise<string> {
  const guildId = useActiveGuildId();
  const pasted = useRef(new Set<string>());

  useEffect(() => {
    const urls = pasted.current;
    return () => {
      for (const url of urls) {
        // Nothing to tell anybody if it fails: the sweep is the backstop.
        discardPastedImage(guildId, url).catch(() => {});
      }
      urls.clear();
    };
  }, [guildId]);

  return useCallback(
    async (file: File) => {
      const url = await uploadPastedImage(guildId, file);
      pasted.current.add(url);
      return url;
    },
    [guildId]
  );
}
