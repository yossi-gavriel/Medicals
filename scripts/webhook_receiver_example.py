"""Reference webhook receiver: verifies the HMAC signature emitted by the
Drug Safety Engine outbox publisher.

Run it locally:

    WEBHOOK_SIGNING_SECRET=your-shared-secret \
        python -m scripts.webhook_receiver_example --port 9000

Then point any callback_url at ``http://localhost:9000/hooks/classifications``.

The receiver:
  * Validates ``X-Signature`` against ``HMAC_SHA256(secret, raw_body)``
  * Rejects unsigned or mismatched requests with HTTP 401
  * Logs the verified event to stdout

This mirrors the headers and signing scheme used by the platform — every
production integration should perform an equivalent check before trusting the
payload (see app/workers/outbox_publisher.py and app/core/security.py).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import sys

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger("webhook_receiver_example")

SIGNATURE_PREFIX = "sha256="


def expected_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify_signature(secret: str, body: bytes, provided: str | None) -> bool:
    if not provided or not provided.startswith(SIGNATURE_PREFIX):
        return False
    expected = expected_signature(secret, body)
    return hmac.compare_digest(expected, provided)


def build_app(secret: str) -> FastAPI:
    if not secret:
        raise ValueError(
            "WEBHOOK_SIGNING_SECRET is required — refusing to start without it"
        )

    app = FastAPI(title="Drug Safety Engine — webhook receiver example")

    @app.post("/hooks/classifications")
    async def receive_classification(
        request: Request,
        x_signature: str | None = Header(default=None, alias="X-Signature"),
        x_event_type: str | None = Header(default=None, alias="X-Event-Type"),
        x_event_id: str | None = Header(default=None, alias="X-Event-Id"),
    ) -> JSONResponse:
        body = await request.body()
        if not verify_signature(secret, body, x_signature):
            logger.warning(
                "rejected_unsigned_or_invalid",
                extra={"extra": {"event_id": x_event_id, "event_type": x_event_type}},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid signature",
            )

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="payload is not valid JSON",
            ) from exc

        logger.info(
            "verified_event",
            extra={
                "extra": {
                    "event_id": x_event_id,
                    "event_type": x_event_type,
                    "job_id": payload.get("job_id"),
                    "result_code": payload.get("result_code"),
                }
            },
        )
        return JSONResponse({"status": "ok"})

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument(
        "--secret-env",
        default="WEBHOOK_SIGNING_SECRET",
        help="env var holding the shared secret (default: WEBHOOK_SIGNING_SECRET)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    secret = os.getenv(args.secret_env, "")
    if not secret:
        sys.stderr.write(
            f"error: env var {args.secret_env} is empty — set it to the same "
            "value as the platform's WEBHOOK_SIGNING_SECRET.\n"
        )
        return 2

    try:
        import uvicorn
    except ModuleNotFoundError:  # pragma: no cover
        sys.stderr.write("uvicorn is required to run the example receiver\n")
        return 1

    app = build_app(secret)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
