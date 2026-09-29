import { describe, expect, it } from "vitest";

import { verifiedStatement } from "./otaTrust";

const toBase64 = (buffer: ArrayBuffer) => btoa(String.fromCharCode(...new Uint8Array(buffer)));

const keyPair = () =>
  crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign", "verify"]);

describe("an app update's signed statement", () => {
  it("verifies against a trusted key, and only over its exact bytes", async () => {
    const trusted = await keyPair();
    const other = await keyPair();
    const spki = toBase64(await crypto.subtle.exportKey("spki", trusted.publicKey));
    const statement = JSON.stringify({
      v: 1,
      version: "0.72.0",
      sha256: "ab",
      minNativeVersion: "0.70.0",
    });
    const signWith = async (key: CryptoKey, text: string) =>
      toBase64(
        await crypto.subtle.sign(
          { name: "ECDSA", hash: "SHA-256" },
          key,
          new TextEncoder().encode(text)
        )
      );

    const signature = await signWith(trusted.privateKey, statement);
    expect(await verifiedStatement(statement, signature, [spki])).toMatchObject({
      version: "0.72.0",
      sha256: "ab",
      minNativeVersion: "0.70.0",
    });

    expect(await verifiedStatement(statement.replace("ab", "cd"), signature, [spki])).toBeNull();
    expect(
      await verifiedStatement(statement, await signWith(other.privateKey, statement), [spki])
    ).toBeNull();
    expect(await verifiedStatement(statement, "not base64!", [spki])).toBeNull();
  });
});
