from ipaddress import ip_address, ip_network


PRIVATE_INSTALL_NETWORKS = (
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
)


def commissioning_access_allowed(client_ip: str, *, complete: bool) -> bool:
    try:
        address = ip_address(client_ip.strip())
    except ValueError:
        return False
    if address.is_loopback:
        return True
    if complete:
        return False
    return any(address in network for network in PRIVATE_INSTALL_NETWORKS)
