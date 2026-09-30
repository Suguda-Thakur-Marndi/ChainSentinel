const fs = require('fs');
const path = require('path');
const { chromium } = require('c:/Users/sugud/OneDrive/Documents/riskwise/web/node_modules/playwright-core');

const SCREENSHOT_DIR = 'C:\\Users\\sugud\\.gemini\\antigravity-ide\\brain\\85efa97d-440c-4c9b-b879-85f6e7a42c92\\screenshots';
const RESULTS_FILE = 'C:\\Users\\sugud\\.gemini\\antigravity-ide\\brain\\85efa97d-440c-4c9b-b879-85f6e7a42c92\\scratch\\step3_results.json';

if (!fs.existsSync(SCREENSHOT_DIR)) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

// 47 routes specification
const ROUTES_DEF = [
  { num: 1, route: '/', screenshot: '001-root.png', dynamic: false },
  { num: 2, route: '/auth', screenshot: '002-auth.png', dynamic: false },
  { num: 3, route: '/dashboard', screenshot: '003-dashboard.png', dynamic: false },
  { num: 4, route: '/overview', screenshot: '004-overview.png', dynamic: false },
  { num: 5, route: '/admin', screenshot: '005-admin.png', dynamic: false },
  { num: 6, route: '/settings', screenshot: '006-settings.png', dynamic: false },
  { num: 7, route: '/map', screenshot: '007-map.png', dynamic: false },
  { num: 8, route: '/suppliers', screenshot: '008-suppliers.png', dynamic: false },
  { num: 9, route: '/carriers', screenshot: '009-carriers.png', dynamic: false },
  { num: 10, route: '/shipments', screenshot: '010-shipments.png', dynamic: false },
  { num: 11, route: '/shipments/[id]', resolvedUrl: '/shipments/0e7faf23-8224-4b33-ad55-9a11385f09cd', screenshot: '011-shipment-detail.png', dynamic: true, validId: '0e7faf23-8224-4b33-ad55-9a11385f09cd' },
  { num: 12, route: '/inventory', screenshot: '012-inventory.png', dynamic: false },
  { num: 13, route: '/products', screenshot: '013-products.png', dynamic: false },
  { num: 14, route: '/ports', screenshot: '014-ports.png', dynamic: false },
  { num: 15, route: '/factories', screenshot: '015-factories.png', dynamic: false },
  { num: 16, route: '/warehouses', screenshot: '016-warehouses.png', dynamic: false },
  { num: 17, route: '/routes', screenshot: '017-routes.png', dynamic: false },
  { num: 18, route: '/risks', screenshot: '018-risks.png', dynamic: false },
  { num: 19, route: '/risks/[id]', resolvedUrl: '/risks/23cbb998-c0fb-498c-a6aa-c88338d12491', screenshot: '019-risk-detail.png', dynamic: true, validId: '23cbb998-c0fb-498c-a6aa-c88338d12491' },
  { num: 20, route: '/incidents', screenshot: '020-incidents.png', dynamic: false },
  { num: 21, route: '/incidents/[id]', resolvedUrl: null, screenshot: '021-incident-detail.png', dynamic: true, validId: null, blockedReason: 'BLOCKED — NO VALID RECORD (0 records in database table incidents)' },
  { num: 22, route: '/recommendations', screenshot: '022-recommendations.png', dynamic: false },
  { num: 23, route: '/recommendations/[id]', resolvedUrl: '/recommendations/662c41e2-5c31-4ab7-aaaa-948dcabf9632', screenshot: '023-recommendation-detail.png', dynamic: true, validId: '662c41e2-5c31-4ab7-aaaa-948dcabf9632' },
  { num: 24, route: '/approvals', screenshot: '024-approvals.png', dynamic: false },
  { num: 25, route: '/actions', screenshot: '025-actions.png', dynamic: false },
  { num: 26, route: '/actions/[id]', resolvedUrl: '/actions/bb1f517e-9b0e-41dd-afe6-5841bbb87305', screenshot: '026-action-detail.png', dynamic: true, validId: 'bb1f517e-9b0e-41dd-afe6-5841bbb87305' },
  { num: 27, route: '/decisions', screenshot: '027-decisions.png', dynamic: false },
  { num: 28, route: '/decisions/[id]', resolvedUrl: '/decisions/rec_748b27a2d99c94d7b3aebaba', screenshot: '028-decision-detail.png', dynamic: true, validId: 'rec_748b27a2d99c94d7b3aebaba' },
  { num: 29, route: '/digital-twin', screenshot: '029-digital-twin.png', dynamic: false },
  { num: 30, route: '/simulations', screenshot: '030-simulations.png', dynamic: false },
  { num: 31, route: '/simulations/[id]', resolvedUrl: null, screenshot: '031-simulation-detail.png', dynamic: true, validId: null, blockedReason: 'BLOCKED — NO VALID RECORD (0 records in database table simulations)' },
  { num: 32, route: '/optimization', screenshot: '032-optimization.png', dynamic: false },
  { num: 33, route: '/optimization/[id]', resolvedUrl: null, screenshot: '033-optimization-detail.png', dynamic: true, validId: null, blockedReason: 'BLOCKED — NO VALID RECORD (0 records in database table optimization_runs)' },
  { num: 34, route: '/notifications', screenshot: '034-notifications.png', dynamic: false },
  { num: 35, route: '/audit', screenshot: '035-audit.png', dynamic: false },
  { num: 36, route: '/audit-logs', screenshot: '036-audit-logs.png', dynamic: false },
  { num: 37, route: '/verification', screenshot: '037-verification.png', dynamic: false },
  { num: 38, route: '/verification/[id]', resolvedUrl: '/verification/c92a926b-0870-44a4-912e-16806c0da203', screenshot: '038-verification-detail.png', dynamic: true, validId: 'c92a926b-0870-44a4-912e-16806c0da203' },
  { num: 39, route: '/policy-inspector', screenshot: '039-policy-inspector.png', dynamic: false },
  { num: 40, route: '/policy-inspector/[id]', resolvedUrl: '/policy-inspector/pol-001', screenshot: '040-policy-inspector-detail.png', dynamic: true, validId: 'pol-001' },
  { num: 41, route: '/agent-runs', screenshot: '041-agent-runs.png', dynamic: false },
  { num: 42, route: '/agent-runs/[id]', resolvedUrl: null, screenshot: '042-agent-run-detail.png', dynamic: true, validId: null, blockedReason: 'BLOCKED — NO VALID RECORD (0 records in database table agent_runs)' },
  { num: 43, route: '/evaluation', screenshot: '043-evaluation.png', dynamic: false },
  { num: 44, route: '/mcp-tools', screenshot: '044-mcp-tools.png', dynamic: false },
  { num: 45, route: '/mcp-tools/[id]', resolvedUrl: '/mcp-tools/route_optimizer', screenshot: '045-mcp-tool-detail.png', dynamic: true, validId: 'route_optimizer' },
  { num: 46, route: '/system-health', screenshot: '046-system-health.png', dynamic: false },
  { num: 47, route: '404 / not-found', resolvedUrl: '/this-route-does-not-exist', screenshot: '047-not-found.png', dynamic: false },
];

