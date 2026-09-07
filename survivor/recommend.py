"""
Weekly CLI (spec section 8): builds the Elo snapshot, pulls this week's
slate, runs the adaptive strategy, prints a sanity-check report, optionally
emails it, and (unless --seed-only) advances state/season_<year>.json on
success.

Usage:
    python -m survivor.recommend --season 2026 --state state/season_2026.json [--send-email] [--seed-only]
"""

import argparse
import json
import os
import smtplib
import sys
from email.mime.text import MIMEText

from survivor import data, ratings, strategy


def load_state(path):
    with open(path) as f:
        return json.load(f)


def save_state(path, state):
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def load_dotenv(path=".env"):
    """Minimal .env loader for local testing - never used in CI, where the
    workflow injects real GitHub Actions secrets as env vars directly."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def build_candidates(games, season, week, used_teams, elo_snapshot):
    slate = games[(games["season"] == season) & (games["week"] == week)]
    candidates = []
    for row in slate.itertuples():
        for team, opponent, is_home in (
            (row.home_team, row.away_team, True),
            (row.away_team, row.home_team, False),
        ):
            if team in used_teams:
                continue
            home_ml, away_ml = row.home_moneyline, row.away_moneyline
            if pd_notna(home_ml) and pd_notna(away_ml):
                home_p, away_p = data.devig(home_ml, away_ml)
                win_prob = home_p if is_home else away_p
            else:
                win_prob = data.spread_implied_prob(row.spread_line, is_home)
            candidates.append(
                {
                    "team": team,
                    "win_prob": win_prob,
                    "favorite_margin": data.favorite_margin(row.spread_line, is_home),
                    "proj_wins_remaining": ratings.proj_wins_remaining(
                        team, season, week, elo_snapshot, games
                    ),
                }
            )
    return candidates


def pd_notna(x):
    # Local alias so this module doesn't need a direct pandas import just
    # for one null check.
    return x == x and x is not None


def format_report(season, week, result, all_candidates):
    lines = [
        f"Survivor pick — Season {season}, Week {week}",
        f"Recommended: {result['pick']}  ({result['rule']})",
        "",
        "Shortlist:",
    ]
    for c in result["shortlist"]:
        lines.append(
            f"  {c['team']:<4}  win_prob={c['win_prob']:.3f}  "
            f"favorite_margin={c['favorite_margin']:+.1f}  "
            f"proj_wins_remaining={c['proj_wins_remaining']:.2f}"
        )
    lines.append("")
    lines.append("All eligible candidates this week:")
    for c in sorted(all_candidates, key=lambda c: c["favorite_margin"], reverse=True):
        lines.append(
            f"  {c['team']:<4}  win_prob={c['win_prob']:.3f}  "
            f"favorite_margin={c['favorite_margin']:+.1f}  "
            f"proj_wins_remaining={c['proj_wins_remaining']:.2f}"
        )
    return "\n".join(lines)


def send_email(subject, body):
    load_dotenv()
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["TO_EMAIL"]

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--send-email", action="store_true")
    parser.add_argument("--seed-only", action="store_true")
    args = parser.parse_args()

    state = load_state(args.state)
    if state["season"] != args.season:
        sys.exit(f"state file is for season {state['season']}, not {args.season}")
    week = state["next_week"]
    used_teams = set(state["used_teams"])

    games = data.load_games()
    elo_snapshot = ratings.build_elo_snapshot(games, args.season, week)
    candidates = build_candidates(games, args.season, week, used_teams, elo_snapshot)
    if not candidates:
        sys.exit(
            f"no eligible unused teams for season {args.season} week {week} - "
            "check the slate/used_teams data before treating this as a real result"
        )

    result = strategy.pick_adaptive(candidates)
    report = format_report(args.season, week, result, candidates)
    print(report)

    if args.seed_only:
        return

    if args.send_email:
        send_email(
            subject=f"Survivor pick — Week {week}: {result['pick']}",
            body=report,
        )

    state["used_teams"].append(result["pick"])
    state["next_week"] = week + 1
    save_state(args.state, state)


if __name__ == "__main__":
    main()
