"""Load a business website: saved fixture, pasted HTML/text, or (opt-in) a public URL."""
from __future__ import annotations
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from . import config


class _P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.links, self.imgs, self.metas = [], [], [], {}
        self.title = self.h1 = ""
        self._in = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"): self._skip += 1
        if tag == "title": self._in = "title"
        if tag == "h1" and not self.h1: self._in = "h1"
        if tag == "a" and a.get("href"): self.links.append(a["href"])
        if tag == "img": self.imgs.append(a.get("alt", ""))
        if tag == "meta" and a.get("name"): self.metas[a["name"].lower()] = a.get("content", "")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip: self._skip -= 1
        if tag in ("title", "h1"): self._in = None
        if tag in ("p", "li", "h1", "h2", "h3", "div", "footer", "br"): self.text.append("\n")

    def handle_data(self, d):
        if self._skip: return
        if self._in == "title": self.title += d
        if self._in == "h1": self.h1 += d
        self.text.append(d)


def parse_html(html: str) -> dict:
    p = _P(); p.feed(html)
    text = re.sub(r"[ \t]+", " ", "".join(p.text))
    text = "\n".join(l.strip() for l in text.splitlines() if l.strip())
    m = re.search(r"<!--\s*url:\s*(\S+)\s*-->", html)
    return {"title": p.title.strip(), "h1": p.h1.strip(), "text": text, "links": p.links, "img_alts": p.imgs,
            "has_viewport": "viewport" in p.metas, "url": m.group(1) if m else "", "raw_len": len(html)}


def _public_host(host: str) -> bool:
    try:
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        return True
    except OSError:
        return False


def fetch_url(url: str) -> str:
    u = urlparse(url)
    if not config.ALLOW_FETCH:
        raise PermissionError("Live URL fetching is disabled. Use a saved fixture, paste the page text, "
                              "or set LEADAGENT_ALLOW_FETCH=1 for public pages you are allowed to read.")
    if u.scheme not in ("http", "https") or not u.hostname or not _public_host(u.hostname):
        raise PermissionError("Only public http(s) hosts are allowed (private/loopback addresses are blocked).")
    req = Request(url, headers={"User-Agent": "LeadAgent/0.1 (demo; respects human approval)"})
    with urlopen(req, timeout=10) as r:                      # noqa: S310 (scheme checked above)
        return r.read(1_000_000).decode("utf-8", errors="replace")


def load_source(source: str) -> tuple[str, str]:
    """Return (html_or_text, label). `source` may be a fixture name, an http(s) URL or raw content."""
    s = source.strip()
    if re.fullmatch(r"[\w\-]+(\.html)?", s):
        p = config.FIXTURES / (s if s.endswith(".html") else s + ".html")
        if p.exists():
            return p.read_text(encoding="utf-8"), f"fixture:{p.stem}"
        raise FileNotFoundError(f"No fixture named {s!r}")
    if s.startswith(("http://", "https://")):
        return fetch_url(s), s
    if len(s) < 40:
        raise ValueError("Provide a fixture name, a URL, or at least a few lines of page text/HTML.")
    return s, "pasted"
