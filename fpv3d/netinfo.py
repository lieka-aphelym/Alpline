"""Local network helpers shared by the server and the launcher (standard library only)."""
from __future__ import annotations

import socket


def lan_addresses() -> list:
    """IPv4 addresses of this computer on its local networks (Wi-Fi, hotspot, cable), best guess first."""
    ips = []
    try:                                     # the interface used to reach the internet / the router
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.168.1.1", 9))   # no packet is sent: this only picks the route
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(info[4][0])
    except OSError:
        pass
    return [ip for i, ip in enumerate(ips) if ip not in ips[:i] and not ip.startswith(("127.", "169.254."))]
