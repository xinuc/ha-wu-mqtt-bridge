"""Async forwarding of weather data to the real Weather Underground servers."""

import asyncio
import logging
from urllib.parse import urlencode

import aiohttp

logger = logging.getLogger(__name__)

# WU endpoints to forward to
WU_HOSTS = [
    "rtupdate.wunderground.com",
    "weatherstation.wunderground.com",
]

WU_PATH = "/weatherstation/updateweatherstation.php"

# Public DNS server used to resolve real WU IPs (bypassing local DNS override)
PUBLIC_DNS = "1.1.1.1"

# Re-resolve DNS every 6 hours (CDNs rotate IPs)
DNS_REFRESH_INTERVAL = 6 * 60 * 60


class WUForwarder:
    """Forwards weather data to the real WU servers.

    Since the local DNS is overridden to redirect WU hostnames to the bridge,
    we resolve the real WU IPs at startup using a public DNS server and
    forward using those IPs directly. IPs are refreshed periodically.
    """

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self._resolved_ips: dict[str, str] = {}
        self._session: aiohttp.ClientSession | None = None
        self._dns_refresh_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Resolve real WU IPs and create HTTP session."""
        if not self._enabled:
            logger.info("WU forwarding is disabled")
            return

        await self._resolve_all_hosts()

        if not self._resolved_ips:
            logger.error("Could not resolve any WU hosts, forwarding disabled")
            self._enabled = False
            return

        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
        )
        self._dns_refresh_task = asyncio.create_task(self._periodic_dns_refresh())
        logger.info("WU forwarding enabled")

    async def stop(self) -> None:
        """Close the HTTP session and stop background tasks."""
        if self._dns_refresh_task:
            self._dns_refresh_task.cancel()
            try:
                await self._dns_refresh_task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
            self._session = None

    async def forward(self, params: dict[str, str]) -> None:
        """Forward weather data to the real WU servers (fire-and-forget).

        This should be called as a background task. Failures are logged
        but never raised — they must not affect local MQTT publishing.
        """
        if not self._enabled or not self._session:
            return

        # Forward to the primary host (rtupdate)
        host = WU_HOSTS[0]
        ip = self._resolved_ips.get(host)
        if not ip:
            # Fall back to second host
            host = WU_HOSTS[1]
            ip = self._resolved_ips.get(host)
        if not ip:
            return

        url = f"https://{ip}{WU_PATH}"
        query = urlencode(params)
        full_url = f"{url}?{query}"

        try:
            async with self._session.get(
                full_url,
                headers={"Host": host},
                ssl=False,  # Don't verify WU's cert when connecting by IP
            ) as resp:
                body = await resp.text()
                if "success" in body.lower():
                    logger.debug("Forwarded to WU (%s): success", host)
                else:
                    logger.warning("WU forward response (%s): %s", host, body[:200])
        except Exception:
            logger.warning("Failed to forward to WU (%s)", host, exc_info=True)

    async def _resolve_all_hosts(self) -> None:
        """Resolve all WU hostnames using public DNS."""
        for host in WU_HOSTS:
            ip = await self._resolve_via_public_dns(host)
            if ip:
                self._resolved_ips[host] = ip
                logger.info("Resolved %s -> %s", host, ip)
            else:
                logger.warning("Could not resolve %s, forwarding to it will be skipped", host)

    async def _periodic_dns_refresh(self) -> None:
        """Re-resolve WU IPs periodically to handle CDN IP rotation."""
        while True:
            await asyncio.sleep(DNS_REFRESH_INTERVAL)
            logger.debug("Refreshing WU DNS resolution")
            await self._resolve_all_hosts()

    @staticmethod
    async def _resolve_via_public_dns(hostname: str) -> str | None:
        """Resolve a hostname using a public DNS server to bypass local overrides."""
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, _dns_resolve, hostname
            )
            return result
        except Exception:
            logger.warning("DNS resolution failed for %s", hostname, exc_info=True)
            return None


def _dns_resolve(hostname: str) -> str | None:
    """Resolve hostname using public DNS (runs in thread).

    Does NOT fall back to system DNS — that would resolve to the bridge itself
    due to the local DNS override, creating a forwarding loop.
    """
    import dns.resolver

    try:
        resolver = dns.resolver.Resolver()
        resolver.nameservers = [PUBLIC_DNS]
        resolver.lifetime = 5
        answers = resolver.resolve(hostname, "A")
        for rdata in answers:
            return str(rdata)
    except Exception:
        logger.warning("Public DNS resolution failed for %s", hostname)
        return None
    return None
