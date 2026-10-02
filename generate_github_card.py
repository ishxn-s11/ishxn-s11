#!/usr/bin/env python3
"""
Generate a dark-themed GitHub contribution calendar + activity overview
radar chart as a single SVG, suitable for embedding in a README profile.

Usage:
    export GH_TOKEN=ghp_xxxxxxxxxxxx      # needs 'read:user' scope
    python generate_github_card.py <github_username> [--year 2025] [--out card.svg]

Then embed in your README like:
    ![stats](./card.svg)

To keep it auto-updating, run this on a schedule with a GitHub Action
(see the workflow snippet at the bottom of this file as a comment).
"""

import argparse
import datetime
import math
import os
import sys
import urllib.request
import json

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalIssueContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""

# GitHub dark-theme green scale
LEVEL_COLORS = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]
BG_COLOR = "#0d1117"
PANEL_BORDER = "#30363d"
TEXT_COLOR = "#c9d1d9"
MUTED_TEXT = "#8b949e"
AXIS_COLOR = "#39d353"
AXIS_LINE = "#2ea043"


def fetch_data(login: str, token: str, year: int):
    from_date = f"{year}-01-01T00:00:00Z"
    to_date = f"{year}-12-31T23:59:59Z"
    body = json.dumps(
        {"query": QUERY, "variables": {"login": login, "from": from_date, "to": to_date}}
    ).encode()
    req = urllib.request.Request(
        GITHUB_GRAPHQL_URL,
        data=body,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]["user"]["contributionsCollection"]


def level_for_count(count, thresholds=(1, 4, 7, 10)):
    if count == 0:
        return 0
    for i, t in enumerate(thresholds):
        if count < t:
            return i + 1
    return len(thresholds) + 1 if len(thresholds) + 1 < len(LEVEL_COLORS) else len(LEVEL_COLORS) - 1


def build_calendar_svg(weeks, x0, y0, cell=11, gap=3):
    svg_parts = []
    month_labels = []
    last_month = None
    day_labels = {1: "Mon", 3: "Wed", 5: "Fri"}

    for wi, week in enumerate(weeks):
        for di, day in enumerate(week["contributionDays"]):
            date = datetime.date.fromisoformat(day["date"])
            if di == 0 and (last_month is None or date.month != last_month):
                month_labels.append((wi, date.strftime("%b")))
                last_month = date.month
            level = level_for_count(day["contributionCount"])
            x = x0 + wi * (cell + gap)
            y = y0 + di * (cell + gap)
            svg_parts.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" ry="2" '
                f'fill="{LEVEL_COLORS[level]}"><title>{day["date"]}: {day["contributionCount"]} contributions</title></rect>'
            )

    labels_svg = []
    for wi, name in month_labels:
        x = x0 + wi * (cell + gap)
        labels_svg.append(f'<text x="{x}" y="{y0 - 10}" fill="{MUTED_TEXT}" font-size="11">{name}</text>')

    for di, name in day_labels.items():
        y = y0 + di * (cell + gap) + cell - 1
        labels_svg.append(f'<text x="{x0 - 30}" y="{y}" fill="{MUTED_TEXT}" font-size="11">{name}</text>')

    width = x0 + len(weeks) * (cell + gap)
    return "\n".join(labels_svg + svg_parts), width


