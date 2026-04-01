"""MQTT client with Home Assistant auto-discovery publishing."""

import asyncio
import collections
import json
import logging
import time

import aiomqtt

from sensors import SensorDef, get_sensor_def, is_weather_param

logger = logging.getLogger(__name__)

VERSION = "0.1.0"

# Reconnection backoff: 1s, 2s, 4s, 8s, 16s, 30s, 30s, ...
MAX_RECONNECT_DELAY = 30

# Maximum queued messages during reconnection (bounded to prevent memory issues)
MAX_QUEUE_SIZE = 100


class MQTTPublisher:
    """Publishes weather data to MQTT with HA auto-discovery.

    Handles reconnection automatically. During reconnection, weather data
    is queued (bounded) so it can be published once the connection is restored.
    """

    def __init__(
        self,
        host: str,
        port: int = 1883,
        username: str = "",
        password: str = "",
        stale_timeout: int = 300,
    ):
        self._host = host
        self._port = port
        self._username = username or None
        self._password = password or None
        self._stale_timeout = stale_timeout

        self._client: aiomqtt.Client | None = None
        self._connected = False
        self._shutting_down = False
        self._reconnecting = False

        # Track which discovery configs we've already published
        self._discovered: set[str] = set()

        # Track last data time per station for availability
        self._station_last_seen: dict[str, float] = {}
        self._stale_check_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None

        # Bounded queue for data received during reconnection
        self._pending_queue: collections.deque[tuple[str, dict[str, str]]] = (
            collections.deque(maxlen=MAX_QUEUE_SIZE)
        )

    async def connect(self) -> None:
        """Connect to the MQTT broker with retry."""
        await self._do_connect()
        self._stale_check_task = asyncio.create_task(self._check_stale_stations())
        self._stale_check_task.add_done_callback(self._on_task_done)

    async def _do_connect(self) -> None:
        """Establish MQTT connection with exponential backoff."""
        self._reconnecting = True
        delay = 1
        try:
            while not self._shutting_down:
                try:
                    # Close old client if it exists (prevents resource leak on reconnect)
                    if self._client is not None:
                        try:
                            await self._client.__aexit__(None, None, None)
                        except Exception:
                            pass
                        self._client = None

                    self._client = aiomqtt.Client(
                        hostname=self._host,
                        port=self._port,
                        username=self._username,
                        password=self._password,
                    )
                    await self._client.__aenter__()
                    self._connected = True
                    # Re-publish discovery for all known sensors after reconnect
                    if self._discovered:
                        logger.info("Reconnected, re-publishing %d discovery configs", len(self._discovered))
                        self._discovered.clear()
                    else:
                        logger.info("Connected to MQTT broker at %s:%s", self._host, self._port)

                    # Drain any data queued during reconnection
                    await self._drain_queue()
                    return
                except Exception as e:
                    logger.warning(
                        "MQTT connection failed (%s), retrying in %ds...", e, delay
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, MAX_RECONNECT_DELAY)
        finally:
            self._reconnecting = False

    async def disconnect(self) -> None:
        """Publish offline for all stations and disconnect."""
        self._shutting_down = True

        if self._stale_check_task:
            self._stale_check_task.cancel()
            try:
                await self._stale_check_task
            except asyncio.CancelledError:
                pass

        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        if self._client and self._connected:
            try:
                for station_id in list(self._station_last_seen.keys()):
                    await self._publish_availability(station_id, "offline")
                await self._client.__aexit__(None, None, None)
            except Exception:
                logger.debug("Error during MQTT disconnect", exc_info=True)
            self._connected = False
            logger.info("Disconnected from MQTT broker")

    def _enqueue(self, station_id: str, params: dict[str, str]) -> None:
        """Add data to the pending queue, logging if oldest entry is evicted."""
        if len(self._pending_queue) >= MAX_QUEUE_SIZE:
            evicted_sid, _ = self._pending_queue[0]
            logger.warning(
                "Queue full (%d), dropping oldest entry for station %s",
                MAX_QUEUE_SIZE, evicted_sid,
            )
        self._pending_queue.append((station_id, params))

    def _ensure_reconnect(self) -> None:
        """Start a reconnect task if one isn't already running."""
        if not self._reconnecting and not self._shutting_down:
            self._reconnect_task = asyncio.create_task(self._do_connect())
            self._reconnect_task.add_done_callback(self._on_task_done)

    async def publish_weather_data(
        self, station_id: str, params: dict[str, str]
    ) -> None:
        """Publish weather data from a station to MQTT.

        If not connected, data is queued (bounded) for later publishing.
        Never raises — the HTTP server must never be blocked.
        """
        if not self._connected or not self._client:
            self._enqueue(station_id, params)
            logger.warning(
                "Not connected to MQTT, queued data for %s (%d in queue)",
                station_id, len(self._pending_queue),
            )
            self._ensure_reconnect()
            return

        try:
            await self._do_publish(station_id, params)
        except Exception:
            # Any exception — queue the data so it's not lost
            self._enqueue(station_id, params)
            logger.exception("Error publishing data for %s, queued for retry", station_id)

    async def _do_publish(
        self, station_id: str, params: dict[str, str]
    ) -> None:
        """Actually publish weather data to MQTT.

        Raises on MQTT errors so callers can handle retry/queuing.
        """
        sid = station_id.lower()

        try:
            # Publish availability
            self._station_last_seen[sid] = time.monotonic()
            await self._publish_availability(sid, "online")

            # Publish each weather parameter
            count = 0
            for param, value in params.items():
                if not is_weather_param(param):
                    continue
                if not value:
                    continue

                sensor_def = get_sensor_def(param)
                entity_key = f"{sid}_{param}"

                # Publish discovery config on first sight
                if entity_key not in self._discovered:
                    await self._publish_discovery(sid, param, sensor_def)
                    self._discovered.add(entity_key)

                # Publish state
                state_topic = f"wu_{sid}/{param}/state"
                await self._client.publish(state_topic, payload=value, retain=True)
                count += 1

            logger.debug("Published %d params for station %s", count, station_id)

        except aiomqtt.MqttError as e:
            logger.warning("MQTT error publishing data for %s: %s", station_id, e)
            self._connected = False
            self._ensure_reconnect()
            raise  # let caller handle queuing

    async def _drain_queue(self) -> None:
        """Publish any data queued during reconnection."""
        if not self._pending_queue:
            return
        count = len(self._pending_queue)
        logger.info("Draining %d queued messages after reconnect", count)
        while self._pending_queue:
            station_id, params = self._pending_queue[0]  # peek, don't pop yet
            try:
                await self._do_publish(station_id, params)
                self._pending_queue.popleft()  # only remove on success
            except aiomqtt.MqttError:
                # Connection lost during drain — stop, messages stay in queue
                # _do_publish already triggered reconnect
                logger.warning("Connection lost during queue drain, %d messages remain", len(self._pending_queue))
                break
            except Exception:
                # Non-MQTT error (e.g., malformed data) — skip this message
                logger.warning("Skipping undrainable message for %s", station_id, exc_info=True)
                self._pending_queue.popleft()

    @staticmethod
    def _on_task_done(task: asyncio.Task) -> None:
        """Log exceptions from background tasks."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.warning("Background task failed: %s", exc)

    async def _publish_discovery(
        self, station_id: str, param: str, sensor_def: SensorDef
    ) -> None:
        """Publish HA MQTT discovery config for a sensor."""
        config_topic = f"homeassistant/sensor/wu_{station_id}/{param}/config"

        payload: dict = {
            "name": sensor_def.name,
            "unique_id": f"wu_{station_id}_{param}",
            "state_topic": f"wu_{station_id}/{param}/state",
            "state_class": sensor_def.state_class,
            "device": {
                "identifiers": [f"wu_{station_id}"],
                "name": f"Weather Station ({station_id.upper()})",
                "manufacturer": "WU-MQTT Bridge",
                "model": "WU Protocol Bridge",
                "sw_version": VERSION,
            },
            "availability_topic": f"wu_{station_id}/availability",
            "payload_available": "online",
            "payload_not_available": "offline",
        }

        if sensor_def.device_class:
            payload["device_class"] = sensor_def.device_class
        if sensor_def.unit:
            payload["unit_of_measurement"] = sensor_def.unit
        if sensor_def.icon:
            payload["icon"] = sensor_def.icon

        await self._client.publish(
            config_topic, payload=json.dumps(payload), retain=True
        )
        logger.debug("Published discovery for %s/%s", station_id, param)

    async def _publish_availability(self, station_id: str, status: str) -> None:
        """Publish station availability status."""
        topic = f"wu_{station_id}/availability"
        await self._client.publish(topic, payload=status, retain=True)

    async def _check_stale_stations(self) -> None:
        """Periodically check for stations that haven't sent data."""
        while not self._shutting_down:
            await asyncio.sleep(60)
            if not self._connected:
                continue
            now = time.monotonic()
            stale_sids = [
                sid for sid, last_seen in self._station_last_seen.items()
                if now - last_seen > self._stale_timeout
            ]
            for sid in stale_sids:
                # Re-check in case data arrived while we were awaiting
                if self._station_last_seen.get(sid, now) > now - self._stale_timeout:
                    continue
                logger.warning(
                    "Station %s is stale (no data for %ds)",
                    sid, self._stale_timeout,
                )
                try:
                    await self._publish_availability(sid, "offline")
                except Exception:
                    logger.debug("Failed to publish offline for %s", sid, exc_info=True)
                # Final re-check: data may have arrived during the await above
                if self._station_last_seen.get(sid, 0) > now:
                    continue  # fresh data arrived, don't remove
                self._station_last_seen.pop(sid, None)
                # Clear discovery cache so sensors are re-published when station returns
                self._discovered = {
                    k for k in self._discovered if not k.startswith(f"{sid}_")
                }
