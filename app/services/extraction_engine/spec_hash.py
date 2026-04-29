from __future__ import annotations

import hashlib
import json

from app.services.extraction_engine.spec import Specification


def compute_spec_hash(spec: Specification) -> str:
    """Return a deterministic SHA-256 hex digest for a normalized spec.

    Two specs with the same semantic content produce the same hash regardless
    of key ordering or whitespace. The hash is computed by:

    1. Serializing through Pydantic (drops unknown fields, applies validators
       which strip indicators and trim names — that normalization is the point
       at which the hash becomes "canonical").
    2. Re-encoding as JSON with sorted keys and a compact separator.
    3. SHA-256 over the resulting UTF-8 bytes.
    """
    normalized = spec.model_dump(mode="json")
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
