/**
 * The app window's views, and how the core's window names reach them.
 *
 * One window, several views (DESIGN.md section 9): the core asks for
 * "quick_note" or "hooks.install"; the window shows "notes/new" or
 * "hooks/install". The list matches APP_VIEWS in windows.rs.
 */

import type { CorePayloads } from "../protocol";

export const VIEWS = [
  "settings",
  "history",
  "clipboard",
  "notes",
  "reminders",
  "hooks",
  "onboarding",
  "agent",
] as const;

export type ViewName = (typeof VIEWS)[number];

export interface Route {
  view: ViewName;
  /** "new" for a quick note, "install" or "uninstall" for hooks. */
  param: string;
}

export type WindowName = CorePayloads["window.open"]["name"];

/** Where a core window name leads; null for the palette (the panel's). */
export function viewFor(name: WindowName): string | null {
  switch (name) {
    case "palette":
      return null;
    case "quick_note":
      return "notes/new";
    case "reminder":
      return "reminders";
    case "hooks.install":
      return "hooks/install";
    case "hooks.uninstall":
      return "hooks/uninstall";
    default:
      return name;
  }
}

/** "#hooks/install" or "hooks/install" -> a route; anything else -> settings. */
export function parseRoute(text: string): Route {
  const [view = "", param = ""] = text.replace(/^#/, "").split("/", 2);
  if ((VIEWS as readonly string[]).includes(view) && /^[a-z]*$/.test(param)) {
    return { view: view as ViewName, param };
  }
  return { view: "settings", param: "" };
}

export function formatRoute(route: Route): string {
  return route.param ? `${route.view}/${route.param}` : route.view;
}
