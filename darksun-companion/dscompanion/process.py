"""Access to another process's memory.

Windows is the main target (ReadProcessMemory). Linux (/proc/<pid>/mem) is
supported too, mostly so the tool can be developed and tested there.
"""

import os
import sys
from typing import Iterator, List, NamedTuple, Tuple


class ProcessError(Exception):
    pass


class Region(NamedTuple):
    start: int
    size: int

    @property
    def end(self) -> int:
        return self.start + self.size


def find_dosbox_processes() -> List[Tuple[int, str]]:
    """(pid, executable name) for every running process that looks like DOSBox."""
    return [(pid, name) for pid, name in list_processes() if "dosbox" in name.lower()]


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _PROCESS_QUERY_INFORMATION = 0x0400
    _PROCESS_VM_READ = 0x0010
    _PROCESS_VM_WRITE = 0x0020
    _PROCESS_VM_OPERATION = 0x0008
    _MEM_COMMIT = 0x1000
    _PAGE_GUARD = 0x100
    _WRITABLE = 0x04 | 0x08 | 0x40 | 0x80  # READWRITE, WRITECOPY, EXECUTE_READWRITE, EXECUTE_WRITECOPY
    _TH32CS_SNAPPROCESS = 0x2
    _INVALID_HANDLE = ctypes.c_void_p(-1).value

    class _MemoryBasicInformation(ctypes.Structure):
        # ctypes alignment reproduces the padding of the 64-bit layout.
        _fields_ = [
            ("BaseAddress", ctypes.c_void_p),
            ("AllocationBase", ctypes.c_void_p),
            ("AllocationProtect", wintypes.DWORD),
            ("RegionSize", ctypes.c_size_t),
            ("State", wintypes.DWORD),
            ("Protect", wintypes.DWORD),
            ("Type", wintypes.DWORD),
        ]

    class _ProcessEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.VirtualQueryEx.argtypes = [
        wintypes.HANDLE, wintypes.LPCVOID, ctypes.POINTER(_MemoryBasicInformation), ctypes.c_size_t]
    _k32.VirtualQueryEx.restype = ctypes.c_size_t
    _k32.ReadProcessMemory.argtypes = [
        wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t)]
    _k32.ReadProcessMemory.restype = wintypes.BOOL
    _k32.WriteProcessMemory.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCVOID, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t)]
    _k32.WriteProcessMemory.restype = wintypes.BOOL
    _k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32)]
    _k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32)]
    _k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]

    def list_processes() -> List[Tuple[int, str]]:
        snap = _k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if snap in (None, _INVALID_HANDLE):
            raise ProcessError(f"CreateToolhelp32Snapshot failed ({ctypes.get_last_error()})")
        result = []
        entry = _ProcessEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        try:
            ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                result.append((entry.th32ProcessID, entry.szExeFile))
                ok = _k32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            _k32.CloseHandle(snap)
        return result

    class ProcessMemory:
        def __init__(self, pid: int):
            self.pid = pid
            self._handle = _k32.OpenProcess(
                _PROCESS_QUERY_INFORMATION | _PROCESS_VM_READ | _PROCESS_VM_WRITE | _PROCESS_VM_OPERATION,
                False, pid)
            if not self._handle:
                raise ProcessError(
                    f"Cannot open process {pid} (error {ctypes.get_last_error()}). "
                    "Use 64-bit Python for 64-bit DOSBox, and run as the same user.")

        def regions(self) -> Iterator[Region]:
            """Committed, writable, readable regions (where DOSBox keeps guest RAM)."""
            mbi = _MemoryBasicInformation()
            addr = 0
            while _k32.VirtualQueryEx(self._handle, addr, ctypes.byref(mbi), ctypes.sizeof(mbi)):
                base = mbi.BaseAddress or 0
                if (mbi.State == _MEM_COMMIT and mbi.Protect & _WRITABLE
                        and not mbi.Protect & _PAGE_GUARD):
                    yield Region(base, mbi.RegionSize)
                addr = base + mbi.RegionSize
                if addr >= sys.maxsize * 2:
                    break

        def read(self, addr: int, size: int) -> bytes:
            buf = ctypes.create_string_buffer(size)
            done = ctypes.c_size_t(0)
            if not _k32.ReadProcessMemory(self._handle, addr, buf, size, ctypes.byref(done)):
                raise ProcessError(
                    f"ReadProcessMemory at {addr:#x} failed ({ctypes.get_last_error()})")
            return buf.raw[:done.value]

        def write(self, addr: int, data: bytes) -> None:
            done = ctypes.c_size_t(0)
            if not _k32.WriteProcessMemory(self._handle, addr, data, len(data), ctypes.byref(done)) \
                    or done.value != len(data):
                raise ProcessError(
                    f"WriteProcessMemory at {addr:#x} failed ({ctypes.get_last_error()})")

        def is_alive(self) -> bool:
            code = wintypes.DWORD()
            _k32.GetExitCodeProcess(self._handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE

        def close(self) -> None:
            if self._handle:
                _k32.CloseHandle(self._handle)
                self._handle = None

else:

    def list_processes() -> List[Tuple[int, str]]:
        result = []
        for entry in os.listdir("/proc"):
            if entry.isdigit():
                try:
                    with open(f"/proc/{entry}/comm") as f:
                        result.append((int(entry), f.read().strip()))
                except OSError:
                    pass
        return result

    class ProcessMemory:
        def __init__(self, pid: int):
            self.pid = pid
            try:
                self._mem = open(f"/proc/{pid}/mem", "r+b", buffering=0)
            except OSError as e:
                raise ProcessError(
                    f"Cannot open memory of process {pid}: {e}. "
                    "You may need root, or kernel.yama.ptrace_scope=0.") from e

        def regions(self) -> Iterator[Region]:
            with open(f"/proc/{self.pid}/maps") as f:
                for line in f:
                    addrs, perms = line.split()[:2]
                    if perms.startswith("rw"):
                        start, end = (int(x, 16) for x in addrs.split("-"))
                        yield Region(start, end - start)

        def read(self, addr: int, size: int) -> bytes:
            try:
                self._mem.seek(addr)
                return self._mem.read(size)
            except (OSError, ValueError) as e:
                raise ProcessError(f"Read at {addr:#x} failed: {e}") from e

        def write(self, addr: int, data: bytes) -> None:
            try:
                self._mem.seek(addr)
                self._mem.write(data)
            except (OSError, ValueError) as e:
                raise ProcessError(f"Write at {addr:#x} failed: {e}") from e

        def is_alive(self) -> bool:
            return os.path.exists(f"/proc/{self.pid}")

        def close(self) -> None:
            self._mem.close()
