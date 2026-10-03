import { describe, expect, it } from "vitest";

import { check, type Scenario } from "./scenario";

const files = import.meta.glob<Scenario>("./scenarios/*.json", {
  eager: true,
  import: "default",
});

describe("every scenario follows the protocol", () => {
  it("there are scenarios", () => {
    expect(Object.keys(files).length).toBeGreaterThanOrEqual(5);
  });

  it.each(Object.entries(files))("%s", (_name, scenario) => {
    expect(check(scenario)).toEqual([]);
  });
});

describe("check", () => {
  const screens = [{ id: "A", width: 100, height: 100 }];

  it("catches a payload the core would never send", () => {
    const bad: Scenario = {
      name: "x",
      description: "",
      screens,
      steps: [{ at: 0, type: "mood", payload: { mood: "grumpy" } }],
    };
    expect(check(bad)[0]).toMatch(/mood/);
  });

  it("catches time going backwards", () => {
    const bad: Scenario = {
      name: "x",
      description: "",
      screens,
      steps: [
        { at: 100, type: "guide.clear", payload: {} },
        { at: 50, type: "guide.clear", payload: {} },
      ],
    };
    expect(check(bad)).toEqual(["step 1 (guide.clear): 'at' goes backwards"]);
  });

  it("catches a point on a screen the scenario does not have", () => {
    const bad: Scenario = {
      name: "x",
      description: "",
      screens,
      steps: [
        {
          at: 0,
          type: "guide.point",
          payload: { screen_id: "B", x: 1, y: 1, label: "" },
        },
      ],
    };
    expect(check(bad)).toEqual(["step 0 (guide.point): unknown screen B"]);
  });

  it("accepts the two pseudo-events for the core itself", () => {
    const ok: Scenario = {
      name: "x",
      description: "",
      screens,
      steps: [
        { at: 0, type: "@core.down" },
        { at: 1, type: "@core.up" },
      ],
    };
    expect(check(ok)).toEqual([]);
  });
});
