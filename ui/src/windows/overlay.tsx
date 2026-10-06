import { createRoot } from "react-dom/client";

import { installTokens } from "../design/tokens";
import { GuideOverlay } from "../guide/GuideOverlay";
import { createClient } from "./connect";
import { tauriEnv } from "./tauriEnv";

installTokens();

// Which screen this window covers: set by the Rust side in the URL.
const screenId = new URLSearchParams(location.search).get("screen") ?? "";

createRoot(document.getElementById("root")!).render(
  <GuideOverlay client={createClient("overlay")} env={tauriEnv} screenId={screenId} />,
);
