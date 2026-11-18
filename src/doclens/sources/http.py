"""Bounded public HTTPS transport shared by network source adapters."""

import socket
from ipaddress import ip_address

import httpx

from doclens.sources.base import IngestionError


def public_addresses(host: str) -> list[str]:
    try:
        addresses = sorted({row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)},
                           key=lambda address: (":" in address, address))
    except OSError:
        raise IngestionError("network_error", retryable=True) from None
    if not addresses or any(not ip_address(address).is_global for address in addresses):
        raise IngestionError("unsafe_destination")
    return addresses


class PinnedTransport(httpx.BaseTransport):
    """Connect to a checked public IP, retaining the approved Host/TLS identity.

    Pinning avoids a second DNS lookup between validation and connection. The
    HTTPX transport still owns TLS verification, sockets and timeout handling.
    """
    def __init__(self, resolver=public_addresses):
        self.resolver = resolver
        self.transport = httpx.HTTPTransport(retries=0, trust_env=False)

    def handle_request(self, request):
        address = self.resolver(request.url.host)[0]
        pinned = httpx.Request(request.method, request.url.copy_with(host=address),
            headers={**request.headers, "host": request.url.host}, stream=request.stream,
            extensions={**request.extensions, "sni_hostname": request.url.host})
        return self.transport.handle_request(pinned)

    def close(self):
        self.transport.close()
