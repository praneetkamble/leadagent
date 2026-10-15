"""Step 2: extract facts. Rule-based; every fact carries the evidence snippet it came from."""
from __future__ import annotations
import re

from . import config

TYPES = {  # keyword -> business type (first match wins, order matters)
    "dental": "clinic", "clinic": "clinic", "doctor": "clinic", "hospital": "clinic",
    "salon": "salon", "makeup": "salon", "spa": "salon",
    "cafe": "cafe", "café": "cafe", "coffee": "cafe",
    "sweets": "bakery", "mithai": "bakery", "bakery": "bakery",
    "restaurant": "restaurant", "kitchen": "restaurant", "dhaba": "restaurant", "food": "restaurant",
}
CITIES = ["Mumbai", "Navi Mumbai", "Thane", "Pune", "Nashik", "Nagpur", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Kolkata", "Ahmedabad"]
PLACEHOLDER = re.compile(r"under construction|coming soon|lorem ipsum|best viewed in internet explorer", re.I)


def _snip(text: str, m: re.Match, pad: int = 40) -> str:
    return re.sub(r"\s+", " ", text[max(0, m.start() - pad): m.end() + pad]).strip()


def _find(pattern: str, text: str, flags=re.I):
    m = re.search(pattern, text, flags)
    return (True, _snip(text, m)) if m else (False, "")


def extract_facts(doc: dict) -> dict:
    text, links = doc["text"], doc["links"]
    low = text.lower()
    F: dict[str, dict] = {}

    def put(key, value, evidence=""):
        F[key] = {"value": value, "evidence": evidence}

    name = doc["title"].split("|")[0].split(" - ")[0].strip() or doc["h1"]
    name = re.sub(r"^welcome to\s+", "", name, flags=re.I)
    put("business_name", re.sub(r"\s+", " ", name).strip(), doc["title"] or doc["h1"])

    btype, ev = "other", ""
    probe = (doc["title"] + " " + doc["h1"] + " " + text[:600]).lower()
    for kw, t in TYPES.items():
        if kw in probe:
            btype, ev = t, kw; break
    put("business_type", btype, f"keyword '{ev}'" if ev else "no keyword matched")

    city = next((c for c in sorted(CITIES, key=len, reverse=True) if c.lower() in low), None)
    put("city", city, city or "")

    m = re.search(r"(\d+)\s+(?:outlets|stores|branches|locations)", text, re.I)
    put("outlet_count", int(m.group(1)) if m else 1, _snip(text, m) if m else "no multi-outlet wording")
    put("is_franchise_or_chain", bool((m and int(m.group(1)) > 3) or re.search(r"franchise", text, re.I)),
        _snip(text, m) if m else "")

    ph = re.search(r"(?:\+?91[\s-]?)?(?:\d{5}[\s-]?\d{5}|\d{2,4}[\s-]\d{3,4}[\s-]\d{3,4})", text)
    put("has_phone", bool(ph), _snip(text, ph) if ph else "")
    em = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    put("has_email", bool(em), em.group(0) if em else "")
    put("has_whatsapp", any("wa.me" in l for l in links) or "whatsapp" in low, "wa.me link / mention" if ("whatsapp" in low or any("wa.me" in l for l in links)) else "")

    put("has_viewport_meta", bool(doc["has_viewport"]), "<meta name=viewport> present" if doc["has_viewport"] else "no viewport meta tag (site is not built for phones)")
    years = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)\s*(?:\(c\)\s*)?(20\d\d|19\d\d)", text + " " + doc.get("raw_footer", ""), re.I)]
    if not years:
        years = [int(y) for y in re.findall(r"^(20\d\d)\s", text, re.M)]
    put("copyright_year", max(years) if years else None, f"© {max(years)}" if years else "no copyright year found")

    ok, ev = _find(PLACEHOLDER.pattern, text)
    put("has_placeholder_content", ok, ev)

    food = btype in ("cafe", "restaurant", "bakery")
    ok, ev = _find(r"order online|add to cart|get the app|order now|online ordering", text)
    put("has_online_ordering", ok, ev)
    ok, ev = _find(r"book(?:ing)? (?:an )?(?:appointment|online|a table|a slot)|appointment form|reserve online", text)
    booking = ok
    if re.search(r"no online booking", text, re.I): booking, ev = False, "'No online booking yet'"
    put("has_online_booking", booking, ev)
    put("needs_ordering_or_booking", (not F["has_online_ordering"]["value"]) if food else (not booking) if btype in ("clinic", "salon") else False,
        "food business without online ordering" if food and not F["has_online_ordering"]["value"] else "service business without online booking" if btype in ("clinic", "salon") and not booking else "")

    has_map = any("google.com/maps" in l for l in links) or bool(re.search(r"google maps|find us on google", low))
    put("has_google_maps_link", has_map, "maps link/mention" if has_map else "no Google Maps link or mention")
    ok, ev = _find(r"rated [\d.]+|google reviews?|patient reviews", text)
    put("mentions_reviews", ok, ev)

    menu_pdf = any(l.lower().endswith(".pdf") for l in links) and "menu" in low
    menu_img = any("menu" in a.lower() for a in doc["img_alts"])
    put("menu_is_pdf_or_image", bool(food and (menu_pdf or menu_img)), "menu is a PDF download" if menu_pdf else "menu is a photo" if menu_img else "")

    b = re.search(r"wix|wordpress|squarespace|shopify", text, re.I)
    put("site_builder_hint", b.group(0).title() if b else None, _snip(text, b) if b else "")
    put("social_links", [l for l in links if re.search(r"instagram|facebook|linkedin|x\.com|twitter", l)], "")
    put("is_https", doc["url"].startswith("https://") if doc["url"] else None, doc["url"])
    put("word_count", len(text.split()), "")
    return F


def facts_digest(F: dict) -> dict:
    return {k: v["value"] for k, v in F.items()}
