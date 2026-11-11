"""Offline multilingual search over everything stored on the device.

No AI and no internet: it only ever shows what is really on the SD card.

- Understands survival words in 12 languages (lexicon.txt), so "brandwond", "quemadura",
  "Verbrennung" and "ожог" all find the burns page, and each Wikipedia gets the query
  in its own language.
- Forgives typos ("hypotermia") and word endings ("Verbrennungen").
- Ignores accents and capitals, so the on-screen keyboard without accents is enough.
"""
import difflib
import os
import re
import unicodedata

LANGS = ["en", "nl", "es", "de", "fr", "pt", "it", "pl", "uk", "ru", "ar", "tr"]
LANG_NAMES = {"en": "English", "nl": "Nederlands", "es": "Español", "de": "Deutsch", "fr": "Français",
              "pt": "Português", "it": "Italiano", "pl": "Polski", "uk": "Українська", "ru": "Русский",
              "ar": "العربية", "tr": "Türkçe"}

# little words that would otherwise match everything (or the wrong concept: Polish "las" = forest)
STOPWORDS = set("""
a an the of to in on at for and or is are be how what with my do i you it this that from by as
de het een en van op te in is hoe wat met voor bij mijn ik je er aan om dat die
el la los las un una y o del al en con por para como que se mi es
der die das ein eine und oder mit von zu im ist wie was fur den dem des
le la les un une et ou du des au aux avec pour comment est que mon
o os as um uma e do da dos das no na com para como meu
il lo gli le uno una di da con per come che mio
w z i na do jak co jest sie
в на и с як що як що це как что это
""".split())

_FOLD = str.maketrans({"ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "ł": "l", "đ": "d", "ı": "i", "þ": "th",
                       "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ـ": ""})
_APOS = "'’ʼ`"
_TOKEN = re.compile(r"\w+(?:[%s]\w+)*" % _APOS)
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def fold(s):
    """Lower case without accents, so typed and stored text compare equal."""
    s = s.lower().translate(_FOLD)
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def tokens_with_pos(text):
    """[(folded word, start offset in text)]. Ukrainian apostrophes stay inside the word
    (пов'язка), elsewhere they split it (l'eau -> l, eau)."""
    out = []
    for m in _TOKEN.finditer(text):
        w = m.group()
        if any(a in w for a in _APOS):
            if _CYRILLIC.search(w):
                out.append((fold(re.sub("[%s]" % _APOS, "", w)), m.start()))
                continue
            off = m.start()
            for part in re.split("[%s]" % _APOS, w):
                if part:
                    out.append((fold(part), off))
                off += len(part) + 1
            continue
        out.append((fold(w), m.start()))
    return out


def tokens(text):
    return [t for t, _ in tokens_with_pos(text)]


def _short_ok(w):
    """Very short words cause false matches ("no", "su"); keep them only in non-Latin scripts or as numbers."""
    return len(w) >= 3 or w.isdigit() or (len(w) == 2 and not w.isascii())


def stem_match(term, word):
    """True when word is term or term with a short ending: burn/burns, verbrennung/verbrennungen."""
    if word == term:
        return True
    return len(term) >= 4 and word.startswith(term) and len(word) - len(term) <= 3


