# Survivor Quant

Computes a weekly NFL survivor pool pick and emails it automatically via
GitHub Actions. The decision rule (Elo ratings, de-vigged market odds, an
SD-normalized "shortlist + tiebreak" strategy) is fully specified and
calibrated in [`ALGORITHM_SPEC.md`](./ALGORITHM_SPEC.md) — this README
covers how the implementation is organized and how to run/operate it.

## How it works, briefly

Each week: pull the current NFL odds (moneylines + spreads) directly from
[nflverse's public `games.csv`](https://github.com/nflverse/nfldata), build
an Elo rating for every team from all completed games, then apply the
adaptive strategy from the spec:

1. Find the week's single biggest favorite (by spread).
2. Build a shortlist of every remaining team within a tight, statistically
   calibrated margin of that favorite.
3. If it's just one team, take it. If several teams are effectively tied
   for biggest favorite, spend the one least likely to be a strong favorite
   again later (lowest projected wins remaining), saving the others.

`nflverse`'s data already includes odds for upcoming games days ahead of
kickoff, so this runs unattended — no manual weekly input needed.

## Project layout

```
survivor/
  data.py         # pulls games.csv live, de-vigs moneylines, spread fallback
  ratings.py      # Elo engine + projected-wins-remaining tiebreak metric
  strategy.py     # the adaptive pick rule itself (pure function, no I/O)
  recommend.py    # CLI: ties it together, emails the pick, updates state
state/
  season_2026.json         # {season, next_week, used_teams} - the only persisted state
.github/workflows/
  weekly_pick.yml           # Tuesday-morning cron -> run recommend.py -> commit state
ALGORITHM_SPEC.md           # full build spec: constants, formulas, backtest design
```

`backtest.py` (Monte Carlo + actual-history validation, per the spec) isn't
built yet — this ships the live recommender only.

## State model

`state/season_2026.json` is the only thing tracking where the season is:

```json
{ "season": 2026, "next_week": 2, "used_teams": ["LAC"] }
```

Every successful run (scheduled or manual) computes the pick for
`next_week`, emails it, then appends that team to `used_teams` and
increments `next_week`. The design assumes you always take the emailed
pick — if you ever deviate in your actual pool, hand-edit this file to
match reality before the next run, or the exclusion list will drift.

**Important:** a run advances state regardless of *why* it ran. There's no
calendar awareness — `workflow_dispatch` (manual trigger) consumes a real
week slot exactly like the Tuesday cron does. To test the pipeline without
touching state or sending an email, use `--seed-only` (see below) rather
than triggering the live workflow.

## Running it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# Preview the current pick without emailing or advancing state:
.venv/bin/python -m survivor.recommend --season 2026 --state state/season_2026.json --seed-only

# Full run (emails + advances state) - normally only the GitHub Action does this:
.venv/bin/python -m survivor.recommend --season 2026 --state state/season_2026.json --send-email
```

Email sending reads `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `TO_EMAIL` from
the environment (or a local, gitignored `.env` for manual testing).

## Automation setup

The workflow (`.github/workflows/weekly_pick.yml`) runs every Tuesday
~8am ET, computes that week's pick, emails it, and commits the updated
state file back to the repo. It needs three repo secrets:

```bash
gh secret set GMAIL_ADDRESS --repo peytonjpope/survivor-quant
gh secret set GMAIL_APP_PASSWORD --repo peytonjpope/survivor-quant   # a Gmail App Password, not your login password
gh secret set TO_EMAIL --repo peytonjpope/survivor-quant
```

To trigger a real run manually (e.g. to catch up a missed week):

```bash
gh workflow run weekly_pick.yml --repo peytonjpope/survivor-quant
```
