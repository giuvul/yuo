import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { PathOut } from "../api/client";
import { activateLocale } from "../i18n";
import { json, mockApi, type Call } from "../test/mockApi";
import { appRoutes, renderApp } from "../test/renderApp";
import { dispositionName, type ExportIn, type ExportPreview } from "./api";

const path: PathOut = {
  id: "p1",
  title: "SQL for analysts",
  subject: "SQL",
  goal: "Get the analyst job at my bank",
  status: "active",
  difficulty: "foundational",
  content_lang: "en",
  level_check: "none",
  preview: "none",
  origin: "goal",
  jobs: [],
  branches: [
    {
      id: "b1",
      code: "basics",
      title: "Basics",
      skills: [
        {
          id: "s1",
          code: "basics.select",
          title: "Selecting rows",
          summary: "",
          requires: [],
          objectives: [],
          lessons: [{ id: "l1", code: "l1", kind: "core", state: "ready", title: "What a table is", has_draft: false }],
        },
      ],
    },
  ],
};

function previewFor(body: ExportIn): ExportPreview {
  const videos = body.profile === "full" || (body.profile === "custom" && body.components?.includes("renditions.video"));
  return {
    contents: ["curriculum", "lessons", "items", ...(videos ? ["renditions.video", "assets"] : [])],
    counts: { path: 1, branch: 1, skill: 2, lesson: 3, item: 9, ...(videos ? { rendition: 3, asset: 9 } : {}) },
    asset_bytes: videos ? 12_400_000 : 0,
    personal_included: body.include_personal ? ["lesson basics.select.r1", "item basics.select.c7"] : [],
    personal_available: ["lesson basics.select.r1", "item basics.select.c7"],
    goal: "Get the analyst job at my bank",
  };
}

const previews = (calls: Call[]) =>
  calls.filter((c) => c.method === "POST" && c.path === "/api/paths/p1/export-preview").map((c) => c.body as ExportIn);

async function openDialog() {
  const user = userEvent.setup();
  const mock = mockApi({
    ...appRoutes,
    "GET /api/paths/p1": () => json(path),
    "POST /api/paths/p1/export-preview": (_r, body) => json(previewFor(body as ExportIn)),
    "POST /api/paths/p1/export": () =>
      new Response(new Uint8Array([80, 75, 3, 4, 1, 2, 3]), {
        headers: {
          "Content-Type": "application/zip",
          "Content-Disposition": 'attachment; filename="SQL-for-analysts.yuo.zip"',
          "Content-Length": "7",
        },
      }),
  });
  renderApp("/paths/p1");
  await user.click(await screen.findByRole("button", { name: "Share or export" }));
  const dialog = await screen.findByRole("dialog", { name: "Share or export this path" });
  await within(dialog).findByText(/2 skills, 3 lessons, 9 questions/);
  return { user, dialog, ...mock };
}

