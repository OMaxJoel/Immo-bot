"""Collecte : pages publiques, RSS, aperçus web de canaux Telegram publics.
Respecte robots.txt, limite le débit, ne contourne aucune protection."""
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Iterator, List, Optional
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from .util import norm

log = logging.getLogger("sources")
UA = "Mozilla/5.0 (compatible; ImmoBotPersonnel/1.0; usage personnel non commercial)"
HEADERS = {"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9"}
_robots = {}

GONE_MARKERS = ["n est plus disponible", "annonce expiree", "annonce supprimee", "deja loue",
                "annonce introuvable", "page introuvable", "annonce n existe plus"]
PHONE_RE = re.compile(r"(?:\+?225[\s.\-]?)?(0[1579](?:[\s.\-]?\d{2}){4})")
IMG_OK = re.compile(r"\.(jpe?g|png|webp)(\?|$)", re.I)
IMG_BAD = re.compile(r"logo|icon|avatar|sprite|banner|placeholder|flag|emoji", re.I)


@dataclass
class RawAd:
    url: str
    source: str
    text: str
    images: List[str] = field(default_factory=list)
    phones: List[str] = field(default_factory=list)
    published: Optional[str] = None
    gone: bool = False


def allowed(url: str) -> bool:
    p = urlparse(url)
    if p.netloc == "t.me":  # aperçu web public prévu par Telegram
        return True
    base = f"{p.scheme}://{p.netloc}"
    rp = _robots.get(base)
    if rp is None:
        rp = robotparser.RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", headers=HEADERS, timeout=10)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            rp.parse([])
        _robots[base] = rp
    return rp.can_fetch(UA, url)


def fetch(url: str) -> Optional[requests.Response]:
    if not allowed(url):
        log.warning("robots.txt interdit : %s", url)
        return None
    try:
        return requests.get(url, headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        log.warning("échec %s : %s", url, type(e).__name__)
        return None


def _images(soup, base_url) -> List[str]:
    out = []
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        out.append(urljoin(base_url, og["content"]))
    for img in soup.find_all("img"):
        for attr in ("data-src", "data-original", "src"):
            v = img.get(attr)
            if v:
                u = urljoin(base_url, v)
                if u.startswith("http") and IMG_OK.search(u) and not IMG_BAD.search(u):
                    out.append(u)
                break
    seen, res = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            res.append(u)
    return res[:8]


def _clean_phones(raw) -> List[str]:
    out = []
    for p in raw:
        d = re.sub(r"\D", "", p)[-10:]
        if len(d) == 10 and d not in out:
            out.append(d)
    return out[:3]


def page_to_ad(url: str, source: str) -> Optional[RawAd]:
    r = fetch(url)
    if r is None:
        return None
    if r.status_code in (404, 410):
        return RawAd(url, source, "", gone=True)
    if r.status_code >= 400:
        return None
    soup = BeautifulSoup(r.text, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else ""
    phones = [a["href"].replace("tel:", "") for a in soup.select('a[href^="tel:"]')]
    images = _images(soup, url)
    for t in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        t.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())[:5000]
    phones = _clean_phones(phones + PHONE_RE.findall(text))
    gone = any(m in norm(title + " " + text[:600]) for m in GONE_MARKERS)
    return RawAd(url, source, f"{title}\n{text}", images, phones, gone=gone)


def list_links(src: dict) -> List[str]:
    r = fetch(src["url"])
    if r is None or r.status_code >= 400:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    host = urlparse(src["url"]).netloc
    rx = re.compile(src["link_regex"]) if src.get("link_regex") else None
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        u = urljoin(src["url"], a["href"]).split("#")[0]
        p = urlparse(u)
        if p.netloc != host or u == src["url"] or u in seen:
            continue
        if rx:
            ok = bool(rx.search(u))
        else:  # heuristique : lien profond contenant un identifiant
            ok = len(p.path) > 12 and bool(re.search(r"\d", p.path))
        if ok:
            seen.add(u)
            out.append(u)
    return out


def _telegram_channel(src) -> Iterator[RawAd]:
    r = fetch(f"https://t.me/s/{src['channel']}")
    if r is None or r.status_code >= 400:
        return
    soup = BeautifulSoup(r.text, "lxml")
    for m in soup.select(".tgme_widget_message"):
        post = m.get("data-post")
        te = m.select_one(".tgme_widget_message_text")
        if not post or not te:
            continue
        text = te.get_text(" ", strip=True)
        imgs = [u for w in m.select(".tgme_widget_message_photo_wrap")
                for u in re.findall(r"url\('([^']+)'\)", w.get("style", ""))]
        tm = m.select_one("time")
        yield RawAd(f"https://t.me/{post}", src["name"], text, imgs[:8],
                    _clean_phones(PHONE_RE.findall(text)), tm.get("datetime") if tm else None)


def _rss(src) -> Iterator[RawAd]:
    feed = feedparser.parse(src["url"], request_headers=HEADERS)
    for e in feed.entries:
        html = e.get("summary", "") or ""
        soup = BeautifulSoup(html, "lxml")
        text = f"{e.get('title', '')}\n{soup.get_text(' ', strip=True)}"
        imgs = [m["url"] for m in e.get("media_content", []) if "url" in m]
        imgs += [i["src"] for i in soup.find_all("img", src=True)]
        yield RawAd(e.get("link", ""), src["name"], text, imgs[:8],
                    _clean_phones(PHONE_RE.findall(text)), e.get("published"))


def iter_ads(src: dict, cfg: dict, is_seen) -> Iterator[RawAd]:
    """Produit uniquement des annonces pas encore examinées (économie de requêtes)."""
    limit = cfg["schedule"]["max_new_per_source"]
    delay = cfg["schedule"]["fetch_delay_seconds"]
    n = 0
    if src["type"] == "html":
        for url in list_links(src):
            if n >= limit:
                break
            if is_seen(url):
                continue
            time.sleep(delay)
            ad = page_to_ad(url, src["name"])
            if ad:
                n += 1
                yield ad
    else:
        gen = _telegram_channel(src) if src["type"] == "telegram_channel" else _rss(src)
        for ad in gen:
            if n >= limit:
                break
            if ad.url and not is_seen(ad.url):
                n += 1
                yield ad
