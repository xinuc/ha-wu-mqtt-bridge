"""WU-MQTT Bridge — main entry point.

Starts the HTTPS server, connects to MQTT, and optionally enables WU forwarding.
Handles graceful shutdown on SIGTERM/SIGINT.
"""

import asyncio
import logging
import os
import signal
import sys

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

    _setup_logging(log_level)

    if not mqtt_host:
        logger.fatal("MQTT_HOST is not set. Cannot start.")
        sys.exit(1)

    logger.info("WU-MQTT Bridge starting...")
    logger.info("MQTT: %s:%d", mqtt_host, mqtt_port)
    logger.info("WU forwarding: %s", "enabled" if wu_forward else "disabled")

    # Initialize components
    mqtt = MQTTPublisher(
        host=mqtt_host,
        port=mqtt_port,
        username=mqtt_user,
        password=mqtt_password,
        stale_timeout=stale_timeout,
    )
    forwarder = WUForwarder(enabled=wu_forward)

    async def on_data_received(station_id: str, params: dict[str, str]) -> None:
        """Called by the HTTP server when weather data arrives."""
        await mqtt.publish_weather_data(station_id, params)
        # Forward in background — don't await, don't block
        task = asyncio.create_task(forwarder.forward(params))
        task.add_done_callback(_log_task_exception)

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
