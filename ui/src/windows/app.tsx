import { createRoot } from "react-dom/client";

import "../panel/panel.css";
import "../app/app.css";
import { AppWindow } from "../app/AppWindow";
import { installTokens } from "../design/tokens";
import { appEnv } from "./appEnv";
import { createClient } from "./connect";

installTokens();

createRoot(document.getElementById("root")!).render(
  <AppWindow client={createClient("app")} env={appEnv} initial={location.hash} />,
);
