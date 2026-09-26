"""
Quiet a harmless Windows-only cleanup error from phonemizer (used by Kokoro).

phonemizer copies espeak-ng.dll into a temp folder and tries to delete it at
exit while the DLL is still loaded, which prints "Access is denied" tracebacks
and leaves the folder behind. We silence that cleanup and, on the next run,
remove the folders earlier runs left behind (their DLLs are unloaded by then).
"""

import shutil
import sys
import tempfile
from pathlib import Path


def _patch_phonemizer():
    try:
        from phonemizer.backend.espeak.api import EspeakAPI
    except ImportError:
        return
    delete = EspeakAPI._delete

    def quiet_delete_win32(self):
        try:
            delete(self._library, self._tempdir)
        except OSError:
            pass

    EspeakAPI._delete_win32 = quiet_delete_win32


def _remove_leftovers():
    removed = 0
    for folder in Path(tempfile.gettempdir()).glob("tmp*"):
        try:
            files = list(folder.iterdir()) if folder.is_dir() else []
        except OSError:
            continue
        if len(files) == 1 and files[0].name == "espeak-ng.dll":
            try:
                shutil.rmtree(folder)   # fails if another run still has it loaded
                removed += 1
            except OSError:
                pass
    if removed:
        print(f"Cleanup: removed {removed} leftover espeak-ng.dll temp folder(s) from earlier runs.\n"
              "  Kokoro's phonemizer copies espeak-ng.dll to a temp folder while it runs and\n"
              "  cannot delete it at exit because Windows keeps a loaded DLL locked.\n"
              "  This is harmless and does not affect the audio.\n")


def quiet_espeak_cleanup():
    if sys.platform != "win32":
        return
    _remove_leftovers()
    _patch_phonemizer()
