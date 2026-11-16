import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { activateLocale } from "../i18n";
import type { PackagePreview, PackageUpload } from "../sharing/api";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, renderApp } from "../test/renderApp";

type Sent = { method: string; url: string; headers: Record<string, string>; body: unknown };

/** XMLHttpRequest stand-in: reports upload progress, then answers with `answer`. */
function fakeXhr(answer: { status: number; body: unknown }) {
  const sent: Sent[] = [];
  class FakeXHR {
    status = 0;
    responseText = "";
    responseType = "";
    upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = {
      onprogress: null,
    };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onabort: (() => void) | null = null;
    private req: Sent = { method: "", url: "", headers: {}, body: null };
    open(method: string, url: string) {
      this.req.method = method;
      this.req.url = url;
    }
    setRequestHeader(name: string, value: string) {
      this.req.headers[name] = value;
    }
    send(body: unknown) {
      this.req.body = body;
      sent.push(this.req);
      setTimeout(() => {
        this.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 });
        setTimeout(() => {
          this.upload.onprogress?.({ lengthComputable: true, loaded: 10, total: 10 });
          this.status = answer.status;
          this.responseText = JSON.stringify(answer.body);
          this.onload?.();
        }, 5);
      }, 5);
    }
    abort() {
      this.onabort?.();
    }
  }
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  return sent;
}

const preview: PackagePreview = {
  title: "SQL for analysts",
  profile: "full",
  contents: ["curriculum", "lessons", "items", "renditions.video", "assets"],
  counts: { path: 1, branch: 1, skill: 2, lesson: 3, item: 9, rendition: 3, asset: 9 },
  content_lang: "en",
  licence: "CC-BY-SA-4.0",
  content_version: "1.1.0",
  format_version: "1.0.0",
  upgraded_from: null,
  package_digest: "abc",
  notices: ["unsigned package"],
  personal: [],
  update_of: null,
  installed_version: null,
  can_create: true,
};

const zip = () => new File([new Uint8Array([80, 75, 3, 4])], "sql.yuo.zip", { type: "application/zip" });

async function choose(answer: PackageUpload | { status: number; body: unknown }, routes = {}) {
  const sent = fakeXhr("status" in answer ? answer : { status: 200, body: answer });
  const mock = mockApi({
    ...appRoutes,
    "DELETE /api/packages/tok1": () => new Response(null, { status: 204 }),
    ...routes,
  });
  const user = userEvent.setup();
  const view = renderApp("/import");
  await screen.findByRole("heading", { name: "Import a path" });
  const input = view.container.ownerDocument.querySelector<HTMLInputElement>('input[type="file"]');
  await user.upload(input!, zip());
  return { user, sent, ...mock, ...view };
}

