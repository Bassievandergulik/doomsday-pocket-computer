#!/usr/bin/env python3
"""Downloads one small photo per plant/mushroom for the guide's identification pages
into app/static/photos/ (run once on a computer with internet; about 3 MB in total):

    python3 tools/get_plant_photos.py

Photos come from Wikipedia/Wikimedia Commons (the article's main image). Their authors and
licences are written to library/plants/photo-credits.md, which the licences require."""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "app", "static", "photos")
CREDITS = os.path.join(ROOT, "library", "plants", "photo-credits.md")
UA = "doomsday-pocket-computer/1.0 (offline survival guide; build script)"
WIDTH = 480

# file name (without .jpg) -> English Wikipedia article whose main image is used
PLANTS = {
    "stinging-nettle": "Urtica_dioica", "dandelion": "Taraxacum_officinale", "plantain": "Plantago_major",
    "ribwort-plantain": "Plantago_lanceolata", "wild-garlic": "Allium_ursinum", "blackberry": "Rubus_fruticosus",
    "bilberry": "Vaccinium_myrtillus", "elder": "Sambucus_nigra", "sweet-chestnut": "Castanea_sativa",
    "horse-chestnut": "Aesculus_hippocastanum", "hazel": "Corylus_avellana", "oak": "Quercus_robur",
    "beech": "Fagus_sylvatica", "cattail": "Typha_latifolia", "chickweed": "Stellaria_media",
    "wood-sorrel": "Oxalis_acetosella", "dog-rose": "Rosa_canina", "lime-tree": "Tilia_cordata",
    "scots-pine": "Pinus_sylvestris", "white-clover": "Trifolium_repens", "purslane": "Portulaca_oleracea",
    "yarrow": "Achillea_millefolium", "willow": "Salix_alba", "sphagnum": "Sphagnum", "birch": "Betula_pendula",
    "sea-grape": "Coccoloba_uvifera", "prickly-pear": "Opuntia_ficus-indica", "coconut": "Coconut",
    "hemlock": "Conium_maculatum", "hemlock-water-dropwort": "Oenanthe_crocata", "giant-hogweed": "Heracleum_mantegazzianum",
    "foxglove": "Digitalis_purpurea", "lily-of-the-valley": "Convallaria_majalis", "autumn-crocus": "Colchicum_autumnale",
    "deadly-nightshade": "Atropa_belladonna", "yew": "Taxus_baccata", "monkshood": "Aconitum_napellus",
    "lords-and-ladies": "Arum_maculatum", "manchineel": "Hippomane_mancinella", "castor-bean": "Ricinus_communis",
    "oleander": "Nerium_oleander", "rosary-pea": "Abrus_precatorius",
    "death-cap": "Amanita_phalloides", "destroying-angel": "Amanita_virosa", "fly-agaric": "Amanita_muscaria",
    "chanterelle": "Chanterelle", "giant-puffball": "Calvatia_gigantea", "porcini": "Boletus_edulis",
}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def main():
    os.makedirs(OUT, exist_ok=True)
    credits = []
    for slug, title in PLANTS.items():
        dest = os.path.join(OUT, slug + ".jpg")
        try:
            s = json.loads(get("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title)))
            src = (s.get("thumbnail") or {}).get("source") or (s.get("originalimage") or {}).get("source")
            if not src:
                print("  no image:", title)
                continue
            # thumbnails look like .../thumb/a/ab/Name.jpg/320px-Name.jpg: ask for our width
            thumb = re.sub(r"/(\d+)px-", "/%dpx-" % WIDTH, src) if "/thumb/" in src else src
            fname = urllib.parse.unquote(src.split("/thumb/")[-1].split("/")[2] if "/thumb/" in src else src.rsplit("/", 1)[-1])
            if not os.path.exists(dest):
                data = get(thumb)
                with open(dest, "wb") as f:
                    f.write(data)
            meta = json.loads(get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
                "action": "query", "format": "json", "prop": "imageinfo", "iiprop": "extmetadata",
                "titles": "File:" + fname})))
            info = next(iter(meta["query"]["pages"].values())).get("imageinfo", [{}])[0].get("extmetadata", {})
            artist = strip_html(info.get("Artist", {}).get("value")) or "unknown"
            lic = strip_html(info.get("LicenseShortName", {}).get("value")) or "see Wikimedia Commons"
            credits.append("| %s | %s | %s | %s |" % (slug, fname.replace("|", "/"), artist.replace("|", "/"), lic))
            print("  ok", slug)
            time.sleep(0.5)  # be polite to Wikimedia
        except Exception as e:  # keep going: a missing photo just isn't shown
            print("  failed:", slug, e, file=sys.stderr)
    with open(CREDITS, "w", encoding="utf-8") as f:
        f.write("# Photo credits\n\nPhotos on the plant and mushroom pages come from Wikimedia Commons.\n\n"
                "| Photo | File | Author | Licence |\n|---|---|---|---|\n" + "\n".join(credits) + "\n")
    print("Done: %d photos in %s" % (len(credits), OUT))


if __name__ == "__main__":
    main()
