import { createRoot } from "react-dom/client";

import { installTokens } from "../design/tokens";
import { GuideCursor } from "../guide/GuideCursor";
import { createClient } from "./connect";
import { tauriEnv } from "./tauriEnv";

installTokens();

// Which screen this window covers: set by the Rust side in the URL.
const screenId = new URLSearchParams(location.search).get("screen") ?? "";

createRoot(document.getElementById("root")!).render(
  <GuideCursor client={createClient("overlay")} env={tauriEnv} screenId={screenId} />,
);
