import type { Strategy } from "@/shared/api";
import { pollDelayMs } from "../api/analysis-api";
import { deltaText, rankLabel, sortStrategies } from "./strategies";

const strat = (id: string, score: number, is_current = false): Strategy => ({
  id,
  name: id,
  is_current,
  rotation: [],
  score,
  confidence: "high",
  summary: "",
  benefits: [],
  risks: [],
  evidence: [],
  information_gaps: [],
  needs_local_review: false,
});

describe("strategies", () => {
  it("ranks by score and compares to the current rotation", () => {
    const sorted = sortStrategies([strat("a", 64, true), strat("b", 82), strat("c", 70)]);
    expect(sorted.map((s) => s.id)).toEqual(["b", "c", "a"]);
    expect(rankLabel(0)).toBe("Best fit");
    expect(rankLabel(2)).toBe("Option 3");
    expect(deltaText(sorted[0]!, 64)).toBe("+18 vs your current rotation");
    expect(deltaText(sorted[2]!, 64)).toBe("Baseline");
  });
});

describe("pollDelayMs", () => {
  it("polls every 2 s, then every 5 s after 30 s", () => {
    expect(pollDelayMs(0)).toBe(2000);
    expect(pollDelayMs(30_001)).toBe(5000);
  });
});
