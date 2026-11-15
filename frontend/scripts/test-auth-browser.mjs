import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

// Run against real local services. Password recovery uses tests/browser_auth_server.py's mail capture.
const origin = process.env.AUTH_BASE_URL || "http://localhost:5173";
const apiOrigin = process.env.AUTH_API_BASE_URL || "http://localhost:8000/v1";
const artifacts = process.env.AUTH_AUDIT_DIR || "/tmp/fieldshift-auth-audit";
const mailFile = process.env.AUTH_MAIL_CAPTURE_PATH;
fs.mkdirSync(artifacts, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
});
const results = [];
let serial = 0;
const password = "BrowserAuditPassword123";
const replacement = "BrowserReplacement456";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const newEmail = () => `auth-browser-${Date.now()}-${++serial}@example.com`;

async function until(predicate) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await predicate()) return;
    await sleep(50);
  }
  throw new Error("Timed out waiting for condition");
}

async function test(name, operation, mobile = false) {
  const context = await browser.newContext({
    viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 },
    isMobile: mobile,
    hasTouch: mobile,
  });
  const page = await context.newPage();
  context.setDefaultTimeout(8_000);
  const errors = [];
  context.on("page", (tab) => tab.on("pageerror", (error) => errors.push(error.message)));
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    await operation(context, page);
    assert.deepEqual(errors, [], "Uncaught browser errors");
    results.push({ name, status: "PASS" });
    console.log(`PASS ${name}`);
  } catch (error) {
    const screenshot = `failure-${results.length + 1}.png`;
    await page.screenshot({ path: path.join(artifacts, screenshot), fullPage: true }).catch(() => {});
    results.push({ name, status: "FAIL", error: error.message, errors, screenshot });
    console.error(`FAIL ${name}: ${error.message}`);
  } finally {
    await context.close();
  }
}

const text = (page, value) => page.getByText(value, { exact: false }).first().waitFor();
async function go(page, route) {
  await page.goto(origin + route);
  await page.waitForFunction(() => !document.body.innerText.includes("Checking your session"));
}
async function fill(page, email, pw = password) {
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(pw);
}
async function login(page, email, pw = password) {
  await fill(page, email, pw);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}
async function signup(page, email = newEmail()) {
  await go(page, "/sign-up");
  await fill(page, email);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await text(page, "Account created.");
  await go(page, "/my-fields");
  return email;
}
async function account(page) {
  if (["/sign-up", "/sign-in", "/reset-password"].includes(new URL(page.url()).pathname)) await go(page, "/my-fields");
  if (await page.getByRole("button", { name: "Menu", exact: true }).isVisible()) {
    if (!(await page.getByRole("button", { name: "Account", exact: true }).isVisible())) {
      await page.getByRole("button", { name: "Menu", exact: true }).click();
    }
  }
  await page.getByRole("button", { name: "Account", exact: true }).click();
}
async function logout(page) {
  await account(page);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.waitForURL(origin + "/");
}
async function session(page) {
  return page.evaluate(async () => {
    // Vite may include an HMR timestamp. Import the module already used by the app.
    const url = performance.getEntriesByType("resource").find((entry) =>
      entry.name.includes("/src/entities/session/model/session.ts"))?.name;
    return (await import(url)).getSession();
  });
}
async function restore(page) {
  await page.evaluate(() => {
    const url = performance.getEntriesByType("resource").find((entry) =>
      entry.name.includes("/src/entities/session/model/session.ts"))?.name;
    void import(url).then((module) => module.restoreSession());
  });
}
async function resetFields(page, pw = replacement, confirmation = pw) {
  await page.getByLabel("New password", { exact: true }).fill(pw);
  await page.getByLabel("Repeat the new password", { exact: true }).fill(confirmation);
}
const savePassword = (page) => page.getByRole("button", { name: "Save new password", exact: true }).click();
function capturedMail(email) {
  return fs.existsSync(mailFile) ? fs.readFileSync(mailFile, "utf8").trim().split("\n")
    .filter(Boolean).map((line) => JSON.parse(line)).filter((message) => message.email === email) : [];
}

