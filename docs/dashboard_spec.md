# Dashboard Specification

This document details the functional specifications, design aesthetics, and structured layout sections of the Market Sniffer 2000 Professional Financial Dashboard.

## Design Aesthetic

- **Theme**: Premium dark financial layout (Slate and Dark grey color palette, high contrast, clean boundaries).
- **Typography**: Clean sans-serif sans spacing system using browser native-fallback stack.
- **Interactivity**: Light animations on hover, transition states for KPI cards, collapsed technical appendix.
- **Charts**: Server-rendered inline SVGs with smooth line layouts and background gradients. Dependency-free.

## Dashboard Sections

### 1. Header
- Displays the title "Market Sniffer 2000".
- Shows evidence calculation and web generation timestamps.
- Displays system data freshness statuses: Data collection run status, Metrics calculation run status, and active quality warning count.

### 2. Market Brief
- **Definition**: A deterministic, plain-English summary of the current market state.
- **Constraints**: Entirely mathematical and descriptive. No recommendations or predictions.
- **Forbidden Vocabulary**:
  - `buy`, `sell`
  - `bullish`, `bearish`
  - `risk-on`, `risk-off`
  - `market will`, `should outperform`

### 3. Key Market Strip
A series of 8 compact KPI tiles showing:
1. **SPY**: Close price and 21d return.
2. **Trend**: Distance from 200-day moving average and 63-day return.
3. **Breadth**: Proportion of assets above 50-day and 200-day moving averages.
4. **Volatility**: Current VIX level and 5-observation change.
5. **Credit**: High-yield Option-Adjusted Spread (OAS) and 21d change.
6. **Rates**: 2s10s yield spread and 3m10y yield spread.
7. **Leadership**: Top performing equity group relative to SPY over 21 days (selected from XLK, XLF, XLE, AI Infrastructure).
8. **Evidence**: Count of active/elevated evidence events in the last 7 days.

### 4. What Changed
- Lists curated, clustered evidence events from the last 14 days, capped at 5 items.
- Repeated trigger events of the same rule are grouped together to prevent spammed entries, displaying trigger frequency and latest value.

### 5. Market Map
A 2x2 grid panel displaying detailed metrics for:
- **Trend & Structure**: SPY close, 5d return, 21d return, 63d return, distance from 200d MA.
- **Breadth & Leadership**: Breadth above 50d/200d, XLK vs SPY, AI Infra vs SPY, XLF vs SPY, XLE vs SPY.
- **Rates & Credit**: 2s10s spread, 3m10y spread, HY OAS, HY OAS change.
- **Volatility & Cross-Asset**: VIX level, VIX change, Gold vs SPY, NFCI level, NFCI change.

### 6. Data Confidence
- Displays unresolved quality items, blocking metrics, unavailable metrics, and stale metrics counts.
- Groups quality items by type and offers an impact statement regarding the usability of core metrics.

### 7. Technical Appendix
- Collapsed by default.
- Details total metrics count, evidence rule count, formula versions, registered source profiles, database type, and read-only boundaries.
