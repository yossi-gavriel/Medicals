from __future__ import annotations

from itertools import combinations

from sqlalchemy.ext.asyncio import AsyncSession

from app.algorithms.contraindication_checker import ContraindicationChecker
from app.algorithms.interaction_checker import InteractionChecker
from app.algorithms.interaction_checker import MedicationContext
from app.algorithms.interaction_graph import InteractionGraph
from app.core.cache import CacheClient
from app.core.settings import Settings
from app.integrations.base import BaseInteractionProvider
from app.integrations.drugbank_api import DrugBankAPI
from app.integrations.dynamed_api import DynaMedAPI
from app.integrations.first_databank_api import FirstDatabankAPI
from app.integrations.lexicomp_api import LexicompAPI
from app.integrations.micromedex_api import MicromedexAPI
from app.integrations.uptodate_api import UpToDateAPI
from app.repositories.drug_repository import DrugRepository
from app.repositories.interaction_repository import InteractionRepository
from app.repositories.patient_repository import PatientRepository
from app.schemas import InteractionIssue, PrescriptionSafetyResponse
from app.services.alternative_service import AlternativeService
from app.services.clinical_explanation_service import ClinicalExplanationService
from app.services.drug_class_service import DrugClassService
from app.services.drug_normalization_service import DrugNormalizationService
from app.services.drug_normalization_service import MedicationInput
from app.services.drug_normalization_service import NormalizedMedication


class InteractionService:
    def __init__(
        self,
        settings: Settings,
        cache_client: CacheClient,
        graph: InteractionGraph,
        class_service: DrugClassService,
        normalization_service: DrugNormalizationService | None = None,
    ) -> None:
        self.settings = settings
        self.graph = graph
        self.providers = self._build_providers(settings)
        self.checker = InteractionChecker(settings, cache_client, graph, self.providers)
        self.explainer = ClinicalExplanationService()
        self.normalizer = normalization_service or DrugNormalizationService()
        self.contraindication_checker = ContraindicationChecker()
        self.alternative_service = AlternativeService(self.checker, class_service)

    def _build_providers(self, settings: Settings) -> list[BaseInteractionProvider]:
        providers: dict[str, BaseInteractionProvider] = {
            "uptodate": UpToDateAPI(settings, settings.uptodate_api_url, settings.uptodate_api_key),
            "dynamed": DynaMedAPI(settings, settings.dynamed_api_url, settings.dynamed_api_key),
            "lexicomp": LexicompAPI(settings, settings.lexicomp_api_url, settings.lexicomp_api_key),
            "micromedex": MicromedexAPI(settings, settings.micromedex_api_url, settings.micromedex_api_key),
            "drugbank": DrugBankAPI(settings, settings.drugbank_api_url, settings.drugbank_api_key),
            "first_databank": FirstDatabankAPI(
                settings, settings.first_databank_api_url, settings.first_databank_api_key
            ),
        }
        return [providers[name] for name in settings.enabled_providers if name in providers]

    async def load_graph(self, session: AsyncSession) -> None:
        interaction_repo = InteractionRepository(session)
        self.graph.clear()
        rows = await interaction_repo.list_all_interactions()
        for drug_a, drug_b, interaction in rows:
            self.graph.upsert_interaction(
                drug_a,
                drug_b,
                interaction.severity,
                interaction.risk,
                interaction.recommendation,
                interaction.source,
            )

    async def check_prescription(
        self,
        patient_id: str,
        new_drugs: list[str] | None,
        session: AsyncSession,
        new_medications: list[MedicationInput] | None = None,
    ) -> PrescriptionSafetyResponse:
        drug_repo = DrugRepository(session)
        interaction_repo = InteractionRepository(session)
        patient_repo = PatientRepository(session)

        current_drugs = await patient_repo.get_current_medications(patient_id)
        normalized_medications = await self.normalizer.normalize_medications(new_medications or [], drug_repo)
        normalized_new = [item.canonical_name for item in normalized_medications]

        normalized_from_names = await self.normalizer.normalize_names(new_drugs or [], drug_repo)
        existing = set(normalized_new)
        for name in normalized_from_names:
            if name in existing:
                continue
            normalized_medications.append(NormalizedMedication(canonical_name=name))
            normalized_new.append(name)
            existing.add(name)

        # Ensure all drugs exist locally for future graph/cache updates.
        for drug in current_drugs + normalized_new:
            await drug_repo.get_or_create(drug)

        issues: list[InteractionIssue] = []
        unsafe_new_drugs: set[str] = set()

        medication_lookup = {
            medication.canonical_name: MedicationContext(
                dose=medication.dose,
                unit=medication.unit,
                frequency=medication.frequency,
            )
            for medication in normalized_medications
        }

        for new_drug in normalized_new:
            for current in current_drugs:
                result = await self.checker.check_pair(
                    new_drug,
                    current,
                    drug_repo,
                    interaction_repo,
                    drug_a_context=medication_lookup.get(new_drug),
                    drug_b_context=None,
                )
                if result.is_unsafe:
                    unsafe_new_drugs.add(new_drug)
                    issues.append(
                        InteractionIssue(
                            drug=new_drug,
                            conflicts_with=current,
                            severity=result.severity,
                            risk=result.risk,
                            recommendation=result.recommendation,
                            source=result.source,
                            explanation=self.explainer.explain(
                                new_drug,
                                current,
                                result.risk,
                                result.severity,
                            ),
                        )
                    )

        for drug_a, drug_b in combinations(normalized_new, 2):
            result = await self.checker.check_pair(
                drug_a,
                drug_b,
                drug_repo,
                interaction_repo,
                drug_a_context=medication_lookup.get(drug_a),
                drug_b_context=medication_lookup.get(drug_b),
            )
            if result.is_unsafe:
                unsafe_new_drugs.update([drug_a, drug_b])
                issues.append(
                    InteractionIssue(
                        drug=drug_a,
                        conflicts_with=drug_b,
                        severity=result.severity,
                        risk=result.risk,
                        recommendation=result.recommendation,
                        source=result.source,
                        explanation=self.explainer.explain(
                            drug_a,
                            drug_b,
                            result.risk,
                            result.severity,
                        ),
                    )
                )

        alternatives = []
        for unsafe_drug in sorted(unsafe_new_drugs):
            pending = [item for item in normalized_new if item != unsafe_drug]
            alternatives.extend(
                await self.alternative_service.suggest_alternatives(
                    unsafe_drug=unsafe_drug,
                    current_drugs=current_drugs,
                    pending_new_drugs=pending,
                    drug_repo=drug_repo,
                    interaction_repo=interaction_repo,
                )
            )

        # Placeholder execution to keep contraindication checks aligned with the
        # main safety pipeline until dedicated response fields are introduced.
        self.contraindication_checker.check(current_drugs + normalized_new)

        deduped_alternatives = list({item.drug: item for item in alternatives}.values())[:3]
        await session.commit()

        return PrescriptionSafetyResponse(
            safe=len(issues) == 0,
            issues=issues,
            suggested_alternatives=deduped_alternatives,
        )
