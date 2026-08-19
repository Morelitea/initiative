/**
 * The widget executor.
 *
 * Every widget — the built-in bar chart as much as an installed listing's —
 * runs here. There is no privileged path: a widget is JS source exposing
 * `render(data, config)`, evaluated by QuickJS compiled to WebAssembly, and its
 * only way out is a JSON value we then validate (`../validateScene`).
 *
 * A WASM interpreter is the right executor because it starts with *no host
 * bindings at all* — `fetch`, `document`, `localStorage`, `Worker` and the rest
 * are simply absent rather than removed, so there is no list to keep in sync
 * and nothing to forget. `sandbox.test.ts` asserts that as a standing
 * regression test.
 *
 * What the host still owes the sandbox is *bounding*: an interpreter with no
 * capabilities can still loop forever or allocate without end, so every
 * evaluation carries an interrupt deadline and a memory cap.
 */

import releaseSyncVariant from "@jitl/quickjs-ng-wasmfile-release-sync";
import { newQuickJSWASMModuleFromVariant, type QuickJSRuntime } from "quickjs-emscripten-core";

export const SandboxErrorCode = {
  UNAVAILABLE: "WIDGET_RUNTIME_UNAVAILABLE",
  TIMEOUT: "WIDGET_TIMEOUT",
  OUT_OF_MEMORY: "WIDGET_OUT_OF_MEMORY",
  THREW: "WIDGET_THREW",
  NO_RENDER_EXPORT: "WIDGET_NO_RENDER_EXPORT",
  BAD_OUTPUT: "WIDGET_BAD_OUTPUT",
} as const;
export type SandboxErrorCode = (typeof SandboxErrorCode)[keyof typeof SandboxErrorCode];

export type SandboxResult =
  | { ok: true; value: unknown }
  | { ok: false; code: SandboxErrorCode; detail?: string };

export interface SandboxLimits {
  /** Wall-clock budget for one `render` call. Generous next to the ~2ms a
   *  built-in takes, tight enough that a stuck widget is caught within a frame
   *  or two. */
  timeoutMs: number;
  memoryBytes: number;
  stackBytes: number;
}

export const DEFAULT_LIMITS: SandboxLimits = {
  timeoutMs: 250,
  // Sized with the scene limits in mind: a legitimately large binding (a
  // 10k-row table and the data it was built from, both alive at once during
  // render) has to fit with room to spare, or the cap punishes real data.
  memoryBytes: 64 * 1024 * 1024,
  stackBytes: 512 * 1024,
};

export interface RenderRequest {
  /** Widget module source: JS defining a top-level `render`. */
  source: string;
  data: unknown;
  config: unknown;
  limits?: Partial<SandboxLimits>;
  /** Seeds the deterministic shims. Same inputs + same seed ⇒ same scene, which
   *  is what lets the host memoize a render. */
  seed?: number;
  now?: number;
  /** The viewer's language tag, handed to `render` as its third argument.
   *
   *  A widget's *own* output has to be readable — a table's column headings are
   *  the widget's words, not ours, and there is no app locale file a
   *  marketplace widget could add itself to. So the module carries its strings
   *  the way it already carries its name, and this says which set to use.
   *
   *  A tag, never `Intl`: the sandbox still has no locale data and no timezone,
   *  and formatting a number or a date stays the host's job. A render is
   *  therefore still a pure function of its inputs, now including this one. */
  locale?: string;
}

/**
 * Establishes the widget's world: deterministic clock and RNG, and none of the
 * host-ish globals QuickJS-ng supplies beyond bare ECMAScript.
 *
 * Determinism is not only reproducibility — it means the renderer, not the
 * widget, decides how a timestamp is displayed, and it lets the host memoize a
 * render on its inputs.
 */