describe("import page", () => {
  beforeAll(async () => {
    await activateLocale("en");
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("is linked from home", async () => {
    mockApi({ ...appRoutes, "GET /api/paths": () => json([]) });
    const user = userEvent.setup();
    const { router } = renderApp("/");
    await user.click(await screen.findByRole("link", { name: "Import a path" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/import"));
  });

  it("uploads the raw file with the CSRF header and shows a refusal with the server's reason", async () => {
    const { sent, calls } = await choose({ token: "tok1", preview: null, error: "the file is not a zip archive" });
    expect(await screen.findByText("Yuo cannot import sql.yuo.zip.")).toBeInTheDocument();
    expect(screen.getByText("Reason: the file is not a zip archive")).toBeInTheDocument();
    expect(screen.getByText("Nothing was imported.")).toBeInTheDocument();
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({
      method: "POST",
      url: "/api/packages",
      headers: { "Content-Type": "application/zip", "X-Yuo-Request": "1" },
    });
    expect(sent[0]!.body).toBeInstanceOf(File);
    // another file can be chosen right away; nothing to cancel on the server
    expect(screen.getByRole("button", { name: "Choose a file" })).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(0);
  });

  it("previews a new package and imports it as a new path", async () => {
    const { user, calls, router } = await choose(
      { token: "tok1", preview: { ...preview, installed_version: "1.0.0" }, error: null },
      {
        "POST /api/packages/tok1/import": () => json({ path_id: "p9" }),
        "GET /api/paths/p9": () => json({ detail: "x" }, 404),
      },
    );
    expect(await screen.findByRole("heading", { name: "SQL for analysts" })).toBeInTheDocument();
    expect(screen.getByText("Ready to study")).toBeInTheDocument();
    expect(screen.getByText(/Skills and structure, Lesson texts, Practice questions, Videos, Media files/)).toBeInTheDocument();
    expect(screen.getByText(/2 skills, 3 lessons, 9 questions/)).toBeInTheDocument();
    expect(screen.getByText("English")).toBeInTheDocument();
    expect(screen.getByText("CC-BY-SA-4.0")).toBeInTheDocument();
    expect(screen.getByText("1.1.0")).toBeInTheDocument(); // installed_version without update_of: an own export
    expect(screen.getByText(/This package is not signed/)).toBeInTheDocument();
    expect(screen.queryByText("Personal content")).toBeNull();
    expect(screen.queryByRole("button", { name: "Update that path" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Import as a new path" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/paths/p9"));
    expect(calls.find((c) => c.path === "/api/packages/tok1/import")?.body).toEqual({ mode: "new" });
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(0);
  });

  it("offers an update of the earlier import, or a new copy, and marks personal content", async () => {
    const { user, calls, router } = await choose(
      {
        token: "tok1",
        preview: {
          ...preview,
          update_of: "p3",
          installed_version: "1.0.0",
          upgraded_from: "0.1.0",
          personal: ["lesson basics.select.r1"],
        },
        error: null,
      },
      { "POST /api/packages/tok1/import": () => json({ path_id: "p3" }), "GET /api/paths/p3": () => json({ detail: "x" }, 404) },
    );
    expect(await screen.findByText(/You imported this package before/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See that path" })).toHaveAttribute("href", "/paths/p3");
    expect(screen.getByText("1.1.0 (you have 1.0.0)")).toBeInTheDocument();
    expect(screen.getByText("Upgraded from package format 0.1.0.")).toBeInTheDocument();
    expect(screen.getByText("Personal content")).toBeInTheDocument();
    expect(screen.getByText("basics.select.r1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import as a new copy" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Update that path" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/paths/p3"));
    expect(calls.find((c) => c.path === "/api/packages/tok1/import")?.body).toEqual({ mode: "update" });
  });

  it("offers only the update when the package cannot make a new path", async () => {
    await choose({ token: "tok1", preview: { ...preview, contents: ["items"], update_of: "p3", can_create: false }, error: null });
    expect(await screen.findByRole("button", { name: "Update that path" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Import as a new/ })).toBeNull();
  });

  it("cancel removes the upload from the server", async () => {
    const { user, calls, sent } = await choose({ token: "tok1", preview, error: null });
    await screen.findByRole("heading", { name: "SQL for analysts" });
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "DELETE").map((c) => c.path)).toEqual(["/api/packages/tok1"]));
    expect(screen.queryByRole("heading", { name: "SQL for analysts" })).toBeNull();
    expect(screen.getByRole("button", { name: "Choose a file" })).toBeInTheDocument();
    expect(sent).toHaveLength(1);
  });

  it("removes an upload that was left without importing", async () => {
    const { calls, unmount } = await choose({ token: "tok1", preview, error: null });
    await screen.findByRole("heading", { name: "SQL for analysts" });
    unmount();
    await waitFor(() => expect(calls.filter((c) => c.method === "DELETE").map((c) => c.path)).toEqual(["/api/packages/tok1"]));
  });

  it("says when the file is too large", async () => {
    await choose({ status: 413, body: { detail: "the package is larger than 10 GB" } });
    expect(await screen.findByText("This file is larger than 10 GB. Nothing was imported.")).toBeInTheDocument();
  });
});
