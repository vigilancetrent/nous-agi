"""Network discovery, enumeration, and mapping tools.

Provides subnet scanning, ARP discovery, DNS reconnaissance,
and OS fingerprinting for authorized network assessments.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import struct
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_cmd(cmd: List[str], timeout: int = 60) -> Dict[str, Any]:
    """Run a subprocess and return structured result."""
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        out = res.stdout
        if res.stderr:
            out += "\n--- STDERR ---\n" + res.stderr
        if len(out) > 50000:
            out = out[:25000] + "\n...(truncated)...\n" + out[-25000:]
        return {"exit_code": res.returncode, "output": out}
    except FileNotFoundError:
        return {"error": f"Command not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return {"error": f"Timeout ({timeout}s) running: {' '.join(cmd)}"}
    except Exception as exc:
        return {"error": str(exc)}


def _install_apt(package: str) -> bool:
    """Attempt to install a system package via apt-get."""
    try:
        subprocess.run(
            ["apt-get", "install", "-y", "-qq", package],
            capture_output=True, timeout=120,
        )
        return True
    except Exception:
        return False


def _parse_subnet(target: str) -> List[str]:
    """Parse a target into a list of IPs. Accepts CIDR, range, or single IP."""
    try:
        net = ipaddress.ip_network(target, strict=False)
        if net.num_addresses > 65536:
            return [str(ip) for ip in list(net.hosts())[:65536]]
        return [str(ip) for ip in net.hosts()]
    except ValueError:
        return [target]


def _ping_one(ip: str, timeout: int = 1) -> bool:
    """Ping a single host. Returns True if alive."""
    try:
        res = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), ip],
            capture_output=True, timeout=timeout + 2,
        )
        return res.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def _ping_sweep(ctx: ToolContext, target: str, threads: int = 50,
                timeout: int = 1) -> str:
    """Discover live hosts on a subnet using ICMP ping.

    target: CIDR (e.g. '192.168.1.0/24') or single IP.
    threads: concurrent ping workers (default 50).
    timeout: per-ping timeout in seconds.
    """
    threads = min(int(threads), 200)
    timeout = min(int(timeout), 5)
    ips = _parse_subnet(target)
    if not ips:
        return json.dumps({"error": "Invalid target"})

    alive = []

    def _check(ip: str) -> None:
        if _ping_one(ip, timeout):
            alive.append(ip)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futs = [pool.submit(_check, ip) for ip in ips]
        for f in as_completed(futs):
            f.result()

    return json.dumps({
        "target": target,
        "total_scanned": len(ips),
        "alive_count": len(alive),
        "alive_hosts": sorted(alive, key=lambda x: ipaddress.ip_address(x)),
    }, ensure_ascii=False, indent=2)


def _arp_scan(ctx: ToolContext, target: str, interface: str = "") -> str:
    """ARP-based LAN device discovery (faster than ping, layer 2).

    target: CIDR subnet (e.g. '192.168.1.0/24').
    interface: network interface (e.g. 'eth0'). Auto-detected if empty.
    """
    cmd = ["arp-scan"]
    if interface:
        cmd += ["-I", interface]
    cmd.append(target)

    result = _run_cmd(cmd, timeout=60)
    if "error" in result and "Command not found" in result["error"]:
        _install_apt("arp-scan")
        result = _run_cmd(cmd, timeout=60)
    if "error" in result:
        # Fallback: use arping per-host for small subnets
        ips = _parse_subnet(target)
        if len(ips) > 256:
            return json.dumps({"error": result["error"],
                               "hint": "Install arp-scan or use a /24 or smaller"})
        hosts = []
        for ip in ips[:256]:
            arpcmd = ["arping", "-c", "1", "-w", "1", ip]
            r = _run_cmd(arpcmd, timeout=3)
            if r.get("exit_code") == 0:
                hosts.append({"ip": ip, "raw": r.get("output", "").strip()})
        return json.dumps({"target": target, "method": "arping_fallback",
                           "hosts": hosts}, ensure_ascii=False, indent=2)

    # Parse arp-scan output
    hosts = []
    for line in result.get("output", "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            try:
                ipaddress.ip_address(parts[0].strip())
                hosts.append({
                    "ip": parts[0].strip(),
                    "mac": parts[1].strip(),
                    "vendor": parts[2].strip() if len(parts) > 2 else "",
                })
            except ValueError:
                continue

    return json.dumps({
        "target": target,
        "host_count": len(hosts),
        "hosts": hosts,
        "raw": result.get("output", "")[:5000],
    }, ensure_ascii=False, indent=2)


def _network_info(ctx: ToolContext) -> str:
    """List local network interfaces, IPs, routes, and ARP table."""
    sections = {}

    for label, cmd in [
        ("interfaces", ["ip", "-j", "addr"]),
        ("routes", ["ip", "-j", "route"]),
        ("arp_table", ["ip", "-j", "neigh"]),
        ("dns", ["cat", "/etc/resolv.conf"]),
    ]:
        r = _run_cmd(cmd, timeout=10)
        if "error" not in r:
            raw = r.get("output", "")
            # Try parse JSON output from ip -j
            try:
                sections[label] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                sections[label] = raw.strip()
        else:
            sections[label] = r["error"]

    # Also grab hostname
    try:
        sections["hostname"] = socket.gethostname()
        sections["fqdn"] = socket.getfqdn()
    except Exception:
        pass

    return json.dumps(sections, ensure_ascii=False, indent=2)


def _traceroute(ctx: ToolContext, target: str, max_hops: int = 30,
                timeout: int = 60) -> str:
    """Trace network path to target host.

    target: hostname or IP.
    max_hops: max TTL (default 30).
    """
    max_hops = min(int(max_hops), 64)
    timeout = min(int(timeout), 120)

    cmd = ["traceroute", "-m", str(max_hops), "-w", "2", target]
    result = _run_cmd(cmd, timeout=timeout)

    if "error" in result and "Command not found" in result["error"]:
        _install_apt("traceroute")
        result = _run_cmd(cmd, timeout=timeout)

    if "error" in result:
        return json.dumps(result, ensure_ascii=False, indent=2)

    # Parse hops
    hops = []
    for line in result.get("output", "").splitlines():
        line = line.strip()
        if not line or line.startswith("traceroute"):
            continue
        match = re.match(r"^\s*(\d+)\s+(.+)", line)
        if match:
            hops.append({"hop": int(match.group(1)), "detail": match.group(2).strip()})

    return json.dumps({
        "target": target,
        "hops": hops,
        "raw": result.get("output", "")[:5000],
    }, ensure_ascii=False, indent=2)


def _dns_recon(ctx: ToolContext, target: str, record_type: str = "ANY",
               nameserver: str = "") -> str:
    """DNS reconnaissance — zone transfer attempt, record enumeration.

    target: domain name.
    record_type: 'A', 'AAAA', 'MX', 'NS', 'TXT', 'SOA', 'ANY', 'AXFR'.
    nameserver: specific DNS server to query (optional).
    """
    results: Dict[str, Any] = {"target": target}

    # Standard resolution via socket
    try:
        addrs = socket.getaddrinfo(target, None)
        results["resolved"] = list({addr[4][0] for addr in addrs})
    except socket.gaierror as e:
        results["resolved"] = str(e)

    # Use dig for detailed records
    dig_cmd = ["dig"]
    if nameserver:
        dig_cmd.append(f"@{nameserver}")
    dig_cmd += [target, record_type, "+noall", "+answer"]

    r = _run_cmd(dig_cmd, timeout=15)
    if "error" not in r:
        results["dig_answer"] = r.get("output", "").strip()
    else:
        results["dig_error"] = r["error"]

    # Zone transfer attempt
    if record_type.upper() == "AXFR" or record_type.upper() == "ANY":
        # Find nameservers first
        ns_cmd = ["dig", target, "NS", "+short"]
        if nameserver:
            ns_cmd.insert(1, f"@{nameserver}")
        nr = _run_cmd(ns_cmd, timeout=10)
        ns_list = [l.strip().rstrip(".")
                   for l in nr.get("output", "").splitlines() if l.strip()]
        results["nameservers"] = ns_list

        # Try AXFR on each NS
        axfr_results = []
        for ns in ns_list[:5]:
            axfr_cmd = ["dig", f"@{ns}", target, "AXFR"]
            ar = _run_cmd(axfr_cmd, timeout=15)
            output = ar.get("output", "")
            if "Transfer failed" not in output and "error" not in ar:
                axfr_results.append({"ns": ns, "records": output[:5000]})
            else:
                axfr_results.append({"ns": ns, "status": "transfer_denied"})
        results["zone_transfer"] = axfr_results

    # Reverse lookup if target is IP
    try:
        ip = ipaddress.ip_address(target)
        try:
            rev = socket.gethostbyaddr(str(ip))
            results["reverse_dns"] = rev[0]
        except socket.herror:
            results["reverse_dns"] = "no PTR record"
    except ValueError:
        pass

    return json.dumps(results, ensure_ascii=False, indent=2)


def _netbios_scan(ctx: ToolContext, target: str, timeout: int = 10) -> str:
    """NetBIOS name scan for Windows host discovery.

    target: IP, CIDR subnet, or hostname.
    """
    timeout = min(int(timeout), 60)

    cmd = ["nbtscan", "-v", target]
    result = _run_cmd(cmd, timeout=timeout)

    if "error" in result and "Command not found" in result["error"]:
        _install_apt("nbtscan")
        result = _run_cmd(cmd, timeout=timeout)

    if "error" in result:
        # Fallback: raw UDP probe to NetBIOS name service (port 137)
        ips = _parse_subnet(target)
        hosts = []
        for ip in ips[:256]:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(2)
                # NetBIOS name query packet for wildcard *
                query = (
                    b"\x80\x94\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00"
                    b"\x20CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\x00"
                    b"\x00\x21\x00\x01"
                )
                sock.sendto(query, (ip, 137))
                data, _ = sock.recvfrom(1024)
                sock.close()
                if len(data) > 56:
                    name_count = data[56]
                    names = []
                    offset = 57
                    for _ in range(name_count):
                        if offset + 18 <= len(data):
                            nb_name = data[offset:offset+15].decode(
                                "ascii", errors="replace").strip()
                            names.append(nb_name)
                            offset += 18
                    hosts.append({"ip": ip, "names": names})
            except Exception:
                pass

        return json.dumps({
            "target": target, "method": "raw_udp",
            "host_count": len(hosts), "hosts": hosts,
        }, ensure_ascii=False, indent=2)

    return json.dumps({
        "target": target,
        "method": "nbtscan",
        "raw": result.get("output", "")[:5000],
    }, ensure_ascii=False, indent=2)


def _snmp_scan(ctx: ToolContext, target: str,
               communities: str = "public,private,community",
               port: int = 161, timeout: int = 2) -> str:
    """SNMP community string brute force and enumeration.

    target: IP or hostname.
    communities: comma-separated community strings to test.
    port: SNMP port (default 161).
    """
    port = int(port)
    timeout = min(int(timeout), 10)
    comm_list = [c.strip() for c in communities.split(",") if c.strip()]
    ips = _parse_subnet(target)

    results = []

    for ip in ips[:256]:
        for community in comm_list:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(timeout)

                # SNMPv1 GET sysDescr.0 (1.3.6.1.2.1.1.1.0)
                pkt = (
                    b"\x30\x29"
                    b"\x02\x01\x00"  # version: SNMPv1
                    b"\x04" + bytes([len(community)])
                    + community.encode()
                    + b"\xa0\x1c"  # GET-request
                    b"\x02\x04\x00\x00\x00\x01"  # request-id
                    b"\x02\x01\x00"  # error-status
                    b"\x02\x01\x00"  # error-index
                    b"\x30\x0e\x30\x0c"
                    b"\x06\x08\x2b\x06\x01\x02\x01\x01\x01\x00"  # sysDescr OID
                    b"\x05\x00"  # NULL value
                )
                # Recalculate outer length
                inner = pkt[2:]
                pkt = b"\x30" + bytes([len(inner)]) + inner

                sock.sendto(pkt, (ip, port))
                data, _ = sock.recvfrom(4096)
                sock.close()

                if data and len(data) > 2:
                    results.append({
                        "ip": ip,
                        "community": community,
                        "status": "open",
                        "response_length": len(data),
                    })
            except socket.timeout:
                pass
            except Exception:
                pass

    found = [r for r in results if r.get("status") == "open"]
    return json.dumps({
        "target": target,
        "port": port,
        "communities_tested": comm_list,
        "found_count": len(found),
        "results": found,
    }, ensure_ascii=False, indent=2)


def _os_fingerprint(ctx: ToolContext, target: str,
                    aggressive: str = "false") -> str:
    """TCP/IP stack OS fingerprinting using nmap -O.

    target: IP or hostname.
    aggressive: 'true' for aggressive scan (-A), default 'false'.
    """
    cmd = ["nmap", "-O", "--osscan-guess"]
    if aggressive.lower() == "true":
        cmd = ["nmap", "-A"]
    cmd.append(target)

    result = _run_cmd(cmd, timeout=120)

    if "error" in result and "Command not found" in result["error"]:
        try:
            subprocess.run(
                ["apt-get", "install", "-y", "-qq", "nmap"],
                capture_output=True, timeout=120,
            )
        except Exception:
            pass
        result = _run_cmd(cmd, timeout=120)

    if "error" in result:
        return json.dumps(result, ensure_ascii=False, indent=2)

    output = result.get("output", "")
    os_matches = []
    for line in output.splitlines():
        if "OS details:" in line or "Running:" in line or "OS CPE:" in line:
            os_matches.append(line.strip())
        if "Aggressive OS guesses:" in line:
            os_matches.append(line.strip())

    return json.dumps({
        "target": target,
        "os_matches": os_matches,
        "raw": output[:8000],
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("ping_sweep", {
            "name": "ping_sweep",
            "description": "Discover live hosts on a subnet using ICMP ping sweep.",
            "parameters": {"type": "object", "properties": {
                "target": {"type": "string",
                           "description": "CIDR subnet or IP (e.g. '192.168.1.0/24')"},
                "threads": {"type": "integer", "default": 50},
                "timeout": {"type": "integer", "default": 1},
            }, "required": ["target"]},
        }, _ping_sweep),

        ToolEntry("arp_scan", {
            "name": "arp_scan",
            "description": "ARP-based LAN device discovery (layer 2, faster than ping).",
            "parameters": {"type": "object", "properties": {
                "target": {"type": "string",
                           "description": "CIDR subnet (e.g. '192.168.1.0/24')"},
                "interface": {"type": "string", "default": ""},
            }, "required": ["target"]},
        }, _arp_scan),

        ToolEntry("network_info", {
            "name": "network_info",
            "description": "List local network interfaces, IPs, routes, ARP table, DNS config.",
            "parameters": {"type": "object", "properties": {}},
        }, _network_info),

        ToolEntry("traceroute", {
            "name": "traceroute",
            "description": "Trace network path to target host.",
            "parameters": {"type": "object", "properties": {
                "target": {"type": "string", "description": "Hostname or IP"},
                "max_hops": {"type": "integer", "default": 30},
                "timeout": {"type": "integer", "default": 60},
            }, "required": ["target"]},
        }, _traceroute),

        ToolEntry("dns_recon", {
            "name": "dns_recon",
            "description": "DNS reconnaissance: zone transfer, record enumeration, reverse lookup.",
            "parameters": {"type": "object", "properties": {
                "target": {"type": "string", "description": "Domain name or IP"},
                "record_type": {"type": "string", "default": "ANY",
                                "description": "'A','AAAA','MX','NS','TXT','SOA','ANY','AXFR'"},
                "nameserver": {"type": "string", "default": ""},
            }, "required": ["target"]},
        }, _dns_recon),

        ToolEntry("netbios_scan", {
            "name": "netbios_scan",
            "description": "NetBIOS name scan for Windows host discovery.",
            "parameters": {"type": "object", "properties": {
                "target": {"type": "string",
                           "description": "IP, CIDR subnet, or hostname"},
                "timeout": {"type": "integer", "default": 10},
            }, "required": ["target"]},
        }, _netbios_scan),

        ToolEntry("snmp_scan", {
            "name": "snmp_scan",
            "description": "SNMP community string brute force and enumeration.",
            "parameters": {"type": "object", "properties": {
                "target": {"type": "string", "description": "IP or CIDR subnet"},
                "communities": {"type": "string",
                                "default": "public,private,community"},
                "port": {"type": "integer", "default": 161},
                "timeout": {"type": "integer", "default": 2},
            }, "required": ["target"]},
        }, _snmp_scan),

        ToolEntry("os_fingerprint", {
            "name": "os_fingerprint",
            "description": "TCP/IP stack OS fingerprinting using nmap -O.",
            "parameters": {"type": "object", "properties": {
                "target": {"type": "string", "description": "IP or hostname"},
                "aggressive": {"type": "string", "default": "false",
                               "description": "'true' for aggressive scan (-A)"},
            }, "required": ["target"]},
        }, _os_fingerprint),
    ]
