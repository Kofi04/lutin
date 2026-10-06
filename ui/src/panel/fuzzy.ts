/**
 * The palette's fuzzy matcher (src/wizard/fuzzy.py), for the bar's "/"
 * filter: DESIGN.md section 5 asks for the same engine, so the same ranking.
 * Checked against answers produced by fuzzy.py (tests/fuzzy_fixtures.json).
 */

const BOUNDARY_BONUS = 12;
const CONSECUTIVE_BONUS = 16;
const FIRST_CHAR_BONUS = 10;
const GAP_PENALTY = 0.6;
const LENGTH_PENALTY = 0.12;
const PREFIX_BONUS = 25;
const SEPARATORS = new Set(" \t-_/\\.:,()[]{}'\"");

/** Lowercase and strip accents, so "reunion" matches "Réunion". */
export function fold(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{Mn}/gu, "");
}

export interface Match {
  score: number;
  positions: number[];
}

export function score(query: string, text: string): Match | null {
  if (!query) return { score: 0, positions: [] };
  if (!text) return null;
  const needle = fold(query);
  const haystack = fold(text);
  if (needle.length > haystack.length) return null;

  let total = 0;
  const positions: number[] = [];
  let cursor = 0;
  let previous = -2;
  for (const char of needle) {
    if (/\s/.test(char)) continue; // a space means "and then"
    const found = haystack.indexOf(char, cursor);
    if (found < 0) return null;
    if (found === 0) total += FIRST_CHAR_BONUS;
    else if (SEPARATORS.has(haystack[found - 1]!)) total += BOUNDARY_BONUS;
    if (found === previous + 1) total += CONSECUTIVE_BONUS;
    total -= (found - cursor) * GAP_PENALTY;
    positions.push(found);
    previous = found;
    cursor = found + 1;
  }
  total -= haystack.length * LENGTH_PENALTY;
  if (haystack.startsWith(needle)) total += PREFIX_BONUS;
  return { score: total, positions };
}

/** Filter and order by match; an empty query keeps the caller's order. */
export function rank<T>(
  query: string,
  items: readonly T[],
  key: (item: T) => string,
): T[] {
  if (!query.trim()) return [...items];
  return items
    .map((item, index) => ({ item, index, hit: score(query, key(item)) }))
    .filter((row) => row.hit !== null)
    .sort((a, b) => b.hit!.score - a.hit!.score || a.index - b.index)
    .map((row) => row.item);
}
