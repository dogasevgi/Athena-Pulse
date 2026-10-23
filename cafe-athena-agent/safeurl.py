"""Block requests to private/internal addresses (SSRF protection for customer-supplied URLs)."""
import ipaddress
import os
import socket
from urllib.parse import urlparse


class UnsafeURL(ValueError):
    pass


def check_public_url(url):
    """Raise UnsafeURL unless url is http(s) on a standard port and resolves only to public IPs.
    Set ALLOW_PRIVATE_FETCH=1 for local development against localhost sites."""
    p = urlparse(url or "")
    if p.scheme not in ("http", "https") or not p.hostname:
        raise UnsafeURL("Enter a full website address starting with http:// or https://")
    if os.getenv("ALLOW_PRIVATE_FETCH") == "1":
        return url
    try:
        port = p.port
    except ValueError:
        raise UnsafeURL("Invalid port")
    if port not in (None, 80, 443):
        raise UnsafeURL("Only standard web ports are allowed")
    try:
        infos = socket.getaddrinfo(p.hostname, port or (443 if p.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise UnsafeURL("We couldn't find that website. Check the address.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise UnsafeURL("That address isn't a public website.")
    return url
