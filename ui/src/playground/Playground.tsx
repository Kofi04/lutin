/**
 * The playground: the real window views, fed by a fake core replaying a
 * scenario. `npm run playground` opens it in the browser; no Python, no Tauri.
 */

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { AvatarCanvas } from "../avatar/AvatarCanvas";
import { VISUAL_STATES } from "../avatar/state";
import type { ActionName } from "../protocol";
import { AvatarView } from "../windows/AvatarView";
import { GuideOverlay } from "../guide/GuideOverlay";
import { Panel } from "../panel/Panel";
import { Desk } from "./desk";
import { Frame } from "./frame";
import { Hub, type SentCommand } from "./hub";
import { play, type Scenario } from "./scenario";

const SCENARIOS = Object.values(
  import.meta.glob<Scenario>("./scenarios/*.json", { eager: true, import: "default" }),
);
/** The two screens drawn at this fraction of their size. */
const SCREEN_SCALE = 0.32;

/**
 * The mouse on the page, standing in for the pointer on the desktop: each
 * move is told to the subscriber, relative to an element's centre, as
 * env.onPointer does with the cursor that Rust watches.
 */
function pointerFrom(element: { current: HTMLElement | null }) {
  return (listener: (pointer: { dx: number; dy: number }) => void) => {
    const onMove = (event: MouseEvent) => {
      const box = element.current?.getBoundingClientRect();
      if (!box) return;
      listener({
        dx: event.clientX - (box.left + box.width / 2),
        dy: event.clientY - (box.top + box.height / 2),
      });
    };
    addEventListener("mousemove", onMove);
    return () => removeEventListener("mousemove", onMove);
  };
}

/** Every state of DESIGN.md section 4, side by side, at two sizes. */
function Gallery() {
  return (
    <section>
      <h2
        style={{ fontSize: "var(--lw-size-title)", fontWeight: 600, margin: "0 0 8px" }}
      >
        États de l'avatar
      </h2>
      {[56, 112].map((size) => (
        <div
          key={size}
          style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}
        >
          {VISUAL_STATES.map((state) => (
            <GalleryItem key={state} state={state} size={size} />
          ))}
        </div>
      ))}
    </section>
  );
}

function GalleryItem({
  state,
  size,
}: {
  state: (typeof VISUAL_STATES)[number];
  size: number;
}) {
  const box = useRef<HTMLDivElement>(null);
  const pointer = useMemo(() => pointerFrom(box), []);
  const [hover, setHover] = useState(false);
  return (
    <figure style={{ margin: 0, textAlign: "center" }}>
      <div
        ref={box}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{
          background: "var(--lw-stage-desk)",
          borderRadius: "var(--lw-radius-button)",
        }}
      >
        <AvatarCanvas
          state={state}
          size={size}
          padding={size / 7}
          hover={hover}
          onPointer={pointer}
        />
      </div>
      <figcaption
        style={{ fontSize: "var(--lw-size-meta)", color: "var(--lw-color-text-2)" }}
      >
        {state}
      </figcaption>
    </figure>
  );
}

function useVisible(frame: Frame): boolean {
  return useSyncExternalStore(frame.subscribe, () => frame.visible);
}

function WindowBox({
  frame,
  title,
  children,
}: {
  frame: Frame;
  title: string;
  children: ReactNode;
}) {
  const visible = useVisible(frame);
  return (
    <figure style={{ margin: 0 }}>
      <figcaption style={{ fontSize: 12, opacity: 0.7, marginBottom: 4 }}>
        {title} {visible ? "" : "— masquée"}
      </figcaption>
      <div style={{ opacity: visible ? 1 : 0.15, transition: "opacity 120ms" }}>
        {children}
      </div>
    </figure>
  );
}

