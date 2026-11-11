import hashlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from . import sources
from .analyze import Analysis, QuotaExceeded
from .tg import build_card
from .util import norm

log = logging.getLogger("pipeline")


@dataclass
class Ctx:
    cfg: dict
    db: Any
    settings: Any
    tg: Any
    gem: Any


KEYWORDS = ["louer", "location", "loyer", "f2", "2 pieces", "chambre", "appartement", "appart", "salon"]


def prefilter(ctx, ad) -> bool:
    """Filtre gratuit avant d'appeler Gemini : quartier cité + vocabulaire de location."""
    t = norm(ad.text)
    return ctx.settings.zone_of(ad.text) is not None and any(k in t for k in KEYWORDS)


def _age_days(a: Analysis, ad):
    for raw in (ad.published, a.published_date):
        if not raw:
            continue
        try:
            d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - d).days
        except ValueError:
            continue
    return None


def evaluate(a: Analysis, ad, settings, scfg):
    """Décision finale en Python (déterministe) : Gemini extrait, le code tranche.
    Retourne (ok, raison, zone, flags, relevance)."""
    if not a.is_rental:
        return False, "ce n'est pas une location", None, [], 0
    if not a.is_residential:
        return False, "ce n'est pas un logement résidentiel", None, [], 0
    if a.is_short_term:
        return False, "location courte durée (tarif non mensuel)", None, [], 0
    if a.bedrooms is not None and a.bedrooms != 1:
        return False, f"{a.bedrooms} chambre(s) : ce n'est pas un 2 pièces", None, [], 0
    zone = settings.zone_of(ad.text) or settings.zone_of(a.zone_text or "")
    if not zone:
        return False, "quartier hors zones recherchées", None, [], 0
    budget = settings.budget
    if a.price_fcfa_month and a.price_fcfa_month > budget:
        return False, f"hors budget ({a.price_fcfa_month} > {budget})", None, [], 0

    flags, rel = [], a.relevance
    if not a.price_fcfa_month:
        flags.append("Prix non précisé dans l'annonce"); rel -= 15
    elif a.price_fcfa_month < 0.35 * budget:
        flags.append("Prix anormalement bas : méfiance (arnaque possible)"); rel -= 15
    if a.bedrooms is None:
        flags.append("Nombre de chambres non confirmé"); rel -= 10
    if a.furnished and scfg.get("prefer_unfurnished"):
        flags.append("Logement meublé (vous préférez le non-meublé)"); rel -= 8
    age = _age_days(a, ad)
    if age is not None and age > scfg.get("max_age_days", 14):
        flags.append(f"Annonce ancienne (~{age} jours)"); rel -= 15
    if a.poster_type == "demarcheur":
        flags.append("Publiée par un démarcheur / courtier")
    flags += [f"Suspect : {s}" for s in a.suspicious] + [f"Contradiction : {c}" for c in a.contradictions]
    rel = max(0, min(100, rel))
    if rel < scfg.get("min_relevance", 60):
        return False, f"pertinence trop faible ({rel} %)", zone, flags, rel
    return True, "ok", zone, flags, rel


def fingerprint(a: Analysis, ad, zone) -> str:
    anchor = re.sub(r"\D", "", ad.phones[0])[-10:] if ad.phones else norm(a.title or ad.text[:60])[:40]
    return hashlib.sha1(f"{zone}|{a.price_fcfa_month}|{anchor}".encode()).hexdigest()


def process(ctx: Ctx, ad, manual=False):
    """Retourne (statut, raison) ; statut ∈ sent | stored | rejected | dup | error."""
    db = ctx.db
    if ad.gone:
        db.mark_seen(ad.url)
        return "rejected", "annonce retirée ou expirée"
    if not manual and not prefilter(ctx, ad):
        db.mark_seen(ad.url)
        return "rejected", "pré-filtre (quartier/vocabulaire)"
    meta = f"Source : {ad.source}\nDate de la source : {ad.published or 'inconnue'}\n"
    if ad.phones:
        meta += f"Téléphones détectés : {', '.join(ad.phones)}\n"
    a = ctx.gem.analyze(meta + "\n" + ad.text, ctx.settings.budget, ctx.settings.zones)  # peut lever QuotaExceeded
    if a is None:
        return "error", "analyse impossible"
    db.mark_seen(ad.url)
    ok, reason, zone, flags, rel = evaluate(a, ad, ctx.settings, ctx.cfg["search"])
    if not ok:
        return "rejected", reason
    fp = fingerprint(a, ad, zone)
    if db.has_fp(fp):
        return "dup", "doublon d'une annonce déjà détectée"
    card = build_card(a, ad, zone, flags, rel)
    notify = manual or not ctx.settings.paused
    data = {"zone": zone, "price": a.price_fcfa_month, "source": ad.source}
    if notify:
        try:
            ctx.tg.send_ad(card, ad.images)
        except RuntimeError as e:
            log.error("envoi Telegram : %s", e)
            return "error", "envoi Telegram échoué"
    db.add_ad(fp, ad.url, data, rel, notify)
    return ("sent" if notify else "stored"), "ok"


def scan(ctx: Ctx):
    stats = {"sources": 0, "examinees": 0, "envoyees": 0, "stockees": 0, "quota": False}
    for src in ctx.cfg["sources"]:
        if not src.get("enabled", True):
            continue
        stats["sources"] += 1
        try:
            for ad in sources.iter_ads(src, ctx.cfg, ctx.db.is_seen):
                stats["examinees"] += 1
                status, why = process(ctx, ad)
                log.info("[%s] %s -> %s (%s)", src["name"], ad.url, status, why)
                if status == "sent":
                    stats["envoyees"] += 1
                elif status == "stored":
                    stats["stockees"] += 1
        except QuotaExceeded as e:
            log.warning("Arrêt du scan : %s", e)
            stats["quota"] = True
            break
        except Exception as e:  # une source cassée ne doit pas bloquer les autres
            log.exception("Source %s en erreur : %s", src["name"], type(e).__name__)
    return stats
