import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { CliOut } from "../api/client";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { cliReady, cliSignedOut, cliStatus } from "../test/renderApp";
import { CliAccess, CliAccessView, type CliHandlers } from "./CliAccess";

beforeAll(async () => {
  await activateLocale("en");
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const noop: CliHandlers = {
  onInstall: () => undefined,
  onLogin: () => undefined,
  onSendCode: () => undefined,
  onCancelLogin: () => undefined,
  onCheck: () => undefined,
};

function view(cli: CliOut, handlers: Partial<CliHandlers> = {}) {
  return render(
    <I18nProvider i18n={i18n}>
      <CliAccessView cli={cli} {...noop} {...handlers} />
    </I18nProvider>,
  );
}

function live(cli: "claude" | "codex" = "claude") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider i18n={i18n}>
        <CliAccess cli={cli} />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const codex = (patch: Partial<CliOut> = {}): CliOut =>
  cliStatus({
    cli: "codex",
    name: "Codex",
    os: "windows",
    can_install: false,
    can_login: false,
    code_login: false,
    install_command: "npm install -g @openai/codex",
    login_command: "codex login",
    docs_url: "https://developers.openai.com/codex/cli",
    ...patch,
  });

describe("a subscription program's card", () => {
  it("offers to install a missing program, with the manual way behind a disclosure", async () => {
    const onInstall = vi.fn();
    const onCheck = vi.fn();
    const user = userEvent.setup();
    view(cliStatus(), { onInstall, onCheck });

    expect(screen.getByRole("heading", { name: "Claude Code is not installed yet" })).toBeInTheDocument();
    expect(screen.getByText(/Your subscription works through Claude Code/)).toBeInTheDocument();
    expect(screen.getByText("curl -fsSL https://claude.ai/install.sh | bash")).not.toBeVisible();
    await user.click(screen.getByRole("button", { name: "Install Claude Code" }));
    expect(onInstall).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Do it yourself" }));
    expect(screen.getByText("curl -fsSL https://claude.ai/install.sh | bash")).toBeInTheDocument();
    expect(screen.getByText("Run this in a terminal on the computer that runs Yuo:")).toBeInTheDocument();
    const guide = screen.getByRole("link", { name: "The Claude Code guide (opens in a new tab)" });
    expect(guide).toHaveAttribute("href", "https://docs.claude.com/en/docs/claude-code/setup");
    expect(guide).toHaveAttribute("target", "_blank");
    await user.click(screen.getByRole("button", { name: "Check again" }));
    expect(onCheck).toHaveBeenCalledTimes(1);
  });

  it("after installing, when the program has not said whether it is signed in, offers the sign-in", async () => {
    const onLogin = vi.fn();
    const user = userEvent.setup();
    view(
      cliStatus({ installed: true, version: "2.1.0", logged_in: null, ready: true, reason: null, can_login: true }),
      { onLogin },
    );
    expect(screen.getByRole("heading", { name: "Claude Code is installed: sign in next" })).toBeInTheDocument();
    expect(screen.getByText(/could not tell yet whether Claude Code is signed in/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sign in to Claude Code" }));
    expect(onLogin).toHaveBeenCalledTimes(1);
  });

  it("says that the installer runs, and after a failure shows the error and the manual way in a container", () => {
    const running = view(cliStatus({ install: { state: "running", url: null, code: null, error: null } }));
    expect(screen.getByRole("heading", { name: "Installing Claude Code" })).toBeInTheDocument();
    expect(screen.getByText("Installing… this can take a minute.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Install Claude Code" })).toBeNull();
    running.unmount();

    view(cliStatus({ container: true, install: { state: "failed", url: null, code: null, error: "the installer needs curl" } }));
    expect(screen.getByRole("alert")).toHaveTextContent("The installer did not finish.");
    expect(screen.getByRole("alert")).toHaveTextContent("the installer needs curl");
    // the manual way is open, inside the container
    expect(screen.getByText(/Run this inside the Yuo container/)).toHaveTextContent("docker compose exec yuo sh");
    expect(screen.getByText("curl -fsSL https://claude.ai/install.sh | bash")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try the installer again" })).toBeInTheDocument();
  });

  it("shows only the manual way for a program Yuo cannot install or sign in (Codex on Windows)", () => {
    const missing = view(codex());
    expect(screen.getByRole("heading", { name: "Codex is not installed yet" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Install Codex/ })).toBeNull();
    expect(screen.getByText("Run this in PowerShell on the computer that runs Yuo:")).toBeInTheDocument();
    expect(screen.getByText("npm install -g @openai/codex")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check again" })).toBeInTheDocument();
    missing.unmount();

    const signedOut = view(codex({ installed: true, logged_in: false, reason: "not_logged_in" }));
    expect(screen.getByRole("heading", { name: "Codex is installed, but not signed in" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Sign in to Codex/ })).toBeNull();
    expect(screen.getByText("codex login")).toBeInTheDocument();
    signedOut.unmount();

    // in a container the sign-in command is run from outside it
    const inContainer = view(codex({ installed: true, logged_in: false, container: true, os: "linux" }));
    expect(screen.getByText("docker compose exec yuo codex login")).toBeInTheDocument();
    inContainer.unmount();

    view(codex({ installed: true, logged_in: null, ready: true, reason: null }));
    expect(screen.getByRole("heading", { name: "Codex is installed" })).toBeInTheDocument();
    expect(screen.getByText(/Yuo could not confirm the sign-in; it will try/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check again" })).toBeInTheDocument();
  });

  it("shows a ready program with its version and plan, and nothing to do", () => {
    view(cliReady());
    expect(screen.getByRole("heading", { name: "Claude Code is installed and signed in" })).toBeInTheDocument();
    expect(screen.getByText("Version 2.1.0 · Max plan")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("waits for a browser sign-in on this computer and lets the learner cancel", async () => {
    const onCancelLogin = vi.fn();
    const user = userEvent.setup();
    const waiting = cliSignedOut({
      os: "windows",
      code_login: false,
      login: { state: "waiting_browser", url: null, code: null, error: null },
    });
    view(waiting, { onCancelLogin });
    expect(screen.getByText(/A browser window has opened on this computer/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel the sign-in" }));
    expect(onCancelLogin).toHaveBeenCalledTimes(1);
  });

  it("shows Codex's sign-in page and one-time code, and waits without asking for anything back", async () => {
    const onCancelLogin = vi.fn();
    const user = userEvent.setup();
    view(
      codex({
        installed: true,
        logged_in: false,
        reason: "not_logged_in",
        can_login: true,
        login: { state: "waiting_device", url: "https://auth.openai.com/codex/device", code: "FQ9C-SNGC4", error: null },
      }),
      { onCancelLogin },
    );

    expect(screen.getByRole("heading", { name: "Signing in to Codex" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open the sign-in page/ })).toHaveAttribute(
      "href",
      "https://auth.openai.com/codex/device",
    );
    expect(screen.getByLabelText("One-time code")).toHaveTextContent("FQ9C-SNGC4");
    expect(screen.getByText(/Waiting for you to finish on the sign-in page/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel the sign-in" }));
    expect(onCancelLogin).toHaveBeenCalledOnce();
  });

  it("copies a command, and selects it when the clipboard is not allowed", async () => {
    const user = userEvent.setup();
    view(codex());
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValueOnce(undefined);
    await user.click(screen.getByRole("button", { name: "Copy" }));
    expect(writeText).toHaveBeenCalledWith("npm install -g @openai/codex");
    expect(await screen.findByText("Copied.")).toBeInTheDocument();

    writeText.mockRejectedValueOnce(new Error("not allowed"));
    await user.click(screen.getByRole("button", { name: "Copy" }));
    expect(await screen.findByText(/The command is selected: copy it by hand/)).toBeInTheDocument();
    expect(window.getSelection()?.toString()).toBe("npm install -g @openai/codex");
  });
});

describe("a subscription program's card, with the server", () => {
  it("signs in with a link and a code, never shows the code again, and polls until signed in", async () => {
    const CODE = "oauth-code-7421#state";
    let status = cliSignedOut();
    const { calls } = mockApi({
      "GET /api/setup/cli/claude": () => {
        // the program takes the code, then says it is signed in (seen by the next poll)
        if (status.login.state === "running") status = cliReady({ login: { state: "done", url: null, code: null, error: null } });
        return json(status);
      },
      "POST /api/setup/cli/claude/login": () => {
        status = cliSignedOut({
          login: { state: "waiting_code", url: "https://claude.ai/oauth/authorize?x=1", code: null, error: null },
        });
        return json(status, 202);
      },
      "POST /api/setup/cli/claude/login/code": () => {
        status = cliSignedOut({ login: { state: "running", url: null, code: null, error: null } });
        return json(status);
      },
    });
    const log = vi.spyOn(console, "log");
    const user = userEvent.setup();
    live();

    await user.click(await screen.findByRole("button", { name: "Sign in to Claude Code" }));
    const link = await screen.findByRole("link", { name: "Open the Claude sign-in page (opens in a new tab)" });
    expect(link).toHaveAttribute("href", "https://claude.ai/oauth/authorize?x=1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");

    const send = screen.getByRole("button", { name: "Send the code" });
    expect(send).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Paste the code from that page" }), `  ${CODE} `);
    await user.click(send);

    expect(calls.find((c) => c.path === "/api/setup/cli/claude/login/code")?.body).toEqual({ code: CODE });
    expect(await screen.findByText("Checking the code…")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(CODE);
    expect(screen.queryByRole("textbox")).toBeNull();

    // no click: the card asks again by itself (every 2 s) until the program is signed in
    expect(
      await screen.findByRole("heading", { name: "Claude Code is installed and signed in" }, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(screen.getByText("Version 2.1.0 · Max plan")).toBeInTheDocument();
    expect(log.mock.calls.flat().join(" ")).not.toContain(CODE);
  }, 10_000);

  it("says when a code is refused or the sign-in fails, and lets the learner start again", async () => {
    let status = cliSignedOut({
      login: { state: "waiting_code", url: "https://claude.ai/oauth/authorize?x=1", code: null, error: null },
    });
    let started = 0;
    mockApi({
      "GET /api/setup/cli/claude": () => json(status),
      "POST /api/setup/cli/claude/login/code": () => {
        status = { ...status, login: { ...status.login, error: "that does not look like a sign-in code" } };
        return json(status);
      },
      "DELETE /api/setup/cli/claude/login": () => {
        status = cliSignedOut({ login: { state: "failed", url: null, code: null, error: "the sign-in took too long" } });
        return json(status);
      },
      "POST /api/setup/cli/claude/login": () => {
        started += 1;
        status = cliSignedOut({ login: { state: "running", url: null, code: null, error: null } });
        return json(status, 202);
      },
    });
    const user = userEvent.setup();
    live();

    await user.type(await screen.findByRole("textbox", { name: "Paste the code from that page" }), "nope");
    await user.click(screen.getByRole("button", { name: "Send the code" }));
    const refused = await screen.findByRole("alert");
    expect(refused).toHaveTextContent("That code did not work.");
    expect(screen.getByRole("textbox", { name: "Paste the code from that page" })).toHaveValue("");

    await user.click(screen.getByRole("button", { name: "Cancel the sign-in" }));
    const failed = await screen.findByText("The sign-in did not finish. You can start it again.");
    const alert = failed.closest("[role=alert]") as HTMLElement;
    expect(within(alert).getByText("the sign-in took too long")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sign in to Claude Code" }));
    expect(await screen.findByText("Starting the sign-in…")).toBeInTheDocument();
    expect(started).toBe(1);
  });

  it("installs the program, polls while the installer runs, and checks again with a fresh look", async () => {
    let status = cliStatus();
    const { calls } = mockApi({
      "GET /api/setup/cli/claude": () => {
        if (status.install.state === "running") {
          status = cliSignedOut({ install: { state: "done", url: null, code: null, error: null } });
        }
        return json(status);
      },
      "POST /api/setup/cli/claude/install": () => {
        status = cliStatus({ install: { state: "running", url: null, code: null, error: null } });
        return json(status, 202);
      },
    });
    const user = userEvent.setup();
    live();

    await user.click(await screen.findByRole("button", { name: "Install Claude Code" }));
    expect(await screen.findByText("Installing… this can take a minute.")).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Claude Code is installed, but not signed in" }, { timeout: 5000 }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Do it yourself" }));
    await user.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/setup/cli/claude?fresh=true")).toBe(true));
  }, 10_000);

  it("shows nothing when the server does not manage the programs (404)", async () => {
    const { calls } = mockApi({});
    const { container } = live();
    await waitFor(() => expect(calls).toHaveLength(1));
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
