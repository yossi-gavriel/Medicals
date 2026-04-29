from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models import (
    ComplianceResult,
    ComplianceRuleResult,
    ExtractionAudit,
    ExtractionRow,
    ExtractionRun,
    ReimbursementCase,
    ReimbursementCaseEvent,
)
from app.repositories.extraction_repository import ExtractionRunRepository
from app.services.compliance import ComplianceEvaluator
from app.services.extraction_engine import (
    ExtractionEngine,
    compute_spec_hash,
    load_specification,
)


def _spec() -> dict:
    return {
        "version": "1.0",
        "treatments": [
            {
                "treatment_code": "CATARACT_SURGERY",
                "rules": [
                    {
                        "field_name": "has_cataract_diagnosis",
                        "type": "boolean",
                        "positive_indicators": ["cataract"],
                        "negative_indicators": ["no cataract"],
                        "default_when_missing": False,
                    },
                    {"field_name": "surgery_date", "type": "date"},
                    {
                        "field_name": "operated_eye",
                        "type": "enum",
                        "allowed_values": ["left", "right", "both", "unknown"],
                    },
                ],
            },
            {
                "treatment_code": "GLAUCOMA_CHECK",
                "rules": [
                    {
                        "field_name": "iop_high",
                        "type": "boolean",
                        "positive_indicators": ["intraocular pressure elevated"],
                    }
                ],
            },
        ],
    }


def _compliance_spec() -> dict:
    payload = _spec()
    payload["treatments"][0]["compliance_rules"] = [
        {
            "rule_id": "minimum_24_hours",
            "description": "Hospitalization must be at least 24 hours",
            "field": "hospitalization_hours",
            "operator": "gte",
            "value": 24,
            "severity": "medium",
            "on_fail": {
                "status": "non_compliant",
                "reason": "Hospitalization duration is below the required threshold",
                "recommended_action": "request_reimbursement",
            },
        }
    ]
    payload["treatments"][0]["rules"].append(
        {
            "field_name": "hospitalization_hours",
            "type": "number",
            "positive_indicators": ["hospitalization duration"],
        }
    )
    return payload


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path/'test.db'}"
    try:
        engine = create_async_engine(db_url, future=True)
    except ModuleNotFoundError:  # pragma: no cover
        pytest.skip("aiosqlite is required for async SQLite tests")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_persist_creates_one_extraction_run(session_factory):
    spec = load_specification(_spec())
    engine = ExtractionEngine()
    text = "Cataract diagnosed; surgery date 10/02/2024. Left eye. intraocular pressure elevated."
    result = engine.run(document_id="doc_1", document_text=text, spec=spec)

    async with session_factory() as session, session.begin():
        run_id = await ExtractionRunRepository(session).persist(
            result, spec_hash=compute_spec_hash(spec)
        )

    async with session_factory() as session:
        runs = (await session.execute(select(ExtractionRun))).scalars().all()
        assert len(runs) == 1
        assert runs[0].id == run_id
        assert runs[0].document_id == "doc_1"
        assert runs[0].spec_version == "1.0"
        assert runs[0].spec_hash == compute_spec_hash(spec)


@pytest.mark.asyncio
async def test_persist_creates_one_row_per_treatment_code(session_factory):
    spec = load_specification(_spec())
    engine = ExtractionEngine()
    text = "Cataract diagnosed; surgery date 10/02/2024. Left eye. intraocular pressure elevated."
    result = engine.run(document_id="doc_2", document_text=text, spec=spec)

    async with session_factory() as session, session.begin():
        await ExtractionRunRepository(session).persist(
            result, spec_hash=compute_spec_hash(spec)
        )

    async with session_factory() as session:
        rows = (await session.execute(select(ExtractionRow))).scalars().all()
        treatment_codes = sorted(r.treatment_code for r in rows)
        assert treatment_codes == ["CATARACT_SURGERY", "GLAUCOMA_CHECK"]
        for r in rows:
            assert r.document_id == "doc_2"


