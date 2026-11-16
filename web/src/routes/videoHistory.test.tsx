// The video watch history is erased from the Videos group in Settings, after one confirmation.
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it } from "vitest";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, renderApp } from "../test/renderApp";

beforeAll(async () => {
  await activateLocale("en");
});

const captions = {
  key: "video.captions",
  cfg: "CFG-78",
  value: true,
  default: true,
  source: "default",
  levels: ["installation", "learner"],
  explanation: "",
  example: "",
  suggestion: "",
  impact: [],
  weakens_learning: null,
};

describe("the video watch history", () => {
  it("is erased from Settings after one confirmation", async () => {
    const api = mockApi({
      ...appRoutes,
      "GET /api/settings": () => json([captions]),
      "DELETE /api/me/video-history": () => json({ counts: { watch_coverage: 3 } }),
    });
    const user = userEvent.setup();
    renderApp("/settings");
    const group = (await screen.findByText("Videos")).closest("summary")!;
    await user.click(group);
    await user.click(screen.getByRole("button", { name: "Delete my video watch history" }));
    const ask = screen.getByRole("group", { name: /Delete which videos you watched/ });
    await user.click(within(ask).getByRole("button", { name: "Delete the history" }));
    expect(await screen.findByText("Your video watch history is deleted.")).toBeInTheDocument();
    expect(api.calls.filter((c) => c.method === "DELETE").map((c) => c.path)).toEqual(["/api/me/video-history"]);
  });
});
