from datetime import datetime

import pytest

from app.services import dashboard_repository


class FakeConnection:
    def __init__(self) -> None:
        self.query = ""
        self.values: tuple[object, ...] = ()

    async def fetch(self, query: str, *values: object) -> list[object]:
        self.query = query
        self.values = values
        return []

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


async def _connection(connection: FakeConnection) -> FakeConnection:
    return connection
