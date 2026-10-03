import { useSyncExternalStore } from "react";

import { CoreClient, type Status } from "../core/client";
import { tauriHost } from "../core/tauri";
import type { Role } from "../protocol";

/** This window's connection inside Tauri: one per page, started once. */
export function createClient(role: Role): CoreClient {
  const client = new CoreClient(role, tauriHost);
  void client.start();
  return client;
}

/**
 * The connection status, kept current.
 *
 * Not useState + useEffect: the status read at render time could change
 * before the effect subscribed, and that change was lost. The playground
 * showed it every time (a fake core answers at once): windows stuck
 * "offline" while events kept arriving.
 */
export function useStatus(client: CoreClient): Status {
  return useSyncExternalStore(
    (onChange) => client.onStatus(onChange),
    () => client.status,
  );
}
