import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  normalizeTransportMode,
  getTransportModeLabel,
  getTransportModeShortLabel,
  getTransportModeTokens,
  TransportMode,
} from "../components/ui/TransportModeIcon";

describe("Transport Mode Normalization & Icon Mapping Contract", () => {
  it("normalizes ocean and maritime variants", () => {
    const oceanInputs = [
      "ocean",
      "OCEAN",
      "Ocean Freight",
      "sea",
      "SEA",
      "maritime",
      "Maritime AIS",
      "vessel",
      "VESSEL",
      "ship",
      "container ship",
      "bulk carrier",
      "cargo ship",
      "water freight",
    ];

    for (const input of oceanInputs) {
      assert.equal(
        normalizeTransportMode(input),
        "ocean",
        `Expected "${input}" to normalize to "ocean"`
      );
    }
    assert.equal(getTransportModeLabel("OCEAN"), "Ocean Freight");
    assert.equal(getTransportModeShortLabel("OCEAN"), "Ocean");
    assert.equal(getTransportModeTokens("OCEAN").hex, "#38BDF8");
  });

  it("normalizes air and aviation variants", () => {
    const airInputs = [
      "air",
      "AIR",
      "Air Freight",
      "flight",
      "aviation",
      "airplane",
      "aircraft",
      "plane",
      "air cargo",
      "airfreight",
    ];

    for (const input of airInputs) {
      assert.equal(
        normalizeTransportMode(input),
        "air",
        `Expected "${input}" to normalize to "air"`
      );
    }
    assert.equal(getTransportModeLabel("AIR"), "Air Freight");
    assert.equal(getTransportModeShortLabel("AIR"), "Air");
    assert.equal(getTransportModeTokens("AIR").hex, "#F59E0B");
  });

  it("normalizes road and trucking variants", () => {
    const roadInputs = [
      "road",
      "ROAD",
      "truck",
      "TRUCK",
      "trucking",
      "highway",
      "road freight",
      "road logistics",
      "ground",
      "van",
    ];

    for (const input of roadInputs) {
      assert.equal(
        normalizeTransportMode(input),
        "road",
        `Expected "${input}" to normalize to "road"`
      );
    }
    assert.equal(getTransportModeLabel("ROAD"), "Road Freight");
    assert.equal(getTransportModeShortLabel("ROAD"), "Road");
    assert.equal(getTransportModeTokens("ROAD").hex, "#10B981");
  });

  it("normalizes rail and train variants", () => {
    const railInputs = [
      "rail",
      "RAIL",
      "railway",
      "train",
      "rail freight",
      "intermodal rail",
      "railcar",
      "freight train",
    ];

    for (const input of railInputs) {
      assert.equal(
        normalizeTransportMode(input),
        "rail",
        `Expected "${input}" to normalize to "rail"`
      );
    }
    assert.equal(getTransportModeLabel("RAIL"), "Rail Freight");
    assert.equal(getTransportModeShortLabel("RAIL"), "Rail");
    assert.equal(getTransportModeTokens("RAIL").hex, "#A855F7");
  });

  it("normalizes warehouse, port, and terminal variants", () => {
    assert.equal(normalizeTransportMode("warehouse"), "warehouse");
    assert.equal(normalizeTransportMode("distribution center"), "warehouse");
    assert.equal(normalizeTransportMode("fulfillment center"), "warehouse");

    assert.equal(normalizeTransportMode("port"), "port");
    assert.equal(normalizeTransportMode("seaport"), "port");
    assert.equal(normalizeTransportMode("marine terminal"), "port");

    assert.equal(normalizeTransportMode("airport"), "airport");
    assert.equal(normalizeTransportMode("air terminal"), "airport");
  });

  it("safely handles unknown and edge case values without throwing", () => {
    const fallbacks = [null, undefined, "", "   ", "teleportation", "rocket", "unknown_mode"];

    for (const input of fallbacks) {
      const mode: TransportMode = normalizeTransportMode(input);
      assert.equal(mode, "unknown");
      assert.ok(typeof getTransportModeLabel(input) === "string");
      assert.ok(typeof getTransportModeShortLabel(input) === "string");
      assert.ok(typeof getTransportModeTokens(input).hex === "string");
    }
  });
});
