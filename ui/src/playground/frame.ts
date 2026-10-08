/**
 * One simulated window: its visibility, and the env and host it hands to the
 * view and to its CoreClient. Both act on the same state, as in Tauri, where
 * the view and the cloak hide the same window.
 */

import { CoreClient } from "../core/client";
import type { ActionName, Role } from "../protocol";
import type { WindowEnv } from "../windows/env";
import type { Desk } from "./desk";
import type { Hub } from "./hub";

export class Frame {
  visible: boolean;
  private listeners = new Set<() => void>();
  readonly client: CoreClient;
  readonly env: WindowEnv;

  constructor(
    hub: Hub,
    role: Role,
    visible: boolean,
    hooks: {
      togglePanel?: () => void;
      openApp?: (view: string) => void;
      onTrayAction?: (listener: (name: ActionName) => void) => () => void;
      onPointer?: WindowEnv["onPointer"];
      onPanelToggle?: WindowEnv["onPanelToggle"];
      onSize?: (width: number, height: number) => void;
      desk?: Desk;
      log?: (text: string) => void;
    } = {},
  ) {
    this.visible = visible;
    this.env = {
      show: () => this.setVisible(true),
      hide: () => this.setVisible(false),
      startDragging: () => hooks.log?.(`${role} : glisser (sans effet ici)`),
      togglePanel: () => hooks.togglePanel?.(),
      openApp: (view) => hooks.openApp?.(view),
      applyAppearance: (scale, clickThrough) =>
        hooks.log?.(`${role} : taille ${scale}, clics traversants ${clickThrough}`),
      setCaptureExclusion: () => {},
      setInteractive: () => {},
      releaseFocus: async () => this.setVisible(false),
      onFileDrop: () => () => {},
      syncOverlays: async () => {},
      onPointer: hooks.onPointer ?? (() => () => {}),
      placePanel: async (width, height) => hooks.onSize?.(width, height),
      showPanel: () => this.setVisible(true),
      onPanelToggle: hooks.onPanelToggle ?? (() => () => {}),
      onTrayAction: (listener) => hooks.onTrayAction?.(listener) ?? (() => {}),
      monitors: async () => [],
      onCursor: () => () => {},
      cursorNow: async () => null,
      avatarAnchor: async () => null,
      broadcast: () => {},
      onBroadcast: () => () => {},
      ...hooks.desk?.env(),
    };
    const host = hub.host(
      (v) => this.setVisible(v),
      () => this.visible,
    );
    this.client = new CoreClient(role, host, hub.makeSocket);
    void this.client.start();
  }

  setVisible(visible: boolean): void {
    if (visible === this.visible) return;
    this.visible = visible;
    for (const listener of this.listeners) listener();
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
}
