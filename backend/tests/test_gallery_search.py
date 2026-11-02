from datetime import UTC, datetime

import pytest

from app.api.feishu import _archive_photo_name
from app.services import dashboard_repository


class FakeConnection:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.query = ""
        self.values: tuple[object, ...] = ()
        self.rows = rows or []
        self.queries: list[str] = []

    async def fetch(self, query: str, *values: object) -> list[object]:
        self.query = query
        self.values = values
        self.queries.append(query)
        return self.rows

    async def fetchrow(self, query: str, *values: object) -> dict[str, str]:
        self.query = query
        self.values = values
        return {"object_key": "orders/photo.jpg"}

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_shared_gallery_searches_all_visible_photos_by_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(dashboard_repository.asyncpg, "connect", lambda _: _connection(connection))

    await dashboard_repository.inspector_photos("user-id", scope="shared", search="法兰 材质光谱")

    assert "WHERE TRUE" in connection.query
    assert "p.photographer_open_id = u.open_id" not in connection.query
    assert connection.values == ("user-id", "法兰", "材质光谱")


@pytest.mark.asyncio
async def test_shared_photo_asset_still_requires_an_authenticated_local_user(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(dashboard_repository.asyncpg, "connect", lambda _: _connection(connection))

    key = await dashboard_repository.photo_object_for_user("user-id", "photo-id", preview=False, scope="shared")

    assert key == "orders/photo.jpg"
    assert "JOIN users u ON u.id = $1::uuid" in connection.query
    assert connection.values == ("user-id", "photo-id", "shared")


@pytest.mark.asyncio
async def test_gallery_date_filter_uses_shanghai_time_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(dashboard_repository.asyncpg, "connect", lambda _: _connection(connection))

    await dashboard_repository.inspector_photos(
        "user-id", captured_from="2026-08-01", captured_to="2026-08-16",
    )

    start, end = connection.values[1:]
    assert start == datetime.fromisoformat("2026-08-01T00:00:00+08:00")
    assert end == datetime.fromisoformat("2026-08-17T00:00:00+08:00")
    assert "p.captured_at >= $2" in connection.query
    assert "p.captured_at < $3" in connection.query


@pytest.mark.asyncio
async def test_gallery_rejects_invalid_or_reversed_date_ranges() -> None:
    with pytest.raises(ValueError, match="Invalid captured_from date"):
        await dashboard_repository.inspector_photos("user-id", captured_from="2026-02-30")
    with pytest.raises(ValueError, match="cannot be later"):
        await dashboard_repository.inspector_photos(
            "user-id", captured_from="2026-08-16", captured_to="2026-08-01",
        )


@pytest.mark.asyncio
async def test_gallery_returns_one_fifty_photo_page_with_total_count(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(dashboard_repository.asyncpg, "connect", lambda _: _connection(connection))

    photos, total = await dashboard_repository.inspector_photos("user-id", page=3, page_size=50)

    assert photos == []
    assert total == 0
    assert "SELECT COUNT(*)::int AS count" in connection.queries[0]
    assert "LIMIT 50 OFFSET 100" in connection.queries[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("page_size", [200, 500, 1000])
async def test_gallery_accepts_expanded_page_sizes(monkeypatch: pytest.MonkeyPatch, page_size: int) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(dashboard_repository.asyncpg, "connect", lambda _: _connection(connection))
    await dashboard_repository.inspector_photos("user-id", page=2, page_size=page_size)
    assert f"LIMIT {page_size} OFFSET {page_size}" in connection.queries[1]


@pytest.mark.asyncio
async def test_gallery_rejects_page_sizes_above_one_thousand() -> None:
    with pytest.raises(ValueError, match="between 1 and 1000"):
        await dashboard_repository.inspector_photos("user-id", page_size=1001)


@pytest.mark.asyncio
async def test_batch_download_resolves_unwatermarked_originals_in_selection_order(monkeypatch: pytest.MonkeyPatch) -> None:
    first_id = "00000000-0000-0000-0000-000000000001"
    second_id = "00000000-0000-0000-0000-000000000002"
    rows = [
        {"id": second_id, "object_key": "photos/2-original.jpg", "contract_no": "C2", "inspection_item": "尺寸"},
        {"id": first_id, "object_key": "photos/1-original.jpg", "contract_no": "C1", "inspection_item": "材质光谱"},
    ]
    connection = FakeConnection(rows)
    monkeypatch.setattr(dashboard_repository.asyncpg, "connect", lambda _: _connection(connection))

    documents = await dashboard_repository.photo_downloads_for_user(
        "user-id", [second_id, first_id], scope="shared", watermarked=False,
    )

    assert "p.original_oss_object_key" in connection.query
    assert [document["id"] for document in documents] == [second_id, first_id]
    assert documents[0]["object_key"] == "photos/2-original.jpg"


def test_batch_download_filename_cannot_escape_archive_directory() -> None:
    filename = _archive_photo_name(
        {
            "id": "../../photo-1",
            "contract_no": "C/1",
            "product_type": "法兰",
            "specification": "DN50",
            "inspection_item": "尺寸",
            "captured_at": datetime(2026, 11, 1, 10, 36, tzinfo=UTC),
        },
    )

    assert "/" not in filename
    assert not filename.startswith(".")
    assert filename.endswith(".jpg")


async def _connection(connection: FakeConnection) -> FakeConnection:
    return connection
