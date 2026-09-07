"""
Elo rating engine (spec section 5) and the projected-wins-remaining
tiebreak metric (spec section 4).

Elo here feeds only the tiebreak - the week's actual win probability
ranking comes from real market odds (data.py), not Elo.
"""

import math
from collections import defaultdict

BASE_ELO = 1505.0
HOME_ELO_BONUS = 65
K_FACTOR = 20.0
SEASON_REGRESS = 1.0 / 3.0


def _expected_home(home_elo, away_elo):
    return 1.0 / (1.0 + 10 ** (-((home_elo + HOME_ELO_BONUS) - away_elo) / 400))


def build_elo_snapshot(games, before_season, before_week):
    """Elo rating for every team using only games completed strictly
    before (before_season, before_week).

    Processes games in chronological order and applies the season-regress
    step once at the start of every new season boundary crossed, per spec
    section 5. Never lets a game at or after the target week leak into the
    snapshot - that would be exactly the lookahead bias section 5 warns
    against.
    """
    played = games[games["home_score"].notna() & games["away_score"].notna()].copy()
    played = played[
        (played["season"] < before_season)
        | ((played["season"] == before_season) & (played["week"] < before_week))
    ]
    played = played.sort_values(["season", "week", "gameday", "gametime"])

    elo = defaultdict(lambda: BASE_ELO)
    current_season = None

    for row in played.itertuples():
        if current_season is not None and row.season != current_season:
            for team in list(elo.keys()):
                elo[team] += SEASON_REGRESS * (BASE_ELO - elo[team])
        current_season = row.season

        home, away = row.home_team, row.away_team
        home_elo, away_elo = elo[home], elo[away]

        expected_home = _expected_home(home_elo, away_elo)
        if row.home_score > row.away_score:
            actual_home = 1.0
        elif row.home_score < row.away_score:
            actual_home = 0.0
        else:
            actual_home = 0.5

        margin = abs(row.home_score - row.away_score)
        # Ties have no natural "winner" for the MOV multiplier's elo_diff
        # term (spec doesn't cover this rare case); fall back to the home
        # side's perspective, consistent with the >= branch below.
        if actual_home >= 0.5:
            elo_diff_winner = home_elo + HOME_ELO_BONUS - away_elo
        else:
            elo_diff_winner = away_elo - (home_elo + HOME_ELO_BONUS)

        mov_multiplier = math.log(max(margin, 1) + 1) * (
            2.2 / (0.001 * abs(elo_diff_winner) + 2.2)
        )
        delta = K_FACTOR * mov_multiplier * (actual_home - expected_home)
        elo[home] = home_elo + delta
        elo[away] = away_elo - delta

    return dict(elo)


def elo_win_prob(team_elo, opp_elo, team_home):
    bonus = HOME_ELO_BONUS if team_home else -HOME_ELO_BONUS
    return 1.0 / (1.0 + 10 ** (-(team_elo - opp_elo + bonus) / 400))


def proj_wins_remaining(team, season, from_week, elo_snapshot, games):
    """Sum of Elo win probabilities over team's remaining schedule this
    season, using a single static Elo snapshot for every team involved
    (spec section 4) - no attempt to project how ratings will drift.
    """
    future = games[
        (games["season"] == season)
        & (games["week"] > from_week)
        & ((games["home_team"] == team) | (games["away_team"] == team))
    ]
    team_elo = elo_snapshot.get(team, BASE_ELO)
    total = 0.0
    for row in future.itertuples():
        is_home = row.home_team == team
        opponent = row.away_team if is_home else row.home_team
        opp_elo = elo_snapshot.get(opponent, BASE_ELO)
        total += elo_win_prob(team_elo, opp_elo, is_home)
    return total
