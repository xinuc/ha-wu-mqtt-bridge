# WU-MQTT Bridge

A Home Assistant add-on that intercepts Weather Underground uploads from your personal weather station and publishes them directly to Home Assistant via MQTT — real-time, local, no cloud round-trip.

```
                          Before
Weather Station → Weather Underground cloud → HA WU integration (slow, unreliable)

                          After
Weather Station → WU-MQTT Bridge → MQTT → Home Assistant (real-time, local)
                       └──→ Weather Underground (optional, keeps cloud working)
```

Sensors appear automatically in Home Assistant with proper device classes, units, and grouping. No `configuration.yaml` editing needed.

## Prerequisites

- Home Assistant with the **Mosquitto broker** add-on (or any MQTT broker)
- A DNS server you control on your network (e.g., **AdGuard Home**, Pi-hole)
- A weather station that uploads to Weather Underground

## Installation

### Step 1: Add the repository

In Home Assistant, go to **Settings → Add-ons → Add-on Store → ⋮ (menu) → Repositories** and add:

```
https://github.com/xinuc/ha-wu-mqtt-bridge
```

Then find **WU-MQTT Bridge** in the store and click **Install**.

### Step 2: Set up DNS rewrites

Your weather station is hardcoded to send data to Weather Underground's servers. You need to redirect those hostnames to your Home Assistant machine so the add-on can intercept the data.

#### AdGuard Home

1. Open your AdGuard Home admin panel
2. Go to **Filters → DNS rewrites**
3. Add two rewrites (replace `192.168.1.100` with your Home Assistant's LAN IP):

| Domain | Answer |
|--------|--------|
| `rtupdate.wunderground.com` | `192.168.1.100` |
| `weatherstation.wunderground.com` | `192.168.1.100` |

4. Click **Save** for each entry

#### Other DNS servers

Add DNS records that point these two hostnames to your Home Assistant machine's LAN IP:

- `rtupdate.wunderground.com`
- `weatherstation.wunderground.com`

### Step 3: Start the add-on

Go to the WU-MQTT Bridge add-on page in Home Assistant and click **Start**.

That's it. Within a few seconds (or up to 5 minutes depending on your station's upload interval), sensors will appear automatically in Home Assistant under a device named **Weather Station (YOUR_STATION_ID)**.

## How it works

Weather stations upload data via HTTP/HTTPS to Weather Underground's servers. The DNS rewrite redirects those requests to your Home Assistant machine instead. The add-on:

1. Accepts the request and responds `success` (the station doesn't know anything changed)
2. Parses the weather data from the URL parameters
3. Publishes each sensor to MQTT with Home Assistant auto-discovery
4. Optionally forwards the original request to the real Weather Underground servers

The add-on listens on both **port 80** (HTTP) and **port 443** (HTTPS with a self-signed certificate) because different stations use different protocols. Most consumer stations (Ecowitt, Ambient Weather) use HTTP; some newer firmware uses HTTPS.

## Configuration

Most users don't need to change anything. MQTT is auto-discovered from the Mosquitto add-on.

| Option | Default | Description |
|--------|---------|-------------|
| MQTT Host | *(auto-discovered)* | Set only if using a non-Mosquitto MQTT broker |
| MQTT Port | *(auto-discovered)* | Set only if using a non-Mosquitto MQTT broker |
| MQTT Username | *(auto-discovered)* | Set only if using a non-Mosquitto MQTT broker |
| MQTT Password | *(auto-discovered)* | Set only if using a non-Mosquitto MQTT broker |
| Forward to WU | `true` | Keep sending data to Weather Underground |
| Log Level | `info` | Set to `debug` to see all incoming data |
| Station Timeout | `300` | Seconds without data before marking a station offline |

## Sensors

All sensors auto-appear in Home Assistant grouped under a single device. Units are published in imperial (as sent by the station) and **Home Assistant automatically converts them to your preferred unit system**.

| Sensor | WU Unit | HA converts to |
|--------|---------|----------------|
| Temperature | °F | °C (if metric) |
| Humidity | % | — |
| Dew Point | °F | °C |
| Wind Chill / Heat Index / Feels Like | °F | °C |
| Pressure | inHg | hPa, mbar |
| Wind Speed / Gust | mph | km/h, m/s |
| Wind Direction | ° | — |
| Rain Rate | in/h | mm/h |
| Daily / Weekly / Monthly / Yearly Rain | in | mm |
| Solar Radiation | W/m² | — |
| UV Index | index | — |
| Soil Temperature | °F | °C |
| Soil Moisture | % | — |
| PM2.5 / PM10 | μg/m³ | — |

Any parameter your station sends that isn't in the known list is still published as a generic sensor.

## Port conflicts

The add-on needs to listen on port 80 and/or 443 because weather stations are hardcoded to send data to these ports.

- **Tailscale add-on**: No conflict. Tailscale binds to its own network interface, not your LAN.
- **Nginx/Caddy reverse proxy**: May conflict on port 443. The add-on will still work on port 80 alone if your station uses HTTP.

The add-on requires at least one of the two ports to bind successfully.

## Troubleshooting

### No sensors appearing

1. Set Log Level to `debug` and check the add-on log for incoming data
2. Verify DNS rewrites are active: run `nslookup rtupdate.wunderground.com` from a device on your network — it should resolve to your HA IP
3. Make sure the Mosquitto add-on is running and the MQTT integration is set up in HA
4. Wait for your station's next upload cycle (can be up to 5 minutes for non-RapidFire stations)

### Station shows as offline

The station is marked offline if no data is received within the timeout period (default: 5 minutes). Check that your weather station is powered on and connected to your network.

### Port 443 already in use

If another service uses port 443, check the add-on log. If your station uses HTTP (most consumer stations do), the add-on will work fine on port 80 alone.

## License

[MIT](LICENSE)
