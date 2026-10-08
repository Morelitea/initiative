/**
 * Registering this device for push. A server that sends a platform through
 * the push relay is told the relay's handle for the device's token, never the
 * token; the handle is kept so an unchanged launch skips the relay for a
 * week, and signing out or leaving the server deletes it at the relay too.
 */
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import {
  forgetPushOnThisDevice,
  HANDLE_REFRESH_MS,
  PUSH_RELAY_URL,
  registerDeviceForPush,
  registerPushToken,
  releasePushForServerSwitch,
} from "@/lib/pushRegistration";
import { setStoredServerUrl } from "@/lib/serverStorage";

const SERVER = "https://initiative.example.com/api/v1";
const OTHER_SERVER = "https://elsewhere.example.org/api/v1";
const SERVER_ID = "srv_0123456789abcdef";
const APNS_TOKEN = "ab".repeat(32);
const FCM_TOKEN = "fcm:registration-token-1234567890";
const handleNo = (n: number) => `rh_${String(n).padStart(43, "x")}`;

interface Routing {
  push_relay_server_id: string | null;
  android_via_relay: boolean;
}

interface Wire {
  relayRegistrations: Record<string, unknown>[];
  relayDeletes: string[];
  registered: Record<string, unknown>[];
  unregistered: Record<string, unknown>[];
}

const serveRouting = (routing: Routing) =>
  server.use(
    http.get("*/settings/fcm-config", () => HttpResponse.json({ enabled: true, ...routing }))
  );

/** The server's push routes and the relay's device routes, recording what each
 *  was sent. The relay issues a new handle per call. */
const wire = (routing: Routing, relayStatus = 200): Wire => {
  const seen: Wire = { relayRegistrations: [], relayDeletes: [], registered: [], unregistered: [] };
  serveRouting(routing);
  server.use(
    http.post("*/push/register", async ({ request }) => {
      seen.registered.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({ status: "registered" });
    }),
    http.delete("*/push/unregister", async ({ request }) => {
      seen.unregistered.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({ status: "unregistered" });
    }),
    http.post(`${PUSH_RELAY_URL}/v1/devices`, async ({ request }) => {
      seen.relayRegistrations.push((await request.json()) as Record<string, unknown>);
      if (relayStatus !== 200) {
        return HttpResponse.json({ error: "RELAY_SERVER_SUSPENDED" }, { status: relayStatus });
      }
      return HttpResponse.json({ handle: handleNo(seen.relayRegistrations.length) });
    }),
    http.delete(`${PUSH_RELAY_URL}/v1/devices/:handle`, ({ params }) => {
      seen.relayDeletes.push(String(params.handle));
      return new HttpResponse(null, { status: 204 });
    })
  );
  return seen;
};

const sentTokens = (seen: Wire) => seen.registered.map((body) => body.push_token);

beforeEach(() => {
  setStoredServerUrl(SERVER);
});

afterEach(async () => {
  // What this run registered is module state; start the next test without it.
  wire({ push_relay_server_id: null, android_via_relay: false });
  await forgetPushOnThisDevice();
  vi.restoreAllMocks();
});

