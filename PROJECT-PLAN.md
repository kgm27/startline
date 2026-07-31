# Going-Live Plan: StartLine

**Goal:** finalize the product, then take the app that currently runs only on your laptop (`localhost:8000`) and
put it on the public internet as a polished, shareable, resume-worthy site — reliably, safely, and without
accidentally running up your paid API bill.

**How to use this doc:** This is the master checklist for the whole "ship it public" effort. It's designed so you
can work on it across *different* chats. At the start of any new chat, tell Claude: *"Read PROJECT-PLAN.md and
let's continue."* Each task has a checkbox — check it off (`[x]`) as you finish. The **Decisions still open**
section is the first thing to settle; later steps depend on those answers.

The plan has two parts:
- **Part 1 — Finalize the product** (Phases 1–3): decide the pages, finalize each page's UX, finish the data
  sources. *This comes first — you shape what the site IS before you ship it.*
- **Part 2 — Ship it live** (Phases 4–9): make it deployable, secure it, deploy, automate, polish, launch. The
  site is **resume-ready at the end of Phase 9**. **Phase 10 (mobile polish) is optional** — desktop is all the
  resume needs.

> Companion doc: full product spec is in [`fantasy-football-advisor-project-brief.md`](fantasy-football-advisor-project-brief.md).

---

## Where things stand today (starting point)

- **Stack:** Python 3.9 · FastAPI · SQLite · Jinja2 server-rendered pages · Alpine.js (via CDN, no build step).
- **Runs:** locally only, `uvicorn app.main:app --port 8000`.
- **Pages that exist now:** the Dashboard (`/`) and the Player detail page (`/player/{id}`).
- **Data:** `data/advisor.db` (~500 KB) holds a real Week 15 2025 backtest. `*.db` is gitignored (not in the repo).
- **Secrets:** `.env` holds the paid Odds API key. `.env` is gitignored (good — keys are not in git).
- **Known risk:** the `POST /refresh` endpoint has **no authentication** and spends real Odds API credits. It must
  be removed from the public UI and locked down before the site is public.
- **Season timing:** It's the off-season (July 2026). The NFL 2026 season starts early September. Until then the
  live data pipeline has no current games — the site can run as a **labeled demo** of the Week 15 2025 backtest.

---

## Decisions

**Settled:**
- ✅ **Page inventory:** Landing (new) · Dashboard (exists) · Player detail (exists) · Comparison (new) · About/Methodology (new).
- ✅ **Comparison page scope:** two players head-to-head (DFS / betting / blended numbers side by side).
- ✅ **FantasyPros:** a launch blocker — the expert-rankings column must be live before going public.
- ✅ **D3 — Off-season display.** Ship now as a clearly-labeled "Week 15 2025 demo." Built: `/dashboard` and
      `/player/{id}` now default to the most recent week with real data (Week 15) instead of the actual current
      NFL week (which returns nothing off-season) whenever no `?week=` is given, and show a "Demo data — Week 15,
      2025 season" banner whenever the displayed week isn't genuinely live. An explicit `?week=N` is still always
      honored as-is. This was a real gap, not just a documentation decision — visiting the site with no query
      params previously showed a blank "Week 1" page.
- ✅ **D1 — Hosting provider (decided 2026-07-30):** **Render, always-on plan (~$7/mo).** Chosen over the free
      tier specifically to avoid the ~30-60s sleep/wake delay on a resume link a recruiter might click cold.
      Not yet signed up for, that's Phase 6.1.
- ✅ **D2 — Custom domain (decided 2026-07-30):** yes, a custom domain (~$12/yr) rather than the free host URL.
      Still need to actually pick and register a domain name, a separate step, not yet done. Ties to Phase 8.2.
- ✅ **D4 — Database strategy (decided 2026-07-30):** **SQLite on a persistent disk**, matches the current setup,
      no migration needed for v1.

