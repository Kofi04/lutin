import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CoreClient, type Endpoint, type Host, type SocketLike } from "./client";

class FakeSocket implements SocketLike {
  readyState = 0;
  onopen: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  sent: { type: string; payload: Record<string, unknown> }[] = [];
  closed = false;

  constructor(readonly url: string) {}

  send(data: string): void {
    this.sent.push(JSON.parse(data));
  }
  close(): void {
    this.closed = true;
  }
  // -- what the core would do
  open(): void {
    this.readyState = 1;
    this.onopen?.({});
  }
  deliver(type: string, payload: object = {}): void {
    this.onmessage?.({ data: JSON.stringify({ type, payload }) });
  }
  drop(): void {
    this.readyState = 3;
    this.onclose?.({});
  }
}

class FakeHost implements Host {
  current: Endpoint | null = { port: 4000, token: "t0k3n" };
  listener: ((endpoint: Endpoint | null) => void) | null = null;
  visible = true;
  calls: string[] = [];

  async endpoint() {
    return this.current;
  }
  onEndpoint(listener: (endpoint: Endpoint | null) => void) {
    this.listener = listener;
  }
  async hideWindow() {
    this.calls.push("hide");
    const was = this.visible;
    this.visible = false;
    return was;
  }
  async showWindow() {
    this.calls.push("show");
    this.visible = true;
  }
}

let sockets: FakeSocket[];
let host: FakeHost;
let client: CoreClient;

async function online(): Promise<FakeSocket> {
  await client.start();
  const socket = sockets.at(-1)!;
  socket.open();
  socket.deliver("hello.ok", { protocol: 1, version: "t", pid: 1 });
  return socket;
}

beforeEach(() => {
  vi.useFakeTimers();
  sockets = [];
  host = new FakeHost();
  client = new CoreClient("avatar", host, (url) => {
    const socket = new FakeSocket(url);
    sockets.push(socket);
    return socket;
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("connecting", () => {
  it("says hello with the token and its role, on loopback", async () => {
    const socket = await online();
    expect(socket.url).toBe("ws://127.0.0.1:4000");
    expect(socket.sent[0]).toEqual({
      type: "hello",
      payload: { token: "t0k3n", protocol: 1, role: "avatar" },
    });
    expect(client.status).toBe("online");
  });

  it("sends nothing before hello.ok", async () => {
    await client.start();
    sockets[0]!.open();
    expect(client.send("ask", { text: "trop tôt" })).toBe(false);
  });

  it("does not connect while the core is down", async () => {
    host.current = null;
    await client.start();
    expect(sockets).toEqual([]);
  });
});

describe("staying connected", () => {
  it("retries with growing delays after the connection drops", async () => {
    const first = await online();
    first.drop();
    expect(client.status).toBe("offline");

    vi.advanceTimersByTime(499);
    expect(sockets).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(sockets).toHaveLength(2);

    sockets[1]!.drop();
    vi.advanceTimersByTime(999);
    expect(sockets).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(sockets).toHaveLength(3);
  });

  it("follows the core to its new port after a restart", async () => {
    const first = await online();
    host.listener!(null);
    expect(first.closed).toBe(true);
    expect(client.status).toBe("offline");

    host.listener!({ port: 5000, token: "t0k3n" });
    expect(sockets.at(-1)!.url).toBe("ws://127.0.0.1:5000");
  });

  it("stops retrying once told the core is gone", async () => {
    const first = await online();
    host.listener!(null);
    first.drop();
    vi.advanceTimersByTime(60_000);
    expect(sockets).toHaveLength(1);
  });
});

describe("events", () => {
  it("delivers typed payloads to their handlers", async () => {
    const moods: string[] = [];
    client.on("mood", (payload) => moods.push(payload.mood));
    const socket = await online();
    socket.deliver("mood", { mood: "waiting" });
    expect(moods).toEqual(["waiting"]);
  });

  it("ignores a malformed message instead of crashing", async () => {
    const seen: string[] = [];
    client.onAny((message) => seen.push(message.type));
    const socket = await online();
    socket.deliver("mood", { mood: "grumpy" });
    socket.deliver("toast", { title: "ok", body: "", kind: "info" });
    expect(seen).toEqual(["hello.ok", "toast"]);
  });
});

describe("the cloak", () => {
  it("hides the window before acknowledging, then shows it again", async () => {
    const socket = await online();
    socket.deliver("cloak.hide", { cloak_id: "c1" });
    await vi.waitFor(() => expect(socket.sent.at(-1)?.type).toBe("cloak.ack"));
    expect(host.calls).toEqual(["hide"]);
    expect(socket.sent.at(-1)).toEqual({
      type: "cloak.ack",
      payload: { cloak_id: "c1" },
    });

    socket.deliver("cloak.show", { cloak_id: "c1" });
    expect(host.calls).toEqual(["hide", "show"]);
  });

  it("does not show a window that was hidden before the grab", async () => {
    host.visible = false;
    const socket = await online();
    socket.deliver("cloak.hide", { cloak_id: "c1" });
    await vi.waitFor(() => expect(socket.sent.at(-1)?.type).toBe("cloak.ack"));
    socket.deliver("cloak.show", { cloak_id: "c1" });
    expect(host.calls).toEqual(["hide"]);
  });
});
