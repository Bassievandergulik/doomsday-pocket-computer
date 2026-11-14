"""Multilingual search, Kiwix and video tests:  python3 -m unittest discover tests"""
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fake_kiwix  # noqa: E402
import search  # noqa: E402
from kiwix import Kiwix  # noqa: E402
from library import Library  # noqa: E402

LEX = os.path.join(ROOT, "app", "lexicon.txt")


class LexiconTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lex = search.Lexicon(LEX)

    def test_every_line_has_all_languages(self):
        with open(LEX, encoding="utf-8") as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    cols = line.rstrip("\n").split("|")
                    self.assertEqual(len(cols), 2 + len(search.LANGS), line[:40])
                    self.assertTrue(all(c.strip() for c in cols[2:]), "empty language in " + cols[0])

    def test_fold(self):
        self.assertEqual(search.fold("Ärztin Straße BRÛLURE"), "arztin strasse brulure")
        self.assertEqual(search.fold("ребёнок"), search.fold("ребенок"))
        self.assertEqual(search.tokens("пов'язка l'eau"), ["повязка", "l", "eau"])

    def test_same_concept_in_every_language(self):
        for q in ["burn", "brandwond", "quemadura", "Verbrennung", "brulure", "queimadura", "ustione",
                  "oparzenie", "опік", "ожог", "حروق", "yanık"]:
            parts = self.lex.analyze(q)
            self.assertEqual(parts[0]["concept"], "burn", q)

    def test_translation_and_language(self):
        parts = self.lex.analyze("eerste hulp bij brandwonden")
        self.assertEqual(self.lex.query_language(parts), "nl")
        self.assertEqual(self.lex.translate(parts, "en"), "first aid burn")
        self.assertEqual(self.lex.translate(parts, "es"), "primeros auxilios quemadura")

    def test_typos_and_endings(self):
        p = self.lex.analyze("hypotermia")[0]
        self.assertEqual((p["concept"], p["corrected"]), ("hypothermia", "hypothermia"))
        self.assertEqual(self.lex.analyze("Verbrennungen")[0]["concept"], "burn")
        self.assertIsNone(self.lex.analyze("Utrecht")[0]["concept"])
        # Spanish article "las" must not turn into the Polish word for forest
        self.assertEqual([p["text"] for p in self.lex.analyze("las setas")], ["setas"])

    def test_place_names_are_not_corrected_into_concepts(self):
        self.assertIsNone(self.lex.analyze("curacao")[0]["concept"])  # was furacão = storm
        # a possible typo is still fixed for the guide, but Wikipedia gets what was typed
        self.assertEqual(self.lex.analyze("spain")[0]["concept"], "sprain")
        for q in ("spain", "china", "chile", "curacao"):
            self.assertEqual(self.lex.translate(self.lex.analyze(q), "nl", keep_guesses=True), q)

    def test_poi(self):
        self.assertEqual(self.lex.poi_categories(self.lex.analyze("ziekenhuis")), ["hospital"])
        self.assertEqual(self.lex.poi_categories(self.lex.analyze("agua potable")), ["water"])


class GuideSearchTest(unittest.TestCase):
    def test_any_language_finds_the_page(self):
        lex = search.Lexicon(LEX)
        lib = Library(os.path.join(ROOT, "library"))
        idx = search.TextIndex()
        for p in lib.pages.values():
            idx.add(p["id"], p["title"], p["text"])
        cases = {"quemadura": "firstaid/burns", "brandwond": "firstaid/burns", "ожог": "firstaid/burns",
                 "reanimatie": "firstaid/cpr", "kalp masajı": "firstaid/cpr", "hypotermia": "firstaid/hypothermia",
                 "water zuiveren": "water/purifying", "Blutung": "firstaid/bleeding", "tourniquet": "firstaid/bleeding",
                 "atragantamiento": "firstaid/choking"}
        for q, want in cases.items():
            res = idx.search(lex.groups(lex.analyze(q, known=idx.vocab)), 3)
            self.assertTrue(res, q)
            self.assertEqual(res[0]["id"], want, q)


class FakeApp:
    """Just enough of server.App for the search endpoints."""

    def __init__(self, kiwix_url, video_dir):
        self.library = Library(os.path.join(ROOT, "library"))
        self.kiwix = Kiwix(kiwix_url)
        self.finder = search.Finder(self, LEX, self.kiwix, [video_dir],
                                    symptoms_path=os.path.join(ROOT, "app", "symptoms.txt"))

        class HS:
            started = None
        self.hotspot = HS()

    def position(self):
        return (52.09, 5.12)

    def search(self, q, lat=None, lon=None):
        return [{"name": "Utrecht", "kind": "city", "lat": 52.09, "lon": 5.12, "dist_m": 0, "bearing": 0}] \
            if "utrecht" in q.lower() else []

    def nearest(self, lat, lon, cat=None, limit=10):
        return [{"cat": cat, "name": "St. Antonius", "lat": 52.1, "lon": 5.1, "dist_m": 1500, "bearing": 300}]


