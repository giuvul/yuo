import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { activateLocale, i18n } from "../i18n";
import { LessonBody } from "./BlockRenderer";

function renderBody(body: unknown) {
  return render(
    <I18nProvider i18n={i18n}>
      <LessonBody body={body} />
    </I18nProvider>,
  );
}

const p = (text: string, marks?: string[]) => ({ text, ...(marks ? { marks } : {}) });

describe("lesson body renderer", () => {
  beforeAll(async () => {
    await activateLocale("en");
  });

  it("marks the block last tapped, so a phone shows only that block's note button", () => {
    const { container } = render(
      <I18nProvider i18n={i18n}>
        <LessonBody
          body={[
            { type: "paragraph", bid: "b1", inlines: [p("First")] },
            { type: "paragraph", bid: "b2", inlines: [p("Second")] },
          ]}
          after={(bid) => <button type="button">note {bid}</button>}
        />
      </I18nProvider>,
    );
    const touched = () => [...container.querySelectorAll("[data-touched]")].map((el) => el.getAttribute("data-bid"));
    expect(touched()).toEqual([]);
    fireEvent.click(screen.getByText("Second"));
    expect(touched()).toEqual(["b2"]);
    fireEvent.click(screen.getByText("First"));
    expect(touched()).toEqual(["b1"]);
  });

  it("renders headings one level below the page title", () => {
    renderBody([
      { type: "heading", bid: "b1", level: 1, text: "Joins" },
      { type: "heading", bid: "b2", level: 2, text: "Inner joins" },
    ]);
    expect(screen.getByRole("heading", { level: 2, name: "Joins" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Inner joins" })).toBeInTheDocument();
  });

  it("renders paragraphs with bold, italic and code marks", () => {
    const { container } = renderBody([
      {
        type: "paragraph",
        bid: "b1",
        inlines: [p("A "), p("join", ["bold"]), p(" combines "), p("rows", ["italic"]), p(" with "), p("ON", ["code"])],
      },
    ]);
    const para = container.querySelector("p")!;
    expect(para).toHaveTextContent("A join combines rows with ON");
    expect(para.querySelector("strong")).toHaveTextContent("join");
    expect(para.querySelector("em")).toHaveTextContent("rows");
    expect(para.querySelector("code")).toHaveTextContent("ON");
  });

  it("renders ordered and unordered lists of inline items", () => {
    renderBody([
      { type: "list", bid: "b1", ordered: true, items: [[p("first")], [p("second", ["bold"])]] },
      { type: "list", bid: "b2", ordered: false, items: [[p("apple")]] },
    ]);
    const lists = screen.getAllByRole("list");
    expect(lists[0]!.tagName).toBe("OL");
    expect(lists[0]!.querySelectorAll("li")).toHaveLength(2);
    expect(lists[1]!.tagName).toBe("UL");
    expect(screen.getByText("second").tagName).toBe("STRONG");
  });

  it("renders code as pre/code with its caption", () => {
    const { container } = renderBody([
      { type: "code", bid: "b1", language: "sql", text: "SELECT 1;", caption: "The smallest query" },
    ]);
    const pre = container.querySelector("pre")!;
    expect(pre).toHaveAttribute("data-language", "sql");
    expect(pre.querySelector("code")).toHaveTextContent("SELECT 1;");
    expect(screen.getByText("The smallest query").tagName).toBe("FIGCAPTION");
  });

  it("renders math with KaTeX after it loads, showing the source first", async () => {
    const { container } = renderBody([{ type: "math", bid: "b1", latex: "a^2 + b^2 = c^2", display: true }]);
    expect(container.querySelector("[data-math] code")).toHaveTextContent("a^2 + b^2 = c^2");
    await waitFor(() => expect(container.querySelector(".katex")).not.toBeNull());
    expect(container.querySelector("[data-math] > code")).toBeNull();
  });

  it("renders callouts with nested blocks, worked examples and glossary terms", () => {
    renderBody([
      {
        type: "callout",
        bid: "b1",
        variant: "warning",
        blocks: [{ type: "paragraph", bid: "b1.1", inlines: [p("NULL is not equal to NULL.")] }],
      },
      { type: "worked_example", bid: "b2", title: "Count rows", steps: [[p("Write "), p("COUNT(*)", ["code"])], [p("Run it")]] },
      { type: "glossary_term", bid: "b3", term: "Join", definition: "Combining rows of two tables." },
    ]);
    expect(screen.getByText("Watch out")).toBeInTheDocument();
    expect(screen.getByText("NULL is not equal to NULL.")).toBeInTheDocument();
    expect(screen.getByText("Worked example")).toBeInTheDocument();
    expect(screen.getByText("Count rows")).toBeInTheDocument();
    expect(screen.getByText("COUNT(*)").tagName).toBe("CODE");
    expect(screen.getByText("Join").tagName).toBe("DFN");
    expect(screen.getByText("Combining rows of two tables.").tagName).toBe("DD");
  });

  it("skips unknown and malformed blocks without crashing", () => {
    const { container } = renderBody([
      { type: "diagram", bid: "b1", syntax: "mermaid", source: "graph TD; A-->B", alt: "x" },
      { type: "paragraph", bid: "b2" },
      null,
      "text",
      { type: "heading", bid: "b3", level: 2, text: "Still here" },
    ]);
    expect(screen.getByRole("heading", { name: "Still here" })).toBeInTheDocument();
    expect(container.textContent).not.toContain("graph TD");
  });

  it("renders nothing for a body that is not a list", () => {
    const { container } = renderBody({ type: "paragraph" });
    expect(container.textContent).toBe("");
  });

  it("never turns text into HTML", () => {
    const evil = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=2</script>';
    const { container } = renderBody([
      { type: "heading", bid: "b1", level: 1, text: evil },
      { type: "paragraph", bid: "b2", inlines: [p(evil), p(evil, ["bold"])] },
      { type: "list", bid: "b3", ordered: false, items: [[p(evil)]] },
      { type: "code", bid: "b4", language: '"><img src=x>', text: evil, caption: evil },
      { type: "callout", bid: "b5", variant: '"><img src=x>', blocks: [{ type: "paragraph", bid: "b5.1", inlines: [p(evil)] }] },
      { type: "worked_example", bid: "b6", title: evil, steps: [[p(evil)]] },
      { type: "glossary_term", bid: "b7", term: evil, definition: evil },
    ]);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("[onerror], [src]")).toBeNull();
    // only the elements the renderer itself creates
    const tags = new Set(Array.from(container.querySelectorAll("*"), (el) => el.tagName.toLowerCase()));
    const allowed = ["div", "h2", "p", "span", "strong", "ul", "li", "figure", "pre", "code", "figcaption", "aside", "section", "ol", "dl", "dt", "dfn", "dd"];
    expect([...tags].filter((t) => !allowed.includes(t))).toEqual([]);
    expect(container.textContent).toContain('<img src=x onerror="window.__pwned=1">');
    expect((window as { __pwned?: number }).__pwned).toBeUndefined();
  });

  it("does not let KaTeX render links or HTML from LaTeX", async () => {
    const { container } = renderBody([
      { type: "math", bid: "b1", latex: "\\href{javascript:alert(1)}{x} \\htmlId{a}{y}", display: false },
    ]);
    await waitFor(() => expect(container.querySelector(".katex")).not.toBeNull());
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("#a")).toBeNull();
  });
});
