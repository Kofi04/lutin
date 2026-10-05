import { createRoot } from "react-dom/client";

import { installTokens } from "../design/tokens";
import { AvatarView } from "./AvatarView";
import { createClient } from "./connect";
import { tauriEnv } from "./tauriEnv";

installTokens();

createRoot(document.getElementById("root")!).render(
  <AvatarView client={createClient("avatar")} env={tauriEnv} />,
);
