// A proxy's 502 while Yuo restarts used to read "The server could not do this: HTTP 502" (,
// a passkey sign-in during an update).
import { I18nProvider } from "@lingui/react";
import { i18n } from "@lingui/core";
import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { activateLocale } from "../i18n";
import { ErrorNotice } from "./ErrorNotice";

beforeAll(async () => {
  await activateLocale("en");
});

const show = (error: unknown) =>
  render(
    <I18nProvider i18n={i18n}>
      <ErrorNotice error={error} />
    </I18nProvider>,
  );

describe("ErrorNotice", () => {
  it("says Yuo is restarting when a proxy answers 502 without a reason", () => {
    show(new ApiError(502, null));
    expect(screen.getByText(/Yuo is restarting or cannot be reached right now/)).toBeInTheDocument();
  });

  it("keeps Yuo's own reason when the app itself answers 502", () => {
    show(new ApiError(502, "OpenRouter did not answer"));
    expect(screen.getByText(/The server could not do this: OpenRouter did not answer/)).toBeInTheDocument();
  });
});
