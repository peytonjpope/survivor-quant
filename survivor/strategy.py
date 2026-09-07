"""
The adaptive pick rule (spec sections 2-3), deliberately kept ignorant of
Elo, moneylines, or CSV parsing - it only knows about already-computed
candidate dicts. That keeps this the one tested implementation of the
decision rule itself, shared by anything that calls it.

Each candidate dict must have: team, win_prob, favorite_margin,
proj_wins_remaining.
"""

# Calibrated against a 16-season backtest (2010-2025) - do not retune
# without re-running it. See spec section 3 for what these produce:
# a 1-team shortlist ~54% of weeks, 2-3 teams ~39%, 4+ teams ~7%.
SD_MARGIN = 13.06
Z_THRESHOLD = 0.15

SHORTLIST_BAND = Z_THRESHOLD * SD_MARGIN


def pick_adaptive(candidates):
    """Return {"pick": team, "shortlist": [...], "rule": str} for the
    adaptive strategy.

    shortlist is every remaining team within SHORTLIST_BAND points of the
    week's biggest favorite; a size-1 shortlist is taken outright, a
    larger one is broken by lowest proj_wins_remaining (spend the team
    least likely to be a strong favorite again later).
    """
    if not candidates:
        raise ValueError("no eligible candidates to pick from")

    best_margin = max(c["favorite_margin"] for c in candidates)
    shortlist = [
        c for c in candidates if best_margin - c["favorite_margin"] <= SHORTLIST_BAND
    ]
    shortlist.sort(key=lambda c: c["favorite_margin"], reverse=True)

    if len(shortlist) == 1:
        pick = shortlist[0]
        rule = "single clear favorite"
    else:
        pick = min(shortlist, key=lambda c: c["proj_wins_remaining"])
        rule = f"tiebreak among {len(shortlist)} co-favorites (lowest proj. wins remaining)"

    return {"pick": pick["team"], "shortlist": shortlist, "rule": rule}
