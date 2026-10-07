#!/usr/bin/env python3
"""Render an ONBOARDING-MEMORY scenario into a temporary file."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import socket
import subprocess
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE / "scenario.json"
PLACEHOLDER = "${ONBOARDING_LAB_HOST}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a temporary scenario with the VM hosts mapping IP resolved."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"canonical scenario to render (default: {DEFAULT_SOURCE})",
    )
    return parser.parse_args()


def validate_ip(value: str) -> str:
    address = value.strip()
    if not address:
        raise ValueError("ONBOARDING_LAB_HOST is empty")
    if "%" in address:
        raise ValueError("ONBOARDING_LAB_HOST must not contain an IPv6 scope identifier")
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise ValueError(
            "ONBOARDING_LAB_HOST must be an IP address without scheme, port, or path"
        ) from exc
    if parsed.is_loopback or parsed.is_unspecified or parsed.is_link_local or parsed.is_multicast:
        raise ValueError("ONBOARDING_LAB_HOST must be a usable non-loopback IP address")
    return str(parsed)


def command_output(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def usable_auto_ipv4(value: str) -> str | None:
    try:
        parsed = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        return None
    if parsed.is_loopback or parsed.is_unspecified or parsed.is_link_local or parsed.is_multicast:
        return None
    return str(parsed)


def unix_interface_candidates() -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []

    for line in command_output(["ip", "-o", "-4", "addr", "show", "scope", "global"]).splitlines():
        match = re.search(r"^\d+:\s+(\S+)\s+inet\s+(\d+(?:\.\d+){3})/", line)
        if match:
            interface = match.group(1).split("@", 1)[0]
            address = usable_auto_ipv4(match.group(2))
            if address:
                candidates.append((interface, address))

    current_interface = ""
    for line in command_output(["ifconfig"]).splitlines():
        if line and not line[0].isspace() and ":" in line:
            current_interface = line.split(":", 1)[0]
        match = re.search(r"\binet\s+(?:addr:)?(\d+(?:\.\d+){3})\b", line)
        if match and current_interface:
            address = usable_auto_ipv4(match.group(1))
            if address:
                candidates.append((current_interface, address))

    return candidates


def windows_interface_candidates() -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    current_interface = ""
    for line in command_output(["ipconfig"]).splitlines():
        stripped = line.strip()
        if line and not line[0].isspace() and stripped.endswith(":"):
            current_interface = stripped[:-1]
        if "IPv4" not in line:
            continue
        match = re.search(r"(\d+(?:\.\d+){3})", line)
        if match:
            address = usable_auto_ipv4(match.group(1))
            if address:
                candidates.append((current_interface or "ipconfig", address))
    return candidates


def default_route_ipv4() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect only consults the routing table; it sends no application data.
        sock.connect(("8.8.8.8", 80))
        return usable_auto_ipv4(sock.getsockname()[0])
    except OSError:
        return None
    finally:
        sock.close()


def hostname_candidates() -> list[tuple[str, str]]:
    try:
        addresses = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return []
    return [
        ("hostname", address)
        for value in addresses
        if (address := usable_auto_ipv4(value)) is not None
    ]


def candidate_score(interface: str, address: str, route_address: str | None) -> int:
    name = interface.lower()
    if "vmnet8" in name:
        score = 600
    elif name == "bridge100":
        score = 550
    elif name.startswith(("vmnet", "vmenet")):
        score = 500
    elif name.startswith("bridge"):
        score = 450
    elif name.startswith(("en", "eth", "wlan", "wlp")):
        score = 350
    elif name == "default-route":
        score = 325
    else:
        score = 100

    if route_address and address == route_address:
        score += 100
    if ipaddress.IPv4Address(address).is_private:
        score += 20
    return score


def detect_host_ip() -> tuple[str, str]:
    route_address = default_route_ipv4()
    candidates = unix_interface_candidates() + windows_interface_candidates()
    if route_address and not any(address == route_address for _, address in candidates):
        candidates.append(("default-route", route_address))
    candidates.extend(hostname_candidates())

    unique: dict[tuple[str, str], None] = {}
    for candidate in candidates:
        unique.setdefault(candidate, None)
    if not unique:
        raise ValueError(
            "could not auto-detect a VM-reachable host IP; set ONBOARDING_LAB_HOST "
            "to an IP address reachable from the OSWorld VM"
        )

    interface, address = max(
        unique,
        key=lambda item: candidate_score(item[0], item[1], route_address),
    )
    return address, f"auto-detected interface {interface}"


def resolve_host_ip() -> tuple[str, str]:
    override = os.environ.get("ONBOARDING_LAB_HOST", "").strip()
    if override:
        return validate_ip(override), "ONBOARDING_LAB_HOST override"
    return detect_host_ip()


def render_scenario(host_ip: str, source: Path = DEFAULT_SOURCE) -> str:
    scenario = json.loads(source.read_text(encoding="utf-8"))
    if "target_url" in scenario:
        raise ValueError("canonical scenario must not define target_url")

    config = scenario.get("config")
    if not isinstance(config, list) or not config:
        raise ValueError("canonical scenario config is empty")

    mapping = config[0]
    if not isinstance(mapping, dict):
        raise ValueError("the first setup step must be a JSON object")
    parameters = mapping.get("parameters", {})
    if not isinstance(parameters, dict):
        raise ValueError("the first setup step parameters must be a JSON object")
    command = parameters.get("command")
    if mapping.get("type") != "execute" or not isinstance(command, str):
        raise ValueError("the first setup step must be the VM hosts mapping command")
    if "/etc/hosts" not in command or "onboarding-lab.internal" not in command:
        raise ValueError("the first setup step does not map onboarding-lab.internal")
    if command.count(PLACEHOLDER) != 1:
        raise ValueError(f"the VM hosts mapping must contain exactly one {PLACEHOLDER}")

    parameters["command"] = command.replace(PLACEHOLDER, host_ip)
    rendered = json.dumps(scenario, indent=2, ensure_ascii=False) + "\n"
    if PLACEHOLDER in rendered:
        raise ValueError(f"unresolved placeholder remains: {PLACEHOLDER}")
    return rendered


def repository_root() -> Path | None:
    for directory in (HERE, *HERE.parents):
        if (directory / ".git").exists():
            return directory.resolve()
    return None


def write_temporary_scenario(rendered: str) -> Path:
    temporary_directory = Path(tempfile.gettempdir()).resolve()
    root = repository_root()
    if root and (temporary_directory == root or root in temporary_directory.parents):
        raise ValueError(
            f"system temporary directory must be outside the Git repository: {temporary_directory}"
        )

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix="onboarding-memory-",
        suffix=".json",
        dir=temporary_directory,
        delete=False,
    ) as temporary_file:
        temporary_file.write(rendered)
        return Path(temporary_file.name).resolve()


def main() -> None:
    args = parse_args()
    try:
        scenario_source = args.source.expanduser().resolve()
        if not scenario_source.is_file():
            raise ValueError(f"canonical scenario does not exist: {scenario_source}")
        host_ip, source = resolve_host_ip()
        rendered = render_scenario(host_ip, scenario_source)
        output = write_temporary_scenario(rendered)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from exc

    print(f"host IP: {host_ip} ({source})")
    print(f"canonical scenario: {scenario_source}")
    print(f"scenario: {output}")
    print(f"bind onboarding-lab to: {host_ip}:8080")


if __name__ == "__main__":
    main()
