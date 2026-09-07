# DESIGN.md

## Product

**RiskWise 2.0** — AI-powered supply chain risk intelligence and decision platform. An enterprise control center used by supply-chain analysts, risk managers, operations managers, and executives to monitor a live global supply chain, investigate emerging risks with a multi-agent AI pipeline, simulate what-if scenarios, and approve AI-recommended mitigations.

**Feel:** Bloomberg Terminal + AI mission control + a live digital twin. A control room, not a marketing dashboard — dense, precise, calm, built for hours of daily use under time pressure.

**Audience:** operators who scan numeric, high-stakes information fast and need to trust every AI-generated figure they act on.

## Principles

1. **Precision over polish.** Hairline borders and flat surfaces, not soft shadows and rounded card kits.
2. **Evidence before conclusion.** No AI-generated number appears without a source, timestamp, and confidence value attached.
3. **Uncertainty stays visible.** Confidence and data provenance (real / estimated / simulated) are first-class visual elements, never smoothed away.
4. **Density with hierarchy.** Screens are necessarily data-dense; hierarchy comes from type weight, spacing, and border color — not from making things bigger.
5. **One deliberate accent moment per screen.** Color is functional (status, AI activity), never decorative.
6. **Numbers are typographic citizens.** Tabular figures get a dedicated monospace treatment so they align and compare at a glance.
7. **The interface never hides its own state.** Loading, stale, degraded, and error states are designed with the same care as the happy path.

## Color

Cool slate-charcoal base (not tinted pure black) with a single functional "harbor blue" identity accent. Status colors are desaturated — instrumentation, not warning stickers.

**Surfaces**
- `surface-0` `#0D1117` — app background, canvas
- `surface-1` `#141922` — panels, sidebar, cards, table rows
- `surface-2` `#1B212C` — modals, popovers, dropdown menus
- `surface-3` `#232A36` — hover / active fill
- `border-hairline` `#28303C` — default dividers
- `border-strong` `#3A4453` — focus rings, active states

**Text**
- `text-primary` `#E7EAEE`
- `text-secondary` `#9AA5B4`
- `text-tertiary` `#5E6878`

**Brand / AI accent**
- `accent-harbor` `#3E8EF7` — AI activity, links, active nav, focus, "information"
- `accent-harbor-dim` `#1F3A5C` — low-opacity accent fills

**Status** (functional only, never decorative)
- `status-safe` `#2FA86A`
- `status-warning` `#D6912B`
- `status-critical` `#E24C4C`
- `status-neutral` `#5E6878`

**Data provenance** (distinct system from risk severity — never conflated)
- `data-real` `#2FA86A`
- `data-estimated` `#3E8EF7`
- `data-simulated` `#8B6FE0` — the only place purple appears; means "this did not happen, we modeled it"

**Chart series:** `#3E8EF7`, `#2FA86A`, `#D6912B`, `#8B6FE0`, baseline `#5E6878` (always dashed). Max 3 series per chart before switching to small multiples.

**Map:** ocean `#0A0D12`, land `#171D26`, hotspot glows `#2FA86A` / `#D6912B` / `#E24C4C` at 25–35% opacity — the map is the only place glow effects are allowed.

## Typography

Two families, each doing one job:
- **IBM Plex Sans** — all interface text: navigation, headings, body, labels, buttons.
- **IBM Plex Mono** — every number that must be scanned or compared: KPI values, risk scores, IDs, timestamps, currency, percentages, coordinates.

Sentence case throughout, except literal codes (shipment IDs like `RW-1042`, ISO country codes). No tracked-out ALL-CAPS labels.

| Role | Size / Line-height | Weight | Face |
|---|---|---|---|
| Page title | 22px / 28px | 600 | Plex Sans |
| Section heading | 16px / 22px | 600 | Plex Sans |
| Body | 14px / 20px | 400 | Plex Sans |
| Label / secondary | 12px / 16px | 500 | Plex Sans |
| Micro (timestamps) | 11px / 14px | 400 | Plex Sans |
| KPI hero figure | 32px / 36px | 500 | Plex Mono |
| Table numeric cell | 13px / 18px | 400 | Plex Mono |

## Layout & spacing

Base unit: 4px. Scale: 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64.

- Sidebar: 264px expanded / 64px collapsed icon rail.
- Top bar: 56px.
- Content gutter: 24px desktop / 16px laptop-tablet.
- Table row height: 44px.
- Right inspector/detail panel: fixed 400px on desktop, full-screen overlay below 1280px.
- Persistent three-pane pattern: left nav → main content → contextual right inspector that updates in place (no navigating away to see detail).

## Shape, elevation, borders

Deliberately breaks from the generic "SaaS card kit" (identical rounded cards + identical soft shadow on everything):
- Radius is **meaningful, not universal**: 6px on interactive controls (buttons, inputs, chips, toggles); 0–2px (square) on structural panels, tables, and the app shell.
- **No drop shadows on static panels.** Elevation is a 1px hairline border + a background-color step, not `box-shadow`. Shadows appear only on genuinely floating elements (command palette, menus, toasts), tight and dark, not a soft SaaS haze.
- Focus states: 2px `border-strong` outline, 2px offset, always visible, never color-only.

## Motion

One orchestrated motion moment per meaningful event, not ambient animation everywhere:
- New critical signal: a single 400ms border-color pulse on the relevant KPI + a toast slide-in. Once, not looping.
- Right inspector panel: slides in from the right over 200ms when something is selected — motion that answers a user's action.
- **No** staggered fade-and-slide-up entrances on card load — that's a generic AI-generated tell.
- Respects `prefers-reduced-motion` throughout.

## Components (core set)

MetricCard, RiskBadge/SeverityBadge/StatusBadge (dot + label, never color alone), ConfidenceIndicator (4-segment neutral-gray bar, distinct from status color), TrendIndicator, DataTable (hairline-divided rows, no zebra striping), FilterBar (chips showing selected value inline), EvidenceCard, AgentStatus/AgentRunCard, RecommendationCard/ApprovalCard, ScenarioCard, RiskMatrix, NetworkGraph, DetailDrawer (one consistent inspector pattern used everywhere), CommandPalette, AuditTable.

## Data visualization

Every chart states its one-line decision-relevant takeaway as a caption — never decorative. Gridlines at hairline opacity. Baseline/reference series always dashed and neutral gray. Charts never imply false precision: financial and delay forecasts render as ranges/confidence bands, not single point values.

## Content & voice

Plain, active language from the analyst's point of view: "Approve reroute," not "Submit." Action names stay identical through a flow — a button that says "Approve" produces a toast that says "Approved," never "Success!" Errors state facts and the next step, never apologize, never vague. No exclamation points in system copy — calm, competent colleague, not a cheerful assistant.

## Accessibility

WCAG 2.2 AA. Full keyboard reachability, visible focus outlines everywhere, 4.5:1 minimum text contrast, status never conveyed by color alone (always paired with shape/icon/label), charts carry a text-equivalent summary.

## What this design avoids

- Warm cream background with terracotta accent, or neon-on-tinted-black — replaced by the slate/harbor-blue system above.
- Identical rounded cards with identical soft shadows — replaced by hairline-bordered flat panels; radius reserved for controls only.
- Tracked-out ALL-CAPS section eyebrows, middle-dot metadata strings, em-dash labels, arrow-suffixed buttons.
- Monospace used for decoration — reserved specifically for comparable numeric/ID data.
- Numbered 01/02/03 markers on non-sequential content — numbering only on genuine pipelines (agent workflow, incident timeline).
- Unexplained AI-generated numbers — every AI-derived figure always carries source, timestamp, and confidence.