class Lexicon:
    def __init__(self, path):
        self.concepts = {}   # id -> {"poi": str|None, "words": {lang: [phrase, ...]}}
        self.phrases = {}    # tuple(folded tokens) -> [(concept, lang)]
        self.maxlen = 1
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip() or line.startswith("#"):
                    continue
                cols = line.split("|")
                cid, poi, cells = cols[0], cols[1] or None, cols[2:]
                words = {}
                for lang, cell in zip(LANGS, cells):
                    words[lang] = [w.strip() for w in cell.split("/") if w.strip()]
                    for w in words[lang]:
                        tk = tuple(tokens(w))
                        if not tk or (len(tk) == 1 and not _short_ok(tk[0])):
                            continue
                        lst = self.phrases.setdefault(tk, [])
                        if (cid, lang) not in lst:
                            lst.append((cid, lang))
                        self.maxlen = max(self.maxlen, len(tk))
                self.concepts[cid] = {"poi": poi, "words": words}
        self.single = sorted(p[0] for p in self.phrases if len(p) == 1)

    def analyze(self, q, known=()):
        """Split a query into parts: each part is a known concept or a plain word.
        known = extra vocabulary (e.g. words in the guide) that should not be "corrected"."""
        toks = [t for t in tokens(q) if (len(t) > 1 or t.isdigit()) and t not in STOPWORDS] or tokens(q)
        parts = []
        i = 0
        while i < len(toks):
            hit = None
            for n in range(min(self.maxlen, len(toks) - i), 0, -1):
                key = tuple(toks[i:i + n])
                if key in self.phrases:
                    hit = (n, self.phrases[key], None)
                    break
            if hit is None:
                t = toks[i]
                # word endings: "verbrennungen" -> "verbrennung"
                stems = [w for w in self.single if len(w) >= 4 and stem_match(w, t)]
                if stems:
                    w = max(stems, key=len)
                    hit = (1, self.phrases[(w,)], None)
                elif len(t) >= 4 and not t.isdigit() and t not in known:
                    # same first letter: typos rarely hit it, and without this place names
                    # became concepts (curacao -> furacao "storm", china -> cheia "flood")
                    close = difflib.get_close_matches(t, [w for w in self.single if w[0] == t[0]], n=1, cutoff=0.8)
                    if close:
                        hit = (1, self.phrases[(close[0],)], close[0])
            if hit:
                n, refs, corrected = hit
                parts.append({"text": " ".join(toks[i:i + n]), "concept": refs[0][0],
                              "langs": sorted({l for c, l in refs if c == refs[0][0]}),
                              "corrected": corrected})
                i += n
            else:
                parts.append({"text": toks[i], "concept": None, "langs": [], "corrected": None})
                i += 1
        return parts

    @staticmethod
    def query_language(parts):
        votes = {}
        for p in parts:
            for l in p["langs"]:
                votes[l] = votes.get(l, 0) + 1.0 / len(p["langs"])
        return max(votes, key=votes.get) if votes else None

    def translate(self, parts, lang, keep_guesses=False):
        """The query in another language: concepts become that language's main word, other words stay.
        With several words the shortest form is used, so "water zuiveren" becomes "water purify".
        keep_guesses: words that were only typo-corrected stay as typed (Wikipedia has its own
        spelling help and knows names the lexicon doesn't: Spain is not "sprain")."""
        out = []
        for p in parts:
            if p["concept"] and not (keep_guesses and p["corrected"]):
                w = self.concepts[p["concept"]]["words"]
                ws = w.get(lang) or w["en"]
                out.append(ws[0] if len(parts) == 1 else min(ws, key=lambda x: len(tokens(x))))
            else:
                out.append(p["text"])
        return " ".join(out)

    def groups(self, parts):
        """For matching local text: per part, every way of writing it (all languages)."""
        out = []
        for p in parts:
            if p["concept"]:
                alts = {(p["text"],)} if p["corrected"] else set()  # also what was typed
                for ws in self.concepts[p["concept"]]["words"].values():
                    for w in ws:
                        tk = tuple(tokens(w))
                        if tk and (len(tk) > 1 or _short_ok(tk[0])):
                            alts.add(tk)
                out.append(alts)
            else:
                out.append({(p["text"],)})
        return out

    def poi_categories(self, parts):
        return [self.concepts[p["concept"]]["poi"] for p in parts
                if p["concept"] and self.concepts[p["concept"]]["poi"]]


class TextIndex:
    """Small in-memory index for the survival guide and video transcripts (hundreds of documents)."""

    def __init__(self):
        self.docs = {}
        self.vocab = set()

    def add(self, did, title, text, **meta):
        tp = tokens_with_pos(text)
        pos = {}
        for i, (w, _) in enumerate(tp):
            pos.setdefault(w, []).append(i)
        self.docs[did] = {"id": did, "title": title, "text": text, "tok": tp, "pos": pos,
                          "title_tok": set(tokens(title)), "meta": meta}
        self.vocab.update(pos)

    def _expand(self, term):
        if len(term) < 4:
            return [term] if term in self.vocab else []
        return [w for w in self.vocab if stem_match(term, w)]

    def search(self, groups, limit=30):
        if not groups or not self.docs:
            return []
        # resolve each alternative's first word to the real words in the index once
        resolved = []
        for alts in groups:
            r = []
            for tk in alts:
                r.append((tk, self._expand(tk[0])))
            resolved.append(r)
        hits = []
        for d in self.docs.values():
            total, matched, first = 0, 0, None
            for alts in resolved:
                cnt = 0
                for tk, firsts in alts:
                    for w in firsts:
                        for i in d["pos"].get(w, ()):
                            if len(tk) == 1 or all(i + k < len(d["tok"]) and stem_match(tk[k], d["tok"][i + k][0])
                                                   for k in range(1, len(tk))):
                                cnt += 1
                                first = i if first is None else min(first, i)
                    if any(w in d["title_tok"] for w in firsts):
                        cnt += 20
                if cnt:
                    matched += 1
                    total += cnt
            if matched:
                hits.append((matched, total, d, first))
        if not hits:
            return []
        best = max(h[0] for h in hits)
        top = max(h[1] for h in hits if h[0] == best)
        out = []
        for matched, total, d, first in sorted(hits, key=lambda h: (-h[0], -h[1])):
            if matched < best or total < top * 0.15:
                break  # only documents about as relevant as the best one, not every passing mention
            off = d["tok"][first][1] if first is not None else 0
            start = max(0, off - 50)
            if start:
                sp = d["text"].find(" ", start, off)
                start = sp + 1 if sp >= 0 else off
            snip = d["text"][start: off + 110].replace("\n", " ")
            snip = re.sub(r"[#*>|_`]", "", snip).strip()
            out.append(dict(d["meta"], id=d["id"], title=d["title"], score=total, snippet=snip))
        return out[:limit]


