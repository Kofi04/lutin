import { createRoot } from "react-dom/client";

import { installTokens } from "../design/tokens";
import { Playground } from "./Playground";

installTokens();

createRoot(document.getElementById("root")!).render(<Playground />);
