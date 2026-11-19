import { describe, expect, it } from "vitest";
import { mathParts, plainMath } from "./MathText";

describe("inline maths", () => {
  it("finds $...$ but leaves amounts of money as text", () => {
    expect(mathParts("Then $f'(x) = 2x$ costs $5 and $10.")).toEqual([
      { math: false, text: "Then " },
      { math: true, text: "f'(x) = 2x" },
      { math: false, text: " costs $5 and $10." },
    ]);
    expect(plainMath("Solve $x^2 = 4$")).toBe("Solve x^2 = 4");
    expect(mathParts("no maths")).toEqual([{ math: false, text: "no maths" }]);
  });
});
