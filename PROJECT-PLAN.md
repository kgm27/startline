# Going-Live Plan — Fantasy Football Advisor

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

**Still open (settle these next):**
- [ ] **D1 — Hosting provider.** Recommendation: **Render** (Python-friendly, connects to GitHub, auto-deploys on
      push, supports a persistent disk so the SQLite database survives restarts). Alternatives: Railway, Fly.io.
      *Cost note (see cost-transparency rule): Render's always-on plan is ~$7/mo; a free tier exists but the site
      "sleeps" when idle and takes ~30–60s to wake. Nothing gets signed up for without your OK.*
- [ ] **D2 — Custom domain?** e.g. `something.com` (~$12/yr) vs. the free host URL (e.g. `ff-advisor.onrender.com`)
      for now. Nicer on a resume but not required for v1.
- [ ] **D4 — Database strategy.** SQLite on a persistent disk (simplest, recommended) vs. hosted Postgres (more
      robust, more setup). Recommendation: **SQLite + persistent disk** for v1.
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
- [ ] **2.5** **About / Methodology** — write the plain-language explanation of the DFS + odds + expert blend, and
      why blending beats any single source. This is what sells the project.
- [ ] **2.6** **Global UX** — nav bar, page titles, favicon, and a "demo data — Week 15 2025" banner while
      off-season (ties to **D3**). *(Desktop is the priority; dedicated mobile work is deferred to optional Phase 10.)*
      Nav bar/page titles done (Phase 1). Demo banner done (see D3, above). Favicon still outstanding.

## Phase 3 — Finish the data sources (FantasyPros — launch blocker)

*Goal: the expert-rankings column is live, not a placeholder "—".*

- [ ] **3.1** Get a FantasyPros API key. *(You had trouble signing up before — Claude can walk you through it step
      by step, and flag any cost before you commit; see [`fantasy-football-data-sources`] notes.)*
- [ ] **3.2** Add the key to your `.env` and confirm the app picks it up.
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

- [ ] **3B.1** **Store daily snapshots.** Add a new table (e.g. `PredictionSnapshot`) that records each player's
      headline numbers — DFS points, betting-derived points, blended score — stamped with the date. Today's tables
      keep only the latest values; this new table is what makes a *history* to chart. Additive — doesn't change the
      existing tables.
- [ ] **3B.2** **Write a snapshot each day.** Have the daily job (Phase 7) save one snapshot row per player per day.
- [ ] **3B.3** **Keep the daily pull cheap.** Pull only the lightweight headline lines daily; leave the expensive
      full-alternate pull on its weekly cadence. Ties to **D5** — confirm the credit cost before switching it on.
- [ ] **3B.4** **Design where the chart appears.** Recommendation: a small "sparkline" trend in each Dashboard row,
      plus a larger, labeled line chart on the Player detail page. Confirm what you want (ties to Phase 2.2 / 2.3).
- [ ] **3B.5** **Build the chart.** Use a lightweight approach that fits the no-build-step stack (hand-drawn inline
      SVG, or a tiny CDN chart library). Show the blended line by default; optionally toggle DFS vs betting lines.
- [ ] **3B.6** **Handle the empty state** — a clear "collecting data — check back in a few days" message when a
      player has too few snapshots to draw a meaningful line.
- [ ] **3B.7** Verify end-to-end: run the daily snapshot a few times (or backfill test rows), confirm the chart
      renders and updates.
