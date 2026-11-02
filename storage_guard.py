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


def _parts_beneath(root, path, *, follow_final=True):
    root_abs = os.path.realpath(root)
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


def _open_posix_directory(path):
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if not getattr(os, "O_NOFOLLOW", 0) or not getattr(os, "O_DIRECTORY", 0):
        raise UnsafeStoragePath("secure directory handles unsupported")
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
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
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


def _windows_handle_inside(root, handle):
    actual = _windows_handle_path(handle)
    trusted = _normalize_windows_path(os.path.realpath(root))
    try:
        return ntpath.commonpath([actual, trusted]) == trusted
    except ValueError:
        return False


def open_scoped_file(root, path):
    """Return a pinned read-only file handle confined to root.

    POSIX: open every directory through dir_fd/O_NOFOLLOW; never follow any
    newly replaced symlink. Windows: open first, validate the *actual handle*
    final path via GetFinalPathNameByHandleW, then read from that handle.
    """
    if not _contained(root, path):
        raise UnsafeStoragePath("storage file escapes root")
    root_abs, parts = _parts_beneath(root, path)
    if os.name == "nt":
        import msvcrt
        fd = os.open(os.path.join(root_abs, *parts), os.O_RDONLY | os.O_BINARY)
        try:
            if not _windows_handle_inside(root, msvcrt.get_osfhandle(fd)):
                raise UnsafeStoragePath("Windows file handle escapes root")
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise UnsafeStoragePath("storage entry is not a regular file")
            return os.fdopen(fd, "rb")
        except Exception:
            os.close(fd)
            raise
    parent = _open_posix_parent(root_abs, parts)
    try:
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
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
    """Unlink the requested directory entry, never its symlink destination."""
    if not _contained(root, path):
        raise UnsafeStoragePath("storage entry escapes root")
    root_abs, parts = _parts_beneath(root, path, follow_final=False)
    if os.name == "nt":
        # Windows deletion must use a validated HANDLE: a path-based unlink
        # after validation would reintroduce a reparse-point race.
        kernel = ctypes.windll.kernel32
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
            if not _windows_handle_inside(root, handle):
                raise UnsafeStoragePath("Windows deletion handle escapes root")
            disposition = ctypes.c_uint32(1)
            if not kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
                raise OSError(ctypes.get_last_error(), "Cannot delete storage entry")
        finally:
            kernel.CloseHandle(handle)
        return
    parent = _open_posix_parent(root_abs, parts)
    try:
        os.unlink(parts[-1], dir_fd=parent)
    finally:
        os.close(parent)
