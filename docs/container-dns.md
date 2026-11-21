# Container DNS while changing installation networks

On 21 November 2026 the third Radxa (labrix-1b09be, now Ethernet10.10.10.126, previously .128) could access pay.labrix.uz from Linux, but its application container still forwarded DNS to the old phone network's10.27.93.78. Container getaddrinfo failed, producing Gateway is not reachable during commissioning. Current phone Wi-Fi used192.168.67.0/24. This was a DNS failure, not a rejected activation code.

`deploy/install-container-dns.py` installs a systemd-resolved listener bound only to Docker's default bridge IPv4 gateway, and configures Docker's default DNS to that stable host address. The host resolver obtains current DNS information from NetworkManager rather than a container retaining a DHCP upstream from creation time. Docker's embedded service-name resolver is retained. The installer preserves other daemon configuration and refuses to replace custom operator DNS. It requires an idle station without credit or session and restarts Docker once. Do not run during customer use.

At boot sammoy2-container-dns.service runs after Docker creates its bridge, refreshes the listener, and precedes sammoy2-post.service. The script must remain installed at its project path. Manually changing Docker's bridge subnet or overriding a container's DNS needs separate review. This does not make the golden image self-updating: installation on future clones is still a separate host provisioning step.

Applied only on the third Radxa. No change to the live .8 or .26 DNS. Recreated third-board factory engine/Telegram/UI once after configuring daemon DNS, with private credentials and database retained. DNS resolution inside the engine then completed in0.023 seconds and HTTPS /health returned200 with certificate verification enabled. Commissioning API returned oktrue; no activation code was consumed. OS reboot and physical network-switch acceptance after the change were not performed. Four installer configuration tests passed.

References: [Docker container DNS](https://docs.docker.com/engine/network/) and [systemd resolved listeners](https://www.freedesktop.org/software/systemd/man/247/resolved.conf.html).
