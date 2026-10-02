import { describe, expect, it } from "vitest";

import fixtures from "../../tests/protocol_fixtures.json";
import spec from "../../src/wizard/protocol_messages.json";
import { decode, encode, ProtocolError, type Sender, uiTypes } from "./protocol";

describe("the fixtures shared with protocol.py", () => {
  it.each(fixtures.valid)("accepts $text", ({ from, text }) => {
    const message = decode(text, from as "core");
    expect(message.type).toBe(JSON.parse(text).type);
  });

  it.each(fixtures.invalid)("refuses $text with $error", ({ from, text, error }) => {
    try {
      decode(text, from as Sender as "core");
      expect.fail("should have been refused");
    } catch (caught) {
      expect(caught).toBeInstanceOf(ProtocolError);
      expect((caught as ProtocolError).code).toBe(error);
    }
  });
});

describe("the hand-written types", () => {
  it("list exactly the messages the UI sends in the spec", () => {
    const fromSpec = Object.entries(spec.messages)
      .filter(([, entry]) => entry.from === "ui")
      .map(([name]) => name)
      .sort();
    expect([...uiTypes].sort()).toEqual(fromSpec);
  });
});

describe("encode", () => {
  it("round-trips through the core's view of a UI message", () => {
    const text = encode("approval.answer", { request_id: "r1", decision: "deny" }, "7");
    expect(decode(text, "ui")).toEqual({
      type: "approval.answer",
      id: "7",
      payload: { request_id: "r1", decision: "deny" },
    });
  });

  it("refuses a malformed message before it leaves", () => {
    expect(() =>
      encode("approval.answer", { request_id: "r1", decision: "maybe" as "deny" }),
    ).toThrow(ProtocolError);
  });

  it("refuses a core message type", () => {
    expect(() => encode("mood" as "ping", {} as Record<string, never>)).toThrow(
      ProtocolError,
    );
  });
});

describe("prototype keys are not message types", () => {
  it.each(["toString", "__proto__", "constructor"])("refuses %s", (type) => {
    expect(() => decode(JSON.stringify({ type, payload: {} }), "core")).toThrow(
      ProtocolError,
    );
  });
});
