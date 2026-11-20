"""跨进程身份探针：只读判定 PID 是否存活，并给出该 PID 的进程启动标记。

用途：账本文件锁与 run 级租约的 stale 回收。仅凭 mtime 回收会误删"慢但仍活着"的
持有者，造成双写窗口；这里把"是否 stale"改为可证明的进程事实：

- ``alive == False``：进程不存在 → 租约可回收；
- ``alive == True`` 且记录的启动标记与当前不一致 → PID 被复用（旧持有者已死）→ 可回收；
- 其余情况一律视为仍被持有（fail closed；宁可在 ``lock_timeout`` 后报错，也不并发写）。

实现只用标准库：
- Windows：``OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`` + ``GetExitCodeProcess`` +
  ``GetProcessTimes``（FILETIME 创建时间）；
- Linux：``/proc/<pid>/stat`` 的 starttime（字段 22，开机后时钟滴答数）；
- 其他 POSIX（无 /proc）：``os.kill(pid, 0)`` 只判存活，启动标记为 None。

本模块只读系统状态，不写文件、不建进程、不联网。
"""

from __future__ import annotations

import os
from typing import Any

__all__ = ["process_alive", "process_identity", "process_start_marker"]

_IS_WINDOWS = os.name == "nt"
if _IS_WINDOWS:  # pragma: no branch - 平台分支
    import ctypes
    from ctypes import wintypes

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _ERROR_ACCESS_DENIED = 5
    _STILL_ACTIVE = 259
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]

    def _windows_identity(pid: int) -> tuple[bool, str | None]:
        handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            # 拒绝访问说明进程存在但不可查询：保守当"活着"，启动标记未知。
            if ctypes.get_last_error() == _ERROR_ACCESS_DENIED:
                return (True, None)
            return (False, None)
        try:
            code = wintypes.DWORD()
            if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return (True, None)
            if code.value != _STILL_ACTIVE:
                return (False, None)
            created = wintypes.FILETIME()
            exited = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            ok = _kernel32.GetProcessTimes(
                handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            )
            if not ok:
                return (True, None)
            stamp = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
            return (True, f"win:{stamp:016x}")
        finally:
            _kernel32.CloseHandle(handle)


_BOOT_ID: str | None = None


def _boot_id() -> str:
    """Linux 开机标识：避免重启后"同 PID + 同 starttime"被误认成同一进程。"""
    global _BOOT_ID
    if _BOOT_ID is None:
        try:
            with open("/proc/sys/kernel/random/boot_id", encoding="ascii") as handle:
                _BOOT_ID = handle.read().strip()
        except OSError:
            _BOOT_ID = ""
    return _BOOT_ID


def _posix_identity(pid: int) -> tuple[bool, str | None]:
    try:
        with open(f"/proc/{int(pid)}/stat", "rb") as handle:
            raw = handle.read()
    except FileNotFoundError:
        return (False, None)
    except OSError:
        return (True, None)
    try:
        # 字段 1=pid、2=comm（可能含空格/括号），从最后一个右括号之后开始数。
        tail = raw[raw.rindex(b")") + 2 :].split()
        starttime = tail[19]  # 字段 22：starttime（字段 3 起，索引 19）
        return (True, "nix:" + _boot_id() + ":" + starttime.decode("ascii"))
    except (ValueError, IndexError, UnicodeDecodeError):
        return (True, None)


def _posix_process_identity(pid: int) -> tuple[bool, str | None]:
    if os.path.isdir("/proc"):
        return _posix_identity(pid)
    try:
        os.kill(int(pid), 0)  # POSIX 下 signal 0 只做权限/存在性检查
    except ProcessLookupError:
        return (False, None)
    except PermissionError:
        return (True, None)
    except OSError:
        return (False, None)
    return (True, None)


def process_identity(pid: Any) -> tuple[bool, str | None]:
    """返回 ``(是否存活, 启动标记)``；标记只在能读到时给出，读不到为 None。"""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return (False, None)
    try:
        if _IS_WINDOWS:
            return _windows_identity(pid)
        return _posix_process_identity(pid)
    except OSError:
        # 探针自身失败不能把"未知"说成"已死"：保守返回"活着但标记未知"。
        return (True, None)


def process_alive(pid: Any) -> bool:
    return process_identity(pid)[0]


def process_start_marker(pid: Any) -> str | None:
    return process_identity(pid)[1]
