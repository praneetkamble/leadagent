"""Step 4: draft the pitch (template by default, LLM optional) + grounding check."""
from __future__ import annotations
import json
import re

from . import config, llm

OBS = {  # rubric id -> (observation sentence builder, service key)
    "no_mobile_layout": lambda F: "the site doesn't seem to be set up for phones (no mobile layout)",
    "outdated_site": lambda F: f"the site footer still says {F['copyright_year']['value']}",
    "placeholder_content": lambda F: "the site still shows under-construction placeholder content",
    "no_ordering_or_booking": lambda F: ("I couldn't find a way to order online" if F["business_type"]["value"] in ("cafe", "restaurant", "bakery")
                                         else "I couldn't find online booking"),
    "no_maps_presence": lambda F: "I couldn't find a Google Maps link on the site",
    "menu_not_searchable": lambda F: "the menu is only a PDF/photo, which is hard to read on a phone",
}
PRIORITY = ["placeholder_content", "no_mobile_layout", "no_ordering_or_booking", "outdated_site", "no_maps_presence", "menu_not_searchable"]


def profile() -> dict:
    return json.loads(config.PROFILE.read_text())


def template_pitch(F: dict, fit: dict) -> dict:
    p = profile()
    hit = {i["id"]: i for i in fit["items"] if i["hit"]}
    picks = [k for k in PRIORITY if k in hit][:2]
    name = F["business_name"]["value"]
    city = F["city"]["value"]
    services = []
    for k in picks:
        svc = hit[k]["service"]
        if svc and svc not in services: services.append(svc)
    if "no_ordering_or_booking" in hit and F["business_type"]["value"] in ("clinic", "salon"):
        services = [s for s in services if s != "qr_ordering"] or ["website"]
    offer = " and ".join(p["services"][s] for s in services) or p["services"]["website"]
    obs = " and ".join(OBS[k](F) for k in picks) or "there may be room to improve it"
    subject = f"Quick idea for {name}"
    body = (f"Hi {name} team,\n\n"
            f"I'm {p['seller_name']}, a {p['seller_role']}. I had a look at your website{(' in ' + city) if city else ''} and noticed that {obs}.\n\n"
            f"I can help with {offer}. Here is my portfolio: {p['portfolio_url']}\n\n"
            f"If it's useful, I'm happy to send a one-page sample of what this could look like. No obligation. "
            f"Would you like me to?\n\nThanks,\n{p['seller_name']}")
    return {"subject": subject, "body": body}


def llm_pitch(F: dict, fit: dict, client=None) -> dict:
    p = profile()
    facts = {k: v["value"] for k, v in F.items() if k in ("business_name", "business_type", "city", "copyright_year", "has_viewport_meta", "has_online_ordering", "has_online_booking", "has_google_maps_link", "has_placeholder_content")}
    gaps = [i["description"] for i in fit["items"] if i["hit"] and i["service"]]
    sys = ("You write short, honest, polite cold emails for a freelance web developer to a local business owner. "
           "Use ONLY the facts provided. Do not invent numbers, clients, prices, results or urgency. Max 110 words. "
           "Return JSON: {\"subject\": str, \"body\": str}.")
    user = json.dumps({"seller": p, "business_facts": facts, "observed_gaps": gaps})
    out = llm.chat_json(sys, user, client)
    if not isinstance(out.get("subject"), str) or not isinstance(out.get("body"), str):
        raise llm.LLMError("missing subject/body")
    return {"subject": out["subject"], "body": out["body"]}


def grounding_check(draft: dict, F: dict, site_text: str) -> dict:
    """Every number and every URL in the draft must come from the site text, the extracted facts or the seller profile."""
    p = json.dumps(profile())
    allowed = site_text + " " + p + " " + json.dumps({k: v["value"] for k, v in F.items()})
    problems = []
    for num in set(re.findall(r"\d[\d,.]*", draft["subject"] + " " + draft["body"])):
        if num.strip(".,") and num.strip(".,") not in allowed:
            problems.append(f"number '{num}' not found in site text or profile")
    for url in set(re.findall(r"https?://[^\s)]+", draft["body"])):
        if url.rstrip(".,") not in allowed:
            problems.append(f"URL '{url}' not in profile")
    if re.search(r"guarantee|100%|limited time|only today|\bfree of cost\b", draft["body"], re.I):
        problems.append("contains a guarantee/urgency claim")
    if F["business_name"]["value"].lower() not in (draft["subject"] + draft["body"]).lower():
        problems.append("does not mention the business name")
    return {"passed": not problems, "problems": problems}
