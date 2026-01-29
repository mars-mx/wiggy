"""Network utilities for MCP server host resolution."""

import logging
import sys

logger = logging.getLogger(__name__)

_LOCALHOST = "127.0.0.1"


def resolve_mcp_bind_host() -> str:
    """Resolve the IP address for the MCP server to bind to.

    On Linux, returns the Docker bridge network gateway IP so that
    containers using ``host.docker.internal`` (mapped to ``host-gateway``)
    can reach the MCP server.  On macOS, Docker Desktop transparently
    routes ``host.docker.internal`` to the host loopback, so
    ``127.0.0.1`` is sufficient.

    Returns ``127.0.0.1`` as a fallback if the bridge gateway cannot be
    determined.
    """
    if sys.platform == "darwin":
        return _LOCALHOST

    try:
        import docker  # lazy import to avoid hard dependency

        client = docker.from_env()
        bridge = client.networks.get("bridge")
        ipam_configs: list[dict[str, str]] = bridge.attrs.get("IPAM", {}).get(
            "Config", []
        )
        for config in ipam_configs:
            gateway = config.get("Gateway")
            if gateway:
                logger.info("Detected Docker bridge gateway: %s", gateway)
                return gateway
        logger.warning("No gateway found in Docker bridge IPAM config")
    except Exception:
        logger.warning(
            "Could not detect Docker bridge gateway, falling back to %s",
            _LOCALHOST,
            exc_info=True,
        )

    return _LOCALHOST
