"""
Game/odds data access.

Source: nflverse's public games.csv, which includes moneylines and spreads
for future (unplayed) games as soon as sportsbooks post them - not just
historical results. That's what makes automated weekly pulls possible
without a hand-built slate file.
"""

import io
import math
import urllib.request

import pandas as pd

GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"

# Shared with strategy.py's shortlist math (spec section 3): the empirical
# stdev of (actual home margin - closing spread) across 2010-2025 REG
# season games. Used here only as the spread->probability fallback when a
# game has no moneyline yet.
SD_MARGIN = 13.06


def load_games(cache_path=None):
    """Download and return the REG-season games table.

    cache_path, if given, is written after a successful download so callers
    have a local copy for debugging - it is not read back as a cache (the
    workflow always runs from a fresh checkout, so a stale local file would
    only cause confusion).
    """
    with urllib.request.urlopen(GAMES_URL) as resp:
        raw = resp.read()
    if cache_path:
        with open(cache_path, "wb") as f:
            f.write(raw)
    df = pd.read_csv(io.BytesIO(raw))
    return df[df["game_type"] == "REG"].copy()


def ml_to_prob(ml):
    """American moneyline -> implied (vig-included) win probability."""
    if ml < 0:
        return (-ml) / (-ml + 100.0)
    return 100.0 / (ml + 100.0)


def devig(home_ml, away_ml):
    """De-vigged (home_prob, away_prob) from both sides' moneylines.

    Spec section 6: remove the vig by normalizing so the two implied
    probabilities sum to 1, rather than trusting either raw number alone.
    """
    raw_home = ml_to_prob(home_ml)
    raw_away = ml_to_prob(away_ml)
    total = raw_home + raw_away
    return raw_home / total, raw_away / total


def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def spread_implied_prob(spread_line, is_home):
    """Fallback win probability from the spread alone, when no moneyline
    is available for a game.

    Models the actual margin as Normal(spread_line, SD_MARGIN) - the same
    distribution the shortlist calibration (spec section 3) is built on -
    and asks for P(team's margin > 0). Prefer devig() over this whenever
    both moneylines are present (spec section 6).
    """
    margin = spread_line if is_home else -spread_line
    return _norm_cdf(margin / SD_MARGIN)


def favorite_margin(spread_line, is_home):
    """Points favored for one side of a game (spec section 6 convention:
    positive spread_line = home team favored by that many points)."""
    return spread_line if is_home else -spread_line
