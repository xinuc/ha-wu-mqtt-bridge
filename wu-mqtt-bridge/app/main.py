"""WU-MQTT Bridge — main entry point.

Starts the HTTPS server, connects to MQTT, and optionally enables WU forwarding.
Handles graceful shutdown on SIGTERM/SIGINT.
"""

import asyncio
import logging
import os
import signal
import sys
import time

from forwarder import WUForwarder
from mqtt import MQTTPublisher
from server import WUServer

logger = logging.getLogger("wu-mqtt-bridge")


def _log_task_exception(task: asyncio.Task) -> None:
    """Log exceptions from fire-and-forget tasks instead of losing them."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("Background task failed: %s", exc)


def _get_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _get_env_bool(name: str, default: bool = True) -> bool:
    val = os.environ.get(name, "").lower()
    if val in ("true", "1", "yes"):
        return True
    if val in ("false", "0", "no"):
        return False
    return default


def _get_env_int(name: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(name, default))
    except (ValueError, TypeError):
        return default


def _setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


async def main() -> None:
    # Configuration from environment (set by S6 run script)
    mqtt_host = _get_env("MQTT_HOST")
    mqtt_port = _get_env_int("MQTT_PORT", 1883)
    mqtt_user = _get_env("MQTT_USER")
    mqtt_password = _get_env("MQTT_PASSWORD")
    wu_forward = _get_env_bool("WU_FORWARD", True)
    log_level = _get_env("LOG_LEVEL", "info")
    stale_timeout = _get_env_int("STALE_TIMEOUT", 300)
    publish_interval = _get_env_int("PUBLISH_INTERVAL", 60)

    _setup_logging(log_level)

    if not mqtt_host:
        logger.fatal("MQTT_HOST is not set. Cannot start.")
        sys.exit(1)

    logger.info("WU-MQTT Bridge starting...")
    logger.info("MQTT: %s:%d", mqtt_host, mqtt_port)
    logger.info("WU forwarding: %s", "enabled" if wu_forward else "disabled")
    logger.info("Publish interval: %ds", publish_interval)

    # Initialize components
    mqtt = MQTTPublisher(
        host=mqtt_host,
        port=mqtt_port,
        username=mqtt_user,
        password=mqtt_password,
        stale_timeout=stale_timeout,
    )
    forwarder = WUForwarder(enabled=wu_forward)

    # Throttling state per station
    last_dateutc: dict[str, str] = {}
    last_publish_time: dict[str, float] = {}
    pending_data: dict[str, tuple[str, dict[str, str]]] = {}
    pending_timers: dict[str, asyncio.TimerHandle] = {}

    def _publish_pending(sid: str) -> None:
        """Fire-and-forget publish of pending data when throttle window expires."""
        entry = pending_data.pop(sid, None)
        pending_timers.pop(sid, None)
        if entry is None:
            return
        station_id, params = entry
        last_publish_time[sid] = time.monotonic()
        last_dateutc[sid] = params.get("dateutc", "")
        task = asyncio.create_task(mqtt.publish_weather_data(station_id, params))
        task.add_done_callback(_log_task_exception)

    async def on_data_received(station_id: str, params: dict[str, str]) -> None:
        """Called by the HTTP server when weather data arrives.

        Deduplicates by dateutc (same data arriving multiple times).
        Throttles MQTT publishing to at most once per publish_interval,
        always keeping the latest data so the most recent reading is published.
        WU forwarding always happens regardless of throttling.
        """
        sid = station_id.lower()
        dateutc = params.get("dateutc", "")

        # Always forward to WU (fire-and-forget) — even duplicates,
        # since WU handles its own dedup and we want reliable forwarding
        task = asyncio.create_task(forwarder.forward(params))
        task.add_done_callback(_log_task_exception)

        # Dedup: skip if we already processed this exact dateutc for this station.
        # "now" is a valid WU value meaning "use server time" — not a real
        # timestamp, so it must not be used for dedup.
        if dateutc and dateutc != "now" and dateutc == last_dateutc.get(sid):
            logger.debug("Skipping duplicate for %s (dateutc=%s)", station_id, dateutc)
            return

        # No throttling — publish immediately
        if publish_interval <= 0:
            last_dateutc[sid] = dateutc
            last_publish_time[sid] = time.monotonic()
            await mqtt.publish_weather_data(station_id, params)
            return

        # Throttle: if within the window, buffer the latest data
        now = time.monotonic()
        elapsed = now - last_publish_time.get(sid, 0)
        if elapsed < publish_interval:
            # Buffer this data — overwrites any previous pending data
            # so we always publish the most recent reading
            pending_data[sid] = (station_id, params)
            # Schedule a timer to publish when the window expires (if not already scheduled)
            if sid not in pending_timers:
                delay = publish_interval - elapsed
                loop = asyncio.get_running_loop()
                pending_timers[sid] = loop.call_later(delay, _publish_pending, sid)
                logger.debug(
                    "Buffered %s (%.0fs until next publish)", station_id, delay,
                )
            else:
                logger.debug("Updated buffered data for %s", station_id)
            return

        # Outside throttle window — publish immediately
        last_dateutc[sid] = dateutc
        last_publish_time[sid] = now
        await mqtt.publish_weather_data(station_id, params)

    server = WUServer(on_data_received=on_data_received)

    # Shutdown handling
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    # Start everything
    try:
        await mqtt.connect()
        await forwarder.start()
        await server.start()

        logger.info("WU-MQTT Bridge is running")

        # Wait for shutdown signal
        await shutdown_event.wait()

    except Exception:
        logger.exception("Fatal error during startup")
        sys.exit(1)
    finally:
        # Graceful shutdown
        logger.info("Shutting down...")
        await server.stop()
        await forwarder.stop()
        await mqtt.disconnect()
        logger.info("WU-MQTT Bridge stopped")


if __name__ == "__main__":
    asyncio.run(main())
