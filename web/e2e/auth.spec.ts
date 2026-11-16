// Sign-in across devices through the real backend: first-run setup with a passkey on a
// virtual authenticator (Chromium DevTools WebAuthn), the passkey on a second device, the devices page,
// revoking a device, the password and a recovery code. Runs first (file name order): it enrols the
// install through the screens, so these tests use the plain Playwright `test` (no signed-in fixture).
import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { setupCode } from "./fixtures";

test.describe.configure({ mode: "serial" });

type VirtualCredential = {
  credentialId: string;
  isResidentCredential: boolean;
  rpId?: string;
  privateKey: string;
  userHandle?: string;
  signCount: number;
};

/** A platform authenticator with a resident key and user verification, answering prompts by itself. */
async function authenticator(context: BrowserContext, page: Page) {
  const cdp = await context.newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  const { authenticatorId } = await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: {
      protocol: "ctap2",
      transport: "internal",
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  });
  return {
    async credentials(): Promise<VirtualCredential[]> {
      return (await cdp.send("WebAuthn.getCredentials", { authenticatorId })).credentials as VirtualCredential[];
    },
    async add(credential: VirtualCredential): Promise<void> {
      await cdp.send("WebAuthn.addCredential", { authenticatorId, credential });
    },
  };
}

let recoveryCodes: string[] = [];
let passkey: VirtualCredential | null = null;
const PASSWORD = "a long and boring passphrase";

test("first run: setup code, passkey, recovery codes", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  const auth = await authenticator(context, page);

  await page.goto("/");
  await expect(page).toHaveURL(/\/setup$/);
  await expect(page.getByRole("heading", { level: 1, name: "Welcome to Yuo" })).toBeVisible();
  // signed out: no navigation, so no "More" menu with "Sign out" in it
  await expect(page.getByRole("button", { name: "More", exact: true })).toHaveCount(0);
  await page.getByRole("textbox", { name: "Setup code" }).fill((await setupCode()).toLowerCase().replaceAll("-", " "));
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByRole("heading", { name: "Add a passkey" })).toBeVisible();
  await page.getByRole("button", { name: "Add a passkey" }).click();
  const list = page.getByRole("list", { name: "Recovery codes" });
  await expect(list.getByRole("listitem")).toHaveCount(10);
  recoveryCodes = await list.getByRole("listitem").allTextContents();
  expect(recoveryCodes[0]).toMatch(/^[A-Z2-9]{5}-[A-Z2-9]{5}$/);
  const [stored] = await auth.credentials();
  expect(stored?.isResidentCredential).toBe(true);
  passkey = stored!;

  await expect(page.getByRole("button", { name: "Continue to Yuo" })).toBeDisabled();
  await page.getByText("I saved these codes").click();
  await page.getByRole("button", { name: "Continue to Yuo" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Your paths" })).toBeVisible();
  await page.getByRole("button", { name: "More", exact: true }).click();
  await expect(page.getByRole("menuitem", { name: "Sign out" })).toBeVisible();
  await context.close();
});

test("a second device signs in with the passkey, sees both devices and signs the other out", async ({ browser }) => {
  // device A: signed in with the passkey on its own authenticator
  const a = await browser.newContext();
  const pageA = await a.newPage();
  const authA = await authenticator(a, pageA);
  await authA.add(passkey!);
  await pageA.goto("/settings");
  await expect(pageA).toHaveURL(/\/sign-in\?next=%2Fsettings$/);
  await pageA.getByRole("button", { name: "Sign in with a passkey" }).click();
  await expect(pageA).toHaveURL(/\/settings$/);
  await expect(pageA.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();

  // device B: a fresh browser with the same passkey (synced, as a passkey manager does; copied with
  // A's signature counter, which the server checks only goes up)
  const b = await browser.newContext({ userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36" });
  const pageB = await b.newPage();
  await (await authenticator(b, pageB)).add((await authA.credentials())[0]!);
  await pageB.goto("/");
  await expect(pageB).toHaveURL(/\/sign-in$/);
  await pageB.getByRole("button", { name: "Sign in with a passkey" }).click();
  await expect(pageB.getByRole("heading", { level: 1, name: "Your paths" })).toBeVisible();

  await pageB.goto("/settings/devices");
  const devices = pageB.getByRole("region", { name: "Devices" });
  const items = devices.getByRole("listitem");
  // the first-run browser, device A and this one
  await expect(items).toHaveCount(3);
  const mine = items.filter({ hasText: "This device" });
  await expect(mine).toHaveCount(1);
  await expect(mine).toContainText("Chrome on Android");

  // sign device A out (the most recently active other device, listed first after this one)
  const other = items.filter({ hasNotText: "This device" }).first();
  const label = (await other.locator("strong").textContent())!;
  await other.getByRole("button", { name: `Sign out ${label}` }).click();
  await other.getByRole("button", { name: `Yes, sign out ${label}` }).click();
  await expect(devices.getByText(`${label} was signed out.`)).toBeVisible();
  await expect(items).toHaveCount(2);

  // device A's next request finds its session gone and goes to sign-in
  await pageA.getByRole("link", { name: "Yuo" }).click();
  await expect(pageA).toHaveURL(/\/sign-in/);
  await expect(pageA.getByRole("heading", { level: 1, name: "Sign in to Yuo" })).toBeVisible();

  // B sets a password for the next test, then signs out
  await pageB.getByRole("button", { name: "Set a password" }).click();
  await pageB.getByLabel("New password").fill(PASSWORD);
  await pageB.getByLabel("The same password again").fill(PASSWORD);
  await pageB.getByRole("button", { name: "Save the password" }).click();
  await expect(pageB.getByText("Password saved.")).toBeVisible();
  await expect(pageB.getByRole("region", { name: "Ways to sign in" }).getByRole("listitem")).toHaveCount(2);
  await pageB.getByRole("button", { name: "More", exact: true }).click();
  await pageB.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(pageB).toHaveURL(/\/sign-in/);
  await a.close();
  await b.close();
});

test("sign in with the password, and with a recovery code", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Use password" }).click();
  await page.getByLabel("Password").fill("not the password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByText("Wrong password.")).toBeVisible();
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Your paths" })).toBeVisible();
  await context.close();

  const other = await browser.newContext();
  const page2 = await other.newPage();
  await page2.setViewportSize({ width: 360, height: 740 });
  await page2.goto("/settings/devices");
  await expect(page2).toHaveURL(/\/sign-in\?next=/);
  const [scroll, width] = await page2.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(scroll, "the sign-in page fits a phone").toBeLessThanOrEqual(width);
  await page2.getByRole("button", { name: "Use a recovery code" }).click();
  await page2.getByRole("textbox", { name: "Recovery code" }).fill(recoveryCodes[0]!.toLowerCase());
  await page2.getByRole("button", { name: "Sign in with the code" }).click();
  await expect(page2).toHaveURL(/\/settings\/devices$/);
  await expect(page2.getByText("9 recovery codes left.")).toBeVisible();
  // a used code does not work again
  await page2.getByRole("button", { name: "Sign out of this device" }).click();
  await expect(page2).toHaveURL(/\/sign-in/);
  await page2.getByRole("button", { name: "Use a recovery code" }).click();
  await page2.getByRole("textbox", { name: "Recovery code" }).fill(recoveryCodes[0]!);
  await page2.getByRole("button", { name: "Sign in with the code" }).click();
  await expect(page2.getByText("That recovery code is not valid or was already used.")).toBeVisible();
  await other.close();
});
