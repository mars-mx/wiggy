"""Tests for MCP networking utilities."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from wiggy.mcp.networking import resolve_mcp_bind_host


class TestResolveMCPBindHost:
    """Tests for resolve_mcp_bind_host."""

    @patch("wiggy.mcp.networking.sys")
    def test_macos_returns_localhost(self, mock_sys: MagicMock) -> None:
        """On macOS, always returns 127.0.0.1."""
        mock_sys.platform = "darwin"
        assert resolve_mcp_bind_host() == "127.0.0.1"

    @patch("wiggy.mcp.networking.sys")
    def test_linux_returns_bridge_gateway(self, mock_sys: MagicMock) -> None:
        """On Linux, returns the Docker bridge gateway IP."""
        mock_sys.platform = "linux"

        mock_bridge = MagicMock()
        mock_bridge.attrs = {
            "IPAM": {
                "Config": [{"Subnet": "172.17.0.0/16", "Gateway": "172.17.0.1"}]
            }
        }
        mock_client = MagicMock()
        mock_client.networks.get.return_value = mock_bridge

        with patch("docker.from_env", return_value=mock_client):
            result = resolve_mcp_bind_host()

        assert result == "172.17.0.1"
        mock_client.networks.get.assert_called_once_with("bridge")

    @patch("wiggy.mcp.networking.sys")
    def test_linux_custom_gateway(self, mock_sys: MagicMock) -> None:
        """Returns custom gateway IP when Docker uses non-default subnet."""
        mock_sys.platform = "linux"

        mock_bridge = MagicMock()
        mock_bridge.attrs = {
            "IPAM": {
                "Config": [{"Subnet": "192.168.99.0/24", "Gateway": "192.168.99.1"}]
            }
        }
        mock_client = MagicMock()
        mock_client.networks.get.return_value = mock_bridge

        with patch("docker.from_env", return_value=mock_client):
            result = resolve_mcp_bind_host()

        assert result == "192.168.99.1"

    @patch("wiggy.mcp.networking.sys")
    def test_linux_fallback_on_docker_error(self, mock_sys: MagicMock) -> None:
        """Falls back to 127.0.0.1 when Docker SDK raises."""
        mock_sys.platform = "linux"

        with patch("docker.from_env", side_effect=Exception("Docker not running")):
            result = resolve_mcp_bind_host()

        assert result == "127.0.0.1"

    @patch("wiggy.mcp.networking.sys")
    def test_linux_fallback_no_gateway(self, mock_sys: MagicMock) -> None:
        """Falls back when bridge has no gateway in IPAM config."""
        mock_sys.platform = "linux"

        mock_bridge = MagicMock()
        mock_bridge.attrs = {"IPAM": {"Config": []}}
        mock_client = MagicMock()
        mock_client.networks.get.return_value = mock_bridge

        with patch("docker.from_env", return_value=mock_client):
            result = resolve_mcp_bind_host()

        assert result == "127.0.0.1"

    @patch("wiggy.mcp.networking.sys")
    def test_linux_fallback_empty_ipam(self, mock_sys: MagicMock) -> None:
        """Falls back when bridge attrs have no IPAM key."""
        mock_sys.platform = "linux"

        mock_bridge = MagicMock()
        mock_bridge.attrs = {}
        mock_client = MagicMock()
        mock_client.networks.get.return_value = mock_bridge

        with patch("docker.from_env", return_value=mock_client):
            result = resolve_mcp_bind_host()

        assert result == "127.0.0.1"
