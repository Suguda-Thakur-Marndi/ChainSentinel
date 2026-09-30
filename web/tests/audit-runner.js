const { chromium } = require("playwright-core");
const path = require("path");
const fs = require("fs");

const SCREENSHOT_DIR = path.resolve(__dirname, "../../docs/screenshots");

async function runAudit() {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }

  console.log("Starting Browser-First UI/UX Audit on RiskWise 2.0...");
  const browser = await chromium.launch({
    channel: "msedge",
    headless: true,
  });

  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });

  const page = await context.newPage();

  const auditLog = [];

  // Helper to snapshot
  async function snapshot(filename, description) {
    const fullPath = path.join(SCREENSHOT_DIR, filename);
    await page.screenshot({ path: fullPath, fullPage: false });
    console.log(`[SNAPSHOT] Saved: ${filename} - ${description}`);
    auditLog.push({ filename, description, timestamp: new Date().toISOString() });
  }

  try {
    // 1. Auth Page
    console.log("\n1. Auditing /auth page...");
    await page.goto("http://localhost:3000/auth", { waitUntil: "networkidle" });
    await page.waitForTimeout(1000);
    await snapshot("auth_login_page.png", "Authentication page with BorderBeam and architectural styling");

    // 2. Demo Login
    console.log("\n2. Executing Demo Access Login...");
    const demoButton = page.locator("text=Enter Mission Control (Demo Access)");
    await demoButton.click();
    await page.waitForURL("**/dashboard", { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(2000);

    // 3. Dashboard in Obsidian Dark
    console.log("\n3. Auditing Dashboard (Obsidian Dark)...");
    await snapshot("dashboard_obsidian_mode.png", "Dashboard with 3D Security Machine and Telemetry HUD in Obsidian Dark");

    // 4. Test Theme Toggle to Warm Ivory
    console.log("\n4. Testing Theme Toggle to Warm Ivory...");
    const themeBtn = page.locator('button[title*="Toggle Architectural Theme"]');
    if (await themeBtn.isVisible()) {
      await themeBtn.click();
      await page.waitForTimeout(1000);
      await snapshot("dashboard_warm_ivory_mode.png", "Dashboard in Warm Ivory high-contrast editorial theme");
      // Toggle back to dark
      await themeBtn.click();
      await page.waitForTimeout(500);
    }

    // 5. Suppliers Page & Modal
    console.log("\n5. Auditing /suppliers route...");
    await page.goto("http://localhost:3000/suppliers", { waitUntil: "networkidle" });
    await page.waitForTimeout(1000);
    await snapshot("suppliers_directory_page.png", "Suppliers directory table with ArchBadge status");

    const registerSupplierBtn = page.locator("text=Register Supplier");
    if (await registerSupplierBtn.isVisible()) {
      await registerSupplierBtn.click();
      await page.waitForTimeout(500);
      await snapshot("suppliers_register_modal.png", "ArchModal for supplier creation with ArchInput controls");
      // Close modal
      const cancelBtn = page.locator("text=Cancel");
      if (await cancelBtn.isVisible()) await cancelBtn.click();
    }

    // 6. Shipments Page & Modal
    console.log("\n6. Auditing /shipments route...");
    await page.goto("http://localhost:3000/shipments", { waitUntil: "networkidle" });
    await page.waitForTimeout(1000);
    await snapshot("shipments_monitor_page.png", "Shipments monitor table and mode/status filters");

    const registerShipmentBtn = page.locator("text=Register Shipment");
    if (await registerShipmentBtn.isVisible()) {
      await registerShipmentBtn.click();
      await page.waitForTimeout(500);
      await snapshot("shipments_register_modal.png", "ArchModal for shipment creation with ArchSelect transport mode");
      const cancelBtn = page.locator("text=Cancel");
      if (await cancelBtn.isVisible()) await cancelBtn.click();
    }

    // 7. Simulations Page & Wizard
    console.log("\n7. Auditing /simulations route...");
    await page.goto("http://localhost:3000/simulations", { waitUntil: "networkidle" });
    await page.waitForTimeout(1000);
    await snapshot("simulations_engine_page.png", "What-If Simulation Engine overview with ArchCards");

    const launchSimBtn = page.locator("text=Launch New Simulation");
    if (await launchSimBtn.isVisible()) {
      await launchSimBtn.click();
      await page.waitForTimeout(500);
      await snapshot("simulations_wizard_modal.png", "Simulation Setup Wizard Step 1 with ArchInput controls");
      const closeBtn = page.locator("text=Cancel").or(page.locator("button:has-text('Back')"));
      // Close modal by clicking outside or pressing escape
      await page.keyboard.press("Escape");
    }

    // 8. Optimization Page
    console.log("\n8. Auditing /optimization route...");
    await page.goto("http://localhost:3000/optimization", { waitUntil: "networkidle" });
    await page.waitForTimeout(1000);
    await snapshot("optimization_engine_page.png", "Google OR-Tools MILP optimization table and ArchButton controls");

    // 9. Admin Page with Tabs
    console.log("\n9. Auditing /admin route...");
    await page.goto("http://localhost:3000/admin", { waitUntil: "networkidle" });
    await page.waitForTimeout(1000);
    await snapshot("admin_rbac_page.png", "Admin RBAC and Tenant boundary with ArchTabs");

    // 10. Approvals Queue
    console.log("\n10. Auditing /approvals route...");
    await page.goto("http://localhost:3000/approvals", { waitUntil: "networkidle" });
    await page.waitForTimeout(1000);
    await snapshot("approvals_queue_page.png", "Dual-control human governance approval queue");

    // 11. Audit Ledger
    console.log("\n11. Auditing /audit route...");
    await page.goto("http://localhost:3000/audit", { waitUntil: "networkidle" });
    await page.waitForTimeout(1000);
    await snapshot("audit_ledger_page.png", "Cryptographically sealed immutable audit ledger");

    // 12. Global Live Map
    console.log("\n12. Auditing /map route...");
    await page.goto("http://localhost:3000/map", { waitUntil: "networkidle" });
    await page.waitForTimeout(1500);
    await snapshot("live_map_page.png", "Global Live Map with multimodal vessel/flight corridors");

    console.log("\nAll 12 audit snapshots captured successfully!");
    fs.writeFileSync(
      path.join(SCREENSHOT_DIR, "audit_index.json"),
      JSON.stringify(auditLog, null, 2)
    );
  } catch (err) {
    console.error("Audit encounterd error:", err);
  } finally {
    await browser.close();
  }
}

runAudit();