await test("Anonymous protected routes require sign-in", async (_, page) => {
  await go(page, "/my-fields");
  await text(page, "Sign in to see your fields");
  await go(page, "/account/password");
  await text(page, "Sign in first to change your password");
});
await test("Empty and malformed login inputs stay in the form", async (_, page) => {
  await go(page, "/sign-in");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await text(page, "Enter your email.");
  await text(page, "Enter your password.");
  await fill(page, "bad@", "short");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await text(page, "Enter an email like name@example.com.");
});
await test("Signup enforces password rules and agreement", async (_, page) => {
  await go(page, "/sign-up");
  await fill(page, "bad@", "short");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await text(page, "Your password does not meet the rules");
  await text(page, "Agree to the terms");
});
await test("Signup sets an HttpOnly scoped cookie and keeps tokens out of storage", async (context, page) => {
  await signup(page);
  const cookie = (await context.cookies()).find((item) => item.name === "refresh_token");
  assert(cookie?.httpOnly && cookie.path === "/v1/auth" && cookie.sameSite === "Lax");
  const storage = await page.evaluate(() => ({
    cookie: document.cookie, local: { ...localStorage }, tab: { ...sessionStorage },
  }));
  assert(!JSON.stringify(storage).includes(cookie.value));
  assert(!JSON.stringify(storage).includes("access_token"));
});
await test("Duplicate registration ignores email casing", async (_, page) => {
  const email = await signup(page);
  await logout(page);
  await go(page, "/sign-up");
  await fill(page, email.toUpperCase());
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await text(page, "An account with this email already exists");
});
await test("Wrong password and unknown account use the same error", async (_, page) => {
  const email = await signup(page);
  await logout(page);
  await go(page, "/sign-in");
  await login(page, email, "WrongPassword123");
  await text(page, "do not match an account");
  await login(page, newEmail());
  await text(page, "do not match an account");
});
await test("Login trims email, ignores casing, and returns to the protected route", async (_, page) => {
  const email = await signup(page);
  await logout(page);
  await go(page, "/sign-in?next=%2Fmy-fields");
  await login(page, `  ${email.toUpperCase()}  `);
  await page.waitForURL(origin + "/my-fields");
  await text(page, "Saved fields");
});
await test("Signup preserves the return route through both auth forms", async (_, page) => {
  await go(page, "/my-fields");
  await text(page, "Sign in to see your fields");
  await page.getByRole("link", { name: "Sign in", exact: true }).last().click();
  await page.getByRole("link", { name: "Create an account", exact: true }).click();
  await page.waitForURL("**/sign-up?next=*");
  await page.getByRole("button", { name: "Create account", exact: true }).waitFor();
  await page.getByRole("link", { name: "Sign in", exact: true }).last().click();
  await page.waitForURL("**/sign-in?next=*");
  await page.getByRole("link", { name: "Create an account", exact: true }).click();
  await fill(page, newEmail());
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await page.waitForURL(origin + "/my-fields");
});
for (const next of ["https://example.com", "//example.com", "/\\example.com"]) {
  await test(`Unsafe return target rejected: ${next}`, async (_, page) => {
    const email = await signup(page);
    await logout(page);
    await go(page, `/sign-in?next=${encodeURIComponent(next)}`);
    await login(page, email);
    await text(page, "Signed in as");
    assert.equal(new URL(page.url()).pathname, "/sign-in");
  });
}
await test("Reload and remembered new tab restore the session", async (context, page) => {
  await signup(page);
  await page.reload();
  await page.getByRole("button", { name: "Account", exact: true }).waitFor();
  const other = await context.newPage();
  await other.goto(origin + "/my-fields");
  await other.getByRole("button", { name: "Account", exact: true }).waitFor();
});
await test("Concurrent tabs can rotate the same refresh cookie safely", async (context, page) => {
  await signup(page);
  const tabs = await Promise.all([context.newPage(), context.newPage(), context.newPage()]);
  await Promise.all(tabs.map((tab) => tab.goto(origin + "/my-fields")));
  await Promise.all(tabs.map((tab) => tab.getByRole("button", { name: "Account", exact: true }).waitFor()));
});
await test("Scheduled refresh rotates the cookie before access-token expiry", async (context, page) => {
  await page.clock.install();
  await signup(page);
  const old = (await context.cookies()).find((cookie) => cookie.name === "refresh_token");
  await page.clock.fastForward(841_000);
  await until(async () => (await context.cookies()).find((cookie) => cookie.name === "refresh_token")?.value !== old.value);
  await page.getByRole("button", { name: "Account", exact: true }).waitFor();
});
await test("Refresh rotation rejects replay of the old cookie", async (context, page) => {
  await signup(page);
  const old = (await context.cookies()).find((cookie) => cookie.name === "refresh_token");
  const status = await page.evaluate(async (base) => (await fetch(`${base}/auth/refresh`, {
    method: "POST", credentials: "include",
  })).status, apiOrigin);
  assert.equal(status, 200);
  assert.notEqual((await context.cookies()).find((cookie) => cookie.name === "refresh_token").value, old.value);
  const other = await browser.newContext();
  try {
    const tab = await other.newPage();
    await go(tab, "/sign-in");
    await other.addCookies([old]);
    const replay = await tab.evaluate(async (base) => (await fetch(`${base}/auth/refresh`, {
      method: "POST", credentials: "include",
    })).status, apiOrigin);
    assert.equal(replay, 401);
  } finally { await other.close(); }
});
await test("Invalid refresh cookie restores an anonymous session", async (context, page) => {
  await context.addCookies([{ name: "refresh_token", value: "invalid-audit-cookie", domain: "localhost", path: "/v1/auth", httpOnly: true }]);
  await go(page, "/my-fields");
  await text(page, "Sign in to see your fields");
});
await test("Logout clears the cookie and protected access after reload", async (context, page) => {
  await signup(page);
  await logout(page);
  assert(!(await context.cookies()).some((cookie) => cookie.name === "refresh_token"));
  await go(page, "/my-fields");
  await text(page, "Sign in to see your fields");
  await page.reload();
  await text(page, "Sign in to see your fields");
});
await test("Nonremembered sessions survive reload but stay off in new tabs", async (context, page) => {
  const email = await signup(page);
  await logout(page);
  await go(page, "/sign-in");
  await page.getByRole("checkbox").uncheck();
  await login(page, email);
  await text(page, "Signed in as");
  await go(page, "/my-fields");
  await page.reload();
  await page.getByRole("button", { name: "Account", exact: true }).waitFor();
  for (let attempt = 0; attempt < 2; attempt++) {
    const tab = await context.newPage();
    await tab.goto(origin + "/my-fields");
    await text(tab, "Sign in to see your fields");
    assert.equal(await tab.evaluate(() => localStorage.getItem("fieldline.remember")), "0");
    await tab.close();
    await restore(page);
    await until(async () => (await session(page)).status === "authenticated");
    assert((await context.cookies()).some((cookie) => cookie.name === "refresh_token"));
  }
});
await test("A delayed startup failure cannot overwrite signup", async (_, page) => {
  let release;
  await page.route("**/auth/refresh", async (route) => {
    await new Promise((resolve) => { release = resolve; });
    await route.fulfill({ status: 401, contentType: "application/json", body: '{"error":{"code":"UNAUTHORIZED"}}' });
  });
  await go(page, "/sign-up");
  await until(() => release);
  await fill(page, newEmail());
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  release();
  await text(page, "Account created.");
  assert.equal((await session(page)).status, "authenticated");
});
await test("A delayed refresh cannot undo logout or leave its cookie", async (context, page) => {
  await signup(page);
  let release;
  await page.route("**/auth/refresh", async (route) => {
    const response = await route.fetch();
    await new Promise((resolve) => { release = resolve; });
    await route.fulfill({ response });
  });
  await restore(page);
  await until(() => release);
  await account(page);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  release();
  await page.waitForURL(origin + "/");
  assert.equal((await session(page)).status, "anonymous");
  assert(!(await context.cookies()).some((cookie) => cookie.name === "refresh_token"));
});
await test("Failed logout shows an error and supports successful retry", async (_, page) => {
  await signup(page);
  await page.route("**/auth/logout", (route) => route.abort("failed"));
  await account(page);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.getByRole("alert").waitFor();
  assert.equal((await session(page)).status, "authenticated");
  await page.unroute("**/auth/logout");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.waitForURL(origin + "/");
});
for (const status of [429, 503]) {
  await test(`Login handles HTTP ${status} and allows retry`, async (_, page) => {
    const email = await signup(page);
    await logout(page);
    await go(page, "/sign-in");
    await page.route("**/auth/login", (route) => route.fulfill({
      status, headers: { "Retry-After": "1" }, contentType: "application/json",
      body: JSON.stringify({ error: { code: status === 429 ? "RATE_LIMITED" : "UPSTREAM_DATA_UNAVAILABLE", message: "Try later." } }),
    }));
    await login(page, email);
    await page.getByRole("alert").waitFor();
    await page.unroute("**/auth/login");
    await login(page, email);
    await text(page, "Signed in as");
  });
}
await test("Offline login keeps the form usable for retry", async (_, page) => {
  const email = await signup(page);
  await logout(page);
  await go(page, "/sign-in");
  await page.route("**/auth/login", (route) => route.abort("failed"));
  await login(page, email);
  await text(page, "We couldn't reach our server.");
  await page.unroute("**/auth/login");
  await login(page, email);
  await text(page, "Signed in as");
});
await test("Change password checks confirmation, rejects wrong current, revokes sessions", async (context, page) => {
  const email = await signup(page);
  const other = await browser.newContext();
  try {
    const tab = await other.newPage();
    await go(tab, "/sign-in");
    await login(tab, email);
    await text(tab, "Signed in as");
    await go(page, "/account/password");
    await page.getByLabel("Current password", { exact: true }).fill("WrongPassword123");
    await resetFields(page, replacement, "Mismatch123");
    await page.getByRole("button", { name: "Change password", exact: true }).click();
    await text(page, "The two passwords do not match.");
    await resetFields(page);
    await page.getByRole("button", { name: "Change password", exact: true }).click();
    await text(page, "Your current password is not right.");
    await page.getByLabel("Current password", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Change password", exact: true }).click();
    await text(page, "Your password was changed.");
    assert(!(await context.cookies()).some((cookie) => cookie.name === "refresh_token"));
    await go(tab, "/my-fields");
    await text(tab, "Sign in to see your fields");
    await tab.reload();
    await text(tab, "Sign in to see your fields");
    await go(page, "/sign-in");
    await login(page, email);
    await text(page, "do not match an account");
    await login(page, email, replacement);
    await text(page, "Signed in as");
  } finally { await other.close(); }
});
await test("Invalid reset link is removed from the URL and rejected helpfully", async (_, page) => {
  await go(page, "/reset-password?token=invalid-audit-token");
  await text(page, "Choose a new password");
  await until(() => !page.url().includes("token="));
  await resetFields(page);
  await savePassword(page);
  await text(page, "This reset link is invalid or expired");
});
await test("Password visibility controls work on login and reset", async (_, page) => {
  await go(page, "/sign-in");
  const pw = page.getByLabel("Password", { exact: true });
  await pw.fill(password);
  await page.getByRole("button", { name: "Show password", exact: true }).click();
  assert.equal(await pw.getAttribute("type"), "text");
  assert.equal(await page.getByRole("button", { name: "Show password", exact: true }).getAttribute("aria-pressed"), "true");
  await page.getByRole("button", { name: "Show password", exact: true }).click();
  assert.equal(await pw.getAttribute("type"), "password");
  await go(page, "/reset-password?token=invalid");
  await page.getByRole("button", { name: "Show password", exact: true }).click();
  assert.equal(await page.getByLabel("Repeat the new password", { exact: true }).getAttribute("type"), "text");
});
if (mailFile) {
  await test("Recovery uses generic confirmation, delivers a link, resets once, revokes other sessions", async (_, page) => {
    const email = await signup(page);
    const other = await browser.newContext();
    try {
      const tab = await other.newPage();
      await go(tab, "/sign-in");
      await login(tab, email);
      await text(tab, "Signed in as");
      await go(page, "/reset-password");
      await page.getByLabel("Email", { exact: true }).fill(email);
      await page.getByRole("button", { name: "Send reset link", exact: true }).click();
      await text(page, "Check your email");
      await until(() => capturedMail(email).length === 1);
      const link = capturedMail(email)[0].url;
      await page.goto(link);
      await text(page, "Choose a new password");
      await until(() => !page.url().includes("token="));
      await resetFields(page, replacement, "Mismatch123");
      await savePassword(page);
      await text(page, "The two passwords do not match.");
      await resetFields(page);
      await savePassword(page);
      await text(page, "Your password was changed.");
      await go(tab, "/my-fields");
      await text(tab, "Sign in to see your fields");
      await tab.reload();
      await text(tab, "Sign in to see your fields");
      await go(page, "/sign-in");
      await login(page, email);
      await text(page, "do not match an account");
      await login(page, email, replacement);
      await text(page, "Signed in as");
      await page.goto(link);
      await resetFields(page);
      await savePassword(page);
      await text(page, "This reset link is invalid or expired");
    } finally { await other.close(); }
  });
  await test("Unknown recovery account gets generic confirmation without mail", async (_, page) => {
    const email = newEmail();
    await go(page, "/reset-password");
    await page.getByLabel("Email", { exact: true }).fill(email);
    await page.getByRole("button", { name: "Send reset link", exact: true }).click();
    await text(page, "Check your email");
    await sleep(200);
    assert.equal(capturedMail(email).length, 0);
  });
} else if (process.env.AUTH_EXPECT_RESET_UNAVAILABLE === "1") {
  await test("Missing SMTP configuration shows a retryable recovery error", async (_, page) => {
    await go(page, "/reset-password");
    await page.getByLabel("Email", { exact: true }).fill(newEmail());
    await page.getByRole("button", { name: "Send reset link", exact: true }).click();
    await text(page, "Password reset email is unavailable.");
  });
}
await test("Mobile signup, reload, account menu, password form, and logout", async (context, page) => {
  await signup(page);
  await page.reload();
  await account(page);
  await page.getByRole("link", { name: "Change password", exact: true }).click();
  await text(page, "Enter your current password");
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: path.join(artifacts, "mobile-change-password.png"), fullPage: true });
  await logout(page);
  assert(!(await context.cookies()).some((cookie) => cookie.name === "refresh_token"));
}, true);
await test("Mobile sign-in and reset forms fit the viewport", async (_, page) => {
  await go(page, "/sign-in");
  await page.screenshot({ path: path.join(artifacts, "mobile-sign-in.png"), fullPage: true });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.getByRole("link", { name: "Forgot password?", exact: true }).click();
  await page.getByRole("button", { name: "Send reset link", exact: true }).click();
  await text(page, "Enter your email.");
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
}, true);

const report = { origin, apiOrigin, browser: `Chromium ${browser.version()}`, results };
await browser.close();
fs.writeFileSync(path.join(artifacts, "browser-results.json"), JSON.stringify(report, null, 2));
console.log(`${results.filter((result) => result.status === "PASS").length}/${results.length} passed`);
if (results.some((result) => result.status === "FAIL")) process.exitCode = 1;
