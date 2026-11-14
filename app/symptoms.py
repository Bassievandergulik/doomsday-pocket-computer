"""Offline symptom checker: type how you feel, get the common conditions that fit best.

No AI and no internet. It is a scored lookup in symptoms.txt (English, Dutch, Spanish):
each condition lists its symptoms with a weight, and the conditions that explain most of
what you typed come first. It is NOT a diagnosis; it tells you what to read and how urgent
it may be, and danger signs always show a red warning.
"""
import difflib
import math
import re

from search import STOPWORDS, fold, stem_match, tokens

LANGS = ["en", "nl", "es"]
LEVELS = {"now": 0, "soon": 1, "self": 2}
# filler words in how people describe symptoms; "not"/"no"/"cannot" stay (no urine, cannot breathe)
EXTRA_STOP = set("""
have has had got after ago getting feel feeling feels very really bit slightly little lot also some since days day
heb hebt heeft na geleden ik voel voelt erg heel beetje veel sinds dagen dag ook last van mijn
tengo tiene siento despues hace muy mucho poco tambien desde dias dia me
""".split()) - {"little"}
STOP = (STOPWORDS | EXTRA_STOP) - {"no", "not", "cannot"}
# split a description into parts: "fever, stiff neck and headache"
_CLAUSE = re.compile(r"[,;.\n+/]| and | en | y | with | met | con ", re.I)


def _toks(text):
    return [t for t in tokens(text) if t not in STOP]


class SymptomChecker:
    def __init__(self, path):
        self.symptoms = {}     # id -> {"flag": str, "words": {lang: [phrase]}}
        self.conditions = []
        self.phrases = []      # (token tuple, symptom id, lang), longest first
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip() or line.startswith("#"):
                    continue
                cols = line.split("|")
                if cols[0] == "S":
                    sid, flag, cells = cols[1], cols[2], cols[3:]
                    words = {l: [w.strip() for w in c.split("/") if w.strip()] for l, c in zip(LANGS, cells)}
                    self.symptoms[sid] = {"flag": flag, "words": words}
                    for l, ws in words.items():
                        for w in ws:
                            tk = tuple(_toks(w))
                            if tk:
                                self.phrases.append((tk, sid, l))
                elif cols[0] == "C":
                    cid, level, guide, wiki, en, nl, es, syms, advice = cols[1:10]
                    weights = {}
                    for part in syms.split(","):
                        s, w = part.split(":")
                        if s not in self.symptoms:
                            raise ValueError("%s: unknown symptom %s" % (cid, s))
                        weights[s] = float(w)
                    self.conditions.append({"id": cid, "level": level, "guide": guide or None, "wiki": wiki,
                                            "names": {"en": en, "nl": nl, "es": es},
                                            "weights": weights, "advice": advice})
        self.by_id = {c["id"]: c for c in self.conditions}
        self.phrases.sort(key=lambda p: -len(p[0]))
        self.single = {}
        for tk, sid, l in self.phrases:
            if len(tk) == 1 and len(tk[0]) >= 5:
                self.single.setdefault(tk[0], (sid, l))

    # ------------------------------------------------------------------ understanding
    def understand(self, q):
        """[(symptom id, text matched, lang)], [words not understood]"""
        found, votes, unknown = [], {}, []
        seen = set()
        for clause in _CLAUSE.split(" %s " % q):
            toks = _toks(clause)
            used = [False] * len(toks)
            for tk, sid, lang in self.phrases:
                pos = self._match(tk, toks, used)
                if pos is None:
                    continue
                for i in pos:
                    used[i] = True
                votes[lang] = votes.get(lang, 0) + 1
                if sid not in seen:
                    seen.add(sid)
                    found.append({"id": sid, "text": " ".join(toks[i] for i in sorted(pos)), "lang": lang})
            for i, t in enumerate(toks):  # typos: "diarea", "hoofpijn"
                if used[i] or len(t) < 5 or t.isdigit():
                    continue
                close = difflib.get_close_matches(t, [w for w in self.single if w[0] == t[0]], n=1, cutoff=0.8)
                if close:
                    sid, lang = self.single[close[0]]
                    used[i] = True
                    if sid not in seen:
                        seen.add(sid)
                        found.append({"id": sid, "text": t, "lang": lang, "corrected": close[0]})
                else:
                    unknown.append(t)
        lang = max(votes, key=votes.get) if votes else None
        return found, unknown, lang

    @staticmethod
    def _match(tk, toks, used):
        """Positions of the phrase's words among the free words of one clause, in any order
        and close together ("pain in my chest" = "chest pain"), or None."""
        free = [i for i, u in enumerate(used) if not u]
        if len(tk) == 1:
            for i in free:
                if stem_match(tk[0], toks[i]):
                    return [i]
            return None
        # in order, side by side first
        for i in free:
            if all(i + k < len(toks) and not used[i + k] and stem_match(tk[k], toks[i + k]) for k in range(len(tk))):
                return list(range(i, i + len(tk)))
        pos = []
        for w in tk:
            cand = [i for i in free if i not in pos and stem_match(w, toks[i])]
            if not cand:
                return None
            pos.append(cand[0])
        return pos if max(pos) - min(pos) < len(tk) + 2 else None

    # ------------------------------------------------------------------ ranking
    def check(self, q, limit=6):
        found, unknown, lang = self.understand(q)
        ids = {f["id"] for f in found}
        real = [f for f in found if self.symptoms[f["id"]]["flag"] != "c"]
        if not real:
            return None
        lang = lang or "en"
        ranked = []
        for c in self.conditions:
            w = c["weights"]
            hit = [s for s in w if s in ids]
            if not hit:
                continue
            got = sum(w[s] for s in hit)
            total = sum(w.values())
            explained = len(hit) / len(ids)
            # fits what you typed (explained) and you have its typical signs (got/total)
            score = explained * got / math.sqrt(total * 4)
            # a key circumstance (a dog bite, a heater indoors, wild mushrooms) that you did not mention
            if any(w[s] >= 3 and s not in ids and self.symptoms[s]["flag"] == "c" for s in w):
                score *= 0.5
            ranked.append((score, c, hit))
        ranked.sort(key=lambda r: (-r[0], LEVELS[r[1]["level"]]))
        if not ranked:
            return None
        best = ranked[0][0]
        name = lambda sid: self.symptoms[sid]["words"].get(lang, [None])[0] or self.symptoms[sid]["words"]["en"][0]  # noqa: E731
        out = []
        for score, c, hit in ranked[:limit]:
            if score < best * 0.35:
                break
            missing = sorted((s for s in c["weights"] if s not in ids and c["weights"][s] >= 2), key=lambda s: -c["weights"][s])
            out.append({"id": c["id"], "level": c["level"], "guide": c["guide"], "wiki": c["wiki"],
                        "name": c["names"]["en"], "local": c["names"].get(lang) if lang != "en" else None,
                        "match": round(min(1.0, score / 0.6), 2),
                        "matched": [name(s) for s in hit], "also": [name(s) for s in missing[:4]],
                        "advice": c["advice"]})
        danger = [name(f["id"]) for f in found if self.symptoms[f["id"]]["flag"] == "!"]
        return {"symptoms": [dict(f, name=name(f["id"])) for f in found], "unknown": unknown, "language": lang,
                "danger": danger, "conditions": out,
                "urgent": bool(danger) or (bool(out) and out[0]["level"] == "now")}
