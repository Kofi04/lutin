/**
 * Every visual value of DESIGN.md section 3, and nowhere else.
 *
 * Components read these, or the CSS variables generated from them
 * (`--lw-<name>`); a test fails if a hex colour appears in any other file.
 */

/** Floating surfaces are always dark (DESIGN.md section 3). */
export const colors = {
  /** The app window (DESIGN.md section 9): opaque, the floating surface's tone. */
  window: "#141418",
  /** The panel at the top of the screen, like a phone's Dynamic Island: true black. */
  island: "#000000",
  surface: "rgba(16,16,20,0.94)",
  surfaceRaised: "rgba(30,30,36,0.96)",
  border: "rgba(255,255,255,0.08)",
  borderStrong: "rgba(255,255,255,0.14)",
  text: "#F2F2F5",
  text2: "rgba(242,242,245,0.64)",
  text3: "rgba(242,242,245,0.40)",
  accent: "#7C7BFF",
  accentHover: "#918FFF",
  stateWorking: "#5AA9FF",
  stateWaiting: "#FFB547",
  stateSuccess: "#3DDC97",
  stateDanger: "#FF5C5C",
  stateOffline: "#8A8A93",
  staffRest: "#E8B04A",
} as const;

/** The figure itself (DESIGN.md section 4). */
export const figure = {
  hat: "#2E2F7A",
  hatBand: "#E8B04A",
  skin: "#5A3825",
  eyeWhite: "#F7F4EE",
  pupil: "#16141F",
  staff: "#8C6A45",
  /** The orb between pulses, and when it is "off". */
  orbOff: "#4A4A52",
  /** A tired machine: the gold, paled. */
  orbPale: "#F1D9A3",
  stressed: "#FF9A3D",
} as const;

/** The guide cursor (DESIGN.md section 6). */
export const guide = {
  /** White outline: visible on light and dark backgrounds alike. */
  stroke: "#FFFFFF",
  /** The rest of the screen, around a highlight. */
  scrim: "rgba(0,0,0,0.35)",
} as const;

/** The playground's desk and screens: not part of the app. */
export const stage = {
  page: "#1B1D24",
  desk: "#2B2D3A",
  wallpaper: "#323A4D",
} as const;

export const radii = { button: 8, field: 12, panel: 18, island: 24, pill: 999 } as const;

export const space = { 1: 4, 2: 8, 3: 12, 4: 16, 5: 20, 6: 24 } as const;

export const shadows = {
  panel:
    "0 16px 48px rgba(0,0,0,.45), 0 2px 8px rgba(0,0,0,.30), inset 0 1px 0 rgba(255,255,255,.06)",
} as const;

export const fonts = {
  ui: '"Segoe UI Variable", "Inter", system-ui, sans-serif',
  code: '"Cascadia Code", "JetBrains Mono", monospace',
} as const;

export const fontSizes = { meta: 12, body: 13, title: 15, window: 20 } as const;

/** Never 700 or more (DESIGN.md section 3). */
export const fontWeights = { regular: 400, medium: 500, semibold: 600 } as const;

/** DESIGN.md section 4: a 56 px figure in a 72 px window, for the halo. */
export const avatarSize = { figure: 56, window: 72 } as const;

function kebab(name: string): string {
  return name.replace(/([a-z])([A-Z0-9])/g, "$1-$2").toLowerCase();
}

/** Every token as a CSS custom property, `--lw-<group>-<name>`. */
export function cssVariables(): Record<string, string> {
  const vars: Record<string, string> = {};
  const add = (group: string, values: Record<string, string | number>, unit = "") => {
    for (const [name, value] of Object.entries(values)) {
      vars[`--lw-${group}-${kebab(name)}`] =
        typeof value === "number" ? `${value}${unit}` : value;
    }
  };
  add("color", colors);
  add("stage", stage);
  add("guide", guide);
  add("radius", radii, "px");
  add("space", space, "px");
  add("shadow", shadows);
  add("font", fonts);
  add("size", fontSizes, "px");
  add("weight", fontWeights);
  return vars;
}

/** Put the variables on :root, once per page, before the first render. */
export function installTokens(root: HTMLElement = document.documentElement): void {
  for (const [name, value] of Object.entries(cssVariables())) {
    root.style.setProperty(name, value);
  }
}
