import { beforeEach, describe, expect, it, vi } from "vitest";
import * as Y from "yjs";

import { CollaborationProvider } from "./CollaborationProvider";

const MSG_SYNC_STEP1 = 0;
const MSG_SYNC_STEP2 = 1;
const MSG_UPDATE = 2;
const MSG_CONTENT = 6;

class FakeWebSocket {
  static last: FakeWebSocket | null = null;
  // The provider compares readyState against these, so the stand-in has to
  // carry them too.
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readyState = 1; // OPEN
  binaryType = "";
  sent: Uint8Array[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: ArrayBuffer }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor() {
    FakeWebSocket.last = this;
  }

  send(data: Uint8Array) {
    this.sent.push(data);
  }

  close() {
    this.readyState = 3;
  }

  /** Frames the socket was sent, by leading message-type byte. */
  framesOfType(type: number): Uint8Array[] {
    return this.sent.filter((frame) => frame[0] === type).map((frame) => frame.slice(1));
  }

  /** Deliver a server frame to the provider. */
  deliver(type: number, payload: Uint8Array) {
    const frame = new Uint8Array(1 + payload.length);
    frame[0] = type;
    frame.set(payload, 1);
    this.onmessage?.({ data: frame.buffer as ArrayBuffer });
  }
}

let counter = 0;

/** A connected provider over a fake socket, with ``doc`` as its state. */
const connect = (doc: Y.Doc) => {
  counter += 1;
  const provider = new CollaborationProvider(
    "ws://test/ws",
    "room",
    doc,
    { auth: { token: "t" } },
    `/connection-${counter}`
  );
  const socket = FakeWebSocket.last as FakeWebSocket;
  socket.onopen?.();
  return { provider, socket };
};

/** The state vector of a peer holding ``doc``'s content. */
const stateVectorOf = (doc: Y.Doc) => Y.encodeStateVector(doc);

beforeEach(() => {
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
  FakeWebSocket.last = null;
});

describe("CollaborationProvider sync handshake", () => {
  it("answers the server's SYNC_STEP1 with the state the server is missing", () => {
    // A client holding work the room has never seen — what a tab looks like
    // after the server rebuilt its room from an older row.
    const doc = new Y.Doc();
    doc.getMap("cells").set("A1", "kept");
    const { socket } = connect(doc);

    socket.deliver(MSG_SYNC_STEP1, stateVectorOf(new Y.Doc()));

    const answers = socket.framesOfType(MSG_SYNC_STEP2);
    expect(answers).toHaveLength(1);

    // What came back reconstructs the work on a doc that never had it.
    const server = new Y.Doc();
    Y.applyUpdate(server, answers[0]);
    expect(server.getMap("cells").get("A1")).toBe("kept");
  });

  it("stays quiet when the server already has everything it holds", () => {
    const doc = new Y.Doc();
    doc.getMap("cells").set("A1", "shared");
    const { socket } = connect(doc);

    // The server's state vector already covers this client's doc.
    socket.deliver(MSG_SYNC_STEP1, stateVectorOf(doc));

    expect(socket.framesOfType(MSG_SYNC_STEP2)).toHaveLength(0);
  });

  it("sends its own SYNC_STEP1 on connect, so both directions settle", () => {
    const { socket } = connect(new Y.Doc());

    expect(socket.framesOfType(MSG_SYNC_STEP1)).toHaveLength(1);
  });

  it("relays local edits as updates without echoing what the server sent", () => {
    const doc = new Y.Doc();
    const { socket } = connect(doc);
    const peer = new Y.Doc();
    peer.getMap("cells").set("B2", "from a peer");

    socket.deliver(MSG_UPDATE, Y.encodeStateAsUpdate(peer));
    const afterRemote = socket.framesOfType(MSG_UPDATE).length;

    doc.getMap("cells").set("C3", "mine");

    expect(doc.getMap("cells").get("B2")).toBe("from a peer");
    // The peer's update was applied but not sent back; the local edit was sent.
    expect(socket.framesOfType(MSG_UPDATE)).toHaveLength(afterRemote + 1);
  });

  it("reports content to the room only once synced", () => {
    const { provider, socket } = connect(new Y.Doc());

    // Before the initial sync lands, this client's doc is not yet the room's.
    provider.sendContent({ root: "too early" });
    expect(socket.framesOfType(MSG_CONTENT)).toHaveLength(0);

    socket.deliver(MSG_SYNC_STEP2, Y.encodeStateAsUpdate(new Y.Doc()));
    provider.sendContent({ root: "ready" });

    const frames = socket.framesOfType(MSG_CONTENT);
    expect(frames).toHaveLength(1);
    expect(JSON.parse(new TextDecoder().decode(frames[0]))).toEqual({ root: "ready" });
  });
});
