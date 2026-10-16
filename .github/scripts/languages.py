"""Render an SVG card of every language used across a user's GitHub repositories.

Run by .github/workflows/profile-assets.yml. Needs GH_TOKEN and GH_USER in the
environment. With the default Actions token only public repositories are
counted; set a LANGS_TOKEN secret (read access to your private repos) to
include private ones as well.

Usage: python3 languages.py <output-dir>
"""
import datetime
import json
import os
import sys
import urllib.request
from xml.sax.saxutils import escape

# Share of each language = bytes^SIZE_WEIGHT * repos^COUNT_WEIGHT, so one huge
# notebook or vendored file can't drown out languages used across many repos.
SIZE_WEIGHT = float(os.environ.get("SIZE_WEIGHT", "0.5"))
COUNT_WEIGHT = float(os.environ.get("COUNT_WEIGHT", "0.5"))
EXCLUDE_REPOS = {r for r in os.environ.get("EXCLUDE_REPOS", "").split(",") if r}

QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    repositories(first: 100, after: $after, ownerAffiliations: OWNER, isFork: false) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        languages(first: 50, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

THEMES = {
    "light": {"bg": "#ffffff", "border": "#d0d7de", "text": "#1f2328", "muted": "#59636e", "track": "#eaeef2"},
    "dark": {"bg": "#0d1117", "border": "#30363d", "text": "#e6edf3", "muted": "#9198a1", "track": "#21262d"},
}

WIDTH, PAD, COLS, ROW_H = 800, 28, 3, 30
FONT = '"Segoe UI", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif'


def graphql(token, variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise SystemExit(f"GitHub API error: {payload['errors']}")
    return payload["data"]["user"]["repositories"]


def collect(token, login):
    langs, repos, after = {}, 0, None
    while True:
        page = graphql(token, {"login": login, "after": after})
        for repo in page["nodes"]:
            # Skip the profile repo itself: its only code is this script.
            if repo["name"] in EXCLUDE_REPOS or repo["name"].lower() == login.lower():
                continue
            if not repo["languages"]["edges"]:
                continue
            repos += 1
            for edge in repo["languages"]["edges"]:
                name = edge["node"]["name"]
                entry = langs.setdefault(name, {"bytes": 0, "repos": 0, "color": edge["node"]["color"] or "#8b949e"})
                entry["bytes"] += edge["size"]
                entry["repos"] += 1
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    scores = {n: (v["bytes"] ** SIZE_WEIGHT) * (v["repos"] ** COUNT_WEIGHT) for n, v in langs.items()}
    total = sum(scores.values())
    ranked = sorted(langs, key=scores.get, reverse=True)
    return [(n, langs[n]["color"], 100 * scores[n] / total) for n in ranked], repos


def render(rows, repo_count, theme):
    c = THEMES[theme]
    bar_w = WIDTH - 2 * PAD
    col_w = bar_w / COLS
    n_rows = -(-len(rows) // COLS)
    legend_y = 112
    height = legend_y + n_rows * ROW_H + 30
    today = datetime.date.today().isoformat()

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}" role="img" aria-labelledby="title">',
        f'<title id="title">Languages across {repo_count} GitHub repositories: '
        + escape(", ".join(f"{n} {p:.1f}%" for n, _, p in rows)) + "</title>",
        "<style>",
        f"text {{ font-family: {FONT}; }}",
        ".seg { transform-box: fill-box; transform-origin: left center; animation: grow .9s cubic-bezier(.2,.8,.2,1) both; }",
        ".item { animation: fade .6s ease-out both; }",
        "@keyframes grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }",
        "@keyframes fade { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }",
        "@media (prefers-reduced-motion: reduce) { .seg, .item { animation: none; } }",
        "</style>",
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{height - 1}" rx="12" fill="{c["bg"]}" stroke="{c["border"]}"/>',
        f'<text x="{PAD}" y="44" font-size="18" font-weight="600" fill="{c["text"]}">Languages I code in</text>',
        f'<text x="{WIDTH - PAD}" y="44" font-size="13" fill="{c["muted"]}" text-anchor="end">'
        f"{len(rows)} languages · {repo_count} repositories</text>",
        f'<clipPath id="bar"><rect x="{PAD}" y="66" width="{bar_w}" height="12" rx="6"/></clipPath>',
        f'<rect x="{PAD}" y="66" width="{bar_w}" height="12" rx="6" fill="{c["track"]}"/>',
        '<g clip-path="url(#bar)">',
    ]
    x = PAD
    for i, (_, color, pct) in enumerate(rows):
        w = bar_w * pct / 100
        gap = 2 if i < len(rows) - 1 and w > 4 else 0
        out.append(
            f'<rect class="seg" style="animation-delay:{i * 0.05:.2f}s" x="{x:.2f}" y="66" '
            f'width="{max(w - gap, 0.8):.2f}" height="12" fill="{color}"/>'
        )
        x += w
    out.append("</g>")

    for i, (name, color, pct) in enumerate(rows):
        col, row = i % COLS, i // COLS
        cx = PAD + col * col_w
        cy = legend_y + row * ROW_H
        pct_txt = f"{pct:.1f}%" if pct >= 0.1 else "<0.1%"
        out.append(
            f'<g class="item" style="animation-delay:{0.3 + i * 0.04:.2f}s">'
            f'<circle cx="{cx + 6:.1f}" cy="{cy - 5}" r="5" fill="{color}"/>'
            f'<text x="{cx + 18:.1f}" y="{cy}" font-size="14" fill="{c["text"]}">{escape(name)}</text>'
            f'<text x="{cx + col_w - 20:.1f}" y="{cy}" font-size="13" fill="{c["muted"]}" text-anchor="end">{escape(pct_txt)}</text>'
            "</g>"
        )

    out.append(
        f'<text x="{PAD}" y="{height - 18}" font-size="11" fill="{c["muted"]}">'
        f"Share weighted by code size and number of repos · auto-updated {today}</text>"
    )
    out.append("</svg>")
    return "\n".join(out)


def main():
    token, login = os.environ.get("GH_TOKEN"), os.environ.get("GH_USER")
    if not token or not login:
        raise SystemExit("GH_TOKEN and GH_USER must be set")
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "dist"
    os.makedirs(out_dir, exist_ok=True)

    rows, repo_count = collect(token, login)
    for theme in THEMES:
        path = os.path.join(out_dir, f"languages-{theme}.svg")
        with open(path, "w") as f:
            f.write(render(rows, repo_count, theme))
        print(f"wrote {path}")
    for name, _, pct in rows:
        print(f"  {name:<18} {pct:5.1f}%")


if __name__ == "__main__":
    main()
