import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { LessonOut, NoteOut, TutorContextIn } from "../api/client";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, renderApp } from "../test/renderApp";
import { contextOut } from "../test/tutor";
import type { VideoPlayerProps } from "./VideoPlayer";

// The real player (Media Chrome) runs in the browser tests; here a stand-in shows what it was given.
vi.mock("./VideoPlayer", () => ({
  default: function FakePlayer(p: VideoPlayerProps) {
    return (
      <div role="group" aria-label={p.label} data-pause-key={p.pauseKey} data-seek={p.seek?.s}>
        <video src={p.src} poster={p.poster}>
          {p.captions ? <track kind="captions" src={p.captions.src} srcLang={p.captions.lang} default={p.captionsOn} /> : null}
        </video>
        <span>{p.captionsOn ? "captions start on" : "captions start off"}</span>
        <button type="button" onClick={() => p.onCaptionsChange?.(!p.captionsOn)}>
          toggle captions
        </button>
        <button type="button" onClick={() => p.onTime?.(12.34)}>
          play to 12 s
        </button>
      </div>
    );
  },
}));

beforeAll(async () => {
  await activateLocale("en");
});
afterEach(() => vi.unstubAllGlobals());

type Video = NonNullable<LessonOut["video"]>;

const lesson = (video: Video | null, unavailable: string | null = null): LessonOut => ({
  id: "L1",
  state: "ready",
  path_id: "p1",
  skill_id: "s1",
  version_id: "lv1",
  title: "Joins",
  body: [{ type: "paragraph", bid: "b1", inlines: [{ text: "A join combines rows." }] }],
  est_minutes: 5,
  lang: "en",
  skill_title: "Joining",
  path_title: "SQL",
  practice_items: 0,
  video,
  video_unavailable: unavailable,
});

const ready: Video = {
  rendition_id: "r1",
  state: "ready",
  version_id: "rv1",
  duration_s: 105,
  lang: "en",
  assets: { video: "hv", subtitles: "hs", poster: "hp" },
};

type Note = NoteOut;

function serve(l: LessonOut, captions: boolean | null = true, extra: { bubble?: boolean; notes?: Note[] } = {}) {
  const puts: unknown[] = [];
  const contexts: TutorContextIn[] = [];
  const posted: unknown[] = [];
  const notes: Note[] = [...(extra.notes ?? [])];
  const bubble =
    extra.bubble === undefined
      ? []
      : [{ key: "video.notes_bubble", cfg: "CFG-83", value: extra.bubble, default: true, source: "learner", levels: ["installation", "learner"], explanation: "", example: "", suggestion: "", impact: [], weakens_learning: null }];
  const api = mockApi({
    ...appRoutes,
    "GET /api/lessons/L1": () => json(l),
    "GET /api/lessons/L1/notes": () => json(notes),
    "POST /api/notes": (_r, body) => {
      posted.push(body);
      const b = body as { text: string; rendition_version_id: string; t_s: number };
      notes.push({ id: `n${notes.length + 1}`, text: b.text, bid: null, lesson_version_id: null, sent_message_id: null, created_at: "2026-11-15T19:00:00.000Z", updated_at: "2026-11-15T19:00:00.000Z", rendition_version_id: b.rendition_version_id, t_s: b.t_s });
      return json({ note_id: `n${notes.length}` }, 201);
    },
    "POST /api/events": (_r, body) => {
      const ids = (body as { events: { id: string }[] }).events.map((e) => e.id);
      return json({ accepted: ids, duplicates: [], rejected: {}, graded: {}, outcomes: {} });
    },
    "GET /api/settings": () =>
      json(
        captions === null
          ? bubble
          : [
              ...bubble,
              {
                key: "video.captions",
                cfg: "CFG-78",
                value: captions,
                default: true,
                source: "learner",
                levels: ["installation", "learner"],
                explanation: "",
                example: "",
                suggestion: "",
                impact: [],
                weakens_learning: null,
              },
            ],
      ),
    "POST /api/lessons/L1/video": () => json({ job_id: "j9" }, 202),
    "PUT /api/settings/video.captions": (_r, body) => {
      puts.push(body);
      return new Response(null, { status: 204 });
    },
    "POST /api/tutor/context": (_r, body) => {
      contexts.push(body as TutorContextIn);
      return json(contextOut());
    },
    "GET /api/tutor/messages": () => json([]),
  });
  return { ...api, puts, contexts, posted };
}

