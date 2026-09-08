# NFL Survivor Pool Pick Algorithm — Build Spec

This document is a complete spec for implementing an NFL survivor pool pick
recommender. It was derived from a backtest already run against 16 seasons
of real data (2010–2025); the algorithm and the constants below are
validated, not guesses. Implement it as-is; only the CLI/plumbing is
un-opinionated.

## 1. What survivor pools are (context for the implementer)

Each week, a player picks one NFL team they think will win straight up (no
point spread). If the team wins, the player advances; if it loses or ties,
the player is eliminated. A team can only be picked once per season (no
reuse). The season-long survival probability is the *product* of each
week's win probability, not a sum or average — so a strategy that quietly
sacrifices win probability in any single week pays for it every time, while
"saving a good team for later" only pays off in the relatively rare case
where the player would otherwise be forced into a bad pick.

## 2. The algorithm to implement

For the upcoming week, given the set of teams the user has already used:

1. Compute every remaining (unused) team's win probability for its game
   this week, and its "favorite margin" (points favored by, from the
   closing spread; negative if an underdog).
2. Find the single biggest favorite this week by favorite margin.
3. Build a **shortlist**: every remaining team whose favorite margin is
   within `Z_THRESHOLD * SD_MARGIN` points of the biggest favorite's margin
   (see §3 for both constants). This is normally just 1 team, occasionally
   2–3, rarely 4+ — that shape is a validated property of the constants
   below, not something to re-tune casually.
4. If the shortlist has exactly one team, pick it. Done.
5. If the shortlist has 2+ teams (a genuine "coin flip" among the week's
   biggest favorites), pick the one with the **lowest projected wins
   remaining** (see §4) — i.e., spend the team least likely to be a great
   favorite again later, and implicitly save the others for future weeks.

This is called the **adaptive strategy** below. Do not apply the
projected-wins-remaining tiebreak outside of step 5 — e.g. never use it to
override a pick that is clearly the best favorite on its own. Backtesting
showed that doing so (a fixed top-k shortlist with no tie threshold)
performs *worse* than simply always taking the best favorite, because it
gives up real win probability weekly for insurance that's rarely needed.
Only the tight, statistically-real "coin flip" version breaks even with, or
slightly beats, always-take-the-favorite.

## 3. Constants (calibrated; do not change without re-running the backtest)

- `SD_MARGIN = 13.06` — the empirical standard deviation of
  `(actual home margin − closing spread_line)` across all games in the
  calibration dataset (2010–2025 NFL regular season). This is the natural
  "how many points apart is meaningfully different" yardstick for an NFL
  game (in line with the commonly cited ~13–14 point figure for NFL score
  variance around the closing line). Recompute it from fresh data if you
  rebuild the backtest (§7) rather than hardcoding a stale value long-term,
  but 13.06 is the validated starting point.
- `Z_THRESHOLD = 0.15` — the shortlist band, in units of `SD_MARGIN`
  (≈ 1.96 points). This calibration produces: exactly 1 team on the
  shortlist ~54% of weeks, 2–3 teams ~39% of weeks, 4+ teams ~7% of weeks.
  A looser band (e.g. `Z_THRESHOLD = 0.25`, ≈ 3.3 points) was tested and
  performs worse — it ties too often and starts sacrificing real win
  probability. Keep the band tight.

Use *spread points* for the shortlist comparison, not raw win-probability
percentage points — win probability compresses non-linearly near 0%/100%,
so a probability-point gap means different things depending on how heavy
the favorite already is. Points-favored (the spread) is linear and
comparable across different games, which is why it's the right space to
normalize by a standard deviation in the first place.

## 4. "Projected wins remaining" (the tiebreak metric)

For a candidate team `T` being considered in week `W` of season `S`:

```
proj_wins_remaining(T) = sum over each future week F > W on T's schedule of
    EloWinProb(T's rating, opponent's rating, T home/away in that game)
```

- Use each team's **actual remaining schedule** (already fixed and public
  before the season starts — this is not a lookahead-bias issue).
