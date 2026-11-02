"""Handle-based storage I/O for user-selected local media roots.

The selected root may be an external disk/UNC path. Each file access is
confined to that root at the actual handle, not just at a prior path check.
"""
import ctypes
import ntpath
import os
import stat


class UnsafeStoragePath(ValueError):
    """The selected media entry is outside its configured storage root."""


def _contained(root, path):
    try:
        root = os.path.realpath(root)
        path = os.path.realpath(path)
        return os.path.commonpath([root, path]) == root
    except (ValueError, OSError):
        return False


def _contained_with_fixed_root(trusted_root, path):
    """Compare with the *pre-open* root, never a re-resolved mutable root."""
    try:
        return os.path.commonpath([trusted_root, os.path.realpath(path)]) == trusted_root
    except (ValueError, OSError):
        return False


def _parts_beneath(root, path, *, follow_final=True, root_is_resolved=False):
    root_abs = os.path.abspath(root) if root_is_resolved else os.path.realpath(root)
    candidate = os.path.realpath(path) if follow_final else os.path.abspath(path)
    try:
        rel = os.path.relpath(candidate, root_abs)
    except ValueError as exc:
        raise UnsafeStoragePath("storage path crosses volumes") from exc
    parts = rel.split(os.sep)
    if rel in {"", "."} or any(p in {"", ".", ".."} for p in parts):
        raise UnsafeStoragePath("storage path is outside the root")
    if os.path.commonpath([root_abs, candidate]) != root_abs:
        raise UnsafeStoragePath("storage path is outside the root")
    return root_abs, parts


def _posix_directory_flags():
    if not getattr(os, "O_NOFOLLOW", 0) or not getattr(os, "O_DIRECTORY", 0):
        raise UnsafeStoragePath("secure directory handles unsupported")
    # O_PATH (Linux) / O_SEARCH (other POSIX) only needs directory traversal
    # permission, unlike O_RDONLY which rejects legitimate 0711 ancestors.
    directory_access = getattr(os, "O_PATH", None)
    if directory_access is None:
        directory_access = getattr(os, "O_SEARCH", None)
    if directory_access is None:
        directory_access = os.O_RDONLY
    return directory_access | os.O_DIRECTORY | os.O_NOFOLLOW


def _open_posix_directory(path):
    flags = _posix_directory_flags()
    fd = os.open(os.sep, flags)
    try:
        for part in path.strip(os.sep).split(os.sep):
            if not part:
                continue
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except Exception:
        os.close(fd)
        raise


def _open_posix_parent(root, parts):
    fd = _open_posix_directory(root)
    flags = _posix_directory_flags()
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except Exception:
        os.close(fd)
        raise


def _normalize_windows_path(path):
    path = str(path)
    if path.startswith("\\\\?\\UNC\\"):
        path = "\\\\" + path[8:]
    elif path.startswith("\\\\?\\"):
        path = path[4:]
    return ntpath.normcase(ntpath.normpath(path))


def _windows_handle_path(handle):
    kernel = ctypes.windll.kernel32
    kernel.GetFinalPathNameByHandleW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong]
    kernel.GetFinalPathNameByHandleW.restype = ctypes.c_ulong
    length = kernel.GetFinalPathNameByHandleW(handle, None, 0, 0)
    if not length:
        raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW failed")
    buf = ctypes.create_unicode_buffer(length + 1)
    written = kernel.GetFinalPathNameByHandleW(handle, buf, length + 1, 0)
    if not written or written > length:
        raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW failed")
    return _normalize_windows_path(buf.value)


def _windows_handle_inside(trusted_root, handle):
    actual = _windows_handle_path(handle)
    # The root was captured before opening the file/entry. Never re-resolve
    # it here: an attacker might have swapped its junction in the meantime.
    trusted = _normalize_windows_path(trusted_root)
    try:
        return ntpath.commonpath([actual, trusted]) == trusted
    except ValueError:
        return False



