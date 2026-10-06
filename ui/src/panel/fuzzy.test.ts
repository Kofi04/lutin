import { describe, expect, it } from "vitest";

import fixtures from "../../../tests/fuzzy_fixtures.json";
import { fold, rank, score } from "./fuzzy";

describe("the same answers as fuzzy.py", () => {
  it.each(fixtures.score)(
    "score($query, $text)",
    ({ query, text, score: expected, positions }) => {
      const hit = score(query, text);
      if (expected === null) {
        expect(hit).toBeNull();
      } else {
        expect(hit).not.toBeNull();
        expect(hit!.score).toBeCloseTo(expected, 6);
        expect(hit!.positions).toEqual(positions);
      }
    },
  );

  it.each(fixtures.rank)("rank($query)", ({ query, items, ranked }) => {
    expect(rank(query, items, (s) => s)).toEqual(ranked);
  });
});

it("folds accents and case", () => {
  expect(fold("Réunion ÉCRAN ça")).toBe("reunion ecran ca");
});