describe("the notes bubble", () => {
  it("saves a question at the video's moment, lists it, jumps to it and sends the open ones to the tutor", async () => {
    const asked: Note = { id: "n0", text: "an old one", bid: null, lesson_version_id: null, sent_message_id: "m1", created_at: "2026-11-15T18:00:00.000Z", updated_at: "2026-11-15T18:00:00.000Z", rendition_version_id: "rv1", t_s: 3 };
    const { posted } = serve(lesson(ready), true, { notes: [asked] });
    const user = userEvent.setup();
    renderApp("/lessons/L1");
    const player = await screen.findByRole("group", { name: "Lesson video" });
    await user.click(within(player).getByRole("button", { name: "play to 12 s" }));
    await user.click(await screen.findByRole("button", { name: /^Questions for the tutor: tap to open/ }));
    const panel = await screen.findByRole("dialog", { name: "Questions for the tutor" });
    const input = within(panel).getByRole("textbox", { name: "Question at 0:12" });
    expect(input).toHaveFocus();
    await user.type(input, "why is B next to C?{Enter}");
    await waitFor(() => expect(posted).toEqual([{ text: "why is B next to C?", rendition_version_id: "rv1", t_s: 12.3 }]));
    expect(await within(panel).findByText("why is B next to C?")).toBeInTheDocument();
    expect(within(panel).queryByText("an old one")).toBeNull(); // already asked: behind a toggle
    await user.click(within(panel).getByRole("button", { name: "Show 1 already asked" }));
    expect(within(panel).getByText("an old one")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Play the video from 0:12" }));
    expect(player).toHaveAttribute("data-seek", "12.3");
    await user.click(within(panel).getByRole("button", { name: "Ask the tutor (1)" }));
    const composer = await screen.findByRole("textbox", { name: "Message to Tutor" });
    expect(composer).toHaveValue("I wrote these questions while watching the video. Can you go through them with me?");
    expect(screen.queryByRole("dialog", { name: "Questions for the tutor" })).toBeNull();
  });

  it("closes on a press outside its box and keeps an unsaved question", async () => {
    serve(lesson(ready), true);
    const user = userEvent.setup();
    renderApp("/lessons/L1");
    const player = await screen.findByRole("group", { name: "Lesson video" });
    await user.click(await screen.findByRole("button", { name: /^Questions for the tutor: tap to open/ }));
    const panel = await screen.findByRole("dialog", { name: "Questions for the tutor" });
    await user.type(within(panel).getByRole("textbox"), "half a question");
    await user.click(within(panel).getByRole("textbox")); // inside: stays open
    expect(screen.getByRole("dialog", { name: "Questions for the tutor" })).toBeInTheDocument();
    await user.click(player);
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Questions for the tutor" })).toBeNull());
    await user.click(screen.getByRole("button", { name: /^Questions for the tutor: tap to open/ }));
    const again = await screen.findByRole("dialog", { name: "Questions for the tutor" });
    expect(within(again).getByRole("textbox")).toHaveValue("half a question");
  });

  it("is not there when the setting is off", async () => {
    serve(lesson(ready), true, { bubble: false });
    renderApp("/lessons/L1");
    await screen.findByRole("group", { name: "Lesson video" });
    expect(screen.queryByRole("button", { name: /^Questions for the tutor/ })).toBeNull();
  });
});

describe("lesson video", () => {
  it("shows the player with poster, captions track and the download link when ready", async () => {
    serve(lesson(ready));
    renderApp("/lessons/L1");
    const player = await screen.findByRole("group", { name: "Lesson video" });
    const video = player.querySelector("video")!;
    expect(video).toHaveAttribute("src", "/api/assets/hv");
    expect(video).toHaveAttribute("poster", "/api/assets/hp");
    const track = player.querySelector("track")!;
    expect(track).toHaveAttribute("src", "/api/assets/hs");
    expect(track).toHaveAttribute("srclang", "en");
    expect(screen.getByRole("link", { name: "Download video (MP4 with subtitles)" })).toHaveAttribute(
      "href",
      "/api/renditions/rv1/export",
    );
    // the reading lesson stays on the page
    expect(screen.getByText("A join combines rows.")).toBeInTheDocument();
  });

  it("starts captions from the learner's setting and saves a toggle", async () => {
    const { puts } = serve(lesson(ready), false);
    const user = userEvent.setup();
    renderApp("/lessons/L1");
    expect(await screen.findByText("captions start off")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "toggle captions" }));
    await waitFor(() => expect(puts).toEqual([{ value: true, level: "learner" }]));
  });

  it("captions are on when the setting is missing (the default)", async () => {
    serve(lesson(ready), null);
    renderApp("/lessons/L1");
    expect(await screen.findByText("captions start on")).toBeInTheDocument();
  });

  it("gives the tutor the video time and pauses when the tutor opens", async () => {
    const { contexts } = serve(lesson(ready));
    const user = userEvent.setup();
    renderApp("/lessons/L1");
    const player = await screen.findByRole("group", { name: "Lesson video" });
    expect(player).toHaveAttribute("data-pause-key", "0");
    await user.click(within(player).getByRole("button", { name: "play to 12 s" }));
    await user.click(screen.getByRole("button", { name: /^Tutor/ }));
    await waitFor(() => expect(player).toHaveAttribute("data-pause-key", "1"));
    await waitFor(() => expect(contexts.at(-1)).toMatchObject({ screen: "reading", lesson_id: "L1", video_s: 12.3 }));
  });

  it.each([["queued"], ["generating"], ["in_review"]] as const)("says the video is being made while %s", async (state) => {
    serve(lesson({ ...ready, state, assets: {} }));
    renderApp("/lessons/L1");
    expect(
      await screen.findByText("The video is being made; the reading lesson is here meanwhile."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Lesson video" })).toBeNull();
    expect(screen.getByText("A join combines rows.")).toBeInTheDocument();
  });

  it("keeps a failed video to one muted line", async () => {
    serve(lesson({ ...ready, state: "failed", assets: {} }));
    renderApp("/lessons/L1");
    expect(
      await screen.findByText("There is no video for this lesson this time; the reading lesson below has it all."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("link", { name: /Download video/ })).toBeNull();
  });

  it("makes a failed video again on request", async () => {
    const api = serve(lesson({ ...ready, state: "failed", assets: {} }));
    renderApp("/lessons/L1");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Try making the video again" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "/api/lessons/L1/video")).toBe(true));
  });

  it("explains in one line when this installation makes no videos", async () => {
    serve(lesson(null, "no_sandbox"));
    renderApp("/lessons/L1");
    expect(await screen.findByText(/This system cannot keep video code away from the network/)).toBeInTheDocument();
  });

  it("shows nothing for a lesson without a video", async () => {
    serve(lesson(null));
    renderApp("/lessons/L1");
    await screen.findByText("A join combines rows.");
    expect(screen.queryByText(/video/i)).toBeNull();
  });
});
