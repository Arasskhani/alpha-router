"""Video billing settle path."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.video_billing_service import VideoBillingCapture, log_video_usage


def test_log_video_usage_calls_log_usage():
    user = SimpleNamespace(id=1, username="tester")
    capture = VideoBillingCapture(model_id="google/veo-3.1-lite", provider_type="openrouter")
    capture.add_usage({"id": "job-1"}, success=True, quantity=4.0, unit="second")
    db = AsyncMock()

    with patch("app.services.video_billing_service.log_usage", new_callable=AsyncMock) as mocked:
        asyncio.run(
            log_video_usage(
                db,
                user=user,
                capture=capture,
                prompt="sunrise",
                response_time_ms=1200.0,
                success=True,
                operation="generation",
                budget_reservation_id="res-1",
                duration_seconds=4,
            )
        )
        mocked.assert_awaited_once()
        kwargs = mocked.await_args.kwargs
        assert kwargs["operation_type"] == "video"
        assert kwargs["success"] is True
        assert kwargs["budget_reservation_id"] == "res-1"
