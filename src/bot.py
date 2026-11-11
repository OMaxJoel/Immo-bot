import logging
import re
from urllib.parse import urlparse

from . import sources
from .analyze import QuotaExceeded
from .pipeline import process
from .sources import RawAd, PHONE_RE
from .util import fmt_price

log = logging.getLogger("bot")
SOCIAL = ("facebook.com", "fb.com", "fb.me", "instagram.com", "tiktok.com", "m.facebook.com")

HELP = ("🤖 <b>Assistant immobilier — Abidjan</b>\n\n"
        "/recherche — lancer une recherche immédiate\n/criteres — critères actuels\n"
        "/sources — sources surveillées\n/recentes — dernières annonces détectées\n"
        "/budget [montant] — voir/modifier le budget max\n"
        "/localisation [quartier1, quartier2] — voir/modifier les quartiers\n"
        "/stop — suspendre les notifications\n/resume — reprendre\n\n"
        "💡 <b>Facebook / Instagram / TikTok</b> : ces plateformes interdisent la collecte automatique. "
        "Si vous voyez une annonce intéressante, <b>transférez-la ou collez son texte (ou son lien) ici</b> : "
        "je l'analyse, la compare à vos critères et vous réponds.")


def handle_update(ctx, upd) -> bool:
    """Traite un message. Retourne True si une recherche immédiate est demandée."""
    msg = upd.get("message")
    if not msg:
        return False
    chat = str(msg["chat"]["id"])
    tg, st = ctx.tg, ctx.settings
    if not tg.chat_id:  # configuration initiale : on révèle l'identifiant de chat
        tg.send_text(f"Votre TELEGRAM_CHAT_ID est : <code>{chat}</code>\nAjoutez-le dans vos secrets puis relancez.", chat)
        return False
    if chat != tg.chat_id:
        return False  # personne d'autre que vous ne peut utiliser le bot
    text = (msg.get("text") or msg.get("caption") or "").strip()
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()

    if cmd in ("/start", "/aide", "/help"):
        tg.send_text(HELP)
    elif cmd == "/recherche":
        tg.send_text("🔎 Recherche lancée…")
        return True
    elif cmd == "/criteres":
        z = ", ".join(x["name"] for x in st.zones)
        tg.send_text(f"📋 <b>Critères</b>\n• Type : appartement 2 pièces (salon + 1 chambre)\n"
                     f"• Budget max : {fmt_price(st.budget)} / mois\n• Quartiers : {z}\n"
                     f"• Préférence : non meublé\n• Notifications : {'⏸️ suspendues' if st.paused else '▶️ actives'}")
    elif cmd == "/sources":
        names = [s["name"] for s in ctx.cfg["sources"] if s.get("enabled", True)]
        tg.send_text("📡 <b>Sources surveillées</b>\n" + "\n".join(f"• {n}" for n in names) +
                     "\n\nFacebook/Instagram/TikTok : via transfert manuel au bot.")
    elif cmd == "/recentes":
        rows = ctx.db.recent(10)
        if not rows:
            tg.send_text("Aucune annonce détectée pour l'instant.")
        else:
            tg.send_text("🕘 <b>Dernières annonces</b>\n" + "\n".join(
                f"• {r['zone']} — {fmt_price(r['price'])} — {r['relevance']} % — {r['url']}" for r in rows))
    elif cmd == "/budget":
        if not arg.strip():
            tg.send_text(f"💰 Budget max actuel : {fmt_price(st.budget)}")
        else:
            m = re.fullmatch(r"(\d[\d\s.]*)\s*(k?)", arg.strip().lower())
            if not m:
                tg.send_text("Format : /budget 150000  (ou /budget 150k)")
            else:
                v = int(re.sub(r"\D", "", m.group(1))) * (1000 if m.group(2) else 1)
                st.set_budget(v)
                tg.send_text(f"✅ Budget max : {fmt_price(v)}")
    elif cmd == "/localisation":
        if not arg.strip():
            tg.send_text("📍 Quartiers : " + ", ".join(x["name"] for x in st.zones) +
                         "\nPour modifier : /localisation Riviera 2, Blockhaus")
        else:
            names = st.set_zones([x for x in arg.split(",")])
            tg.send_text("✅ Quartiers : " + ", ".join(names))
    elif cmd == "/stop":
        st.set_paused(True)
        tg.send_text("⏸️ Notifications suspendues. /resume pour reprendre.")
    elif cmd == "/resume":
        st.set_paused(False)
        tg.send_text("▶️ Notifications reprises.")
    elif cmd.startswith("/"):
        tg.send_text("Commande inconnue. /aide")
    elif text or msg.get("photo"):
        _manual_ad(ctx, msg, text)
    return False


def _manual_ad(ctx, msg, text):
    """Annonce transmise par l'utilisateur (Facebook, WhatsApp, lien...)."""
    tg = ctx.tg
    urls = re.findall(r"https?://\S+", text)
    ad = None
    if urls and not any(d in urlparse(urls[0]).netloc for d in SOCIAL):
        ad = sources.page_to_ad(urls[0], "Transmis manuellement")
    if ad is None:
        photos = [msg["photo"][-1]["file_id"]] if msg.get("photo") else []
        ad = RawAd(urls[0] if urls else f"manuel:{abs(hash(text))}", "Transmis manuellement" , text,
                   photos, sorted(set(PHONE_RE.findall(text))))
    try:
        status, why = process(ctx, ad, manual=True)
    except QuotaExceeded:
        tg.send_text("⚠️ Quota Gemini atteint, réessayez plus tard.")
        return
    if status != "sent":
        tg.send_text(f"❌ Annonce non retenue : {why}")
