import logging
import time
from typing import List, Literal, Optional

from pydantic import BaseModel

log = logging.getLogger("gemini")


class QuotaExceeded(Exception):
    pass


class Analysis(BaseModel):
    is_rental: bool                       # location (et non vente / recherche de logement)
    is_residential: bool                  # logement (et non bureau, magasin, terrain...)
    is_short_term: bool                   # location journalière / hebdomadaire (type Airbnb)
    bedrooms: Optional[int]               # nb de chambres ; null si inconnu
    price_fcfa_month: Optional[int]       # loyer MENSUEL en FCFA ; null si absent
    zone_text: Optional[str]              # quartier cité dans l'annonce, tel quel
    furnished: Optional[bool]
    equipment: List[str]
    published_date: Optional[str]         # AAAA-MM-JJ si présente dans le texte
    contact: Optional[str]
    poster_type: Literal["proprietaire", "agence", "demarcheur", "inconnu"]
    visit_fee: Optional[str]
    availability: Optional[str]           # ce que dit l'annonce, sans extrapoler
    contradictions: List[str]
    suspicious: List[str]
    relevance: int                        # 0-100
    title: Optional[str]


PROMPT = """Tu analyses une annonce immobilière d'Abidjan (Côte d'Ivoire), souvent mal rédigée.
RÈGLES STRICTES : n'invente RIEN. Si une information n'est pas dans le texte, mets null (ou liste vide).
Vocabulaire local : "2 pièces", "F2", "salon-chambre", "chambre-salon", "appartement avec une chambre" = salon + 1 chambre (bedrooms=1).
Un studio = bedrooms 0. "3 pièces"/"F3" = salon + 2 chambres (bedrooms=2).
Le prix doit être le LOYER MENSUEL en FCFA (ex: "130.000", "130 000 F", "130k" -> 130000).
Ne confonds pas le loyer avec la caution, l'avance, les frais d'agence ou un prix de vente.
Prix journalier ou hebdomadaire : is_short_term=true et price_fcfa_month=null.
availability = ce que l'annonce affirme (ex: "disponible immédiatement"), jamais une déduction.
poster_type : "proprietaire" seulement si l'annonce le dit (ex: "sans démarcheur", "directement propriétaire").
suspicious : signale prix incohérent, demande d'argent avant visite, photos génériques, texte copié...
contradictions : informations incompatibles dans le texte.
relevance (0-100) : adéquation avec la recherche ci-dessous.

RECHERCHE : appartement 2 pièces (salon + 1 chambre) en location, loyer mensuel max {budget} FCFA,
quartiers : {zones}. Préférence pour le non-meublé.

ANNONCE :
\"\"\"
{text}
\"\"\"
"""


class Gemini:
    def __init__(self, api_key: str, gcfg: dict):
        from google import genai
        self.client = genai.Client(api_key=api_key)
        self.model = gcfg["model"]
        self.max_calls = gcfg["max_calls_per_run"]
        self.gap = gcfg["seconds_between_calls"]
        self.calls = 0
        self._last = 0.0

    def analyze(self, text: str, budget: int, zones: list) -> Optional[Analysis]:
        from google.genai import types
        if self.calls >= self.max_calls:
            raise QuotaExceeded("plafond d'appels Gemini par exécution atteint")
        prompt = PROMPT.format(budget=budget, zones=", ".join(z["name"] for z in zones), text=text[:4500])
        for attempt in range(2):
            wait = self.gap - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                resp = self.client.models.generate_content(
                    model=self.model, contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=Analysis, temperature=0.1))
                self.calls += 1
                if isinstance(resp.parsed, Analysis):
                    return resp.parsed
                return Analysis.model_validate_json(resp.text)
            except Exception as e:  # noqa
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    if attempt == 0:
                        time.sleep(35)
                        continue
                    raise QuotaExceeded("quota Gemini atteint")
                log.warning("Erreur Gemini : %s", msg[:200])
                return None
        return None