describe("registerDeviceForPush", () => {
  it("gives the server the relay's handle for an iPhone, never the token", async () => {
    const seen = wire({ push_relay_server_id: SERVER_ID, android_via_relay: false });

    await registerDeviceForPush({ serverUrl: SERVER, token: APNS_TOKEN, platform: "ios" });

    expect(seen.relayRegistrations).toEqual([
      { server_id: SERVER_ID, platform: "ios", token: APNS_TOKEN, environment: "production" },
    ]);
    expect(seen.registered).toEqual([{ push_token: handleNo(1), platform: "ios" }]);
    expect(JSON.stringify(seen.registered)).not.toContain(APNS_TOKEN);
  });

  it("names the sandbox for a debug iPhone build", async () => {
    const seen = wire({ push_relay_server_id: SERVER_ID, android_via_relay: false });

    await registerDeviceForPush({
      serverUrl: SERVER,
      token: APNS_TOKEN,
      platform: "ios",
      apnsEnvironment: "sandbox",
    });

    expect(seen.relayRegistrations[0]?.environment).toBe("sandbox");
  });

  it("names its platform when it asks the server how pushes go", async () => {
    wire({ push_relay_server_id: SERVER_ID, android_via_relay: false });
    const asked: (string | null)[] = [];
    server.use(
      http.get("*/settings/fcm-config", ({ request }) => {
        asked.push(new URL(request.url).searchParams.get("platform"));
        return HttpResponse.json({
          enabled: true,
          push_relay_server_id: null,
          android_via_relay: false,
        });
      })
    );

    await registerDeviceForPush({ serverUrl: SERVER, token: FCM_TOKEN, platform: "android" });
    await registerDeviceForPush({ serverUrl: SERVER, token: APNS_TOKEN, platform: "ios" });

    expect(asked).toEqual(["android", "ios"]);
  });

  it("gives the server Android's own token when it sends through its own Firebase", async () => {
    const seen = wire({ push_relay_server_id: SERVER_ID, android_via_relay: false });

    await registerDeviceForPush({ serverUrl: SERVER, token: FCM_TOKEN, platform: "android" });

    expect(seen.relayRegistrations).toEqual([]);
    expect(seen.registered).toEqual([{ push_token: FCM_TOKEN, platform: "android" }]);
  });

  it("gives the server a handle for Android when Android goes through the relay", async () => {
    const seen = wire({ push_relay_server_id: SERVER_ID, android_via_relay: true });

    await registerDeviceForPush({ serverUrl: SERVER, token: FCM_TOKEN, platform: "android" });

    expect(seen.relayRegistrations).toEqual([
      { server_id: SERVER_ID, platform: "android", token: FCM_TOKEN },
    ]);
    expect(sentTokens(seen)).toEqual([handleNo(1)]);
  });

  it("registers nothing for a relay platform while the server has no relay id", async () => {
    const seen = wire({ push_relay_server_id: null, android_via_relay: true });

    await registerDeviceForPush({ serverUrl: SERVER, token: APNS_TOKEN, platform: "ios" });
    await registerDeviceForPush({ serverUrl: SERVER, token: FCM_TOKEN, platform: "android" });

    expect(seen.relayRegistrations).toEqual([]);
    expect(seen.registered).toEqual([]);
  });

  it("registers nothing when the relay refuses or the server cannot be asked", async () => {
    const seen = wire({ push_relay_server_id: SERVER_ID, android_via_relay: false }, 403);
    await registerDeviceForPush({ serverUrl: SERVER, token: APNS_TOKEN, platform: "ios" });

    server.use(http.get("*/settings/fcm-config", () => HttpResponse.error()));
    await registerDeviceForPush({ serverUrl: SERVER, token: FCM_TOKEN, platform: "android" });

    expect(seen.relayRegistrations).toHaveLength(1);
    expect(seen.registered).toEqual([]);
  });

  it("reuses the kept handle for a week, then asks the relay again", async () => {
    const seen = wire({ push_relay_server_id: SERVER_ID, android_via_relay: false });
    const start = Date.now();
    const now = vi.spyOn(Date, "now").mockReturnValue(start);

    await registerDeviceForPush({ serverUrl: SERVER, token: APNS_TOKEN, platform: "ios" });
    now.mockReturnValue(start + HANDLE_REFRESH_MS - 1);
    await registerDeviceForPush({ serverUrl: SERVER, token: APNS_TOKEN, platform: "ios" });
    expect(seen.relayRegistrations).toHaveLength(1);

    now.mockReturnValue(start + HANDLE_REFRESH_MS);
    await registerDeviceForPush({ serverUrl: SERVER, token: APNS_TOKEN, platform: "ios" });

    expect(seen.relayRegistrations).toHaveLength(2);
    // Every launch tells the server, whether or not the relay was asked.
    expect(sentTokens(seen)).toEqual([handleNo(1), handleNo(1), handleNo(2)]);
    expect(seen.relayDeletes).toEqual([]);
  });

  it("replaces the handle when the token or the server's relay id changes", async () => {
    const seen = wire({ push_relay_server_id: SERVER_ID, android_via_relay: false });
    await registerDeviceForPush({ serverUrl: SERVER, token: APNS_TOKEN, platform: "ios" });

    // The OS rotated the token.
    await registerDeviceForPush({ serverUrl: SERVER, token: "cd".repeat(32), platform: "ios" });
    expect(seen.relayDeletes).toEqual([handleNo(1)]);
    expect(seen.unregistered).toEqual([{ push_token: handleNo(1) }]);

    // The server registered with the relay again and has a new id.
    serveRouting({ push_relay_server_id: "srv_fedcba9876543210", android_via_relay: false });
    await registerDeviceForPush({ serverUrl: SERVER, token: "cd".repeat(32), platform: "ios" });

    expect(seen.relayRegistrations[2]?.server_id).toBe("srv_fedcba9876543210");
    expect(seen.relayDeletes).toEqual([handleNo(1), handleNo(2)]);
    expect(sentTokens(seen)).toEqual([handleNo(1), handleNo(2), handleNo(3)]);
  });
});

describe("withdrawing push", () => {
  it("withdraws every token this device registered, once", async () => {
    const seen = wire({ push_relay_server_id: null, android_via_relay: false });

    await forgetPushOnThisDevice();
    expect(seen.unregistered).toEqual([]);

    await registerPushToken("phone-token", "android");
    await registerPushToken("rotated-token", "android");
    await forgetPushOnThisDevice();
    await forgetPushOnThisDevice();

    expect(seen.unregistered).toHaveLength(2);
    expect(seen.unregistered).toEqual(
      expect.arrayContaining([{ push_token: "phone-token" }, { push_token: "rotated-token" }])
    );
  });

  it("signing out withdraws the kept handle at the server and deletes it at the relay", async () => {
    const seen = wire({ push_relay_server_id: SERVER_ID, android_via_relay: false });
    await registerDeviceForPush({ serverUrl: SERVER, token: APNS_TOKEN, platform: "ios" });

    await forgetPushOnThisDevice();

    expect(seen.unregistered).toEqual([{ push_token: handleNo(1) }]);
    expect(seen.relayDeletes).toEqual([handleNo(1)]);

    // Nothing is kept: the next launch asks the relay again.
    await registerDeviceForPush({ serverUrl: SERVER, token: APNS_TOKEN, platform: "ios" });
    expect(seen.relayRegistrations).toHaveLength(2);
  });

  it("moving to another server deletes the handle at the relay; staying does not", async () => {
    const seen = wire({ push_relay_server_id: SERVER_ID, android_via_relay: false });
    await registerDeviceForPush({ serverUrl: SERVER, token: APNS_TOKEN, platform: "ios" });

    await releasePushForServerSwitch(SERVER);
    expect(seen.relayDeletes).toEqual([]);

    await releasePushForServerSwitch(OTHER_SERVER);
    expect(seen.relayDeletes).toEqual([handleNo(1)]);

    // Already gone: disconnecting has nothing left to delete.
    await releasePushForServerSwitch(null);
    expect(seen.relayDeletes).toEqual([handleNo(1)]);
  });
});
