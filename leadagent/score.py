"""Step 3: transparent fit-scoring rubric. Pure function of the extracted facts: no LLM involved,
so every point can be traced to a fact and its evidence."""
from __future__ import annotations
import json

from . import config

# (id, max points, description, service the signal maps to)
RUBRIC = [
    ("target_segment", 15, "Business is in a segment I serve (cafe, restaurant, salon, clinic, bakery)", None),
    ("local_single_site", 10, "Local / single-location business (not a chain or franchise)", None),
    ("no_mobile_layout", 15, "Website has no mobile viewport tag", "website"),
    ("outdated_site", 10, "Copyright year is 4+ years old", "website"),
    ("placeholder_content", 10, "Site shows placeholder / under-construction content", "website"),
    ("no_ordering_or_booking", 15, "No online ordering (food) / online booking (clinic, salon)", "qr_ordering"),
    ("no_maps_presence", 10, "No Google Maps link or mention on the site", "gbp"),
    ("reachable", 10, "A phone, email or WhatsApp contact is published (I can reach them)", None),
    ("menu_not_searchable", 5, "Menu is only a PDF or a photo", "website"),
]
assert sum(r[1] for r in RUBRIC) == 100
CHAIN_CAP = 20


def _v(F, k): return F[k]["value"]


def score_fit(F: dict, year: int | None = None) -> dict:
    year = year or config.CURRENT_YEAR
    cy = _v(F, "copyright_year")
    target = _v(F, "business_type") in json.loads(config.PROFILE.read_text())["target_types"]
    earned = {
        "target_segment": target,
        "local_single_site": not _v(F, "is_franchise_or_chain"),
        "no_mobile_layout": not _v(F, "has_viewport_meta"),
        "outdated_site": bool(cy and year - cy >= 4),
        "placeholder_content": _v(F, "has_placeholder_content"),
        "no_ordering_or_booking": _v(F, "needs_ordering_or_booking"),
        "no_maps_presence": not _v(F, "has_google_maps_link"),
        "reachable": _v(F, "has_phone") or _v(F, "has_email") or _v(F, "has_whatsapp"),
        "menu_not_searchable": _v(F, "menu_is_pdf_or_image"),
    }
    evid = {
        "target_segment": f"type={_v(F,'business_type')}",
        "local_single_site": F["is_franchise_or_chain"]["evidence"] or f"outlets={_v(F,'outlet_count')}",
        "no_mobile_layout": F["has_viewport_meta"]["evidence"],
        "outdated_site": F["copyright_year"]["evidence"],
        "placeholder_content": F["has_placeholder_content"]["evidence"],
        "no_ordering_or_booking": F["needs_ordering_or_booking"]["evidence"],
        "no_maps_presence": F["has_google_maps_link"]["evidence"],
        "reachable": F["has_phone"]["evidence"] or F["has_email"]["evidence"] or F["has_whatsapp"]["evidence"],
        "menu_not_searchable": F["menu_is_pdf_or_image"]["evidence"],
    }
    items, total = [], 0
    for rid, pts, desc, svc in RUBRIC:
        hit = bool(earned[rid])
        got = pts if hit else 0
        total += got
        items.append({"id": rid, "description": desc, "max": pts, "earned": got, "hit": hit, "evidence": evid[rid], "service": svc})
    capped = False
    if _v(F, "is_franchise_or_chain") and total > CHAIN_CAP:
        total, capped = CHAIN_CAP, True
    tier = "strong" if total >= 65 else "moderate" if total >= config.MIN_FIT_TO_DRAFT else "weak"
    return {"score": total, "tier": tier, "capped_for_chain": capped, "items": items, "rubric_max": 100}
