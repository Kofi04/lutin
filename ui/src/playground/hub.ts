/**
 * A stand-in for the Python core, for the playground and the tests.
 *
 * Each window keeps its real CoreClient; only the socket is fake. The hub
 * answers `hello` like the core, broadcasts the events it is given, records
 * the commands the windows send, and can go down and come back up like a
 * crashed and restarted core. Nothing here touches the network.
 */

import type { Endpoint, Host, SocketLike } from "../core/client";
import { decode, type UiMessage } from "../protocol";

const ENDPOINT: Endpoint = { port: 1, token: "playground" };

/** What the core repeats to every window that connects (presenter_remote.py). */
const STATE_TYPES = ["mood", "connection", "sessions.update", "quiet"];
const OPEN = 1;
const CLOSED = 3;

export interface SentCommand {
  role: string;
  message: UiMessage;
}

class FakeSocket implements SocketLike {
  readyState = 0;
  onopen: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  role = "";

  constructor(private readonly hub: Hub) {
    // Opens asynchronously, like a real socket.
    queueMicrotask(() => {
      if (!hub.up) {
        this.drop();
        return;
      }
      this.readyState = OPEN;
      hub.sockets.add(this);
      this.onopen?.({});
    });
  }

  send(data: string): void {
    const message = decode(data, "ui");
    if (message.type === "hello") {
      this.role = message.payload.role;
      this.receive("hello.ok", { protocol: 1, version: "playground", pid: 0 });
      for (const [type, payload] of this.hub.state) this.receive(type, payload);
      return;
    }
    this.hub.record(this.role, message);
  }

  close(): void {
    this.drop();
  }

  receive(type: string, payload: object): void {
    if (this.readyState !== OPEN) return;
    this.onmessage?.({ data: JSON.stringify({ type, payload }) });
  }

  drop(): void {
    if (this.readyState === CLOSED) return;
    this.readyState = CLOSED;
    this.hub.sockets.delete(this);
    this.onclose?.({});
  }
}

export class Hub {
  up = true;
  readonly sockets = new Set<FakeSocket>();
  readonly sent: SentCommand[] = [];
  /** The latest of each state event, replayed on connection like the core does. */
  readonly state = new Map<string, object>();
  private endpointListeners = new Set<(endpoint: Endpoint | null) => void>();
  private commandListeners = new Set<(command: SentCommand) => void>();

  makeSocket = (_url: string): SocketLike => new FakeSocket(this);

  /** A Host for one window; `visible` mirrors what Tauri would do to it. */
  host(setVisible: (visible: boolean) => void, isVisible: () => boolean): Host {
    return {
      endpoint: async () => (this.up ? ENDPOINT : null),
      onEndpoint: (listener) => {
        this.endpointListeners.add(listener);
      },
      hideWindow: async () => {
        const was = isVisible();
        setVisible(false);
        return was;
      },
      showWindow: async () => setVisible(true),
    };
  }

  broadcast(type: string, payload: object): void {
    if (STATE_TYPES.includes(type)) this.state.set(type, payload);
    for (const socket of [...this.sockets]) socket.receive(type, payload);
  }

  /** Like a core that crashed: every connection drops, the endpoint is gone. */
  down(): void {
    this.up = false;
    for (const listener of this.endpointListeners) listener(null);
    for (const socket of [...this.sockets]) socket.drop();
  }

  /** Like the supervisor announcing a restarted core. */
  restart(): void {
    this.up = true;
    for (const listener of this.endpointListeners) listener(ENDPOINT);
  }

  record(role: string, message: UiMessage): void {
    const command = { role, message };
    this.sent.push(command);
    for (const listener of this.commandListeners) listener(command);
  }

  onCommand(listener: (command: SentCommand) => void): () => void {
    this.commandListeners.add(listener);
    return () => this.commandListeners.delete(listener);
  }
}