- [ ] **3B.8** **Credit optimization — only pull games in play.** On hourly ticks, fetch only the games actually
      being played / not yet final (on Thu/Mon that's one game, not the whole 16-game slate). Big credit saver.
- [ ] **3B.9** **Credit optimization — split the call by region.** Request the `us` sportsbook markets and the
      `us_dfs` DFS market in separate calls so you don't pay `markets × regions` for combinations that don't exist.
      Roughly halves the headline-pull cost. (On the 100K plan these two are "nice"; on 20K they'd be load-bearing.)
- [ ] **3B.10** **Historical "Chance of Going Over" %, not just headline points.** Extends this phase's trend idea
      to the per-threshold probabilities shown in each Sportsbook Markets table (e.g. Rushing Yards @ 24.5 →
      92.4%), not just the three headline numbers from 3B.1. Added `ThresholdSnapshot` (player, week, stat,
      threshold, probability, day) — a same-day refresh updates that day's row instead of piling up duplicates.
      `/refresh` now writes one snapshot per (player, stat, threshold) with real curve data every time it runs.
      UI: every threshold's percentage is hoverable (same pattern as every other hover on the page — no separate
      dot/icon cluttering the table). Once 2+ days of history exist, hovering shows a real trend-line chart —
      sized for the tooltip (not squeezed into a table cell), with the date range and percentage range labeled
      directly on the chart. Until then, hovering explains "trend data starts updating about a week before
      kickoff, once lines are posted for this week's games." Verified with temporary synthetic snapshot rows
      (inserted, confirmed the chart + labels render correctly, then deleted) — the 638 rows now in the table
      are real, from the already-stored/paid-for odds data (today's genuine first snapshot), not fabricated.
      History will keep accumulating each time `/refresh` runs with fresh odds data.

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

- [ ] **3C.1** **Define the "boom" metric.** Recommendation: for a player's main stat, read the survival curve for
      the probability of beating the line by a meaningful margin. Decide: absolute margin (e.g. +30 yards),
      relative (+X% over the line), or an upper-tail percentile — and whether the margin is set per-stat (30 yards
      means very different things for pass yards vs receptions).
- [ ] **3C.2** **Decide the scope.** v1 recommendation: score the player's single **main stat** (rush yds for RBs,
      rec yds for WRs, pass yds for QBs). Combining every stat into one fantasy-point "ceiling" is more powerful but
      needs merging several distributions — leave that as a v2.
- [ ] **3C.3** **Compute a ceiling score + a simple flag** (e.g. top-quartile tail → a 🚀 "high ceiling" badge).
- [ ] **3C.4** **Reuse existing data / handle the dependency.** The tail probabilities come from the alternate-line
      survival curve, i.e. the same data behind `ThresholdSnapshot` (3B.10) — pulled by the **weekly full pull**,
      not the daily headline pull (D5 / 3B.3). So the score refreshes weekly and exists only for games/players
      where alternates were pulled; show "n/a" (not a fake 0) everywhere else.
- [ ] **3C.5** **UI.** A badge/column on the Dashboard (ties to Phase 2.2) and a tail breakdown on the Player
      detail page (Phase 2.3) — ideally showing the real number, e.g. "38% chance of 30+ yards over the line."
- [ ] **3C.6** *(Optional companion)* **Floor / "bust" indicator** — the mirror tail, P(outcome ≤ line − margin) —
      to separate safe plays from boom-or-bust plays. Not required for v1, but nearly free once 3C.1–3C.3 exist.
- [ ] **3C.7** **Verify against a known example.** The Titans@49ers game already has real alternate-line data (e.g.
      McCaffrey's rush yards came out right-skewed, ~73 vs a ~65.5 line) — a good sanity check that the tail math
      is reading the curve correctly.

---

# PART 2 — Ship it live

## Phase 4 — Make the app deployable

*Goal: the app can start on a server that isn't your laptop. No public exposure yet.*

- [ ] **4.1** Make the app read the server's port from a `PORT` environment variable (currently hardcoded to 8000).
- [ ] **4.2** Add a production start command / `Procfile` (e.g. `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT`).
- [ ] **4.3** Pin dependency versions in `requirements.txt` (currently `>=`; pin to exact versions).
- [ ] **4.4** Confirm secrets are read from real environment variables, not only the `.env` file (`config.py`
      already uses `os.getenv`, so this likely just needs verifying on the host).
- [ ] **4.5** Decide how the production database gets created and seeded (the `.db` file isn't in git). Ties to **D4**.
- [ ] **4.6** Test the production start command locally once, the way the server will run it.

## Phase 5 — Secure it before it's public

*Goal: a stranger who finds the site cannot cost you money or break your data.*

- [ ] **5.1** 🔴 **Lock down data refresh.** With the public button gone (2.2), ensure any remaining refresh trigger
      requires a secret token (stored as an env var). This guards your paid Odds API credits.
- [ ] **5.2** Add basic rate limiting so the public pages can't be hammered.
- [ ] **5.3** Confirm no secrets are committed: `.env` stays gitignored; keys live only in the host's settings.
      Double-check the git history never contained a real key.
- [ ] **5.4** Run a security review before launch (`/security-review`).
- [ ] **5.5** Add clean 404/500 error pages that don't leak internal details.

## Phase 6 — Deploy for the first time

*Goal: a real, public URL that loads the site.*

- [ ] **6.1** Create the hosting account (per **D1**) and connect it to the GitHub repo. *(The repo isn't on GitHub
      yet — pushing it up is part of this step.)*
- [ ] **6.2** Configure environment variables on the host: `ODDS_API_KEY`, `FANTASYPROS_API_KEY`, `SCORING_FORMAT`,
      and the refresh secret from 5.1.
- [ ] **6.3** Attach a persistent disk for the SQLite file (per **D4**) so data survives restarts/redeploys.
- [ ] **6.4** First deploy. Watch the build/boot logs; fix and redeploy as needed.
- [ ] **6.5** Seed the production database (run the refresh/seed once, or upload the existing `advisor.db`).
- [ ] **6.6** Smoke-test the live URL: every page loads, filters/sort/search work, comparison works.

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

- [ ] **8.1** Write a proper `README.md` (what it is, the stack, a screenshot, a link to the live site) — this is
      what people see on GitHub.
- [ ] **8.2** Set up the custom domain if chosen (**D2**).
- [ ] **8.3** Polish pass: social-share preview card, consistent titles/favicon. *(Desktop; mobile is Phase 10.)*
- [ ] **8.4** (Optional) Lightweight privacy-friendly analytics so you can see visits.

## Phase 9 — Launch

- [ ] **9.1** Final review of the live site on desktop.
- [ ] **9.2** Add the link to your resume / portfolio / LinkedIn.
- [ ] **9.3** Note the live URL and any host/login details somewhere safe.

**✅ At this point the site is resume-ready. Everything below is optional.**

## Phase 10 — Mobile polish *(optional, after launch)*

*Goal: the site also looks and works well on a phone. Not required for the resume — do it only if you want it.*

- [ ] **10.1** Check every page on a phone-sized screen (Landing, Dashboard, Player detail, Comparison, About).
- [ ] **10.2** Fix the most likely trouble spots: the wide data tables (make them scroll or stack), the nav bar,
      and the comparison side-by-side layout (may need to stack vertically on narrow screens).
- [ ] **10.3** Confirm tap targets (buttons, filters, links) are big enough to use with a thumb.
- [ ] **10.4** Re-test on desktop to make sure the mobile fixes didn't break the desktop layout.

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