/** One run of one scenario: its own hub and windows, thrown away on change. */
function Run({
  scenario,
  speed,
  onCommand,
  onStep,
  trayRef,
}: {
  scenario: Scenario;
  speed: number;
  onCommand: (command: SentCommand) => void;
  onStep: (index: number) => void;
  trayRef: { current: ((name: ActionName) => void) | null };
}) {
  const hub = useMemo(() => new Hub(), []);
  const avatarBox = useRef<HTMLDivElement>(null);
  const [panelSize, setPanelSize] = useState({ width: 552, height: 140 });
  const desk = useMemo(() => new Desk(scenario.screens, SCREEN_SCALE), [scenario]);
  const frames = useMemo(() => {
    // The avatar's click reaches the panel as Tauri's "panel://toggle" does.
    const toggles = new Set<() => void>();
    const panel = new Frame(hub, "panel", false, {
      desk,
      onPanelToggle: (listener) => {
        toggles.add(listener);
        return () => toggles.delete(listener);
      },
      onSize: (width, height) => setPanelSize({ width, height }),
    });
    const avatar = new Frame(hub, "avatar", true, {
      desk,
      onPointer: pointerFrom(avatarBox),
      togglePanel: () => toggles.forEach((toggle) => toggle()),
      onTrayAction: (listener) => {
        trayRef.current = listener;
        return () => (trayRef.current = null);
      },
    });
    const overlays = scenario.screens.map((screen) => ({
      screen,
      frame: new Frame(hub, "overlay", false, { desk }),
    }));
    return { avatar, panel, overlays };
  }, [hub, scenario, trayRef, desk]);

  // The page's mouse over a pretend screen is the pointer on that screen.
  useEffect(() => {
    const onMove = (event: MouseEvent) => desk.mouse(event.clientX, event.clientY);
    addEventListener("mousemove", onMove);
    return () => removeEventListener("mousemove", onMove);
  }, [desk]);

  useEffect(() => hub.onCommand(onCommand), [hub, onCommand]);
  useEffect(() => {
    const stop = play(scenario, hub, onStep, speed);
    return () => {
      stop();
      hub.down(); // the windows of this run go offline and stop retrying
    };
  }, [hub, scenario, speed, onStep]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>
        <WindowBox frame={frames.avatar} title="Avatar (72 px)">
          <div
            ref={avatarBox}
            style={{
              width: 72,
              height: 72,
              background: "var(--lw-stage-desk)",
              borderRadius: "var(--lw-radius-button)",
            }}
          >
            <AvatarView client={frames.avatar.client} env={frames.avatar.env} />
          </div>
        </WindowBox>
        <WindowBox
          frame={frames.panel}
          title={`Panneau (${panelSize.width} × ${panelSize.height})`}
        >
          {/* The window's own size, as Rust would set it: overflow is cut. */}
          <div
            style={{
              width: panelSize.width,
              height: panelSize.height,
              overflow: "hidden",
              outline: "1px dashed var(--lw-color-border)",
            }}
          >
            <Panel client={frames.panel.client} env={frames.panel.env} />
          </div>
        </WindowBox>
      </div>
      <div
        style={{ display: "flex", gap: 24, alignItems: "flex-start", flexWrap: "wrap" }}
      >
        {frames.overlays.map(({ screen, frame }) => (
          <WindowBox
            key={screen.id}
            frame={frame}
            title={`Écran ${screen.id} (${screen.width} × ${screen.height})`}
          >
            <div
              ref={(element) => {
                if (element) desk.boxes.set(screen.id, element);
              }}
              style={{
                width: screen.width * SCREEN_SCALE,
                height: screen.height * SCREEN_SCALE,
                overflow: "hidden",
                background: "var(--lw-stage-wallpaper)",
                borderRadius: "var(--lw-radius-button)",
              }}
            >
              <div
                style={{
                  position: "relative",
                  width: screen.width,
                  height: screen.height,
                  transform: `scale(${SCREEN_SCALE})`,
                  transformOrigin: "0 0",
                }}
              >
                <GuideOverlay
                  client={frame.client}
                  env={frame.env}
                  screenId={screen.id}
                />
              </div>
            </div>
          </WindowBox>
        ))}
      </div>
    </div>
  );
}

export function Playground() {
  const [index, setIndex] = useState(0);
  const [run, setRun] = useState(0);
  const [speed, setSpeed] = useState(1);
  const [step, setStep] = useState(-1);
  const [commands, setCommands] = useState<SentCommand[]>([]);
  const trayRef = useMemo<{ current: ((name: ActionName) => void) | null }>(
    () => ({ current: null }),
    [],
  );
  const scenario = SCENARIOS[index]!;
  const onCommand = useMemo(
    () => (command: SentCommand) =>
      setCommands((list) => [command, ...list].slice(0, 40)),
    [],
  );

  const restart = (next = index) => {
    setIndex(next);
    setStep(-1);
    setCommands([]);
    setRun((r) => r + 1);
  };

  return (
    <div
      style={{
        display: "flex",
        gap: 24,
        padding: 20,
        minHeight: "100vh",
        boxSizing: "border-box",
      }}
    >
      <aside
        style={{
          width: 280,
          flexShrink: 0,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <h1 style={{ fontSize: 20, margin: 0 }}>Terrain d'essai</h1>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {SCENARIOS.map((s, i) => (
            <button
              key={s.name}
              onClick={() => restart(i)}
              style={{ fontWeight: i === index ? 600 : 400, textAlign: "left" }}
            >
              {s.name}
            </button>
          ))}
        </div>
        <p style={{ margin: 0, opacity: 0.8 }}>{scenario.description}</p>
        <div>
          Étape {step + 1} / {scenario.steps.length}
          {step >= 0 && <code> {scenario.steps[step]!.type}</code>}
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={() => restart()}>Rejouer</button>
          {[1, 2, 4].map((s) => (
            <button
              key={s}
              onClick={() => setSpeed(s)}
              style={{ fontWeight: s === speed ? 600 : 400 }}
            >
              ×{s}
            </button>
          ))}
        </div>
        <div>
          <div style={{ fontSize: 12, opacity: 0.7 }}>Menu de l'icône</div>
          {(["ask", "capture.region", "capture.screen"] as ActionName[]).map((name) => (
            <button key={name} onClick={() => trayRef.current?.(name)}>
              {name}
            </button>
          ))}
        </div>
        <div style={{ fontSize: 12, opacity: 0.7 }}>Commandes envoyées au core</div>
        <ol
          style={{
            margin: 0,
            paddingLeft: 18,
            fontFamily: "var(--lw-font-code)",
            fontSize: 11,
          }}
        >
          {commands.map((c, i) => (
            <li key={commands.length - i}>
              <b>{c.role}</b> {c.message.type} {JSON.stringify(c.message.payload)}
            </li>
          ))}
        </ol>
      </aside>
      <main style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        <Gallery />
        <Run
          key={run}
          scenario={scenario}
          speed={speed}
          onCommand={onCommand}
          onStep={setStep}
          trayRef={trayRef}
        />
      </main>
    </div>
  );
}
