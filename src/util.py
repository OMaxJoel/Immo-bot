import re
import unicodedata


def norm(s: str) -> str:
    """minuscules, sans accents, ponctuation -> espaces."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def contains(norm_text: str, norm_alias: str) -> bool:
    return f" {norm_alias} " in f" {norm_text} "


def fmt_price(p) -> str:
    return f"{int(p):,}".replace(",", " ") + " FCFA" if p else "Non précisé"
