"""Unit tests for the Ephemeral Allowlist Proxy and SSRF/LAN protection."""

import socket
import unittest
import urllib.error
import urllib.request
from core.proxy import (
    DEFAULT_ALLOWLIST,
    EphemeralAllowlistProxy,
    is_domain_allowed,
    is_private_or_local_ip,
    resolve_safe_ip,
)


class TestProxyRules(unittest.TestCase):
    """Test domain and IP validation logic."""

    def test_private_and_local_ip_detection(self):
        # RFC 1918 Private ranges
        self.assertTrue(is_private_or_local_ip("10.0.0.1"))
        self.assertTrue(is_private_or_local_ip("172.16.0.1"))
        self.assertTrue(is_private_or_local_ip("192.168.1.1"))
        # Loopback
        self.assertTrue(is_private_or_local_ip("127.0.0.1"))
        self.assertTrue(is_private_or_local_ip("127.0.1.1"))
        # Link-local & Multicast
        self.assertTrue(is_private_or_local_ip("169.254.1.1"))
        self.assertTrue(is_private_or_local_ip("224.0.0.1"))
        # IPv6
        self.assertTrue(is_private_or_local_ip("::1"))
        self.assertTrue(is_private_or_local_ip("fe80::1"))
        # Public IPs
        self.assertFalse(is_private_or_local_ip("8.8.8.8"))
        self.assertFalse(is_private_or_local_ip("1.1.1.1"))
        self.assertFalse(is_private_or_local_ip("142.250.190.46"))

    def test_domain_allowlist_matching(self):
        allow = [
            "generativelanguage.googleapis.com",
            "*.googleapis.com",
            "*.google.com",
            "*.imdb.com",
        ]
        # Direct matches
        self.assertTrue(is_domain_allowed("generativelanguage.googleapis.com", allow))
        self.assertTrue(is_domain_allowed("googleapis.com", allow))
        self.assertTrue(is_domain_allowed("aicode.googleapis.com", allow))
        self.assertTrue(is_domain_allowed("www.google.com", allow))
        self.assertTrue(is_domain_allowed("m.imdb.com", allow))

        # Unauthorized domains
        self.assertFalse(is_domain_allowed("evil.com", allow))
        self.assertFalse(is_domain_allowed("notgoogleapis.com", allow))
        self.assertFalse(is_domain_allowed("google.com.attacker.com", allow))

        # Direct LAN IPs must be rejected even if pattern is wildcard
        self.assertFalse(is_domain_allowed("192.168.1.1", allow))
        self.assertFalse(is_domain_allowed("127.0.0.1", allow))
        self.assertFalse(is_domain_allowed("10.0.0.1", allow))

    def test_anti_ssrf_resolve_safe_ip(self):
        # Localhost and LAN IPs must never resolve to a safe IP
        self.assertIsNone(resolve_safe_ip("127.0.0.1"))
        self.assertIsNone(resolve_safe_ip("192.168.1.1"))
        self.assertIsNone(resolve_safe_ip("localhost"))

        # Public domain resolves to a safe public IP
        safe = resolve_safe_ip("www.google.com")
        self.assertIsNotNone(safe)
        self.assertFalse(is_private_or_local_ip(safe))


class TestEphemeralProxyServer(unittest.TestCase):
    """Test live ephemeral proxy server execution and request filtering."""

    def test_proxy_lifecycle(self):
        proxy = EphemeralAllowlistProxy(bind_host="127.0.0.1")
        port = proxy.start()
        self.assertGreater(port, 1024)
        self.assertTrue(proxy._running)

        # Context manager lifecycle
        proxy.stop()
        self.assertFalse(proxy._running)

    def test_unauthorized_domain_blocked_with_403(self):
        allow = ["*.google.com", "generativelanguage.googleapis.com"]
        with EphemeralAllowlistProxy(allowlist=allow, bind_host="127.0.0.1") as proxy:
            proxy_url = f"http://127.0.0.1:{proxy.port}"
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"https": proxy_url, "http": proxy_url})
            )

            # 1. Blocked unauthorized domain
            with self.assertRaises(urllib.error.URLError) as ctx:
                opener.open("https://unauthorized-attacker-domain.org", timeout=2)
            self.assertIn("403 Forbidden", str(ctx.exception))

            # 2. Blocked private LAN IP
            with self.assertRaises(urllib.error.URLError) as ctx:
                opener.open("https://192.168.1.1", timeout=2)
            self.assertIn("403 Forbidden", str(ctx.exception))

    def test_unix_socket_proxy_lifecycle_and_filtering(self):
        import os
        sock_path = "/tmp/test-unit-agy-proxy.sock"
        if os.path.exists(sock_path):
            os.unlink(sock_path)

        allow = ["*.google.com", "generativelanguage.googleapis.com"]
        proxy = EphemeralAllowlistProxy(allowlist=allow, socket_path=sock_path)
        ret_path = proxy.start()
        self.assertEqual(ret_path, sock_path)
        self.assertTrue(os.path.exists(sock_path))
        self.assertTrue(proxy._running)

        # Connect directly over Unix domain socket
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(sock_path)
        client.sendall(b"CONNECT unauthorized-site.com:443 HTTP/1.1\r\nHost: unauthorized-site.com:443\r\n\r\n")
        resp = client.recv(4096)
        client.close()
        self.assertIn(b"403 Forbidden", resp)

        # Test LAN IP rejection over Unix domain socket
        client2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client2.connect(sock_path)
        client2.sendall(b"CONNECT 192.168.1.1:443 HTTP/1.1\r\nHost: 192.168.1.1:443\r\n\r\n")
        resp2 = client2.recv(4096)
        client2.close()
        self.assertIn(b"403 Forbidden", resp2)

        # Stop proxy and verify socket cleanup
        proxy.stop()
        self.assertFalse(proxy._running)
        self.assertFalse(os.path.exists(sock_path))


if __name__ == "__main__":
    unittest.main()
