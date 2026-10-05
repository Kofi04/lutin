import { describe, expect, it } from "vitest";

import { type Clock, AvatarRenderer } from "./renderer";

/** A clock the test moves by hand. */
class FakeClock implements Clock {
  time = 0;
  private timers: { at: number; callback: () => void; id: number }[] = [];
  private nextId = 1;

  now() {
    return this.time;
  }
  setTimeout(callback: () => void, ms: number) {
    const id = this.nextId++;
    this.timers.push({ at: this.time + ms, callback, id });
    return id;
  }
  clearTimeout(handle: unknown) {
    this.timers = this.timers.filter((t) => t.id !== handle);
  }
  random() {
    return 0.5;
  }
  /** Run every timer due within `ms`, in order. */
  advance(ms: number) {
    const end = this.time + ms;
    for (;;) {
      this.timers.sort((a, b) => a.at - b.at);
      const next = this.timers[0];
      if (!next || next.at > end) break;
      this.timers.shift();
      this.time = next.at;
      next.callback();
    }
    this.time = end;
  }
  /** Milliseconds until the next timer fires. */
  get nextIn() {
    return Math.min(...this.timers.map((t) => t.at)) - this.time;
  }
  get pending() {
    return this.timers.length;
  }
}

function setup(reduced = false) {
  const clock = new FakeClock();
  const renderer = new AvatarRenderer(
    () => {},
    () => reduced,
    clock,
  );
  renderer.setState("calm");
  return { clock, renderer };
}

describe("the avatar's frame budget", () => {
  it("a calm wizard paints only a fraction of its ticks", () => {
    const { clock, renderer } = setup();
    renderer.start();
    clock.advance(60_000);
    // Ticking every 100 ms is 600 ticks a minute; most look the same.
    expect(renderer.painted).toBeGreaterThan(30);
    expect(renderer.painted).toBeLessThan(300);
  });

  it("with reduced motion, almost nothing moves, so almost nothing is painted", () => {
    const { clock, renderer } = setup(true);
    renderer.start();
    clock.advance(60_000);
    // Only the blinks remain: one every 4.5 s here, a few frames each.
    expect(renderer.painted).toBeLessThan(60);
  });

  it("paints nothing at all while stopped (window hidden)", () => {
    const { clock, renderer } = setup();
    renderer.start();
    clock.advance(1000);
    renderer.stop();
    const before = renderer.painted;
    clock.advance(60_000);
    expect(renderer.painted).toBe(before);
    expect(clock.pending).toBe(0);
  });

  it("repaints at once when shown again, even if the pose did not change", () => {
    const { clock, renderer } = setup(true);
    renderer.start();
    clock.advance(100);
    renderer.stop();
    const before = renderer.painted;
    renderer.start();
    expect(renderer.painted).toBe(before + 1);
  });

  it("a state change is painted immediately, not at the next tick", () => {
    const { clock, renderer } = setup();
    renderer.start();
    clock.advance(1000);
    const before = renderer.painted;
    renderer.setState("working");
    expect(renderer.painted).toBe(before + 1);
  });

  it("keeps a single timer, however often it is woken", () => {
    const { clock, renderer } = setup();
    renderer.start();
    for (let i = 0; i < 10; i++) renderer.setHover(i % 2 === 0);
    expect(clock.pending).toBe(1);
  });
});

describe("ticks are spent where they show", () => {
  it("never misses a blink, though a calm tick is longer than a blink", () => {
    const clock = new FakeClock();
    const opens: number[] = [];
    const renderer = new AvatarRenderer(
      (p) => opens.push(p.eyeOpen),
      () => true, // still: only blinks change the picture
      clock,
    );
    renderer.setState("calm");
    renderer.start();
    clock.advance(20_000);
    // random() is 0.5: the next blink is drawn 4.5 s after the second that
    // follows the last one, so at 4.5, 10 and 15.5 s. Every one is seen.
    expect(opens.filter((open) => open < 0.2).length).toBe(3);
  });

  it("a pointer move costs one frame, and only if the eyes change", () => {
    const { clock, renderer } = setup(true);
    renderer.start();
    renderer.setPointer({ dx: -400, dy: 0 });
    clock.advance(1000);
    let before = renderer.painted;
    renderer.setPointer({ dx: 400, dy: 0 });
    expect(renderer.painted - before).toBe(1);
    before = renderer.painted;
    renderer.setPointer({ dx: 420, dy: 3 }); // same direction: same pupils
    expect(renderer.painted - before).toBe(0);
  });
});

