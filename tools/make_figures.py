#!/usr/bin/env python3
"""Draws the step pictures for the guide (knots, first aid, shelter, fire, navigation, water, signals...)
into app/static/figs/ as small SVG line drawings (no packages, no internet).
Pages use them as  ![caption](fig:name.svg)  on a line of their own.
Run again after changing a drawing:  python3 tools/make_figures.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from figlib import *  # noqa: E402,F401,F403

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "static", "figs")
FIGS = {}


def fig(name, w=400, h=220):
    def deco(fn):
        FIGS[name] = (w, h, fn)
        return fn
    return deco


# ================================================================ KNOTS
def post_v(x0, x1, y0, y1, z=1):
    return (z, rect(x0, y0, x1 - x0, y1 - y0, WOOD, INK, 2) + line(x0 + 8, y0 + 4, x0 + 8, y1 - 4, "#b98450", 3))


@fig("knot-clove-hitch")
def _():
    r = Rope([(30, 100), (110, 100), (165, 100), (200, 112), (235, 125), (200, 132), (165, 138), (200, 100), (235, 62),
              (200, 67), (165, 72), (200, 85), (235, 100), (300, 104), (372, 106)],
             [(0, 4, 2), (4, 6, 0), (6, 8, 3), (8, 10, 0), (10, 14, 2)], width=10)
    hidden = (2.5, path("M235 125 L165 138 M235 62 L165 72", "#3a2510", 2, dash="4 4"))
    return (scene(post_v(165, 235, 12, 208), r, hidden)
            + label(80, 86, "standing part") + label(330, 92, "end")
            + label(310, 160, "end tucked under") + label(310, 176, "the 2nd wrap")
            + arrow([(282, 146), (240, 112), (214, 94)], RED, 2.5, 9)
            + label(200, 230 - 12, "", 1))


@fig("knot-figure-eight")
def _():
    p = [(30, 140), (120, 140), (150, 140), (170, 140), (190, 140), (212, 140), (235, 140), (262, 128), (268, 98),
         (240, 76), (210, 84), (198, 110), (193, 126), (190, 140), (186, 168), (162, 180), (145, 165), (150, 140),
         (158, 114), (178, 106), (198, 110), (222, 120), (235, 140), (243, 165), (262, 192)]
    r = Rope(p, [(0, 1, 1), (1, 3, 3), (3, 5, 1), (5, 7, 3), (7, 10, 1), (10, 12, 1), (12, 14, 3), (14, 16, 1),
                 (16, 18, 1), (18, 21, 3), (21, 24, 1)], width=10)
    return scene(r) + label(80, 126, "standing part") + label(300, 196, "end") + label(330, 60, "Figure-eight stopper", 14)



def _bowline_points():
    p = [(65, 8), (65, 28), (65, 38), (65, 50), (65, 62), (60, 72), (55, 82), (60, 96), (70, 97), (80, 88), (83, 74),
         (76, 66), (70, 63.5), (65, 62), (60, 61.5), (54, 61), (44, 63), None, None, None, None, None, None,
         (80, 106), (70, 97), (72, 82), (76, 66), (78, 50), (73, 40), (65, 38), (56, 41), (52, 50), (54, 61), (57, 80),
         (60, 96), (58, 112), (55, 128)]
    q = [None if v is None else (66 + 1.45 * (v[0] - 66), 88 + 1.45 * (v[1] - 70)) for v in p]
    q[0] = (65, 10)
    q[17:23] = [(16, 125), (18, 185), (48, 228), (95, 222), (114, 185), (106, 160)]
    return q


@fig("knot-bowline", 400, 260)
def _():
    p = _bowline_points()
    base = [(0, 1, 1), (1, 3, 3), (3, 6, 1), (6, 9, 3), (9, 12, 1), (12, 14, 2), (14, 16, 1), (16, 22, 1)]
    r1 = Rope(p[:22], base[:-1] + [(16, 21, 1)], width=8)
    r2 = Rope(p[:32], base + [(22, 25, 1), (25, 27, 4), (27, 31, 0)], width=8)
    r3 = Rope(p, base + [(22, 25, 1), (25, 27, 4), (27, 31, 0), (31, 33, 4), (33, 36, 1)], width=8)
    g = lambda dx, body: '<g transform="translate(%d 8)">%s</g>' % (dx, body)
    out = g(0, scene(r1) + step(14, 12, 1) + label(104, 20, "tree", 12) + label(112, 92, "rabbit", 12)
            + label(112, 106, "hole", 12) + arrow([(116, 176), (106, 140), (80, 122)], RED, 2.5, 9))
    out += g(133, scene(r2) + step(14, 12, 2) + arrow([(49, 47), (42, 62), (46, 82)], RED, 2.5, 9)
             + label(110, 24, "up,", 12) + label(110, 38, "round", 12) + label(110, 52, "the tree", 12))
    out += g(266, scene(r3) + step(14, 12, 3) + label(112, 24, "back", 12) + label(112, 38, "down", 12)
             + label(112, 52, "the hole", 12) + label(100, 244, "pull tight", 12))
    return out + line(133, 15, 133, 245, LIGHT, 2) + line(266, 15, 266, 245, LIGHT, 2)


@fig("knot-sheet-bend")
def _():
    T = Rope([(30, 80), (150, 80), (192, 80), (220, 80), (250, 80), (262, 81), (272, 83), (285, 92), (292, 110), (285, 128),
              (268, 137), (230, 140), (210, 140), (188, 140), (140, 140), (30, 140)],
             [(0, 3, 3), (3, 7, 1), (7, 10, 3), (10, 12, 1), (12, 15, 3)], ROPE2, 13)
    t = Rope([(390, 182), (330, 166), (300, 150), (285, 128), (268, 112), (258, 100), (250, 80), (244, 58), (220, 46),
              (198, 56), (192, 80), (189, 110), (188, 140), (194, 162), (214, 166), (226, 154), (230, 140), (242, 118),
              (258, 100), (265, 91), (272, 83), (284, 58)],
             [(0, 2, 2), (2, 4, 0), (4, 7, 4), (7, 9, 2), (9, 13, 0), (13, 15, 2), (15, 17, 4), (17, 19, 1), (19, 21, 4)],
             ROPE, 8)
    return (scene(T, t) + label(80, 66, "thick rope: bight") + label(80, 160, "(short end on top)", 12)
            + label(345, 196, "thin rope") + label(340, 50, "thin end tucks") + label(340, 66, "under itself")
            + arrow([(316, 74), (286, 92), (262, 104)], RED, 2.5, 9) + label(200, 206, "Pull both ropes: the thin end stays trapped", 13))


@fig("knot-square")
def _():
    pa = [(30, 100), (120, 100), (146, 100), (175, 100), (196, 100), (200, 93), (210, 84), (230, 80), (248, 88),
          (254, 100), (256, 110), (254, 120), (248, 132), (230, 140), (210, 136), (200, 127), (196, 120), (175, 120),
          (146, 120), (120, 120), (30, 120)]
    pb = [(400 - x, y) for x, y in pa]
    A = Rope(pa, [(0, 1, 2), (1, 3, 0), (3, 4, 2), (4, 6, 4), (6, 8, 2), (8, 12, 4), (12, 14, 2), (14, 16, 0), (16, 17, 2),
                  (17, 19, 0), (19, 20, 2)], ROPE, 11)
    B = Rope(pb, [(0, 1, 2), (1, 3, 0), (3, 4, 2), (4, 6, 0), (6, 8, 2), (8, 12, 4), (12, 14, 2), (14, 16, 4), (16, 17, 2),
                  (17, 19, 0), (19, 20, 2)], ROPE2, 11)
    return (scene(A, B) + label(200, 34, "Right over left and under,") + label(200, 52, "then left over right and under")
            + label(200, 178, "Each rope's end and standing part come out", 13) + label(200, 194, "side by side. Lumpy and crossed = granny", 13)
            + label(200, 210, "knot: untie and tie again.", 13))


@fig("knot-half-hitches")
def _():
    def hitch(x0):
        return [(x0 - 26, 148), (x0 - 15, 138), (x0 - 7, 126), (x0, 110), (x0 + 5, 90), (x0 + 16, 78), (x0 + 28, 86),
                (x0 + 27, 110), (x0 + 16, 128), (x0 - 15, 138), (x0 - 32, 150), (x0 - 22, 168), (x0 + 10, 166)]
    p = [(380, 110), (250, 110), (150, 110), (100, 110), (73, 106), (52, 112), (45, 132), (55, 151), (75, 160), (110, 156)]
    parts = [(0, 3, 2), (3, 5, 3), (5, 8, 0), (8, 9, 2)]
    for x0 in (180, 270):
        i = len(p)
        p += hitch(x0)
        parts += [(i - 1, i, 2), (i, i + 4, 4), (i + 4, i + 6, 2), (i + 6, i + 8, 0), (i + 8, i + 10, 1), (i + 10, i + 12, 2)]
    p += [(330, 172), (350, 182)]
    parts += [(len(p) - 3, len(p) - 1, 2)]
    ring = (1, circle(55, 125, 26, "none", "#555", 9) + circle(55, 125, 26, "none", "#aaa", 4))
    return (scene(ring, Rope(p, parts, ROPE, 10)) + label(330, 98, "standing part") + label(185, 205, "hitch 1", 12)
            + label(272, 205, "hitch 2", 12) + label(200, 34, "Two half hitches: both turns go the same way", 13))



@fig("knot-taut-line", 400, 240)
def _():
    peg = (1, poly([(180, 196), (196, 196), (188, 234)], WOOD, INK, 2) + ground(214, 120, 280))
    p = [(170, 8), (170, 60), (170, 91), (170, 108), (170, 140), (170, 166), (172, 190), (184, 206), (200, 196),
         (205, 180), (205, 168), (186, 162), (170, 159), (150, 154), (172, 150), (192, 146), (170, 140), (150, 134),
         (172, 129), (190, 124), (170, 108), (150, 92), (172, 88), (190, 86), (170, 91), (154, 95), (132, 102)]
    parts = [(0, 1, 2), (1, 3, 2), (3, 6, 2), (6, 10, 1), (10, 13, 4), (13, 15, 0), (15, 17, 4), (17, 19, 0),
             (19, 21, 5), (21, 23, 0), (23, 24, 3), (24, 26, 1)]
    return (scene(peg, Rope(p, parts, ROPE, 9)) + label(110, 30, "to tarp", 12) + label(262, 152, "2 turns inside", 13)
            + label(262, 168, "the loop", 13) + label(262, 92, "1 turn outside,", 13) + label(262, 108, "end tucked under", 13)
            + label(250, 226, "peg", 12) + arrow([(110, 150), (110, 120), (110, 96)], RED, 3, 10) + label(72, 128, "slide", 12)
            + label(72, 142, "to tighten", 12))


@fig("knot-truckers", 400, 230)
def _():
    anchor = (1, rect(352, 60, 22, 150, WOOD, INK, 2) + circle(352, 120, 12, "none", "#555", 6))
    tr = (1, tree(48, 206, 100))
    loop = Rope([(176, 80), (166, 100), (176, 120), (194, 116), (196, 96), (184, 82)], [(0, 5, 2)], ROPE, 8, ends=(False, False))
    p = [(52, 140), (110, 92), (178, 80), (240, 100), (330, 128), (344, 132), (348, 118), (334, 108), (250, 96),
         (205, 98), (186, 92), (184, 104), (200, 126), (250, 158), (290, 172)]
    parts = [(0, 2, 2), (2, 4, 2), (4, 8, 2), (8, 9, 3), (9, 11, 1), (11, 12, 1), (12, 14, 3)]
    return (scene(tr, anchor, loop, Rope(p, parts, ROPE, 8)) + step(150, 54, 1) + label(150, 34, "slip loop", 13)
            + step(370, 40, 2) + label(305, 44, "round anchor", 12)
            + step(150, 140, 3) + label(150, 166, "back through", 12) + label(150, 180, "the loop, pull", 12)
            + arrow([(286, 172), (334, 188)], RED, 4, 12) + label(318, 210, "2x force", 12)
            + label(200, 222, "Lock: two half hitches round both lines", 12))


@fig("knot-prusik", 400, 220)
def _():
    main_rope = (1, path("M200 8 L200 212", INK, 18) + path("M200 8 L200 212", ROPE2, 14))
    out = main_rope
    wraps = ""
    for i, y in enumerate((62, 78, 94, 126, 142, 158)):
        wraps += (path("M184 %d Q200 %d 216 %d" % (y, y - 8, y - 10), INK, 9) + path("M184 %d Q200 %d 216 %d" % (y, y - 8, y - 10), CORD, 5))
    bridge = path("M218 56 Q232 110 218 160", INK, 9) + path("M218 56 Q232 110 218 160", CORD, 5)
    tails = path("M186 106 Q180 150 160 190 M190 110 Q192 150 176 196", INK, 9) + path(
        "M186 106 Q180 150 160 190 M190 110 Q192 150 176 196", CORD, 5)
    out = scene(out, (2, bridge), (3, wraps), (2.5, tails))
    out += circle(166, 200, 10, "none", "#666", 5)
    return (out + label(310, 60, "thin cord loop,") + label(310, 76, "3 turns round") + label(310, 92, "the thick rope")
            + label(310, 140, "Loose: slides.") + label(310, 156, "Loaded: grips.") + label(90, 190, "load / foot loop", 12)
            + label(90, 40, "thick rope", 12))


@fig("knot-square-lashing", 400, 230)
def _():
    poles = (1, log(200, 10, 200, 222, 22) + log(40, 112, 360, 112, 20))
    band = ""
    for dx in (-30, -22, -14):
        band += line(200 + dx, 92, 200 + dx, 132, INK, 8) + line(200 + dx, 92, 200 + dx, 132, ROPE, 5)
    for dx in (14, 22, 30):
        band += line(200 + dx, 92, 200 + dx, 132, INK, 8) + line(200 + dx, 92, 200 + dx, 132, ROPE, 5)
    hidden = path("M170 92 L230 92 M170 132 L230 132", "#5a3a18", 2, dash="4 4")
    clove = path("M190 160 Q200 150 212 158 M188 172 Q202 160 214 170", INK, 8) + path(
        "M190 160 Q200 150 212 158 M188 172 Q202 160 214 170", ROPE, 5) + path("M188 172 Q170 185 150 190", INK, 8) + path(
        "M188 172 Q170 185 150 190", ROPE, 5)
    return (scene(poles, (2, hidden + band), (3, clove)) + label(84, 160, "1 start: clove hitch", 12)
            + label(310, 66, "2 wrap 3-4 times:", 12) + label(310, 80, "in front of the crossbar,", 12)
            + label(310, 94, "behind the upright", 12) + label(310, 160, "3 two or three turns", 12)
            + label(310, 174, "between the poles", 12) + label(310, 188, "pulled tight (frapping)", 12)
            + label(84, 50, "4 finish: clove hitch", 12))



# ================================================================ FIRST AID
def lying(x_head, y_ground, color=P1, legs_up=False):
    """A person lying on their back, head to the left (side view)."""
    y = y_ground - 16
    legs = [[(x_head + 140, y + 2), (x_head + 205, y + 2), (x_head + 270, y + 4)]]
    if legs_up:
        legs = [[(x_head + 140, y + 2), (x_head + 200, y - 18), (x_head + 262, y - 34)]]
    return person((x_head, y - 2), (x_head + 20, y), (x_head + 140, y + 2), legs=legs, scale=1.2,
                  back_arms=[[(x_head + 28, y - 2), (x_head + 75, y + 4), (x_head + 120, y + 6)]], color=color)


@fig("cpr-compressions", 400, 230)
def _():
    gy = 214
    resc_back = person((92, 58), (112, 84), (176, 140), color=P2,
                       back_legs=[[(176, 140), (160, gy - 8), (230, gy - 6)]])
    pat = lying(48, gy)
    arms = (limb([(116, 88), (112, 128), (110, 172)], P2, 11) + circle(110, 174, 7, SKIN, INK, 2)
            + limb([(106, 86), (104, 128), (104, 172)], P2, 11))
    return (ground(gy) + resc_back + pat + arms
            + arrow([(66, 120), (66, 158)], RED, 4, 12) + label(60, 112, "push", 13) + label(40, 176, "5-6 cm", 12)
            + label(285, 36, "Arms straight,", 13) + label(285, 52, "shoulders right above", 13)
            + label(285, 68, "your hands", 13) + label(285, 104, "100-120 pushes", 13) + label(285, 120, "a minute", 13)
            + label(285, 150, "30 pushes, 2 breaths", 13))


def body_front(cx, top, skin=SKIN, shirt=None, arms_down=True):
    """Front view of a person from head to hips; returns svg. top = top of the head."""
    c = shirt or skin
    out = path("M%s %s Q%s %s %s %s L%s %s Q%s %s %s %s Z" % (
        f(cx - 52), f(top + 62), f(cx), f(top + 50), f(cx + 52), f(top + 62), f(cx + 40), f(top + 200),
        f(cx), f(top + 210), f(cx - 40), f(top + 200)), INK, 2, fill=c)
    if arms_down:
        out += limb([(cx - 48, top + 70), (cx - 60, top + 140), (cx - 62, top + 200)], c, 18)
        out += limb([(cx + 48, top + 70), (cx + 60, top + 140), (cx + 62, top + 200)], c, 18)
        out += path("M%s %s Q%s %s %s %s Q%s %s %s %s Z" % (
            f(cx - 52), f(top + 62), f(cx), f(top + 50), f(cx + 52), f(top + 62), f(cx + 40), f(top + 200),
            f(cx - 40), f(top + 200)), "none", 0, fill=c)
    out += rect(cx - 8, top + 34, 16, 20, skin, INK, 2) + circle(cx, top + 22, 20, skin, INK, 2)
    return out


def chest_marks(cx, top):
    return (path("M%s %s Q%s %s %s %s M%s %s Q%s %s %s %s" % (
        f(cx - 40), f(top + 66), f(cx - 20), f(top + 60), f(cx - 4), f(top + 64),
        f(cx + 40), f(top + 66), f(cx + 20), f(top + 60), f(cx + 4), f(top + 64)), "#a0704e", 2)
            + line(cx, top + 66, cx, top + 140, "#a0704e", 3) + circle(cx - 24, top + 108, 3, "#a0704e", "none", 0)
            + circle(cx + 24, top + 108, 3, "#a0704e", "none", 0))


@fig("cpr-hands", 400, 230)
def _():
    cx, top = 110, 6
    out = body_front(cx, top) + chest_marks(cx, top)
    out += circle(cx, top + 124, 13, "rgba(208,52,44,.35)", RED, 3)
    # hands: heel of one hand, other on top, fingers laced and lifted
    hx, hy = 300, 120
    out += ellipse(hx, hy + 14, 46, 22, SKIN, INK, 2)
    for i in range(4):
        out += ellipse(hx - 30 + i * 18, hy - 12, 7, 18, SKIN, INK, 2, rot=-8 + i * 6)
    out += ellipse(hx + 4, hy + 4, 44, 22, "#f1c49f", INK, 2)
    out += ellipse(hx + 52, hy + 18, 8, 16, "#f1c49f", INK, 2, rot=40)
    out += circle(hx - 26, hy + 26, 12, "rgba(208,52,44,.35)", RED, 3)
    out += label(hx, 46, "Heel of one hand,") + label(hx, 62, "other hand on top,") + label(hx, 78, "fingers off the ribs")
    out += label(hx - 26, hy + 64, "push with the heel", 12) + arrow([(hx - 26, hy + 50), (hx - 26, hy + 40)], RED, 3, 9)
    return out + label(300, 200, "Centre of the chest:", 13) + label(300, 216, "lower half of the breastbone", 13)


@fig("cpr-airway", 400, 210)
def _():
    gy = 196
    out = ground(gy)
    # lying person, head on the left, chin up
    out += person((0, 0), (215, 168), (380, 172), color=P1).replace('<circle cx="0" cy="0" r="13"', '<circle cx="-99" cy="-99" r="0"')
    head = ellipse(150, 160, 40, 32, SKIN, INK, 2, rot=-15)
    nose = path("M122 132 L112 118 L128 124", INK, 2, fill=SKIN)
    chin = path("M178 138 Q192 136 188 152", INK, 2, fill=SKIN)
    out += limb([(186, 160), (215, 168)], SKIN, 22) + head + nose + chin + circle(132, 140, 3, INK, "none", 0)
    # hand on forehead
    out += limb([(60, 40), (90, 100), (118, 128)], P2, 12) + ellipse(122, 136, 22, 10, SKIN, INK, 2, rot=30)
    # two fingers under the chin
    out += limb([(260, 40), (230, 100), (200, 132)], P2, 12) + ellipse(196, 140, 14, 7, SKIN, INK, 2, rot=-60)
    out += arrow([(94, 160), (84, 176)], RED, 3.5, 10) + label(56, 150, "press", 13) + label(56, 166, "forehead", 13)
    out += arrow([(226, 150), (214, 122)], RED, 3.5, 10) + label(290, 120, "lift the chin", 13) + label(290, 136, "with 2 fingers", 13)
    return out + label(200, 22, "Tilt the head back: the tongue moves off the airway", 13)


@fig("recovery-position", 400, 250)
def _():
    def arms_ready(dx):
        near = [(dx + 52, 56), (dx + 24, 62), (dx + 22, 36)]
        far = [(dx + 80, 56), (dx + 82, 86), (dx + 52, 36)]
        return near, far
    out = ""
    # 1: on the back, arm at right angle, other hand to cheek
    n, fa = arms_ready(0)
    out += person((66, 30), (66, 48), (66, 128), arms=[n, fa], legs=[[(58, 128), (56, 172), (56, 222)], [(74, 128), (76, 172), (76, 222)]])
    out += step(14, 14, 1) + label(66, 232, "arm out,", 11) + label(66, 245, "hand to cheek", 11)
    # 2: far knee up, roll towards you
    n, fa = arms_ready(133)
    out += person((199, 30), (199, 48), (199, 128), arms=[n, fa], legs=[[(191, 128), (189, 172), (189, 222)], [(207, 128), (222, 162), (214, 186)]])
    out += arrow([(236, 170), (200, 205), (160, 190)], RED, 3, 10) + step(147, 14, 2) + label(199, 232, "far knee up,", 11) + label(199, 245, "roll them to you", 11)
    # 3: on the side
    out += person((298, 32), (304, 50), (314, 128),
                  arms=[[(296, 56), (270, 62), (268, 36)], [(312, 56), (310, 70), (284, 40)]],
                  legs=[[(310, 128), (276, 140), (276, 186)], [(318, 128), (322, 176), (326, 222)]])
    out += step(280, 14, 3) + label(332, 232, "head tilted back,", 11) + label(332, 245, "check breathing", 11)
    return out + line(133, 10, 133, 230, LIGHT, 2) + line(266, 10, 266, 230, LIGHT, 2) + label(200, 8, "", 1)


@fig("aed-pads", 400, 230)
def _():
    cx, top = 140, 8
    out = body_front(cx, top) + chest_marks(cx, top)
    out += rect(cx - 46, top + 70, 34, 46, "#e8e8e8", INK, 2, 4) + line(cx - 29, top + 70, cx - 29, top + 50, "#333", 2)
    out += rect(cx + 30, top + 128, 46, 34, "#e8e8e8", INK, 2, 4) + line(cx + 53, top + 128, cx + 70, top + 110, "#333", 2)
    out += label(cx - 29, top + 98, "1", 18) + label(cx + 53, top + 152, "2", 18)
    out += label(310, 60, "1 below their right") + label(310, 76, "collarbone")
    out += label(310, 140, "2 their left side,") + label(310, 156, "below the armpit")
    out += label(310, 200, "Bare, dry chest.", 13) + label(310, 216, "Nobody touches them", 13) + label(310, 232 - 4, "", 1)
    return out


@fig("choking-back-blows", 400, 220)
def _():
    gy = 208
    pat = person((316, 98), (296, 106), (236, 128), color=P1,
                 legs=[[(236, 128), (238, 168), (240, gy - 4)]], back_legs=[[(236, 128), (250, 168), (256, gy - 4)]],
                 back_arms=[[(290, 110), (300, 140), (304, 168)]])
    helper = person((176, 40), (174, 62), (170, 130), color=P2,
                    legs=[[(170, 130), (168, 170), (166, gy - 4)]], back_legs=[[(170, 130), (182, 170), (186, gy - 4)]],
                    back_arms=[[(180, 70), (232, 108), (300, 126)]])
    strike = limb([(170, 68), (210, 50), (262, 98)], P2, 11) + circle(264, 100, 7, SKIN, INK, 2)
    marks = line(250, 82, 244, 72, RED, 3) + line(262, 80, 262, 68, RED, 3) + line(274, 84, 280, 74, RED, 3)
    return (ground(gy) + helper + pat + strike + marks + label(80, 40, "Support the chest,", 13) + label(80, 56, "lean them forward", 13)
            + label(84, 96, "Up to 5 hard blows", 13) + label(84, 112, "between the", 13) + label(84, 128, "shoulder blades", 13)
            + label(84, 144, "with the heel", 13) + label(84, 160, "of your hand", 13))


@fig("choking-thrusts", 400, 230)
def _():
    gy = 216
    helper = person((176, 40), (178, 64), (182, 138), color=P2,
                    legs=[[(182, 138), (180, 178), (176, gy - 4)]], back_legs=[[(182, 138), (196, 178), (200, gy - 4)]],
                    back_arms=[[(188, 74), (226, 98), (252, 116)]])
    pat = person((246, 46), (238, 70), (226, 140), color=P1,
                 legs=[[(226, 140), (230, 178), (236, gy - 4)]], back_legs=[[(226, 140), (220, 178), (216, gy - 4)]],
                 back_arms=[[(244, 76), (256, 112), (258, 140)]])
    near = limb([(176, 72), (204, 104), (246, 118)], P2, 11) + circle(250, 118, 9, SKIN, INK, 2)
    belly = circle(250, 118, 13, "none", RED, 3)
    out = ground(gy) + helper + pat + near + belly
    out += arrow([(276, 132), (272, 112), (258, 96)], RED, 4, 12) + label(310, 150, "pull sharply", 13) + label(310, 166, "IN and UP", 13)
    out += label(90, 120, "Fist just above", 13) + label(90, 136, "the belly button,", 13) + label(90, 152, "other hand over it", 13)
    out += label(320, 34, "Up to 5 thrusts,", 13) + label(320, 50, "then 5 back blows", 13)
    return out


@fig("choking-infant", 400, 200)
def _():
    out = ground(186)
    out += log(60, 150, 300, 150, 30, "#3b4752")  # your thigh
    out += limb([(320, 118), (220, 120), (128, 140)], SKIN, 20)  # your forearm, sloping down to the hand
    baby = person((118, 124), (134, 120), (204, 108), color="#f2e1b0", scale=0.7,
                  legs=[[(204, 108), (226, 124), (232, 140)]], back_legs=[[(204, 108), (222, 100), (240, 108)]],
                  back_arms=[[(140, 120), (138, 140), (130, 150)]])
    hand = ellipse(116, 146, 16, 8, SKIN, INK, 2, rot=-10)
    blow = limb([(250, 20), (210, 50), (176, 82)], P2, 11) + circle(174, 86, 8, SKIN, INK, 2) + line(166, 100, 160, 92, RED, 3) + line(178, 102, 180, 94, RED, 3)
    return (out + baby + hand + blow + label(90, 40, "Baby face down,", 13) + label(90, 56, "head LOWER than body,", 13)
            + label(90, 72, "your hand holds the jaw", 13) + label(300, 70, "up to 5 back blows", 13)
            + label(300, 176, "rest your arm on your thigh", 12))


@fig("tourniquet", 400, 220)
def _():
    out = limb([(10, 120), (200, 118)], SKIN, 46) + limb([(200, 118), (360, 124)], SKIN, 38)
    out += circle(388, 126, 20, SKIN, INK, 2)
    out += path("M296 118 l6 -6 l6 8 l6 -8 l6 6", RED, 3) + circle(312, 122, 9, "rgba(208,52,44,.5)", RED, 2)
    out += rect(236, 94, 18, 56, "#d9d2c3", INK, 2, 3)
    out += log(212, 86, 280, 98, 7, WOOD) + circle(245, 92, 6, "#d9d2c3", INK, 2)
    out += curved_arrow(245, 92, 26, 200, 340, RED, 3)
    out += text(130, 108, "T 14:05", 15, "middle", RED, "bold")
    out += step(245, 170, 1) + label(245, 196, "5-7 cm above the wound,", 12) + label(245, 210, "not on a joint", 12)
    out += step(245, 30, 2) + label(325, 34, "stick in the knot:", 12) + label(325, 48, "twist until bleeding", 12) + label(325, 62, "stops", 12)
    out += step(70, 30, 3) + label(130, 30, "lock the stick,", 12) + label(130, 46, "write the time", 12)
    out += label(320, 160, "wound", 12) + label(60, 170, "towards the body", 11) + arrow([(110, 176), (20, 176)], GREY, 2, 8)
    return out


@fig("sling", 400, 240)
def _():
    cx, top = 150, 8
    out = body_front(cx, top, shirt="#7d9cc0", arms_down=False)
    out += limb([(cx + 48, top + 70), (cx + 60, top + 140), (cx + 62, top + 200)], "#7d9cc0", 18)
    out += limb([(cx - 48, top + 70), (cx - 58, top + 150)], "#7d9cc0", 18)
    out += limb([(cx - 58, top + 150), (cx + 30, top + 118)], "#7d9cc0", 18) + circle(cx + 36, top + 116, 9, SKIN, INK, 2)
    out += poly([(cx + 26, top + 54), (cx + 50, top + 142), (cx - 70, top + 170), (cx - 46, top + 60)], "rgba(240,236,220,.8)", INK, 2)
    out += circle(cx - 38, top + 56, 7, "#e7dfcb", INK, 2)
    out += circle(cx - 66, top + 166, 4, RED, INK, 1)
    out += label(300, 40, "Knot at the side", 13) + label(300, 56, "of the neck", 13) + line(244, 46, cx - 30, top + 54, GREY, 1.5)
    out += label(310, 110, "Hand a little", 13) + label(310, 126, "higher than elbow", 13)
    out += label(310, 186, "Pin or twist the", 13) + label(310, 202, "corner at the elbow", 13) + line(244, 196, cx - 62, top + 168, GREY, 1.5)
    return out


@fig("splint-leg", 400, 200)
def _():
    out = limb([(10, 96), (150, 100)], SKIN, 40) + limb([(150, 100), (330, 106)], SKIN, 30)
    out += path("M326 92 L360 70 L372 86 L338 120 Z", INK, 2, fill=SKIN)
    out += path("M236 92 l6 6 l-6 6 l6 6 l-6 6", RED, 3)
    out += log(110, 74, 352, 80, 10, WOOD) + log(110, 128, 352, 134, 10, WOOD)
    for x in (128, 190, 296, 340):
        out += rect(x - 6, 66, 12, 76, "#d9d2c3", INK, 2, 3)
    out += text(239, 60, "break", 13, "middle", RED, "bold")
    out += label(200, 168, "Splint longer than the bone: past the knee AND the ankle.", 12)
    out += label(200, 184, "Tie in 2+ places, never over the break. Pad the gaps.", 12)
    out += label(150, 30, "knee", 12) + label(330, 40, "ankle", 12)
    return out


@fig("stretcher", 400, 200)
def _():
    out = log(20, 50, 380, 50, 10) + log(20, 150, 380, 150, 10)
    for x0 in (70, 160, 250):
        out += rect(x0, 50, 80, 100, "#6f8f5e", INK, 2, 4) + line(x0 + 40, 54, x0 + 40, 146, "#3b4a32", 3, dash="4 3")
        out += rect(x0 + 6, 40, 24, 20, "#5d7a4e", INK, 2, 6) + rect(x0 + 50, 40, 24, 20, "#5d7a4e", INK, 2, 6)
        out += rect(x0 + 6, 140, 24, 20, "#5d7a4e", INK, 2, 6) + rect(x0 + 50, 140, 24, 20, "#5d7a4e", INK, 2, 6)
    out += log(20, 50, 66, 50, 10) + log(334, 50, 380, 50, 10) + log(20, 150, 66, 150, 10) + log(334, 150, 380, 150, 10)
    return (out + label(200, 22, "2 poles of 2 m through the sleeves of 2-3 jackets", 13)
            + label(200, 182, "Zip or button the jackets, sleeves inside. Test it first.", 12))


@fig("shock-legs-up", 400, 190)
def _():
    gy = 176
    out = ground(gy) + rect(10, gy - 8, 300, 8, "#b8a27a", INK, 1.5)
    out += rect(280, gy - 52, 70, 52, "#6f8f5e", INK, 2, 8)
    out += lying(40, gy - 6, legs_up=True)
    out += path("M60 %d Q160 %d 230 %d" % (gy - 32, gy - 44, gy - 30), INK, 2, fill="none")
    out += label(110, 40, "Lie them flat, raise", 13) + label(110, 56, "the legs about 30 cm", 13)
    out += label(320, 40, "Keep warm:", 13) + label(320, 56, "blanket under", 13) + label(320, 72, "and over", 13)
    return out


@fig("hypothermia-warming", 400, 230)
def _():
    cx, top = 120, 6
    out = body_front(cx, top, shirt="#7d9cc0")
    for x, y in ((cx - 14, top + 46), (cx + 14, top + 46), (cx - 44, top + 76), (cx + 44, top + 76), (cx, top + 110),
                 (cx - 18, top + 196), (cx + 18, top + 196)):
        out += circle(x, y, 9, "rgba(208,52,44,.6)", RED, 2)
    for x, y in ((cx - 62, top + 206), (cx + 62, top + 206)):
        out += line(x - 8, y - 8, x + 8, y + 8, INK, 3) + line(x - 8, y + 8, x + 8, y - 8, INK, 3)
    out += label(300, 50, "Warm packs here:") + label(300, 70, "neck, armpits,") + label(300, 86, "chest, groin")
    out += label(300, 140, "Not on hands", 13) + label(300, 156, "and feet (X)", 13)
    out += label(300, 200, "Wrap packs in cloth", 12)
    return out


@fig("help-huddle", 400, 200)
def _():
    water = rect(2, 90, 396, 106, WATER, "none", 0) + path("M4 90 q12 -8 24 0 t24 0 t24 0 t24 0 t24 0 t24 0 t24 0 t24 0", "#3b78b0", 3)
    out = water
    # HELP: knees to chest, arms crossed, life jacket
    out += person((90, 64), (90, 84), (96, 128), color="#f08a24",
                  legs=[[(96, 128), (122, 108), (110, 148)]], arms=[[(84, 92), (110, 104), (80, 108)], [(98, 92), (72, 104), (102, 108)]])
    out += path("M4 96 q12 -8 24 0 t24 0 t24 0 t24 0 t24 0 t24 0 t24 0 t24 0", "rgba(59,120,176,.6)", 3)
    out += label(96, 22, "Alone: HELP", 13) + label(96, 38, "knees up, arms crossed", 12)
    out += line(200, 10, 200, 190, LIGHT, 2)
    for i in range(4):
        import math as _m
        a = _m.radians(45 + i * 90)
        x, y = 300 + 34 * _m.cos(a), 128 + 26 * _m.sin(a)
        out += circle(x, y, 16, "#f08a24", INK, 2) + circle(x, y, 9, SKIN, INK, 2)
    out += circle(300, 128, 40, "none", INK, 2)
    out += label(300, 22, "Group: huddle", 13) + label(300, 38, "close, sides together", 12)
    return out



# ================================================================ SHELTER
def peg(x, y):
    return poly([(x - 5, y - 6), (x + 5, y - 6), (x, y + 10)], WOOD, INK, 1.5)


def leaves(x, y, w, h, n=40, seed=3):
    import random
    rnd = random.Random(seed)
    out = ""
    for _ in range(n):
        cx, cy = x + rnd.random() * w, y + rnd.random() * h
        out += ellipse(cx, cy, 7, 3.5, rnd.choice(["#b5762e", "#c99236", "#8f5a22", "#a8812f"]), "#5b3a14", 1, rnd.randint(0, 180))
    return out


@fig("tarp-a-frame", 400, 220)
def _():
    gy = 204
    out = ground(gy) + rect(193, 20, 14, gy - 20, WOOD, INK, 2) + circle(200, 30, 40, GREEN, INK, 2)
    out += poly([(200, 74), (300, gy - 6), (100, gy - 6)], "#3f7f5a", INK, 2.5)
    out += poly([(200, 92), (276, gy - 8), (124, gy - 8)], "#2a5a3e", "none", 0)
    out += person((150, 180), (168, 186), (250, 188), legs=[[(250, 188), (280, 190)]], color=P1, scale=0.7)
    out += circle(200, 74, 4, INK, "none", 0) + peg(100, gy - 2) + peg(300, gy - 2)
    out += label(320, 60, "line between two", 12) + label(320, 74, "trees, chest height", 12) + line(262, 70, 206, 74, GREY, 1.5)
    out += label(76, 120, "tarp over the line,", 12) + label(76, 134, "edges pegged down", 12)
    out += label(330, 140, "end view: low,", 12) + label(330, 154, "narrow end", 12) + label(330, 168, "into the wind", 12)
    return out

@fig("tarp-lean-to", 400, 220)
def _():
    gy = 200
    out = ground(gy) + rect(120, 50, 12, gy - 50, WOOD, INK, 2)
    out += line(126, 62, 126, 62, INK, 3)
    out += poly([(126, 62), (300, gy - 4), (340, gy - 16), (166, 48)], "#3f7f5a", INK, 2) + line(126, 62, 166, 48, "#555", 3)
    out += peg(300, gy - 2)
    out += person((210, 168), (192, 176), (150, 182), legs=[[(150, 182), (120, 186), (88, 188)]], color=P1, scale=0.8)
    out += flame(60, gy - 6, 0.8) + log(40, gy - 6, 82, gy - 6, 6)
    for i in range(4):
        out += ellipse(16, gy - 8 - i * 13, 8, 6.5, WOOD, INK, 2)
    out += arrow([(390, 90), (330, 110)], "#5b8bd0", 4, 12) + arrow([(390, 130), (340, 140)], "#5b8bd0", 4, 12)
    out += label(360, 76, "wind", 13) + label(60, 120, "fire with", 12) + label(60, 134, "reflector wall", 12)
    out += label(230, 36, "open side away from the wind", 13)
    return out


@fig("debris-hut", 400, 220)
def _():
    gy = 204
    out = ground(gy)
    out += path("M30 %d Q36 120 70 104 Q150 112 360 %d Z" % (gy, gy), INK, 2, fill="#a8812f")
    import random as _r
    rr = _r.Random(5)
    for _ in range(110):
        x = 40 + rr.random() * 300
        top = 120 + max(0, x - 80) * 0.25
        y = top + rr.random() * (gy - 8 - top)
        out += ellipse(x, y, 7, 3.5, rr.choice(["#b5762e", "#c99236", "#8f5a22", "#a8812f"]), "#5b3a14", 1, rr.randint(0, 180))
    out += path("M60 %d Q66 140 80 132 L330 %d" % (gy, gy), "#4a2f12", 2, dash="5 4")
    out += log(64, gy, 66, 130, 10) + log(66, 130, 360, gy - 2, 7)
    for x in range(100, 330, 30):
        y = 130 + (x - 66) * (gy - 2 - 130) / (360 - 66)
        out += line(x, y, x - 14, gy, WOOD_D, 3)
    out += person((110, 170), (128, 176), (200, 186), legs=[[(200, 186), (260, 192)]], color=P1, scale=0.75)
    out += line(380, 108, 380, 196, RED, 2) + line(372, 108, 388, 108, RED, 2) + label(345, 100, "60-90 cm leaves", 12)
    out += label(200, 30, "Ridge pole from a stump at hip height to the ground,", 12)
    out += label(200, 46, "sticks leaning on both sides, then a thick leaf pile", 12)
    return out


@fig("snow-cave", 400, 220)
def _():
    gy = 206
    out = rect(2, gy, 396, 12, "#c9d7e3", "none", 0)
    out += path("M10 %d Q60 40 220 36 Q370 40 390 %d Z" % (gy, gy), "#8aa3b8", 2, fill="#eef4f8")
    out += path("M110 %d Q120 100 210 96 Q300 100 320 %d L320 150 L110 150 Z" % (150, 150), "#8aa3b8", 2, fill="#cfdce6")
    out += path("M20 %d L20 172 Q60 172 70 186 L110 186 L110 150 L80 150 L80 160 L40 160 L40 %d Z" % (gy, gy), "none", 0, fill="#cfdce6")
    out += rect(110, 150, 210, 18, "#b9c9d6", "#8aa3b8", 1.5)
    out += person((150, 140), (166, 144), (240, 146), legs=[[(240, 146), (300, 148)]], color=P1, scale=0.75)
    out += line(220, 96, 230, 44, "#5a7287", 3) + line(232, 96, 242, 44, "#5a7287", 3)
    out += arrow([(236, 110), (236, 30)], RED, 3, 10) + label(300, 30, "vent hole: keep open", 12)
    out += arrow([(100, 176), (40, 182)], "#3b78b0", 3, 10) + label(70, 200, "cold air out", 12)
    out += label(215, 124, "warm: sleep higher than the entrance", 12)
    return out


# ================================================================ FIRE
@fig("fire-lays", 400, 210)
def _():
    gy = 180
    out = ground(gy, 6, 394)
    # teepee
    out += ellipse(66, gy - 8, 16, 8, "#e0c46a", INK, 1.5)
    for dx in (-34, -22, -10, 10, 22, 34):
        out += log(66 + dx, gy - 2, 66 + dx * 0.15, gy - 74, 5)
    out += label(66, 204, "Teepee", 13)
    # log cabin
    cx = 200
    for i in range(5):
        y = gy - 6 - i * 11
        if i % 2 == 0:
            out += log(cx - 40, y, cx + 40, y - 4, 8) if i == 0 else log(cx - 36, y, cx + 36, y, 8)
        else:
            out += ellipse(cx - 32, y, 6, 6, WOOD, INK, 2) + ellipse(cx + 32, y, 6, 6, WOOD, INK, 2)
    for dx in (-14, -6, 6, 14):
        out += log(cx + dx, gy - 6, cx + dx * 0.2, gy - 50, 4)
    out += label(cx, 204, "Log cabin", 13)
    # lean-to
    out += log(276, gy - 12, 380, gy - 12, 20)
    for i in range(6):
        out += log(296 + i * 14, gy - 2, 300 + i * 14, gy - 24, 4)
    out += ellipse(330, gy - 6, 30, 6, "#e0c46a", INK, 1.5)
    for i in range(6):
        out += log(296 + i * 14, gy - 2, 290 + i * 15, gy - 30, 5)
    out += arrow([(394, 120), (366, 140)], "#5b8bd0", 3.5, 10) + label(372, 106, "wind", 12)
    out += label(332, 204, "Lean-to", 13)
    out += line(133, 20, 133, 190, LIGHT, 2) + line(266, 20, 266, 190, LIGHT, 2)
    out += label(66, 30, "tinder in the", 12) + label(66, 44, "middle", 12)
    out += label(200, 30, "teepee inside,", 12) + label(200, 44, "cooks steady", 12)
    out += label(320, 30, "big log shields", 12) + label(320, 44, "it from the wind", 12)
    return out


@fig("bow-drill", 400, 240)
def _():
    gy = 214
    out = ground(gy)
    out += rect(60, gy - 18, 210, 14, "#c79a5e", INK, 2)                      # board
    out += path("M150 %d L170 %d L170 %d Z" % (gy - 4, gy - 4, gy - 18), INK, 2, fill="#5a3a1a")
    out += ellipse(160, gy - 2, 26, 5, "#5d8a3e", INK, 1.5)                  # leaf under the notch
    out += path("M200 %d Q190 %d 214 %d L270 %d L270 %d L200 %d Z" % (gy - 18, gy - 50, gy - 46, gy - 40, gy - 22, gy - 20),
                INK, 2, fill="#4a3a2a")                                      # boot on the board
    out += rect(156, 74, 12, gy - 18 - 74, "#d8b07a", INK, 2)                 # spindle
    out += rect(138, 56, 48, 18, "#8c8c8c", INK, 2, 6)                       # bearing block
    out += limb([(150, 20), (160, 40), (162, 54)], SKIN, 14)
    out += path("M20 120 Q110 96 300 116", WOOD_D, 7) + path("M20 120 Q110 96 300 116", WOOD, 4)   # bow
    out += path("M24 124 L156 132 M168 126 L296 120", "#333", 2) + path("M156 124 L168 132 M156 132 L168 124", "#333", 2)
    out += arrow([(70, 150), (30, 150)], RED, 3, 9) + arrow([(90, 160), (130, 160)], RED, 3, 9)
    out += label(84, 182, "long even strokes", 12)
    out += label(255, 64, "bearing block,", 12) + label(255, 78, "press down", 12)
    out += label(330, 104, "bow, cord", 12) + label(330, 118, "twisted once", 12) + label(330, 132, "round spindle", 12)
    out += label(140, gy + 2 - 30 - 16, "", 1)
    out += label(338, 172, "foot holds", 12) + label(338, 186, "the board", 12)
    # notch detail, seen from above
    bx, by = 340, 36
    out += rect(bx - 44, by - 22, 88, 44, "#c79a5e", INK, 2) + circle(bx, by + 2, 11, "#3d2a14", INK, 1.5)
    out += poly([(bx, by + 2), (bx - 7, by + 22), (bx + 7, by + 22)], PAPER, INK, 1.5)
    out += label(bx, by + 40, "notch: 1/8 slice", 11)
    out += label(160, 230, "", 1)
    return out


@fig("feather-stick", 400, 140)
def _():
    out = log(30, 70, 370, 70, 26, "#d8b07a")
    for i in range(9):
        x = 120 + i * 24
        out += path("M%d 58 q-16 -8 -26 6 q-4 10 6 12" % x, "#8a6234", 2, fill="#f0d6a8")
    out += label(200, 24, "Shave thin curls along a dry stick, leave them attached", 13)
    out += label(200, 116, "Several feather sticks catch a flame even in wet weather", 12)
    return out


# ================================================================ NAVIGATION
@fig("compass-bearing", 400, 240)
def _():
    out = rect(60, 20, 120, 210, "rgba(220,235,245,.9)", "#6c8ba3", 2, 10)
    out += poly([(120, 26), (108, 52), (132, 52)], RED, INK, 1.5) + line(120, 52, 120, 90, RED, 3)
    out += circle(120, 152, 54, "#ffffff", INK, 2) + circle(120, 152, 46, "none", "#aaa", 1)
    for a in range(0, 360, 30):
        import math as _m
        r1, r2 = 46, 54
        x1, y1 = 120 + r1 * _m.sin(_m.radians(a)), 152 - r1 * _m.cos(_m.radians(a))
        x2, y2 = 120 + r2 * _m.sin(_m.radians(a)), 152 - r2 * _m.cos(_m.radians(a))
        out += line(x1, y1, x2, y2, INK, 1.5)
    out += text(120, 112, "N", 14, weight="bold")
    out += path("M112 120 L112 186 M128 120 L128 186", RED, 1.5) + poly([(120, 112), (110, 128), (130, 128)], "none", RED, 2)
    out += poly([(120, 116), (114, 152), (126, 152)], RED, INK, 1) + poly([(120, 188), (114, 152), (126, 152)], "#ffffff", INK, 1)
    out += line(120, 90, 120, 98, INK, 3)
    out += step(208, 36, 1) + label(296, 32, "point the arrow", 12) + label(296, 46, "at your target", 12)
    out += step(208, 86, 2) + label(298, 80, "turn the dial until", 12) + label(298, 94, "the red needle sits", 12) + label(298, 108, "in the outline (shed)", 12)
    out += step(208, 146, 3) + label(296, 150, "read the degrees", 12) + label(296, 164, "at the arrow's foot", 12) + line(240, 150, 126, 96, GREY, 1.5)
    out += label(300, 196, "Walk where the arrow", 12) + label(300, 210, "points; keep red in", 12) + label(300, 224, "the shed", 12)
    return out


@fig("shadow-stick", 400, 210)
def _():
    out = poly([(10, 120), (390, 120), (380, 200), (20, 200)], "#d9cfae", "#b8a77a", 1.5)
    out += line(200, 170, 200, 70, WOOD_D, 6)
    out += line(200, 170, 110, 140, "#7d7563", 6) + line(200, 170, 290, 146, "#7d7563", 4)
    out += circle(110, 140, 6, "#fff", INK, 2) + circle(290, 146, 6, "#fff", INK, 2)
    out += line(110, 140, 290, 146, RED, 2.5, dash="6 4") + arrowhead(300, 146.4, 2, RED, 12)
    out += label(96, 124, "1st mark", 12) + label(96, 168, "West", 13) + label(304, 130, "2nd mark", 12) + label(318, 168, "East", 13)
    out += label(200, 30, "Mark the shadow tip, wait 15-20 minutes, mark again.", 12)
    out += label(200, 46, "1st mark = West, 2nd = East. North is at a right angle", 12)
    out += label(200, 62, "(left of the line when you face East).", 12)
    return out


@fig("watch-method", 400, 220)
def _():
    import math as _m
    cx, cy, r = 140, 116, 82
    out = circle(cx, cy, r, "#fff", INK, 3)
    for h in range(12):
        a = _m.radians(h * 30)
        out += line(cx + (r - 10) * _m.sin(a), cy - (r - 10) * _m.cos(a), cx + (r - 2) * _m.sin(a), cy - (r - 2) * _m.cos(a), INK, 3 if h % 3 == 0 else 1.5)
    out += text(cx, cy - r + 26, "12", 14, weight="bold")
    a4 = _m.radians(4 * 30)
    out += line(cx, cy, cx + 50 * _m.sin(a4), cy - 50 * _m.cos(a4), INK, 6)
    out += line(cx + 50 * _m.sin(a4), cy - 50 * _m.cos(a4), cx + 140 * _m.sin(a4), cy - 140 * _m.cos(a4), "#e0a000", 2, dash="4 4")
    sx, sy = cx + 150 * _m.sin(a4), cy - 150 * _m.cos(a4)
    out += circle(sx, sy, 14, "#ffd23f", "#c08a00", 2)
    a2 = _m.radians(2 * 30)
    out += line(cx, cy, cx + (r + 30) * _m.sin(a2), cy - (r + 30) * _m.cos(a2), RED, 3, dash="6 4")
    out += arrowhead(cx + (r + 34) * _m.sin(a2), cy - (r + 34) * _m.cos(a2), -30, RED, 12)
    out += text(cx + (r + 36) * _m.sin(a2) + 20, cy - (r + 36) * _m.cos(a2) - 4, "SOUTH", 14, "start", RED, "bold")
    out += circle(cx, cy, 5, INK, "none", 0)
    out += label(320, 120, "Hour hand at the sun.", 12) + label(320, 136, "South is halfway", 12) + label(320, 152, "between it and 12", 12)
    out += label(320, 172, "(summer time: use 1)", 12)
    out += label(320, 30 - 4, "", 1)
    return out


def _sky(h):
    return rect(1, 1, 398, h - 2, "#1d2a44", "#bdb5a3", 1, 8)


def star(x, y, r=4, col="#fff8d0"):
    return circle(x, y, r, col, "none", 0)


@fig("stars-north", 400, 230)
def _():
    out = _sky(230)
    M, D = (50, 120), (78, 112)
    v = (D[0] - M[0], D[1] - M[1])
    pol = (D[0] + 4.5 * v[0], D[1] + 4.5 * v[1])
    dipper = [(120, 190), (104, 176), (95, 158), (85, 137), D, M, (57, 145), (85, 137)]
    out += polyline(dipper, "#8fa6c9", 1.5)
    for x, y in dipper:
        out += star(x, y)
    out += line(M[0], M[1], pol[0], pol[1], "#ffd23f", 1.5, dash="5 5") + star(pol[0], pol[1], 6, "#ffffff")
    little = [pol, (170, 96), (150, 112), (132, 132), (120, 150)]
    out += polyline(little, "#56688a", 1)
    cas = [(280, 64), (296, 42), (312, 58), (330, 36), (346, 54)]
    out += polyline(cas, "#8fa6c9", 1.5) + "".join(star(x, y) for x, y in cas)
    out += rect(1, 200, 398, 28, "#2f3b26", "none", 0)
    out += line(pol[0], pol[1] + 10, pol[0], 198, "#ffd23f", 1.5, dash="3 4")
    out += text(pol[0], 220, "NORTH", 14, "middle", "#ffd23f", "bold").replace('stroke="%s"' % PAPER, 'stroke="#2f3b26"')
    t = lambda x, y, s, sz=12: text(x, y, s, sz, "middle", "#e8eefc").replace('stroke="%s"' % PAPER, 'stroke="#1d2a44"')
    out += t(pol[0] + 30, pol[1] - 12, "Polaris (North Star)") + t(62, 78, "Plough / Big Dipper")
    out += t(140, 64, "5x the gap", 11) + t(314, 86, "Cassiopeia (W)") + t(300, 170, "Polaris is not very bright,", 11)
    out += t(300, 184, "at the end of the Little Dipper", 11)
    return out

@fig("southern-cross", 400, 230)
def _():
    out = _sky(230)
    g, a = (222, 30), (230, 70)
    cross = [g, a, (206, 54), (246, 46)]
    out += line(g[0], g[1], a[0], a[1], "#8fa6c9", 1.5) + line(206, 54, 246, 46, "#8fa6c9", 1.5)
    for x, y in cross:
        out += star(x, y, 4.5)
    pole = (a[0] + (a[0] - g[0]) * 3.2, a[1] + (a[1] - g[1]) * 3.2)
    out += line(a[0], a[1], pole[0], pole[1], "#ffd23f", 1.5, dash="5 5") + circle(pole[0], pole[1], 6, "none", "#ffd23f", 2)
    out += star(120, 84, 5) + star(146, 64, 5)
    out += rect(1, 200, 398, 28, "#2f3b26", "none", 0)
    out += line(pole[0], pole[1], pole[0], 198, "#ffd23f", 1.5, dash="3 4")
    out += text(pole[0], 220, "SOUTH", 14, "middle", "#ffd23f", "bold").replace('stroke="%s"' % PAPER, 'stroke="#2f3b26"')
    t = lambda x, y, s, sz=12: text(x, y, s, sz, "middle", "#e8eefc").replace('stroke="%s"' % PAPER, 'stroke="#1d2a44"')
    out += t(320, 40, "Southern Cross") + t(120, 110, "pointer stars", 11) + t(pole[0] + 84, pole[1] + 4, "4.5x the long axis", 11)
    out += t(80, 30, "Southern hemisphere", 11)
    return out

@fig("moon-south", 400, 220)
def _():
    out = _sky(220)
    out += circle(200, 80, 40, "#fff3c0", "none", 0) + circle(220, 70, 38, "#1d2a44", "none", 0)
    h1, h2 = (196, 40.4), (229.9, 106)
    dx, dy = h2[0] - h1[0], h2[1] - h1[1]
    t = (196 - h1[1]) / dy
    end = (h1[0] + dx * t, 196)
    out += line(h1[0] - dx * 0.3, h1[1] - dy * 0.3, end[0], end[1], "#ffd23f", 1.5, dash="5 5")
    out += rect(1, 196, 398, 22, "#2f3b26", "none", 0)
    out += text(end[0], 214, "roughly SOUTH", 13, "middle", "#ffd23f", "bold").replace('stroke="%s"' % PAPER, 'stroke="#2f3b26"')
    out += text(320, 60, "Line through the", 12, "middle", "#e8eefc").replace('stroke="%s"' % PAPER, 'stroke="#1d2a44"')
    out += text(320, 76, "two horns of a", 12, "middle", "#e8eefc").replace('stroke="%s"' % PAPER, 'stroke="#1d2a44"')
    out += text(320, 92, "crescent moon", 12, "middle", "#e8eefc").replace('stroke="%s"' % PAPER, 'stroke="#1d2a44"')
    out += text(90, 120, "(northern", 11, "middle", "#e8eefc").replace('stroke="%s"' % PAPER, 'stroke="#1d2a44"')
    out += text(90, 134, "hemisphere)", 11, "middle", "#e8eefc").replace('stroke="%s"' % PAPER, 'stroke="#1d2a44"')
    return out


# ================================================================ WATER
@fig("bottle-filter", 400, 270)
def _():
    x0, x1 = 130, 230
    layers = [("gravel", "#9b9384", 40), ("coarse sand", "#d8b980", 30), ("fine sand", "#efd9a6", 30),
              ("crushed charcoal", "#3b3b3b", 30)]
    y = 30
    out = ""
    for name, col, h in layers:
        out += rect(x0, y, x1 - x0, h, col, "none", 0)
        out += label(244, y + h / 2 + 5, name, 13, "start") + line(x1 + 4, y + h / 2, 240, y + h / 2, GREY, 1.5)
        y += h
    out += path("M%d %d L%d %d L%d %d Q%d %d %d %d L%d %d L%d %d L%d %d Q%d %d %d %d Z" % (
        x0, y, x1, y, x1, y + 14, x1, y + 30, 194, y + 40, 194, y + 58, 166, y + 58, 166, y + 40, x0, y + 30, x0, y + 14),
        INK, 2, fill="#f2efe6")
    out += label(244, y + 46, "cloth in the neck", 13, "start") + line(196, y + 44, 240, y + 42, GREY, 1.5)
    out += rect(x0, 30, x1 - x0, y - 30 + 14, "none", INK, 2.5)
    out += line(x0 - 8, 30, x1 + 8, 30, INK, 1.5, dash="4 3") + label(180, 22, "bottom cut off, pour slowly", 12)
    for i in range(3):
        out += path("M180 %d q-4 8 0 10 q4 -2 0 -10" % (y + 64 + i * 14), "#3b78b0", 1.5, fill=WATER)
    out += path("M140 %d L140 262 L220 262 L220 %d" % (y + 104, y + 104), INK, 2.5) + rect(142, 244, 76, 16, WATER, "none", 0)
    out += label(76, 120, "Clears dirt only.", 12) + label(76, 136, "Still boil or", 12) + label(76, 152, "disinfect after!", 12)
    return out


@fig("transpiration-bag", 400, 200)
def _():
    out = log(10, 30, 200, 60, 10) + log(200, 60, 260, 120, 6)
    out += path("M200 50 Q330 40 360 120 Q350 175 300 178 Q240 170 222 64 Z", "#6b8fa8", 2, fill="rgba(200,225,240,.55)")
    import math as _m
    for i in range(9):
        a = i * 0.7
        out += ellipse(240 + 60 * _m.sin(a) + i * 6, 80 + i * 9, 14, 6, "#4f9a4a", INK, 1, i * 25)
    out += path("M300 178 Q312 160 326 164 Q338 172 330 180 Z", "none", 0, fill=WATER)
    out += circle(318, 172, 6, GREY, INK, 1.5)
    out += path("M214 58 L232 72", INK, 4)
    out += label(110, 110, "Clear bag over a", 12) + label(110, 126, "leafy branch in sun,", 12) + label(110, 142, "tied tight", 12)
    out += label(330, 196, "water + small stone", 12)
    return out


@fig("solar-still", 400, 210)
def _():
    gy = 70
    out = rect(2, gy, 396, 136, "#b49a6a", "none", 0) + line(2, gy, 398, gy, GROUND, 3)
    out += path("M70 %d Q200 230 330 %d Z" % (gy, gy), "#8a7454", 2, fill="#e8dcc0")
    out += path("M50 %d L200 150 L350 %d" % (gy - 2, gy - 2), "#6b8fa8", 3)
    out += circle(200, 140, 9, GREY, INK, 2)
    out += path("M176 182 L176 166 L224 166 L224 182 Z", INK, 2, fill="#ddd") + rect(178, 172, 44, 9, WATER, "none", 0)
    out += ellipse(50, gy - 6, 26, 10, "#8a7454", INK, 1.5) + ellipse(350, gy - 6, 26, 10, "#8a7454", INK, 1.5)
    for x, y in ((140, 116), (250, 112), (200, 152)):
        out += path("M%d %d q-3 6 0 8 q3 -2 0 -8" % (x, y), "#3b78b0", 1.5, fill=WATER)
    out += label(200, 24, "Plastic sheet over a hole, stone in the middle,", 12)
    out += label(200, 40, "cup under the stone. About 0.5 L a day: last resort.", 12)
    out += label(300, 196, "edges sealed with soil", 12)
    return out


@fig("rain-catch", 400, 190)
def _():
    gy = 176
    out = ground(gy)
    for x, top in ((60, 70), (340, 70)):
        out += line(x, gy, x, top, WOOD_D, 6)
    out += path("M60 70 Q200 150 340 70 L320 104 Q200 170 80 104 Z", INK, 2, fill="#3f7f5a")
    out += path("M190 140 L190 150", "#3b78b0", 3) + path("M200 146 L200 158", "#3b78b0", 3)
    out += rect(172, 154, 56, 22, "#ddd", INK, 2) + rect(174, 162, 52, 12, WATER, "none", 0)
    out += label(200, 30, "Tie a tarp or poncho with a low middle,", 12) + label(200, 46, "container under it. Treat before drinking.", 12)
    return out


# ================================================================ SIGNALS
@fig("signal-mirror", 400, 200)
def _():
    out = circle(70, 120, 24, SKIN, INK, 2) + circle(80, 114, 3, INK, "none", 0)
    out += rect(92, 104, 10, 26, "#cfe3ef", INK, 2, 2)
    out += limb([(70, 160), (160, 128), (250, 116)], P2, 12)
    out += path("M250 116 L262 92 M250 116 L268 98", SKIN, 7) + path("M250 116 L262 92 M250 116 L268 98", INK, 1)
    out += path("M98 114 L340 52", "#f0c020", 3, dash="8 6")
    out += path("M330 50 l30 -6 l-4 6 l14 6 l-14 0 l-6 8 z", "#555", 1.5, fill="#888")
    out += label(110, 40, "Mirror next to your eye,", 12) + label(110, 56, "other arm out with a V", 12)
    out += label(280, 150, "tilt the mirror until the", 12) + label(280, 166, "light spot sits in the V,", 12)
    out += label(280, 182, "then rock it slightly", 12)
    return out


@fig("ground-signals", 400, 210)
def _():
    out = rect(2, 2, 396, 206, "#9cbf6e", "none", 0)
    def logs(pts):
        return "".join(log(a[0], a[1], b[0], b[1], 9, "#e9e2cf") for a, b in pts)
    out += logs([((26, 40), (50, 110)), ((50, 110), (74, 40))])
    out += logs([((116, 40), (166, 110)), ((166, 40), (116, 110))])
    out += logs([((210, 80), (290, 80)), ((290, 80), (272, 62)), ((290, 80), (272, 98))])
    out += logs([((330, 40), (330, 110)), ((330, 40), (370, 110)), ((370, 110), (370, 40))])
    t = lambda x, y, s: text(x, y, s, 13, "middle", INK, "bold").replace('stroke="%s"' % PAPER, 'stroke="#9cbf6e"')
    out += t(50, 136, "V") + t(50, 152, "need help") + t(141, 136, "X") + t(141, 152, "need doctor")
    out += t(250, 136, "travelling") + t(250, 152, "this way") + t(350, 136, "N") + t(350, 152, "no")
    out += t(200, 186, "At least 3 m tall, in the open, contrasting colours")
    return out


@fig("helicopter-signals", 400, 210)
def _():
    gy = 196
    out = ground(gy)
    out += person((110, 70), (110, 90), (110, 150), arms=[[(104, 94), (86, 66), (72, 40)], [(116, 94), (134, 66), (148, 40)]],
                  legs=[[(106, 150), (100, 172), (96, gy - 4)], [(114, 150), (120, 172), (124, gy - 4)]], color=P2)
    out += person((290, 70), (290, 90), (290, 150), arms=[[(296, 94), (312, 66), (322, 38)], [(284, 94), (268, 120), (262, 150)]],
                  legs=[[(286, 150), (280, 172), (276, gy - 4)], [(294, 150), (300, 172), (304, gy - 4)]], color=P1)
    out += text(110, 26, "YES: need help", 14, weight="bold") + text(290, 26, "NO help needed", 14, weight="bold")
    out += label(200, 120, "back to", 12) + label(200, 134, "the wind", 12)
    out += line(200, 20, 200, 180, LIGHT, 2)
    return out


# ================================================================ WILD
@fig("ice-rescue", 400, 200)
def _():
    wy = 110
    out = rect(2, wy, 396, 88, WATER, "none", 0)
    out += poly([(2, wy - 14), (150, wy - 14), (150, wy + 6), (2, wy + 6)], "#e6f1f8", "#8aa3b8", 2)
    out += poly([(250, wy - 14), (398, wy - 14), (398, wy + 6), (250, wy + 6)], "#e6f1f8", "#8aa3b8", 2)
    out += person((176, wy - 34), (186, wy - 16), (230, wy + 6), arms=[[(180, wy - 14), (156, wy - 24), (128, wy - 26)]],
                  legs=[[(230, wy + 6), (270, wy + 14), (310, wy + 12)]], color=P1)
    out += arrow([(120, wy - 40), (40, wy - 40)], RED, 3.5, 11)
    out += label(80, 50, "back the way you came", 12) + label(80, 66, "(that ice held you)", 12)
    out += label(300, 50, "arms on the ice, kick legs", 12) + label(300, 66, "up level, slide out on belly,", 12)
    out += label(300, 82, "then ROLL away, don't stand", 12)
    out += path("M260 150 q10 -10 20 0 M290 160 q10 -10 20 0", "#3b78b0", 2)
    return out


@fig("bottle-trap", 400, 170)
def _():
    out = rect(2, 2, 396, 166, "rgba(127,182,224,.35)", "none", 0)
    out += path("M80 60 L250 60 Q280 60 290 75 L310 75 L310 105 L290 105 Q280 120 250 120 L80 120 Q66 120 66 106 L66 74 Q66 60 80 60 Z",
                "#6b8fa8", 2, fill="rgba(230,245,255,.6)")
    out += path("M80 60 L120 82 L120 98 L80 120", "#6b8fa8", 2, fill="none")
    out += path("M30 90 q-6 -8 6 -12 q20 -4 22 12 q-2 16 -22 12 q-12 -4 -6 -12 z", "#555", 1.5, fill="#9aa")
    out += arrow([(56, 90), (90, 90)], RED, 3, 10)
    out += ellipse(200, 100, 18, 8, "#8a5a3a", INK, 1.5)
    out += label(200, 30, "Cut off the neck, push it back in upside down", 12)
    out += label(200, 150, "Fish swim in for the bait and can't find the way out", 12)
    out += label(200, 84, "bait", 12)
    return out


@fig("gorge-hook", 400, 150)
def _():
    out = log(80, 60, 200, 60, 6, "#e9e2cf") + path("M76 60 L84 57 L84 63 Z M204 60 L196 57 L196 63 Z", INK, 1, fill=INK)
    out += path("M140 60 Q150 100 190 120", "#555", 2)
    out += label(140, 30, "sliver sharp at both ends,", 12) + label(140, 46, "line tied in the middle", 12)
    out += log(250, 70, 330, 80, 6, "#e9e2cf") + path("M290 75 Q300 110 330 130", "#555", 2)
    out += path("M230 50 Q300 20 360 60 Q380 90 340 110 Q290 120 230 90 Z", "#6b8fa8", 2, fill="rgba(170,200,220,.3)")
    out += label(290, 140, "swallowed, it turns crosswise", 12)
    return out


@fig("stone-trap", 400, 190)
def _():
    out = rect(2, 2, 396, 186, "rgba(127,182,224,.5)", "none", 0)
    for i in range(10):
        t = i / 9
        out += ellipse(50 + 180 * t, 26 + 64 * t, 10, 8, "#8b8b80", INK, 1.5)
        out += ellipse(50 + 180 * t, 164 - 64 * t, 10, 8, "#8b8b80", INK, 1.5)
    for x in (250, 270, 290, 310, 330):
        out += ellipse(x, 84, 10, 8, "#8b8b80", INK, 1.5) + ellipse(x, 116, 10, 8, "#8b8b80", INK, 1.5)
    out += ellipse(344, 92, 8, 8, "#8b8b80", INK, 1.5) + ellipse(344, 108, 8, 8, "#8b8b80", INK, 1.5)
    out += arrow([(20, 96), (70, 96)], "#1d4f80", 3, 10) + label(40, 122, "flow", 12)
    out += label(140, 100, "fish swim into the V", 12) + label(300, 150, "small pen at the point:", 12)
    out += label(300, 166, "block the gap behind them", 12)
    return out

@fig("knife-sharpening", 400, 170)
def _():
    out = rect(40, 110, 320, 34, "#8b8b80", INK, 2, 6)
    out += path("M120 110 L300 70 L312 74 L132 112 Z", INK, 2, fill="#cfd6dc")
    out += path("M300 70 L380 52 L384 64 L312 74 Z", INK, 2, fill="#3a2a1a")
    out += path("M150 110 A40 40 0 0 0 148 100", RED, 2) + label(176, 104, "20°", 13)
    out += arrow([(280, 150), (120, 150)], RED, 3.5, 11)
    out += label(200, 30, "Push the edge forward as if slicing a thin layer off the stone.", 12)
    out += label(200, 46, "Same number of strokes on both sides.", 12)
    return out


@fig("batoning", 400, 210)
def _():
    gy = 196
    out = ground(gy) + rect(140, 110, 90, gy - 110, "#c79a5e", INK, 2) + ellipse(185, 110, 45, 10, "#e3c08a", INK, 2)
    out += path("M120 100 L260 100 L266 106 L120 110 Z", INK, 2, fill="#cfd6dc") + rect(70, 98, 50, 14, "#3a2a1a", INK, 2, 4)
    out += log(250, 40, 290, 90, 14) + arrow([(300, 50), (276, 84)], RED, 3.5, 11)
    out += label(80, 40, "Blade on the log end,", 12) + label(80, 56, "hit the back of the", 12) + label(80, 72, "blade tip with a stick", 12)
    out += label(320, 150, "fixed blade only", 12)
    return out


@fig("reverse-wrap", 400, 160)
def _():
    out = ""
    for i in range(6):
        x = 60 + i * 40
        out += path("M%d 70 q20 -26 40 0" % x, INK, 12) + path("M%d 70 q20 -26 40 0" % x, "#b8a070", 8)
        out += path("M%d 70 q20 26 40 0" % (x + 20 if False else x), INK, 12) + path("M%d 70 q20 26 40 0" % x, "#8f7a4a", 8)
    out += path("M300 70 L340 50 M300 70 L340 92", INK, 12) + path("M300 70 L340 50", "#b8a070", 8) + path("M300 70 L340 92", "#8f7a4a", 8)
    out += curved_arrow(352, 46, 12, 180, 420, RED, 2.5) + curved_arrow(352, 96, 12, 180, -60, RED, 2.5)
    out += label(200, 130, "Twist the top strand away from you, then lay it over the", 12)
    out += label(200, 146, "other strand towards you. Repeat; add fibres as you go.", 12)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    only = sys.argv[1:]
    for name, (w, h, fn) in FIGS.items():
        if only and name not in only:
            continue
        with open(os.path.join(OUT, name + ".svg"), "w", encoding="utf-8") as fh:
            fh.write(svg(w, h, fn()))
    print("wrote %d pictures to %s" % (len(FIGS), os.path.normpath(OUT)))


if __name__ == "__main__":
    main()
