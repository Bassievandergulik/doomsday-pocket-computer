"""Tiny stand-in for kiwix-serve (catalog, suggest, full-text search, content), used by the tests.
Responses follow the formats of kiwix-serve 3.x under --urlRootLocation=/kiwix."""
import http.server
import json
import threading
from urllib.parse import parse_qs, urlparse

BOOKS = [("wikipedia_en_all_maxi_2026-01", "Wikipedia", "eng"),
         ("wikipedia_es_all_nopic_2026-01", "Wikipedia (español)", "spa"),
         ("wikimed_nl_2026-01", "WikiMed", "nld")]
ARTICLES = {
    "wikipedia_en_all_maxi_2026-01": {"Burn": "A burn is an injury to skin caused by heat, cold, electricity...",
                                      "Burns_Night": "Burns Night is a celebration of the poet Robert Burns."},
    "wikipedia_es_all_nopic_2026-01": {"Quemadura": "Una quemadura es un tipo de lesión en la piel..."},
    "wikimed_nl_2026-01": {"Brandwond": "Een brandwond is een beschadiging van de huid..."},
}


def catalog():
    entries = "".join(f"""<entry><id>urn:uuid:{n}</id><title>{t}</title><name>{n}</name><flavour>maxi</flavour>
<category>wikipedia</category><language>{l}</language><articleCount>{len(ARTICLES[n])}</articleCount>
<link type="text/html" href="/kiwix/content/{n}"/></entry>""" for n, t, l in BOOKS)
    return f"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"
xmlns:opds="https://specs.opds.io/opds-1.2"><id>x</id><title>All zims</title>{entries}</feed>"""


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _out(self, code, body, ctype="text/html; charset=utf-8", extra=()):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path
        if p == "/kiwix/catalog/v2/entries":
            return self._out(200, catalog(), "application/atom+xml;profile=opds-catalog;kind=acquisition")
        if p == "/kiwix/suggest":
            book = q.get("books.name") or q.get("content")
            term = q.get("term", "").lower()
            res = [{"value": t.replace("_", " "), "label": t.replace("_", " "), "kind": "path", "path": t}
                   for t in ARTICLES.get(book, {}) if t.lower().startswith(term)]
            res.append({"value": term + " ", "label": "containing '%s'..." % term, "kind": "pattern"})
            return self._out(200, json.dumps(res), "application/json; charset=utf-8")
        if p == "/kiwix/search":
            book, pat = q.get("books.name"), q.get("pattern", "").lower()
            if book not in ARTICLES:
                return self._out(400, "No such book")
            hits = [(t, txt) for t, txt in ARTICLES[book].items() if pat.split()[0] in (t + txt).lower()]
            items = "".join(f"<item><title>{t.replace('_', ' ')}</title><link>/kiwix/content/{book}/{t}</link>"
                            f"<description>...{txt[:60]} &lt;b&gt;match&lt;/b&gt;...</description>"
                            f"<book><title>{book}</title></book><wordCount>123</wordCount></item>" for t, txt in hits)
            return self._out(200, f"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"
xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"><channel><title>Search</title>
<opensearch:totalResults>{len(hits)}</opensearch:totalResults>{items}</channel></rss>""", "application/rss+xml")
        if p.startswith("/kiwix/content/"):
            rest = p[len("/kiwix/content/"):].split("/", 1)
            book = rest[0]
            if len(rest) == 1 or not rest[1]:
                first = sorted(ARTICLES[book])[0]
                return self._out(302, "", extra=[("Location", "/kiwix/content/%s/%s" % (book, first))])
            txt = ARTICLES.get(book, {}).get(rest[1])
            if txt is None:
                return self._out(404, "not found")
            return self._out(200, "<html><body><h1>%s</h1><p>%s</p></body></html>" % (rest[1], txt))
        self._out(404, "not found")


def start():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
