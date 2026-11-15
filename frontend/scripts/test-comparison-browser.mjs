import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

// Run with tests.browser_auth_server and a Vite proxy to its disposable real API.
const origin = process.env.COMPARISON_BASE_URL || "http://localhost:5175";
const artifacts = process.env.COMPARISON_AUDIT_DIR || "/tmp/fieldshift-comparison-audit";
fs.mkdirSync(artifacts, { recursive: true });
const browser = await chromium.launch({ headless: true,
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
context.setDefaultTimeout(30_000);
const page = await context.newPage();
const results = [], errors = [], calls = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("response", (r) => { if (r.url().endsWith("/comparisons/saved-fields")) calls.push(r.status()); });
const endpoint = "**/v1/comparisons/saved-fields";
const update = () => page.getByRole("button", { name: "Update comparison", exact: true });
const table = () => page.getByRole("table", { name: "Comparison of selected fields" });
const rent = (letter) => page.getByLabel(new RegExp(`^${letter} · .* asking rent$`));
const response = () => page.waitForResponse((r) => r.url().endsWith("/comparisons/saved-fields"));
const returnRow = () => page.getByRole("row").filter({ has: page.getByRole("rowheader", { name: /^Return after rent, per acre/ }) });
async function step(name, action) {
  try { await action(); results.push({ name, status: "PASS" }); console.log(`PASS ${name}`); }
  catch (error) {
    await page.screenshot({ path: path.join(artifacts, `failure-${results.length + 1}.png`), fullPage: true });
    results.push({ name, status: "FAIL", error: error.message }); throw error;
  }
}
async function api(method, route, body) {
  return page.evaluate(async ({ method, route, body }) => {
    const url = performance.getEntriesByType("resource").find((e) => e.name.includes("/src/shared/api/access-token.ts"))?.name;
    const { getAccessToken } = await import(url);
    const r = await fetch(`/v1${route}`, { method, headers: { "Content-Type": "application/json", Authorization: `Bearer ${getAccessToken()}` },
      ...(body ? { body: JSON.stringify(body) } : {}) });
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  }, { method, route, body });
}
async function apply() {
  const pending = response(); await update().click(); const r = await pending;
  await update().waitFor(); return { status: r.status(), body: await r.json() };
}
async function compare() {
  const pending = response(); await page.getByRole("button", { name: "Compare fields", exact: true }).click();
  const r = await pending; assert.equal(r.status(), 200); await table().waitFor(); return r.json();
}
async function noOverflow() {
  const size = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }));
  assert(size.scroll <= size.width, `Page overflows: ${JSON.stringify(size)}`);
}
try {
  await step("Anonymous entry requires sign-in", async () => {
    await page.goto(origin + "/my-fields"); await page.getByRole("heading", { name: "Sign in to see your fields" }).waitFor();
  });
  await step("Sign up, resolve two locations and save fields through UI", async () => {
    await page.goto(origin + "/sign-up");
    await page.getByLabel("Email", { exact: true }).fill(`comparison-browser-${Date.now()}@example.com`);
    await page.getByLabel("Password", { exact: true }).fill("ComparisonBrowser123");
    await page.getByRole("checkbox").check(); await page.getByRole("button", { name: "Create account", exact: true }).click();
    await page.getByText("Account created.", { exact: false }).waitFor();
    for (const point of ["41.60, -93.60", "41.60, -93.582"]) {
      await page.goto(origin + "/pick-field");
      await page.getByRole("button", { name: "Link or coordinates", exact: true }).click();
      await page.getByLabel("Google Maps link, Apple Maps link or coordinates", { exact: true }).fill(point);
      await page.getByRole("button", { name: "Save field", exact: true }).click();
      await page.getByRole("button", { name: "Saved", exact: true }).waitFor();
    }
    const saved = await api("GET", "/me/fields"); assert.equal(saved.status, 200);
    assert.equal(saved.body.items.length, 2); assert(saved.body.items.every((f) => f.field_id));
  });
  await step("Select two fields and compare via real API with budget details", async () => {
    await page.goto(origin + "/my-fields");
    await page.getByRole("checkbox").nth(0).waitFor();
    assert(await page.getByRole("button", { name: "Compare fields", exact: true }).isDisabled());
    await page.getByRole("checkbox").nth(0).check();
    assert(await page.getByRole("button", { name: "Compare fields", exact: true }).isDisabled());
    await page.getByRole("checkbox").nth(1).check();
    const body = await compare(); assert.equal(body.fields.length, 2); assert.equal(body.rows.length, 18); assert(body.warnings.length);
    await page.getByText("How is this calculated?", { exact: true }).first().click();
    await page.getByRole("region", { name: "Rough rotation budget" }).first().waitFor(); await noOverflow();
    await page.screenshot({ path: path.join(artifacts, "desktop-budget.png"), fullPage: true });
    await page.getByText("How is this calculated?", { exact: true }).first().click();
  });
  await step("Changing rents changes returns and reverses winner", async () => {
    await rent("A").fill("100"); await rent("B").fill("400"); const first = await apply(); assert.equal(first.status, 200);
    assert.deepEqual(first.body.best.net_return, [first.body.fields[0].saved_field_id]);
    await rent("A").fill("400"); await rent("B").fill("100"); const next = await apply(); assert.equal(next.status, 200);
    assert.deepEqual(next.body.best.net_return, [next.body.fields[1].saved_field_id]);
    assert.equal(next.body.fields[0].net_return_per_acre.base - first.body.fields[0].net_return_per_acre.base, -300);
    await returnRow().getByRole("cell").nth(1).getByText("Best", { exact: true }).waitFor();
  });
  await step("Zero rent works; invalid negative rent sends no request", async () => {
    await rent("A").fill("0"); assert.equal((await apply()).body.fields[0].rent.per_acre, 0);
    const count = calls.length; await rent("A").fill("-1"); await update().click();
    await page.getByRole("alert").filter({ hasText: "Enter rents from $0 to $5,000" }).waitFor(); assert.equal(calls.length, count);
    await rent("A").fill("0"); await apply();
  });
  await step("Failed update retains results and retries", async () => {
    await page.route(endpoint, (r) => r.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "INTERNAL_ERROR", message: "Test outage." } }) }));
    assert.equal((await apply()).status, 503);
    await page.getByText("Showing the previous comparison. The latest update failed.", { exact: true }).waitFor(); assert(await table().isVisible());
    await page.unroute(endpoint); const pending = response(); await page.getByRole("button", { name: "Try again", exact: true }).click();
    assert.equal((await pending).status(), 200); await update().waitFor(); assert.equal(await page.getByRole("alert").count(), 0);
  });
  await step("Rate limit cooldown blocks requests and recovers after reconnect", async () => {
    await page.route(endpoint, (r) => r.fulfill({ status: 429, headers: { "Retry-After": "2" }, contentType: "application/json", body: JSON.stringify({ error: { code: "RATE_LIMITED", message: "Slow down." } }) }));
    assert.equal((await apply()).status, 429); await page.getByText(/Try again in 2 seconds/).waitFor();
    assert(await page.getByRole("button", { name: "Try again", exact: true }).isDisabled());
    const count = calls.length; await page.evaluate(() => { dispatchEvent(new Event("offline")); dispatchEvent(new Event("online")); });
    await page.unroute(endpoint); await page.getByRole("button", { name: "Try again", exact: true }).click();
    const ready = await apply(); assert.equal(ready.status, 200); assert.equal(calls.length, count + 2);
    assert(await update().isEnabled());
  });
  await step("Shared plan and horizon update; missing wheat budget stays unavailable", async () => {
    await page.getByLabel("Shared crop rotation").selectOption("winter_wheat"); await page.getByLabel("Budget horizon").selectOption("3");
    const result = await apply(); assert.equal(result.status, 200); assert.deepEqual(result.body.plan, { rotation: ["winter_wheat"], horizon_years: 3 });
    assert(result.body.fields.every((f) => f.net_return_per_acre === null));
    assert.equal(await returnRow().getByText("Not available", { exact: true }).count(), 2);
    await page.getByLabel("Shared crop rotation").selectOption("corn,soybean"); await page.getByLabel("Budget horizon").selectOption("2");
    const count = calls.length; await update().click();
    await page.getByText("How is this calculated?", { exact: true }).first().waitFor();
    assert.equal(calls.length, count); // Previously requested settings restore their cached response.
  });
  await step("Phone shows both fields, contains budget details and opens field", async () => {
    await page.setViewportSize({ width: 390, height: 844 }); await noOverflow(); await returnRow().scrollIntoViewIfNeeded();
    for (const cell of await returnRow().getByRole("cell").all()) { const b = await cell.boundingBox(); assert(b.x >= 0 && b.x + b.width <= 390); }
    await page.screenshot({ path: path.join(artifacts, "mobile-two-fields.png"), fullPage: true });
    await page.getByText("How is this calculated?", { exact: true }).first().click();
    await page.getByText("Yearly figures, assumptions and sources", { exact: true }).first().click(); await noOverflow();
    await page.getByRole("link", { name: "Open field A", exact: true }).click(); await page.waitForURL("**/field?*");
  });
  await step("Four fields, point limitations, selection cap and responsive widths", async () => {
    for (let i = 0; i < 3; i++) {
      const r = await api("POST", "/me/fields", { name: `Screening point ${i + 1}`, geometry: { type: "Point", coordinates: [-93.7 + i * 0.02, 41.98] } }); assert.equal(r.status, 201);
    }
    await page.goto(origin + "/my-fields"); const boxes = page.getByRole("checkbox"); await boxes.nth(4).waitFor();
    for (let i = 0; i < 4; i++) await boxes.nth(i).check(); assert(await boxes.nth(4).isDisabled());
    const body = await compare(); assert.equal(body.fields.length, 4); assert(body.fields.some((f) => f.boundary_type === "buffered_point" && f.net_return_field === null));
    for (const width of [1440, 1024, 760, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 }); await noOverflow();
      if (width <= 760) for (const cell of await returnRow().getByRole("cell").all()) { const b = await cell.boundingBox(); assert(b.x >= 0 && b.x + b.width <= width); }
      if ([1440, 390].includes(width)) await page.screenshot({ path: path.join(artifacts, `${width === 1440 ? "desktop" : "mobile"}-four-fields.png`), fullPage: true });
    }
  });
  assert.deepEqual(errors, [], "Uncaught browser errors");
} finally {
  fs.writeFileSync(path.join(artifacts, "browser-results.json"), JSON.stringify({ results, errors, comparisonStatuses: calls }, null, 2));
  await browser.close();
}
console.log(`${results.length} comparison browser checks passed. Artifacts: ${artifacts}`);
