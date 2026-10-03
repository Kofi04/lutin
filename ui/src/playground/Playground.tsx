/**
 * The playground: the real window views, fed by a fake core replaying a
 * scenario. `npm run playground` opens it in the browser; no Python, no Tauri.
 */

import {
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import type { ActionName } from "../protocol";
import { AvatarView } from "../windows/AvatarView";
import { OverlayView } from "../windows/OverlayView";
import { PanelView } from "../windows/PanelView";
import { Frame } from "./frame";
import { Hub, type SentCommand } from "./hub";
import { play, type Scenario } from "./scenario";

const SCENARIOS = Object.values(
  import.meta.glob<Scenario>("./scenarios/*.json", { eager: true, import: "default" }),
);
/** The two screens drawn at this fraction of their size. */
const SCREEN_SCALE = 0.32;

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
  const frames = useMemo(() => {
    const panel = new Frame(hub, "panel", false);
    const avatar = new Frame(hub, "avatar", true, {
      togglePanel: () => panel.setVisible(!panel.visible),
      onTrayAction: (listener) => {
        trayRef.current = listener;
        return () => (trayRef.current = null);
      },
    });
    const overlays = scenario.screens.map((screen) => ({
      screen,
      frame: new Frame(hub, "overlay", false),
    }));
    return { avatar, panel, overlays };
  }, [hub, scenario, trayRef]);

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
          <div style={{ width: 72, height: 72, background: "#2b2d3a", borderRadius: 8 }}>
            <AvatarView client={frames.avatar.client} env={frames.avatar.env} />
          </div>
        </WindowBox>
        <WindowBox frame={frames.panel} title="Panneau (520 × 420)">
          <div style={{ width: 520, height: 420 }}>
            <PanelView client={frames.panel.client} env={frames.panel.env} />
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
              style={{
                width: screen.width * SCREEN_SCALE,
                height: screen.height * SCREEN_SCALE,
                overflow: "hidden",
                background: "linear-gradient(#3a4256, #2a2f3d)",
                borderRadius: 6,
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
                <OverlayView client={frame.client} env={frame.env} screenId={screen.id} />
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
            fontFamily: "Cascadia Code, monospace",
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
      <main>
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
