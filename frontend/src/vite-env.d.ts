/// <reference types="vite/client" />

declare const __APP_VERSION__: string;
declare const __IS_CAPACITOR__: boolean;

// Type declarations for Yjs-related packages
declare module "y-protocols/awareness" {
  import { Doc } from "yjs";

  export class Awareness {
    constructor(doc: Doc);
    clientID: number;
    getLocalState(): Record<string, unknown> | null;
    setLocalState(state: Record<string, unknown> | null): void;
    setLocalStateField(field: string, value: unknown): void;
    getStates(): Map<number, Record<string, unknown>>;
    on(event: "change" | "update", callback: (...args: unknown[]) => void): void;
    off(event: "change" | "update", callback: (...args: unknown[]) => void): void;
    destroy(): void;
  }
}