@pytest.mark.asyncio
async def test_row_values_excludes_document_id_and_treatment_code(session_factory):
    spec = load_specification(_spec())
    engine = ExtractionEngine()
    text = "Cataract diagnosed; surgery date 10/02/2024. Left eye."
    result = engine.run(document_id="doc_3", document_text=text, spec=spec)

    async with session_factory() as session, session.begin():
        await ExtractionRunRepository(session).persist(
            result, spec_hash=compute_spec_hash(spec)
        )

    async with session_factory() as session:
        cataract_row = (
            await session.execute(
                select(ExtractionRow).where(ExtractionRow.treatment_code == "CATARACT_SURGERY")
            )
        ).scalar_one()
        assert "document_id" not in cataract_row.values
        assert "treatment_code" not in cataract_row.values
        assert cataract_row.values["has_cataract_diagnosis"] is True
        assert cataract_row.values["surgery_date"] == "2024-02-10"
        assert cataract_row.values["operated_eye"] == "left"


@pytest.mark.asyncio
async def test_persist_creates_one_audit_entry_per_field(session_factory):
    spec = load_specification(_spec())
    engine = ExtractionEngine()
    text = "Cataract diagnosed; surgery date 10/02/2024. Left eye. intraocular pressure elevated."
    result = engine.run(document_id="doc_4", document_text=text, spec=spec)

    async with session_factory() as session, session.begin():
        await ExtractionRunRepository(session).persist(
            result, spec_hash=compute_spec_hash(spec)
        )

    async with session_factory() as session:
        audit = (await session.execute(select(ExtractionAudit))).scalars().all()
        # 3 fields for cataract + 1 for glaucoma = 4 audit entries
        assert len(audit) == 4
        diag = next(a for a in audit if a.field_name == "has_cataract_diagnosis")
        assert diag.value is True
        assert diag.evidence
        assert diag.confidence is not None
        assert diag.reason


@pytest.mark.asyncio
async def test_rollback_prevents_partial_persistence(session_factory, monkeypatch):
    """If audit insert fails after rows succeed, NO run/row/audit must remain.

    We force a failure by making the second flush (the one for audit entries)
    raise before commit. The transaction rolls back; the DB stays empty.
    """
    spec = load_specification(_spec())
    engine = ExtractionEngine()
    text = "Cataract diagnosed; surgery date 10/02/2024. Left eye. intraocular pressure elevated."
    result = engine.run(document_id="doc_rollback", document_text=text, spec=spec)

    real_persist = ExtractionRunRepository.persist

    async def _failing_persist(self, result, *, spec_hash, tenant_id=None):
        # Run the real path far enough to insert the run + rows, then blow up
        # before the final flush that would have inserted audit. The outer
        # session.begin() is responsible for rolling everything back.
        await real_persist(self, result, spec_hash=spec_hash, tenant_id=tenant_id)
        raise RuntimeError("simulated audit insert failure")

    monkeypatch.setattr(ExtractionRunRepository, "persist", _failing_persist)

    async with session_factory() as session:
        with pytest.raises(RuntimeError, match="simulated audit insert failure"):
            async with session.begin():
                await ExtractionRunRepository(session).persist(
                    result, spec_hash=compute_spec_hash(spec)
                )

    async with session_factory() as session:
        runs = (await session.execute(select(ExtractionRun))).scalars().all()
        rows = (await session.execute(select(ExtractionRow))).scalars().all()
        audit = (await session.execute(select(ExtractionAudit))).scalars().all()
        assert runs == []
        assert rows == []
        assert audit == []


