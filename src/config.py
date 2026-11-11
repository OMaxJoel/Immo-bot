import json
import os
import yaml
from .util import norm, contains


def load_config(path=None):
    path = path or os.environ.get("CONFIG_PATH", "config.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class Settings:
    """Critères effectifs = config.yaml + modifications faites via Telegram (stockées en base)."""

    def __init__(self, cfg, db):
        self.cfg, self.db = cfg, db

    @property
    def budget(self) -> int:
        return int(self.db.get("budget") or self.cfg["search"]["max_budget_fcfa"])

    def set_budget(self, v: int):
        self.db.set("budget", str(int(v)))

    @property
    def zones(self):
        all_z = self.cfg["search"]["zones"]
        saved = self.db.get("zones")
        if not saved:
            return all_z
        out = []
        for name in json.loads(saved):
            m = next((z for z in all_z if norm(z["name"]) == norm(name)), None)
            out.append(m or {"name": name, "aliases": [name]})
        return out

    def set_zones(self, names):
        all_z = self.cfg["search"]["zones"]
        resolved = []
        for n in names:
            nn = norm(n)
            if not nn:
                continue
            m = next((z for z in all_z if nn in norm(z["name"]) or
                      any(nn == norm(a) for a in z["aliases"])), None)
            resolved.append(m["name"] if m else n.strip())
        self.db.set("zones", json.dumps(resolved, ensure_ascii=False))
        return resolved

    @property
    def paused(self) -> bool:
        return self.db.get("paused") == "1"

    def set_paused(self, v: bool):
        self.db.set("paused", "1" if v else "0")

    def zone_of(self, text: str):
        t = norm(text)
        for z in self.zones:
            for a in z["aliases"] + [z["name"]]:
                if contains(t, norm(a)):
                    return z["name"]
        return None