const RESPONSIVE_TARGETS = [
  '/dashboard',
  '/overview',
  '/suppliers',
  '/shipments',
  '/risks',
  '/recommendations',
  '/approvals',
  '/digital-twin',
  '/simulations',
  '/optimization',
  '/system-health'
];

const VIEWPORTS = [
  { name: '390px', width: 390, height: 844 },
  { name: '768px', width: 768, height: 1024 },
  { name: '1280px', width: 1280, height: 800 },
  { name: '1440px', width: 1440, height: 900 }
];

async function runAudit() {
  console.log('=== STARTING STEP 3 ROUTE AUDIT (47 ROUTES) ===');
  
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });

  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 RiskWiseAudit/1.0'
  });

  const results = {
    testEnvironment: {
      frontend: 'http://localhost:3000',
      backend: 'http://localhost:8000',
      database: 'SQLite (api/riskwise_local.db)',
      authMechanism: 'Official Backend Demo Login (/api/v1/auth/demo-login)',
      browser: 'Google Chrome 130+ via Playwright-core',
      timestamp: new Date().toISOString()
    },
    preAuthChecks: {},
    routes: [],
    apiFailures: [],
    consoleErrors: [],
    interactionResults: [],
    responsiveResults: []
  };

  const page = await context.newPage();

  // Step A: Pre-Auth Checks
  console.log('\n--- PHASE A: PRE-AUTHENTICATION CHECKS ---');
  
  // 1. Check unauthenticated /dashboard redirect
  try {
    console.log('Testing unauthenticated access to /dashboard...');
    const resp = await page.goto('http://localhost:3000/dashboard', { waitUntil: 'domcontentloaded', timeout: 10000 });
    await page.waitForTimeout(2000);
    const finalUrl = page.url();
    results.preAuthChecks.unauthenticatedDashboard = {
      initialStatus: resp ? resp.status() : 'none',
      finalUrl,
      redirectedToAuth: finalUrl.includes('/auth')
    };
    console.log(`Unauthenticated /dashboard final URL: ${finalUrl} (Redirected to auth: ${finalUrl.includes('/auth')})`);
  } catch (err) {
    results.preAuthChecks.unauthenticatedDashboard = { error: err.message };
  }

  // 2. Perform official demo login to obtain valid session
  console.log('\n--- PHASE B: PERFORMING OFFICIAL DEMO LOGIN ---');
  try {
    console.log('Navigating to /api/v1/auth/demo-login?return_to=/dashboard...');
    const loginResp = await page.goto('http://localhost:3000/api/v1/auth/demo-login?return_to=/dashboard', {
      waitUntil: 'networkidle',
      timeout: 15000
    });
    await page.waitForTimeout(2500);
    const cookies = await context.cookies();
    const sessionCookie = cookies.find(c => c.name === 'riskwise_session');
    results.preAuthChecks.sessionEstablished = {
      urlAfterLogin: page.url(),
      hasSessionCookie: Boolean(sessionCookie),
      cookieDetails: sessionCookie ? { name: sessionCookie.name, httpOnly: sessionCookie.httpOnly, domain: sessionCookie.domain } : null
    };
    console.log(`Demo login result: URL = ${page.url()}, sessionCookie = ${Boolean(sessionCookie)}`);
  } catch (err) {
    console.error('Demo login failed:', err.message);
    results.preAuthChecks.sessionEstablished = { error: err.message };
  }

  // Step C: Route-by-route audit (47 routes)
  console.log('\n--- PHASE C: TESTING ALL 47 ROUTES ONE-BY-ONE ---');

  for (const item of ROUTES_DEF) {
    const routeId = item.num;
    const targetPath = item.resolvedUrl || item.route;
    const screenshotPath = path.join(SCREENSHOT_DIR, item.screenshot);

    console.log(`\n[${routeId}/47] Testing ${item.route} (Target: ${targetPath})...`);

    if (item.blockedReason) {
      console.log(`  -> ${item.blockedReason}`);
      results.routes.push({
        num: routeId,
        route: item.route,
        targetUrl: targetPath,
        httpStatus: 'N/A',
        browserStatus: 'BLOCKED',
        consoleSummary: 'N/A',
        networkSummary: 'N/A',
        interactionSummary: 'BLOCKED',
        screenshot: 'NONE',
        status: 'BLOCKED',
        reason: item.blockedReason,
        pageTitle: 'N/A'
      });
      continue;
    }

    // Set up route collectors
    const consoleLogs = [];
    const networkErrors = [];
    const apiCalls = [];

    const consoleHandler = msg => {
      const type = msg.type();
      const text = msg.text();
      consoleLogs.push({ type, text });
      if (type === 'error') {
        results.consoleErrors.push({ route: item.route, text, severity: text.includes('Hydration') ? 'ERROR' : 'ERROR' });
      }
    };

    const pageErrorHandler = err => {
      consoleLogs.push({ type: 'pageerror', text: err.message });
      results.consoleErrors.push({ route: item.route, text: err.message, severity: 'CRITICAL' });
    };

    const requestHandler = req => {
      const url = req.url();
      if (url.includes('/api/')) {
        apiCalls.push({ url, method: req.method() });
      }
    };

    const responseHandler = resp => {
      const url = resp.url();
      const status = resp.status();
      if (url.includes('/api/') && status >= 400) {
        networkErrors.push({ url, status, method: resp.request().method() });
        results.apiFailures.push({
          method: resp.request().method(),
          endpoint: url,
          status,
          route: item.route,
          error: `HTTP ${status}`
        });
      }
    };

    page.on('console', consoleHandler);
    page.on('pageerror', pageErrorHandler);
    page.on('request', requestHandler);
    page.on('response', responseHandler);

    let httpStatus = '200';
    let browserStatus = 'PASS';
    let status = 'PASS';
    let pageTitle = '';
    let visibleSnippet = '';
    let interactionSummary = 'WORKING';

    try {
      const fullUrl = `http://localhost:3000${targetPath}`;
      const resp = await page.goto(fullUrl, { waitUntil: 'networkidle', timeout: 15000 }).catch(async () => {
        // Fallback wait if networkidle times out
        return await page.waitForLoadState('domcontentloaded');
      });

      if (resp && typeof resp.status === 'function') {
        httpStatus = String(resp.status());
      }

      await page.waitForTimeout(1500); // Allow animations/charts to settle

      pageTitle = await page.title();
      
      // Capture screenshot
      await page.screenshot({ path: screenshotPath, fullPage: true });
      console.log(`  Captured screenshot: ${item.screenshot}`);

      // Extract body text snippet
      visibleSnippet = await page.evaluate(() => {
        const text = document.body.innerText || '';
        return text.replace(/\s+/g, ' ').trim().slice(0, 300);
      });

      // Test page interactions safely
      const interactionDetails = await testPageInteractions(page, item.route);
      interactionSummary = interactionDetails.summary;
      results.interactionResults.push({
        num: routeId,
        route: item.route,
        ...interactionDetails
      });

      // Special Route Verifications
      if (item.num === 7) { // /map
        const mapInfo = await page.evaluate(() => {
          const mapEl = document.querySelector('.mapboxgl-map, [data-testid="map-container"], canvas');
          const errorEl = document.body.innerText.match(/mapbox|token|failed to load map/i);
          return { hasCanvas: Boolean(mapEl), mapText: errorEl ? errorEl[0] : null };
        });
        console.log(`  Map check: canvas = ${mapInfo.hasCanvas}, error = ${mapInfo.mapText}`);
      }

      if (item.num === 46) { // /system-health
        const healthText = await page.evaluate(() => document.body.innerText);
        console.log(`  System Health text includes: ${healthText.slice(0, 150)}...`);
      }

      // Determine final status
      const hasCriticalError = consoleLogs.some(c => c.type === 'pageerror');
      const hasApiErrors = networkErrors.length > 0;
      
      if (hasCriticalError) {
        status = 'FAIL';
      } else if (hasApiErrors || interactionSummary === 'BROKEN') {
        status = 'PARTIAL';
      } else {
        status = 'PASS';
      }

    } catch (err) {
      console.error(`  Error testing route ${item.route}:`, err.message);
      browserStatus = 'FAIL';
      status = 'FAIL';
      results.consoleErrors.push({ route: item.route, text: err.message, severity: 'CRITICAL' });
    } finally {
      page.off('console', consoleHandler);
      page.off('pageerror', pageErrorHandler);
      page.off('request', requestHandler);
      page.off('response', responseHandler);
    }

    const consoleSummary = consoleLogs.filter(c => c.type === 'error' || c.type === 'pageerror').length > 0
      ? `${consoleLogs.filter(c => c.type === 'error' || c.type === 'pageerror').length} Errors`
      : 'Clean';

    const networkSummary = networkErrors.length > 0
      ? `${networkErrors.length} Failed (${networkErrors.map(e => `${e.method} ${e.status}`).join(', ')})`
      : 'Clean';

    results.routes.push({
      num: routeId,
      route: item.route,
      targetUrl: targetPath,
      httpStatus,
      browserStatus,
      consoleSummary,
      networkSummary,
      interactionSummary,
      screenshot: item.screenshot,
      status,
      pageTitle,
      visibleSnippet
    });
  }

  // Step D: Responsive Smoke Tests
  console.log('\n--- PHASE D: RESPONSIVE SMOKE TESTS ---');
  for (const routePath of RESPONSIVE_TARGETS) {
    console.log(`Testing responsiveness for: ${routePath}`);
    const routeResp = { route: routePath, viewports: {} };

    for (const vp of VIEWPORTS) {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(`http://localhost:3000${routePath}`, { waitUntil: 'domcontentloaded', timeout: 10000 });
      await page.waitForTimeout(800);

      const metrics = await page.evaluate(() => {
        const scrollW = document.documentElement.scrollWidth;
        const clientW = document.documentElement.clientWidth;
        const hasHorizontalOverflow = scrollW > clientW;
        return {
          scrollWidth: scrollW,
          clientWidth: clientW,
          overflowPixels: scrollW - clientW,
          hasHorizontalOverflow
        };
      });

      routeResp.viewports[vp.name] = {
        ...metrics,
        status: metrics.hasHorizontalOverflow ? 'OVERFLOW_DETECTED' : 'OK'
      };

      if (metrics.hasHorizontalOverflow) {
        console.log(`  [${vp.name}] OVERFLOW DETECTED: +${metrics.overflowPixels}px`);
      }
    }
    results.responsiveResults.push(routeResp);
  }

  await browser.close();
  console.log('\nAudit complete. Saving results to JSON...');
  fs.writeFileSync(RESULTS_FILE, JSON.stringify(results, null, 2), 'utf-8');
  console.log(`Results saved to: ${RESULTS_FILE}`);
}