VIDEO_EXT = (".mp4", ".webm", ".m4v", ".ogv", ".mkv")


def _vtt_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except OSError:
        return ""
    lines = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln or ln == "WEBVTT" or "-->" in ln or ln.isdigit():
            continue
        lines.append(re.sub(r"<[^>]+>", "", ln))
    return " ".join(lines)


def scan_videos(roots):
    """Videos you copied to data/videos/<subject>/... (e.g. Khan Academy downloads).
    A same-named .vtt/.srt/.txt next to a video (subtitles/transcript) is searched too."""
    out = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _, files in os.walk(root):
            for f in sorted(files):
                if not f.lower().endswith(VIDEO_EXT):
                    continue
                path = os.path.join(dirpath, f)
                rel = os.path.relpath(path, root).replace(os.sep, "/")
                base = os.path.splitext(path)[0]
                text = ""
                for ext in (".vtt", ".srt", ".txt", ".en.vtt", ".nl.vtt", ".es.vtt"):
                    if os.path.exists(base + ext):
                        text = _vtt_text(base + ext)
                        break
                title = re.sub(r"^\d+[\s._-]*", "", os.path.splitext(f)[0])
                title = re.sub(r"[_]+", " ", title).strip() or f
                subject = " / ".join(p.replace("_", " ") for p in rel.split("/")[:-1])
                out.append({"root": root, "rel": rel, "title": title, "subject": subject, "text": text})
    return out


class Finder:
    """Ties the sources together; server.py exposes it as /api/find."""

    def __init__(self, app, lexicon_path, kiwix=None, video_roots=()):
        self.app = app
        self.lex = Lexicon(lexicon_path)
        self.kiwix = kiwix
        self.video_roots = list(video_roots)
        self.guide = TextIndex()
        self.videos = TextIndex()
        self.reload()

    def reload(self):
        self.guide = TextIndex()
        for p in self.app.library.pages.values():
            self.guide.add(p["id"], p["title"], p["text"], section=p["section"])
        self.videos = TextIndex()
        self.video_files = {}
        for n, v in enumerate(scan_videos(self.video_roots)):
            vid = "v%d" % n
            self.video_files[vid] = os.path.join(v["root"], v["rel"])
            self.videos.add(vid, v["title"], " ".join([v["title"], v["subject"], v["text"]]),
                            subject=v["subject"], url="/media/%s" % vid)

    def understand(self, q):
        parts = self.lex.analyze(q, known=self.guide.vocab | self.videos.vocab)
        lang = self.lex.query_language(parts)
        return parts, lang

    def guide_search(self, q, limit=30):
        parts, _ = self.understand(q)
        return self.guide.search(self.lex.groups(parts), limit)

    def books_for(self, parts, lang):
        """Every installed Kiwix book with the query in that book's language;
        books in the language you typed first, then English, then the rest."""
        if not self.kiwix:
            return []
        books = self.kiwix.books()
        order = [lang, "en"]
        rank = lambda b: (order.index(b["lang"]) if b["lang"] in order else 2, b["title"])  # noqa: E731
        out = []
        for b in sorted(books, key=rank):
            ql = b["lang"] if b["lang"] in LANGS else (lang or "en")
            q, alt = self.lex.translate(parts, ql, keep_guesses=True), self.lex.translate(parts, ql)
            out.append(dict(b, query=q, alt=alt if alt != q else None))  # alt: the spelling fix, if nothing is found
        return out

    def find(self, q, lat=None, lon=None):
        parts, lang = self.understand(q)
        groups = self.lex.groups(parts)
        res = {
            "query": q,
            "language": lang,
            "understood": [{"text": p["text"], "concept": p["concept"], "corrected": p["corrected"]}
                           for p in parts],
            "translations": {l: self.lex.translate(parts, l) for l in LANGS}
            if any(p["concept"] for p in parts) else {},
            "guide": self.guide.search(groups, 8),
            "videos": self.videos.search(groups, 8),
            "places": [],
            "books": self.books_for(parts, lang),
        }
        # map: names that match, plus the nearest useful places for words like "water" or "hospital"
        try:
            res["places"] = self.app.search(q, lat, lon)[:8]
            if lat is not None:
                for cat in self.lex.poi_categories(parts)[:2]:
                    for r in self.app.nearest(lat, lon, cat, limit=5):
                        r["kind"] = cat
                        res["places"].append(r)
        except Exception:  # map database missing or damaged: the rest still works
            pass
        return res
