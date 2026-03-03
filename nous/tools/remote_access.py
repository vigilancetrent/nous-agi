"""Remote access tools for connecting to and controlling remote systems.

Provides SSH, SCP, SMB, WinRM, RDP, and Telnet capabilities
for authorized remote system management and penetration testing.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import socket
import threading
import time
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------

def _ensure_paramiko():
    """Lazy-import paramiko, auto-install if missing."""
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
    """Lazy-import impacket, auto-install if missing."""
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


def _ensure_pywinrm():
    """Lazy-import winrm, auto-install if missing."""
    try:
        import winrm
        return winrm
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "pywinrm"],
            capture_output=True, timeout=120,
        )
        import winrm
        return winrm


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


def _ssh_connect(host: str, port: int, username: str,
                 password: str = "", key_path: str = "",
                 timeout: int = 10):
    """Create and return a connected paramiko SSHClient."""
    paramiko = _ensure_paramiko()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    kwargs: Dict[str, Any] = {
        "hostname": host,
        "port": int(port),
        "username": username,
        "timeout": timeout,
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


# ---------------------------------------------------------------------------
# SSH tools
# ---------------------------------------------------------------------------

def _ssh_exec(ctx: ToolContext, host: str, username: str,
              command: str, password: str = "", key_path: str = "",
              port: int = 22, timeout: int = 30) -> str:
    """Execute a command on a remote host via SSH.

    host: target IP or hostname.
    username: SSH username.
    command: shell command to execute.
    password: password (if not using key).
    key_path: path to SSH private key.
    port: SSH port (default 22).
    """
    try:
        client = _ssh_connect(host, int(port), username, password,
                              key_path, timeout=int(timeout))
        stdin, stdout, stderr = client.exec_command(
            command, timeout=int(timeout),
        )
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        client.close()

        if len(out) > 50000:
            out = out[:25000] + "\n...(truncated)...\n" + out[-25000:]

        return json.dumps({
            "host": host, "command": command,
            "exit_code": exit_code,
            "stdout": out,
            "stderr": err[:5000] if err else "",
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "host": host})


def _ssh_interactive(ctx: ToolContext, host: str, username: str,
                     commands: str, password: str = "",
                     key_path: str = "", port: int = 22,
                     timeout: int = 30) -> str:
    """Execute multiple commands in a single SSH session (preserves state).

    commands: newline-separated list of commands to run sequentially.
    """
    try:
        client = _ssh_connect(host, int(port), username, password,
                              key_path, timeout=int(timeout))
        channel = client.invoke_shell()
        time.sleep(0.5)

        outputs = []
        for cmd in commands.strip().split("\n"):
            cmd = cmd.strip()
            if not cmd:
                continue
            channel.send(cmd + "\n")
            time.sleep(1)
            buf = b""
            while channel.recv_ready():
                buf += channel.recv(65536)
                time.sleep(0.1)
            outputs.append({
                "command": cmd,
                "output": buf.decode("utf-8", errors="replace"),
            })

        channel.close()
        client.close()

        return json.dumps({
            "host": host, "results": outputs,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "host": host})


def _scp_transfer(ctx: ToolContext, host: str, username: str,
                  remote_path: str, local_path: str = "",
                  direction: str = "download", password: str = "",
                  key_path: str = "", port: int = 22) -> str:
    """Upload or download files via SFTP/SCP.

    direction: 'download' or 'upload'.
    remote_path: path on the remote host.
    local_path: local path. For download, defaults to /tmp/<filename>.
    """
    try:
        client = _ssh_connect(host, int(port), username, password, key_path)
        sftp = client.open_sftp()

        if direction == "download":
            if not local_path:
                local_path = "/tmp/" + os.path.basename(remote_path)
            sftp.get(remote_path, local_path)
            stat = os.stat(local_path)
            result = {
                "action": "download", "host": host,
                "remote_path": remote_path, "local_path": local_path,
                "size_bytes": stat.st_size,
            }
        else:
            sftp.put(local_path, remote_path)
            rstat = sftp.stat(remote_path)
            result = {
                "action": "upload", "host": host,
                "local_path": local_path, "remote_path": remote_path,
                "size_bytes": rstat.st_size,
            }

        sftp.close()
        client.close()
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "host": host})


def _ssh_tunnel(ctx: ToolContext, host: str, username: str,
                tunnel_type: str = "local", local_port: int = 8080,
                remote_host: str = "127.0.0.1", remote_port: int = 80,
                password: str = "", key_path: str = "",
                port: int = 22, duration: int = 300) -> str:
    """Create an SSH port forward tunnel.

    tunnel_type: 'local' (L), 'remote' (R), or 'dynamic' (D/SOCKS).
    local_port: local bind port.
    remote_host: target host (from SSH server's perspective).
    remote_port: target port.
    duration: tunnel lifetime in seconds (default 300).
    """
    try:
        paramiko = _ensure_paramiko()
        client = _ssh_connect(host, int(port), username, password, key_path)
        transport = client.get_transport()

        local_port = int(local_port)
        remote_port = int(remote_port)
        duration = min(int(duration), 3600)

        if tunnel_type == "local":
            # Local port forward: localhost:local_port -> remote_host:remote_port
            transport.request_port_forward("", local_port)

            def _forward():
                time.sleep(duration)
                transport.cancel_port_forward("", local_port)
                client.close()

            t = threading.Thread(target=_forward, daemon=True)
            t.start()

            return json.dumps({
                "tunnel_type": "local",
                "bind": f"localhost:{local_port}",
                "target": f"{remote_host}:{remote_port}",
                "duration_sec": duration,
                "status": "active",
            }, ensure_ascii=False, indent=2)

        elif tunnel_type == "dynamic":
            # SOCKS proxy via SSH
            transport.request_port_forward("", local_port)

            def _forward():
                time.sleep(duration)
                client.close()

            t = threading.Thread(target=_forward, daemon=True)
            t.start()

            return json.dumps({
                "tunnel_type": "dynamic_socks",
                "socks_bind": f"localhost:{local_port}",
                "duration_sec": duration,
                "status": "active",
                "usage": f"Use SOCKS5 proxy at 127.0.0.1:{local_port}",
            }, ensure_ascii=False, indent=2)

        else:
            # Remote port forward
            transport.request_port_forward(remote_host, remote_port)

            def _forward():
                time.sleep(duration)
                client.close()

            t = threading.Thread(target=_forward, daemon=True)
            t.start()

            return json.dumps({
                "tunnel_type": "remote",
                "remote_bind": f"{remote_host}:{remote_port}",
                "forward_to": f"localhost:{local_port}",
                "duration_sec": duration,
                "status": "active",
            }, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e), "host": host})


# ---------------------------------------------------------------------------
# SMB tools
# ---------------------------------------------------------------------------

def _smb_enum(ctx: ToolContext, host: str, username: str = "",
              password: str = "", domain: str = "") -> str:
    """Enumerate SMB shares and permissions on a target host.

    host: target IP or hostname.
    username/password: credentials (empty for null session).
    """
    cmd = ["smbclient", "-L", host, "-N"]
    if username:
        cmd = ["smbclient", "-L", host, "-U",
               f"{domain + '/' if domain else ''}{username}%{password}"]

    result = _run_cmd(cmd, timeout=30)

    if "error" in result and "Command not found" in result["error"]:
        try:
            subprocess.run(["apt-get", "install", "-y", "-qq", "smbclient"],
                           capture_output=True, timeout=120)
        except Exception:
            pass
        result = _run_cmd(cmd, timeout=30)

    if "error" in result:
        return json.dumps(result, ensure_ascii=False, indent=2)

    # Parse shares from output
    shares = []
    for line in result.get("output", "").splitlines():
        line = line.strip()
        if "\tDisk" in line or "\tIPC" in line or "\tPrinter" in line:
            parts = line.split("\t")
            if parts:
                shares.append({
                    "name": parts[0].strip(),
                    "type": parts[1].strip() if len(parts) > 1 else "",
                    "comment": parts[2].strip() if len(parts) > 2 else "",
                })

    return json.dumps({
        "host": host, "share_count": len(shares),
        "shares": shares,
        "raw": result.get("output", "")[:5000],
    }, ensure_ascii=False, indent=2)


def _smb_access(ctx: ToolContext, host: str, share: str,
                action: str = "list", remote_path: str = "/",
                local_path: str = "", username: str = "",
                password: str = "", domain: str = "") -> str:
    """Read, write, or list files on SMB shares.

    action: 'list', 'get' (download), 'put' (upload).
    share: share name (e.g. 'C$', 'Users').
    remote_path: path within the share.
    """
    auth = f"{domain + '/' if domain else ''}{username}%{password}" if username else "guest%"
    svc = f"//{host}/{share}"

    if action == "list":
        smb_cmd = f'ls "{remote_path}/*"'
        cmd = ["smbclient", svc, "-U", auth, "-c", smb_cmd]
    elif action == "get":
        if not local_path:
            local_path = "/tmp/" + os.path.basename(remote_path)
        smb_cmd = f'get "{remote_path}" "{local_path}"'
        cmd = ["smbclient", svc, "-U", auth, "-c", smb_cmd]
    elif action == "put":
        smb_cmd = f'put "{local_path}" "{remote_path}"'
        cmd = ["smbclient", svc, "-U", auth, "-c", smb_cmd]
    else:
        return json.dumps({"error": f"Unknown action: {action}"})

    result = _run_cmd(cmd, timeout=30)
    if "error" in result:
        return json.dumps(result, ensure_ascii=False, indent=2)

    return json.dumps({
        "host": host, "share": share, "action": action,
        "path": remote_path,
        "output": result.get("output", "")[:5000],
    }, ensure_ascii=False, indent=2)


def _smb_exec(ctx: ToolContext, host: str, username: str,
              password: str, command: str, domain: str = "",
              hashes: str = "") -> str:
    """Execute commands via SMB (PsExec-style) using impacket.

    host: target IP or hostname.
    command: command to execute on target.
    hashes: NTLM hash 'LM:NT' for pass-the-hash (instead of password).
    """
    try:
        _ensure_impacket()
        from impacket.smbconnection import SMBConnection
        from impacket.examples.smbexec import SMBEXEC

        executer = SMBEXEC(
            command, None, None,
            domain if domain else ".",
            username, password,
            hashes if hashes else None,
            None, None,
        )
        executer.run(host, host)

        return json.dumps({
            "host": host, "command": command,
            "status": "executed",
            "method": "smbexec",
        }, ensure_ascii=False, indent=2)
    except ImportError as e:
        return json.dumps({"error": f"impacket import failed: {e}"})
    except Exception as e:
        return json.dumps({"error": str(e), "host": host})


def _winrm_exec(ctx: ToolContext, host: str, username: str,
                password: str, command: str,
                transport: str = "ntlm",
                use_ssl: str = "false") -> str:
    """Execute commands via WinRM on Windows targets.

    host: target IP or hostname.
    command: command or PowerShell script to execute.
    transport: 'ntlm', 'kerberos', 'basic'.
    use_ssl: 'true' for HTTPS (port 5986), 'false' for HTTP (port 5985).
    """
    try:
        winrm = _ensure_pywinrm()
        import winrm as winrm_mod

        scheme = "https" if use_ssl.lower() == "true" else "http"
        port = 5986 if use_ssl.lower() == "true" else 5985
        endpoint = f"{scheme}://{host}:{port}/wsman"

        session = winrm_mod.Session(
            endpoint, auth=(username, password),
            transport=transport,
            server_cert_validation="ignore",
        )

        result = session.run_cmd(command)
        stdout = result.std_out.decode("utf-8", errors="replace")
        stderr = result.std_err.decode("utf-8", errors="replace")

        return json.dumps({
            "host": host, "command": command,
            "exit_code": result.status_code,
            "stdout": stdout[:10000],
            "stderr": stderr[:5000] if stderr else "",
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "host": host})


def _rdp_check(ctx: ToolContext, host: str, port: int = 3389,
               timeout: int = 5) -> str:
    """Check RDP availability on target host.

    host: target IP or hostname.
    port: RDP port (default 3389).
    """
    port = int(port)
    timeout = min(int(timeout), 30)
    result: Dict[str, Any] = {"host": host, "port": port}

    # TCP connect check
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        # Read RDP banner
        banner = sock.recv(1024)
        sock.close()
        result["rdp_open"] = True
        result["banner_hex"] = banner[:64].hex()
        if banner[:4] == b"\x03\x00":
            result["protocol"] = "RDP/TPKT"
    except socket.timeout:
        result["rdp_open"] = False
        result["reason"] = "timeout"
    except ConnectionRefusedError:
        result["rdp_open"] = False
        result["reason"] = "connection_refused"
    except Exception as e:
        result["rdp_open"] = False
        result["reason"] = str(e)

    # Try xfreerdp check if available
    if result.get("rdp_open"):
        xfree_cmd = [
            "xfreerdp", f"/v:{host}", f"/port:{port}",
            "/cert:ignore", "+auth-only",
            "/u:probe", "/p:probe",
            "/sec:nla",
        ]
        r = _run_cmd(xfree_cmd, timeout=10)
        if "error" not in r:
            result["nla_enabled"] = "NLA" in r.get("output", "")
            result["xfreerdp_output"] = r.get("output", "")[:2000]

    return json.dumps(result, ensure_ascii=False, indent=2)


def _telnet_exec(ctx: ToolContext, host: str, command: str = "",
                 username: str = "", password: str = "",
                 port: int = 23, timeout: int = 10) -> str:
    """Connect and execute commands via Telnet.

    host: target IP or hostname.
    command: command to execute after login.
    username/password: login credentials.
    """
    port = int(port)
    timeout = min(int(timeout), 60)

    try:
        import telnetlib
        tn = telnetlib.Telnet(host, port, timeout=timeout)

        output_parts = []

        if username:
            tn.read_until(b"login: ", timeout=timeout)
            tn.write(username.encode() + b"\n")

        if password:
            tn.read_until(b"assword: ", timeout=timeout)
            tn.write(password.encode() + b"\n")

        if username or password:
            time.sleep(1)
            output_parts.append(tn.read_very_eager().decode(
                "utf-8", errors="replace"))

        if command:
            for cmd in command.split(";"):
                cmd = cmd.strip()
                if cmd:
                    tn.write(cmd.encode() + b"\n")
                    time.sleep(1)
                    output_parts.append(tn.read_very_eager().decode(
                        "utf-8", errors="replace"))

        tn.write(b"exit\n")
        time.sleep(0.5)
        output_parts.append(tn.read_all().decode("utf-8", errors="replace"))
        tn.close()

        full_output = "\n".join(output_parts)
        if len(full_output) > 50000:
            full_output = (full_output[:25000]
                           + "\n...(truncated)...\n"
                           + full_output[-25000:])

        return json.dumps({
            "host": host, "port": port,
            "output": full_output,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "host": host})


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("ssh_exec", {
            "name": "ssh_exec",
            "description": "Execute a command on a remote host via SSH.",
            "parameters": {"type": "object", "properties": {
                "host": {"type": "string", "description": "Target IP or hostname"},
                "username": {"type": "string"},
                "command": {"type": "string", "description": "Shell command to run"},
                "password": {"type": "string", "default": ""},
                "key_path": {"type": "string", "default": ""},
                "port": {"type": "integer", "default": 22},
                "timeout": {"type": "integer", "default": 30},
            }, "required": ["host", "username", "command"]},
        }, _ssh_exec),

        ToolEntry("ssh_interactive", {
            "name": "ssh_interactive",
            "description": "Execute multiple commands in a single SSH session (preserves state/env).",
            "parameters": {"type": "object", "properties": {
                "host": {"type": "string"},
                "username": {"type": "string"},
                "commands": {"type": "string",
                             "description": "Newline-separated commands"},
                "password": {"type": "string", "default": ""},
                "key_path": {"type": "string", "default": ""},
                "port": {"type": "integer", "default": 22},
                "timeout": {"type": "integer", "default": 30},
            }, "required": ["host", "username", "commands"]},
        }, _ssh_interactive),

        ToolEntry("scp_transfer", {
            "name": "scp_transfer",
            "description": "Upload or download files via SFTP/SCP.",
            "parameters": {"type": "object", "properties": {
                "host": {"type": "string"},
                "username": {"type": "string"},
                "remote_path": {"type": "string"},
                "local_path": {"type": "string", "default": ""},
                "direction": {"type": "string", "default": "download",
                              "description": "'download' or 'upload'"},
                "password": {"type": "string", "default": ""},
                "key_path": {"type": "string", "default": ""},
                "port": {"type": "integer", "default": 22},
            }, "required": ["host", "username", "remote_path"]},
        }, _scp_transfer),

        ToolEntry("ssh_tunnel", {
            "name": "ssh_tunnel",
            "description": "Create SSH port forward tunnel (local/remote/dynamic SOCKS).",
            "parameters": {"type": "object", "properties": {
                "host": {"type": "string"},
                "username": {"type": "string"},
                "tunnel_type": {"type": "string", "default": "local",
                                "description": "'local', 'remote', or 'dynamic'"},
                "local_port": {"type": "integer", "default": 8080},
                "remote_host": {"type": "string", "default": "127.0.0.1"},
                "remote_port": {"type": "integer", "default": 80},
                "password": {"type": "string", "default": ""},
                "key_path": {"type": "string", "default": ""},
                "port": {"type": "integer", "default": 22},
                "duration": {"type": "integer", "default": 300},
            }, "required": ["host", "username"]},
        }, _ssh_tunnel),

        ToolEntry("smb_enum", {
            "name": "smb_enum",
            "description": "Enumerate SMB shares and permissions on a target host.",
            "parameters": {"type": "object", "properties": {
                "host": {"type": "string"},
                "username": {"type": "string", "default": ""},
                "password": {"type": "string", "default": ""},
                "domain": {"type": "string", "default": ""},
            }, "required": ["host"]},
        }, _smb_enum),

        ToolEntry("smb_access", {
            "name": "smb_access",
            "description": "Read, write, or list files on SMB shares.",
            "parameters": {"type": "object", "properties": {
                "host": {"type": "string"},
                "share": {"type": "string", "description": "Share name (e.g. 'C$')"},
                "action": {"type": "string", "default": "list",
                           "description": "'list', 'get', or 'put'"},
                "remote_path": {"type": "string", "default": "/"},
                "local_path": {"type": "string", "default": ""},
                "username": {"type": "string", "default": ""},
                "password": {"type": "string", "default": ""},
                "domain": {"type": "string", "default": ""},
            }, "required": ["host", "share"]},
        }, _smb_access),

        ToolEntry("smb_exec", {
            "name": "smb_exec",
            "description": "Execute commands via SMB (PsExec-style) using impacket.",
            "parameters": {"type": "object", "properties": {
                "host": {"type": "string"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                "command": {"type": "string"},
                "domain": {"type": "string", "default": ""},
                "hashes": {"type": "string", "default": "",
                           "description": "NTLM hash 'LM:NT' for pass-the-hash"},
            }, "required": ["host", "username", "password", "command"]},
        }, _smb_exec),

        ToolEntry("winrm_exec", {
            "name": "winrm_exec",
            "description": "Execute commands via WinRM on Windows targets.",
            "parameters": {"type": "object", "properties": {
                "host": {"type": "string"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                "command": {"type": "string"},
                "transport": {"type": "string", "default": "ntlm",
                              "description": "'ntlm', 'kerberos', 'basic'"},
                "use_ssl": {"type": "string", "default": "false"},
            }, "required": ["host", "username", "password", "command"]},
        }, _winrm_exec),

        ToolEntry("rdp_check", {
            "name": "rdp_check",
            "description": "Check RDP availability and probe NLA on target host.",
            "parameters": {"type": "object", "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer", "default": 3389},
                "timeout": {"type": "integer", "default": 5},
            }, "required": ["host"]},
        }, _rdp_check),

        ToolEntry("telnet_exec", {
            "name": "telnet_exec",
            "description": "Connect and execute commands via Telnet.",
            "parameters": {"type": "object", "properties": {
                "host": {"type": "string"},
                "command": {"type": "string", "default": ""},
                "username": {"type": "string", "default": ""},
                "password": {"type": "string", "default": ""},
                "port": {"type": "integer", "default": 23},
                "timeout": {"type": "integer", "default": 10},
            }, "required": ["host"]},
        }, _telnet_exec),
    ]
