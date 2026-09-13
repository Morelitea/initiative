/** Mint a checklist item id.
 *
 * The client mints it so a line typed just now is addressable before it has
 * round-tripped — a tick names one item by id. Random rather than sequential:
 * two people adding a line at the same moment must not land on the same id.
 * Letters and digits only, which is what the API accepts.
 */
export const newChecklistItemId = (): string => {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) return uuid.replace(/-/g, "");
  return `${Math.random().toString(36).slice(2, 12)}${Date.now().toString(36)}`;
};
