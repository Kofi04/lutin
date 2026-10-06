import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import { springAt, springs } from "./motion";
import { colors, cssVariables, figure, guide, stage } from "./tokens";

const SRC = join(import.meta.dirname, "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx|css)$/.test(name) && !/\.test\.ts$/.test(name) ? [path] : [];
  });
}

describe("tokens", () => {
  it("are the values DESIGN.md section 3 gives", () => {
    expect(colors.accent).toBe("#7C7BFF");
    expect(colors.surface).toBe("rgba(16,16,20,0.94)");
    expect(colors.staffRest).toBe("#E8B04A");
    expect(figure.hat).toBe("#2E2F7A");
    expect(figure.skin).toBe("#5A3825");
  });

  it("all become CSS variables", () => {
    const vars = cssVariables();
    expect(vars["--lw-color-accent"]).toBe("#7C7BFF");
    expect(vars["--lw-color-state-working"]).toBe("#5AA9FF");
    expect(vars["--lw-radius-panel"]).toBe("18px");
    expect(vars["--lw-weight-semibold"]).toBe("600");
    expect(Object.keys(vars)).toHaveLength(
      Object.keys(colors).length +
        Object.keys(stage).length +
        Object.keys(guide).length +
        4 +
        6 +
        1 +
        2 +
        4 +
        3,
    );
  });

  it("are the only place a colour is written (DESIGN.md: no colour in components)", () => {
    const offenders = sourceFiles(SRC)
      .filter((path) => !path.endsWith(join("design", "tokens.ts")))
      .flatMap((path) => {
        const text = readFileSync(path, "utf8");
        const found = text.match(/#[0-9a-fA-F]{3,8}\b|rgba?\(/g) ?? [];
        return found.map((hit) => `${relative(SRC, path)}: ${hit}`);
      });
    expect(offenders).toEqual([]);
  });
});

describe("springs", () => {
  it("start at rest and settle on the target", () => {
    for (const spring of Object.values(springs)) {
      expect(springAt(spring, 0)).toBe(0);
      expect(springAt(spring, 3)).toBeCloseTo(1, 3);
    }
  });

  it("bouncy overshoots, snappy and smooth barely do", () => {
    const peak = (spring: (typeof springs)[keyof typeof springs]) => {
      let max = 0;
      for (let t = 0; t < 1.5; t += 0.002) max = Math.max(max, springAt(spring, t));
      return max;
    };
    expect(peak(springs.bouncy)).toBeGreaterThan(1.2);
    expect(peak(springs.snappy)).toBeLessThan(1.05);
    expect(peak(springs.smooth)).toBeLessThan(1.05);
  });

  it("an overdamped spring never overshoots", () => {
    const slow = { stiffness: 100, damping: 40 };
    for (let t = 0; t < 2; t += 0.01) expect(springAt(slow, t)).toBeLessThanOrEqual(1);
  });
});