- Use a single **static snapshot of Elo ratings as of "now"** (before week
  W's games) for both the team and all of its future opponents. Do not try
  to project how those opponents' ratings will change over the season —
  the static snapshot is what was backtested and what performed well;
  it's also simpler and avoids compounding simulation error.
- `EloWinProb(a, b, a_home) = 1 / (1 + 10 ** (-(a - b + (65 if a_home else
  -65)) / 400))` — standard logistic Elo formula with a 65-point home-field
  bonus (see §5 for where the 65 comes from / how it's used elsewhere).

Lower `proj_wins_remaining` = the team is less likely to be a strong
favorite again later = safer/cheaper to spend now. That's why the tiebreak
picks the *lowest* value among the shortlist.

## 5. Elo rating system (feeds the tiebreak, not the weekly win-probability ranking)

Elo is used only to estimate each team's underlying strength for the
projected-wins-remaining calculation — the week's actual win probability
(step 1 in §2) should come from real market odds, not Elo, whenever odds
are available (see §6).

Standard NFL Elo, processed in chronological order across all available
games:

- `BASE_ELO = 1505.0` (starting rating for every team, and the value all
  teams regress toward between seasons)
- `HOME_ELO_BONUS = 65` (points added to the home team's rating before
  computing expected outcome)
- `K_FACTOR = 20.0`
- `SEASON_REGRESS = 1/3` — at the start of each new season, move every
  team's rating 1/3 of the way back toward `BASE_ELO`:
  `elo[t] += SEASON_REGRESS * (BASE_ELO - elo[t])`
- Margin-of-victory multiplier (523-style):
  ```
  margin = abs(home_score - away_score)
  elo_diff_winner = (home_elo + 65 - away_elo)   if home team won
                   = (away_elo - (home_elo + 65)) if away team won
  mov_multiplier = ln(max(margin, 1) + 1) * (2.2 / (0.001 * abs(elo_diff_winner) + 2.2))
  ```
- Update after each game:
  ```
  expected_home = 1 / (1 + 10 ** (-((home_elo + 65) - away_elo) / 400))
  actual_home = 1.0 if home won, 0.0 if home lost, 0.5 if tie
  delta = K_FACTOR * mov_multiplier * (actual_home - expected_home)
  home_elo += delta
  away_elo -= delta
  ```

Keep a rating snapshot **before each week's games** (i.e., using only
games already completed) — that snapshot is what §4 uses for both "now"
and, in the backtest, for what a bettor could have known at that point in
history. Never let a team's future results leak into a rating used to
evaluate a pick made before those results happened.

## 6. Win probability from real odds (de-vig)

When you have both sides' American moneylines for a game:

```python
def ml_to_prob(ml):
    return (-ml) / (-ml + 100.0) if ml < 0 else 100.0 / (ml + 100.0)

raw_home = ml_to_prob(home_moneyline)
raw_away = ml_to_prob(away_moneyline)
home_p = raw_home / (raw_home + raw_away)   # remove the vig
away_p = raw_away / (raw_home + raw_away)
```

Always de-vig before using a moneyline-derived probability for ranking or
simulation. If only a point spread is available (no moneyline), it's
acceptable to approximate win probability from the spread, but prefer the
de-vigged moneyline when both are present — it's the more direct estimate.

The **favorite margin** used for the shortlist (§2–3) should come from the
**spread**, independent of which probability source you used:
`favorite_margin(home team) = spread_line` (positive = home favored by
that many points), `favorite_margin(away team) = -spread_line`. This
project assumes a "spread_line = predicted home margin" sign convention
(positive means the home team is favored) — verify this against whatever
data source you use before trusting it; get it backwards and every
favorite/underdog determination inverts.

## 7. Backtest requirements (build this first, to validate the implementation)

Before building the live weekly recommender, implement a backtest and
confirm it reproduces results in the same ballpark as below. This is the
regression test for the whole system — if these numbers are wildly off,
something in the Elo, de-vig, or shortlist logic is wrong.

**Data**: nflverse's public schedule/odds file,
`https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv`
(no auth required; a plain download). Columns of interest: `season`,
`game_type`, `week`, `home_team`, `away_team`, `home_score`, `away_score`,
`away_moneyline`, `home_moneyline`, `spread_line`. Filter to
`game_type == "REG"`. Moneyline coverage is essentially complete for
seasons 2010 onward (spot check whatever range you use — earlier seasons
are missing moneylines entirely and should be excluded from any backtest
that needs them).

**Two evaluation modes, both needed:**

1. **Monte Carlo** — for each season, replay the schedule 1,000–2,000+
   times; each simulated week, the pick's outcome is a random draw
   weighted by that game's de-vigged win probability (not the real
   outcome). This gives a large-sample estimate of each strategy's true
   expected performance, since any single realized season is a very noisy
   sample (one win/loss swing early in the year dominates the result).
2. **Actual history replay** — walk the real schedule once per season
   using the real final scores. This answers "how would this literally
   have gone."

Report, per strategy: average weeks survived, and % of
seasons/simulations that survived the entire season. Also report the
average win probability of the strategy's picks (a quick sanity metric —
a strategy that's quietly picking worse teams will show a lower number
here even before you look at survival outcomes).

