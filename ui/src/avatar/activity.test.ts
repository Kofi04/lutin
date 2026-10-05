import { describe, expect, it } from "vitest";

import type { CoreMessage } from "../protocol";
import { isActivity } from "./activity";

const message = (type: string, payload: object = {}) =>
  ({ type, payload }) as CoreMessage;

describe("what wakes the avatar", () => {
  it("Claude's moods do", () => {
    for (const mood of ["working", "waiting", "done", "error"]) {
      expect(isActivity(message("mood", { mood }))).toBe(true);
    }
  });

  it("the machine's moods do not", () => {
    for (const mood of ["calm", "busy", "stressed", "tired"]) {
      expect(isActivity(message("mood", { mood }))).toBe(false);
    }
  });

  it("nor its load, nor the plumbing", () => {
    for (const type of ["system", "hello.ok", "reply", "error"]) {
      expect(isActivity(message(type))).toBe(false);
    }
  });

  it("everything about you and Claude does", () => {
    for (const type of [
      "stream.chunk",
      "approval.request",
      "toast",
      "guide.point",
      "sessions.update",
    ]) {
      expect(isActivity(message(type))).toBe(true);
    }
  });
});
