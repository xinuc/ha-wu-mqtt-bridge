"""WU parameter to Home Assistant sensor mapping."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SensorDef:
    """Definition for mapping a WU parameter to an HA sensor."""

    name: str
    device_class: str | None = None
    unit: str | None = None
    state_class: str = "measurement"
    icon: str | None = None


# Parameters that are not weather data (excluded from sensor publishing)
NON_WEATHER_PARAMS = frozenset({
    "ID",
    "PASSWORD",
    "action",
    "dateutc",
    "realtime",
    "rtfreq",
    "softwaretype",
})

# Known WU parameters mapped to HA sensor definitions.
# Any parameter NOT in this map is still published as a generic sensor.
SENSOR_MAP: dict[str, SensorDef] = {
    # Temperature & Humidity
    "tempf": SensorDef("Temperature", "temperature", "°F"),
    "humidity": SensorDef("Humidity", "humidity", "%"),
    "dewptf": SensorDef("Dew Point", "temperature", "°F"),
    "indoortempf": SensorDef("Indoor Temperature", "temperature", "°F"),
    "indoorhumidity": SensorDef("Indoor Humidity", "humidity", "%"),
    # Additional temp sensors (some stations have up to 10)
    "temp2f": SensorDef("Temperature 2", "temperature", "°F"),
    "temp3f": SensorDef("Temperature 3", "temperature", "°F"),
    "temp4f": SensorDef("Temperature 4", "temperature", "°F"),
    "temp5f": SensorDef("Temperature 5", "temperature", "°F"),
    "temp6f": SensorDef("Temperature 6", "temperature", "°F"),
    "temp7f": SensorDef("Temperature 7", "temperature", "°F"),
    "temp8f": SensorDef("Temperature 8", "temperature", "°F"),
    "temp9f": SensorDef("Temperature 9", "temperature", "°F"),
    "temp10f": SensorDef("Temperature 10", "temperature", "°F"),
    "windchillf": SensorDef("Wind Chill", "temperature", "°F"),
    "heatindexf": SensorDef("Heat Index", "temperature", "°F"),
    "feelslikef": SensorDef("Feels Like", "temperature", "°F"),
    # Wind
    "windspeedmph": SensorDef("Wind Speed", "wind_speed", "mph"),
    "winddir": SensorDef("Wind Direction", "wind_direction", "°"),
    "windgustmph": SensorDef("Wind Gust", "wind_speed", "mph"),
    "windgustdir": SensorDef("Wind Gust Direction", "wind_direction", "°"),
    "windspdmph_avg2m": SensorDef("Wind Speed Avg 2m", "wind_speed", "mph"),
    "winddir_avg2m": SensorDef("Wind Direction Avg 2m", "wind_direction", "°"),
    "windgustmph_10m": SensorDef("Wind Gust 10m", "wind_speed", "mph"),
    "windgustdir_10m": SensorDef("Wind Gust Dir 10m", "wind_direction", "°"),
    # Precipitation
    "rainin": SensorDef("Rain Rate", "precipitation_intensity", "in/h"),
    "dailyrainin": SensorDef("Daily Rain", "precipitation", "in", state_class="total_increasing"),
    "weeklyrainin": SensorDef("Weekly Rain", "precipitation", "in", state_class="total_increasing"),
    "monthlyrainin": SensorDef("Monthly Rain", "precipitation", "in", state_class="total_increasing"),
    "yearlyrainin": SensorDef("Yearly Rain", "precipitation", "in", state_class="total_increasing"),
    # Pressure
    "baromin": SensorDef("Pressure", "atmospheric_pressure", "inHg"),
    "absbaromin": SensorDef("Absolute Pressure", "atmospheric_pressure", "inHg"),
    # Solar & UV
    "solarradiation": SensorDef("Solar Radiation", "irradiance", "W/m²"),
    "UV": SensorDef("UV Index", None, "UV index", icon="mdi:sun-wireless"),
    # Soil sensors (up to 4)
    "soiltempf": SensorDef("Soil Temperature", "temperature", "°F"),
    "soiltemp2f": SensorDef("Soil Temperature 2", "temperature", "°F"),
    "soiltemp3f": SensorDef("Soil Temperature 3", "temperature", "°F"),
    "soiltemp4f": SensorDef("Soil Temperature 4", "temperature", "°F"),
    "soilmoisture": SensorDef("Soil Moisture", "moisture", "%"),
    "soilmoisture2": SensorDef("Soil Moisture 2", "moisture", "%"),
    "soilmoisture3": SensorDef("Soil Moisture 3", "moisture", "%"),
    "soilmoisture4": SensorDef("Soil Moisture 4", "moisture", "%"),
    # Leaf sensors
    "leafwetness": SensorDef("Leaf Wetness", "moisture", "%"),
    "leafwetness2": SensorDef("Leaf Wetness 2", "moisture", "%"),
    # Air quality
    "AqPM2.5": SensorDef("PM2.5", "pm25", "μg/m³"),
    "AqPM10": SensorDef("PM10", "pm10", "μg/m³"),
}


def get_sensor_def(param: str) -> SensorDef:
    """Get the sensor definition for a WU parameter.

    Returns a known definition if available, otherwise creates a generic one
    using the parameter name as the sensor name.
    """
    if param in SENSOR_MAP:
        return SENSOR_MAP[param]
    # Generic sensor for unknown parameters
    return SensorDef(name=param, icon="mdi:weather-cloudy")


def is_weather_param(param: str) -> bool:
    """Check if a parameter is weather data (not metadata)."""
    return param not in NON_WEATHER_PARAMS