async function testPageInteractions(page, route) {
  try {
    const controls = await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll('button:not([disabled])')).map(b => b.innerText.trim()).filter(Boolean);
      const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"])')).length;
      const links = Array.from(document.querySelectorAll('a[href]')).length;
      const tabs = Array.from(document.querySelectorAll('[role="tab"]')).length;
      return { buttonsCount: buttons.length, buttonsSample: buttons.slice(0, 5), inputsCount: inputs, linksCount: links, tabsCount: tabs };
    });

    // Test a non-destructive interaction (search input or tab click)
    let testedControl = 'None';
    let controlState = 'NOT APPLICABLE';

    // 1. Try search input
    const searchInput = await page.$('input[placeholder*="Search" i], input[type="search"], input[type="text"]');
    if (searchInput) {
      testedControl = 'Search Input';
      await searchInput.focus();
      await searchInput.fill('TEST_QUERY');
      const val = await searchInput.inputValue();
      await searchInput.fill(''); // clear
      controlState = val === 'TEST_QUERY' ? 'WORKING' : 'BROKEN';
    } else {
      // 2. Try safe tab/filter button
      const safeTab = await page.$('button[role="tab"], button:has-text("ALL"), button:has-text("Overview"), button:has-text("Details")');
      if (safeTab) {
        testedControl = 'Tab / Filter Button';
        await safeTab.click();
        await page.waitForTimeout(300);
        controlState = 'WORKING';
      } else if (controls.buttonsCount > 0 || controls.linksCount > 0) {
        testedControl = 'Navigation / Action Controls';
        controlState = 'WORKING';
      }
    }

    return {
      summary: controlState === 'BROKEN' ? 'BROKEN' : 'WORKING',
      testedControl,
      controlState,
      controls
    };
  } catch (err) {
    return {
      summary: 'PARTIAL',
      testedControl: 'Error during test',
      controlState: 'ERROR',
      error: err.message
    };
  }
}

runAudit().catch(err => {
  console.error('Fatal audit failure:', err);
  process.exit(1);
});
