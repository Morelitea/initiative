/**
 * Stands in for the browser's WebSocket, with the transitions driven by hand.
 *
 * Both push channels — the personal notification stream and the per-guild
 * events bus — are the same shape: a socket that authenticates in its first
 * frame, reconnects on its own, and is watched for going quiet. Their tests
 * drive it the same way, so the double is shared rather than written twice.
 *
 * Install it with `vi.stubGlobal("WebSocket", MockWebSocket)` and clear
 * {@link MockWebSocket.instances} between tests.
 */
export class MockWebSocket {
  static instances: MockWebSocket[] = [];
  // The hooks read these off the constructor, which is this once stubbed in.
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  url: string;
  binaryType = "blob";
  sent: Uint8Array[] = [];
  closed = false;
  readyState: number = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: Uint8Array) {
    this.sent.push(data);
  }

  close() {
    this.closed = true;
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code: 1000 });
  }

  // ── Driving helpers ──
  open() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  receive(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  serverClose(code: number) {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code });
  }

  /** The first frame is `[MSG_AUTH, ...utf8 json]`. */
  authPayload(): unknown {
    return JSON.parse(new TextDecoder().decode(this.sent[0].slice(1)));
  }
}

/** The socket most recently constructed — the one a hook just opened. */
export const latestSocket = () => MockWebSocket.instances.at(-1) as MockWebSocket;
