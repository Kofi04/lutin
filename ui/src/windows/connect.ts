import { useEffect, useState } from "react";

import { CoreClient, type Status } from "../core/client";
import { tauriHost } from "../core/tauri";
import type { Role } from "../protocol";

/** This window's connection: one per page, started once. */
export function createClient(role: Role): CoreClient {
  const client = new CoreClient(role, tauriHost);
  void client.start();
  return client;
}

export function useStatus(client: CoreClient): Status {
  const [status, setStatus] = useState<Status>(client.status);
  useEffect(() => client.onStatus(setStatus), [client]);
  return status;
}
