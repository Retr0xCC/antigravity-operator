"""Ephemeral in-process HTTP/HTTPS forward proxy with strict domain allowlist and LAN isolation.

Provides zero-footprint, non-root network security for AI agent containers:
- Allows strictly whitelisted Google APIs (Gemini, OAuth) and metadata providers (IMDb, TMDb, Wikipedia).
- Strictly blocks access to local/private networks (RFC 1918, loopback, link-local) to protect LAN.
- Defeats SSRF and DNS-rebinding attacks by validating resolved IP addresses.
- Operates entirely in-memory within the dispatcher process; leaves zero persistent traces.
"""

from __future__ import annotations

import ipaddress
import logging
import select
import socket
import threading
from typing import Sequence
from urllib.parse import urlparse


logger = logging.getLogger("antigravity.proxy")

# Default trusted domains required for Antigravity AI agent and media metadata
DEFAULT_ALLOWLIST: tuple[str, ...] = (
    # Google Gemini API & Cloud Code Services
    "generativelanguage.googleapis.com",
    "accounts.google.com",
    "oauth2.googleapis.com",
    "www.googleapis.com",
    "lh3.googleusercontent.com",
    "aicode.googleapis.com",
    "cloudcode-pa.googleapis.com",
    "daily-cloudcode-pa.googleapis.com",
    "antigravity.google",
    "antigravity.google.com",
    "antigravity-unleash.goog",
    "play.googleapis.com",
    "safebrowsing.googleapis.com",
    "www.gstatic.com",
    "storage.googleapis.com",
    "*.googleapis.com",
    "*.google.com",
    "*.gstatic.com",
    "raw.githubusercontent.com",
    # Multimedia Metadata Resolution
    "*.imdb.com",
    "m.media-amazon.com",
    "*.themoviedb.org",
    "*.tmdb.org",
    "*.thetvdb.com",
    "*.wikipedia.org",
    "*.wikimedia.org",
    "openlibrary.org",
    "*.openlibrary.org",
    "covers.openlibrary.org",
)