**Still open (settle these next):**
- [ ] **D5 — Pull cadence & Odds API plan (for the trend feature, Phase 3B).**
      **Cadence — SETTLED (season only; off-season → drop to the free tier):**
      - Baseline: **2 pulls/day, every day** (~8am + ~6pm ET) — catches injury news + weekly line drift.
      - **Hourly 8am–1am ET on Saturday AND Sunday.** Saturday is included on purpose — it's the day people set
        lineups, so the trend is most useful then; the Saturday pull fetches the upcoming Sunday slate.
      - **Hourly ~5pm–1am ET on Thursday & Monday nights**, fetching only that one night game.
      - **Overnight 1am–8am ET: paused** (games are over, lines don't move). Note: 1am *Eastern* is the cutoff —
        the latest SNF/MNF finishes by ~12:30am ET; 1am Pacific (4am ET) would just be dead pulls.
      - The expensive *full* alternate-line pull stays **weekly** (feeds the detailed player pages); everything
        above is the cheap *headline* pull that feeds the trend line.
      **Cost:** ~29,000 credits/mo built optimized, up to ~84,000 built simply — both exceed the 20K plan, both fit
      the 100K plan. **Plan — recommend the $59/mo / 100K tier for the season** (huge headroom; the $30/20K tier
      can't fit hourly on both weekend days without dropping to every-2-hours). 🔴 **PLAN PURCHASE: pending owner
      confirmation** — don't switch the hourly job on until the tier is in place.

---

# PART 1 — Finalize the product

## Phase 1 — Confirm the pages (site map)

*Goal: agree the full set of pages and how they connect, before building any of them.*

- [x] **1.1** Confirm the five pages and each one's job:
      - **Landing** *(new)* — the front door: what the site is, the one-line pitch, a button into the Dashboard.
      - **Dashboard** *(exists)* — the main sortable/filterable table of players and their blended scores.
      - **Player detail** *(exists)* — the deep dive for one player (per-source numbers, threshold tables).
      - **Comparison** *(new)* — pick two players, see their DFS / betting / blended numbers head-to-head.
      - **About / Methodology** *(new)* — plain-language explanation of how the blend works (the resume centerpiece).
- [x] **1.2** Decide the top navigation (what links appear on every page, in what order). Settled: logo (→ Landing)
      · Dashboard · Compare · About, active page highlighted.
- [x] **1.3** Decide how a user gets from the Dashboard/Player pages into a Comparison (e.g. a "compare" action on
      each row, or a player-picker on the Comparison page itself). Settled: start with a player-picker on the
      Comparison page itself; a per-row "compare" shortcut can be added later.

## Phase 2 — Finalize the UX for each page

*Goal: lock down what each page looks like and does. Build/refine one page at a time.*

- [x] **2.1** **Landing page** — hero headline, one-sentence explanation, clear call-to-action into the Dashboard.
- [x] **2.2** **Dashboard** — 🔴 **remove the public "Refresh Data" button** (refresh will move to an automated job
      + a protected trigger — see Phases 5 & 7). Keep the client-side filters, sort, and search. Confirm each row
      links to the Player detail page and can start a Comparison. Done: button removed (the `/refresh` endpoint
      itself is untouched — locking it down is Phase 5.1). Added a League Format dropdown (Half PPR / Standard /
      Full PPR / Superflex / Dynasty / Best Ball) — only Half PPR is wired to real data; selecting any other
      format hides the whole dashboard and shows a "coming soon" message instead. Added a FLEX filter pill
      (RB/WR/TE combined). Injury column kept (real data — 72/969 players have a designation) with a custom
      styled hover tooltip defining each code (Questionable/Doubtful/Out/IR/PUP/DNR/NA). Added colored team
      badges using each team's real brand colors. DFS Proj./Betting Est./Blended now display to one decimal
      (tenths) instead of two — display-only, sorting still uses full precision.
- [x] **2.3** **Player detail** — review the collapsible threshold tables and per-source breakdown; tighten spacing
      and labels so it reads cleanly to a stranger. Done: found and fixed a real bug where every small per-market
      table's header used the same `position: sticky` CSS as the Dashboard's one long table — on player pages,
      with a dozen+ short tables, this made headers detach and float/duplicate down the page as you scrolled,
      leaving blank gaps. Scoped sticky headers to the Dashboard table only. Also normalized number formatting:
      DFS projection rows and the three summary-box numbers (DFS/Sportsbook/Blended) were printing raw
      unrounded precision from the database (e.g. "19.0", "20.05", "22.0" side by side); now consistently 2
      decimals everywhere on the page, matching the market-block math below. Verified live in-browser (Joe
      Burrow, McCaffrey, Dak Prescott with an injury tag, and a player missing DFS data) — tooltips, threshold
      expand/collapse, and empty states all confirmed working.
- [x] **2.4** **Comparison page** — design the two-player picker and the side-by-side layout (which numbers to show,
      how to highlight the difference). Done: two searchable pickers (typeahead dropdown, reusing the Dashboard's
      player dataset via a new shared `_player_rows()` helper so Dashboard and Compare can never disagree on a
      player's numbers) with a swap button and a shareable `?a=&b=` URL (synced via `history.replaceState`, same
      convention as `?week=` elsewhere). Results table shows Blended first (then DFS Projection, Sportsbook
      Projection, Expert Perspective) — the whole column of whichever player has the higher Blended score is
      tinted, so the "start this one" call reads at a glance; each row also bolds+deltas whichever side wins that
      specific metric. The Injury row was replaced with a callout badge (amber pill, hover tooltip) directly under
      the player's name/team so it's visible without scanning a table row. Verified live in-browser: search/select
      for both slots, swap, Change/reset, URL sync, and the injury callout (tested with Dak Prescott/Questionable).
- [x] **2.5** **About / Methodology**: write the plain-language explanation of the DFS + odds + expert blend, and
      why blending beats any single source. This is what sells the project. Done: full page covering why one
      source isn't enough, the three inputs, and a 4-step numbered walkthrough of how they become one blended
      score (with real half-PPR scoring rates). The worked example is **live, not hardcoded**: `/about` now
      computes this week's #1 blended-score player server-side (same `_player_rows()` helper as Dashboard/Compare)
      and shows their real DFS/Sportsbook/Blended numbers with a link straight into their actual Player detail
      page, so the methodology page is provably accurate rather than an illustrative mockup. Verified live in-browser,
      including clicking through to the example player's page and confirming the numbers match exactly.
- [x] **2.6** **Global UX**: nav bar, page titles, favicon, and a "demo data, Week 15 2025" banner while
      off-season (ties to **D3**). *(Desktop is the priority; dedicated mobile work is deferred to optional Phase 10.)*
      Nav bar/page titles done (Phase 1). Demo banner done (see D3, above). Favicon done: a simple SVG (purple
      rounded square, white "FF", matching the nav logo) at `/static/favicon.svg`, cache-busted the same way as
      `style.css`/`app.js`. Owner is fine using this proposed version for now and may revisit the design later.

## Phase 3 — Finish the data sources (FantasyPros — launch blocker)

*Goal: the expert-rankings column is live, not a placeholder "—".*

- [x] **3.1** Get a FantasyPros API key. *(You had trouble signing up before, Claude can walk you through it step
      by step, and flag any cost before you commit; see [`fantasy-football-data-sources`] notes.)* Done: key
      obtained 2026-07-30.
- [x] **3.2** Add the key to your `.env` and confirm the app picks it up. Done: key added, confirmed working with
      a live test call. 🔴 **Found a real blocker**: the key is on FantasyPros' free tier, which per the live API
      response (`"tier": "free"`, `"public_api_limited": true`) always returns Week 1 preseason rankings no
      matter what week is requested (tested week 15 and week 3, both 2025 and 2026, all returned the same Week 1
      data). Full weekly archives need the paid MVP/HOF membership already flagged in the brief (~$6-13/mo).
      Owner is upgrading later today; 3.3-3.5 are paused until then.
- [ ] **3.3** Un-hide / populate the expert column on the Dashboard and Player detail pages (the code already
      degrades gracefully; this switches it on).
- [ ] **3.4** Decide how expert rankings appear on the new Comparison page.
- [ ] **3.5** Verify real expert data flows through end-to-end.

## Phase 3B — Prediction-trend feature (new)

*Goal: show how a player's projection is moving over time — a line chart fed by a daily data pull. This is a
standout resume feature (it shows the numbers changing as real information arrives before kickoff).*

*How it fits the season timing: a trend needs several days of history to show anything, so this chart stays empty
until the daily job has been running for a few days in-season. During the Week 15 2025 demo there's no daily
history to plot — plan for a graceful "not enough history yet" state.*

- [x] **3B.1** **Store daily snapshots.** Add a new table (e.g. `PredictionSnapshot`) that records each player's
      headline numbers: DFS points, betting-derived points, blended score, stamped with the date. Today's tables
      keep only the latest values; this new table is what makes a *history* to chart. Additive, doesn't change the
      existing tables. Done: `PredictionSnapshot` added to `models.py` (player, week, dfs_pts, betting_pts,
      blended, snapshot_date), same one-row-per-day pattern as `ThresholdSnapshot`.
- [x] **3B.2** **Write a snapshot each day.** Have the daily job (Phase 7) save one snapshot row per player per day.
      Done for the capture logic itself: `capture_prediction_snapshots(db, week)` reads each player's already-fetched
      DfsProjection/OddsProp rows (no extra API calls) and upserts today's snapshot; wired into `/refresh` right
      alongside `capture_threshold_snapshots()`. The actual daily *automated* trigger is still Phase 7 (scheduling
      doesn't exist yet); for now this runs whenever `/refresh` is called manually.
- [ ] **3B.3** **Keep the daily pull cheap.** Pull only the lightweight headline lines daily; leave the expensive
      full-alternate pull on its weekly cadence. Ties to **D5**, confirm the credit cost before switching it on.
      Not applicable to the capture logic itself (`capture_prediction_snapshots` spends zero extra API credits,
      it only reads data already fetched); this item is really about Phase 7's pull cadence and stays open until
      that's built.
- [x] **3B.4** **Design where the chart appears.** Recommendation: a small "sparkline" trend in each Dashboard row,
      plus a larger, labeled line chart on the Player detail page. Confirm what you want (ties to Phase 2.2 / 2.3).
      Done as recommended: a tiny axis-free sparkline next to the Blended number on each Dashboard row (shows "—"
      when a player has no history yet), and a larger, axis-labeled chart card on Player detail with tabs to
      switch between Blended / DFS Projection / Sportsbook Projection.
- [x] **3B.5** **Build the chart.** Use a lightweight approach that fits the no-build-step stack (hand-drawn inline
      SVG, or a tiny CDN chart library). Show the blended line by default; optionally toggle DFS vs betting lines.
      Done: hand-drawn inline SVG (no chart library), reusing the same `_trend_chart_svg()` renderer built for
      3B.10's per-threshold charts, generalized to support a points-based axis (not just percentages). Blended is
      the default tab; DFS/Sportsbook are one click away.
- [x] **3B.6** **Handle the empty state**: a clear "collecting data, check back in a few days" message when a
      player has too few snapshots to draw a meaningful line. Done using the same grayed-mockup-plus-overlay
      pattern built for 3B.10 (`_placeholder_prediction_trend_svg()`), anchored to the player's real current
      number rather than a generic "no data" box. Dashboard's tiny row sparkline uses a simpler "—" dash instead,
      since there's no room for a message in that small a space.
- [x] **3B.7** Verify end-to-end: run the daily snapshot a few times (or backfill test rows), confirm the chart
      renders and updates. Done: temporarily inserted synthetic `PredictionSnapshot` rows for Joe Burrow (Player
      detail, all 3 tabs) and Josh Allen/McCaffrey (Dashboard sparklines), confirmed real (non-placeholder) charts
      rendered correctly with real axes/trend lines, then deleted the test rows, same pattern as 3B.10's original
      verification.
- [ ] **3B.8** **Credit optimization: only pull games in play.** On hourly ticks, fetch only the games actually
      being played / not yet final (on Thu/Mon that's one game, not the whole 16-game slate). Big credit saver.
      Deferred to Phase 7 (the live pull cadence), not applicable to the snapshot/chart feature itself.
- [ ] **3B.9** **Credit optimization: split the call by region.** Request the `us` sportsbook markets and the
      `us_dfs` DFS market in separate calls so you don't pay `markets × regions` for combinations that don't exist.
      Roughly halves the headline-pull cost. (On the 100K plan these two are "nice"; on 20K they'd be load-bearing.)
      Deferred to Phase 7 (the live pull cadence), not applicable to the snapshot/chart feature itself.
- [x] **3B.10** **Historical "Chance of Going Over" %, not just headline points.** Extends this phase's trend idea
      to the per-threshold probabilities shown in each Sportsbook Markets table (e.g. Rushing Yards @ 24.5:
      92.4%), not just the three headline numbers from 3B.1. Added `ThresholdSnapshot` (player, week, stat,
      threshold, probability, day): a same-day refresh updates that day's row instead of piling up duplicates.
      `/refresh` now writes one snapshot per (player, stat, threshold) with real curve data every time it runs.
      UI: every threshold's percentage is hoverable (same pattern as every other hover on the page, no separate
      dot/icon cluttering the table). Once 2+ days of history exist, hovering shows a real trend-line chart,
      sized for the tooltip (not squeezed into a table cell), with the date range and percentage range labeled
      directly on the chart. Verified with temporary synthetic snapshot rows (inserted, confirmed the chart and
      labels render correctly, then deleted); the 638 rows now in the table are real, from the
      already-stored/paid-for odds data (that day's genuine first snapshot), not fabricated. History keeps
      accumulating each time `/refresh` runs with fresh odds data. Checkbox was previously left unchecked despite
      this being built and verified; confirmed still working and checked off today. **2026-07-30 update:** until
      2+ days of history exist, hovering used to show plain text only; now it shows a real mockup of the eventual
      chart instead, grayed out with the explanation overlaid on top. `_placeholder_sparkline_svg()` builds a
      larger chart (280x132, up from the first pass's small unlabeled squiggle) with a real x-axis (the actual
      preceding 5 calendar dates, ending today) and a real y-axis (percentages, scaled tightly around this
      threshold's actual current probability rather than a fixed 0-100% range). Only the current/last point is
      real; the four earlier points are a deterministic, illustrative wiggle around it, not real history, kept
      honest by staying visually dimmed with the message layered on top. **Follow-up done same day:** the real
      chart (`_sparkline_svg`, once 2+ real days of history exist) now shares the same renderer as the mockup
      (`_trend_chart_svg()`), so both use identical real axes, sizing, and styling; the only difference is the
      mockup is dimmed with the message overlay and the real one is full brightness. The shared renderer also
      thins x-axis date labels to at most 5 so it won't get cluttered once real history grows past a handful of
      days in-season (the line itself still plots every point). Verified by temporarily inserting synthetic
      `ThresholdSnapshot` rows for Joe Burrow's Passing TDs 0.5 threshold (3 dates), confirming the real
      (non-dimmed) chart rendered correctly with proper axes, then deleting them, same pattern as the original
      3B.10 verification.

## Phase 3C — Boom-potential (ceiling) indicator (new)

*Goal: flag players whose betting markets imply unusual **upside** — a real chance to blow well past their over/under
line — so a manager can spot high-ceiling plays. Two players with the same O/U line can have very different tails;
this surfaces that difference.*

*Design principle — context, not points. Boom potential **never changes the blended score** (the right-skewed
upside is already partly baked into the expected value). It's a **tiebreaker / context signal**: when two players
score close to each other, the boom flag tells you which one carries the higher ceiling. Present it that way — a
badge/context cue alongside the number, never added on top of it.*

*Why it's cheap to build: the app already pulls the alternate-line markets and already builds a per-stat "survival
curve" (the market's implied probability of exceeding each threshold) in `blend.py` to compute expected value —
and Phase 3B.10 already stores those per-threshold probabilities over time in `ThresholdSnapshot`. Boom potential
reads straight off that same curve (e.g. P(yards ≥ line + 30) is already in the data). This is mostly a new metric
+ a badge, not a new data source.*

- [x] **3C.1** **Define the "boom" metric.** Recommendation: for a player's main stat, read the survival curve for
      the probability of beating the line by a meaningful margin. Decide: absolute margin (e.g. +30 yards),
      relative (+X% over the line), or an upper-tail percentile, and whether the margin is set per-stat (30 yards
      means very different things for pass yards vs receptions). Decided: **relative margin, 30% over the
      market's own expected value** (`BOOM_MARGIN = 0.30`), not a fixed yardage number, so it means the same
      thing whether the stat is pass yards or receiving yards. Read via a new `_interpolate_survival()` helper
      (linear interpolation between the two nearest quoted thresholds); returns "n/a" rather than guessing when
      30% over expectation falls beyond the highest line a book quoted.
- [x] **3C.2** **Decide the scope.** v1 recommendation: score the player's single **main stat** (rush yds for RBs,
      rec yds for WRs, pass yds for QBs). Combining every stat into one fantasy-point "ceiling" is more powerful but
      needs merging several distributions, leave that as a v2. Done as recommended: `MAIN_STAT_BY_POSITION` maps
      QB to pass_yds, RB to rush_yds, WR/TE to reception_yds.
- [x] **3C.3** **Compute a ceiling score + a simple flag** (e.g. top-quartile tail → a 🚀 "high ceiling" badge).
      Done: flag is the top quartile of `boom_prob` *within each position* (not a fixed cutoff), computed once per
      Dashboard load in `_player_rows()`, skipped entirely for a position if fewer than 4 players have a real
      boom_prob to rank against. Verified 48 players flagged across QB/RB/WR/TE in the current Week 15 dataset.
- [x] **3C.4** **Reuse existing data / handle the dependency.** The tail probabilities come from the alternate-line
      survival curve, i.e. the same data behind `ThresholdSnapshot` (3B.10), pulled by the **weekly full pull**,
      not the daily headline pull (D5 / 3B.3). So the score refreshes weekly and exists only for games/players
      where alternates were pulled; show "n/a" (not a fake 0) everywhere else. Done: `_main_stat_curve()` reuses
      the same `MIN_THRESHOLDS_FOR_CURVE` richness gate `betting_derived_points()` uses; players without a rich
      enough curve get `boom_prob = None` and are simply left out of the Dashboard flag and the Player detail
      callout (no fake number, no visible "n/a" clutter on rows where it doesn't apply).
- [x] **3C.5** **UI.** A badge/column on the Dashboard (ties to Phase 2.2) and a tail breakdown on the Player
      detail page (Phase 2.3), ideally showing the real number, e.g. "38% chance of 30+ yards over the line."
      Done: a 🚀 badge next to the player's name on Dashboard rows (hover tooltip with the real percentage and
      stat), and an accent-colored callout on Player detail with the actual sentence, e.g. "25% chance of topping
      95.4 yds for Rushing Yards (30% above the market's projected 73.4 yds)." **2026-07-30 refinement:** owner
      asked whether boom potential should be measured against the blended score instead of the raw stat.
      Discussed the tradeoff: a true points-based version needs merging several stat distributions (yards + TDs
      + receptions) into one, which means assuming how correlated they are with each other, exactly the "v2"
      complexity 3C.2 deliberately scoped out. Agreed on a middle ground instead: keep the same single-stat
      curve (still statistically sound, already verified), but also convert the yardage upside into fantasy
      points using the existing scoring rate, so the badge/callout speaks in the site's usual "points" language.
      Both surfaces now show it, e.g. Dashboard tooltip: "worth about +3.3 fantasy pts if it happens"; Player
      detail: "worth about +2.2 more fantasy points if it happens."
- [ ] **3C.6** *(Optional companion)* **Floor / "bust" indicator**: the mirror tail, P(outcome ≤ line - margin),
      to separate safe plays from boom-or-bust plays. Not required for v1, but nearly free once 3C.1-3C.3 exist.
      Owner confirmed 2026-07-30: not wanted, boom only. Not built, will not be built.
- [x] **3C.7** **Verify against a known example.** The Titans@49ers game already has real alternate-line data (e.g.
      McCaffrey's rush yards came out right-skewed, ~73 vs a ~65.5 line), a good sanity check that the tail math
      is reading the curve correctly. Verified live: McCaffrey's Player detail page shows the boom callout's
      expected value as 73.4 yds, matching the visible Rushing Yards market breakdown (73.39 yds) exactly, and
      matching this plan's own note about the real number from when 3B.10 was built.

---

# PART 2 — Ship it live

## Phase 4 — Make the app deployable

*Goal: the app can start on a server that isn't your laptop. No public exposure yet.*

- [x] **4.1** Make the app read the server's port from a `PORT` environment variable (currently hardcoded to 8000).
      Done: there's no Python code hardcoding the port (it was only ever a CLI flag), so this is solved entirely
      by 4.2's `Procfile` using `$PORT`. Local dev (`.claude/launch.json`) keeps its own explicit `--port 8000`,
      unaffected since `PORT` is never set locally.
- [x] **4.2** Add a production start command / `Procfile` (e.g. `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT`).
      Done: `Procfile` added at the repo root with exactly that command. `--host 0.0.0.0` is required for
      production (binds all interfaces; uvicorn's local-dev default of 127.0.0.1 wouldn't be reachable from
      outside the container).
- [x] **4.3** Pin dependency versions in `requirements.txt` (currently `>=`; pin to exact versions). Done: pinned
      to the exact versions already installed and verified working (fastapi 0.128.8, uvicorn[standard] 0.39.0,
      sqlalchemy 2.0.51, jinja2 3.1.6, python-dotenv 1.2.1, httpx 0.28.1, python-multipart 0.0.20).
- [x] **4.4** Confirm secrets are read from real environment variables, not only the `.env` file (`config.py`
      already uses `os.getenv`, so this likely just needs verifying on the host). Verified directly: temporarily
      moved `.env` aside, ran the app with `ODDS_API_KEY`/`FANTASYPROS_API_KEY` set as real shell env vars
      (simulating production, where no `.env` file is deployed), confirmed `get_settings()` still read them
      correctly. `.env` restored immediately after.
- [x] **4.5** Decide how the production database gets created and seeded (the `.db` file isn't in git). Ties to **D4**.
      Decided: upload the existing local `data/advisor.db` (already holds the real, paid-for Week 15 2025
      backtest) to the production persistent disk on first deploy, rather than re-running the historical Odds
      API pull in production and spending those credits again. Actual upload happens at Phase 6.5.
- [x] **4.6** Test the production start command locally once, the way the server will run it. Done: ran the exact
      `Procfile` command (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`) locally with `PORT=8000`, confirmed
      it starts and serves `/dashboard` with a 200.

## Phase 5 — Secure it before it's public

*Goal: a stranger who finds the site cannot cost you money or break your data.*

- [x] **5.1** 🔴 **Lock down data refresh.** With the public button gone (2.2), ensure any remaining refresh trigger
      requires a secret token (stored as an env var). This guards your paid Odds API credits. Done: added
      `REFRESH_SECRET` to `.env`/`.env.example` (a random 43-char token, generated with Python's `secrets`
      module). `POST /refresh` now requires a matching `X-Refresh-Token` header, checked with a timing-safe
      comparison (`secrets.compare_digest`), before touching anything else in the function, so it fails closed:
      if `REFRESH_SECRET` isn't set at all, every request is rejected rather than silently allowed through.
      Verified both rejection paths live (no header → 401, wrong header → 401). Did **not** test the accepting
      path over HTTP, since a real successful call would spend real Odds API credits; confirmed by reading the
      code that the auth check runs before `sync_players()`/`sync_odds()`, so nothing downstream can run without
      a valid token.
- [x] **5.2** Add basic rate limiting so the public pages can't be hammered. Done: an in-memory, fixed-window
      per-IP limiter (100 requests/60s, no new dependency needed for a single-process app), applied globally via
      Starlette middleware. Reads `X-Forwarded-For` for the real visitor IP (Render sits the app behind a proxy,
      so `request.client.host` alone would be the proxy's address, not the visitor's), falling back to
      `request.client.host` for local dev. Periodic cleanup every 5 minutes keeps memory bounded. Verified with a
      fast in-process burst (115 requests against `/` in under half a second): exactly 100 succeeded, #101 onward
      correctly got 429. 🔴 **Found and fixed a real, separate performance issue while testing this:**
      `/dashboard`, `/about`, and `/compare` each took ~800ms-1100ms to load (measured directly), because all
      three call `_player_rows()`, which ran 3 separate DB queries per player (~374 players = ~1,100+ queries)
      plus the Phase 3C boom-probability curve math, every request. **Two-part fix:** (1) batched the 3 per-player
      queries into 3 total queries for the whole week (grouped into dicts by player_id in Python), which alone
      brought load times down to ~460-625ms; (2) profiling showed the *remaining* time was mostly SQLAlchemy
      hydrating ~30,000 `OddsProp` rows into ORM objects every request, not the query count, so added a short
      (30s) in-memory cache on `_player_rows()`'s output, cleared immediately whenever `/refresh` actually writes
      new data (so a real refresh shows up right away, not after a stale-cache wait). Verified live: first load
      after a restart ~570ms (cache miss), every load after that ~90-125ms, an 8-10x improvement, with the
      Dashboard's real player data and boom badges still rendering correctly.
- [x] **5.3** Confirm no secrets are committed: `.env` stays gitignored; keys live only in the host's settings.
      Double-check the git history never contained a real key. Verified: `.env` is untracked and was never
      committed in any commit, ever (`git log --all --full-history -- .env` is empty). Searched every commit's
      full diff for real key-shaped values (not just the env var names) and for any long token-like strings, both
      came back clean, the only matches were commit SHAs and code identifiers. Listed every file ever committed
      across all history: no `.db` file, no `.env`, no stray scratch/test scripts with hardcoded credentials.
      Also confirmed `.env.example` only has empty placeholder values and the new `Procfile` has no secrets in
      it, before either gets committed.
- [x] **5.4** Run a security review before launch (`/security-review`). Done: the skill itself couldn't run
      (it diffs against `origin/HEAD`, and this repo has no GitHub remote yet, that's Phase 6.1), so did a manual
      full-codebase review instead. Found and fixed 6 real issues: (1) a failed Odds API call could print the raw
      exception (which can contain the API key, since httpx embeds request URLs in its errors) onto the public
      dashboard and into logs, now logged server-side only via a generic message; (2) the rate limiter trusted the
      first `X-Forwarded-For` entry, which is attacker-controlled and spoofable, switched to the last entry (the
      one Render's own proxy appends); (3) `?week=` accepted unbounded integers, confirmed live that a huge value
      crashes the page (`OverflowError`), now rejects anything outside 1-30 with a clean 400; (4) the injury-status
      hover tooltip (Dashboard, Compare, and Player detail, the last one wasn't caught by the reviewing agent, found
      it by pattern-matching) rendered raw unescaped text via Alpine's `x-html` for any status not in the known
      lookup table, now escaped consistently with every other tooltip on the site; (5) player/team JSON embedded
      into `<script>` blocks had HTML-safety escaping disabled entirely (a custom `tojson` override plus `|safe`),
      added a dedicated `_script_safe_json()` helper (escapes `<`, `>`, `&`, `'` so a value can't prematurely close
      the script tag) used only for script-tag embeds, left the original `tojson` filter untouched since it's
      still needed for Alpine attribute contexts; (6) `/docs` and `/openapi.json` were publicly live, now disabled.
      Checked but not upgraded: `pip-audit` flagged known CVEs in starlette/python-dotenv/python-multipart, but
      verified directly that the "fixed" versions it cited don't exist on PyPI yet, every pin here is already the
      latest available release, nothing to bump. Verified all 6 fixes live (curl + browser): `/docs` and
      `/openapi.json` 404, an oversized `?week=` returns a clean 400 while normal weeks still work, `/compare` and
      `/dashboard` still render correctly with the new script-safe JSON, and a simulated malicious injury string
      now renders HTML-escaped instead of raw. Confirmed clean (no changes needed): no SQL injection anywhere (all
      queries go through the ORM), static file serving isn't vulnerable to path traversal, CORS has no wide-open
      middleware registered, the refresh-token auth gates every code path before any paid API call, no hardcoded
      secrets anywhere in the repo. Deferred as "nice to have" (not required before launch): no HTTP security
      headers (X-Frame-Options etc.), no Subresource Integrity hash on the Alpine.js CDN script, the `?note=`
      dashboard param is safely escaped but still an open reflection point worth tightening later.
- [x] **5.5** Add clean 404/500 error pages that don't leak internal details. Done: a new shared `error.html`
      template (matches the site's hero styling, status badge + heading + message + "Back to Dashboard" button),
      plus two FastAPI exception handlers in `main.py`. 404s (bad URL, unknown player id) now render the branded
      page; every other `HTTPException` (400 bad `?week=`, 401 on `/refresh`) still returns the same plain JSON
      as before, those are already safe, meaningful messages, not something to hide. A new catch-all handler for
      any genuine unhandled crash logs the real exception (with traceback) server-side only via `logging.exception`
      and shows the visitor the same generic branded 500 page, never the raw error. Verified live: added a
      temporary `/__test_crash` route that deliberately raised an exception, confirmed the response body contained
      no trace of the exception type/message/file path while the real traceback appeared in the server log, then
      removed the test route and re-confirmed the 404 handler, all four core pages, and the temporary route's own
      404 (proving the removal took effect) all still work. Screenshots of both pages taken in-browser.

## Phase 6 — Deploy for the first time

*Goal: a real, public URL that loads the site.*

- [x] **6.1** Create the hosting account (per **D1**) and connect it to the GitHub repo. *(The repo isn't on GitHub
      yet — pushing it up is part of this step.)* Done: repo created at github.com/kgm27/startline (public),
      pushed via a new SSH key generated on this machine (owner added the public key to their GitHub account, no
      password ever handled by Claude). Render account created by owner (payment/account creation is owner-only,
      Claude never handles card details or passwords), connected to the GitHub repo, Starter plan (~$7/mo, per D1).
- [x] **6.2** Configure environment variables on the host: `ODDS_API_KEY`, `FANTASYPROS_API_KEY`, `SCORING_FORMAT`,
      and the refresh secret from 5.1. Done: owner copied all 4 values from the local `.env` into Render's
      Environment Variables screen before the first deploy.
- [x] **6.3** Attach a persistent disk for the SQLite file (per **D4**) so data survives restarts/redeploys. Done,
      after a real snag: the first disk was created with a mount path that had a stray trailing space
      (`/opt/render/project/src/data ` instead of `.../data`), so the app's own hardcoded path (no space) actually
      pointed at the container's throwaway filesystem, not the disk, every redeploy silently wiped it. Found via a
      temporary diagnostic endpoint (added, used, then removed) that dumped the real cwd/mount state rather than
      guessing. Render doesn't allow editing a disk's mount path after creation, so the fix was deleting the
      (empty, unused) disk and recreating it with the exact path. Verified correct via the diagnostic endpoint
      (`data_dir_is_mount: true`, no trailing-space duplicate) before trusting it.
- [x] **6.4** First deploy. Watch the build/boot logs; fix and redeploy as needed. Done: build succeeded first try
      once the Start Command (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`) was pasted into Render's form
      (Render doesn't auto-read the repo's `Procfile` for this). Site went live at startline.onrender.com.
- [x] **6.5** Seed the production database (run the refresh/seed once, or upload the existing `advisor.db`). Done,
      via a temporary `POST /admin/upload-db` endpoint (gated by the same `X-Refresh-Token`/`REFRESH_SECRET` auth
      as `/refresh`), added, used twice (once before the disk-mount fix, once after), then removed both times —
      avoided spending Odds API credits on a fresh production pull and avoided setting up SSH/CLI access. The
      real test was pushing a code change (removing the endpoint) and confirming the 374-player Week 15 dataset
      survived that redeploy, which it did.
- [x] **6.6** Smoke-test the live URL: every page loads, filters/sort/search work, comparison works. Done: `/`,
      `/dashboard`, `/compare`, `/about` all return 200 live, Dashboard shows the real 374-player Week 15 demo
      dataset with the boom-badge legend, and both temporary admin endpoints confirmed gone (404) from production.

## Phase 7 — Automate data refresh (mostly in-season)

*Goal: data updates itself on a schedule during the season, without spending credits carelessly. Two cadences:
a cheap **daily** headline pull (feeds the Phase 3B trend chart) and the fuller **weekly** pull.*

- [ ] **7.1** Add scheduled jobs (cron) matching the **D5 cadence**: the headline pulls that write trend snapshots
      (Phase 3B.2) — 2×/day baseline, hourly 8am–1am ET on Sat & Sun, hourly on Thu/Mon nights — plus the **weekly**
      fuller pull (full alternate lines). Both replace the removed manual button.
- [ ] **7.2** Make the jobs credit-aware: skip when there are no upcoming games (off-season/byes) so they don't
      waste Odds API credits. Log what each run spent. Ties to **D5**.
- [ ] **7.4** **Decide how the schedule runs (do this first — it governs 7.1).** Recommendation: run the scheduler
      **inside the web app** (e.g. an APScheduler background job) so there's **no extra hosting cost**. The
      alternatives — Render's separate Cron Jobs service or an external scheduler hitting the protected refresh
      endpoint — are also fine but add a small cost and/or another moving part. Keep it in-process unless there's a
      reason not to. *(This is also the only genuinely new cost decision surfaced in the 2026-07-29 cost review.)*

## Phase 8 — Final polish

- [x] **8.1** Write a proper `README.md` (what it is, the stack, a screenshot, a link to the live site) — this is
      what people see on GitHub. Done: covers what it is, the 4-step blend methodology, every page, the full
      stack, data sources, and a local-dev quickstart. No embedded screenshot (owner chose to skip that part for
      now, can add one later by dropping a PNG in and referencing it).
- [x] **8.2** Set up the custom domain if chosen (**D2**). Done: registered `getstartline.com` (~$12/yr,
      Namecheap, WhoisGuard privacy enabled). Confirmed available first via direct WHOIS/RDAP queries before
      purchase across `.io`/`.com`/`.app`/`.dev` for the exact name (all taken) before landing on this one. Wired
      into Render: an A record (`@` → `216.24.57.1`) for the apex domain and a CNAME (`www` → `startline.onrender.com`)
      for the www subdomain, added at Namecheap after removing the default parking-page records that conflicted
      with them. Both domains verified and got their SSL certificates issued by Render (a separate, slightly
      slower step than DNS verification itself). `www.getstartline.com` correctly 301-redirects to the canonical
      `getstartline.com`. Verified live: both `getstartline.com` and `www.getstartline.com` reachable over HTTPS,
      every page (`/`, `/dashboard`, `/compare`, `/about`) returns 200 on the new domain.
- [x] **8.3** Polish pass: social-share preview card, consistent titles/favicon. *(Desktop; mobile is Phase 10.)*
      Done: added Open Graph + Twitter Card meta tags to `base.html` (site name, per-page title reused from the
      existing `{% block title %}`, a description, and a canonical `og:url` built from `getstartline.com` regardless
      of which host actually served the request). No preview image (owner chose to skip the image specifically,
      title/description-only previews still work on every platform that supports OG tags). Titles/favicon were
      already consistent from earlier phases. Verified live: correct per-page `og:title`/`og:url` on all four pages.
- [ ] **8.4** (Optional) Lightweight privacy-friendly analytics so you can see visits. Owner decided 2026-07-31
      to skip this for now, not required for launch. Left unchecked/open rather than marked done, can revisit later.

## Phase 9 — Launch

- [x] **9.1** Final review of the live site on desktop. Done: walked through Landing, Dashboard, a Player detail
      page (Josh Allen, including the trend chart and threshold tables), Compare, and About on `getstartline.com`
      — all render correctly, no console errors on any page. Also confirmed the branded 404 page works on the
      custom domain, the SSL certificate is valid (Google Trust Services, auto-renewing, valid through Oct 2026),
      and `www.getstartline.com` still correctly redirects to the canonical domain.
- [ ] **9.2** Add the link to your resume / portfolio / LinkedIn.
- [ ] **9.3** Note the live URL and any host/login details somewhere safe.

**✅ At this point the site is resume-ready. Everything below is optional.**

## Phase 10 — Mobile polish *(optional, after launch)*

*Goal: the site also looks and works well on a phone. Not required for the resume, do it only if you want it.*

- [x] **10.1** Check every page on a phone-sized screen (Landing, Dashboard, Player detail, Comparison, About).
      Done: audited all five at a real 375px mobile viewport (not guessed). Landing and About already worked fine
      (simple stacked prose/cards). Found two real bugs on Dashboard, Player detail, and Compare, fixed in 10.2.
- [x] **10.2** Fix the most likely trouble spots: the wide data tables (make them scroll or stack), the nav bar,
      and the comparison side-by-side layout (may need to stack vertically on narrow screens). Done, two real bugs
      found and fixed: (1) `.table-card` (wrapping both the Dashboard and Compare tables) had `overflow: hidden`,
      which was silently clipping the DFS/Sportsbook/Blended/Expert columns off-screen on a phone, not just
      pushing them off-screen-but-reachable. Changed to `overflow-x: auto` so the table now swipe-scrolls
      horizontally instead; same defensive fix applied to Player detail's per-market tables. (2) The Dashboard's
      stat row and Player detail's summary numbers use a left-border divider between items, which broke when the
      row wrapped on a narrow screen: whatever item wrapped to a new line kept an orphaned left border with
      nothing before it. Fixed by stacking them in a single column on mobile with a top-border instead, where
      "first item" is unambiguous. The Comparison page's picker/stacking behavior already worked from earlier
      responsive CSS. Nav bar already wrapped fine, no changes needed there.
- [x] **10.3** Confirm tap targets (buttons, filters, links) are big enough to use with a thumb. Done: measured
      actual rendered heights on a mobile viewport rather than guessing. Position-filter pills (~28px), nav links
      (~29px), and the League Format select (~35px) were all under Apple/Google's ~44px minimum. Bumped padding
      (mobile-only, via media query, no change to desktop sizing) to bring all three to 43-46px. Verified with
      real measurements after the fix.
- [x] **10.4** Re-test on desktop to make sure the mobile fixes didn't break the desktop layout. Done: confirmed
      at 1280px width that the stat row and summary numbers stay horizontal with their original left-border
      dividers (the mobile stacking/top-border rule is scoped to the same max-width: 640px media query as the
      rest of the site's mobile overrides), and the Dashboard/Compare tables still show every column without a
      scrollbar at that width.

---

## Running log (append notes here as you go)

- 2026-07-29 — Plan created. Goal: ship public/live as a resume piece.
- 2026-07-29 — Restructured into Part 1 (finalize product: pages → UX → sources) + Part 2 (ship it live) after
  owner flagged that page inventory, per-page UX, and FantasyPros weren't represented. Settled: 5-page inventory,
  comparison = two-player head-to-head, FantasyPros = launch blocker. Refresh button to be removed from public UI.
- 2026-07-29 — Added optional Phase 10 (mobile polish) after launch, and pulled mobile out of the earlier phases.
  Priority is a desktop, resume-ready site; mobile is a nice-to-have to tackle only after Phase 9.
- 2026-07-29 — Added Phase 3B (prediction-trend line chart, fed by a daily snapshot) + decision D5. Key constraint:
  daily FULL pulls would blow the 20k-credit/mo budget, so daily = cheap headline pull, weekly = full alternates.
- 2026-07-29 — Settled the pull cadence in D5: 2×/day baseline + hourly 8am–1am ET on Sat & Sun (Saturday kept
  because it's lineup-setting day) + hourly Thu/Mon nights (one game). Cost ~29k–84k/mo → recommend upgrading to
  the $59/100K Odds API tier for the season. Plan purchase still pending owner confirmation. Added credit-optimization
  tasks 3B.8 (only pull in-play games) and 3B.9 (split call by region).
- 2026-07-29 — Cost review: fully-built-out cost ≈ $80/mo in-season (Odds API $59 + FantasyPros HOF ~$12 + Render
  $7 + disk/domain ~$1), ≈ $20/mo off-season. FantasyPros HOF is ~$12/mo ($9 annual) — ⚠️ confirm HOF actually
  includes API access (may be a separate partner deal) at Phase 3.1. Added task 7.4 to choose the scheduler
  (recommend in-process/APScheduler = no extra cost).
- 2026-07-29 — Added Phase 3C (boom-potential / ceiling indicator). Reads the alternate-line survival curve — the
  same per-threshold data already stored by 3B.10 (`ThresholdSnapshot`) — so it's mostly a new metric + a 🚀 badge,
  not a new data source. Refreshes weekly (needs the full-alternate pull). Optional mirror: a floor/"bust" flag.
- 2026-07-29 — Phase 1 built (not just decided): added a shared nav bar (logo → Landing · Dashboard · Compare ·
  About, active-page highlighting) to `base.html`. Moved the Dashboard from `/` to `/dashboard` so `/` could
  become the real Landing page. Built the Landing page (2.1 — hero, pitch, CTA into Dashboard). Added `/compare`
  and `/about` routes with "coming soon" placeholders so nav has no dead links; their real content is Phase 2
  (2.4, 2.5). Verified all five pages + player detail + nav highlighting in-browser.
- 2026-07-29 — 2.2 Dashboard done: removed the public Refresh Data button; added a League Format dropdown
  (Half PPR/Standard/Full PPR/Superflex/Dynasty/Best Ball) as a UI-only preview — no new scoring logic, a note
  explains other formats are coming soon. Also fixed a real bug hit while verifying: `/static/style.css` had no
  cache-busting, so the local browser preview kept serving a stale stylesheet after edits. Fixed by versioning
  the link with the file's mtime (`?v=...`, set in `main.py`, used in `base.html`) — this is a permanent fix,
  worth knowing about for any future "my CSS change isn't showing up" moment.
- 2026-07-29 — 2.2 Dashboard confirmed done (owner reviewed each change live in-browser before sign-off): on top
  of the button removal + League Format dropdown, added a FLEX filter pill, kept the Injury column and gave it a
  custom-styled hover tooltip (not the native browser tooltip) defining each status code, added real-brand-color
  team badges, and switched DFS/Betting/Blended to one-decimal display (sorting still uses full precision).
- 2026-07-29 — Found and fixed a real bug while checking Odds API credit-cost math for a "fully update Week 15"
  question: `/dashboard` and `/player/{id}` with no `?week=` were showing a blank "Week 1" page (off-season
  `fetch_current_week()` returns a week with zero data). This is the exact gap D3 was about — now settled: both
  routes fall back to the most recent week with real data when the actual current week has none, and show a
  "Demo data — Week X" banner whenever the displayed week isn't genuinely live. Explicit `?week=N` still always
  wins. Also fixed two stale code comments (`odds_api.py`) claiming a historical props pull costs 180
  credits/event on 9 markets — the real, current figure is 300 credits/event on 15 markets (`ALTERNATE_MARKETS`
  was added after those comments were written and never updated). A full Week 15 re-pull (15 games × 300) would
  cost ~4,500 credits — flagged to the owner that since Week 15 2025 is a past week, a re-pull is deterministic
  and would return byte-identical data to what's already stored, so it wasn't run without a clearer reason to.
- 2026-07-29 — Found the real reason player pages looked sparse (owner noticed on Joe Burrow): only 23 of 352
  players (all but 2 from the Titans @ 49ers game — the one game pulled with the current rich per-bookmaker
  method during development) had real threshold-curve data; the other 329 players, including starters like
  Josh Allen, only had flat "legacy" single-line data with no bookmaker/odds attached (shows as "unknown" with
  dashes). This time a re-pull had real value (unlike the no-op case above), since those 14 games had never
  been pulled with the current method at all. Ran the real historical re-pull for all 15 Week 15 games (owner
  confirmed the ~4,200-credit cost first) — 28,094 props + 382 DFS rows stored. Rich-data coverage went from
  23 → 355 of 374 players. Verified on Joe Burrow: went from "unknown" book / no odds to real per-book threshold
  tables (BetMGM, BetOnline.ag, BetRivers, etc.) matching the McCaffrey/Kittle pages used throughout dev/testing.
- 2026-07-30 — 2.3 Player detail done. Found and fixed a real bug: every per-market table on the page inherited
  the same `position: sticky; top: 0` header CSS built for the Dashboard's single long table — on player pages,
  with a dozen+ short tables, headers detached and floated/duplicated down the page while scrolling, leaving
  blank gaps. Scoped sticky headers to `.dashboard-table` only. Also normalized number formatting: DFS
  projection rows and the three summary-box numbers (DFS/Sportsbook/Blended) were printing raw unrounded
  database precision (e.g. "19.0", "20.05", "22.0" side by side) — now consistently 2 decimals across the page.
  Verified live in-browser (Joe Burrow, McCaffrey, Dak Prescott with an injury tag, a player missing DFS data) —
  tooltips, threshold expand/collapse, and empty states all confirmed working. Also noted: the dev server had
  been running without `--reload` since a prior session, so Python-side edits weren't taking effect — restarted
  it. Separately, the browser-preview tool's `preview_start` couldn't launch the project's `.venv` Python (a
  sandbox permission error reading `.venv/pyvenv.cfg`), so the server was started directly via a background
  shell command instead — worth knowing about if this recurs in a future session.
- 2026-07-30 — 2.4 Comparison page built and confirmed. Extracted `_player_rows()` in `main.py` so `/dashboard`
  and `/compare` share one source of truth for a player's numbers. Built two-player search/select pickers, a
  swap button, and a `?a=&b=` shareable URL. Owner asked mid-build for three layout changes, all applied and
  verified: (1) Blended moved to the first result row instead of last, (2) the entire column of the player with
  the higher Blended score is now tinted rather than only bolding per-metric winners, (3) the Injury table row
  was replaced with a hoverable callout badge under the player's name.
- 2026-07-30 — 2.5 About/Methodology written and confirmed. Explains why blending beats trusting one source, the
  three inputs, and a 4-step walkthrough of the math (with real half-PPR rates). The worked example is computed
  live server-side (this week's #1 blended-score player, via the same `_player_rows()` helper as
  Dashboard/Compare) rather than hardcoded, so it's provably real data, verified by clicking through to that
  player's own page and confirming the numbers match exactly. Owner feedback applied after first draft: dropped
  the "what this site intentionally doesn't do" section (no reason to include it), and going forward, no em
  dashes anywhere on the site or in this doc.
- 2026-07-30 — Started Phase 3. Owner provided a FantasyPros API key; added to `.env`, confirmed
  `FANTASYPROS_API_KEY` loads correctly. Live test call succeeded but surfaced a real blocker: this key is
  FantasyPros' free tier, which always returns Week 1 preseason rankings regardless of the requested week
  (confirmed with three different week/year combinations, all returned identical Week 1 data, response includes
  `"tier": "free"` and `"public_api_limited": true`). That means it can't supply real Week 15 2025 rankings to
  pair with the demo dataset, or real per-week rankings once the season starts. Matches the cost note already in
  the brief: full weekly access needs the paid MVP/HOF membership (~$6-13/mo). Owner is upgrading later today;
  3.3-3.5 (wiring the sync into `/refresh`, populating `ExpertRank`, verifying end to end) are paused until the
  upgrade goes through.
- 2026-07-30 — Owner asked whether 3B.10 (the per-threshold trend chart) had already been built, since they
  remembered a trendline draft. It had (2026-07-29), but the checkbox was never flipped to done, a
  documentation gap, now fixed. While confirming, owner asked for one more improvement: the "not enough history
  yet" hover state used to be plain text only; now it shows the same chart frame grayed out with the message
  overlaid on top (new `_placeholder_sparkline_svg()`, a generic squiggle with no real numbers behind it), so it
  previews the shape of the real chart. Verified via the rendered tooltip HTML on Joe Burrow's Passing TDs
  market. 3B.10 checked off; 3B.1-3B.9 (the separate headline-score sparkline, needs a new `PredictionSnapshot`
  table) remain unbuilt.
- 2026-07-30 — Owner flagged the new placeholder chart was too small to see and asked for a real mockup: larger,
  with an x-axis of the preceding 5 dates and a y-axis of percentages scaled to the actual data, not a fixed
  0-100% range. Rebuilt `_placeholder_sparkline_svg()`: now 280x132 (up from a small unlabeled squiggle), draws
  real axis lines, gridlines, and tick labels, uses the real last-5-calendar-day dates ending today on the
  x-axis, and scales the y-axis tightly around this threshold's actual current probability (the one real data
  point available) with headroom, same approach the real chart already uses for its own range. Only the final
  point is real; the four before it are a deterministic illustrative wiggle, not real history. Verified via the
  rendered SVG markup and screenshot on Joe Burrow's Passing TDs 0.5 threshold: axis showed 87%/93%/98% and
  Jul 26-Jul 30, with the real 94.1% value landing correctly on the last point. Flagged as a follow-up: the real
  chart (once actual history accumulates) still uses the older small style, so it won't match this mockup until
  updated too.
- 2026-07-30 — Closed that follow-up same day: refactored `_sparkline_svg()` (the real chart) and
  `_placeholder_sparkline_svg()` (the mockup) to share one renderer, `_trend_chart_svg()`, so both draw identical
  real axes/gridlines/sizing; only the mockup gets dimmed and gets the message overlay. The shared renderer also
  thins x-axis labels to at most 5 so real history won't clutter the axis once a player has many days of data
  in-season. Removed the now-unused `.spark-label` CSS rule (the old corner-label style it replaced). Verified
  the real-chart path specifically by temporarily inserting 3 synthetic `ThresholdSnapshot` rows for Joe Burrow's
  Passing TDs 0.5 threshold, confirming the full-brightness chart rendered correctly with real axes, then
  deleting the test rows.
- 2026-07-30 — 2.6 closed out: owner is happy using the favicon built earlier (paused mid-session, then
  confirmed later) as-is for now, may revisit the design later. Re-verified `/static/favicon.svg` still serves
  correctly (200, `image/svg+xml`) after several dev-server restarts. All of Phase 2 is now done.
- 2026-07-30 — Built the rest of Phase 3B (the headline-score trend feature, distinct from 3B.10's per-threshold
  percentages): added `PredictionSnapshot` (player, week, dfs_pts, betting_pts, blended, day) and
  `capture_prediction_snapshots(db, week)`, wired into `/refresh` next to the threshold-snapshot capture, reads
  already-fetched data so it costs no extra API credits. Generalized `_trend_chart_svg()` (built for 3B.10) to
  support a points-based y-axis (not just percentages) via a `value_fmt`/`max_value` param, and added a matching
  placeholder-mockup function for points. Player detail now has a chart card (Blended/DFS Projection/Sportsbook
  Projection tabs, Alpine `x-show` toggle, real axes, larger than the tooltip charts since it's inline on the
  page) right under the summary numbers. Dashboard rows got a tiny axis-free sparkline next to the Blended
  number (`_mini_sparkline_svg()`), falling back to "—" when a player has no history. Verified end-to-end with
  temporary synthetic `PredictionSnapshot` rows (Joe Burrow for the Player detail chart and tab-switching, Josh
  Allen/McCaffrey for the Dashboard sparklines), confirmed real charts render correctly, then deleted the test
  rows. 3B.1/3B.2/3B.4/3B.5/3B.6/3B.7 checked off; 3B.3/3B.8/3B.9 are really about Phase 7's live pull cadence
  and stay open until that phase is built.
- 2026-07-30 — Built Phase 3C (boom-potential/ceiling indicator). Chose a relative 30% margin over the market's
  own expected value (`BOOM_MARGIN = 0.30`) rather than a fixed yardage number, read via a new
  `_interpolate_survival()` helper on the same alternate-line curve `blend.py` already builds, scoped to each
  position's single main stat (pass_yds/rush_yds/reception_yds). Dashboard flags the top quartile *within each
  position* (not a fixed cutoff) with a 🚀 badge next to the player's name (hover tooltip has the real number);
  Player detail shows a full sentence callout with the real target/expected values. Players without a rich
  enough curve are simply left out, never shown a fake number. Verified two ways: (1) the known McCaffrey
  example from 3B.10's build notes, his Player detail page shows a 73.4 yds expected rushing total, matching
  both this plan's earlier note (~73 vs a ~65.5 line) and the visible Rushing Yards market breakdown (73.39 yds)
  exactly; (2) a direct query confirmed 48 players flagged high-ceiling across QB/RB/WR/TE with sensible
  20-32% probabilities. 3C.1/3C.2/3C.3/3C.4/3C.5/3C.7 checked off; 3C.6 (optional floor/bust mirror) not built.
- 2026-07-30 — Discussed whether boom potential should be measured against the blended score instead of the raw
  stat. Explained the tradeoff: a real points-based version needs merging multiple stat distributions (not just
  one), which requires assuming their correlation, exactly the "v2" complexity 3C.2 already scoped out on
  purpose. Agreed on a middle ground: keep the existing single-stat curve unchanged, but also convert the 30%
  yardage margin into fantasy points (using the same scoring rate the blended score is built from) and show that
  alongside the percentage on both the Dashboard tooltip and Player detail callout. Owner also confirmed: boom
  only, no "bust"/floor mirror wanted, so 3C.6 will not be built. Verified live: McCaffrey's Player detail
  callout now reads "...worth about +2.2 more fantasy points if it happens"; Joe Burrow's Dashboard tooltip
  reads "...worth about +3.3 fantasy pts if it happens."
- 2026-07-30 — Owner flagged the Dashboard's boom-badge hover was long and text-heavy. Restructured it: the
  percentage and points boost are now large text on their own line ("20%  +3.3 pts"), with the explanation
  sentence kept small underneath instead of one run-on paragraph. Player detail's callout box was left as-is
  (it's an always-visible sentence, not a hover, so the "text-heavy" complaint didn't apply there). Verified by
  triggering the tooltip directly on Joe Burrow's badge and reading the rendered HTML.
- 2026-07-30 — Follow-up: owner noted the "+3.3 pts" was still small and unexplained. Redesigned as two co-equal
  stat blocks side by side ("20% / CHANCE" and "+3.3 / PTS UPSIDE", same size, each with its own small caption),
  and added the missing explanation back into the detail sentence ("...worth about +3.3 fantasy points if it
  happens"), which had been dropped when the tooltip was first restructured out of plain text. Verified via the
  rendered tooltip HTML on Joe Burrow's badge.
- 2026-07-30 — Owner asked for a visual arrow between the two stats to show they're connected (the chance
  produces the points upside). Added a small "→" between the two stat blocks, aligned to the top of the numbers
  rather than centered across the whole block (so it doesn't visually drift toward the small caption text
  underneath). Verified live: "20% CHANCE → +3.3 PTS UPSIDE" on Joe Burrow's badge.
- 2026-07-30 — Settled Part 2's open hosting decisions: **D1** Render, always-on (~$7/mo, chosen over the free
  tier to avoid sleep/wake delay on a resume link). **D2** yes to a custom domain (~$12/yr), name not picked yet.
  **D4** SQLite + persistent disk, as recommended. None of this is signed up for yet, decisions only, Phase 6.1
  is the actual Render signup. Only D5 (Odds API pull cadence/plan purchase) remains open.
- 2026-07-30 — Phase 4 (make the app deployable) fully built and verified: `Procfile` added
  (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`), `requirements.txt` pinned to exact working versions,
  env-var-only secret loading verified by testing with `.env` temporarily removed, and the exact Procfile command
  tested locally end to end. Production DB approach decided (upload the existing real `data/advisor.db` rather
  than re-pulling historical odds in production). All of 4.1-4.6 checked off.
- 2026-07-30 — Renamed the site to **StartLine** (from the "Start/Sit Advisor" working title), covering both the
  live site and the planning docs per owner's choice. First pass briefly used "LineupLock" before the owner
  corrected it to StartLine minutes later in the same session; that name never really settled, so this entry
  reflects the actual final name rather than logging both as separate renames. Live site: nav badge "FF" to "SL",
  nav wordmark "Advisor" to "StartLine", favicon initials, every page `<title>`, the Dashboard H1, the Landing
  hero eyebrow, and the FastAPI app title (shows in the auto-generated `/docs` page). Docs: this file's H1 and
  the project brief's H1.
  Deliberately left alone: the historical running-log entries describing the *old* "FF" favicon build (a record
  of what was true then, not something to rewrite), the `advisor.db` filename (not user-visible branding), the
  brief's filename itself, and the repo's containing folder name. Verified live across Landing/Dashboard/About/
  Compare (nav, titles, headings) and the favicon SVG directly. Confirmed via grep: zero remaining references to
  the old name anywhere in app code or docs.
- 2026-07-30 — 5.1 done: `POST /refresh` now requires a secret `X-Refresh-Token` header, checked against a new
  `REFRESH_SECRET` env var (random 43-char token) with a timing-safe comparison, fails closed if the secret
  isn't configured at all. Verified the rejection paths live (missing/wrong header both 401); did not test the
  accepting path over HTTP since that would spend real Odds API credits, confirmed via code review that the auth
  check gates everything else in the function.
- 2026-07-30 — 5.2 done: added in-memory per-IP rate limiting (100 req/60s, Starlette middleware, respects
  X-Forwarded-For behind Render's proxy). Verified with a fast in-process burst against `/`: 100 succeeded, #101
  onward got 429. While debugging an earlier slow/inconclusive test, found that `/dashboard`, `/about`, and
  `/compare` each genuinely take ~800ms-1100ms per load (measured directly) due to `_player_rows()`'s N+1 query
  pattern (~1,100+ DB queries per request across ~374 players) plus the Phase 3C boom-probability math running
  every time. Landing, which skips that function, loads in 1-6ms. Flagged to owner as a separate decision, not
  fixed yet.
- 2026-07-30 — Owner asked for the `_player_rows()` performance issue to be fixed. Batched the per-player N+1
  queries into 3 bulk queries (dict-grouped by player_id in Python) first; that alone cut load times to
  ~460-625ms. Profiled with cProfile to find what was left: ~70% of remaining time was SQLAlchemy hydrating
  ~30,000 `OddsProp` rows into ORM objects, not the query count itself. Added a 30-second in-memory cache on the
  function's output (cleared immediately on a successful `/refresh`, not just left to expire, so real new data
  shows up right away). Verified: first load after a restart ~570ms, every load after that ~90-125ms across
  Dashboard/About/Compare, an 8-10x improvement over the original ~800-1100ms. Confirmed live the Dashboard still
  renders correctly (real player data, boom badges intact) after the change.
- 2026-07-30 — 5.3 done: confirmed `.env` was never committed in this repo's history (checked, not just assumed)
  and searched every commit's full diff for real leaked key values, none found. Also spot-checked the current
  uncommitted `.env.example` and `Procfile` for accidental secrets before they get committed. All clean.
- 2026-07-30 — Ran a full manual security review (5.4) since the `/security-review` skill needs a GitHub remote
  to diff against, which doesn't exist yet (Phase 6.1). Found 7 issues, owner chose to fix all of them. Fixed 6
  in `app/main.py` and the templates: raw exception text (which can contain the live Odds API key) no longer
  reaches the public dashboard/logs on a failed refresh; the rate limiter now trusts the last `X-Forwarded-For`
  entry instead of the spoofable first one; `?week=` now rejects out-of-range values (confirmed live it used to
  crash the page); the injury-status tooltip's fallback text is now HTML-escaped on all three pages that show it
  (Dashboard, Compare, Player detail); JSON embedded in `<script>` blocks now goes through a new
  `_script_safe_json()` helper instead of raw `json.dumps` + `|safe`; `/docs` and `/openapi.json` are disabled.
  The 7th (outdated dependencies per `pip-audit`) turned out to be a no-op on inspection: the "fixed" versions it
  cited for starlette/python-dotenv/python-multipart aren't published on PyPI yet, every pin here is already the
  latest available. Verified all 6 fixes live via curl and the browser. Left as future nice-to-haves (not
  blocking launch): no HTTP security headers, no SRI hash on the Alpine.js CDN script, the `?note=` param is
  safely escaped but still an open reflection point. Owner confirmed 2026-07-30, checked off.
- 2026-07-30 — Owner flagged the 🚀 boom badge (3C.5) was hover-only with no indication it's hoverable, so people
  wouldn't know to check it. Added a small caption line above the Dashboard table: "🚀 High ceiling — hover the
  badge next to a player's name for the odds behind it." Player detail's boom callout wasn't touched since it's
  already an always-visible sentence, no legend needed there. Verified live via screenshot.
- 2026-07-31 — Started Phase 8. Checked domain availability directly via WHOIS/RDAP (not guessing): `startline`
  was taken across `.io` (since 2016), `.com` (since 1998), `.app` (since 2023), and `.dev` (since 2024).
  `getstartline.com` confirmed genuinely available via the `.com` registry itself, registered at Namecheap
  (~$12/yr, WhoisGuard privacy on, a free Namecheap protection). Connected it to Render: added an A record for
  the apex domain and a CNAME for `www`, after removing Namecheap's default parking-page records that were
  conflicting with them. Both domains verified and got SSL certificates (which lag DNS verification by several
  minutes on Render, a real timing gotcha worth knowing about for next time). `www` now correctly redirects to
  the canonical apex domain. 8.2 done. Also wrote `README.md` (8.1) and added Open Graph/Twitter Card meta tags
  to `base.html` (8.3) with a canonical `og:url` hardcoded to `getstartline.com` so it's correct regardless of
  which host (Render's or the custom domain) actually serves a given request. Owner chose to skip a real preview
  image for now (tried a couple of approaches to generate one automatically, none worked out cleanly; title/
  description-only social previews still work fine without it). 8.4 (optional analytics) still an open decision.
- 2026-07-30 — Owner reported the boom-badge ("High Ceiling") hover tooltip was clipped off the left edge for
  short names like Joe Burrow — the default tooltip layout centers itself under the trigger element, and the
  badge sits near the table's left edge, so a 320px-wide tooltip centered there ran off-screen to the left. Added
  a dedicated `showTooltipRight()` positioning method (Dashboard's the only place this badge shows as a hover;
  Player detail's boom callout is already always-visible text, not a hover, so it didn't need this) that anchors
  the tooltip to the badge's right side instead, with a small left-pointing arrow, falling back to the left only
  if a very narrow window leaves no room on the right. Every other tooltip (injury, method info, threshold
  trends) is untouched, confirmed via the existing `showTooltip()` still producing the same centered-below layout.
  Verified live on Joe Burrow specifically (the reported case): tooltip now starts well on-screen instead of
  running negative, confirmed via both computed position and a screenshot.
- 2026-07-30 — Phase 6 (deploy) done, all of 6.1-6.6. GitHub: created github.com/kgm27/startline (public), pushed
  via a new SSH key (owner added the public key to their GitHub account, no password handled by Claude). Render:
  owner created the account and Starter web service (~$7/mo) themselves (payment details are owner-only), Claude
  provided the env var values to copy from `.env` and the exact Start Command (Render doesn't read the repo's
  `Procfile` automatically, it wants the command pasted into its own field). Hit one real, non-obvious bug: the
  first persistent disk was created with a trailing space in its mount path
  (`/opt/render/project/src/data ` vs. the app's `.../data`), so every redeploy silently reset the database to
  empty, since the app was actually writing to the container's throwaway filesystem, not the disk. Found this via
  a temporary diagnostic endpoint (added, used, removed) rather than guessing; Render doesn't allow editing a
  disk's mount path after creation, so the fix was delete-and-recreate the disk with the exact path, verified via
  the same diagnostic before trusting it. Seeded the real `advisor.db` (374 players, the Week 15 2025 backtest)
  onto the corrected disk via a temporary, secret-token-gated upload endpoint (same auth pattern as `/refresh`),
  used twice, removed both times — this avoided both a wasteful production re-pull of the Odds API and setting up
  SSH/CLI access just for a one-time file transfer. Confirmed the fix actually worked by pushing the
  endpoint-removal commit itself as the real persistence test: the 374-player dataset survived that redeploy.
  Final state verified live: all four pages (Landing/Dashboard/Compare/About) return 200 at startline.onrender.com,
  Dashboard shows real data with the boom-badge legend, and both temporary admin endpoints are confirmed gone
  (404) from production.
- 2026-07-30 — 5.5 built and confirmed: added `error.html` (shared branded template for both 404 and 500) and two
  exception handlers in `main.py`. 404s now show the branded page; 400/401 keep their existing plain JSON (already
  safe/meaningful, not a leak). Unhandled crashes are logged server-side with the full traceback and show
  visitors a generic branded 500 page. Verified live with a temporary crash route: confirmed no exception detail
  leaked into the response body, then removed the test route. Owner confirmed 2026-07-30, checked off.
- 2026-07-31 — Owner said the site "looks completely AI-generated" and shared Robinhood screenshots as the target
  feel. First pass (removing the already-very-faint card shadow) was too subtle to notice. Real fix: removed the
  boxed-card treatment entirely from the Dashboard's stat row and Player detail's summary numbers (numbers now
  sit directly on the page with a thin divider, not in little bordered tiles, since a "everything in a rounded
  card" pattern is itself a hallmark of generic templated UIs), sized those numbers up further, and added a soft
  gradient fill under every trend-chart line (verified on both the light Player detail card and the dark tooltip
  background) so charts read as finished rather than a bare debug plot. Also fixed the Blended score's click
  affordance (owner flagged it wasn't obvious it was clickable): it used the same muted dashed-underline style as
  the page's hover-only tooltips, genuinely ambiguous. Now bold + accent-colored with a trailing chevron, visually
  distinct from anything hover-only on the page.
- 2026-07-31 — Owner flagged an em dash appearing when switching League Format on the Dashboard (a standing site
  rule, no em dashes anywhere). Fixed that instance, then found the rule was actually violated much more broadly
  (~60 instances built up across earlier sessions before it became a hard rule). Owner asked for a full sweep:
  every prose/comment em dash across all templates, `app.js`, `main.py`, and `README.md` replaced with a comma,
  period, or colon as fit each sentence. Left the "—" placeholder glyph used for missing table values as-is (a
  UI convention, not prose, a deliberate judgment call flagged to the owner rather than silently decided).
  `PROJECT-PLAN.md`'s own historical log entries (~130 instances across many past sessions) were left alone,
  out of scope for this pass since it's an internal doc, not something site visitors see.
