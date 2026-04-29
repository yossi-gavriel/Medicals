from app.integrations.base import BaseInteractionProvider


class DrugBankAPI(BaseInteractionProvider):
    provider_key = "drugbank"
    provider_name = "DrugBank"

    # Fallback map used when no external DrugBank connector is configured.
    atc_fallback_map: dict[str, str] = {
        "aspirin": "B01AC06",
        "warfarin": "B01AA03",
        "clopidogrel": "B01AC04",
        "simvastatin": "C10AA01",
        "atorvastatin": "C10AA05",
        "rosuvastatin": "C10AA07",
        "clarithromycin": "J01FA09",
        "azithromycin": "J01FA10",
        "metformin": "A10BA02",
        "lisinopril": "C09AA03",
        "losartan": "C09CA01",
        "spironolactone": "C03DA01",
    }

    async def get_atc_code(self, drug_name: str) -> str | None:
        normalized = drug_name.strip().lower()
        if not normalized:
            return None
        return self.atc_fallback_map.get(normalized)
