"""Bounded web fetching with public IP pinning and redirect validation."""

import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit

from .limits import MAX_URL_BYTES

TIMEOUT_SECONDS = 10
TOTAL_SECONDS = 30
MAX_REDIRECTS = 3


def _target(url):
    try:
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("Invalid URL.") from exc
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or port != (443 if parsed.scheme == "https" else 80)
            or any(ord(char) < 32 or ord(char) == 127 for char in url)):
        raise ValueError("Use a public HTTP(S) URL with a standard port and no credentials.")
    host = parsed.hostname.encode("idna").decode("ascii")
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Could not resolve the URL hostname.") from exc
    ips = [entry[4][0] for entry in addresses]
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError("URLs pointing to local or private networks are not allowed.")
    return parsed, host, port, ips[0]


def fetch_page(url: str) -> tuple[bytes, str]:
    deadline = time.monotonic() + TOTAL_SECONDS
    for redirect in range(MAX_REDIRECTS + 1):
        parsed, host, port, ip = _target(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Web page download timed out.")
        connection = http.client.HTTPConnection(host, port, timeout=min(TIMEOUT_SECONDS, remaining))
        try:
            # Connect to the validated IP; do not resolve the hostname again.
            connection.sock = socket.create_connection((ip, port), connection.timeout)
            if parsed.scheme == "https":
                connection.sock = ssl.create_default_context().wrap_socket(
                    connection.sock, server_hostname=host,
                )
            connection.auto_open = 0
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request("GET", path, headers={
                "User-Agent": "RAGChatbot/1.0", "Accept-Encoding": "identity",
                "Accept": "text/html, text/plain, application/xhtml+xml",
            })
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location or redirect == MAX_REDIRECTS:
                    raise ValueError("Too many redirects or missing redirect URL.")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError(f"Web page returned HTTP {response.status}.")
            content_type = response.getheader("Content-Type", "").split(";")[0].lower().strip()
            if content_type not in {"text/html", "text/plain", "application/xhtml+xml"}:
                raise ValueError("The URL must return an HTML or plain text page.")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("Compressed web responses are not supported.")
            length = response.getheader("Content-Length")
            if length and int(length) > MAX_URL_BYTES:
                raise ValueError("Web page exceeds the 2 MB download limit.")
            chunks = []
            size = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("Web page download timed out.")
                if connection.sock:
                    connection.sock.settimeout(min(TIMEOUT_SECONDS, remaining))
                chunk = response.read1(min(64 * 1024, MAX_URL_BYTES + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_URL_BYTES:
                    raise ValueError("Web page exceeds the 2 MB download limit.")
                chunks.append(chunk)
            return b"".join(chunks), url
        except (OSError, http.client.HTTPException) as exc:
            raise ValueError("Could not download the web page.") from exc
        finally:
            connection.close()
    raise ValueError("Too many redirects.")
