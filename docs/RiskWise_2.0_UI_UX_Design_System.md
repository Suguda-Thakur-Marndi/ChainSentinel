# RiskWise 2.0 — UI/UX Design System
### AI-Powered Supply Chain Risk Intelligence & Decision Platform

This document is the complete design language for RiskWise 2.0: the reasoning behind it, the tokens that implement it, and the screen-by-screen specification. It's written so a design or engineering team can build the product without inventing the visual identity as they go — and without it collapsing into the generic "AI dashboard" look that every recent SaaS tool shares.

---

## 0. Why this document exists

Most AI-generated enterprise dashboards converge on the same handful of moves: a near-black background tinted to `#0B0B0B`, one glowing accent color, everything chopped into identical rounded cards with the same soft grey shadow, tracked-out ALL-CAPS labels above every section, meta text joined with middle dots, and a monospace font used purely for decoration. None of that is wrong on its own — but applied without reason, it reads as templated, and on a product whose entire value proposition is **trust and explainability**, a templated shell undercuts the pitch before anyone reads a number.

RiskWise's visual identity is instead built from its actual subject matter: this is a **control room**, not a content site. The people who live in it — analysts, ops managers, risk managers — spend eight hours a day scanning dense, precise, numeric information under real time pressure, the way a shipping-line dispatcher, an air-traffic controller, or a fixed-income trader does. Every design decision below traces back to that fact.

---

## 1. Design principles

1. **Precision over polish.** Hairline borders, not soft shadows. Flat surfaces, not gradients. A control room looks calibrated, not decorated.
2. **Evidence before conclusion.** Nothing the AI states appears without a source, a timestamp, and a confidence value next to it, visually subordinate but never hidden.
3. **Uncertainty is visible, not smoothed over.** Confidence and data provenance (real / estimated / simulated) are first-class visual elements, not footnotes.
4. **Density with hierarchy.** The screens are data-dense by necessity. Hierarchy is carried by type weight, spacing rhythm, and border-color, not by making things bigger.
5. **One deliberate accent moment per screen.** Color is functional (status, AI activity) everywhere else. It is never decorative.
6. **Numbers are typographic citizens.** Tabular figures get their own typeface treatment so they align, scan, and compare at a glance — this is a Bloomberg-terminal habit, not a generic "big stat" card.
7. **The interface never lies about its own state.** Loading, stale, degraded, offline, and permission-denied states are designed with the same care as the happy path.

---

## 2. Design tokens

### 2.1 Color

The palette is a cool slate-charcoal system (not a tinted pure black) with a **harbor blue** identity accent — chosen because the product's subject is literally ports, vessels, and global movement, not because blue is a safe SaaS default. Status colors are desaturated so they read as instrumentation, not warning stickers.

**Base surfaces**
| Token | Hex | Use |
|---|---|---|
| `surface-0` | `#0D1117` | App background (canvas, map, chart backdrops) |
| `surface-1` | `#141922` | Panels, sidebar, cards, table rows |
| `surface-2` | `#1B212C` | Raised elements: modals, popovers, dropdown menus |
| `surface-3` | `#232A36` | Hover / active state fill |
| `border-hairline` | `#28303C` | Default 1px dividers, panel edges, table rules |
| `border-strong` | `#3A4453` | Focus rings, selected-row edges, active tab underline |

**Text**
| Token | Hex | Use |
|---|---|---|
| `text-primary` | `#E7EAEE` | Headings, primary data values |
| `text-secondary` | `#9AA5B4` | Body copy, labels, table secondary columns |
| `text-tertiary` | `#5E6878` | Placeholder, disabled, timestamps, metadata |

**Brand / AI accent**
| Token | Hex | Use |
|---|---|---|
| `accent-harbor` | `#3E8EF7` | AI activity, links, active nav item, focus state, "information" |
| `accent-harbor-dim` | `#1F3A5C` | Accent fills at low opacity (backgrounds behind accent text) |

**Status (semantic, functional only — never decorative)**
| Token | Hex | Use |
|---|---|---|
| `status-safe` | `#2FA86A` | Healthy, approved, on-time, low risk |
| `status-warning` | `#D6912B` | Elevated risk, delayed, needs attention |
| `status-critical` | `#E24C4C` | Critical risk, breach, rejected, overdue |
| `status-neutral` | `#5E6878` | No data, paused, not applicable |

