import type { ProviderAwareness } from "@lexical/yjs";
import { useEffect, useMemo, useRef, useState } from "react";

import { getUserColorHsl } from "@/lib/userColor";

/**
 * Selection-presence awareness for the spreadsheet editor.
 *
 * Each connected client publishes ``spreadsheet_user`` (id + name) and
 * ``spreadsheet_selection`` (row + col + color + updatedAt) to the
 * shared awareness layer. Peers subscribe to render colored rings and
 * a name label on the cells other users have selected.
 *
 * Same shape vocabulary the whiteboard cursor hook uses, just keyed
 * with a ``spreadsheet_*`` prefix so the two editors never collide on
 * the awareness state for a multi-doc-type session.
 */

interface SpreadsheetAwarenessUser {
  id: number;
  name: string;
}

interface SpreadsheetAwarenessSelection {
  row: number;
  col: number;
  color: string;
  updatedAt: number;
}

export interface SpreadsheetPeer {
  clientId: number;
  user: SpreadsheetAwarenessUser;
  selection: SpreadsheetAwarenessSelection;
}

interface UseSpreadsheetAwarenessArgs {
  awareness: ProviderAwareness | null;
  clientId: number | null;
  user: { id: number; name: string } | null;
  selected: { row: number; col: number };
  enabled: boolean;
}

interface UseSpreadsheetAwarenessResult {
  /** Map keyed by ``"r:c"`` for O(1) lookup during cell rendering. */
  peerSelectionsByCell: Map<string, SpreadsheetPeer>;
}

const SELECTION_KEY = "spreadsheet_selection";
const USER_KEY = "spreadsheet_user";

const PEER_TIMEOUT_MS = 30_000;

export const useSpreadsheetAwareness = ({
  awareness,
  clientId,
  user,
  selected,
  enabled,
}: UseSpreadsheetAwarenessArgs): UseSpreadsheetAwarenessResult => {
  const [peers, setPeers] = useState<SpreadsheetPeer[]>([]);

  // Publish the local selection. Throttled to once per requestAnimation
  // frame would be overkill — selection changes are rare (clicks /
  // arrow keys) so a plain effect suffices.
  const lastPublishedRef = useRef<{ row: number; col: number } | null>(null);
  useEffect(() => {
    if (!enabled || !awareness || !user) return;
    awareness.setLocalStateField(USER_KEY, { id: user.id, name: user.name });
  }, [enabled, awareness, user]);

  useEffect(() => {
    if (!enabled || !awareness || !user) return;
    const last = lastPublishedRef.current;
    if (last && last.row === selected.row && last.col === selected.col) return;
    lastPublishedRef.current = { row: selected.row, col: selected.col };
    awareness.setLocalStateField(SELECTION_KEY, {
      row: selected.row,
      col: selected.col,
      color: getUserColorHsl(user.id),
      updatedAt: Date.now(),
    });
  }, [enabled, awareness, user, selected.row, selected.col]);

  // Clear selection on unmount so peers don't see a ghost cursor.
  useEffect(() => {
    if (!enabled || !awareness) return;
    return () => {
      awareness.setLocalStateField(SELECTION_KEY, null);
    };
  }, [enabled, awareness]);

  // Subscribe to peer state.
  useEffect(() => {
    if (!enabled || !awareness) {
      setPeers([]);
      return;
    }
    const rebuild = () => {
      const states = awareness.getStates();
      const now = Date.now();
      const next: SpreadsheetPeer[] = [];
      states.forEach((state, peerClientId) => {
        if (clientId !== null && peerClientId === clientId) return;
        const peerUser = (state as Record<string, unknown>)[USER_KEY] as
          | SpreadsheetAwarenessUser
          | undefined;
        const selection = (state as Record<string, unknown>)[SELECTION_KEY] as
          | SpreadsheetAwarenessSelection
          | undefined;
        if (!peerUser || !selection) return;
        if (now - selection.updatedAt > PEER_TIMEOUT_MS) return;
        next.push({ clientId: peerClientId, user: peerUser, selection });
      });
      setPeers(next);
    };
    rebuild();
    awareness.on("update", rebuild);
    return () => awareness.off("update", rebuild);
  }, [enabled, awareness, clientId]);

  const peerSelectionsByCell = useMemo(() => {
    const m = new Map<string, SpreadsheetPeer>();
    for (const peer of peers) {
      m.set(`${peer.selection.row}:${peer.selection.col}`, peer);
    }
    return m;
  }, [peers]);

  return { peerSelectionsByCell };
};
