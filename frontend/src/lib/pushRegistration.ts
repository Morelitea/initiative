/**
 * Registering this device for push notifications with the server it is
 * signed in to, and withdrawing it again.
 *
 * Where a server sends a platform's pushes through BeyondersStudio's push
 * relay (an iPhone always; Android when the server has no Firebase project of
 * its own), the server never sees the device's own token. The app registers
 * the token with the relay under that server's relay id and is given a
 * handle, which reaches only this device and only for that server, and the
 * handle is what the server is told. The relay's address is compiled in: a
 * server only ever names its own id, never where the token goes.
 *
 * The handle is kept with the server, the relay id and a hash of the token it
 * was issued for, so a launch that changed none of them asks the relay again
 * only once a week. Signing out and moving to another server delete it at the
 * relay as well as at the server.
 */
import { CapacitorHttp } from "@capacitor/core";

import {
  registerPushToken as registerPushTokenRequest,
  unregisterPushToken,
} from "@/api/generated/push/push";
import { getStoredServerUrl } from "@/lib/serverStorage";
import { getItem, removeItem, setItem } from "@/lib/storage";

/** The push relay. Never read from a server. */
export const PUSH_RELAY_URL = "https://push-relay.beyonders.studio";

/** What the relay hands out: `rh_` and 43 base64url characters. */
const HANDLE = /^rh_[A-Za-z0-9_-]{43}$/;

const HANDLE_KEY = "initiative-push-relay-handle";

/** How long a kept handle is used before the relay is asked again. */
export const HANDLE_REFRESH_MS = 7 * 24 * 60 * 60 * 1000;

const RELAY_TIMEOUT_MS = 10_000;

export type PushPlatform = "ios" | "android";

/** The APNs environment an iPhone build registers in; debug builds use the
 *  sandbox. */
export type ApnsEnvironment = "production" | "sandbox";

/** How the server reaches each platform, from `GET /settings/fcm-config`. */
export interface PushRouting {
  relayServerId: string | null;
  androidViaRelay: boolean;
}

interface KeptHandle {
  server_origin: string;
  server_id: string;
  raw_token_hash: string;
  handle: string;
  refreshed_at: number;
}

/** The tokens and handles this device registered in this run, for sign-out
 *  to withdraw. */
const registered = new Set<string>();

const originOf = (serverUrl: string | null): string | null => {
  if (!serverUrl) return null;
  try {
    return new URL(serverUrl).origin;
  } catch {
    return null;
  }
};

const readKept = (): KeptHandle | null => {
  const raw = getItem(HANDLE_KEY);
  if (!raw) return null;
  try {
    const kept = JSON.parse(raw) as Partial<KeptHandle>;
    if (
      typeof kept.server_origin === "string" &&
      typeof kept.server_id === "string" &&
      typeof kept.raw_token_hash === "string" &&
      typeof kept.handle === "string" &&
      typeof kept.refreshed_at === "number"
    ) {
      return kept as KeptHandle;
    }
  } catch {
    // Unreadable: the same as nothing kept.
  }
  return null;
};

const sha256Hex = async (value: string): Promise<string> => {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
};

/**
 * Which platforms the server sends through the relay, and its relay id.
 * The phone names its platform: the server hands its relay id (and registers
 * with the relay for it) only to a phone whose pushes go that way, so a server
 * with its own Firebase never contacts the relay for an Android phone.
 * Null when the server could not be asked; nothing is registered then,
 * because which kind of token it wants is not known.
 */
