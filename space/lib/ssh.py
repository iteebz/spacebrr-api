
import argparse
import socket
import subprocess
import sys
from pathlib import Path

from space.lib.commands import echo, fail, space_cmd

_DEFAULT_SSH_DIR = Path.home() / ".ssh"
_DEFAULT_KEY_NAME = "space"


@space_cmd("ssh")
def main() -> None:
    parser = argparse.ArgumentParser(prog="ssh", description="Remote shell access")
    subs = parser.add_subparsers(dest="cmd")

    connect_p = subs.add_parser("connect", help="SSH to remote host")
    connect_p.add_argument("host", help="user@host or alias")
    connect_p.add_argument("-i", "--key", help="SSH key path")
    connect_p.add_argument("-p", "--port", type=int, default=22, help="SSH port")

    keygen_p = subs.add_parser("keygen", help="Generate SSH key")
    keygen_p.add_argument("name", nargs="?", default=_DEFAULT_KEY_NAME, help="Key name")
    keygen_p.add_argument("-o", "--output", help="Output directory")

    copyid_p = subs.add_parser("copy-id", help="Copy SSH public key to remote host")
    copyid_p.add_argument("host", help="user@host")
    copyid_p.add_argument("-i", "--key", help="Public key path")

    subs.add_parser("host", help="Show your machine's IP addresses")

    config_p = subs.add_parser("config", help="Manage SSH config")
    config_p.add_argument("-s", "--show", action="store_true", help="Show SSH config")

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        sys.exit(0)

    if args.cmd == "connect":
        _connect(args.host, args.key, args.port)
    elif args.cmd == "keygen":
        _keygen(args.name, args.output)
    elif args.cmd == "copy-id":
        _copy_id(args.host, args.key)
    elif args.cmd == "host":
        _host()
    elif args.cmd == "config":
        _config(args.show)


def _connect(host: str, key: str | None, port: int) -> None:
    cmd = ["ssh"]
    if key:
        cmd.extend(["-i", key])
    if port != 22:
        cmd.extend(["-p", str(port)])
    cmd.append(host)

    try:
        sys.exit(subprocess.call(cmd))
    except KeyboardInterrupt:
        sys.exit(130)


def _keygen(name: str, output: str | None) -> None:
    ssh_dir = Path(output) if output else _DEFAULT_SSH_DIR
    key_path = ssh_dir / name
    if key_path.exists():
        fail(f"Key already exists: {key_path}")

    ssh_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ssh-keygen",
        "-t",
        "ed25519",
        "-f",
        str(key_path),
        "-C",
        f"space-{name}",
        "-N",
        "",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        fail(f"Failed to generate key: {result.stderr}")

    echo(f"Generated key: {key_path}")
    echo(f"Public key: {key_path}.pub")
    echo("\nAdd public key to remote ~/.ssh/authorized_keys:")
    echo(f"  cat {key_path}.pub | ssh user@host 'cat >> ~/.ssh/authorized_keys'")


def _copy_id(host: str, key: str | None) -> None:
    key_path = Path(key) if key else (_DEFAULT_SSH_DIR / f"{_DEFAULT_KEY_NAME}.pub")
    if not key_path.exists():
        echo(f"Key not found: {key_path}", err=True)
        fail("Generate one with: space ssh keygen")

    cmd = ["ssh-copy-id", "-i", str(key_path), host]
    try:
        sys.exit(subprocess.call(cmd))
    except KeyboardInterrupt:
        sys.exit(130)


def _host() -> None:
    hostname = socket.gethostname()

    result = subprocess.run(["ifconfig"], capture_output=True, text=True, check=False)

    if result.returncode != 0:
        fail("Failed to get network info")

    ips = []
    for line in result.stdout.split("\n"):
        line = line.strip()
        if line.startswith("inet ") and not line.startswith("inet 127."):
            parts = line.split()
            if len(parts) >= 2:
                ip = parts[1]
                ips.append(ip)

    echo(f"Hostname: {hostname}")
    echo("\nLocal IP addresses:")
    for ip in ips:
        echo(f"  {ip}")

    if not ips:
        echo("  (no network interfaces found)")

    echo("\nShare one of these with your wife:")
    echo("  space ssh copy-id <username>@<ip>")


def _config(show: bool) -> None:
    ssh_config = Path.home() / ".ssh/config"

    if show:
        if not ssh_config.exists():
            fail("No SSH config found")
        echo(ssh_config.read_text())
        return

    echo("Add to ~/.ssh/config:")
    echo(
        """
Host tyson-space
    HostName <your-server-ip>
    User <username>
    IdentityFile ~/.ssh/space
    Port 22

# Then: space ssh connect tyson-space
"""
    )
