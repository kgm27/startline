# StartLine

**Live site: [getstartline.com](https://getstartline.com)**

A fantasy football start/sit dashboard that blends three independent sources into one expected-points number
for every player, every week: DFS site projections, sportsbook betting lines (converted from market odds into
expected stat outcomes), and FantasyPros expert consensus rankings. No more tab-juggling between three sites
to make one lineup call.

> **Note:** it's currently the NFL off-season, so the live site shows a labeled demo of a real Week 15, 2025
> backtest rather than fabricated numbers. Live data resumes once the season starts.

## What it does

- **Dashboard** — every tracked player's DFS projection, sportsbook-derived projection, and blended score in
  one sortable, filterable, searchable table, with a 🚀 "high ceiling" badge for players whose betting markets
  imply unusual upside beyond their median projection.
- **Player detail** — the full breakdown behind a player's numbers: every DFS site's projection, every
  sportsbook's line for every stat market, and how each converts into expected fantasy points.
- **Compare** — two players side by side, with the higher-scoring metric highlighted per row.
- **About** — a plain-language walkthrough of the blending methodology, using a live-computed real example
  (not a hardcoded illustration).

## How the blend works

1. **DFS projections** (Underdog, PrizePicks) are averaged directly into expected fantasy points.
2. **Sportsbook lines** are converted from a market's implied probability at each quoted threshold into a
   full expected-value curve for that stat (e.g. rushing yards), then priced into fantasy points using the
   league's scoring rules.
3. **Expert rankings** (FantasyPros consensus) provide a sanity-check perspective alongside the numbers.
4. The DFS and sportsbook expected-points numbers are averaged into one **blended score** — the headline
   number the Dashboard sorts on by default.

## Stack

- **Backend:** Python 3.9, FastAPI
- **Data:** SQLite (SQLAlchemy ORM), server-rendered Jinja2 templates
- **Frontend:** Alpine.js (via CDN, no build step) for client-side sort/filter/search and interactive tooltips
- **Data sources:** [The Odds API](https://the-odds-api.com) (sportsbook lines + DFS projections),
  [FantasyPros](https://www.fantasypros.com/api-data) (expert consensus rankings),
  [Sleeper](https://docs.sleeper.com) (player/roster data, free, no key required)
- **Hosting:** [Render](https://render.com), SQLite on a persistent disk

## Running it locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your own API keys
uvicorn app.main:app --port 8000
```

Visit `http://localhost:8000`.
