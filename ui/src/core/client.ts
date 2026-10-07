/**
 * One window's connection to the Python core.
 *
 * Each Tauri window holds its own: it authenticates with its role, receives
 * every event, and sends commands. The connection survives the core
 * restarting: the host (Tauri) announces each new endpoint, and the client
 * reconnects to it.
 *
 * The cloak is handled here, once for every window: on `cloak.hide` the window
 * hides itself, then acknowledges; on `cloak.show` it comes back, but only if
 * it was visible before. Without the ack the core abandons the capture.
 */

import {
  type CoreMessage,
  type CorePayloads,
  type CoreType,
  decode,
  encode,
  PROTOCOL_VERSION,
  type Role,
  type UiPayloads,
  type UiType,
} from "../protocol";

export interface Endpoint {
  port: number;
  token: string;
}

/** What the window's host provides: Tauri in the app, a fake in tests. */
export interface Host {
  endpoint(): Promise<Endpoint | null>;
  /** Called with each new endpoint, or null when the core goes down. */
  onEndpoint(listener: (endpoint: Endpoint | null) => void): void;
  /** Hide this window; resolves to whether it was visible. */
  hideWindow(): Promise<boolean>;
  showWindow(): Promise<void>;
}

/** The part of WebSocket the client uses, so tests can stand in for it. */
export interface SocketLike {
  readonly readyState: number;
  onopen: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: unknown) => void) | null;
  onerror: ((event: unknown) => void) | null;
  send(data: string): void;
  close(): void;
}

export type Status = "connecting" | "online" | "offline";

const OPEN = 1;
const RETRY_MS = [500, 1000, 2000, 5000];

type Handler<K extends CoreType> = (
  payload: CorePayloads[K],
  message: CoreMessage,
) => void;

export class CoreClient {
  status: Status = "offline";

  private socket: SocketLike | null = null;
  private endpoint: Endpoint | null = null;
  private retries = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private handlers = new Map<
    string,
    Set<(payload: never, message: CoreMessage) => void>
  >();
  private anyHandlers = new Set<(message: CoreMessage) => void>();
  private statusHandlers = new Set<(status: Status) => void>();
  private hiddenForCloak = false;
  private requests = 0;

  constructor(
    private readonly role: Role,
    private readonly host: Host,
    private readonly makeSocket: (url: string) => SocketLike = (url) =>
      new WebSocket(url) as unknown as SocketLike,
  ) {}

  async start(): Promise<void> {
    this.host.onEndpoint((endpoint) => {
      this.endpoint = endpoint;
      this.retries = 0;
      if (endpoint === null) {
        this.drop();
        this.setStatus("offline");
      } else {
        this.connect();
      }
    });
    const endpoint = await this.host.endpoint();
    if (endpoint !== null && this.endpoint === null) {
      this.endpoint = endpoint;
      this.connect();
    }
  }

  on<K extends CoreType>(type: K, handler: Handler<K>): () => void {
    let set = this.handlers.get(type);
    if (set === undefined) {
      set = new Set();
      this.handlers.set(type, set);
    }
    const stored = handler as unknown as (payload: never, message: CoreMessage) => void;
    set.add(stored);
    return () => set.delete(stored);
  }

  onAny(handler: (message: CoreMessage) => void): () => void {
    this.anyHandlers.add(handler);
    return () => this.anyHandlers.delete(handler);
  }

  onStatus(handler: (status: Status) => void): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  /** Send a command; false if not connected (nothing is queued). */
  send<K extends UiType>(type: K, payload: UiPayloads[K], id?: string): boolean {
    if (
      this.socket === null ||
      this.socket.readyState !== OPEN ||
      this.status !== "online"
    ) {
      return false;
    }
    this.socket.send(encode(type, payload, id));
    return true;
  }

  /**
   * Ask the core something (rpc.py) and wait for its answer. Rejects with
   * the core's French message on a refusal, or if no answer comes in time.
   */
  request<T = Record<string, unknown>>(
    method: string,
    params: Record<string, unknown> = {},
    timeoutMs = 10_000,
  ): Promise<T> {
    const id = `q${++this.requests}`;
    if (!this.send("request", { method, params }, id)) {
      return Promise.reject(new Error("Le cœur n'est pas connecté."));
    }
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        stop();
        reject(new Error("Le cœur n'a pas répondu à temps."));
      }, timeoutMs);
      const stop = this.on("reply", (payload, message) => {
        if (message.id !== id) return;
        clearTimeout(timer);
        stop();
        if (payload.ok) resolve((payload.data ?? {}) as T);
        else reject(new Error(payload.message ?? payload.error ?? "Refusé par le cœur."));
      });
    });
  }

  // -- connection ---------------------------------------------------------

  private connect(): void {
    this.drop();
    if (this.endpoint === null) return;
    const { port, token } = this.endpoint;
    this.setStatus("connecting");
    const socket = this.makeSocket(`ws://127.0.0.1:${port}`);
    this.socket = socket;
    socket.onopen = () => {
      if (this.socket !== socket) return;
      socket.send(
        encode("hello", { token, protocol: PROTOCOL_VERSION, role: this.role }),
      );
    };
    socket.onmessage = (event) => {
      if (this.socket !== socket || typeof event.data !== "string") return;
      this.receive(event.data);
    };
    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.setStatus("offline");
      this.scheduleRetry();
    };
    socket.onerror = () => {
      /* onclose follows */
    };
  }

  private drop(): void {
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    const socket = this.socket;
    this.socket = null;
    socket?.close();
  }

  private scheduleRetry(): void {
    if (this.endpoint === null) return;
    const delay = RETRY_MS[Math.min(this.retries, RETRY_MS.length - 1)]!;
    this.retries += 1;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, delay);
  }

  private setStatus(status: Status): void {
    if (status === this.status) return;
    this.status = status;
    for (const handler of this.statusHandlers) handler(status);
  }

  private receive(text: string): void {
    let message: CoreMessage;
    try {
      message = decode(text, "core");
    } catch (error) {
      console.warn("ignored a malformed message from the core", error);
      return;
    }
    if (message.type === "hello.ok") {
      this.retries = 0;
      this.setStatus("online");
    } else if (message.type === "cloak.hide") {
      void this.cloak(message.payload.cloak_id);
    } else if (message.type === "cloak.show") {
      if (this.hiddenForCloak) {
        this.hiddenForCloak = false;
        void this.host.showWindow();
      }
    }
    for (const handler of this.handlers.get(message.type) ?? []) {
      handler(message.payload as never, message);
    }
    for (const handler of this.anyHandlers) handler(message);
  }

  private async cloak(cloakId: string): Promise<void> {
    // Only after the window is really hidden: the core grabs right after.
    this.hiddenForCloak = await this.host.hideWindow();
    this.send("cloak.ack", { cloak_id: cloakId });
  }
}