Severity fills used behind badges/rows are the status color at 12–16% opacity over `surface-1`, never a solid saturated block — this keeps a table of 40 rows legible rather than looking like a traffic-light strip.

**Data-provenance colors** (distinct from risk severity, so the two systems are never confused)
| Token | Hex | Use |
|---|---|---|
| `data-real` | `#2FA86A` | Live/verified data (reuses safe-green semantics deliberately: "real" is trustworthy) |
| `data-estimated` | `#3E8EF7` | Model-estimated (reuses accent — this is an AI inference) |
| `data-simulated` | `#8B6FE0` | Simulated / scenario data — the **only** place purple appears in the system, reserved so a user instantly knows "this did not happen, we modeled it" |

**Chart series colors** (used only when a chart genuinely has 2–4 comparable series; beyond that, switch to small multiples rather than adding a 5th hue)
| Token | Hex | Use |
|---|---|---|
| `series-1` | `#3E8EF7` | Primary series — matches `accent-harbor`, used for the "main" line/bar in any single-series or first-of-multi chart |
| `series-2` | `#2FA86A` | Secondary series — reuses `status-safe`; appropriate when the second series is a "good" baseline (e.g. on-time performance) |
| `series-3` | `#D6912B` | Tertiary series — reuses `status-warning`; use when the third series represents a risk/cost dimension |
| `series-4` | `#8B6FE0` | Quaternary series — reserved for simulated/forecast series specifically, consistent with `data-simulated` |
| `series-baseline` | `#5E6878` (dashed) | Reference/baseline line in any comparison chart — always dashed, never solid, so "baseline" is legible even in grayscale print |

