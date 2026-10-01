const { chromium } = require("playwright-core");
const path = require("path");
const fs = require("fs");

const SCREENSHOT_DIR = path.resolve(__dirname, "../../docs/screenshots");

async function runMapAudit() {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }

  console.log("==================================================");
  console.log("STARTING LIVE MAP OPERATIONAL PLAYWRIGHT AUDIT");
  console.log("==================================================");

  const browser = await chromium.launch({
    channel: "msedge",
    headless: true,
  });

  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });

  await context.addInitScript(() => {
    try {
      Object.defineProperty(document, 'fonts', {
        get() {
          return {
            ready: Promise.resolve(),
            status: 'loaded',
            check: () => true,
            load: () => Promise.resolve([]),
            addEventListener: () => {},
            removeEventListener: () => {},
          };
        },
        configurable: true,
      });
    } catch (e) {}
  });

  const page = await context.newPage();

  // Track network requests and console errors
  const interceptedRequests = [];
  const consoleErrors = [];
  const leakedSecretsFound = [];

  const SENSITIVE_KEYWORDS = [
    process.env.GOOGLE_MAPS_API_KEY,
    process.env.AISSTREAM_API_KEY,
    process.env.OPENWEATHER_API_KEY,
  ].filter((s) => Boolean(s && s.length >= 8));

  page.on("request", (req) => {
    const url = req.url();
    interceptedRequests.push(url);
    for (const secret of SENSITIVE_KEYWORDS) {
      if (url.includes(secret)) {
        leakedSecretsFound.push({ url, secret: "[DETECTED_IN_URL]" });
      }
    }
  });

  page.on("console", (msg) => {
    const text = msg.text();
    if (msg.type() === "error") {
      consoleErrors.push(text);
    }
    for (const secret of SENSITIVE_KEYWORDS) {
      if (text.includes(secret)) {
        leakedSecretsFound.push({ context: "console", secret: "[DETECTED_IN_CONSOLE]" });
      }
    }
  });

  const results = {
    mapLoaded: false,
    initialDataReceived: false,
    providersHealthReceived: false,
    wsConnected: false,
    vesselsRendered: 0,
    activeTransponders: 0,
    leakedSecrets: 0,
    screenshots: [],
    timings: {},
  };

  let cdpSession = null;
  async function takeScreenshot(filename, caption) {
    if (!cdpSession) {
      cdpSession = await page.context().newCDPSession(page);
    }
    const filePath = path.join(SCREENSHOT_DIR, filename);
    const { data } = await cdpSession.send("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(filePath, Buffer.from(data, "base64"));
    console.log(`[SNAPSHOT] Saved: ${filename} - ${caption}`);
    results.screenshots.push({ filename, caption });
  }

  try {
    const t0 = Date.now();

    // 1. Authenticate via Demo Access
    console.log("1. Authenticating session via /auth...");
    await page.goto("http://localhost:3000/auth", { waitUntil: "networkidle" });
    const demoButton = page.locator("text=Enter Mission Control (Demo Access)");
    await demoButton.click();
    await page.waitForURL("**/dashboard", { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(1000);

    // 2. Navigate to /map
    console.log("2. Navigating to /map...");
    const navStart = Date.now();
    await page.goto("http://localhost:3000/map", { waitUntil: "domcontentloaded" });
    results.timings.navigationMs = Date.now() - navStart;

    // 3. Wait for map elements
    console.log("3. Waiting for live map to mount and fetch telemetry...");
    await page.waitForSelector("text=Global Live Telemetry Control Tower", { timeout: 15000 });
    results.mapLoaded = true;

    // Wait for live stream or objects
    await page.waitForTimeout(4000);
    results.timings.firstDataMs = Date.now() - t0;

    // Check if network requests fired
    results.initialDataReceived = interceptedRequests.some((u) => u.includes("/api/v1/map/objects"));
    results.providersHealthReceived = interceptedRequests.some((u) => u.includes("/api/v1/map/providers/health"));

    // Check for WS connection indicator
    const liveStreamBadge = await page.locator("text=LIVE STREAM").isVisible().catch(() => false);
    const connectedBadge = await page.locator("text=Live Telemetry Connected").isVisible().catch(() => false);
    results.wsConnected = liveStreamBadge || connectedBadge;

    // 4. Capture Initial Desktop Map
    console.log("4. Capturing initial desktop map snapshot...");
    await takeScreenshot("map_01_live_telemetry_desktop.png", "Live multi-source geospatial control tower with live streaming vessels, ports, weather hazards, and transponders");

    // 5. Open Telemetry Layers & Sources Panel
    console.log("5. Opening Telemetry Layers drawer...");
    await page.evaluate(() => {
      document.getElementById("btn-toggle-telemetry-layers")?.click();
    });
    await page.waitForTimeout(1000);
    await takeScreenshot("map_02_layers_and_providers_panel.png", "Telemetry operational control panel with layer filters and real-time provider health statuses (AISStream, Aircraft, Project44, OpenWeather, TomTom, Mobility, Internal)");

    // 6. Test Tactical SVG Radar Mode
    console.log("6. Switching to Tactical SVG mode...");
    await page.evaluate(() => {
      document.getElementById("btn-view-tactical-svg")?.click();
    });
    await page.waitForTimeout(1000);
    await takeScreenshot("map_03_tactical_svg_radar.png", "Tactical SVG global radar grid display with live transponder overlay");

    // Switch back to Google Dark
    await page.evaluate(() => {
      document.getElementById("btn-view-google-dark")?.click();
    });
    await page.waitForTimeout(500);

    // 7. Test Mobile Viewport via dedicated context
    console.log("7. Testing mobile responsive layout (375x812)...");
    const mobileContext = await browser.newContext({ viewport: { width: 375, height: 812 } });
    const mobilePage = await mobileContext.newPage();
    await mobilePage.goto("http://localhost:3000/auth", { waitUntil: "networkidle" });
    await mobilePage.locator("text=Enter Mission Control (Demo Access)").click();
    await mobilePage.waitForURL("**/dashboard", { timeout: 15000 }).catch(() => {});
    await mobilePage.goto("http://localhost:3000/map", { waitUntil: "domcontentloaded" });
    await mobilePage.waitForTimeout(3000);

    // Toggle collapse sidebar to view full mobile map
    await mobilePage.evaluate(() => {
      const btn = document.querySelector("aside button") || document.querySelector("nav button");
      if (btn) btn.click();
    });
    await mobilePage.waitForTimeout(1000);

    const mobileCdp = await mobileContext.newCDPSession(mobilePage);
    const { data: mobileData } = await mobileCdp.send("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(path.join(SCREENSHOT_DIR, "map_04_mobile_view.png"), Buffer.from(mobileData, "base64"));
    console.log("[SNAPSHOT] Saved: map_04_mobile_view.png - Mobile responsive live geospatial tracking layout");
    results.screenshots.push({ filename: "map_04_mobile_view.png", caption: "Mobile responsive live geospatial tracking layout" });
    await mobileContext.close();

    // Verify backend secrets did NOT leak
    const backendSecretKeywords = [
      process.env.AISSTREAM_API_KEY,
      process.env.OPENWEATHER_API_KEY,
      process.env.PROJECT44_CLIENT_SECRET,
      process.env.MOBILITY_DATABASE_ACCESS_TOKEN,
    ].filter((s) => Boolean(s && s.length >= 8));
    const backendLeaks = [];
    for (const reqUrl of interceptedRequests) {
      for (const secret of backendSecretKeywords) {
        if (reqUrl.includes(secret)) {
          backendLeaks.push({ url: reqUrl, type: "network" });
        }
      }
    }
    for (const err of consoleErrors) {
      for (const secret of backendSecretKeywords) {
        if (err.includes(secret)) {
          backendLeaks.push({ error: err, type: "console" });
        }
      }
    }
    results.backendLeakedSecrets = backendLeaks.length;
    results.leakedSecrets = backendLeaks.length;

    console.log("\n==================================================");
    console.log("MAP AUDIT SUMMARY:");
    console.log(`- Map Loaded: ${results.mapLoaded}`);
    console.log(`- Initial /api/v1/map/objects called: ${results.initialDataReceived}`);
    console.log(`- /api/v1/map/providers/health called: ${results.providersHealthReceived}`);
    console.log(`- WebSocket Live Stream Connected: ${results.wsConnected}`);
    console.log(`- Leaked Secrets in URLs or Console: ${results.leakedSecrets}`);
    console.log(`- Console Errors: ${consoleErrors.length}`);
    console.log("==================================================");

    fs.writeFileSync(
      path.join(SCREENSHOT_DIR, "live_map_audit_results.json"),
      JSON.stringify(results, null, 2)
    );
  } catch (err) {
    console.error("Audit error:", err);
  } finally {
    await browser.close();
  }
}

runMapAudit();
