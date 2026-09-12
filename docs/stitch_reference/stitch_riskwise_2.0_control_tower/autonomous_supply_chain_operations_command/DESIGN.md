---
name: Autonomous Supply Chain Operations Command
colors:
  surface: '#101419'
  surface-dim: '#101419'
  surface-bright: '#36393f'
  surface-container-lowest: '#0a0e13'
  surface-container-low: '#181c21'
  surface-container: '#1c2025'
  surface-container-high: '#262a30'
  surface-container-highest: '#31353b'
  on-surface: '#e0e2ea'
  on-surface-variant: '#c2c6d6'
  inverse-surface: '#e0e2ea'
  inverse-on-surface: '#2d3136'
  outline: '#8c909f'
  outline-variant: '#424754'
  surface-tint: '#adc6ff'
  primary: '#adc6ff'
  on-primary: '#002e6a'
  primary-container: '#4d8eff'
  on-primary-container: '#00285d'
  inverse-primary: '#005ac2'
  secondary: '#4edea3'
  on-secondary: '#003824'
  secondary-container: '#00a572'
  on-secondary-container: '#00311f'
  tertiary: '#d0bcff'
  on-tertiary: '#3c0091'
  tertiary-container: '#a078ff'
  on-tertiary-container: '#340080'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#d8e2ff'
  primary-fixed-dim: '#adc6ff'
  on-primary-fixed: '#001a42'
  on-primary-fixed-variant: '#004395'
  secondary-fixed: '#6ffbbe'
  secondary-fixed-dim: '#4edea3'
  on-secondary-fixed: '#002113'
  on-secondary-fixed-variant: '#005236'
  tertiary-fixed: '#e9ddff'
  tertiary-fixed-dim: '#d0bcff'
  on-tertiary-fixed: '#23005c'
  on-tertiary-fixed-variant: '#5516be'
  background: '#101419'
  on-background: '#e0e2ea'
  surface-variant: '#31353b'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.02em
  display-lg-mobile:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-lg:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.005em
  headline-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: 0em
  body-lg:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 22px
    letterSpacing: 0em
  body-md:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0em
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
    letterSpacing: 0.01em
  label-md:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.02em
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.04em
  label-xs:
    fontFamily: JetBrains Mono
    fontSize: 10px
    fontWeight: '600'
    lineHeight: 12px
    letterSpacing: 0.06em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 0.75rem
  margin: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
---

## Brand & Style

The design system establishes a high-stakes, mission-critical operational cockpit for enterprise supply chain visibility and autonomous risk resolution. The aesthetic merges the relentless density and tactical precision of telemetry radar displays, defense-grade intelligence consoles, and modern low-latency software. 

The emotional tone balances absolute calm with zero-latency situational awareness:
- **Hyper-legible & Tactical:** Prioritizes functional scan speed over decorative padding. Information density remains compact, crisp, and predictable.
- **Governed & Traceable:** Evokes rigorous accountability through explicit data provenance, state verification indicators, and clear lineage badges.
- **Engineered Precision:** Uses sharp hairline borders, subtle status glows, and dark-mode depth tiers to prevent cognitive fatigue over extended 12-hour shifts.

## Colors

The palette operates in strict dark mode by default, anchored by a deep obsidian core (`#0B0F14`) that recedes into the background, allowing telemetry surfaces (`#111827`, `#1A2332`) and semantic alerts to stand forward with absolute clarity.

### Semantic Systems & Functional Tokens

1. **Brand & Action Layer:**
   - **Primary Action:** Electric Blue (`#3B82F6`), transitioning to `#2563EB` on interactive active states.
   - **Borders & Dividers:** Tactical hairline gray-slate (`#243044`).

2. **Risk Severity Matrix:**
   - **Critical:** `#EF4444` (Vibrant crimson; signals immediate operational disruption).
   - **High:** `#F97316` (High-contrast orange; threshold breach imminent).
   - **Medium:** `#EAB308` (Amber/yellow; degraded performance warning).
   - **Low:** `#22C55E` (Emerald green; nominal operational threshold).
   - **Informational:** `#64748B` (Neutral slate; reference logging).

3. **Evidence Precedence Archetypes:**
   - **REAL:** Solid `#10B981` (Confirmed sensor telemetry, IoT pings, stamped customs events).
   - **ESTIMATED:** `#F59E0B` (Statistical projection, ETA inference; rendered with dashed indicator strokes).
   - **SIMULATED:** `#8B5CF6` (Synthetic twin, Monte Carlo stress tests; rendered with dotted micro-borders).

4. **Verification & Audit Lifecycle:**
   - **VERIFIED:** `#10B981`
   - **PARTIALLY_VERIFIED:** `#F59E0B`
   - **FAILED:** `#EF4444`
   - **PENDING:** `#60A5FA`
   - **CONFLICT:** `#F43F5E`
   - **EXPIRED:** `#6B7280`

Text tokens adhere to high-contrast WCAG AAA/AA values: Primary text sits at `#F9FAFB` (98% luminance), Secondary at `#9CA3AF`, and Muted/Metadata at `#64748B`.

## Typography

The type system implements a strict dual-font structure:
- **Inter** provides high-neutrality UI structuring, narrative reading, and panel headers.
- **JetBrains Mono** enforces structured scanning across high-velocity telemetry, lat/long geo-coordinates, bill of lading hashes, container IDs, and strict timestamp comparisons.

### Tabular Alignment Rules
All numerical figures, financial impact estimates, disruption lead times, and status tags rendered in `JetBrains Mono` must inherit `font-feature-settings: "tnum" 1, "zero" 1`. This enforces strict tabular alignment across data grids, preventing jitter during live socket re-renders.

## Layout & Spacing

