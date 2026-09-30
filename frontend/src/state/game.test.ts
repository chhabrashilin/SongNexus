import { describe, expect, it } from "vitest";

import { applyMiss, applyStep, classifyMove, currentDistance, newGame, shareText, undo, type Step } from "./game";

const node = (name: string) => ({ id: name.toLowerCase(), name, genres: [] });
const step = (name: string, distance: number | null): Step => ({ artist: node(name), evidence: [], evidenceTotal: 0, distance });
const puzzle = { number: 7, start: node("Miles Davis"), target: node("Drake"), par: 4 };

describe("daily game", () => {
  it("classifies moves by distance to the target", () => {
    expect(classifyMove(4, 3)).toBe("closer");
    expect(classifyMove(3, 3)).toBe("same");
    expect(classifyMove(3, 4)).toBe("farther");
    expect(classifyMove(3, null)).toBe("farther");
  });

  it("tracks the current distance, starting at par", () => {
    let game = newGame("2026-10-06");
    expect(currentDistance(game, 4)).toBe(4);
    game = applyStep(game, step("Herbie Hancock", 3), 4, false);
    expect(currentDistance(game, 4)).toBe(3);
  });

  it("wins, counts misses once, and supports undo while playing", () => {
    let game = newGame("2026-10-06");
    game = applyStep(game, step("Herbie Hancock", 3), 4, false);
    game = applyStep(game, step("Wayne Shorter", 4), 4, false);
    game = undo(game);
    game = applyMiss(applyMiss(game, "Kanye"), "Kanye");
    game = applyStep(game, step("Robert Glasper", 2), 4, false);
    game = applyStep(game, step("Yebba", 1), 4, false);
    game = applyStep(game, step("Drake", 0), 4, true);
    expect(game.status).toBe("won");
    expect(game.chain.map((s) => s.artist.name)).toEqual(["Herbie Hancock", "Robert Glasper", "Yebba", "Drake"]);
    expect(game.misses).toEqual(["Kanye"]);
    expect(undo(game)).toBe(game); // no undo after winning
  });

  it("share text is spoiler-free", () => {
    let game = newGame("2026-10-06");
    game = applyStep(game, step("Herbie Hancock", 3), 4, false);
    game = applyStep(game, step("Drake", 0), 4, true);
    game = { ...game, hints: 1, misses: ["X"] };
    const text = shareText(game, puzzle);
    expect(text).toBe("SongNexus Daily #7 🎧\nMiles Davis → Drake\n2 steps (par 4) · 1 miss · 1 hint\n🟩🟩🎯");
    expect(text).not.toContain("Herbie");
  });
});
