# StartLine: Project Brief

## 1. Project Overview

A website that helps fantasy football managers make weekly start/sit decisions by combining:
- **DFS pick'em projections** (Underdog Fantasy, PrizePicks) — third-party projected fantasy point totals per player
- **Sportsbook betting data** (player prop yardage lines, anytime-TD odds, game totals/spreads) — market-implied expectations for player performance
- **Expert rankings** (FantasyPros Expert Consensus Rankings — see Section 4) — qualitative, human-expert weekly rankings, used as a separate "expert perspective" lens rather than folded into the numeric projection
- **The site's own blended "expected fantasy points" number** and a **start/sit recommendation** per player, informed by both the quantitative blend and the expert-perspective lens

The core idea: betting markets and DFS projection services are each independently pretty good at predicting player performance, and they don't always agree. Blending them (and showing *why* they disagree) should produce a better-informed decision than any single source alone. Expert rankings add a third, qualitative check — human analysts often factor in things (scheme fit, coaching tendencies, locker-room news) that don't show up cleanly in numbers, so they're kept as a separate signal rather than averaged into the math.

**Owner's technical background:** No prior coding experience. This project will be built primarily by Claude (via Claude Code), with this document as the guiding spec.

## 2. Goals & Success Criteria

- **v1 priority: speed over polish.** Get a working tool in front of real use (this season) even if the UI is plain and the feature set is narrow.
- **Long-term potential: public-facing.** Not required for v1, but architecture decisions should not paint us into a corner — avoid anything that only works for a single hardcoded user if it's cheap to avoid.
- **Success for v1** = for a given week, the owner can look up any relevant player and see: a blended expected points number, the inputs that produced it, and a start/sit call — updated automatically, not by hand.

## 3. Core Features

