/**
 * One overlay window (one per screen): the guide cursor, and the veil for
 * drawing a zone when the core asks for one (capture.select).
 */

import { useEffect, useState } from "react";

import type { CoreClient } from "../core/client";
import { GuideCursor } from "../guide/GuideCursor";
import { RegionSelect } from "../guide/RegionSelect";
import type { WindowEnv } from "./env";

export function OverlayView({
  client,
  env,
  screenId,
}: {
  client: CoreClient;
  env: WindowEnv;
  screenId: string;
}) {
  const [selecting, setSelecting] = useState<"ask" | "text" | null>(null);

  useEffect(() => {
    const off = [
      client.on("capture.select", (p) => setSelecting(p.mode)),
      client.on("capture.select.end", () => setSelecting(null)),
      // A core that went away takes its selection with it.
      client.onStatus((status) => {
        if (status !== "online") setSelecting(null);
      }),
    ];
    return () => off.forEach((stop) => stop());
  }, [client]);

  // Click-through, except while drawing: the veil needs the mouse.
  useEffect(() => {
    env.setInteractive(selecting !== null);
    if (selecting !== null) void env.syncOverlays().then(() => env.show());
  }, [selecting, env]);

  return (
    <>
      <GuideCursor
        client={client}
        env={env}
        screenId={screenId}
        held={selecting !== null}
      />
      {selecting !== null && (
        <RegionSelect client={client} env={env} screenId={screenId} mode={selecting} />
      )}
    </>
  );
}
