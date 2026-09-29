import { describe, expect, it } from "vitest";

import { beginNativeSignIn, takePendingSignIn } from "./nativeSignIn";

describe("a sign-in the app began in the phone's browser", () => {
  it("is answered once, and only for the server it began against", async () => {
    const challenge = await beginNativeSignIn("https://one.example");
    expect(challenge).toMatch(/^[A-Za-z0-9_-]{43}$/);

    expect(takePendingSignIn("https://two.example")).toBeNull();
    // Asking about another server spent it too: a callback is answered once.
    expect(takePendingSignIn("https://one.example")).toBeNull();

    await beginNativeSignIn("https://one.example");
    const pending = takePendingSignIn("https://one.example");
    expect(pending?.origin).toBe("https://one.example");
    expect(takePendingSignIn("https://one.example")).toBeNull();
  });
});
