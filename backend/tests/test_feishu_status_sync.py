import asyncio

import pytest

from app.services.feishu_status_sync import (
    FeishuStatusSyncConfigurationError,
    enqueue_status_updates,
)


def test_completed_records_require_a_feishu_status_field() -> None:
    with pytest.raises(FeishuStatusSyncConfigurationError, match="status field"):
        asyncio.run(
            enqueue_status_updates(
                None,  # type: ignore[arg-type]  # configuration fails before DB access
                table_id="tbl_task",
                field_id="",
                record_ids=["rec_1"],
            )
        )
