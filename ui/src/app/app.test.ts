import { describe, expect, it } from "vitest";

import { prettySpec, specFromKey } from "./hotkey";
import { formatRoute, parseRoute, viewFor } from "./routes";

const press = (
  code: string,
  mods: Partial<Record<"ctrl" | "alt" | "shift" | "meta", boolean>> = {},
) => ({
  code,
  ctrlKey: !!mods.ctrl,
  altKey: !!mods.alt,
  shiftKey: !!mods.shift,
  metaKey: !!mods.meta,
});

describe("routes", () => {
  it("map the core's window names to views", () => {
    expect(viewFor("quick_note")).toBe("notes/new");
    expect(viewFor("reminder")).toBe("reminders");
    expect(viewFor("hooks.install")).toBe("hooks/install");
    expect(viewFor("hooks.uninstall")).toBe("hooks/uninstall");
    expect(viewFor("settings")).toBe("settings");
    expect(viewFor("palette")).toBeNull();
  });

  it("parse a hash, falling back to settings", () => {
    expect(parseRoute("#hooks/install")).toEqual({ view: "hooks", param: "install" });
    expect(parseRoute("history")).toEqual({ view: "history", param: "" });
    expect(parseRoute("#nowhere")).toEqual({ view: "settings", param: "" });
    expect(parseRoute("#notes/<b>")).toEqual({ view: "settings", param: "" });
  });

  it("round-trip", () => {
    for (const text of ["notes/new", "agent", "hooks/uninstall"]) {
      expect(formatRoute(parseRoute(text))).toBe(text);
    }
  });
});

describe("hotkeys", () => {
  it("need Ctrl, Alt or Win", () => {
    expect(specFromKey(press("KeyN", { ctrl: true, alt: true }))).toBe("ctrl+alt+N");
    expect(specFromKey(press("KeyN", { meta: true }))).toBe("win+N");
    expect(specFromKey(press("KeyN", { shift: true }))).toBeNull();
    expect(specFromKey(press("KeyN"))).toBeNull();
  });

  it("wait for a real key, not a modifier alone", () => {
    expect(specFromKey(press("ControlLeft", { ctrl: true }))).toBeNull();
    expect(specFromKey(press("AltRight", { alt: true }))).toBeNull();
  });

  it("name keys the way the config does", () => {
    expect(specFromKey(press("Digit5", { ctrl: true }))).toBe("ctrl+5");
    expect(specFromKey(press("F12", { alt: true, shift: true }))).toBe("alt+shift+f12");
    expect(specFromKey(press("Space", { ctrl: true }))).toBe("ctrl+space");
    expect(specFromKey(press("NumpadEnter", { ctrl: true }))).toBe("ctrl+enter");
    expect(specFromKey(press("Semicolon", { ctrl: true }))).toBeNull();
  });

  it("are written the way people write them", () => {
    expect(prettySpec("ctrl+alt+N")).toBe("Ctrl + Alt + N");
    expect(prettySpec("alt+shift+f12")).toBe("Alt + Maj + F12");
    expect(prettySpec("ctrl+space")).toBe("Ctrl + Space");
  });
});