describe("settled: nothing moves without a reason (DESIGN.md section 1)", () => {
  it("a settled, calm wizard paints nothing at all for a minute", () => {
    const { clock, renderer } = setup();
    renderer.start();
    renderer.setSettled(true);
    const before = renderer.painted;
    clock.advance(60_000);
    expect(renderer.painted).toBe(before);
    // And barely ticks: a safety net every two seconds.
    expect(clock.nextIn).toBeGreaterThanOrEqual(1000);
  });

  it("his eyes still follow the pointer while settled", () => {
    const { clock, renderer } = setup();
    renderer.start();
    renderer.setSettled(true);
    renderer.setPointer({ dx: -400, dy: 0 });
    clock.advance(1000);
    const before = renderer.painted;
    renderer.setPointer({ dx: 400, dy: 0 });
    expect(renderer.painted).toBe(before + 1);
  });

  it("wakes at once when something happens", () => {
    const { clock, renderer } = setup();
    renderer.start();
    renderer.setSettled(true);
    clock.advance(10_000);
    const before = renderer.painted;
    renderer.setSettled(false);
    clock.advance(4000);
    expect(renderer.painted).toBeGreaterThan(before + 3); // breathing again
  });

  it("states that mean work keep animating, settled or not", () => {
    const { clock, renderer } = setup();
    renderer.start();
    renderer.setState("working");
    renderer.setSettled(true);
    const before = renderer.painted;
    clock.advance(5000);
    expect(renderer.painted - before).toBeGreaterThan(20); // the blue pulse
  });
});

describe("the gaze when settled", () => {
  it("a busy mouse moves settled eyes at most once a second", () => {
    const { clock, renderer } = setup();
    renderer.start();
    renderer.setSettled(true);
    const before = renderer.painted;
    // Eight moves a second for five seconds, sweeping around him.
    for (let i = 0; i < 40; i++) {
      const angle = (i / 40) * Math.PI * 2;
      renderer.setPointer({ dx: 400 * Math.cos(angle), dy: 400 * Math.sin(angle) });
      clock.advance(125);
    }
    expect(renderer.painted - before).toBeLessThanOrEqual(6);
    expect(renderer.painted - before).toBeGreaterThanOrEqual(4);
  });

  it("awake, the eyes follow every move", () => {
    const { clock, renderer } = setup(true);
    renderer.start();
    const before = renderer.painted;
    for (let i = 0; i < 16; i++) {
      const angle = (i / 16) * Math.PI * 2;
      renderer.setPointer({ dx: 400 * Math.cos(angle), dy: 400 * Math.sin(angle) });
      clock.advance(125);
    }
    expect(renderer.painted - before).toBeGreaterThanOrEqual(15);
  });

  it("the last position is never lost, even when the moves stop", () => {
    const clock = new FakeClock();
    const pupils: number[] = [];
    const watched = new AvatarRenderer(
      (p) => pupils.push(p.pupilX),
      () => true,
      clock,
    );
    watched.setState("calm");
    watched.start();
    watched.setSettled(true);
    watched.setPointer({ dx: -400, dy: 0 });
    clock.advance(100);
    watched.setPointer({ dx: 400, dy: 0 }); // within the second: deferred
    clock.advance(2000);
    expect(pupils.at(-1)).toBeGreaterThan(0); // ends looking right
  });
});
