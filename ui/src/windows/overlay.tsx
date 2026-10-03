import { createRoot } from "react-dom/client";

import { createClient } from "./connect";
import { OverlayView } from "./OverlayView";
import { tauriEnv } from "./tauriEnv";

// Which screen this window covers: set by the Rust side in the URL.
const screenId = new URLSearchParams(location.search).get("screen") ?? "";

createRoot(document.getElementById("root")!).render(
  <OverlayView client={createClient("overlay")} env={tauriEnv} screenId={screenId} />,
);
