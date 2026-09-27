import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { forgetPushOnThisDevice, registerPushToken } from "@/lib/pushRegistration";

describe("pushRegistration", () => {
  it("withdraws the token this device registered, once", async () => {
    const withdrawn: unknown[] = [];
    server.use(
      http.post("*/push/register", () => HttpResponse.json({ status: "registered" })),
      http.delete("*/push/unregister", async ({ request }) => {
        withdrawn.push(await request.json());
        return HttpResponse.json({ status: "unregistered" });
      })
    );

    await forgetPushOnThisDevice();
    expect(withdrawn).toEqual([]);

    await registerPushToken("phone-token", "android");
    await forgetPushOnThisDevice();
    await forgetPushOnThisDevice();

    expect(withdrawn).toEqual([{ push_token: "phone-token" }]);
  });
});