const PRELUDE = `
(function (seed, now) {
  var state = seed >>> 0;
  Math.random = function () {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };

  var RealDate = Date;
  function FrozenDate() {
    if (!(this instanceof FrozenDate)) return new RealDate(now).toString();
    return arguments.length === 0
      ? new RealDate(now)
      : new RealDate(...Array.prototype.slice.call(arguments));
  }
  FrozenDate.prototype = RealDate.prototype;
  FrozenDate.now = function () { return now; };
  FrozenDate.parse = RealDate.parse;
  FrozenDate.UTC = RealDate.UTC;
  Date = FrozenDate;
})(__seed__, __now__);
delete globalThis.__seed__;
delete globalThis.__now__;

// None of these help compute a scene, and each is something we would otherwise
// hand every widget: a high-resolution timer, async scheduling for a contract
// that is synchronous, and shared memory. sandbox.test.ts pins the resulting
// global set exactly, so whatever a future runtime adds has to be considered
// rather than silently inherited.
delete globalThis.performance;
delete globalThis.queueMicrotask;
delete globalThis.SharedArrayBuffer;
`;

/** Calls the widget and hands back a tagged string: `v:<json>` for a value,
 *  `e:<reason>` for a fault we can name from in here. The widget's own source is
 *  evaluated separately from this, so a stray brace in it cannot change what
 *  this expression means.
 *
 *  A `render` that throws is deliberately *not* caught — the host classifies it
 *  from the evaluation error, which is also how an interrupt or a tripped memory
 *  cap surfaces. */
const INVOKE = `
(function () {
  if (typeof render !== "function") return "e:no-render";
  var out = render(JSON.parse(__data__), JSON.parse(__config__), { locale: __locale__ });
  try {
    return "v:" + JSON.stringify(out === undefined ? null : out);
  } catch (err) {
    return "e:bad-output";
  }
})();
`;

/** Reads the module's `meta` export — the widget's own name, description, and
 *  option labels. Static, so it is read once per module rather than per render.
 *  A module without meta is not an error: the caller falls back to the type id. */
const READ_META = `
(function () {
  if (typeof meta === "undefined") return "v:null";
  try {
    return "v:" + JSON.stringify(meta);
  } catch (err) {
    return "e:bad-output";
  }
})();
`;

let modulePromise: ReturnType<typeof newQuickJSWASMModuleFromVariant> | null = null;
let runtime: QuickJSRuntime | null = null;
let deadline = Number.POSITIVE_INFINITY;

/** One runtime per thread, contexts per render (§6.2): contexts are cheap and
 *  give each widget an isolated global, so two widgets on a canvas cannot see
 *  each other's state. */
async function getRuntime(limits: SandboxLimits): Promise<QuickJSRuntime> {
  if (!runtime) {
    modulePromise ??= newQuickJSWASMModuleFromVariant(releaseSyncVariant);
    const quickjs = await modulePromise;
    runtime = quickjs.newRuntime();
    runtime.setInterruptHandler(() => now() > deadline);
  }
  runtime.setMemoryLimit(limits.memoryBytes);
  runtime.setMaxStackSize(limits.stackBytes);
  return runtime;
}

const now = (): number => (typeof performance !== "undefined" ? performance.now() : Date.now());

/** QuickJS reports both budget failures as `InternalError`; the message is what
 *  separates "looped forever" from "allocated forever". */
const classify = (message: string, timedOut: boolean): SandboxErrorCode => {
  if (timedOut || /interrupted/i.test(message)) return SandboxErrorCode.TIMEOUT;
  if (/out of memory|stack overflow/i.test(message)) {
    return SandboxErrorCode.OUT_OF_MEMORY;
  }
  return SandboxErrorCode.THREW;
};

/** Release the runtime — used when a memory cap leaves it in an unusable state,
 *  and by tests between cases. */
export function disposeSandbox(): void {
  runtime?.dispose();
  runtime = null;
}

/** Shared evaluation path: boot the runtime, establish the widget's world,
 *  evaluate its module, then run one of our own expressions against it. Both
 *  entry points below go through here, so meta is read under exactly the same
 *  capability, interrupt, and memory bounds a render is. */
