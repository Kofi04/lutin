import { createRoot } from "react-dom/client";

import { AvatarView } from "./AvatarView";
import { createClient } from "./connect";
import { tauriEnv } from "./tauriEnv";

createRoot(document.getElementById("root")!).render(
  <AvatarView client={createClient("avatar")} env={tauriEnv} />,
);