The layout is built for real-time dense intelligence consoles. It utilizes a fluid multi-pane workspace driven by collapsible inspection sidebars, fixed command bars, and dynamic telemetry grids.

### Spatial Rhythm
- **Core Baseline:** Built upon a compact 4px grid. Standard row heights sit strictly between `36px` (compact telemetry logs) and `44px` (actionable governance lists with inline approvals).
- **Desktop (1440px+):** Tri-pane architecture: Navigation Rail (56px) + Primary Entity Explorer / Topology Graph (fluid, min 640px) + Deep Telemetry & Action Inspector (380px–480px fixed-width dock).
- **Tablet / Responsive Consoles (768px - 1439px):** Inspector transitions into a sliding overlay surface; topology maps preserve operational aspect ratios with dedicated overlay controls.
- **Field Terminal / Mobile (<768px):** Single-column stacked workflow. Data tables collapse to tabular key-value cards. Telemetry switches to tab-swapped view modes.

## Elevation & Depth

Visual hierarchy does not rely on traditional muddy drop shadows. Instead, the design system uses calibrated surface tonal tiers bounded by structural 1px hairline strokes, accompanied by tactical illumination glows for emergency alerts.

### Surface Tiers
- **Base Deck (`#0B0F14`):** Canvas background, persistent structural underlay.
- **Surface Layer 1 (`#111827`):** Primary workspace panels, passive data tables, inactive card modules.
- **Surface Layer 2 (`#1A2332`):** Focused inspection sidecars, active rows, modal envelopes, sticky table headers.
- **Surface Layer 3 (`#243044`):** Flyout tooltips, context menus, drag overlays.

### Borders and Edge Luminance
All containers are defined by a crisp `1px solid #243044` hairline border. When an element enters an active or processing state, the border shifts to `#3B82F6` with an accompanying subtle accent diffusion: `0 0 12px -2px rgba(59, 130, 246, 0.25)`.

### Risk Halo Treatments
Critical disruption alerts gain an ambient status halo to draw peripheral attention across multi-monitor control displays:
- **Critical Pulsing Node:** `box-shadow: 0 0 8px 1px rgba(239, 68, 68, 0.4)`
- **Simulation Preview Boundary:** Border style transitions to `1px dashed #8B5CF6` with an inner wash of `rgba(139, 92, 246, 0.04)`.

## Shapes

The interface balances industrial precision with contemporary refinement through restrained, deliberate roundedness. Standard components adhere to an architectural `0.25rem` (4px) curvature, preserving a tactical instrument aesthetic. 

Higher-level contextual surfaces (such as modals, drawer sheets, and grouped metric cards) scale to `rounded-lg` (8px), preventing sharp corners from conflicting with outer monitor bezels while sustaining an engineered feel. High-density data chips, status badges, and pills remain bounded at `0.25rem` (4px) to maximize internal horizontal area for monospaced metrics.

## Components

### 1. Action Buttons & Governance Triggers
- **Primary Operational Button:** Solid `#3B82F6` fill, `#FFFFFF` Inter bold text, 36px height, 4px corner radius. Hover transitions to `#2563EB`. Active state invokes a 1px ring offset (`rgba(59, 130, 246, 0.4)`).
- **Destructive / High Risk:** Deep red tint background (`rgba(239, 68, 68, 0.12)`), `#EF4444` border and label. Hover shifts to solid `#EF4444` with `#FFFFFF` text.
- **Autonomous Override (Dual-Action):** High-density split button with primary trigger paired with an audit configuration dropdown caret, divided by a 1px `#1A2332` separator.

### 2. Status & Evidence Badges
- **Real Evidence Badge:** Solid green indicator pip (6px circle, `#10B981`), `JetBrains Mono` label, background `rgba(16, 185, 129, 0.1)`, hairline border `rgba(16, 185, 129, 0.25)`.
- **Estimated Precedence Badge:** Amber indicator (`#F59E0B`), background `rgba(245, 158, 11, 0.08)`, bounded by a `1px dashed #F59E0B` outline.
- **Simulated Projection Badge:** Violet indicator (`#8B5CF6`), bounded by a `1px dotted #8B5CF6` outline with tracking-wide uppercase typography.

### 3. High-Density Telemetry Tables
- **Metrics & Sizing:** Fixed header at 32px height; data rows calibrated between 36px (compact) and 44px (with actions).
- **Row Styling:** Hairline bottom separator (`1px solid #243044`). Zebra striping is omitted in favor of clean hover highlights (`rgba(59, 130, 246, 0.05)`).
- **Cell Behavior:** Monospaced data points (coordinates, timestamps, vessel MMSI) display left-aligned with subtle contrast differences: label keys in `#64748B`, live values in `#F9FAFB`.

### 4. Input Fields & Parameter Steppers
- **Search & Filters:** Dark background (`#111827`), 1px structural border (`#243044`), 32px or 36px height. Leading search iconography in `#64748B`. Focus state initiates `#3B82F6` border with 0-blur highlight.
- **Command Palette Quick-Switchers:** JetBrains Mono inline keyboard shortcut keys styled in elevated `#1A2332` keycaps (`1px solid #243044`, 10px text).

### 5. Tactical Panels & Sensor Cards
- **Structure:** Encased in `#111827` with 8px radius and 1px `#243044` perimeter border. Header bar features an integrated 32px utility strip with node telemetry status, refresh countdown timers, and full-screen expansion triggers.

### 6. Specialized Platform Components
- **Lineage Breadcrumb Bar:** Direct link visualization showing data provenance from source (e.g., AIS Satellite -> Carrier EDI -> Inferred Risk Model -> Automated Reroute Approval).
- **Audit Verification Rail:** Vertical stepper displaying cryptographically signed validation checkpoints (`VERIFIED`, `CONFLICT`, etc.) alongside explicit timestamps.