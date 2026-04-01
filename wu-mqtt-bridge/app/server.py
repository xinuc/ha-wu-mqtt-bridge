"""HTTPS server that accepts Weather Underground protocol uploads."""

import asyncio
import logging
import os
import ssl
from pathlib import Path

from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

CERT_DIR = Path("/data/certs")
CERT_FILE = CERT_DIR / "cert.pem"
KEY_FILE = CERT_DIR / "key.pem"


def _generate_self_signed_cert() -> tuple[Path, Path]:
    """Generate a self-signed TLS certificate if one doesn't exist."""
    if CERT_FILE.exists() and KEY_FILE.exists():
        logger.info("Using existing TLS certificate")
        return CERT_FILE, KEY_FILE

    logger.info("Generating self-signed TLS certificate...")
    CERT_DIR.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WU-MQTT Bridge")])
    now = datetime.now(timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("rtupdate.wunderground.com"),
                x509.DNSName("weatherstation.wunderground.com"),
                x509.DNSName("localhost"),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    KEY_FILE.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    os.chmod(KEY_FILE, 0o600)
    CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    logger.info("TLS certificate generated")
    return CERT_FILE, KEY_FILE


def create_ssl_context() -> ssl.SSLContext:
    """Create an SSL context with the self-signed certificate."""
    cert_file, key_file = _generate_self_signed_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert_file), str(key_file))
    return ctx


class WUServer:
    """HTTP/HTTPS server that accepts WU protocol uploads."""

    def __init__(self, on_data_received):
        """Initialize the server.

        Args:
            on_data_received: async callback(station_id: str, params: dict[str, str])
                called for each valid weather data upload.
        """
        self._on_data_received = on_data_received
        self._app = web.Application()
        self._app.router.add_get(
            "/weatherstation/updateweatherstation.php", self._handle_wu_upload
        )
        # Some stations POST instead of GET
        self._app.router.add_post(
            "/weatherstation/updateweatherstation.php", self._handle_wu_upload
        )
        # Catch-all for health checks / unknown paths
        self._app.router.add_route("*", "/{path:.*}", self._handle_catchall)

        self._runners: list[web.AppRunner] = []
        # Hold references to background tasks to prevent GC
        self._background_tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        """Start both HTTPS (443) and HTTP (80) servers.

        At least one listener must bind successfully, or startup fails.
        Many cheap stations use HTTP (port 80), while others use HTTPS (443).
        """
        runner = web.AppRunner(self._app)
        await runner.setup()
        self._runners.append(runner)

        listeners = 0

        # HTTPS on 443
        try:
            ssl_ctx = create_ssl_context()
            https_site = web.TCPSite(runner, "0.0.0.0", 443, ssl_context=ssl_ctx)
            await https_site.start()
            logger.info("HTTPS server listening on port 443")
            listeners += 1
        except OSError as e:
            logger.error("Failed to start HTTPS on 443: %s", e)

        # HTTP on 80 (many stations use plain HTTP)
        try:
            http_site = web.TCPSite(runner, "0.0.0.0", 80)
            await http_site.start()
            logger.info("HTTP server listening on port 80")
            listeners += 1
        except OSError as e:
            logger.error("Failed to start HTTP on 80: %s", e)

        if listeners == 0:
            raise RuntimeError(
                "Could not bind to port 443 or 80. "
                "Check if another service is using these ports."
            )

    async def stop(self) -> None:
        """Stop the server."""
        for runner in self._runners:
            await runner.cleanup()
        logger.info("Server stopped")

    async def _handle_wu_upload(self, request: web.Request) -> web.Response:
        """Handle a WU protocol upload request.

        Responds with 'success' immediately, then processes data async.
        """
        # Parse query parameters
        params: dict[str, str] = {}
        for key, value in request.query.items():
            params[key] = value

        # Also handle POST form data
        if request.method == "POST":
            post_data = await request.post()
            for key, value in post_data.items():
                params[key] = str(value)

        station_id = params.get("ID", "unknown")

        logger.debug(
            "Received data from station %s (%d params)", station_id, len(params)
        )

        # Fire callback without blocking the response
        task = asyncio.create_task(self._safe_callback(station_id, params))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        # Always return success — never reject data
        return web.Response(text="success")

    async def _safe_callback(
        self, station_id: str, params: dict[str, str]
    ) -> None:
        """Call the data callback, catching any errors."""
        try:
            await self._on_data_received(station_id, params)
        except Exception:
            logger.exception("Error processing data from station %s", station_id)

    async def _handle_catchall(self, request: web.Request) -> web.Response:
        """Handle unknown paths gracefully."""
        logger.debug("Unknown request: %s %s", request.method, request.path)
        return web.Response(text="success")