### v1 (MVP)
- Player lookup/search (start with a subset — e.g., skill positions: QB/RB/WR/TE)
- For each player, display:
  - Underdog and/or PrizePicks projected fantasy points
  - Relevant sportsbook lines (rushing/receiving/passing yard props, anytime TD odds, game total/spread as context)
  - A blended **expected fantasy points** number (methodology below)
  - An **expert perspective** indicator (e.g., "Top 12 at position," "Flex-worthy," "Bench" — derived from expert rankings, shown alongside but separate from the quant number)
  - ~~A simple **Start / Sit / Toss-up** recommendation~~ — **removed 2026-07-29.** The recommendation compared the blended number to a flat, hardcoded per-position threshold that had no way to account for league format (team count, roster spots, PPR/superflex/etc.) — a 12-team-league "Start" could easily be a 10-team-league lock or a 14-team-league bench piece, and the tool had no way to know which. Rather than show a confident-looking badge built on an assumption that's wrong for most leagues, v1 now just shows the raw numbers (DFS projection, betting-derived estimate, blended) and lets the user apply their own league's context. See Section 5 below for the real fix path (compare against the user's actual Sleeper league roster instead of a flat threshold) — deferred, not abandoned.
- Data refreshes automatically on a schedule (not manual re-entry) — see Section 4 on feasibility per source
- Basic table/dashboard view, sortable by position and expected points
- **Site structure (added 2026-07-29, see `PROJECT-PLAN.md` for full status):** grew from a single dashboard into
  a 5-page site — Landing, Dashboard, Player detail (all live), plus Comparison and About/Methodology (still
  placeholders as of this writing). Player detail shows a full per-market breakdown: pooled threshold curves
  across every bookmaker, hoverable "chance of going over" trend history (Phase 3B — day-by-day probability
  tracking, separate from the "historical accuracy tracking" idea listed under Later phases below), and
  summary-box numbers that link/hover into the section that produced them.

### Later phases (not v1)
- User accounts, saved rosters, league sync (Sleeper/ESPN/Yahoo import)
- Head-to-head comparison tool ("start Player A or Player B")
- Historical accuracy tracking (did the blended number beat either source alone?)
- Mobile-friendly polish, notifications ("your player's line moved")
- Public launch: multi-user support, rate-limiting, billing if paid data sources are involved

## 4. Data Sources — Validated Decisions (as of July 2026)

### Sportsbook odds & player props → **The Odds API**
Official docs: `the-odds-api.com` (verify the hyphens — see warning below)

- Covers exactly what we need for NFL: passing/rushing/receiving yards, receptions, anytime/1st/last TD scorer, pass/rush/reception TDs, and more, all as clean Over/Under or Yes/No markets pulled from real US sportsbooks
- Pricing tiers: **Free** (500 credits/mo, all sports/bookmakers/markets, no historical data) → **$30/mo** (20,000 credits, adds historical odds) → higher tiers up to $249/mo for very high volume
- Player props are pulled per-event (one game at a time), which uses credits faster than the main odds feed — worth starting on the free tier during development to see real credit consumption before committing to a paid plan
- **⚠️ Important:** there is an active impersonator site, `theoddsapi.com` (no hyphen), reselling this data without authorization and billing separately from the real company. Only use `the-odds-api.com` (with hyphens). This is worth double-checking yourself before signing up, not just taking my word for it.
- **Alternative considered and rejected:** BoltOdds — real-time WebSocket/play-by-play streaming starting at $99/mo. Not chosen: it's built for live in-play betting/trading (second-by-second updates), which this project doesn't need since decisions are made pre-game on a scheduled pull, and it costs 3–10x more for that unused capability.

### Expert rankings → **FantasyPros Expert Consensus Rankings (ECR) API**
Official docs: `fantasypros.com/api-data`

- One clean, official REST API (`api.fantasypros.com`) that already aggregates 100+ fantasy analysts into a single weekly consensus rank — this covers "The Athletic and other sites" better than chasing individual paywalled outlets, since it's already the aggregate
- Supports NFL with position and scoring-format filters (STD/PPR/HALF) — **half-PPR is directly supported**, matching our v1 scoring decision
- A free key exists for prototyping; production access (needed for a live site) comes bundled with a paid **MVP** or **HOF** membership, roughly **$6–13/month** depending on commitment length (cheapest with an annual plan)
- This replaces the original "scrape The Athletic" idea — no scraping, no paywall workaround needed, and it's a broader consensus than any single outlet

### Underdog / PrizePicks projections → **automated via The Odds API's `us_dfs` region**
- **Correction (2026-07-28):** the original research below was wrong in practice — neither platform has *its own* public API, but The Odds API (already integrated for sportsbook props) separately aggregates both as bookmakers under a dedicated `us_dfs` region: `prizepicks` and `underdog` bookmaker keys, exposing a `player_fantasy_points` "Fantasy points (Over/Under), DFS only" market. This is an official, documented part of the same product we already pay/don't-pay for — not a scrape or ToS gray area.
- **Decision:** pull these automatically alongside sportsbook props, using the same API key. No manual entry needed for v1. Combining the `us_dfs` region into the same per-event odds call costs additional credits (credit cost = markets × regions), so this uses free-tier credits faster than sportsbook props alone — worth watching during the season.
- Original (superseded) research: it was believed neither platform offered any API access, official or aggregated, and that the only options were unofficial/reverse-engineered endpoints or paid scrapers (e.g. via Apify) of uncertain ToS standing. That specific claim was wrong; the aggregated `us_dfs` access above replaces it entirely, so there's nothing left to revisit in Phase 2 for this data source.

### Supporting data (rosters, injuries, team/position) → **Sleeper API**
Official docs: `docs.sleeper.com`

- Free, public, official, read-only — no API key or account needed
- Provides player team, position, and current injury status (Out/Doubtful/Questionable/etc.), which is exactly what's needed to avoid recommending a player who's inactive
- Rate limit is generous (roughly 1,000 requests/minute) — non-issue at this scale

### Estimated v1 monthly cost
~$30/mo (odds, once past free-tier development) + ~$6–13/mo (FantasyPros) ≈ **$36–43/month**, plus hosting (many options have a free or near-free tier for a project this size). Underdog/PrizePicks and Sleeper are $0. Nothing here should be signed up for automatically — decide and create these accounts yourself when ready to start building.

**Update (2026-07-29, see `PROJECT-PLAN.md` decision D5 for the full breakdown):** the original $30/mo Odds API
figure assumed the 20K-credit tier. The Phase 3B trend feature's pull cadence (hourly during game windows) needs
~29K–84K credits/month, which doesn't fit that tier — **recommended $59/mo / 100K-credit tier for the season**
instead. Purchase still pending owner confirmation as of this writing. Revised full-build estimate ≈ **$65–75/mo
in-season** (odds + FantasyPros + hosting), lower off-season.

## 5. Expected Points Methodology (starting point — expect to refine)

Rough v1 approach, in plain terms:

1. **From DFS projections:** take Underdog/PrizePicks projected points directly (they're already fantasy-scored).
2. **From betting lines:** convert props into a fantasy-point estimate:
   - Yardage props (e.g., "O/U 65.5 rushing yards") → use the line itself as a point estimate, scored per your league's rules (e.g., 0.1 pt/yard, plus 0.5 pt/reception for half-PPR)
   - Anytime-TD odds → convert American/decimal odds to implied probability (removing vig where possible) → multiply by 6 (or 4 for passing TDs) for expected TD points
   - Game total/spread → used as context (game script, blowout risk) rather than a direct point input at first
3. **Blend:** start with a simple average or weighted average of the DFS-projection number and the betting-derived number. Weighting can be tuned later based on which source proves more accurate. **Expert rankings are intentionally excluded from this blend** — they stay qualitative and are not converted into points.
4. ~~**Start/Sit call:** compare the blended number to a positional replacement-level threshold...~~ **Removed 2026-07-29** — a flat per-position threshold (e.g. "18 pts = startable QB") can't account for league depth/format, and showing a confident-looking Start/Sit/Toss-up badge built on a wrong assumption is worse than showing none. v1 now stops at the blended number and lets the user decide. **Real fix, deferred not abandoned:** compare the blended number directly against the alternatives on the user's actual bench, pulled from their real Sleeper league (Sleeper already supports fetching a specific league's rosters/settings for free, given a league ID) — this was always the "right" version per the original plan, just not built yet.
5. ~~**Apply the expert-perspective lens on top of the quant call**~~ — the expert-agreement/conflict messaging was part of the removed Start/Sit call and went with it. The underlying expert-perspective indicator itself (Top 12/Flex-worthy/Bench label, Section 3) is unaffected and still shown separately once FantasyPros is configured.

This should be treated as a first draft — refining the blend using real results, and eventually rebuilding the start/sit call against real league rosters, is an explicit part of the roadmap, not a one-time decision.

## 6. Technical Architecture (recommendation, not final)

Given "automated data + could go public later + move fast now":

- **Backend:** Python (FastAPI) or Node — handles scheduled data pulls, the blending calculation, and serves the frontend
- **Scheduled jobs:** pull fresh odds/projections on a cron schedule (e.g., a few times daily during the season)
- **Database:** start simple (SQLite) — easy to migrate to Postgres later if it goes multi-user
- **Frontend:** a simple web dashboard (can start as a basic React app or even server-rendered pages — doesn't need to be fancy for v1)
- **Hosting:** a low-friction platform suited to small projects (e.g., Railway, Render, Vercel) — cheap or free to start, easy to scale later
- Build with light separation between "data layer," "scoring/blending logic," and "presentation" from the start — costs almost nothing now and makes the public-facing path much easier later

## 7. Roadmap

- **Phase 1 (now):** Confirm data source feasibility → build core pipeline (pull data → blend → store) → bare-bones dashboard → usable for the owner this season
- **Phase 2:** Automate fully, improve UI, add historical accuracy tracking, tune the blending formula
- **Phase 3:** Multi-user support, accounts, league imports, and (if pursued) public launch considerations — auth, scaling, cost of paid data sources at higher usage

## 8. Open Questions

- Which positions to support first (skill positions only, or also K/DST/IDP)?
- Exact hosting provider (a few good low-cost options exist — pick when ready to deploy)

**Settled:**
- **Scoring format:** build v1 against **half-PPR**. Design the scoring logic as a configurable module (not hardcoded), since standard and full-PPR support are planned for a later phase.
- **Budget:** no fixed ceiling for data/hosting costs. However, any paid service, subscription, or recurring cost should be surfaced to the owner *before* being adopted — not after the fact. Free/low-cost options should still be preferred by default when they're roughly as good.
- **Data sources (see Section 4):** sportsbook odds/props → The Odds API; Underdog/PrizePicks projections → also The Odds API (`us_dfs` region — automated, no manual entry); expert rankings → FantasyPros ECR API; supporting roster/injury data → Sleeper API (free).

## 9. Notes for Claude (working on this project)

- The owner has no coding background — explain technical decisions in plain language, and avoid assuming familiarity with dev tools/terminology.
- Bias toward shipping something functional over building the "ideal" architecture — v1 speed is the stated priority.
- Treat Section 4 (data sourcing) as settled — the research is done. First real build task is setting up accounts/API keys for The Odds API and FantasyPros (owner does this personally, since it involves payment), then building the data pipeline against them.
- This document is a living brief — as decisions get made (data providers chosen, formula tuned, etc.), it should be updated so future sessions stay in sync. For day-to-day implementation status, open decisions, and a running log of what's been built, see `PROJECT-PLAN.md` instead — it's updated far more frequently than this brief and is the source of truth for "where things stand right now."
- **Cost transparency:** there's no hard budget cap, but always flag pricing/subscription costs to the owner *before* signing up for or integrating a paid service — never assume a cost is acceptable just because there's no ceiling.