describe("share or export dialog", () => {
  beforeAll(async () => {
    await activateLocale("en");
  });
  beforeEach(() => {
    // jsdom has no blob URLs
    URL.createObjectURL = vi.fn(() => "blob:pkg");
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("previews the ready-to-study package with the goal for review and own content off", async () => {
    const { dialog, calls } = await openDialog();
    expect(previews(calls)[0]).toEqual({ profile: "full", components: [], include_personal: false, formats: [] });
    expect(within(dialog).getByRole("radio", { name: /Ready to study/ })).toBeChecked();
    expect(within(dialog).getByText(/Skills and structure, Lesson texts, Practice questions, Videos/)).toBeInTheDocument();
    expect(within(dialog).getByText(/3 videos and readings/)).toBeInTheDocument();
    expect(within(dialog).getByText("12 MB")).toBeInTheDocument();
    expect(within(dialog).getByText("Get the analyst job at my bank")).toBeInTheDocument();
    expect(within(dialog).getByText(/Check this before sharing: it often says something about you/)).toBeInTheDocument();
    expect(within(dialog).getByText(/code Yuo wrote to make them is never shared/)).toBeInTheDocument();
    const own = within(dialog).getByRole("checkbox", { name: /^Include my own content \(2 items: requested lessons/ });
    expect(own).not.toBeChecked();
    expect(within(dialog).queryByRole("list", { name: "My own content in the package" })).toBeNull();
  });

  it("switches profiles and sends the chosen parts", async () => {
    const { user, dialog, calls } = await openDialog();
    await user.click(within(dialog).getByText("Structure and texts"));
    await waitFor(() => expect(previews(calls).at(-1)?.profile).toBe("structure"));
    await waitFor(() => expect(within(dialog).queryByText("12 MB")).toBeNull());
    expect(within(dialog).queryByRole("checkbox", { name: "Videos" })).toBeNull();

    await user.click(within(dialog).getByText("Choose parts"));
    await waitFor(() =>
      expect(previews(calls).at(-1)).toEqual({
        profile: "custom",
        components: ["curriculum", "lessons", "items", "renditions.video", "sources"],
        include_personal: false,
        formats: [],
      }),
    );
    await user.click(within(dialog).getByRole("checkbox", { name: "Videos" }));
    await user.click(within(dialog).getByRole("checkbox", { name: "Sources" }));
    await waitFor(() =>
      expect(previews(calls).at(-1)?.components).toEqual(["curriculum", "lessons", "items"]),
    );

    for (const name of ["Skills and structure", "Lesson texts", "Practice questions"]) {
      await user.click(within(dialog).getByRole("checkbox", { name }));
    }
    expect(within(dialog).getByText("Choose at least one part.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Download" })).toBeDisabled();
    // no preview is asked for an empty selection
    expect(previews(calls).every((b) => b.profile !== "custom" || (b.components ?? []).length > 0)).toBe(true);
  });

  it("lists my own content only when I include it", async () => {
    const { user, dialog, calls } = await openDialog();
    await user.click(within(dialog).getByRole("checkbox", { name: /^Include my own content/ }));
    await waitFor(() => expect(previews(calls).at(-1)?.include_personal).toBe(true));
    const list = await within(dialog).findByRole("list", { name: "My own content in the package" });
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Lesson basics.select.r1",
      "Question basics.select.c7",
    ]);
    await user.click(within(dialog).getByRole("checkbox", { name: /^Include my own content/ }));
    await waitFor(() => expect(within(dialog).queryByRole("list", { name: "My own content in the package" })).toBeNull());
  });

  it("downloads the package with the chosen standard files", async () => {
    const saved: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      saved.push(`${this.download} ${this.href}`);
    });
    const { user, dialog, calls } = await openDialog();
    await user.click(within(dialog).getByRole("checkbox", { name: "Anki deck" }));
    await user.click(within(dialog).getByRole("checkbox", { name: "Bibliography (BibTeX)" }));
    await user.click(within(dialog).getByRole("button", { name: "Download" }));
    expect(await within(dialog).findByText(/Saved as SQL-for-analysts\.yuo\.zip/)).toBeInTheDocument();
    const download = calls.find((c) => c.path === "/api/paths/p1/export");
    expect(download?.body).toEqual({
      profile: "full",
      components: [],
      include_personal: false,
      formats: ["anki-apkg", "bibtex"],
    });
    const request = vi.mocked(globalThis.fetch).mock.calls.find(([u]) => String(u).endsWith("/api/paths/p1/export"));
    expect(new Headers(request?.[1]?.headers).get("X-Yuo-Request")).toBe("1");
    expect(saved).toEqual(["SQL-for-analysts.yuo.zip blob:pkg"]);
    expect(within(dialog).getByRole("button", { name: "Download" })).toBeEnabled();
  });

  it("shows why a download failed", async () => {
    const { user, dialog } = await openDialog();
    mockApi({
      ...appRoutes,
      "POST /api/paths/p1/export": () => json({ detail: "path not found" }, 422),
    });
    await user.click(within(dialog).getByRole("button", { name: "Download" }));
    expect(await within(dialog).findByText(/The server could not do this: path not found/)).toBeInTheDocument();
  });

  it("reads the file name from Content-Disposition", () => {
    expect(dispositionName('attachment; filename="a.yuo.zip"')).toBe("a.yuo.zip");
    expect(dispositionName("attachment; filename*=utf-8''Gr%C3%BC%C3%9Fe.yuo.zip; filename=\"x\"")).toBe("Grüße.yuo.zip");
    expect(dispositionName(null)).toBeNull();
  });
});