@pytest.mark.asyncio
async def test_persist_creates_compliance_rule_results_and_reimbursement_case(session_factory):
    spec = load_specification(_compliance_spec())
    engine = ExtractionEngine()
    result = engine.run(
        document_id="doc_refund",
        document_text="Cataract diagnosed. hospitalization duration 6 hours.",
        spec=spec,
    )
    compliance = ComplianceEvaluator().evaluate(extraction_result=result, spec=spec)

    async with session_factory() as session, session.begin():
        run_id = await ExtractionRunRepository(session).persist(
            result,
            spec_hash=compute_spec_hash(spec),
            tenant_id="tenant-a",
            metadata={
                "patient_id": "p1",
                "billed_amount": 1200.50,
                "currency": "ILS",
            },
            duration_ms=12,
            compliance_results=compliance,
        )

    async with session_factory() as session:
        persisted = (await session.execute(select(ComplianceResult))).scalar_one()
        rule = (await session.execute(select(ComplianceRuleResult))).scalar_one()
        case = (await session.execute(select(ReimbursementCase))).scalar_one()
        event = (await session.execute(select(ReimbursementCaseEvent))).scalar_one()
        run = (await session.execute(select(ExtractionRun))).scalar_one()

    assert persisted.run_id == run_id
    assert persisted.status == "non_compliant"
    assert rule.actual == 6
    assert rule.expected == 24
    assert rule.evidence
    assert case.tenant_id == "tenant-a"
    assert case.status == "draft"
    assert float(case.estimated_amount) == 1200.50
    assert case.currency == "ILS"
    assert event.case_id == case.id
    assert event.event_type == "case_created"
    assert event.previous_status is None
    assert event.new_status == "draft"
    assert run.context_metadata["patient_id"] == "p1"
    assert run.duration_ms == 12


@pytest.mark.asyncio
async def test_compliant_result_does_not_create_reimbursement_case(session_factory):
    spec = load_specification(_compliance_spec())
    engine = ExtractionEngine()
    result = engine.run(
        document_id="doc_compliant",
        document_text="Cataract diagnosed. hospitalization duration 30 hours.",
        spec=spec,
    )
    compliance = ComplianceEvaluator().evaluate(extraction_result=result, spec=spec)

    async with session_factory() as session, session.begin():
        await ExtractionRunRepository(session).persist(
            result,
            spec_hash=compute_spec_hash(spec),
            tenant_id="tenant-a",
            compliance_results=compliance,
        )

    async with session_factory() as session:
        cases = (await session.execute(select(ReimbursementCase))).scalars().all()
        persisted = (await session.execute(select(ComplianceResult))).scalar_one()

    assert persisted.status == "compliant"
    assert cases == []


@pytest.mark.asyncio
async def test_rollback_prevents_partial_compliance_persistence(session_factory, monkeypatch):
    spec = load_specification(_compliance_spec())
    engine = ExtractionEngine()
    result = engine.run(
        document_id="doc_compliance_rollback",
        document_text="Cataract diagnosed. hospitalization duration 6 hours.",
        spec=spec,
    )
    compliance = ComplianceEvaluator().evaluate(extraction_result=result, spec=spec)
    real_persist_compliance = ExtractionRunRepository._persist_compliance_results

    async def _failing_compliance_persist(self, *, run_id, tenant_id, metadata, compliance_results):
        await real_persist_compliance(
            self,
            run_id=run_id,
            tenant_id=tenant_id,
            metadata=metadata,
            compliance_results=compliance_results,
        )
        raise RuntimeError("simulated compliance insert failure")

    monkeypatch.setattr(
        ExtractionRunRepository,
        "_persist_compliance_results",
        _failing_compliance_persist,
    )

    async with session_factory() as session:
        with pytest.raises(RuntimeError, match="simulated compliance insert failure"):
            async with session.begin():
                await ExtractionRunRepository(session).persist(
                    result,
                    spec_hash=compute_spec_hash(spec),
                    tenant_id="tenant-a",
                    compliance_results=compliance,
                )

    async with session_factory() as session:
        runs = (await session.execute(select(ExtractionRun))).scalars().all()
        rows = (await session.execute(select(ExtractionRow))).scalars().all()
        audit = (await session.execute(select(ExtractionAudit))).scalars().all()
        compliance_rows = (await session.execute(select(ComplianceResult))).scalars().all()
        rule_rows = (await session.execute(select(ComplianceRuleResult))).scalars().all()
        cases = (await session.execute(select(ReimbursementCase))).scalars().all()
        case_events = (await session.execute(select(ReimbursementCaseEvent))).scalars().all()

    assert runs == []
    assert rows == []
    assert audit == []
    assert compliance_rows == []
    assert rule_rows == []
    assert cases == []
    assert case_events == []
