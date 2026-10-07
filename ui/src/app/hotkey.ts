/**
 * A key press as a hotkey spec ("ctrl+alt+N"), the rules of hotkey_spec.py.
 *
 * A usable global shortcut needs Ctrl, Alt or Win: Shift alone would swallow
 * every capital letter typed anywhere. Read from `event.code`, the physical
 * key, so AZERTY's A is "A" and Alt does not turn N into a dead key.
 */

export interface KeyPress {
  code: string;
  ctrlKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
  metaKey: boolean;
}

const NAMED: Record<string, string> = {
  Space: "space",
  Tab: "tab",
  Escape: "escape",
  Enter: "enter",
  NumpadEnter: "enter",
  Insert: "insert",
  Delete: "delete",
  Home: "home",
  End: "end",
};

function keyName(code: string): string | null {
  const named = NAMED[code];
  if (named !== undefined) return named;
  const match = /^(?:Key([A-Z])|Digit([0-9])|F([1-9]|1[0-9]|2[0-4]))$/.exec(code);
  if (!match) return null;
  const [, letter, digit, fn] = match;
  return letter ?? digit ?? `f${fn}`;
}

/** The spec, or null while it is not a usable shortcut (yet). */
export function specFromKey(press: KeyPress): string | null {
  const name = keyName(press.code);
  if (name === null) return null;
  const parts: string[] = [];
  if (press.ctrlKey) parts.push("ctrl");
  if (press.altKey) parts.push("alt");
  if (press.shiftKey) parts.push("shift");
  if (press.metaKey) parts.push("win");
  if (!parts.some((part) => part === "ctrl" || part === "alt" || part === "win")) {
    return null;
  }
  return [...parts, name].join("+");
}

/** ctrl+alt+N -> Ctrl + Alt + N, as onboarding.pretty does. */
export function prettySpec(spec: string): string {
  const names: Record<string, string> = {
    ctrl: "Ctrl",
    alt: "Alt",
    shift: "Maj",
    win: "Win",
  };
  return spec
    .split("+")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => names[part.toLowerCase()] ?? part[0]!.toUpperCase() + part.slice(1))
    .join(" + ");
}
