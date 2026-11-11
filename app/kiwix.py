"""Talks to kiwix-serve, which serves the offline Wikipedia / WikiMed / Khan Academy ZIM files.

kiwix-serve runs as its own service on 127.0.0.1:8081 under /kiwix (see deploy/kiwix.sh);
server.py passes /kiwix/... through so articles open on the screen and over the hotspot.
"""
import html
import http.client
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote, unquote, urlencode, urlparse

ATOM = "{http://www.w3.org/2005/Atom}"
# ZIM files use 3-letter language codes
LANG3 = {"eng": "en", "nld": "nl", "spa": "es", "deu": "de", "ger": "de", "fra": "fr", "fre": "fr", "por": "pt",
         "ita": "it", "pol": "pl", "ukr": "uk", "rus": "ru", "ara": "ar", "tur": "tr"}


def _int(s):
    """kiwix-serve 3.8 writes numbers with thousands separators ("3,574")."""
    digits = re.sub(r"\D", "", s or "")
    return int(digits) if digits else 0


def _strip(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


class Kiwix:
    def __init__(self, url="http://127.0.0.1:8081/kiwix", timeout=20):
        u = urlparse(url)
        self.host, self.port = u.hostname, u.port or 80
        self.root = u.path.rstrip("/")
        self.timeout = timeout
        self._books, self._books_t = [], 0
        self._lock = threading.Lock()

    def _get(self, path, timeout=None):
        c = http.client.HTTPConnection(self.host, self.port, timeout=timeout or self.timeout)
        try:
            c.request("GET", self.root + path)
            r = c.getresponse()
            return r.status, r.read()
        finally:
            c.close()

    def books(self, max_age=60):
        """Installed ZIM files: [{name, title, lang, category, url}], cached for a minute."""
        with self._lock:
            if time.time() - self._books_t < max_age:
                return self._books
            try:
                status, body = self._get("/catalog/v2/entries?count=-1", timeout=3)
                out = []
                if status == 200:
                    for e in ET.fromstring(body).iter(ATOM + "entry"):
                        # kiwix-serve 3.8 addresses books by the name in their text/html link
                        # (wikipedia_nl_all_nopic_2026-04), not by the catalog <name> (wikipedia_nl_all)
                        name = ""
                        for link in e.iter(ATOM + "link"):
                            href = link.get("href") or ""
                            if link.get("type") == "text/html" and "/content/" in href:
                                name = unquote(href.split("/content/", 1)[1].strip("/").split("/")[0])
                        name = name or e.findtext(ATOM + "name") or ""
                        if not name:
                            continue
                        lang3 = (e.findtext(ATOM + "language") or "").split(",")[0].strip()
                        out.append({"name": name, "title": e.findtext(ATOM + "title") or name,
                                    "lang": LANG3.get(lang3, lang3[:2]), "category": e.findtext(ATOM + "category") or "",
                                    "articles": _int(e.findtext(ATOM + "articleCount")),
                                    "url": "%s/content/%s/" % (self.root, quote(name))})
                self._books = out
            except (OSError, ET.ParseError, ValueError):
                self._books = []
            self._books_t = time.time()
            return self._books

    def available(self):
        return bool(self.books())

    def suggest(self, book, term, count=6):
        """Fast title matches."""
        q = urlencode({"books.name": book, "term": term, "count": count})
        status, body = self._get("/suggest?" + q, timeout=8)
        if status != 200:
            # kiwix-serve before 3.3 only knows content=
            status, body = self._get("/suggest?" + urlencode({"content": book, "term": term, "count": count}), timeout=8)
        if status != 200:
            return []
        out = []
        for s in json.loads(body.decode("utf-8", "replace")):
            if s.get("kind") == "pattern" or not s.get("path"):
                continue
            out.append({"title": _strip(s.get("value") or s.get("label")),
                        "url": "%s/content/%s/%s" % (self.root, quote(book), quote(s["path"]))})
        return out

    def search(self, book, pattern, count=10, start=0):
        """Full-text search (needs a ZIM with a full-text index, which all official Wikipedia ZIMs have)."""
        q = urlencode({"books.name": book, "pattern": pattern, "format": "xml", "pageLength": count, "start": start})
        status, body = self._get("/search?" + q)
        if status != 200:
            return {"total": 0, "results": [], "error": "no full-text index" if status in (400, 404) else "error %d" % status}
        root = ET.fromstring(body)
        ch = root.find("channel")
        total = 0
        if ch is not None:
            for el in ch:
                if el.tag.endswith("totalResults"):
                    total = _int(el.text)
        res = []
        for it in root.iter("item"):
            link = it.findtext("link") or ""
            if not link.startswith("/"):
                link = "%s/%s" % (self.root, link)
            res.append({"title": _strip(it.findtext("title")), "url": link,
                        "snippet": _strip(it.findtext("description"))[:240],
                        "words": _int(it.findtext("wordCount"))})
        return {"total": total or len(res), "results": res}

    def find(self, book, query, count=8):
        """Title matches first (they are usually the article you want), then full-text hits."""
        out, seen, err = [], set(), None
        try:
            for s in self.suggest(book, query, 4):
                seen.add(s["url"])
                out.append(dict(s, snippet="", title_match=True))
        except (OSError, ValueError):
            pass
        try:
            r = self.search(book, query, count)
            err = r.get("error")
            for s in r["results"]:
                if s["url"] not in seen:
                    out.append(s)
        except (OSError, ET.ParseError, ValueError) as e:
            err = str(e)
        return {"book": book, "query": query, "results": out[:count + 4], "error": None if out else err}

    def proxy(self, handler, path):
        """Pass a browser request through to kiwix-serve unchanged (redirects included,
        so relative links inside articles keep working)."""
        c = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            try:
                c.request("GET", path, headers={"Accept-Encoding": handler.headers.get("Accept-Encoding", "")})
            except OSError:
                return handler._send(503, "The offline library (kiwix-serve) is not running.", "text/plain; charset=utf-8")
            r = c.getresponse()
            handler.send_response(r.status)
            length = r.getheader("Content-Length")
            for h in ("Content-Type", "Content-Encoding", "Location", "Cache-Control", "ETag", "Last-Modified"):
                v = r.getheader(h)
                if v:
                    handler.send_header(h, v)
            if length is not None:
                handler.send_header("Content-Length", length)
            else:
                handler.send_header("Connection", "close")
                handler.close_connection = True
            handler.end_headers()
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                try:
                    handler.wfile.write(chunk)
                except ConnectionError:
                    handler.close_connection = True
                    return
        finally:
            c.close()