**Map & glow colors** (used only on the map surface, never in UI chrome — keeps the map's visual energy contained to the map)
| Token | Hex | Use |
|---|---|---|
| `map-ocean` | `#0A0D12` | Ocean/water fill, slightly darker than `surface-0` so land reads as "raised" |
| `map-land` | `#171D26` | Landmass fill |
| `map-border` | `#232B36` | Country/region boundary lines |
| `map-route` | `#3E8EF7` at 60% opacity | Active shipment route lines |
| `map-route-dim` | `#3E8EF7` at 20% opacity | Inactive/unselected route lines |
| `hotspot-safe` | `#2FA86A` radial glow, 25% max opacity | Low-risk zone marker |
| `hotspot-warning` | `#D6912B` radial glow, 30% max opacity | Elevated-risk zone marker |
| `hotspot-critical` | `#E24C4C` radial glow, 35% max opacity | Critical-risk zone marker — the single brightest thing allowed on the map, so it's unmistakable |

**Interaction & state overlays**
| Token | Hex / Value | Use |
|---|---|---|
| `overlay-hover` | `#FFFFFF` at 4% opacity, layered over surface | Generic hover wash on non-row elements (buttons, chips, nav items) |
| `overlay-pressed` | `#FFFFFF` at 8% opacity | Active/pressed state |
| `overlay-disabled` | `#0D1117` at 55% opacity | Disabled-element scrim |
| `scrim-modal` | `#000000` at 60% opacity | Backdrop behind modals and the command palette |
| `focus-ring` | `#3A4453` (`border-strong`), 2px, 2px offset | Keyboard focus indicator — same token everywhere, no exceptions |

### 2.2 Typography

Two type families, each doing a distinct job — not decoration, a division of labor that mirrors how the content actually works:

- **IBM Plex Sans** — interface text: navigation, headings, body copy, buttons, form labels. Chosen for its engineering/technical character (it was designed for IBM's technical products) rather than a default humanist grotesk — it fits a logistics/infrastructure product without reaching for a "startup" typeface.
- **IBM Plex Mono** — every number that needs to be compared, scanned down a column, or trusted at a glance: risk scores, KPI values, coordinates, timestamps, shipment/run/request IDs, currency figures, percentages. Tabular figures in a monospace face align vertically in tables and make magnitude differences jump out — a genuine Bloomberg-terminal convention, used here for function, not for a "techy" vibe.

**Type scale** (desktop)
| Role | Size / Line-height | Weight | Face |
|---|---|---|---|
| Page title | 22px / 28px | 600 | Plex Sans |
| Section heading | 16px / 22px | 600 | Plex Sans |
| Body | 14px / 20px | 400 | Plex Sans |
| Secondary / label | 12px / 16px | 500 | Plex Sans |
| Micro (timestamps, footnotes) | 11px / 14px | 400 | Plex Sans |
| KPI hero figure | 32px / 36px | 500 | Plex Mono |
| Table numeric cell | 13px / 18px | 400 | Plex Mono |
| Inline ID / code (RW-1042) | 13px / 18px | 400 | Plex Mono |

Labels are **sentence case**, not tracked-out uppercase — the one exception is genuine codes that are inherently uppercase in the real world (ISO country codes, carrier SCAC codes, incident IDs like `RW-1042`), because those are literal identifiers, not decorative eyebrows.

No middle-dot-joined metadata strings (`A · B · C`) and no em-dash-built labels (`WORD — fragment`). Metadata is separated with generous spacing or a hairline vertical divider, e.g. `Singapore` `│` `Updated 24s ago` `│` `Confidence 82%` — but used sparingly, only where three related facts genuinely belong on one line.

### 2.3 Spacing & grid

Base unit: **4px**. Spacing scale: 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64.

- Sidebar width: 264px expanded / 64px collapsed.
- Top bar height: 56px.
- Content gutter: 24px on desktop, 16px on laptop/tablet.
- Panel-to-panel gap: 16px.
- Table row height: 44px (data-dense) with 8px vertical padding inside cells.
- Right inspector/detail panel: fixed 400px on desktop, becomes full-screen overlay below 1280px.

### 2.4 Radius, elevation, and borders

This is where RiskWise deliberately breaks from the generic "SaaS card kit" (identical rounded corners + identical soft shadow on everything):

- **Radius is meaningful, not universal.** Interactive controls (buttons, inputs, chips, toggles) get **6px** radius. Structural panels, tables, and the app shell get **0–2px** radius — square, precise, control-room. A rounded card holding a risk score next to a sharp-edged table reads as inconsistent; RiskWise instead reserves rounding for things you click.
- **No drop shadows on static panels.** Elevation is communicated with a **1px hairline border** (`border-hairline`) and a background-color step (`surface-1` → `surface-2`), not `box-shadow: rgba(0,0,0,.1)`. Shadows appear only on genuinely floating elements — command palette, dropdown menus, toasts — and are tight and dark (`0 4px 12px rgba(0,0,0,0.4)`), not soft SaaS haze.
- **Focus states** use a 2px `border-strong` outline offset 2px from the element, always visible, never color-only (see §12 Accessibility).

### 2.5 Motion

One orchestrated motion moment per meaningful event, not ambient animation everywhere:

- **New critical signal arrives:** the relevant KPI card takes a single 400ms border-color pulse (hairline → `status-critical` → hairline) plus a toast slide-in from the top-right. This happens once, not on a loop.
- **Right inspector panel** slides in from the right over 200ms ease-out when a row/node is selected — this is motion that answers a user's action, not a scroll-triggered reveal.
- **No** fade-and-slide-up entrances on cards as they load. Panels simply appear once data resolves, or show a skeleton (§11) — repeated staggered entrance animation is a generic AI-generated tell and adds latency to how fast an analyst can start reading.
- Respects `prefers-reduced-motion`: all of the above collapse to instant state changes.

---

## 3. Application shell

### 3.1 Left sidebar

Persistent, collapsible to a 64px icon rail (tooltip on hover when collapsed).

```
┌────────────────────────┐
│ ◆ RISKWISE 2.0          │  ← wordmark, not a generic gradient logomark
├────────────────────────┤
│ OVERVIEW                │  ← section label, sentence case, low-emphasis
│   Dashboard             │
│                          │
│ NETWORK                 │
│   Suppliers              │
│   Facilities             │
│   Shipments               │
│   Inventory               │
│   Routes                  │
│   Ports                   │
│                          │
│ RISK INTELLIGENCE       │
│   Risk Center             │
│   Incidents                │
│   Predictions               │
│   Research                  │
│                          │
│ SIMULATION               │
│   Digital Twin              │
│   Scenarios                  │
│   Simulation Runs             │
│   Optimization                 │
│                          │
│ AI OPERATIONS            │
│   Agent Runs                │
│   Recommendations             │
│   Approvals   ⬤3               │  ← numeric badge, status-warning fill
│   Actions                       │
│                          │
│ INTELLIGENCE              │
│   Reports                    │
│   Knowledge                    │
│   Audit Trail                    │
│                          │
│ ADMINISTRATION            │
│   Settings                     │
│   Integrations                   │
├────────────────────────┤
│ ● System: Nominal          │  ← green dot, live status
│ Acme Global Logistics ▾     │  ← org selector
│ [avatar] J. Alvarez ▾         │
└────────────────────────┘
```

Active nav item: left 2px `accent-harbor` bar + `text-primary` + `surface-2` row fill. Section labels (`NETWORK`, `RISK INTELLIGENCE`...) are 11px, `text-tertiary`, sentence-spaced (not letter-tracked caps) — small caps-like weight through color and size, not through tracking, which is the generic tell.

### 3.2 Top bar

56px, `surface-1`, bottom hairline border.

`[Org: Acme Global ▾]` — `[Search everything…  ⌘K]` (grows on focus, opens command palette) — spacer — `[● Live · data current]` — `[bell icon, badge count]` — `[? help]` — `[avatar ▾]`

Global search results are grouped by entity type (Suppliers, Shipments, Incidents, Risks, Recommendations, Products, Facilities) with the entity's status badge shown inline, so a search for "Singapore" surfaces a port, three shipments, and one incident, each legible without opening it.

---

## 4. Component system

Each component is specified by anatomy + states, not just appearance, because in an ops tool the states matter more than the resting look.

**MetricCard** — label (12px secondary) · hero value (Plex Mono, 32px) · trend arrow + delta vs. prior period (colored by whether the trend is good or bad for *that specific metric* — a rising "Active Incidents" trend is colored `status-critical`, a rising "Network Health" trend is colored `status-safe`) · inline sparkline (32px tall, single color, no fill gradient) · severity rail: a 3px left border in the relevant status color. States: default, stale (`text-tertiary` value + "Updated 6m ago" flag), no-data.

**RiskBadge / SeverityBadge / StatusBadge** — a small filled dot (not a filled pill background) + label, e.g. `● Critical`. Color carries meaning but the dot shape and label text are what's actually read — this satisfies "don't rely on color alone" (§12) by default, not as a bolt-on.

**ConfidenceIndicator** — a horizontal 4-segment bar (Low / Moderate / High / Verified) with the active segment filled in `text-secondary` gray, never a status color — confidence is not risk severity and must not visually collide with it. Always paired with the numeric percentage in Plex Mono.

**TrendIndicator** — small arrow glyph + Plex Mono delta value + comparison window in `text-tertiary` ("vs. last 7d").

**DataTable** — dense rows (44px), sortable columns, sticky header, zebra-free (rows are distinguished by hairline separators, not alternating fill, to stay calm at 40+ rows), row-hover = `surface-2`, selected row = left 2px `accent-harbor` bar.

**FilterBar** — horizontal row of dropdown chips (6px radius, `surface-2` fill, hairline border), an active filter shows its selected value inline on the chip itself (`Severity: Critical ×`) rather than a separate "Filters (2)" summary elsewhere on the page.

**SearchBar** — inline within FilterBar or top bar; icon left, `⌘K` hint right when it's the global one.

**MapPanel** — see §5.2 and §17.

**Timeline** — vertical for incident/audit sequences, horizontal for the map's temporal scrubber. Vertical timeline nodes are filled circles connected by a 2px line; completed = `status-safe`, active = `accent-harbor` with a subtle pulse (one-time, on entry), pending = hollow circle in `border-strong`.

**AgentStatus / AgentRunCard** — agent name · role tag ("Research", "Risk", "Prediction"...) · status chip (Running / Complete / Failed / Waiting) · duration (Plex Mono) · tools-used list as small icon chips · evidence count · one-line output summary. Never a "thinking..." transcript — see §6.

**EvidenceCard** — source name + link icon · timestamp · one-line excerpt (paraphrased, not a scraped block) · confidence tag.

**RecommendationCard / ApprovalCard** — title · "why it matters" (1–2 sentences) · evidence count (expandable) · expected benefit (risk reduction %, delay reduction, cost) · confidence · status badge · action row (Approve / Reject / Modify / View evidence).

**ScenarioCard** — scenario label (A/B/C, user-editable name) · one-line event description · key deltas vs. baseline in Plex Mono · "Recommended" ribbon only on the actual top-ranked scenario (never decorative).

**SimulationChart** — baseline vs. scenario as two line series, baseline always rendered as a dashed `text-tertiary` line so it reads as "reference," scenario as a solid `accent-harbor` or `data-simulated` line.

**RiskMatrix** — 5×5 probability × impact grid, cell fill intensity maps to risk tier, current risk plotted as a labeled dot, not just a colored cell — supports users who can't rely on the color grid alone (a numeric coordinate label shows on hover/focus).

**NetworkGraph** — see §9.

**DetailDrawer** — the 400px right-side inspector, consistent across Risk Center, Supplier detail, Digital Twin node inspector, Shipment detail. Header: entity name + close. Body: stacked sections with hairline dividers, not nested cards.

**CommandPalette** — `⌘K` overlay, `surface-2`, tight shadow, fuzzy search across all entity types and actions ("Approve RW-1042", "Go to Digital Twin").

**NotificationCenter** — grouped by category (§16), each item shows severity dot, one-line summary, relative timestamp, and a single primary action.

**AuditTable** — see §15.

---

## 5. Overview / Executive Dashboard

**Header:** "Supply Chain Control Center" (22px) · subtitle in `text-secondary`: "Real-time network health, emerging risks, and recommended actions." · top-right: environment tag `DEMO ENVIRONMENT` in `text-tertiary` on a hairline-outlined chip (never hidden, never styled to look incidental) and last-refresh timestamp.

### 5.1 KPI row

Six MetricCards in a row: Network Risk · Active Incidents · At-Risk Shipments · Predicted Disruptions · Potential Financial Exposure · Inventory at Risk. Each follows the MetricCard spec in §4. Financial Exposure renders as currency in Plex Mono with a tooltip breaking down the estimate's confidence interval — never a bare single number implying false precision.

### 5.2 Main split (left 65% / right 35%)

**Left — Global Risk Map** (see §17 for full map spec; this is the embedded, non-fullscreen version)
- Dark basemap, muted landmass in `surface-1`, ocean in `surface-0`.
- Layer toggle chips along the top of the map panel: Risk · Shipments · Suppliers · Weather · Traffic · Ports · Routes — multi-select, active chips filled `surface-2` with `accent-harbor` text.
- Risk hotspots render as soft radius glows in the relevant status color (kept restrained — radius glow, not a full-bleed gradient wash across the map) sized by affected-shipment-count.
- Vessel/road/air movement shown as small directional glyphs animating along route lines only while the map is in "live" mode — turned off if `prefers-reduced-motion`.
- A compact legend sits bottom-left, always visible, never a hidden hover-only affordance.

**Right — Critical Risks**
Stacked risk cards, most severe first: severity dot + risk title · location · affected asset count · probability % (Plex Mono) · impact tier · composite risk score (large Plex Mono figure, 0–100 scale) · confidence indicator · time-to-impact ("~36h"). Clicking opens the Risk Center detail view for that risk.

### 5.3 Bottom — AI Recommendations

Horizontal scroll or 3-up grid of RecommendationCards (§4). Each shows approval status as a StatusBadge (Pending / Approved / Rejected / In Progress) so the dashboard doubles as an at-a-glance approval queue without needing to visit the Approval Center.

---

## 6. Risk Center

**Header:** "Risk Center." **FilterBar:** Severity · Risk type · Geography · Supplier · Product · Mode · Time range · Status.

**Left (list, 55%):** DataTable — Severity · Risk name · Location · Affected assets · Risk score · Probability · Impact · Trend · Last updated. Row click opens/updates the right detail panel (no navigation away — this keeps scanning fast).

**Right (detail, 45%):**
1. Risk score visualization — a single large Plex Mono number (0–100) with a thin radial arc, plus the ConfidenceIndicator directly beneath it (never floating unexplained).
2. Probability × Impact matrix (RiskMatrix component) with this risk plotted.
3. Risk factors — short bulleted list, each factor tagged with its evidence source.
4. Evidence — stack of EvidenceCards, each with source, timestamp, confidence.
5. Affected network — compact NetworkGraph fragment (suppliers/shipments touched).
6. Timeline — vertical Timeline of how this risk was detected and evolved.
7. Prediction — forecast statement with explicit model/version tag and confidence.
8. Potential consequences — plain-language bullets, not fabricated dollar figures unless sourced.
9. AI explanation — structured findings (see §6 principle below), never raw model narration.
10. Recommended actions — RecommendationCards, inline Approve/Reject.

**Non-negotiable rule enforced visually throughout Risk Center:** every AI-derived number is rendered with a small metadata row directly under it — `Source: Prediction Agent v2.3 · 14:32 UTC · Confidence 78%` — in `text-tertiary`, 11px. No number appears without this row.

---

## 7. Incident Investigation

**Header:** incident name ("Port Congestion — Singapore") + `StatusBadge: CRITICAL` + detected time + source + location. Summary strip: affected assets count, severity, one-line synthesis.

**Timeline (horizontal, top):** Signal detected → Research started → Evidence collected → Risk assessed → Prediction generated → Scenarios evaluated → Recommendation created. This is a genuine sequence, so numbered/ordered treatment is appropriate here (unlike a generic "01/02/03" feature list).

**AI Investigation panel:** five AgentStatus rows (Research / Risk / Prediction / Scenario / Decision), each expandable to show:
- status, duration, tools used (chips), evidence count
- **structured findings only** — a short list of "Finding → supporting evidence → confidence" triples, plus tool-call log (tool name, input summary, output summary) and citations
- explicitly **no** chain-of-thought transcript, no "thinking..." streaming text — this is a deliberate product and trust decision, not a missing feature, and the panel's empty area where a transcript might go is instead used for the structured findings list, so it never reads as withheld.

---

## 8. Shipment Control Center

**FilterBar:** Mode · Status · Risk · ETA · Carrier · Origin · Destination.

**Table:** Shipment ID (Plex Mono, e.g. `RW-1042`) · Mode (small icon: vessel/air/road/rail) · Origin · Destination · Current location · ETA · Delay (Plex Mono, colored if non-zero) · Risk (SeverityBadge) · Status.

**Detail (on row click, opens DetailDrawer or full workspace):** route map, current location, timeline, ETA prediction with confidence band (shown as a shaded range, not a false-precise single time), delay prediction, risk factors, events log, carrier info, related incidents.

**Data-provenance tag is mandatory and visually consistent everywhere in this screen:** every value carries a small inline tag — `REAL` (`data-real` dot), `ESTIMATED` (`data-estimated` dot), or `SIMULATED` (`data-simulated` dot) — placed directly beside the value, same position every time, so a user's eye learns exactly where to check it. Simulated data additionally gets a diagonal-hairline texture on its chart line (not just color) so it's distinguishable without relying on color alone.

---

## 9. Supplier Risk

**Table/cards:** Supplier · Country (flag glyph + ISO code, Plex Mono) · Criticality · Reliability % · Financial exposure · Lead time · Alternative suppliers count · Current risk · Trend.

**Detail page:** profile header, Sites/Products tabs, historical reliability line chart, current risks list, geographic exposure mini-map, shipment exposure count, DependencyGraph (a constrained NetworkGraph showing this supplier's upstream/downstream links), risk timeline, AI-generated investigation summary (structured findings, per §6/§7 rule), recommended mitigation (RecommendationCards).

---

## 10. Digital Twin

The hero screen. Full-canvas NetworkGraph:

```
[Supplier] → [Factory] → [Port] → [Route] → [Warehouse] → [Customer]
```

Each node type gets a distinct **shape**, not just a distinct color, so the graph remains legible for colorblind users and at a glance even before colors are processed:
- Supplier: diamond
- Factory: square
- Port: hexagon
- Route (edge, not a node in itself, but waypoints along long routes render as small circles)
- Warehouse: rounded square
- Customer: triangle

Node fill color = current risk tier (safe/warning/critical/neutral). Node size = throughput volume. Edges are drawn with thickness = capacity and a small icon indicating mode (vessel/air/road/rail); an animated dash pattern along the edge indicates current utilization intensity, replacing the need for a separate utilization number floating in space.

**Top control chips:** Live Network · Risk Overlay · Capacity · Inventory · Transportation · Dependencies (single-select toggle group — these are mutually exclusive lenses on the same graph, not stacking filters).

**Right inspector (DetailDrawer):** on node select — node health, capacity, utilization, risk, dependencies list, incoming/outgoing flows, affected shipments. Selecting an edge instead shows: mode, lead time, capacity, utilization, current risk factors on that lane.

---

## 11. Scenario Simulation

**Header:** "What happens if..." (this is the one place in the product where a conversational, slightly narrative header tone is earned — it's a literal question the tool answers, not a stylistic flourish).

**Scenario builder:** free-text/structured event input ("Port Singapore experiences a 7-day disruption") + variable sliders: Duration, Severity, Capacity reduction, Affected routes.

**Results:** affected suppliers/shipments counts, inventory impact, delivery delay distribution, financial exposure range (always a range, never a false-precise point estimate).

**Baseline vs. Scenario comparison:** paired line/area charts (delivery delay, inventory level, financial impact, risk score) — baseline dashed `text-tertiary`, scenario solid, using the `data-simulated` purple to keep scenario output visually distinct from live data anywhere it might otherwise be confused for real (per the provenance rule in §8).

**Multi-scenario compare:** Scenario A/B/C as tabs or side-by-side ScenarioCards; the top-ranked one gets a "Recommended" tag with the reasoning one line beneath it, not just a bare label.

---

## 12. Optimization

**Header:** "Mitigation Optimization." Objective statement shown as plain text, not hidden in a tooltip: "Minimize disruption risk + financial loss + delay + logistics cost."

**Candidate actions table:** Reroute shipment · Increase inventory · Switch supplier · Increase safety stock · Change transport mode — each row: Cost · Risk reduction · Delay reduction · Capacity impact · Confidence.

**Recommended Plan** — visually distinguished with a single `accent-harbor` left border (not a loud banner), showing expected risk reduction, estimated cost, expected delay reduction, affected shipments, affected suppliers, all in Plex Mono for direct comparability against the candidate table above it.

---

## 13. AI Recommendations & 14. Approval Center

Recommendations and Approvals share the RecommendationCard/ApprovalCard component (§4) but differ in framing: Recommendations is a browse/triage list; Approval Center is a queue with explicit consequence framing per card — Why / Evidence (count, expandable) / Expected impact (delay reduction, risk reduction, cost) / actions (Approve, Reject, Request Changes). High-impact actions are visually marked (a `status-critical` or `status-warning` left border, matched to actual severity, not automatically red) and require the approval flow; low-impact ones can auto-apply if configured, shown with an "Auto-applied" tag instead of an approval prompt. Approval history is a chronological list beneath the active queue, not a separate hidden tab.

---

## 15. Agent Operations & Audit Trail

**Agent Operations table:** Run ID (Plex Mono) · Workflow · Trigger · Status · Duration · Agents (avatar stack) · Tools · Confidence · Outcome.

**Workflow visualization** (horizontal pipeline, genuine sequence so numbered stages are appropriate):
`Detection → Research → Risk → Prediction → Scenario → Optimization → Decision → Approval → Action → Verification`
Each stage: status dot, duration, one-line input/output summary, evidence count. Same "no chain-of-thought" rule as §7.

**Audit Trail:** FilterBar (User, Agent, Action, Resource, Date, Severity) + AuditTable (Timestamp · Actor · Type · Resource · Action · Status · Request ID). Row click opens structured audit detail in a DetailDrawer — full before/after state, not a raw log dump.

---

## 16. Notifications

Grouped by category: Critical Risk · Shipment Delay · Supplier Risk · Approval Required · AI Recommendation · System Alert. Each item: severity dot + one-line summary + relative time + single primary action button. Category headers are collapsible; unread items get a subtle `surface-2` fill, not a bold-text trick alone.

---

## 17. Full-Screen Map Experience

Layers: Supply Chain Network · Shipments · Suppliers · Factories · Warehouses · Ports · Traffic · Weather · Risk Zones — left floating control panel (`surface-2`, hairline border, tight shadow since it floats over the map).

Right contextual panel: appears only when something is selected (consistent with DetailDrawer elsewhere — one inspector pattern used everywhere in the product, not a bespoke map popup style).

Bottom timeline: horizontal scrubber for temporal playback, with a "Live" pin on the right edge that you drag away from to enter historical playback — dragging back to the right edge snaps back to Live, communicating "you are looking at the past" unambiguously.

---

## 18. Reports & 19. Settings

**Reports:** report type list (Network Risk, Supplier Risk, Shipment Risk, Incident, Scenario, AI Decision) each opens a generated report combining charts + KPIs + trends + recommendations + evidence, with Export / Share / Generate Report actions in the header, not buried in a menu.

**Settings:** standard sectioned settings (Organization, Users, Roles, Integrations, AI Configuration, Risk Configuration, Notifications, Security, Audit). Integration cards show Connected/Disconnected/Error/Last sync/Health as a StatusBadge + relative timestamp; connected credentials are always masked (`sk-••••••••4f2a`), never fully hidden or fully shown.

---

## 20. Data visualization language

- Line/area charts: gridlines at `border-hairline` opacity, axis labels in `text-tertiary` Plex Mono, one accent color per series maximum three series before switching to small multiples.
- Sankey/flow: used only for genuine flow-volume questions (inventory movement, shipment routing volume) — not decoratively.
- Heatmaps: risk-matrix and calendar-style incident-density only; cells always carry a numeric label on hover/focus, never color-only.
- Every chart has a one-line caption stating the decision-relevant takeaway ("Delay risk rises sharply after day 4 of disruption") directly beneath it — charts are not decorative, per brief principle 21.

---

## 21. UX states

Every screen implements: Loading (skeleton matching real layout, not a generic spinner), Empty (a short explanation + one primary action — "No active incidents. New signals will appear here automatically."), Error (what happened + retry, in the interface's own voice, never apologetic), Success (inline confirmation, e.g. a toast: "Recommendation approved"), Partial data (a `text-tertiary` "Some data unavailable" strip with which sources are missing, not a silent gap), Offline/degraded provider (a persistent top-bar strip, not a silent failure), Permission denied (explains what's missing and who to ask, not just "403").

Data freshness is always visible: "Updated 24 seconds ago" in `text-tertiary`, next to the relevant panel header — never only in a global corner indicator.

---

## 22. Accessibility (WCAG 2.2 AA)

- All interactive elements keyboard-reachable in a logical order; DetailDrawer traps focus while open and returns focus on close.
- Visible 2px focus outline (`border-strong`) on every focusable element — never `outline: none` without a replacement.
- Text contrast minimum 4.5:1 against its surface at every token pairing above (verified: `text-primary` on `surface-0/1/2` all exceed 4.5:1; `text-secondary` on `surface-0/1` exceeds 4.5:1).
- Status is always paired with a shape/icon/label, never color alone (SeverityBadge's dot + text, provenance tags' distinct icons, RiskMatrix's numeric labels).
- Charts include a text-equivalent summary (visually hidden but screen-reader accessible) stating the same one-line takeaway shown in the caption.
- All icons carry `aria-label`s matching their plain-language function, not their internal name.

---

## 23. Responsive behavior

- **Desktop (1440px+):** full three-pane control-room layout as specified above.
- **Laptop (1024–1439px):** right inspector collapses to an overlay rather than a fixed third column; KPI row wraps 3+3.
- **Tablet (768–1023px):** sidebar defaults to collapsed icon rail; map and table views become tab-switched rather than side-by-side.
- **Mobile:** simplified operational view only — KPI summary, critical risk list, approval queue, notifications. Digital Twin and full map are view-only with a "open on desktop for full simulation tools" note rather than a broken cramped attempt at the full graph.

---

## 24. Voice & content

- Written in plain, active language from the analyst's point of view: "Approve reroute" not "Submit," "3 shipments affected" not "Impacted shipment count: 3."
- Action names stay identical through the whole flow: a button that says "Approve" produces a toast that says "Approved," never "Success!" or "Done."
- Errors and empty states state facts and the next step; they don't apologize and they're never vague ("Couldn't load supplier data — retry" not "Oops, something went wrong").
- No exclamation points in system-generated copy. The tone is a calm, competent colleague, not a cheerful assistant — this is a control room, not a consumer app.

---

## 25. Anti-pattern checklist (what this design deliberately avoids)

- ❌ Warm cream background with terracotta accent, or a single neon accent on tinted-black — replaced with the functional slate/harbor-blue system in §2.1.
- ❌ Identical rounded cards with identical soft shadows everywhere — replaced with hairline-bordered flat panels; radius reserved for interactive controls only (§2.4).
- ❌ Tracked-out ALL-CAPS eyebrows above every section — sidebar section labels use size/color/weight, not letter-spacing tricks.
- ❌ Middle-dot-joined metadata strings and em-dash labels used as decoration — used only sparingly, functionally, for genuinely related facts.
- ❌ Monospace used cosmetically for "tech" flavor — Plex Mono is reserved specifically for comparable numeric/ID data, per §2.2.
- ❌ Arrow (→) appended to every button/link label — buttons say exactly what they do, nothing appended.
- ❌ Staggered fade-and-slide-up entrance animation on every card load — motion is reserved for one deliberate moment per event (§2.5).
- ❌ Numbered 01/02/03 markers on non-sequential content — numbering appears only on genuine pipelines (agent workflow, incident timeline).
- ❌ Unexplained AI-generated numbers — every AI-derived figure carries source, timestamp, and confidence, every time (§6).
