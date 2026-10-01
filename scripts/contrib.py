"""Draws assets/contributions-{light,dark}.svg from the GitHub contribution calendar.

Run by .github/workflows/contributions.yml every day. Locally:
    GITHUB_TOKEN=$(gh auth token) python scripts/contrib.py
Text is outlined from the fonts in scripts/fonts (OFL), because GitHub
won't load web fonts inside an <img>.
"""
import datetime as dt
import io
import json
import os
import urllib.request

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

USER = os.environ.get("GH_USER", "DevAdamExp")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUERY = """query($login: String!) { user(login: $login) { contributionsCollection { contributionCalendar {
  totalContributions weeks { contributionDays { date contributionCount } } } } } }"""


class Face:
    def __init__(self, file):
        data = open(os.path.join(ROOT, "scripts", "fonts", file), "rb").read()
        self.tt = TTFont(io.BytesIO(data))
        self.hb = hb.Font(hb.Face(data))
        self.upm = self.tt["head"].unitsPerEm
        self.gs = self.tt.getGlyphSet()
        self.order = self.tt.getGlyphOrder()

    def _shape(self, text):
        b = hb.Buffer()
        b.add_str(text)
        b.guess_segment_properties()
        hb.shape(self.hb, b, {"kern": True, "liga": True, "calt": True})
        return b.glyph_infos, b.glyph_positions

    def width(self, text, size, track=0.0):
        _, pos = self._shape(text)
        return sum(p.x_advance for p in pos) * size / self.upm + track * size * (len(pos) - 1)

    def path(self, text, size, x, y, track=0.0, anchor="start"):
        if anchor == "end":
            x -= self.width(text, size, track)
        infos, pos = self._shape(text)
        s = size / self.upm
        pen = SVGPathPen(self.gs)
        for info, p in zip(infos, pos):
            self.gs[self.order[info.codepoint]].draw(TransformPen(pen, (s, 0, 0, -s, x + p.x_offset * s, y - p.y_offset * s)))
            x += p.x_advance * s + track * size
        return pen.getCommands()


THEMES = {
    "light": dict(paper="#f4f1ea", ink="#17171a", muted="#5c5c66", rule="rgba(23,23,26,0.05)", edge="#17171a",
                  shadow="#17171a", empty="rgba(23,23,26,0.07)", levels=("#cfd7f7", "#8fa2ec", "#4d68e0", "#2747d9")),
    "dark": dict(paper="#111114", ink="#efebe2", muted="#a19e96", rule="rgba(239,235,226,0.04)", edge="rgba(239,235,226,0.16)",
                 shadow="#000000", empty="rgba(239,235,226,0.07)", levels=("#262d4d", "#3b4a8f", "#6378d6", "#9aabff")),
}
MARIGOLD = "#f1b52e"


def fetch():
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": USER}}).encode(),
        headers={"Authorization": f"bearer {os.environ['GITHUB_TOKEN']}", "Content-Type": "application/json"},
    )
    cal = json.load(urllib.request.urlopen(req))["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    return cal["totalContributions"], [[d["contributionCount"] for d in w["contributionDays"]] for w in cal["weeks"]], \
        [w["contributionDays"][0]["date"] for w in cal["weeks"]]


def render(c, total, weeks, starts, hand, display, mono):
    W, H = 1280, 300
    counts = sorted(n for w in weeks for n in w if n)
    # Quartile buckets, so a few huge days don't wash out everything else.
    cuts = [counts[int(len(counts) * q)] for q in (0.25, 0.5, 0.75)] if counts else [1, 2, 3]
    best = max(counts) if counts else 0
    active = len(counts)

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
         f'aria-label="{total:,} contributions in the last year across {active} active days">']
    o.append(f'<defs><clipPath id="card"><rect x="2" y="2" width="{W-14}" height="{H-14}" rx="26"/></clipPath></defs>')
    o.append(f'<rect x="10" y="10" width="{W-14}" height="{H-14}" rx="26" fill="{c["shadow"]}"/>')
    o.append(f'<rect x="2" y="2" width="{W-14}" height="{H-14}" rx="26" fill="{c["paper"]}"/>')
    o.append('<g clip-path="url(#card)">' + "".join(
        f'<path d="M0 {y}H{W}" stroke="{c["rule"]}" stroke-width="1.5"/>' for y in range(36, H, 32)) + "</g>")
    o.append(f'<rect x="2" y="2" width="{W-14}" height="{H-14}" rx="26" fill="none" stroke="{c["edge"]}" stroke-width="2"/>')

    # Left: the number
    o.append(f'<path d="{hand.path("last 12 months", 28, 44, 70)}" fill="{c["muted"]}"/>')
    o.append(f'<path d="{display.path(f"{total:,}", 76, 42, 154, -0.03)}" fill="{c["ink"]}"/>')
    o.append(f'<path d="{mono.path(f"{active} ACTIVE DAYS", 14, 44, 204, 0.1)}" fill="{c["muted"]}"/>')
    o.append(f'<path d="{mono.path(f"BEST DAY · {best}", 14, 44, 230, 0.1)}" fill="{c["muted"]}"/>')

    # Right: the year as a grid
    cell, gap = 14, 4
    gx = W - 44 - len(weeks) * (cell + gap) + gap
    gy = 92
    last_month, last_label = None, -9
    for i, start in enumerate(starts):
        m = dt.date.fromisoformat(start).strftime("%b")
        if m != last_month:
            last_month = m
            if i - last_label >= 3 and i < len(starts) - 2:  # skip labels that would collide
                o.append(f'<path d="{mono.path(m.upper(), 12, gx + i * (cell + gap), gy - 14, 0.08)}" fill="{c["muted"]}"/>')
                last_label = i
    for wi, week in enumerate(weeks):
        for di, n in enumerate(week):
            if n == best and best:
                fill = MARIGOLD
            elif n == 0:
                fill = c["empty"]
            else:
                fill = c["levels"][sum(n > k for k in cuts)]
            o.append(f'<rect x="{gx + wi * (cell + gap)}" y="{gy + di * (cell + gap)}" width="{cell}" height="{cell}" rx="3.5" fill="{fill}"/>')
    # Legend
    ly = gy + 7 * (cell + gap) + 22
    lx = W - 44
    for f in reversed((c["empty"],) + c["levels"]):
        lx -= cell
        o.append(f'<rect x="{lx}" y="{ly - 12}" width="{cell}" height="{cell}" rx="3.5" fill="{f}"/>')
        lx -= gap
    o.append(f'<path d="{mono.path("LESS", 12, lx - 8, ly, 0.08, "end")}" fill="{c["muted"]}"/>')
    o.append(f'<path d="{hand.path("gold = best day", 20, gx, ly + 2)}" fill="{c["muted"]}"/>')
    o.append("</svg>")
    return "\n".join(o)


def main():
    total, weeks, starts = fetch()
    hand, display, mono = Face("hand.ttf"), Face("display.ttf"), Face("mono.ttf")
    for name, c in THEMES.items():
        with open(os.path.join(ROOT, "assets", f"contributions-{name}.svg"), "w") as f:
            f.write(render(c, total, weeks, starts, hand, display, mono))
    print(f"{total} contributions, {len(weeks)} weeks")


if __name__ == "__main__":
    main()
