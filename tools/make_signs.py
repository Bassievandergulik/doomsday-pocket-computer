#!/usr/bin/env python3
"""Draws the pictures for the guide's "Flags & signs" pages into app/static/signs/ (SVG, no packages).
Run again after changing a drawing:  python3 tools/make_signs.py"""
import math
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "static", "signs")
R, B, Y, W, K = "#d52b1e", "#0b3d91", "#ffd200", "#ffffff", "#111111"


def save(name, w, h, body):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">%s</svg>\n'
                % (w, h, w, h, body))


def rect(x, y, w, h, c):
    return '<rect x="%g" y="%g" width="%g" height="%g" fill="%s"/>' % (x, y, w, h, c)


def poly(pts, c):
    return '<polygon points="%s" fill="%s"/>' % (" ".join("%g,%g" % p for p in pts), c)


# ---------------------------------------------------------------- International Code of Signals flags
FW, FH = 60, 40
SWALLOW = [(0, 0), (FW, 0), (FW * 0.7, FH / 2), (FW, FH), (0, FH)]


def hstripes(cols):
    h = FH / len(cols)
    return "".join(rect(0, i * h, FW, h + 0.3, c) for i, c in enumerate(cols))


def vstripes(cols):
    w = FW / len(cols)
    return "".join(rect(i * w, 0, w + 0.3, FH, c) for i, c in enumerate(cols))


def quarters(a, b):
    return rect(0, 0, FW, FH, b) + rect(0, 0, FW / 2, FH / 2, a) + rect(FW / 2, FH / 2, FW / 2, FH / 2, a)


def cross(bg, fg, t=8):
    return rect(0, 0, FW, FH, bg) + rect((FW - t) / 2, 0, t, FH, fg) + rect(0, (FH - t) / 2, FW, t, fg)


def saltire(bg, fg, t=7):
    return (rect(0, 0, FW, FH, bg) + '<path d="M0 0L%d %dM%d 0L0 %d" stroke="%s" stroke-width="%d"/>' % (FW, FH, FW, FH, fg, t))


FLAGS = {
    "A": poly(SWALLOW, B) + '<polygon points="0,0 %g,0 %g,%g 0,%g" fill="%s"/>' % (FW / 2, FW / 2, FH, FH, W),
    "B": poly(SWALLOW, R),
    "C": hstripes([B, W, R, W, B]),
    "D": rect(0, 0, FW, FH, Y) + rect(0, FH / 4, FW, FH / 2, B),
    "E": hstripes([B, R]),
    "F": rect(0, 0, FW, FH, W) + poly([(FW / 2, 0), (FW, FH / 2), (FW / 2, FH), (0, FH / 2)], R),
    "G": vstripes([Y, B, Y, B, Y, B]),
    "H": vstripes([W, R]),
    "I": rect(0, 0, FW, FH, Y) + '<circle cx="30" cy="20" r="11" fill="%s"/>' % K,
    "J": hstripes([B, W, B]),
    "K": vstripes([Y, B]),
    "L": quarters(Y, K),
    "M": saltire(B, W),
    "N": "".join(rect(c * 15, r * 10, 15.3, 10.3, B if (r + c) % 2 == 0 else W) for r in range(4) for c in range(4)),
    "O": poly([(0, FH), (FW, FH), (0, 0)], Y) + poly([(0, 0), (FW, 0), (FW, FH)], R),
    "P": rect(0, 0, FW, FH, B) + rect(18, 12, 24, 16, W),
    "Q": rect(0, 0, FW, FH, Y),
    "R": cross(R, Y),
    "S": rect(0, 0, FW, FH, W) + rect(18, 12, 24, 16, B),
    "T": vstripes([R, W, B]),
    "U": quarters(R, W),
    "V": saltire(W, R),
    "W": rect(0, 0, FW, FH, B) + rect(8, 8, FW - 16, FH - 16, W) + rect(20, 15, 20, 10, R),
    "X": cross(W, B),
    "Y": rect(0, 0, FW, FH, Y) + "".join(
        '<path d="M%g 0L%g %d" stroke="%s" stroke-width="5.5"/>' % (x, x - FH, FH, R) for x in range(6, 110, 14)),
    "Z": poly([(0, 0), (FW, 0), (FW / 2, FH / 2)], Y) + poly([(0, 0), (FW / 2, FH / 2), (0, FH)], K)
    + poly([(0, FH), (FW / 2, FH / 2), (FW, FH)], R) + poly([(FW, 0), (FW, FH), (FW / 2, FH / 2)], B),
}

# ---------------------------------------------------------------- hazard pictograms


