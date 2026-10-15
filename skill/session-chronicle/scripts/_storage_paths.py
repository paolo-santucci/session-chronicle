"""Reject aliased storage paths before cooperating writers mutate local memory."""
from pathlib import Path
import stat

MEMORY_FOLDERS = (".drafts", ".drafts/pending", "pending", "sessions", "topics", "continuations")


def regular_file(path, publication_temporaries=False):
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Memory storage requires regular files without symbolic links")
    permitted_links = 1
    if publication_temporaries:
        # A crash between immutable link publication and temporary unlink leaves
        # a second name. Only same-directory checkpoint temporaries are internal.
        for temporary in path.parent.glob(".checkpoint-*"):
            candidate = temporary.lstat()
            if (stat.S_ISREG(candidate.st_mode) and
                    (candidate.st_dev, candidate.st_ino) == (info.st_dev, info.st_ino)):
                permitted_links += 1
    if info.st_nlink != permitted_links:
        raise ValueError("Memory storage cannot share hard links with other paths")


def storage_layout(base, inspect_files=True):
    base = Path(base).absolute()
    directories = (base, *(base / folder for folder in MEMORY_FOLDERS))
    for directory in directories:
        for component in (directory, *directory.parents):
            if component.is_symlink():
                raise ValueError("Memory storage directories cannot contain symbolic links")
        if directory.exists() and not directory.is_dir():
            raise ValueError("Memory storage directories must be directories")
    regular_file(base / ".drafts/.writer.lock")
    if not inspect_files:
        return
    for folder, pattern in ((".drafts", "*.draft.jsonl"), (".drafts/pending", "*.jsonl"),
                            ("pending", "*.jsonl"), ("sessions", "*.md"),
                            ("topics", "*.md"), ("continuations", "*.json")):
        for path in (base / folder).glob(pattern):
            regular_file(path, publication_temporaries=folder in ("sessions", "continuations"))
