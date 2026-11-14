"""Drawing helpers for tools/make_figures.py: ropes, people, arrows and labels as plain SVG (no packages)."""
import math

INK = "#1e1e1e"
PAPER = "#f7f4ec"
ROPE = "#e3a33b"     # main rope
ROPE2 = "#3f86d6"    # second rope
CORD = "#c0392b"     # thin cord (prusik)
RED = "#d0342c"      # arrows, "here!"
GREEN = "#2e8b3e"
WOOD = "#9a6634"
WOOD_D = "#6e4520"
SKIN = "#e9b48a"
P1 = "#4f7fb3"       # patient / person A clothes
P2 = "#d98a2b"       # helper / person B clothes
GROUND = "#8a7d66"
WATER = "#7fb6e0"
GREY = "#9a9a9a"
LIGHT = "#d9d2c3"


def f(v):
    return ("%.1f" % v).rstrip("0").rstrip(".")


def pts(p):
    return " ".join("%s,%s" % (f(x), f(y)) for x, y in p)


def svg(w, h, body, title=""):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
            'font-family="DejaVu Sans, sans-serif">%s'
            '<rect x="1" y="1" width="%d" height="%d" rx="8" fill="%s" stroke="#bdb5a3"/>%s</svg>\n'
            % (w, h, w, h, ("<title>%s</title>" % title) if title else "", w - 2, h - 2, PAPER, body))


def text(x, y, s, size=14, anchor="middle", color=INK, weight="normal"):
    return ('<text x="%s" y="%s" font-size="%d" text-anchor="%s" fill="%s" font-weight="%s" '
            'stroke="%s" stroke-width="3" paint-order="stroke" stroke-linejoin="round">%s</text>'
            % (f(x), f(y), size, anchor, color, weight, PAPER, s))


def label(x, y, s, size=13, anchor="middle", color=INK):
    return text(x, y, s, size, anchor, color)


def step(x, y, n):
    """A numbered circle for step-by-step pictures."""
    return ('<circle cx="%s" cy="%s" r="11" fill="%s"/><text x="%s" y="%s" font-size="14" font-weight="bold" '
            'text-anchor="middle" fill="#fff">%s</text>' % (f(x), f(y), INK, f(x), f(y + 5), n))


def line(x1, y1, x2, y2, color=INK, w=3, cap="round", dash=None):
    return '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="%s" stroke-linecap="%s"%s/>' % (
        f(x1), f(y1), f(x2), f(y2), color, f(w), cap, (' stroke-dasharray="%s"' % dash) if dash else "")


def path(d, color=INK, w=3, fill="none", cap="round", dash=None, join="round"):
    return '<path d="%s" stroke="%s" stroke-width="%s" fill="%s" stroke-linecap="%s" stroke-linejoin="%s"%s/>' % (
        d, color, f(w), fill, cap, join, (' stroke-dasharray="%s"' % dash) if dash else "")


def poly(p, fill, stroke=INK, w=2):
    return '<polygon points="%s" fill="%s" stroke="%s" stroke-width="%s" stroke-linejoin="round"/>' % (pts(p), fill, stroke, f(w))


def polyline(p, color=INK, w=3, dash=None):
    return path("M" + " L".join("%s %s" % (f(x), f(y)) for x, y in p), color, w, dash=dash)


def rect(x, y, w, h, fill, stroke=INK, sw=2, rx=0):
    return '<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="%s" stroke="%s" stroke-width="%s"/>' % (
        f(x), f(y), f(w), f(h), f(rx), fill, stroke, f(sw))


def circle(x, y, r, fill, stroke=INK, sw=2):
    return '<circle cx="%s" cy="%s" r="%s" fill="%s" stroke="%s" stroke-width="%s"/>' % (f(x), f(y), f(r), fill, stroke, f(sw))


def ellipse(x, y, rx, ry, fill, stroke=INK, sw=2, rot=0):
    return '<ellipse cx="%s" cy="%s" rx="%s" ry="%s" fill="%s" stroke="%s" stroke-width="%s" transform="rotate(%s %s %s)"/>' % (
        f(x), f(y), f(rx), f(ry), fill, stroke, f(sw), f(rot), f(x), f(y))


def arrowhead(x, y, ang, color=RED, size=11):
    a = math.radians(ang)
    p = [(x, y), (x - size * math.cos(a - 0.45), y - size * math.sin(a - 0.45)),
         (x - size * math.cos(a + 0.45), y - size * math.sin(a + 0.45))]
    return poly(p, color, color, 1)


def arrow(p, color=RED, w=3.5, size=11, both=False):
    """Arrow along a smooth line through the points p (head at the last point)."""
    out = path(smooth(p), color, w)
    (x1, y1), (x2, y2) = p[-2], p[-1]
    out += arrowhead(x2, y2, math.degrees(math.atan2(y2 - y1, x2 - x1)), color, size)
    if both:
        (x1, y1), (x2, y2) = p[1], p[0]
        out += arrowhead(x2, y2, math.degrees(math.atan2(y2 - y1, x2 - x1)), color, size)
    return out


def curved_arrow(cx, cy, r, a0, a1, color=RED, w=3.5):
    """Arrow along a circle arc from angle a0 to a1 (degrees, 0 = right, clockwise positive)."""
    n = max(4, int(abs(a1 - a0) / 10))
    p = [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
         for i in range(n + 1)]
    return arrow(p, color, w)


