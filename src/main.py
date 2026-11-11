import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone

from . import sources
from .analyze import Gemini
from .bot import handle_update
from .config import Settings, load_config
from .db import DB
from .pipeline import Ctx, scan
from .tg import Telegram
from .util import fmt_price

log = logging.getLogger("main")


def build_ctx() -> Ctx:
    cfg = load_config()
    db = DB(os.environ.get("DB_PATH", "data/immo.db"))
    tg = Telegram(os.environ["TELEGRAM_BOT_TOKEN"], os.environ.get("TELEGRAM_CHAT_ID", ""))
    return Ctx(cfg, db, Settings(cfg, db), tg, Gemini(os.environ["GEMINI_API_KEY"], cfg["gemini"]))


def poll(ctx, timeout=0) -> bool:
    force = False
    for u in ctx.tg.get_updates(int(ctx.db.get("offset") or 0), timeout):
        ctx.db.set("offset", str(u["update_id"] + 1))
        try:
            force |= handle_update(ctx, u)
        except Exception as e:  # noqa
            log.exception("commande en erreur : %s", type(e).__name__)
    return force


def run_scan(ctx, announce):
    s = scan(ctx)
    log.info("scan : %s", s)
    if announce:
        extra = "\n⚠️ Quota Gemini atteint : le reste sera traité au prochain passage." if s["quota"] else ""
        ctx.tg.send_text(f"✅ Recherche terminée : {s['sources']} sources, {s['examinees']} nouvelles annonces "
                         f"examinées, {s['envoyees']} envoyée(s).{extra}")


def digest(ctx):
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    if ctx.settings.paused or now.hour < ctx.cfg["schedule"]["daily_digest_hour_utc"] \
            or ctx.db.get("last_digest") == today:
        return
    rows = ctx.db.recent(50, since=time.time() - 86400)
    ctx.db.set("last_digest", today)
    if rows:
        rows.sort(key=lambda r: -r["relevance"])
        ctx.tg.send_text(f"📰 <b>Récapitulatif 24 h</b> — {len(rows)} annonce(s)\n" + "\n".join(
            f"• {r['zone']} — {fmt_price(r['price'])} — {r['relevance']} % — {r['url']}" for r in rows[:8]))
    else:
        ctx.tg.send_text("📰 Récapitulatif 24 h : aucune nouvelle annonce correspondante.")


def check_sources():
    cfg = load_config()
    for s in cfg["sources"]:
        if not s.get("enabled", True):
            continue
        if s["type"] == "html":
            links = sources.list_links(s)
            print(f"{'OK ' if links else 'KO '} {s['name']:<28} {len(links):>3} liens  ex: {links[:2]}")
        else:
            n = len(list(sources.iter_ads(s, cfg, lambda u: False)))
            print(f"{'OK ' if n else 'KO '} {s['name']:<28} {n:>3} messages")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="un passage (GitHub Actions)")
    ap.add_argument("--daemon", action="store_true", help="boucle continue (PC / serveur / Raspberry)")
    ap.add_argument("--check-sources", action="store_true", help="teste la collecte sans Gemini ni Telegram")
    args = ap.parse_args()
    if args.check_sources:
        return check_sources()
    ctx = build_ctx()
    if args.daemon:
        last, every = 0.0, ctx.cfg["schedule"]["daemon_interval_minutes"] * 60
        while True:
            try:
                force = poll(ctx, 25)
                if force or (not ctx.settings.paused and time.time() - last >= every):
                    run_scan(ctx, announce=force)
                    last = time.time()
                digest(ctx)
            except Exception as e:  # noqa
                log.exception("boucle : %s", type(e).__name__)
                time.sleep(30)
    else:
        force = poll(ctx, 0)
        if force or not ctx.settings.paused:
            run_scan(ctx, announce=force)
        digest(ctx)


if __name__ == "__main__":
    sys.exit(main())
