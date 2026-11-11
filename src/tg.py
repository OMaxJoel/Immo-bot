import html
import json
import logging
import requests

from .util import fmt_price

log = logging.getLogger("telegram")
API = "https://api.telegram.org/bot{}/{}"
POSTER = {"proprietaire": "Propriétaire direct", "agence": "Agence",
          "demarcheur": "Démarcheur / courtier", "inconnu": "Non précisé"}


def esc(x) -> str:
    return html.escape(str(x), quote=False)


class Telegram:
    def __init__(self, token: str, chat_id: str):
        self.token, self.chat_id = token, str(chat_id or "")

    def call(self, method, data=None, files=None, timeout=30):
        try:
            r = requests.post(API.format(self.token, method), data=data, files=files, timeout=timeout)
            j = r.json()
        except (requests.RequestException, ValueError):
            # on n'inclut jamais l'URL (elle contient le token) dans les erreurs
            raise RuntimeError(f"Telegram {method} : erreur réseau") from None
        if not j.get("ok"):
            raise RuntimeError(f"Telegram {method} : {j.get('description')}")
        return j["result"]

    def get_updates(self, offset, timeout=0):
        return self.call("getUpdates", {"offset": offset, "timeout": timeout,
                                        "allowed_updates": json.dumps(["message"])}, timeout=timeout + 15)

    def send_text(self, text, chat_id=None):
        cid = chat_id or self.chat_id
        for i in range(0, len(text), 4000):
            self.call("sendMessage", {"chat_id": cid, "text": text[i:i + 4000], "parse_mode": "HTML",
                                      "disable_web_page_preview": "true"})

    # --- photos : d'abord par URL / file_id, sinon on télécharge puis on envoie le fichier ---
    def _download(self, url):
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and len(r.content) < 8_000_000:
                return r.content
        except requests.RequestException:
            pass
        return None

    def _photos(self, photos, caption, upload=False):
        cid = self.chat_id
        files, media = {}, []
        for i, p in enumerate(photos):
            ref = p
            if upload:
                content = self._download(p) if p.startswith("http") else None
                if content is None:
                    continue
                files[f"f{i}"] = (f"p{i}.jpg", content)
                ref = f"attach://f{i}"
            media.append({"type": "photo", "media": ref})
        if not media:
            raise RuntimeError("aucune photo exploitable")
        if len(media) == 1:  # sendMediaGroup exige 2 à 10 éléments
            d = {"chat_id": cid, "photo": media[0]["media"]}
            if caption:
                d.update(caption=caption, parse_mode="HTML")
            if upload:
                d["photo"] = "attach://photo"
                return self.call("sendPhoto", d, files={"photo": next(iter(files.values()))})
            return self.call("sendPhoto", d)
        if caption:
            media[0]["caption"], media[0]["parse_mode"] = caption, "HTML"
        return self.call("sendMediaGroup", {"chat_id": cid, "media": json.dumps(media)}, files=files or None)

    def send_ad(self, card: str, images):
        images = (images or [])[:10]
        if not images:
            return self.send_text(card)
        caption = card if len(card) <= 1000 else None
        if caption is None:
            self.send_text(card)
        for upload in (False, True):
            try:
                return self._photos(images, caption, upload=upload)
            except RuntimeError as e:
                log.info("album échec (upload=%s) : %s", upload, e)
        if caption is not None:
            self.send_text(card + "\n\n<i>(photos non transmissibles : voir le lien)</i>")


def build_card(a, ad, zone, flags, relevance) -> str:
    cfg_line = {1: "1 chambre + salon", 0: "Studio"}.get(a.bedrooms,
               f"{a.bedrooms} chambres + salon" if a.bedrooms else "À confirmer")
    typ = "Appartement 2 pièces" if a.bedrooms == 1 else "Appartement (configuration à confirmer)"
    equip = ", ".join(a.equipment) if a.equipment else "Non renseignés"
    meuble = {True: "meublé", False: "non meublé", None: "meublé ? non précisé"}[a.furnished]
    avail = "À confirmer auprès du propriétaire"
    if a.availability:
        avail += f" — l'annonce indique : « {a.availability} »"
    contact = a.contact or (", ".join(ad.phones) if ad.phones else "Voir l'annonce originale")
    L = ["🏠 <b>NOUVELLE ANNONCE IMMOBILIÈRE</b>", "",
         f"📍 Localisation : {esc(zone)}" + (f" ({esc(a.zone_text)})" if a.zone_text and a.zone_text.lower() != zone.lower() else ""),
         f"🏢 Type : {typ}",
         f"💰 Loyer mensuel : {fmt_price(a.price_fcfa_month)}",
         f"🛏️ Configuration : {cfg_line}",
         f"🛋️ Équipements : {esc(equip)} ({meuble})",
         f"📅 Publication : {esc(a.published_date or ad.published or 'Non précisée')}",
         f"🔎 Disponibilité : {esc(avail)}",
         f"👤 Contact : {esc(contact)} — {POSTER[a.poster_type]}"]
    if a.visit_fee:
        L.append(f"💸 Frais de visite : {esc(a.visit_fee)}")
    if flags:
        L += ["", "⚠️ <b>Points d'attention :</b>"] + [f"• {esc(f)}" for f in flags]
    L += ["", f"🔗 <a href=\"{html.escape(ad.url)}\">Consulter l'annonce originale</a> ({esc(ad.source)})",
          f"⭐ Pertinence : {relevance} %"]
    return "\n".join(L)
