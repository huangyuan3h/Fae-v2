"""Live weather via Open-Meteo (no API key)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger("fae.tools.weather")

WEATHER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": (
                "Fetch live current weather and today's forecast for a city. "
                "Call this whenever the user asks about weather, temperature, "
                "rain, or whether to bring an umbrella. "
                "Omit city to use the user's saved City preference."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": (
                            "City name, e.g. '北京', 'Shanghai', 'Tokyo'. "
                            "Optional if the user profile has City set."
                        ),
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "Temperature unit. Default celsius.",
                    },
                },
            },
        },
    },
]

# WMO weather interpretation codes → short bilingual labels
_WMO_LABELS: dict[int, str] = {
    0: "Clear / 晴",
    1: "Mainly clear / 大部晴朗",
    2: "Partly cloudy / 多云",
    3: "Overcast / 阴",
    45: "Fog / 雾",
    48: "Depositing rime fog / 雾凇",
    51: "Light drizzle / 小毛毛雨",
    53: "Moderate drizzle / 中毛毛雨",
    55: "Dense drizzle / 大毛毛雨",
    61: "Slight rain / 小雨",
    63: "Moderate rain / 中雨",
    65: "Heavy rain / 大雨",
    71: "Slight snow / 小雪",
    73: "Moderate snow / 中雪",
    75: "Heavy snow / 大雪",
    80: "Slight rain showers / 阵雨",
    81: "Moderate rain showers / 中阵雨",
    82: "Violent rain showers / 强阵雨",
    95: "Thunderstorm / 雷暴",
    96: "Thunderstorm with slight hail / 雷暴伴冰雹",
    99: "Thunderstorm with heavy hail / 强雷暴冰雹",
}

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Heuristic: only attach get_weather when the turn looks weather-related.
_WEATHER_HINTS = (
    "天气",
    "气温",
    "温度",
    "下雨",
    "下雪",
    "伞",
    "冷不冷",
    "热不热",
    "weather",
    "temperature",
    "forecast",
    "raining",
    "rain",
    "snow",
    "umbrella",
    "humid",
)


def weather_likely(user_text: str) -> bool:
    """True when the user message likely needs live weather."""
    text = (user_text or "").strip().lower()
    if not text:
        return False
    return any(h.lower() in text for h in _WEATHER_HINTS)


def _wmo_label(code: int | None) -> str:
    if code is None:
        return "Unknown"
    return _WMO_LABELS.get(int(code), f"Code {code}")


async def geocode_city(
    city: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any] | None:
    """Resolve a city name to lat/lon via Open-Meteo geocoding."""
    name = (city or "").strip()
    if not name:
        return None
    owns = client is None
    http = client or httpx.AsyncClient(timeout=12.0)
    try:
        resp = await http.get(
            _GEOCODE_URL,
            params={"name": name, "count": 1, "language": "zh"},
        )
        resp.raise_for_status()
        results = (resp.json() or {}).get("results") or []
        if not results:
            return None
        hit = results[0]
        return {
            "name": hit.get("name") or name,
            "country": hit.get("country"),
            "admin1": hit.get("admin1"),
            "latitude": hit.get("latitude"),
            "longitude": hit.get("longitude"),
            "timezone": hit.get("timezone"),
        }
    finally:
        if owns:
            await http.aclose()


async def fetch_weather(
    city: str,
    *,
    unit: str = "celsius",
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Return a compact weather payload for the LLM."""
    name = (city or "").strip()
    if not name:
        return {"ok": False, "error": "city_required"}

    temp_unit = "fahrenheit" if unit == "fahrenheit" else "celsius"
    owns = client is None
    http = client or httpx.AsyncClient(timeout=12.0)
    try:
        place = await geocode_city(name, client=http)
        if place is None or place.get("latitude") is None:
            return {"ok": False, "error": "city_not_found", "city": name}

        params: dict[str, Any] = {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": (
                "temperature_2m,relative_humidity_2m,apparent_temperature,"
                "weather_code,wind_speed_10m,precipitation"
            ),
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max"
            ),
            "timezone": "auto",
            "forecast_days": 1,
            "temperature_unit": temp_unit,
            "wind_speed_unit": "kmh",
        }
        resp = await http.get(_FORECAST_URL, params=params)
        resp.raise_for_status()
        data = resp.json() or {}
        current = data.get("current") or {}
        daily = data.get("daily") or {}
        code = current.get("weather_code")
        daily_code = None
        codes = daily.get("weather_code") or []
        if codes:
            daily_code = codes[0]

        def _daily_first(key: str) -> Any:
            vals = daily.get(key) or []
            return vals[0] if vals else None

        return {
            "ok": True,
            "city": place["name"],
            "country": place.get("country"),
            "admin1": place.get("admin1"),
            "timezone": data.get("timezone") or place.get("timezone"),
            "unit": temp_unit,
            "current": {
                "time": current.get("time"),
                "temperature": current.get("temperature_2m"),
                "feels_like": current.get("apparent_temperature"),
                "humidity_pct": current.get("relative_humidity_2m"),
                "wind_kmh": current.get("wind_speed_10m"),
                "precipitation_mm": current.get("precipitation"),
                "condition": _wmo_label(code if isinstance(code, int) else None),
                "weather_code": code,
            },
            "today": {
                "high": _daily_first("temperature_2m_max"),
                "low": _daily_first("temperature_2m_min"),
                "precip_probability_pct": _daily_first(
                    "precipitation_probability_max"
                ),
                "condition": _wmo_label(
                    daily_code if isinstance(daily_code, int) else None
                ),
            },
            "source": "open-meteo",
        }
    except httpx.HTTPError as e:
        logger.warning("weather fetch failed city=%s err=%s", name, e)
        return {"ok": False, "error": "fetch_failed", "detail": str(e), "city": name}
    finally:
        if owns:
            await http.aclose()


async def dispatch_weather_tool(
    name: str,
    arguments: str | dict[str, Any],
    *,
    default_city: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Execute a weather tool and return a JSON string for the model."""
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            args = {}
    else:
        args = arguments or {}

    if name != "get_weather":
        return json.dumps({"ok": False, "error": f"unknown tool {name}"})

    city = str(args.get("city") or "").strip() or (default_city or "").strip()
    unit = str(args.get("unit") or "celsius").strip().lower()
    if unit not in {"celsius", "fahrenheit"}:
        unit = "celsius"
    if not city:
        return json.dumps(
            {
                "ok": False,
                "error": "city_required",
                "hint": "Ask the user which city, or save City in their profile.",
            }
        )
    result = await fetch_weather(city, unit=unit, client=client)
    return json.dumps(result, ensure_ascii=False)