def _cr(p, i0, i1):
    """Catmull-Rom spline through all points p, as Bezier commands from point i0 to i1."""
    d = ""
    for i in range(i0, i1):
        p0 = p[max(i - 1, 0)]
        p1, p2 = p[i], p[i + 1]
        p3 = p[min(i + 2, len(p) - 1)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += " C%s %s %s %s %s %s" % (f(c1[0]), f(c1[1]), f(c2[0]), f(c2[1]), f(p2[0]), f(p2[1]))
    return d


def smooth(p, i0=0, i1=None):
    i1 = len(p) - 1 if i1 is None else i1
    return "M%s %s" % (f(p[i0][0]), f(p[i0][1])) + _cr(p, i0, i1)


class Rope:
    """A rope drawn as an outlined band along a smooth line through points.
    parts = [(first point, last point, layer)]: higher layers are drawn on top, which makes the over/under crossings."""

    def __init__(self, p, parts, color=ROPE, width=9, ends=(True, True)):
        self.p, self.parts, self.color, self.w, self.ends = p, parts, color, width, ends

    def pieces(self):
        out = []
        last = len(self.p) - 1
        for i0, i1, z in self.parts:
            d = smooth(self.p, i0, i1)
            s = ""
            for idx, show in ((0, self.ends[0]), (last, self.ends[1])):
                if show and idx in (i0, i1):
                    x, y = self.p[idx]
                    s += circle(x, y, self.w / 2 + 2, INK, "none", 0) + circle(x, y, self.w / 2, self.color, "none", 0)
            # outline with flat ends, fill with round ends: hides the seam where two parts meet
            s += path(d, INK, self.w + 4, cap="butt") + path(d, self.color, self.w, cap="round")
            s += path(d, "rgba(255,255,255,.35)", 2, cap="butt", dash="3 7")
            out.append((z, s))
        return out


def scene(*items):
    """items: Rope objects or (layer, svg) tuples; drawn in layer order."""
    allp = []
    for it in items:
        if isinstance(it, Rope):
            allp += it.pieces()
        else:
            allp.append(it)
    allp.sort(key=lambda t: t[0])
    return "".join(s for _, s in allp)


# ---------------------------------------------------------------- people
def limb(p, color, w):
    return path(smooth(p) if len(p) > 2 else "M%s %sL%s %s" % (f(p[0][0]), f(p[0][1]), f(p[1][0]), f(p[1][1])),
                INK, w + 4) + path(smooth(p) if len(p) > 2 else "M%s %sL%s %s" % (f(p[0][0]), f(p[0][1]), f(p[1][0]), f(p[1][1])),
                                     color, w)


def person(head, neck, hip, arms=(), legs=(), color=P1, skin=SKIN, scale=1.0, back_arms=(), back_legs=(),
           pants="#3b4752", hair=None):
    """A simple rounded person. head=(x,y); neck/hip = torso ends; arms/legs = lists of point lists
    (shoulder→elbow→hand, hip→knee→foot). back_* are drawn behind the body (far side)."""
    s = scale
    out = ""
    for a in back_arms:
        out += limb(a, color, 11 * s) + circle(a[-1][0], a[-1][1], 5 * s, skin, INK, 2)
    for l in back_legs:
        out += limb(l, pants, 13 * s)
    out += limb([neck, hip], color, 24 * s)
    for l in legs:
        out += limb(l, pants, 13 * s)
    out += circle(head[0], head[1], 13 * s, skin, INK, 2)
    if hair:
        out += hair
    for a in arms:
        out += limb(a, color, 11 * s) + circle(a[-1][0], a[-1][1], 5 * s, skin, INK, 2)
    return out


def ground(y, x0=4, x1=396, color=GROUND):
    return line(x0, y, x1, y, color, 3) + "".join(line(x, y + 2, x - 8, y + 10, color, 1.5) for x in range(int(x0) + 12, int(x1), 18))


def tree(x, y, h=120, color=GREEN):
    return (rect(x - 6, y - h, 12, h, WOOD, INK, 2) + circle(x, y - h - 10, 34, color, INK, 2)
            + circle(x - 24, y - h + 12, 22, color, INK, 2) + circle(x + 24, y - h + 12, 22, color, INK, 2))


def log(x1, y1, x2, y2, w=12, color=WOOD):
    return path("M%s %sL%s %s" % (f(x1), f(y1), f(x2), f(y2)), INK, w + 4) + path(
        "M%s %sL%s %s" % (f(x1), f(y1), f(x2), f(y2)), color, w)


def flame(x, y, s=1.0):
    return (path("M%s %s c%s %s %s %s %s %s c%s %s %s %s %s %s z" % (
        f(x), f(y), f(-18 * s), f(-6 * s), f(-10 * s), f(-30 * s), f(0), f(-44 * s),
        f(4 * s), f(14 * s), f(26 * s), f(20 * s), f(0), f(44 * s)), "#b5371d", 2, fill="#f39a1e")
            + path("M%s %s c%s %s %s %s %s %s c%s %s %s %s %s %s z" % (
                f(x), f(y - 2 * s), f(-8 * s), f(-4 * s), f(-5 * s), f(-16 * s), f(0), f(-24 * s),
                f(3 * s), f(9 * s), f(12 * s), f(12 * s), f(0), f(24 * s)), "none", 0, fill="#ffd34a"))
