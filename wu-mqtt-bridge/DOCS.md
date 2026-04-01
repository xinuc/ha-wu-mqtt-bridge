# WU-MQTT Bridge

Intercepts Weather Underground uploads from your personal weather station and publishes the data to Home Assistant via MQTT. Sensors appear automatically — no configuration.yaml editing needed.

## How it works

Your weather station sends data to Weather Underground via HTTP. This add-on intercepts those requests (using a DNS override) and publishes the data to your MQTT broker. Home Assistant auto-discovers the sensors.

Optionally, the add-on also forwards the data to the real Weather Underground servers so your cloud account keeps working.

```
Weather Station → [DNS Override] → WU-MQTT Bridge → MQTT → Home Assistant
                                        └──→ Weather Underground (optional)
```

## Setup

### 1. Install the add-on

Add this repository to your Home Assistant add-on store and install WU-MQTT Bridge.

### 2. Add DNS rewrites

In your DNS server (AdGuard Home, Pi-hole, etc.), add these rewrites pointing to your Home Assistant machine's LAN IP:

| Domain | Answer |
|--------|--------|
| `rtupdate.wunderground.com` | Your HA LAN IP (e.g., `192.168.1.100`) |
| `weatherstation.wunderground.com` | Your HA LAN IP (e.g., `192.168.1.100`) |

**AdGuard Home**: Settings → DNS rewrites → Add DNS rewrite

**Pi-hole**: Local DNS → DNS Records

### 3. Start the add-on

That's it. If you have the Mosquitto add-on installed, MQTT is auto-discovered. Sensors will appear in Home Assistant as your weather station sends its next update.

## Configuration

All settings have sensible defaults. Most users don't need to change anything.

### MQTT Connection

MQTT is auto-discovered from the Mosquitto add-on. If you use a different MQTT broker, set these options:

- **MQTT Host**: Broker hostname or IP
- **MQTT Port**: Broker port (default: 1883)
- **MQTT Username**: Broker username
- **MQTT Password**: Broker password

### Options

- **Forward to Weather Underground** (default: on): Keep sending data to WU so cloud features still work.
- **Log Level** (default: info): Set to `debug` to see all incoming weather data.
- **Station Timeout** (default: 300 seconds): Time without data before a station is marked offline in HA.

## Port 443 conflicts

This add-on listens on port 443 (HTTPS) because weather stations are hardcoded to send to that port. If something else on your HA machine uses port 443:

- **Tailscale add-on**: No conflict — Tailscale binds to its own interface, not the LAN.
- **Nginx/Caddy reverse proxy**: You'll need to route WU hostnames to this add-on.

The add-on also listens on port 80 (HTTP) for stations that use the standard (non-RapidFire) endpoint.

## Sensors

Sensors auto-appear in Home Assistant grouped under a device named "Weather Station (STATION_ID)". Common sensors include:

| Sensor | Unit |
|--------|------|
| Temperature | °F (HA converts to your preferred unit) |
| Humidity | % |
| Dew Point | °F |
| Pressure | inHg |
| Wind Speed | mph |
| Wind Direction | ° |
| Wind Gust | mph |
| Rain Rate | in/h |
| Daily Rain | in |
| Solar Radiation | W/m² |
| UV Index | UV index |

Units are published as-is from the weather station (imperial). Home Assistant automatically converts them to your preferred unit system.

Any sensor your station sends that isn't in the known list is still published as a generic sensor.

## Troubleshooting

### No sensors appearing

1. Check the add-on log for incoming data (set Log Level to `debug`)
2. Verify DNS rewrites are working: the weather station should be sending data to your HA IP, not the real WU servers
3. Make sure the Mosquitto add-on is running and the MQTT integration is configured in HA

### Station shows as offline

The station is marked offline if no data is received within the timeout period (default: 5 minutes). Check that your weather station is powered on and connected to your network.
