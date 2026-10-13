"""Small redacted Linux runtime samples. Importing performs no probes.

RSS values describe mappings and must not be summed as physical memory. Drive
mount disk counters are filesystem reports, not an authoritative account quota.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8")[:65536]
    except (OSError, UnicodeError):
        return None


def _memory_fields(path, wanted):
    text = _read(path)
    if text is None:
        return None
    result = {}
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key in wanted:
            parts = value.split()
            if parts and parts[0].isdigit():
                result[key] = int(parts[0]) * (1024 if len(parts) > 1 and parts[1] == "kB" else 1)
    return result


def _cgroup(root=Path("/sys/fs/cgroup")):
    membership = _read("/proc/self/cgroup")
    if membership is None:
        return None
    relative = next((line[3:] for line in membership.splitlines() if line.startswith("0::")), None)
    if relative is None:
        return {"version": "v2 counters unavailable", "effectiveLimitVerified": False}
    root = Path(root).resolve()
    base = (root / relative.lstrip("/")).resolve()
    if not base.is_relative_to(root):
        return {"effectiveLimitVerified": False}
    levels = []
    while True:
        counters = {}
        for name in ("memory.max", "memory.current", "memory.peak", "memory.swap.current"):
            value = _read(base / name)
            counters[name] = int(value.strip()) if value and value.strip().isdigit() else (value.strip() if value else None)
        events = _read(base / "memory.events")
        counters["memory.events"] = None if events is None else {}
        for line in (events or "").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit():
                counters["memory.events"][parts[0]] = int(parts[1])
        levels.append(counters)
        if base == root:
            break
        base = base.parent
    limits, headroom = [], []
    verified = True
    for level in levels:
        maximum, current = level["memory.max"], level["memory.current"]
        if type(maximum) is int:
            limits.append(maximum)
            if type(current) is int:
                headroom.append(max(0, maximum - current))
            else:
                verified = False
        elif maximum != "max":
            verified = False
    # A leaf declaring max can still have a tighter parent. Parent current
    # includes sibling usage, so its remaining headroom also bounds this process.
    return {**levels[0], "ancestors": levels[1:], "effectiveLimitVerified": verified,
            "effectiveLimitBytes": min(limits) if limits else None,
            "effectiveHeadroomBytes": min(headroom) if headroom else None,
            "scope": "process membership and accessible ancestors; inaccessible bounds remain unverified"}


def available_memory():
    host = _memory_fields("/proc/meminfo", {"MemAvailable"})
    group = _cgroup()
    if not host or not group or not group.get("effectiveLimitVerified"):
        return 0
    available = host.get("MemAvailable", 0)
    headroom = group.get("effectiveHeadroomBytes")
    return min(available, headroom) if type(headroom) is int else available


def snapshot(*, pids=(), disks=()) -> dict:
    result = {"sampledAtMillis": int(time.time() * 1000), "os": platform.system(),
        "architecture": platform.machine(), "glibc": list(platform.libc_ver()),
        "python": platform.python_version(), "hostMemoryBytes": _memory_fields("/proc/meminfo",
            {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}), "cgroup": _cgroup(),
        "processes": [], "gpu": None, "disks": [],
        "rssCaution": "Shared/file mappings are not additive physical RAM; unavailable counters are null."}
    for pid in sorted({os.getpid(), *(int(p) for p in pids if p is not None)}):
        result["processes"].append({"pid": pid,
            "memoryBytes": _memory_fields(f"/proc/{pid}/status",
                {"VmRSS", "VmHWM", "VmSwap", "RssAnon", "RssFile", "RssShmem"})})
    try:
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,compute_cap,driver_version,memory.total,memory.free,memory.used",
            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
        if gpu.returncode == 0:
            result["gpu"] = []
            for line in gpu.stdout[:4096].splitlines():
                values = [value.strip() for value in line.split(",")]
                if len(values) == 6:
                    result["gpu"].append(dict(zip(("name", "computeCapability", "driver", "totalMiB", "freeMiB", "usedMiB"), values)))
        else:
            result["gpuProbe"] = {"available": False, "returnCode": gpu.returncode}
    except (OSError, subprocess.TimeoutExpired):
        result["gpuProbe"] = {"available": False}
    for label, path in disks:
        try:
            usage = shutil.disk_usage(path)
            result["disks"].append({"label": label, "totalBytes": usage.total, "freeBytes": usage.free,
                "scope": "filesystem counter; persistent account quota must be checked separately"})
        except OSError:
            result["disks"].append({"label": label, "available": False})
    return result


def write_snapshot(path, **kwargs):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snapshot(**kwargs), indent=2) + "\n", encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target


if __name__ == "__main__":
    print(json.dumps(snapshot(pids=[int(value) for value in sys.argv[1:]]), indent=2))
