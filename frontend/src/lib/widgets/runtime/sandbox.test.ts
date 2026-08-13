import { afterEach, describe, expect, it } from "vitest";

import { disposeSandbox, renderInSandbox, SandboxErrorCode, type SandboxResult } from "./sandbox";

afterEach(() => {
  disposeSandbox();
});

const run = (source: string, data: unknown = {}, config: unknown = {}) =>
  renderInSandbox({ source, data, config });

const expectValue = (result: SandboxResult) => {
  expect(result.ok, `expected success, got ${JSON.stringify(result)}`).toBe(true);
  if (!result.ok) throw new Error("unreachable");
  return result.value;
};

const expectCode = (result: SandboxResult, code: SandboxErrorCode) => {
  expect(result.ok).toBe(false);
  if (result.ok) throw new Error("unreachable");
  expect(result.code).toBe(code);
};

describe("the widget sandbox", () => {
  it("runs a widget and returns its scene", async () => {
    const result = await run(
      `function render(data, config) {
         return { v: 1, scene: { kind: "metric", value: data.count, label: config.label } };
       }`,
      { count: 7 },
      { label: "Open" }
    );
    expect(expectValue(result)).toEqual({
      v: 1,
      scene: { kind: "metric", value: 7, label: "Open" },
    });
  });

  // The security property this whole design rests on. Pinned as an exact set
  // rather than a list of things we thought to probe: QuickJS-ng already ships
  // three globals beyond bare ECMAScript (performance, queueMicrotask,
  // SharedArrayBuffer, all removed in the prelude), and the next runtime bump
  // may ship more. An exact assertion turns that into a failing test instead of
  // a capability every widget quietly inherits.
  it("exposes exactly the expected globals and nothing more", async () => {
    const expected = [
      // Bare ECMAScript, plus the two strings we hand the widget its inputs in.
      "AggregateError",
      "Array",
      "ArrayBuffer",
      "BigInt",
      "BigInt64Array",
      "BigUint64Array",
      "Boolean",
      "DOMException",
      "DataView",
      "Date",
      "Error",
      "EvalError",
      "FinalizationRegistry",
      "Float16Array",
      "Float32Array",
      "Float64Array",
      "Function",
      "Infinity",
      "Int16Array",
      "Int32Array",
      "Int8Array",
      "InternalError",
      "Iterator",
      "JSON",
      "Map",
      "Math",
      "NaN",
      "Number",
      "Object",
      "Promise",
      "Proxy",
      "RangeError",
      "ReferenceError",
      "Reflect",
      "RegExp",
      "Set",
      "String",
      "Symbol",
      "SyntaxError",
      "TypeError",
      "URIError",
      "Uint16Array",
      "Uint32Array",
      "Uint8Array",
      "Uint8ClampedArray",
      "WeakMap",
      "WeakRef",
      "WeakSet",
      "__config__",
      "__data__",
      "decodeURI",
      "decodeURIComponent",
      "encodeURI",
      "encodeURIComponent",
      "escape",
      "eval",
      "globalThis",
      "isFinite",
      "isNaN",
      "parseFloat",
      "parseInt",
      "render",
      "undefined",
      "unescape",
    ].sort();

    const result = await run(
      `function render() { return Object.getOwnPropertyNames(globalThis).sort(); }`
    );
    expect(expectValue(result)).toEqual(expected);
  });

  // Reads as documentation of intent; the exact-set assertion above is what
  // actually holds the line.
  it.each([
    "fetch",
    "XMLHttpRequest",
    "WebSocket",
    "EventSource",
    "navigator",
    "location",
    "document",
    "window",
    "self",
    "localStorage",
    "sessionStorage",
    "indexedDB",
    "crypto",
    "Worker",
    "importScripts",
    "process",
    "require",
    "module",
    "performance",
    "postMessage",
    "setTimeout",
    "setInterval",
    "queueMicrotask",
    "SharedArrayBuffer",
  ])("has no ambient %s", async (global) => {
    const result = await run(
      `function render() { return { present: typeof ${global} !== "undefined" }; }`
    );
    expect(expectValue(result)).toEqual({ present: false });
  });

  it("cannot reach the host through the constructor chain", async () => {
    const result = await run(
      `function render() {
         try {
           var host = (function () {}).constructor("return typeof fetch")();
           return { escaped: host !== "undefined" };
         } catch (err) {
           return { escaped: false, blocked: true };
         }
       }`
    );
    const value = expectValue(result) as { escaped: boolean };
    expect(value.escaped).toBe(false);
  });

  it("isolates widgets from each other", async () => {
    await run(`globalThis.leaked = "secret"; function render() { return 1; }`);
    const result = await run(`function render() { return { saw: typeof globalThis.leaked }; }`);
    expect(expectValue(result)).toEqual({ saw: "undefined" });
  });

  it("kills an infinite loop instead of hanging the canvas", async () => {
    const result = await renderInSandbox({
      source: `function render() { while (true) {} }`,
      data: {},
      config: {},
      limits: { timeoutMs: 50 },
    });
    expectCode(result, SandboxErrorCode.TIMEOUT);
  });

  it("stays usable after a widget times out", async () => {
    await renderInSandbox({
      source: `function render() { while (true) {} }`,
      data: {},
      config: {},
      limits: { timeoutMs: 50 },
    });
    const result = await run(`function render() { return { fine: true }; }`);
    expect(expectValue(result)).toEqual({ fine: true });
  });

  it("caps memory", async () => {
    const result = await renderInSandbox({
      source: `function render() {
                 var acc = [];
                 while (true) acc.push(new Array(10000).fill("x"));
               }`,
      data: {},
      config: {},
      limits: { memoryBytes: 1024 * 1024, timeoutMs: 5000 },
    });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect([SandboxErrorCode.OUT_OF_MEMORY, SandboxErrorCode.TIMEOUT]).toContain(result.code);
  });

  it("reports a widget that throws", async () => {
    const result = await run(`function render() { throw new Error("boom"); }`);
    expectCode(result, SandboxErrorCode.THREW);
    if (!result.ok) expect(result.detail).toContain("boom");
  });

  it("reports a module with no render export", async () => {
    const result = await run(`var notRender = 1;`);
    expectCode(result, SandboxErrorCode.NO_RENDER_EXPORT);
  });

  it("reports output JSON cannot represent", async () => {
    const result = await run(`function render() { var a = {}; a.self = a; return a; }`);
    expectCode(result, SandboxErrorCode.BAD_OUTPUT);
  });

  it("does not let data be parsed as code", async () => {
    const result = await run(`function render(data) { return { got: data.evil }; }`, {
      evil: '"); globalThis.pwned = 1; ("',
    });
    expect(expectValue(result)).toEqual({ got: '"); globalThis.pwned = 1; ("' });
  });

  describe("determinism", () => {
    it("seeds Math.random", async () => {
      const source = `function render() { return [Math.random(), Math.random()]; }`;
      const a = await renderInSandbox({ source, data: {}, config: {}, seed: 42 });
      const b = await renderInSandbox({ source, data: {}, config: {}, seed: 42 });
      const c = await renderInSandbox({ source, data: {}, config: {}, seed: 7 });
      expect(expectValue(a)).toEqual(expectValue(b));
      expect(expectValue(a)).not.toEqual(expectValue(c));
    });

    it("freezes the clock, so a render is a function of its inputs", async () => {
      const source = `function render() { return [Date.now(), new Date().getTime()]; }`;
      const result = await renderInSandbox({
        source,
        data: {},
        config: {},
        now: 1_700_000_000_000,
      });
      expect(expectValue(result)).toEqual([1_700_000_000_000, 1_700_000_000_000]);
    });

    it("still allows explicit dates", async () => {
      const result = await renderInSandbox({
        source: `function render() { return new Date(86_400_000).getTime(); }`,
        data: {},
        config: {},
        now: 0,
      });
      expect(expectValue(result)).toBe(86_400_000);
    });
  });
});
