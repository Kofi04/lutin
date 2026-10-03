import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CoreClient } from "../core/client";
import { Hub } from "./hub";
import { play, type Scenario } from "./scenario";

let hub: Hub;
let visible: boolean;

function window(role: "avatar" | "panel" = "avatar"): CoreClient {
  const host = hub.host(
    (v) => (visible = v),
    () => visible,
  );
  const client = new CoreClient(role, host, hub.makeSocket);
  void client.start();
  return client;
}

async function settle(): Promise<void> {
  await vi.advanceTimersByTimeAsync(0);
}

beforeEach(() => {
  vi.useFakeTimers();
  hub = new Hub();
  visible = true;
});

afterEach(() => vi.useRealTimers());

describe("the fake core", () => {
  it("lets a real client connect, as the core would", async () => {
    const client = window();
    await settle();
    expect(client.status).toBe("online");
  });

  it("records the commands the windows send, with their role", async () => {
    const client = window("panel");
    await settle();
    client.send("ask", { text: "Bonjour" });
    expect(hub.sent).toEqual([
      { role: "panel", message: { type: "ask", payload: { text: "Bonjour" } } },
    ]);
  });

  it("tells a late window the current state, like the core", async () => {
    hub.broadcast("mood", { mood: "working" });
    const moods: string[] = [];
    const client = window();
    client.on("mood", (p) => moods.push(p.mood));
    await settle();
    expect(moods).toEqual(["working"]);
  });

  it("goes down and comes back, and the windows follow", async () => {
    const client = window();
    await settle();
    hub.down();
    expect(client.status).toBe("offline");
    hub.restart();
    await settle();
    expect(client.status).toBe("online");
  });

  it("acks a cloak only once the window is hidden", async () => {
    window();
    await settle();
    hub.broadcast("cloak.hide", { cloak_id: "c1" });
    await settle();
    expect(visible).toBe(false);
    expect(hub.sent.at(-1)?.message).toEqual({
      type: "cloak.ack",
      payload: { cloak_id: "c1" },
    });
    hub.broadcast("cloak.show", { cloak_id: "c1" });
    await settle();
    expect(visible).toBe(true);
  });
});

describe("play", () => {
  const scenario: Scenario = {
    name: "t",
    description: "",
    screens: [{ id: "A", width: 10, height: 10 }],
    steps: [
      { at: 0, type: "mood", payload: { mood: "working" } },
      { at: 1000, type: "@core.down" },
      { at: 2000, type: "@core.up" },
    ],
  };

  it("plays the steps on time, at the chosen speed", async () => {
    const client = window();
    await settle();
    const played: number[] = [];
    play(scenario, hub, (i) => played.push(i), 2);

    await vi.advanceTimersByTimeAsync(0);
    expect(played).toEqual([0]);
    await vi.advanceTimersByTimeAsync(500);
    expect(played).toEqual([0, 1]);
    expect(client.status).toBe("offline");
    await vi.advanceTimersByTimeAsync(500);
    expect(client.status).toBe("online");
  });

  it("can be stopped", async () => {
    window();
    await settle();
    const played: number[] = [];
    const stop = play(scenario, hub, (i) => played.push(i));
    stop();
    await vi.advanceTimersByTimeAsync(5000);
    expect(played).toEqual([]);
  });
});