**Strategies to implement and compare** (for validation — the adaptive
strategy from §2 is the one that ships in the final tool, but implement
these as regression checkpoints):

| Strategy | Logic | Expected relative result |
|---|---|---|
| `greedy` | Always take the single highest win-probability available team | Baseline. ~4.2 avg weeks survived, ~1.9% full-season survival rate (32,000-sim Monte Carlo, 2010–2025) |
| `power_tiebreak` | Fixed top-3 by win prob, then spend the one with lowest current Elo | Underperforms greedy: ~3.2 avg weeks, ~0.8% full-season |
| `forward_tiebreak` | Fixed top-3 by win prob, then spend the one with lowest proj-wins-remaining, unconditionally | Also underperforms greedy: ~3.2 avg weeks, ~0.9% full-season |
| `adaptive` (§2, the one to ship) | Dynamic SD-normalized shortlist, tiebreak only within it | Matches or slightly beats greedy: ~4.1–4.2 avg weeks, ~2.0–2.1% full-season |

If your `power_tiebreak` / `forward_tiebreak` implementations *don't*
underperform greedy, or your `adaptive` implementation doesn't come out
roughly even with or ahead of greedy, treat that as a bug signal and
recheck the Elo update, the de-vig math, and the shortlist direction (the
tiebreak spends the *lowest* proj-wins-remaining team, not the highest —
getting this backwards silently reproduces the "always slightly worse"
result for the adaptive strategy too).

Every strategy picks a different team each week (no reuse); a bye week
simply removes that team from that week's candidate pool; if a week has no
eligible unused teams left, that's a data problem worth surfacing, not
silently skipping.

## 8. Weekly recommender (the actual deliverable)

A CLI (or small script) that a user runs once a week during the season:

**Inputs:**
- Season and week number.
- The set of teams already used this season (so they're excluded).
- This week's slate: for each remaining game, the two teams, which is
  home, the closing (or current) spread, and — if available — both teams'
  moneylines. A simple CSV is fine:
  ```
  home_team,away_team,spread_line,home_moneyline,away_moneyline
  KC,LAC,-6.5,-280,235
  BUF,NYJ,-9,-450,360
  ...
  ```
  (`spread_line` positive = home favored, matching §6's convention —
  restate this in the tool's own docs/help text since it's easy to get
  backwards.)

**What it does:**
1. Loads/updates the historical + current-season data (§7's data source)
   to build Elo ratings as of "now" (using every completed game through
   the given week, per §5).
2. For every team on the current season's full schedule, computes
   `proj_wins_remaining` from that week forward (§4), using the
   just-built Elo snapshot.
3. Merges in this week's slate (de-vigging moneylines per §6 when
   present; falling back to a spread-implied probability otherwise),
   excludes already-used teams, and runs the adaptive algorithm (§2).

**What it outputs:** the recommended pick, plus enough to sanity-check it
by hand — the full shortlist with each candidate's win probability,
favorite margin, and projected wins remaining, and one line explaining
which rule fired (single clear favorite vs. tiebreak-among-N).

## 9. Suggested project layout

```
survivor/
  README.md                  (this file)
  requirements.txt            (pandas, numpy — no other hard dependencies)
  survivor/
    data.py                   # download/cache games.csv, de-vig, filtering
    ratings.py                 # Elo engine, per-week snapshots, schedule lookup
    strategy.py                 # the adaptive pick function (§2) + the
                                 #   comparison strategies (§7) for the backtest
    backtest.py                 # Monte Carlo + actual-history runner (§7)
    recommend.py                 # weekly CLI (§8)
  examples/
    this_week_example.csv       # a filled-in example of the §8 input format
```

Keep `strategy.py` strategy-agnostic of data source — it should take
already-computed candidate dicts (`team`, `win_prob`, `favorite_margin`,
`proj_wins_remaining`) and know nothing about Elo, moneylines, or CSV
parsing. That keeps the backtest and the live recommender sharing one
tested implementation of the actual decision rule, which is the part that
must not silently drift between the two.

## 10. Explicit non-goals (don't scope-creep into these unless asked)

- Pool pick-percentage / contrarian strategy (maximizing *winning* a pool
  outright, vs. this tool's scope of maximizing survival probability) —
  not modeled here; would need a separate public-pick-percentage data
  source.
- Playoff weeks — this spec is regular season only.
- Live odds scraping/API integration — the recommender takes a
  user-supplied slate file (§8) rather than fetching live lines itself.