async function evaluateModule(request: RenderRequest, invoke: string): Promise<SandboxResult> {
  const limits = { ...DEFAULT_LIMITS, ...request.limits };

  let vm: QuickJSRuntime;
  try {
    vm = await getRuntime(limits);
  } catch (error) {
    return {
      ok: false,
      code: SandboxErrorCode.UNAVAILABLE,
      detail: error instanceof Error ? error.message : String(error),
    };
  }

  const context = vm.newContext();
  deadline = now() + limits.timeoutMs;

  try {
    // Values arrive as global strings rather than being interpolated into
    // source, so nothing in the data can be parsed as code.
    for (const [name, value] of [
      ["__data__", JSON.stringify(request.data ?? null)],
      ["__config__", JSON.stringify(request.config ?? {})],
      ["__locale__", request.locale ?? "en"],
    ] as const) {
      const handle = context.newString(value);
      context.setProp(context.global, name, handle);
      handle.dispose();
    }
    for (const [name, value] of [
      ["__seed__", request.seed ?? 1],
      ["__now__", request.now ?? 0],
    ] as const) {
      const handle = context.newNumber(value);
      context.setProp(context.global, name, handle);
      handle.dispose();
    }

    for (const [code, stage] of [
      [PRELUDE, "prelude"],
      [request.source, "module"],
    ] as const) {
      const evaluated = context.evalCode(code);
      if (evaluated.error) {
        const message = String(context.dump(evaluated.error)?.message ?? "");
        evaluated.error.dispose();
        return {
          ok: false,
          // A failure in our own prelude is a runtime fault, not the widget's.
          code:
            stage === "prelude"
              ? SandboxErrorCode.UNAVAILABLE
              : classify(message, now() > deadline),
          detail: message,
        };
      }
      evaluated.value.dispose();
    }

    const invoked = context.evalCode(invoke);
    if (invoked.error) {
      const message = String(context.dump(invoked.error)?.message ?? "");
      invoked.error.dispose();
      return {
        ok: false,
        code: classify(message, now() > deadline),
        detail: message,
      };
    }

    const raw = context.dump(invoked.value);
    invoked.value.dispose();

    if (typeof raw !== "string") {
      return { ok: false, code: SandboxErrorCode.BAD_OUTPUT };
    }
    if (raw === "e:no-render") {
      return { ok: false, code: SandboxErrorCode.NO_RENDER_EXPORT };
    }
    if (!raw.startsWith("v:")) {
      // `render` returned something JSON.stringify could not represent — a
      // BigInt, or a structure with a cycle.
      return { ok: false, code: SandboxErrorCode.BAD_OUTPUT };
    }
    try {
      return { ok: true, value: JSON.parse(raw.slice(2)) };
    } catch {
      return { ok: false, code: SandboxErrorCode.BAD_OUTPUT };
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const code = classify(message, now() > deadline);
    // A tripped memory cap can leave the runtime unable to allocate again, so
    // the next widget gets a fresh one rather than a spurious failure.
    if (code === SandboxErrorCode.OUT_OF_MEMORY) disposeSandbox();
    return { ok: false, code, detail: message };
  } finally {
    deadline = Number.POSITIVE_INFINITY;
    if (runtime === vm) {
      try {
        context.dispose();
      } catch {
        // The context can already be gone if the runtime was torn down above.
      }
    }
  }
}

export async function renderInSandbox(request: RenderRequest): Promise<SandboxResult> {
  return evaluateModule(request, INVOKE);
}

/** Read a widget module's declared metadata. Resolves with `value: null` when
 *  the module declares none. */
export async function readMetaInSandbox(
  source: string,
  limits?: Partial<SandboxLimits>
): Promise<SandboxResult> {
  return evaluateModule({ source, data: null, config: {}, limits }, READ_META);
}