export const readPushRouting = async (
  serverUrl: string,
  platform: PushPlatform
): Promise<PushRouting | null> => {
  try {
    const query = new URLSearchParams({ platform });
    const response = await fetch(`${serverUrl}/settings/fcm-config?${query}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return null;
    const body = (await response.json()) as {
      push_relay_server_id?: unknown;
      android_via_relay?: unknown;
    };
    return {
      relayServerId:
        typeof body.push_relay_server_id === "string" ? body.push_relay_server_id : null,
      androidViaRelay: body.android_via_relay === true,
    };
  } catch {
    return null;
  }
};

/**
 * Ask the relay for this token's handle under a server's relay id. It goes
 * through the native HTTP client: the relay serves apps, not web pages, and
 * sends none of the CORS headers a request from the webview would need.
 */
const requestHandle = async (
  serverId: string,
  platform: PushPlatform,
  token: string,
  environment: ApnsEnvironment
): Promise<string | null> => {
  const data: Record<string, string> = { server_id: serverId, platform, token };
  if (platform === "ios") data.environment = environment;
  try {
    const response = await CapacitorHttp.post({
      url: `${PUSH_RELAY_URL}/v1/devices`,
      headers: { "Content-Type": "application/json" },
      data,
      connectTimeout: RELAY_TIMEOUT_MS,
      readTimeout: RELAY_TIMEOUT_MS,
    });
    if (response.status !== 200) return null;
    const handle = (response.data as { handle?: unknown } | null)?.handle;
    return typeof handle === "string" && HANDLE.test(handle) ? handle : null;
  } catch {
    return null;
  }
};

/** Delete a handle at the relay. Best effort: one left behind is deleted
 *  when its server next sends to it and is told it is gone, or expires. */
const deleteHandle = async (handle: string): Promise<void> => {
  if (!HANDLE.test(handle)) return;
  try {
    await CapacitorHttp.request({
      method: "DELETE",
      url: `${PUSH_RELAY_URL}/v1/devices/${handle}`,
      connectTimeout: RELAY_TIMEOUT_MS,
      readTimeout: RELAY_TIMEOUT_MS,
    });
  } catch {
    // Nothing more to do about it here.
  }
};

/** Register a token or handle with the signed-in account. */
export const registerPushToken = async (token: string, platform: string): Promise<void> => {
  await registerPushTokenRequest({ push_token: token, platform });
  registered.add(token);
};

/**
 * The handle to register for this token: the kept one while it still fits
 * and is fresh, otherwise a new one from the relay. A kept handle that no
 * longer fits (another token, another relay id) is deleted at the relay, and
 * at the server when it is the same server.
 */
const handleFor = async (
  serverOrigin: string,
  serverId: string,
  platform: PushPlatform,
  token: string,
  environment: ApnsEnvironment
): Promise<string | null> => {
  const tokenHash = await sha256Hex(token);
  const kept = readKept();
  const fits =
    kept !== null &&
    kept.server_origin === serverOrigin &&
    kept.server_id === serverId &&
    kept.raw_token_hash === tokenHash;
  if (fits && Date.now() - kept.refreshed_at < HANDLE_REFRESH_MS) return kept.handle;
  if (kept && !fits) {
    await removeItem(HANDLE_KEY);
    if (kept.server_origin === serverOrigin) {
      registered.delete(kept.handle);
      await unregisterPushToken({ push_token: kept.handle }).catch(() => undefined);
    }
    await deleteHandle(kept.handle);
  }
  const handle = await requestHandle(serverId, platform, token, environment);
  if (!handle) return null;
  const next: KeptHandle = {
    server_origin: serverOrigin,
    server_id: serverId,
    raw_token_hash: tokenHash,
    handle,
    refreshed_at: Date.now(),
  };
  await setItem(HANDLE_KEY, JSON.stringify(next));
  return handle;
};

/**
 * Register the token the OS gave this device with the account signed in on
 * `serverUrl`: the token itself where the server sends to it directly, the
 * relay's handle for it where the server sends through the relay. Resolves
 * having registered nothing when the server cannot be asked or cannot reach
 * this platform.
 */
export const registerDeviceForPush = async ({
  serverUrl,
  token,
  platform,
  apnsEnvironment = "production",
}: {
  serverUrl: string;
  token: string;
  platform: PushPlatform;
  apnsEnvironment?: ApnsEnvironment;
}): Promise<void> => {
  const serverOrigin = originOf(serverUrl);
  if (!serverOrigin) return;
  const routing = await readPushRouting(serverUrl, platform);
  if (!routing) return;
  if (platform === "android" && !routing.androidViaRelay) {
    await registerPushToken(token, platform);
    return;
  }
  if (!routing.relayServerId) return;
  const handle = await handleFor(
    serverOrigin,
    routing.relayServerId,
    platform,
    token,
    apnsEnvironment
  );
  if (!handle) return;
  await registerPushToken(handle, platform);
};

/**
 * Withdraw what this device registered, so the account stops being sent
 * notifications here, and delete its handle at the relay. Called on
 * sign-out, while the credential still works; nothing to do where nothing
 * was registered.
 */
export const forgetPushOnThisDevice = async (): Promise<void> => {
  const tokens = new Set(registered);
  registered.clear();
  const kept = readKept();
  if (kept) {
    await removeItem(HANDLE_KEY);
    if (kept.server_origin === originOf(getStoredServerUrl())) tokens.add(kept.handle);
  }
  await Promise.allSettled([...tokens].map((token) => unregisterPushToken({ push_token: token })));
  if (kept) await deleteHandle(kept.handle);
};

/**
 * Before the app moves to `nextServerUrl`, or to no server: a handle kept for
 * another server is deleted at the relay. Where somebody was signed in,
 * signing out has already withdrawn it at the old server too; where nobody
 * was, the old server finds out from the relay the next time it sends.
 */
export const releasePushForServerSwitch = async (nextServerUrl: string | null): Promise<void> => {
  const kept = readKept();
  if (kept && nextServerUrl !== null && kept.server_origin === originOf(nextServerUrl)) return;
  registered.clear();
  if (!kept) return;
  await removeItem(HANDLE_KEY);
  await deleteHandle(kept.handle);
};