class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.kiwix_srv = fake_kiwix.start()
        cls.tmp = tempfile.mkdtemp()
        vdir = os.path.join(cls.tmp, "videos", "Biology")
        os.makedirs(vdir)
        cls.video = bytes(range(256)) * 400
        with open(os.path.join(vdir, "03_Skin_and_burns.mp4"), "wb") as f:
            f.write(cls.video)
        with open(os.path.join(vdir, "03_Skin_and_burns.vtt"), "w") as f:
            f.write("WEBVTT\n\n00:00.000 --> 00:04.000\nThe epidermis protects against dehydration.\n")
        app = FakeApp("http://127.0.0.1:%d/kiwix" % cls.kiwix_srv.server_port, os.path.join(cls.tmp, "videos"))
        server.Handler.app = app
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_port

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.kiwix_srv.shutdown()

    def get(self, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r, body

    def test_find_everything(self):
        r, body = self.get("/api/find?q=" + quote("brandwond"))
        d = json.loads(body)
        self.assertEqual(d["language"], "nl")
        self.assertEqual(d["guide"][0]["id"], "firstaid/burns")
        self.assertEqual(d["videos"][0]["title"], "Skin and burns")
        # Dutch book first, each book gets the query in its own language
        self.assertEqual([(b["lang"], b["query"]) for b in d["books"]],
                         [("nl", "brandwond"), ("en", "burn"), ("es", "quemadura")])
        r, body = self.get("/api/find/wiki?book=wikipedia_en_all_maxi_2026-01&q=burn")
        w = json.loads(body)
        self.assertEqual(w["results"][0]["title"], "Burn")
        self.assertTrue(w["results"][0]["url"].startswith("/kiwix/content/wikipedia_en_all_maxi_2026-01/"))
        self.assertIn("Burns Night", [x["title"] for x in w["results"]])
        self.assertNotIn("<b>", json.dumps(w))
        # kiwix-serve 3.8: books are addressed by their file name, numbers carry thousands separators
        self.assertIn("wikipedia_en_all_maxi_2026-01", [b.get("name") for b in d["books"]])
        w = json.loads(self.get("/api/find/wiki?book=wikipedia_en_all_maxi_2026-01&q=skin")[1])
        self.assertEqual([x["title"] for x in w["results"]], ["Burn"])  # full-text only: no title starts with "skin"
        # the exact article comes first, also when typed without the ç (a redirect in the ZIM)
        w = json.loads(self.get("/api/find/wiki?book=wikipedia_en_all_maxi_2026-01&q=curacao")[1])
        self.assertEqual(w["results"][0]["title"], "Curaçao")
        self.assertTrue(w["results"][0]["title_match"])
        self.assertEqual(self.get(w["results"][0]["url"])[0].status, 200)

    def test_symptoms_in_search(self):
        d = json.loads(self.get("/api/find?q=" + quote("koorts hoofdpijn stijve nek"))[1])
        self.assertEqual(d["health"]["conditions"][0]["id"], "meningitis")
        self.assertTrue(d["health"]["danger"])
        self.assertIsNone(json.loads(self.get("/api/find?q=water")[1])["health"])

    def test_map_concepts(self):
        d = json.loads(self.get("/api/find?q=" + quote("hospital"))[1])
        self.assertEqual(d["places"][0]["name"], "St. Antonius")
        d = json.loads(self.get("/api/find?q=Utrecht")[1])
        self.assertEqual(d["places"][0]["name"], "Utrecht")

    def test_kiwix_proxy_keeps_redirects(self):
        r, _ = self.get("/kiwix/content/wikipedia_es_all_nopic_2026-01")
        self.assertEqual(r.status, 302)
        self.assertEqual(r.getheader("Location"), "/kiwix/content/wikipedia_es_all_nopic_2026-01/Quemadura")
        r, body = self.get("/kiwix/content/wikipedia_es_all_nopic_2026-01/Quemadura")
        self.assertEqual(r.status, 200)
        self.assertIn("quemadura", body.decode().lower())

    def test_video_ranges(self):
        r, body = self.get("/media/v0")
        self.assertEqual((r.status, body), (200, self.video))
        r, body = self.get("/media/v0", {"Range": "bytes=1000-1999"})
        self.assertEqual(r.status, 206)
        self.assertEqual(body, self.video[1000:2000])
        self.assertEqual(r.getheader("Content-Range"), "bytes 1000-1999/%d" % len(self.video))
        r, body = self.get("/media/v0", {"Range": "bytes=-100"})
        self.assertEqual(body, self.video[-100:])
        self.assertEqual(self.get("/media/v9")[0].status, 404)

    def test_without_kiwix(self):
        k = Kiwix("http://127.0.0.1:9/kiwix")
        self.assertEqual(k.books(), [])
        self.assertFalse(k.available())


if __name__ == "__main__":
    unittest.main()
