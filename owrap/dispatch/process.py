"""
Low-level process/port/server introspection -- no stored state of
its own beyond the short-lived health cache below.
"""
import os
import socket
import time

_health_cache: dict[str, tuple[bool, float]] = {}


def is_alive(pid: int) -> bool:
    """
    Return whether a process is still running.
    """
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def server_responsive(url: str, timeout: float = 3) -> bool:
    """
    True if a TCP connection to `url`'s host:port succeeds. Cached
    per 5-second bucket so repeated checks against the same URL
    don't each pay a fresh connect attempt.
    """
    now = time.time()
    cached = _health_cache.get(url)
    if cached is not None:
        alive, cached_ts = cached
        if now // 5 == cached_ts // 5:
            return alive
    try:
        addr = url.replace("http://", "").replace("https://", "")
        parts = addr.rsplit(":", 1)
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 4096
        with socket.create_connection((host, port), timeout=timeout):
            _health_cache[url] = (True, now)
            return True
    except (OSError, ValueError):
        _health_cache[url] = (False, now)
        return False


def find_port_pids(port: int) -> list:
    """
    Return PIDs listening on `port` by reading /proc/net/tcp (no
    external tools).
    """
    hex_port = format(port, '04X')
    inodes = set()
    for tcp_file in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            with open(tcp_file) as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 10:
                        continue
                    local_addr = parts[1]
                    state = parts[3]
                    inode = parts[9]
                    if state == '0A':  # LISTEN
                        port_hex = local_addr.split(':')[-1].upper()
                        if port_hex == hex_port:
                            inodes.add(inode)
        except OSError:
            pass
    if not inodes:
        return []
    pids = []
    try:
        for entry in os.listdir('/proc'):
            if not entry.isdigit():
                continue
            try:
                fd_dir = f'/proc/{entry}/fd'
                for fd in os.listdir(fd_dir):
                    try:
                        link = os.readlink(f'{fd_dir}/{fd}')
                        if link.startswith('socket:[') and link[8:-1] in inodes:
                            pids.append(int(entry))
                            break
                    except OSError:
                        pass
            except OSError:
                pass
    except OSError:
        pass
    return pids
