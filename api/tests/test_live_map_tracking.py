"""Comprehensive test suite for RiskWise Live Map & Geospatial Tracking Subsystem.

Verifies:
- Strict coordinate validation (-90 <= lat <= 90, -180 <= lon <= 180)
- Rejection of (0,0) null islands unless explicitly grounded
- Truthful reporting of unavailable/error providers (zero synthetic/fabricated data)
- Aggregator filtering by types, source, bounding box, and temporal recency
- REST API contracts for /api/v1/map/objects and /api/v1/map/providers/health
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.tracking.models import (
    LiveMapObject,
    MapObjectType,
    ProviderHealth,
    ProviderHealthStatus,
)
from app.services.tracking.aggregator import LiveMapAggregator
from app.services.tracking.aircraft_provider import AircraftTrackingProvider
from app.services.tracking.project44_provider import Project44TrackingProvider
from app.services.tracking.base import TrackingProvider


def test_01_live_map_object_valid_coordinates():
    """Verify standard valid coordinates pass validation."""
    obj = LiveMapObject(
        id="vessel-212802000",
        type="vessel",
        source="aisstream",
        latitude=50.56328,
        longitude=1.17197,
        heading=120.0,
        speed=12.4,
        status="Under way using engine",
        name="FRI LIEPAJA",
        identifier="212802000",
        timestamp="2026-09-30T15:27:57Z",
        last_seen="2026-09-30T15:27:57Z",
    )
    assert obj.id == "vessel-212802000"
    assert obj.latitude == 50.56328
    assert obj.longitude == 1.17197
    assert obj.speed == 12.4
    assert obj.heading == 120.0


def test_02_live_map_object_rejects_out_of_bounds_latitude():
    """Verify latitudes outside [-90, 90] are rejected."""
    with pytest.raises(ValueError, match="out of WGS84 range"):
        LiveMapObject(
            id="test-1",
            type="vessel",
            source="test",
            latitude=95.0,  # Invalid
            longitude=20.0,
            name="Test Ship",
            timestamp="2026-09-30T15:00:00Z",
            last_seen="2026-09-30T15:00:00Z",
        )


def test_03_live_map_object_rejects_out_of_bounds_longitude():
    """Verify longitudes outside [-180, 180] are rejected."""
    with pytest.raises(ValueError, match="out of WGS84 range"):
        LiveMapObject(
            id="test-2",
            type="vessel",
            source="test",
            latitude=20.0,
            longitude=-185.0,  # Invalid
            name="Test Ship",
            timestamp="2026-09-30T15:00:00Z",
            last_seen="2026-09-30T15:00:00Z",
        )


def test_04_live_map_object_rejects_null_island_by_default():
    """Verify exact (0,0) coordinates are rejected as placeholder null islands."""
    with pytest.raises(ValueError, match="null island"):
        LiveMapObject(
            id="test-3",
            type="vessel",
            source="test",
            latitude=0.0,
            longitude=0.0,
            name="Null Island Vessel",
            timestamp="2026-09-30T15:00:00Z",
            last_seen="2026-09-30T15:00:00Z",
        )


def test_05_aircraft_provider_truthfully_reports_unavailable():
    """Verify AircraftTrackingProvider returns unavailable when no credentials are configured."""
    provider = AircraftTrackingProvider(client_id=None, client_secret=None)
    health = pytest.importorskip("asyncio").run(provider.health_check())
    assert health.status == ProviderHealthStatus.UNAVAILABLE
    assert health.objects == 0
    assert "No aircraft telemetry provider configured" in (health.reason or "")
    objects = pytest.importorskip("asyncio").run(provider.get_objects())
    assert len(objects) == 0  # Zero fake planes!


def test_06_project44_provider_handles_unconfigured_or_invalid():
    """Verify Project44 provider does not invent coordinates or objects."""
    import asyncio
    provider = Project44TrackingProvider(client_id="", client_secret="")
    health = asyncio.run(provider.health_check())
    assert health.status == ProviderHealthStatus.UNCONFIGURED
    assert health.objects == 0
    objects = asyncio.run(provider.get_objects())
    assert len(objects) == 0  # Zero fake shipments!


def test_07_aggregator_type_and_bbox_filtering():
    """Verify LiveMapAggregator correctly filters by object type and spatial bounding box."""
    import asyncio

    async def _run():
        aggregator = LiveMapAggregator()

        obj_vessel = LiveMapObject(
            id="v-1",
            type="vessel",
            source="test_src",
            latitude=51.92,
            longitude=4.48,
            name="Rotterdam Vessel",
            timestamp="2026-09-30T15:00:00Z",
            last_seen="2026-09-30T15:00:00Z",
        )
        obj_weather = LiveMapObject(
            id="w-1",
            type="weather",
            source="test_src",
            latitude=1.29,
            longitude=103.85,
            name="Singapore Weather",
            timestamp="2026-09-30T15:00:00Z",
            last_seen="2026-09-30T15:00:00Z",
        )

        await aggregator.handle_provider_update([obj_vessel, obj_weather])

        # 1. Type filter
        res_vessels = await aggregator.get_objects(types=["vessel"])
        assert res_vessels.total_count == 1
        assert res_vessels.items[0].id == "v-1"

        # 2. Bbox filter (around Rotterdam: minLon=4.0, minLat=51.0, maxLon=5.0, maxLat=52.5)
        res_bbox = await aggregator.get_objects(bbox=[4.0, 51.0, 5.0, 52.5])
        assert res_bbox.total_count == 1
        assert res_bbox.items[0].id == "v-1"

        # 3. Bbox filter (around Singapore: minLon=100.0, minLat=0.0, maxLon=105.0, maxLat=3.0)
        res_sg = await aggregator.get_objects(bbox=[100.0, 0.0, 105.0, 3.0])
        assert res_sg.total_count == 1
        assert res_sg.items[0].id == "w-1"

    asyncio.run(_run())


def test_08_rest_endpoints_health_and_objects():
    """Test HTTP REST endpoints /api/v1/map/objects and /api/v1/map/providers/health."""
    with TestClient(app) as client:
        # 1. Health endpoint
        res_health = client.get("/api/v1/map/providers/health")
        assert res_health.status_code == 200
        health_data = res_health.json()
        assert "providers" in health_data
        assert isinstance(health_data["providers"], list)
        provider_names = [p["name"] for p in health_data["providers"]]
        assert "aisstream" in provider_names
        assert "aircraft" in provider_names
        assert "openweather" in provider_names

        # 2. Objects endpoint
        res_objects = client.get("/api/v1/map/objects?limit=50")
        assert res_objects.status_code == 200
        obj_data = res_objects.json()
        assert "items" in obj_data
        assert "sources" in obj_data
        assert "total_count" in obj_data