def ghs(inner):
    return ('<polygon points="50,3 97,50 50,97 3,50" fill="#fff" stroke="%s" stroke-width="6"/>' % R) + inner


def emoji(ch, size=46, y=66):
    return ('<text x="50" y="%d" font-size="%d" text-anchor="middle" '
            'font-family="Noto Color Emoji, sans-serif">%s</text>' % (y, size, ch))


def trefoil():
    out = [rect(0, 0, 100, 100, Y), '<circle cx="50" cy="50" r="8" fill="%s"/>' % K]
    for a0 in (90, 210, 330):  # three 60-degree blades
        a1, a2 = math.radians(a0 - 30), math.radians(a0 + 30)
        r1, r2 = 13, 40
        p = lambda r, a: (50 + r * math.cos(a), 50 - r * math.sin(a))  # noqa: E731
        (x1, y1), (x2, y2), (x3, y3), (x4, y4) = p(r1, a1), p(r2, a1), p(r2, a2), p(r1, a2)
        out.append('<path d="M%.1f %.1fL%.1f %.1fA%d %d 0 0 0 %.1f %.1fL%.1f %.1fA%d %d 0 0 1 %.1f %.1fZ" fill="%s"/>'
                   % (x1, y1, x2, y2, r2, r2, x3, y3, x4, y4, r1, r1, x1, y1, K))
    return "".join(out)


def triangle(inner):
    return '<polygon points="50,6 96,90 4,90" fill="%s" stroke="%s" stroke-width="5" stroke-linejoin="round"/>' % (Y, K) + inner


HAZ = {
    "ghs-explosive": ghs(emoji("💥", 50, 68)),
    "ghs-flammable": ghs(emoji("🔥", 50, 68)),
    "ghs-oxidising": ghs('<circle cx="50" cy="64" r="12" fill="none" stroke="#111" stroke-width="5"/>' + emoji("🔥", 30, 55)),
    "ghs-gas": ghs('<g transform="rotate(-35 50 52)"><rect x="40" y="36" width="20" height="40" rx="8" fill="#111"/>'
                 '<rect x="46" y="28" width="8" height="10" fill="#111"/></g>'),
    "ghs-corrosive": ghs(emoji("🧪", 46)),
    "ghs-toxic": ghs('<text x="50" y="72" font-size="56" text-anchor="middle" fill="#111" font-family="DejaVu Sans, sans-serif">☠</text>'),
    "ghs-harmful": ghs('<text x="50" y="70" font-size="52" font-weight="900" text-anchor="middle" fill="#111" '
                       'font-family="sans-serif">!</text>'),
    "ghs-health": ghs('<circle cx="50" cy="32" r="8" fill="#111"/><path d="M33 75Q33 45 50 43Q67 45 67 75Z" fill="#111"/>'
                      '<polygon points="50,50 53,58 61,58 55,63 57,71 50,66 43,71 45,63 39,58 47,58" fill="#fff"/>'),
    "ghs-environment": ghs(emoji("🐟", 26, 70) + '<path d="M40 50V28M40 36L32 30M40 40L48 33" stroke="#111" stroke-width="3"/>'),
    "radiation": trefoil(),
    "biohazard": rect(0, 0, 100, 100, Y) + emoji("☣️", 64, 75),
    "warning": triangle('<text x="50" y="80" font-size="50" font-weight="900" text-anchor="middle" fill="#111" '
                        'font-family="sans-serif">!</text>'),
}


def adr(top, bottom):
    return ('<rect x="2" y="2" width="146" height="96" rx="4" fill="#ff7f00" stroke="#111" stroke-width="4"/>'
            '<line x1="2" y1="50" x2="148" y2="50" stroke="#111" stroke-width="4"/>'
            '<text x="75" y="40" font-size="34" font-weight="700" text-anchor="middle" font-family="sans-serif">%s</text>'
            '<text x="75" y="88" font-size="34" font-weight="700" text-anchor="middle" font-family="sans-serif">%s</text>'
            % (top, bottom))


def main():
    os.makedirs(OUT, exist_ok=True)
    for k, body in FLAGS.items():
        save("flag-%s.svg" % k, FW, FH, '<g>%s</g><rect x=".5" y=".5" width="59" height="39" fill="none" stroke="#777"/>' % body)
    for k, body in HAZ.items():
        save("%s.svg" % k, 100, 100, body)
    save("adr-33-1203.svg", 150, 100, adr("33", "1203"))
    print("wrote %d pictures to %s" % (len(FLAGS) + len(HAZ) + 1, OUT))


if __name__ == "__main__":
    main()
