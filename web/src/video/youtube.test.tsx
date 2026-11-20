import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { LessonOut, SettingOut } from "../api/client";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, renderApp } from "../test/renderApp";
import { embedUrl } from "./YouTubeVideo";

beforeAll(async () => {
  await activateLocale("en");
});

type YouTube = NonNullable<LessonOut["youtube"]>;

const found: YouTube = {
  video_id: "vid2aaaaaa",
  title: "Joins explained",
  channel: "Data Channel",
  start_s: 60,
  end_s: 570,
  gone: false,
  note: null,
};

const lesson = (youtube: YouTube | null, state = "ready"): LessonOut => ({
  id: "L1",
  state,
  path_id: "p1",
  skill_id: "s1",
  version_id: "lv1",
  title: "Joins",
  body: [{ type: "paragraph", bid: "b1", inlines: [{ text: "A join combines rows." }] }],
  est_minutes: 5,
  lang: "it",
  skill_title: "Joining",
  path_title: "SQL",
  practice_items: 0,
  sources: [],
  video: null,
  video_unavailable: null,
  youtube,
});

function serve(l: LessonOut) {
  const another: string[] = [];
  const api = mockApi({
    ...appRoutes,
    "GET /api/lessons/L1": () => json(l),
    "GET /api/lessons/L1/notes": () => json([]),
    "GET /api/settings": () => json([]),
    "POST /api/lessons/L1/youtube/another": () => {
      another.push("L1");
      return json({ job_id: "j1" }, 202);
    },
    "POST /api/events": (_r, body) => {
      const ids = (body as { events: { id: string }[] }).events.map((e) => e.id);
      return json({ accepted: ids, duplicates: [], rejected: {}, graded: {}, outcomes: {} });
    },
  });
  return { ...api, another };
}

