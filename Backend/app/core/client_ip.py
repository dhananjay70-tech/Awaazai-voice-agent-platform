"""Work out the real client address, without trusting headers a client can forge."""

import ipaddress


def resolve_client_ip(peer: str | None, forwarded_for: str | None, trusted_proxy_count: int) -> str:
    """Return the client address.

    peer: the TCP peer address (the nearest proxy, or the client itself if there is no proxy).
    forwarded_for: the raw X-Forwarded-For header. Each proxy appends the address it received the request from.
    trusted_proxy_count: how many proxies in front of us are ours.

    Only entries appended by *our own* proxies can be trusted, and those are at the right-hand end of the
    chain. Anything a client puts at the left (e.g. "X-Forwarded-For: 1.2.3.4") is ignored.
    With 0 trusted proxies the header is never read.
    """
    peer = peer or "unknown"
    if trusted_proxy_count <= 0 or not forwarded_for:
        return peer

    chain = [part.strip() for part in forwarded_for.split(",") if part.strip()] + [peer]
    candidate = chain[max(len(chain) - (trusted_proxy_count + 1), 0)]
    if candidate == peer:
        return peer
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:  # garbage in the header: fall back to the peer rather than keying on junk
        return peer


def rate_limit_identity(client_ip: str) -> str:
    """Group IPv6 clients by /64 (one customer usually owns a whole /64, so per-address limits are trivially evaded)."""
    try:
        address = ipaddress.ip_address(client_ip)
    except ValueError:
        return client_ip
    if address.version == 6:
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)