def build_radar_svg(cx, cy, radius, commits_pct, issues_pct, pr_pct, review_pct):
    """4 axes: top=Code review, right=Issues, bottom=Pull requests, left=Commits."""
    axes = [
        ("Code review", 270, review_pct),
        ("Issues", 0, issues_pct),
        ("Pull requests", 90, pr_pct),
        ("Commits", 180, commits_pct),
    ]

    def point(angle_deg, value_pct):
        angle = math.radians(angle_deg)
        r = radius * (value_pct / 100.0)
        return cx + r * math.cos(angle), cy + r * math.sin(angle)

    parts = []
    # axis lines (full length, faint)
    for label, angle, _ in axes:
        ex, ey = point(angle, 100)
        parts.append(f'<line x1="{cx}" y1="{cy}" x2="{ex}" y2="{ey}" stroke="{AXIS_LINE}" stroke-width="1.5"/>')

    # filled polygon of actual values
    poly_points = []
    for label, angle, value in axes:
        px, py = point(angle, max(value, 2))  # min visible nub
        poly_points.append(f"{px},{py}")
    parts.append(
        f'<polygon points="{cx},{cy} ' + " ".join(poly_points) +
        f'" fill="{AXIS_COLOR}" fill-opacity="0.35" stroke="{AXIS_COLOR}" stroke-width="1.5"/>'
    )
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="4" fill="white"/>')

    for label, angle, value in axes:
        px, py = point(angle, max(value, 2))
        parts.append(f'<circle cx="{px}" cy="{py}" r="4" fill="white"/>')
        lx, ly = point(angle, 118)
        anchor = "middle"
        if angle == 0:
            anchor = "start"
        elif angle == 180:
            anchor = "end"
        dy = 4
        parts.append(f'<text x="{lx}" y="{ly + dy}" fill="{TEXT_COLOR}" font-size="13" text-anchor="{anchor}">{label}</text>')
        if value > 0:
            pct_y = ly + dy + (16 if angle != 270 else -16)
            parts.append(
                f'<text x="{lx}" y="{pct_y}" fill="#58a6ff" font-size="13" font-weight="bold" text-anchor="{anchor}">{value:.0f}%</text>'
            )

    return "\n".join(parts)


def generate_svg(login, collection, year):
    cal = collection["contributionCalendar"]
    total = cal["totalContributions"]
    weeks = cal["weeks"]

    commits = collection["totalCommitContributions"]
    issues = collection["totalIssueContributions"]
    prs = collection["totalPullRequestContributions"]
    reviews = collection["totalPullRequestReviewContributions"]
    grand_total = max(commits + issues + prs + reviews, 1)
    commits_pct = commits / grand_total * 100
    issues_pct = issues / grand_total * 100
    pr_pct = prs / grand_total * 100
    review_pct = reviews / grand_total * 100

    width = 860
    cal_svg, cal_width = build_calendar_svg(weeks, x0=60, y0=60)
    radar_cx, radar_cy, radar_r = width // 2 + 60, 330, 90

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="480" viewBox="0 0 {width} 480">
  <rect x="0" y="0" width="{width}" height="480" rx="10" fill="{BG_COLOR}"/>
  <rect x="10" y="10" width="{width-20}" height="460" rx="8" fill="none" stroke="{PANEL_BORDER}"/>
  <text x="30" y="35" fill="{TEXT_COLOR}" font-size="16" font-weight="bold">{total} contributions in {year}</text>
  {cal_svg}
  <line x1="10" y1="220" x2="{width-10}" y2="220" stroke="{PANEL_BORDER}"/>
  <text x="30" y="250" fill="{TEXT_COLOR}" font-size="15" font-weight="bold">Activity overview</text>
  <line x1="{width//2 - 40}" y1="230" x2="{width//2 - 40}" y2="470" stroke="{PANEL_BORDER}"/>
  {build_radar_svg(radar_cx, radar_cy, radar_r, commits_pct, issues_pct, pr_pct, review_pct)}
</svg>'''
    return svg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--year", type=int, default=datetime.date.today().year)
    parser.add_argument("--out", default="card.svg")
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN")
    if not token:
        print("Error: set the GH_TOKEN environment variable to a GitHub personal access token", file=sys.stderr)
        sys.exit(1)

    collection = fetch_data(args.username, token, args.year)
    svg = generate_svg(args.username, collection, args.year)

    with open(args.out, "w") as f:
        f.write(svg)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# Sample GitHub Actions workflow to auto-regenerate this daily and commit it
# (save as .github/workflows/update-card.yml in your profile repo):
#
# name: Update profile card
# on:
#   schedule:
#     - cron: "0 0 * * *"
#   workflow_dispatch:
# jobs:
#   update:
#     runs-on: ubuntu-latest
#     steps:
#       - uses: actions/checkout@v4
#       - uses: actions/setup-python@v5
#         with:
#           python-version: "3.11"
#       - run: python generate_github_card.py YOUR_USERNAME --out card.svg
#         env:
#           GH_TOKEN: ${{ secrets.GH_TOKEN }}
#       - run: |
#           git config user.name "github-actions"
#           git config user.email "actions@github.com"
#           git add card.svg
#           git commit -m "Update contribution card" || echo "No changes"
#           git push
# ---------------------------------------------------------------------------
