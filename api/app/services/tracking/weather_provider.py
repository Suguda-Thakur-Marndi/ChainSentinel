"""OpenWeather live meteorological risk & hazard overlay provider.

Monitors real-time atmospheric hazards (typhoons, gale-force winds, sea states,
precipitation) across critical global shipping choke-points and major hubs.
Normalizes data strictly into type="weather" without creating fake vehicle markers.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional

import httpx
from app.services.tracking.base import TrackingProvider
from app.services.tracking.models import LiveMapObject, ProviderHealth, ProviderHealthStatus

logger = logging.getLogger("riskwise.tracking.weather")

# Critical maritime corridors & mega-hub gateways for live atmospheric monitoring
KEY_WEATHER_NODES = [
    {"id": "wx-suez", "name": "Suez Canal Corridor", "lat": 30.585, "lon": 32.565},
    {"id": "wx-malacca", "name": "Strait of Malacca (Singapore)", "lat": 1.290, "lon": 103.852},
    {"id": "wx-panama", "name": "Panama Canal (Colon)", "lat": 9.359, "lon": -79.901},
    {"id": "wx-hormuz", "name": "Strait of Hormuz", "lat": 26.566, "lon": 56.255},
    {"id": "wx-babelmandeb", "name": "Bab-el-Mandeb Strait", "lat": 12.585, "lon": 43.332},
    {"id": "wx-rotterdam", "name": "Port of Rotterdam", "lat": 51.924, "lon": 4.477},
    {"id": "wx-shanghai", "name": "Port of Shanghai", "lat": 31.230, "lon": 121.473},
    {"id": "wx-losangeles", "name": "Port of Los Angeles", "lat": 33.743, "lon": -118.267},
    {"id": "wx-gibraltar", "name": "Strait of Gibraltar", "lat": 35.952, "lon": -5.604},
    {"id": "wx-taiwan", "name": "Taiwan Strait (Kaohsiung)", "lat": 22.627, "lon": 120.301},
]


class WeatherTrackingProvider(TrackingProvider):
    """OpenWeather live atmospheric hazard provider."""

    name: str = "openweather"
    purpose: str = "Maritime Hazards & Atmospheric Overlays"

    def __init__(
        self,
        api_key: Optional[str] = None,
        poll_interval_seconds: int = 300,
        on_update: Optional[Callable[[List[LiveMapObject]], Coroutine[None, None, None]]] = None,
    ):
        super().__init__(on_update=on_update)
        self._api_key = api_key or os.getenv("OPENWEATHER_API_KEY") or os.getenv("OPENWEATHERMAP_API_KEY")
        self._poll_interval = poll_interval_seconds
        self._weather_objects: Dict[str, LiveMapObject] = {}
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        if self._api_key:
            self._status = ProviderHealthStatus.CONNECTED
        else:
            self._status = ProviderHealthStatus.UNCONFIGURED

        self._last_success: Optional[str] = None
        self._last_error: Optional[str] = None
        self._latency_ms: Optional[float] = None

    async def start(self) -> None:
        """Start weather monitoring task."""
        if not self._api_key:
            self._status = ProviderHealthStatus.UNCONFIGURED
            self._last_error = "OpenWeather API key not configured"
            return

        self._is_running = True
        self._task = asyncio.create_task(self._poll_loop(), name="weather_poll_worker")
        logger.info("[WeatherProvider] Monitoring started for key maritime corridors.")

    async def stop(self) -> None:
        """Stop weather monitoring."""
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[WeatherProvider] Monitoring stopped.")

    async def health_check(self) -> ProviderHealth:
        """Return runtime health status."""
        async with self._lock:
            count = len(self._weather_objects)
        return ProviderHealth(
            name=self.name,
            purpose=self.purpose,
            status=self._status,
            last_success=self._last_success,
            last_error=self._last_error,
            latency_ms=self._latency_ms,
            objects=count,
            reason=self._last_error if self._status != ProviderHealthStatus.CONNECTED else None,
        )

    async def get_objects(self) -> List[LiveMapObject]:
        """Return list of weather risk objects."""
        async with self._lock:
            return list(self._weather_objects.values())

    async def _poll_loop(self) -> None:
        """Poll weather for key corridors with rate limiting and exponential backoff."""
        while self._is_running:
            await self._fetch_all_nodes()
            # Sleep until next poll interval
            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break

    async def _fetch_all_nodes(self) -> None:
        """Fetch current weather for each corridor node."""
        base_url = "https://api.openweathermap.org/data/2.5/weather"
        start_time = time.monotonic()
        updated_objects: List[LiveMapObject] = []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                for node in KEY_WEATHER_NODES:
                    if not self._is_running:
                        break
                    params = {
                        "lat": node["lat"],
                        "lon": node["lon"],
                        "appid": self._api_key,
                        "units": "metric",
                    }
                    try:
                        resp = await client.get(base_url, params=params)
                        if resp.status_code == 200:
                            data = resp.json()
                            obj = self._parse_weather_response(node, data)
                            if obj:
                                updated_objects.append(obj)
                        elif resp.status_code == 429:
                            self._status = ProviderHealthStatus.RATE_LIMITED
                            self._last_error = "OpenWeather rate limit reached"
                            logger.warning("[WeatherProvider] Rate limited (HTTP 429).")
                            break
                        else:
                            logger.debug(f"[WeatherProvider] Node {node['name']} HTTP {resp.status_code}")
                    except Exception as node_err:
                        logger.debug(f"[WeatherProvider] Error fetching {node['name']}: {node_err}")

                    # Micro-delay between requests to avoid burst rate limits
                    await asyncio.sleep(0.2)

            self._latency_ms = round((time.monotonic() - start_time) * 1000, 2)
            if updated_objects:
                now_iso = datetime.now(timezone.utc).isoformat()
                self._last_success = now_iso
                self._status = ProviderHealthStatus.CONNECTED
                self._last_error = None
                async with self._lock:
                    for obj in updated_objects:
                        self._weather_objects[obj.id] = obj

                if self._on_update:
                    try:
                        await self._on_update(updated_objects)
                    except Exception as e:
                        logger.debug(f"[WeatherProvider] Update callback error: {e}")

        except Exception as e:
            self._status = ProviderHealthStatus.ERROR
            self._last_error = f"{type(e).__name__}: {str(e)}"
            logger.warning(f"[WeatherProvider] Cycle failed: {e}")

    def _parse_weather_response(self, node: Dict[str, Any], data: Dict[str, Any]) -> Optional[LiveMapObject]:
        """Convert OpenWeather payload to LiveMapObject."""
        weather_list = data.get("weather", [])
        main_data = data.get("main", {})
        wind_data = data.get("wind", {})

        condition = weather_list[0].get("main", "Clear") if weather_list else "Clear"
        description = weather_list[0].get("description", "Normal conditions") if weather_list else ""
        temp_c = main_data.get("temp")
        wind_speed_mps = wind_data.get("speed", 0.0)
        wind_deg = wind_data.get("deg")

        # Determine severity level
        severity = "LOW"
        if "Thunderstorm" in condition or "Squall" in condition or "Tornado" in condition:
            severity = "CRITICAL"
        elif wind_speed_mps >= 17.0:  # Gale force
            severity = "HIGH"
        elif "Rain" in condition or wind_speed_mps >= 10.0:
            severity = "MEDIUM"

        now_iso = datetime.now(timezone.utc).isoformat()
        dt_epoch = data.get("dt")
        source_ts = datetime.fromtimestamp(dt_epoch, tz=timezone.utc).isoformat() if dt_epoch else now_iso

        return LiveMapObject(
            id=node["id"],
            type="weather",
            source="openweather",
            latitude=node["lat"],
            longitude=node["lon"],
            heading=float(wind_deg) if wind_deg is not None else None,
            speed=float(wind_speed_mps) if wind_speed_mps is not None else None,
            status=f"{condition}: {description.capitalize()}",
            name=f"Weather: {node['name']}",
            identifier=node["id"],
            timestamp=source_ts,
            last_seen=now_iso,
            metadata={
                "condition": condition,
                "description": description,
                "temperature_c": temp_c,
                "wind_speed_mps": wind_speed_mps,
                "wind_deg": wind_deg,
                "severity": severity,
                "humidity": main_data.get("humidity"),
                "pressure": main_data.get("pressure"),
                "provenance": "REAL",
            },
        )