def _open_windows_root_handle(trusted_root):
    """Pin and verify the original directory identity before opening children."""
    from ctypes import wintypes
    kernel = ctypes.windll.kernel32
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(
        trusted_root,
        0x00000080,  # FILE_READ_ATTRIBUTES
        0x00000007, None, 3,
        0x02000000,  # BACKUP_SEMANTICS: follow root junction and inspect target
        None,
    )
    if handle is None or handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "Cannot pin storage root")
    try:
        if _windows_handle_path(handle) != _normalize_windows_path(trusted_root):
            raise UnsafeStoragePath("Windows storage root changed before open")
        return handle
    except Exception:
        kernel.CloseHandle(handle)
        raise


def open_scoped_file(root, path):
    """Open one read-only regular file pinned below a trusted storage root.

    The root is canonicalized once before any child file handle is opened.
    POSIX uses link-proof directory FDs; Windows pins the original root handle
    and validates the final file handle against that pre-open trust boundary.
    """
    trusted_root = os.path.realpath(root)
    if not _contained_with_fixed_root(trusted_root, path):
        raise UnsafeStoragePath("storage file escapes root")
    root_abs, parts = _parts_beneath(
        trusted_root, path, root_is_resolved=True
    )
    if os.name == "nt":
        import msvcrt
        root_handle = _open_windows_root_handle(trusted_root)
        try:
            fd = os.open(os.path.join(root_abs, *parts), os.O_RDONLY | os.O_BINARY)
            try:
                if not _windows_handle_inside(trusted_root, msvcrt.get_osfhandle(fd)):
                    raise UnsafeStoragePath("Windows file handle escapes trusted root")
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise UnsafeStoragePath("storage entry is not a regular file")
                return os.fdopen(fd, "rb")
            except Exception:
                os.close(fd)
                raise
        finally:
            ctypes.windll.kernel32.CloseHandle(root_handle)
    parent = _open_posix_parent(root_abs, parts)
    try:
        # Without O_NONBLOCK, an attacker-swapped FIFO blocks the event loop
        # before fstat() has a chance to reject it.
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise UnsafeStoragePath("storage entry is not a regular file")
        return os.fdopen(fd, "rb")
    except Exception:
        os.close(fd)
        raise


def unlink_scoped_file(root, path):
    """Delete the selected entry using a parent FD or verified Win32 HANDLE."""
    trusted_root = os.path.realpath(root)
    if not _contained_with_fixed_root(trusted_root, path):
        raise UnsafeStoragePath("storage entry escapes root")
    root_abs, parts = _parts_beneath(
        trusted_root, path, follow_final=False, root_is_resolved=True
    )
    if os.name == "nt":
        # Windows deletion must use a validated HANDLE; a path-based unlink
        # after checking would reintroduce the reparse-point race.
        kernel = ctypes.windll.kernel32
        from ctypes import wintypes
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                       ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                      ctypes.c_void_p, wintypes.DWORD]
        kernel.SetFileInformationByHandle.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        root_handle = _open_windows_root_handle(trusted_root)
        try:
            handle = kernel.CreateFileW(
                os.path.join(root_abs, *parts),
                0x00010000 | 0x00000080,  # DELETE | FILE_READ_ATTRIBUTES
                0x00000007, None, 3,
                0x00200000 | 0x02000000,  # OPEN_REPARSE_POINT | BACKUP_SEMANTICS
                None,
            )
            invalid = ctypes.c_void_p(-1).value
            if handle == invalid or handle is None:
                raise OSError(ctypes.get_last_error(), "Cannot open storage entry")
            try:
                if not _windows_handle_inside(trusted_root, handle):
                    raise UnsafeStoragePath("Windows deletion handle escapes trusted root")
                disposition = ctypes.c_uint32(1)
                if not kernel.SetFileInformationByHandle(
                    handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)
                ):
                    raise OSError(ctypes.get_last_error(), "Cannot delete storage entry")
            finally:
                kernel.CloseHandle(handle)
        finally:
            kernel.CloseHandle(root_handle)
        return
    parent = _open_posix_parent(root_abs, parts)
    try:
        os.unlink(parts[-1], dir_fd=parent)
    finally:
        os.close(parent)