describe("a lesson built on a YouTube video", () => {
  it("loads nothing from YouTube until play, then plays the stretch in the nocookie player", async () => {
    serve(lesson(found));
    const user = userEvent.setup();
    renderApp("/lessons/L1");
    const section = await screen.findByRole("region", { name: "Video for this lesson" });
    expect(section.querySelector("iframe")).toBeNull();
    expect(within(section).getByText(/Data Channel · Watch 1:00 to 9:30/)).toBeInTheDocument();
    await user.click(within(section).getByRole("button", { name: /Joins explained/ }));
    const frame = section.querySelector("iframe");
    expect(frame?.getAttribute("src")).toBe(
      "https://www.youtube-nocookie.com/embed/vid2aaaaaa?autoplay=1&rel=0&hl=it&cc_lang_pref=it&start=60&end=570" +
        `&enablejsapi=1&origin=${encodeURIComponent(window.location.origin)}`,
    );
    expect(within(section).getByRole("link", { name: "Open on YouTube" })).toHaveAttribute(
      "href",
      "https://www.youtube.com/watch?v=vid2aaaaaa&t=60s",
    );
    expect(within(section).getByRole("link", { name: "YouTube Terms of Service" })).toBeInTheDocument();
  });

  it("keeps the lesson's part in view while the video plays: where it is, what is left, the way back", async () => {
    serve(lesson(found));
    const user = userEvent.setup();
    renderApp("/lessons/L1");
    const section = await screen.findByRole("region", { name: "Video for this lesson" });
    await user.click(within(section).getByRole("button", { name: /Joins explained/ }));
    const frame = section.querySelector("iframe") as HTMLIFrameElement;
    const player = frame.contentWindow as Window;
    const sent: string[] = [];
    vi.spyOn(player, "postMessage").mockImplementation((m: unknown) => void sent.push(String(m)));
    expect(within(section).getByText("Watch 1:00 to 9:30")).toBeInTheDocument(); // before the player answers
    const at = (s: number) =>
      act(() => {
        window.dispatchEvent(
          new MessageEvent("message", {
            data: JSON.stringify({ event: "infoDelivery", info: { currentTime: s } }),
            origin: "https://www.youtube-nocookie.com",
            source: player,
          }),
        );
      });
    at(120.4);
    expect(await within(section).findByText("At 2:00: 7:30 left, until 9:30.")).toBeInTheDocument();
    expect(within(section).getByRole("progressbar", { name: "Through the lesson's part of the video" })).toHaveAttribute(
      "aria-valuenow",
      "60",
    );
    at(575);
    expect(await within(section).findByText(/The lesson's part ended at 9:30/)).toBeInTheDocument();
    await user.click(within(section).getByRole("button", { name: "Back to 1:00" }));
    expect(sent.some((m) => m.includes('"seekTo"') && m.includes("[60,true]"))).toBe(true);
    // a message from another page is not the player's
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: JSON.stringify({ event: "infoDelivery", info: { currentTime: 30 } }),
          origin: "https://example.com",
        }),
      );
    });
    expect(within(section).getByText(/The lesson's part ended at 9:30/)).toBeInTheDocument();
  });

  it("asks for another video and says the lesson is being written again", async () => {
    const { another } = serve(lesson(found));
    const user = userEvent.setup();
    renderApp("/lessons/L1");
    await user.click(await screen.findByRole("button", { name: "Another video" }));
    await waitFor(() => expect(another).toEqual(["L1"]));
    expect(await screen.findByText(/Yuo is looking for another video/)).toBeInTheDocument();
  });

  it("says why there is no video and offers to look again", async () => {
    serve(lesson({ ...found, video_id: null, title: null, channel: null, note: "blocked" }));
    renderApp("/lessons/L1");
    expect(await screen.findByText(/YouTube refused this server's request/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Look for a video again" })).toBeInTheDocument();
    expect(screen.getByText("A join combines rows.")).toBeInTheDocument();
  });

  it("an embed without an end plays from the start of the stretch", () => {
    expect(embedUrl({ ...found, end_s: null }, "en")).not.toContain("end=");
  });
});

const setting = (key: string, value: unknown): SettingOut => ({
  key,
  cfg: "CFG-87",
  value,
  default: "generated",
  source: "learner",
  levels: ["installation", "learner", "path"],
  explanation: "",
  example: "",
  suggestion: "",
  impact: [],
  weakens_learning: null,
});

describe("Settings > Videos with YouTube", () => {
  it("shows the disclaimer and checks and saves a YouTube key", async () => {
    const keys: unknown[] = [];
    mockApi({
      ...appRoutes,
      "GET /api/settings": () => json([setting("video.source", "youtube")]),
      "PUT /api/setup/access/youtube": (_r, body) => {
        keys.push(body);
        return new Response(null, { status: 204 });
      },
    });
    const user = userEvent.setup();
    renderApp("/settings");
    expect(await screen.findByText(/You use this at your own risk/)).toBeInTheDocument();
    const field = screen.getByLabelText("YouTube key");
    await user.type(field, "sk-wrong");
    expect(screen.getByText(/does not look like a Google API key/)).toBeInTheDocument();
    await user.clear(field);
    await user.type(field, "AIzaTESTKEY123");
    await user.click(within(field.closest("form")!).getByRole("button", { name: "Check and save the key" }));
    await waitFor(() => expect(keys).toEqual([{ key: "AIzaTESTKEY123" }]));
    expect(await screen.findByText("The key works and is saved.")).toBeInTheDocument();
  });

  it("shows neither when videos are made by Yuo", async () => {
    mockApi({ ...appRoutes, "GET /api/settings": () => json([setting("video.source", "generated")]) });
    renderApp("/settings");
    expect(await screen.findByRole("heading", { name: "Where videos come from" })).toBeInTheDocument();
    expect(screen.queryByText(/You use this at your own risk/)).toBeNull();
    expect(screen.queryByLabelText("YouTube key")).toBeNull();
  });
});