def is_private_or_local_ip(ip_str: str) -> bool:
    """Check if an IP address belongs to private, loopback, link-local, or reserved ranges."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )
    except ValueError:
        return False


def is_domain_allowed(host: str, allowlist: Sequence[str]) -> bool:
    """Check if target host matches any rule in the allowlist."""
    host = host.lower().strip()

    # Block direct IP access to private/LAN addresses unconditionally
    if is_private_or_local_ip(host):
        return False

    for pattern in allowlist:
        pattern = pattern.lower().strip()
        if pattern == "*":
            return True
        if pattern.startswith("*."):
            suffix = pattern[2:]
            if host == suffix or host.endswith("." + suffix):
                return True
        elif host == pattern:
            return True

    return False


def resolve_safe_ip(host: str) -> str | None:
    """Resolve a host name and ensure the resulting IP is NOT in a private or local range (Anti-SSRF)."""
    if is_private_or_local_ip(host):
        return None

    try:
        addr_info = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
        for family, socktype, proto, canonname, sockaddr in addr_info:
            ip = sockaddr[0]
            if not is_private_or_local_ip(ip):
                return ip
    except Exception:
        pass
    return None


class EphemeralAllowlistProxy:
    """Lightweight in-memory HTTP/HTTPS tunneling proxy with domain filtering and LAN protection."""

    def __init__(
        self,
        allowlist: Sequence[str] | None = None,
        bind_host: str = "0.0.0.0",
        port: int = 0,
    ) -> None:
        self.allowlist = list(allowlist if allowlist is not None else DEFAULT_ALLOWLIST)
        self.bind_host = bind_host
        self._requested_port = port
        self.port: int = 0
        self._server_sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._active_sockets: set[socket.socket] = set()
        self._lock = threading.Lock()

    def start(self) -> int:
        """Start the proxy server in a background daemon thread and return the bound port."""
        if self._running:
            return self.port

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.bind_host, self._requested_port))
        sock.listen(128)
        sock.settimeout(0.5)

        self.port = sock.getsockname()[1]
        self._server_sock = sock
        self._running = True

        self._thread = threading.Thread(
            target=self._accept_loop,
            name=f"EphemeralProxy-{self.port}",
            daemon=True,
        )
        self._thread.start()
        logger.info("Ephemeral Allowlist Proxy started on %s:%d", self.bind_host, self.port)
        return self.port

    def stop(self) -> None:
        """Stop the proxy server and close all active sockets."""
        self._running = False

        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
            self._server_sock = None

        with self._lock:
            for s in list(self._active_sockets):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    s.close()
                except Exception:
                    pass
            self._active_sockets.clear()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info("Ephemeral Allowlist Proxy stopped.")

    def __enter__(self) -> EphemeralAllowlistProxy:
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    def _track_socket(self, sock: socket.socket) -> None:
        with self._lock:
            self._active_sockets.add(sock)

    def _untrack_socket(self, sock: socket.socket) -> None:
        with self._lock:
            self._active_sockets.discard(sock)

    def _accept_loop(self) -> None:
        while self._running:
            try:
                if not self._server_sock:
                    break
                client_sock, client_addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except Exception:
                break

            client_thread = threading.Thread(
                target=self._handle_client,
                args=(client_sock, client_addr),
                daemon=True,
            )
            client_thread.start()

    def _handle_client(self, client: socket.socket, addr: tuple[str, int]) -> None:
        self._track_socket(client)
        upstream: socket.socket | None = None
        try:
            client.settimeout(10.0)
            raw_header = bytearray()
            while b"\r\n\r\n" not in raw_header and len(raw_header) < 65536:
                chunk = client.recv(4096)
                if not chunk:
                    break
                raw_header.extend(chunk)

            if not raw_header:
                return

            header_str = raw_header.decode("latin1", "ignore")
            req_line = header_str.split("\r\n", 1)[0]
            parts = req_line.split()
            if len(parts) < 2:
                self._send_error(client, 400, "Bad Request")
                return

            method, target = parts[0].upper(), parts[1]

            if method == "CONNECT":
                # HTTPS Tunneling: target is 'host:port'
                if ":" in target:
                    target_host, target_port_s = target.split(":", 1)
                    try:
                        target_port = int(target_port_s)
                    except ValueError:
                        target_port = 443
                else:
                    target_host, target_port = target, 443

                if not is_domain_allowed(target_host, self.allowlist):
                    logger.warning("Blocked CONNECT to unauthorized domain: %s", target_host)
                    self._send_error(client, 403, f"Forbidden by Operator Security Policy: {target_host}")
                    return

                safe_ip = resolve_safe_ip(target_host)
                if not safe_ip:
                    logger.warning("Blocked CONNECT to unsafe or unresolvable IP/host: %s", target_host)
                    self._send_error(client, 403, f"Forbidden: Unsafe target address {target_host}")
                    return

                try:
                    upstream = socket.create_connection((safe_ip, target_port), timeout=10.0)
                    self._track_socket(upstream)
                    client.sendall(b"HTTP/1.1 200 Connection Established\r\nProxy-Agent: Antigravity-Operator-Proxy\r\n\r\n")
                    self._relay(client, upstream)
                except Exception as e:
                    self._send_error(client, 502, f"Bad Gateway: {e}")
                    return

            else:
                # Plain HTTP proxy request: target is 'http://host[:port]/path' or path with Host header
                parsed = urlparse(target)
                target_host = parsed.hostname or ""
                target_port = parsed.port or 80

                if not target_host:
                    # Look up Host header
                    for line in header_str.split("\r\n"):
                        if line.lower().startswith("host:"):
                            val = line.split(":", 1)[1].strip()
                            if ":" in val:
                                target_host, p_str = val.split(":", 1)
                                target_port = int(p_str)
                            else:
                                target_host = val
                            break

                if not target_host or not is_domain_allowed(target_host, self.allowlist):
                    logger.warning("Blocked plain HTTP request to: %s", target_host)
                    self._send_error(client, 403, f"Forbidden: {target_host}")
                    return

                safe_ip = resolve_safe_ip(target_host)
                if not safe_ip:
                    self._send_error(client, 403, "Forbidden: Unsafe host address")
                    return

                try:
                    upstream = socket.create_connection((safe_ip, target_port), timeout=10.0)
                    self._track_socket(upstream)

                    # Rewrite absolute URL to relative path for upstream web server
                    path_to_send = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
                    new_req_line = f"{method} {path_to_send} {parts[2] if len(parts) > 2 else 'HTTP/1.1'}\r\n"
                    body_start = raw_header.find(b"\r\n") + 2
                    upstream.sendall(new_req_line.encode("latin1") + bytes(raw_header[body_start:]))
                    self._relay(client, upstream)
                except Exception as e:
                    self._send_error(client, 502, f"Bad Gateway: {e}")
                    return

        except Exception:
            pass
        finally:
            if upstream:
                self._untrack_socket(upstream)
                try:
                    upstream.close()
                except Exception:
                    pass
            self._untrack_socket(client)
            try:
                client.close()
            except Exception:
                pass

    def _relay(self, sock1: socket.socket, sock2: socket.socket) -> None:
        """Bidirectionally relay data between two sockets until either is closed."""
        sock1.setblocking(False)
        sock2.setblocking(False)
        sockets = [sock1, sock2]

        while self._running:
            try:
                readable, _, exceptional = select.select(sockets, [], sockets, 30.0)
                if exceptional:
                    break
                if not readable:
                    continue

                for s in readable:
                    data = s.recv(32768)
                    if not data:
                        return
                    other = sock2 if s is sock1 else sock1
                    other.sendall(data)
            except Exception:
                break

    @staticmethod
    def _send_error(client: socket.socket, code: int, message: str) -> None:
        try:
            body = f"<html><body><h1>{code} {message}</h1></body></html>".encode("utf-8")
            resp = (
                f"HTTP/1.1 {code} {message}\r\n"
                f"Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode("latin1") + body
            client.sendall(resp)
        except Exception:
            pass
