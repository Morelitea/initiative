import { Capacitor } from "@capacitor/core";

import FirebaseRuntime from "@/plugins/firebaseRuntime";

import { getItem, setItem } from "./storage";

const storageKey = (serverUrl: string) => `fcm-project:${serverUrl}`;

/**
 * Keep the Android app's Firebase project in step with its server's.
 *
 * The native side keeps the Firebase settings it fetched for a server and reuses
 * them for as long as the address stays the same. A server can change projects
 * at that address, for instance when its operator stops using their own Firebase
 * and sends through the push relay, so before Firebase starts this compares the
 * project the server names now with the last one seen for it and, when they
 * differ or none was recorded, clears the saved settings so they are fetched
 * afresh. Call it before {@link FirebaseRuntime.initialize}. Android only: the
 * iPhone app has no Firebase.
 */
export const syncFirebaseProject = async (serverUrl: string): Promise<void> => {
  if (Capacitor.getPlatform() !== "android") return;
  let projectId: string | null;
  try {
    const response = await fetch(`${serverUrl}/settings/fcm-config`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return;
    const body = (await response.json()) as { project_id?: unknown };
    projectId = typeof body.project_id === "string" ? body.project_id : null;
  } catch {
    return;
  }
  if (!projectId) return;
  if (getItem(storageKey(serverUrl)) === projectId) return;
  try {
    await FirebaseRuntime.clearConfig();
  } catch {
    return;
  }
  await setItem(storageKey(serverUrl), projectId);
};
