"""Where the notes live: cloud-folder detection, moving the library, renaming notes.

EchoPad stores every note as an ordinary Markdown file next to its audio, so
"connecting OneDrive or Google Drive" needs no OAuth, no API keys, and no
third-party access to your account: you point the notes folder at the folder
that provider's own client already syncs on this machine. Sync, version
history, and off-device backup then come from the provider for free.

The tradeoff is real and worth stating plainly: notes stored in a synced
folder *do* leave your machine and reach that provider. Keeping notes in the
default local folder is still the fully-private option.
"""
import json
import os
import re
import shutil
from pathlib import Path

# A dedicated subfolder inside the sync root — never the root itself, so
# EchoPad neither scans nor moves unrelated files the user keeps there.
LIBRARY_FOLDER_NAME = "EchoPad"

# Per-note sidecar holding the title, tags, and template. It travels with the
# note, so a note's own folder is fully self-describing: move the library,
# sync it to another computer, or delete the index entirely, and the details
# are recovered from disk rather than lost.
META_FILENAME = "meta.json"
META_FIELDS = ("title", "tags", "template", "word_count", "created_at")

_WINDOWS_DRIVE_LETTERS = "DEFGHIJKLMNOPQRSTUVWXYZ"


def _exists_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _glob_dirs(parent: Path, pattern: str):
    if not _exists_dir(parent):
        return []
    try:
        return sorted(p for p in parent.glob(pattern) if p.is_dir())
    except OSError:
        return []


def detect_providers(home: Path = None, env=None, include_windows_drives: bool = None):
    """Cloud-sync folders that appear to exist on this machine.

    Returns a list of {"label", "path", "kind"} dicts, de-duplicated by
    resolved path. `home`/`env` are injectable for testing.
    """
    home = Path(home) if home else Path.home()
    env = os.environ if env is None else env
    if include_windows_drives is None:
        include_windows_drives = os.name == "nt"

    found = []

    # --- OneDrive -------------------------------------------------------
    # The Windows client exports these; macOS uses ~/Library/CloudStorage.
    for var, label in (
        ("OneDrive", "OneDrive"),
        ("OneDriveConsumer", "OneDrive (Personal)"),
        ("OneDriveCommercial", "OneDrive (Work or School)"),
    ):
        value = env.get(var)
        if value and _exists_dir(Path(value)):
            found.append({"label": label, "path": Path(value), "kind": "onedrive"})

    for candidate in (home / "OneDrive", home / "OneDrive - Personal"):
        if _exists_dir(candidate):
            found.append({"label": "OneDrive", "path": candidate, "kind": "onedrive"})

    cloud_storage = home / "Library" / "CloudStorage"
    for path in _glob_dirs(cloud_storage, "OneDrive-*"):
        account = path.name.split("-", 1)[-1].replace("-", " ").strip()
        found.append({"label": f"OneDrive ({account})" if account else "OneDrive",
                      "path": path, "kind": "onedrive"})

    # --- Google Drive ---------------------------------------------------
    # Drive for Desktop nests the real root under "My Drive".
    for path in _glob_dirs(cloud_storage, "GoogleDrive-*"):
        account = path.name.split("-", 1)[-1].strip()
        my_drive = path / "My Drive"
        target = my_drive if _exists_dir(my_drive) else path
        found.append({"label": f"Google Drive ({account})" if account else "Google Drive",
                      "path": target, "kind": "googledrive"})

    for candidate in (home / "Google Drive" / "My Drive", home / "Google Drive"):
        if _exists_dir(candidate):
            found.append({"label": "Google Drive", "path": candidate, "kind": "googledrive"})
            break

    if include_windows_drives:
        # Drive for Desktop commonly mounts as a virtual drive (G:\My Drive).
        for letter in _WINDOWS_DRIVE_LETTERS:
            candidate = Path(f"{letter}:/My Drive")
            if _exists_dir(candidate):
                found.append({"label": f"Google Drive ({letter}:)", "path": candidate,
                              "kind": "googledrive"})

    # --- Others that behave the same way --------------------------------
    icloud = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    if _exists_dir(icloud):
        found.append({"label": "iCloud Drive", "path": icloud, "kind": "icloud"})

    for candidate in (home / "Dropbox",):
        if _exists_dir(candidate):
            found.append({"label": "Dropbox", "path": candidate, "kind": "dropbox"})

    deduped, seen = [], set()
    for provider in found:
        try:
            key = str(provider["path"].resolve()).lower()
        except OSError:
            key = str(provider["path"]).lower()
        if key not in seen:
            seen.add(key)
            deduped.append(provider)
    return deduped


def library_path_for(provider_path) -> Path:
    """The folder EchoPad would actually use inside a sync root."""
    return Path(provider_path).expanduser() / LIBRARY_FOLDER_NAME


def meta_path(md_path, note_filename: str = "note.md") -> Path:
    """Where a note's sidecar metadata lives."""
    md_path = Path(md_path)
    if md_path.name == note_filename:
        return md_path.parent / META_FILENAME
    return md_path.with_name(md_path.stem + ".meta.json")  # legacy flat layout


def read_note_meta(md_path, note_filename: str = "note.md") -> dict:
    """Sidecar metadata for a note, or {} if absent/unreadable."""
    try:
        data = json.loads(meta_path(md_path, note_filename).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if k in META_FIELDS} if isinstance(data, dict) else {}


def write_note_meta(md_path, note_filename: str = "note.md", **fields) -> None:
    """Merge `fields` into a note's sidecar metadata. Best-effort: failing to
    write it must never lose the note itself, which is already on disk."""
    known = {k: v for k, v in fields.items() if k in META_FIELDS}
    if not known:
        return
    merged = {**read_note_meta(md_path, note_filename), **known}
    try:
        meta_path(md_path, note_filename).write_text(
            json.dumps(merged, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def _prune_empty_dirs(root: Path) -> None:
    """Remove directories left empty after a move, keeping `root` itself."""
    root = Path(root)
    for path in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
        try:
            next(path.iterdir())
        except StopIteration:
            try:
                path.rmdir()
            except OSError:
                pass
        except OSError:
            pass


def move_library(src, dst) -> dict:
    """Move every file from `src` into `dst`, verifying before deleting anything.

    Each file is copied and its size checked at the destination. Only once
    *all* copies verify are the originals removed — if any copy fails, the
    partial copies are rolled back and the original library is left exactly
    as it was. Files already present at the destination are reported as
    conflicts and skipped rather than overwritten.
    """
    src, dst = Path(src).expanduser(), Path(dst).expanduser()
    dst.mkdir(parents=True, exist_ok=True)

    try:
        same = src.resolve() == dst.resolve()
    except OSError:
        same = str(src) == str(dst)
    if same:
        return {"moved": 0, "conflicts": [], "failed": [], "unchanged": True}

    planned, conflicts = [], []
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        relative = path.relative_to(src)
        target = dst / relative
        if target.exists():
            conflicts.append(str(relative))
        else:
            planned.append((path, target))

    copied, failed = [], []
    for source_file, target_file in planned:
        try:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
            if target_file.stat().st_size != source_file.stat().st_size:
                raise OSError("size mismatch after copy")
            copied.append((source_file, target_file))
        except OSError as exc:
            failed.append({"file": str(source_file.relative_to(src)), "error": str(exc)})
            break

    if failed:
        for _, target_file in copied:  # roll back; originals were never touched
            try:
                target_file.unlink()
            except OSError:
                pass
        return {"moved": 0, "conflicts": conflicts, "failed": failed, "unchanged": False}

    for source_file, _ in copied:
        try:
            source_file.unlink()
        except OSError:
            pass
    _prune_empty_dirs(src)
    return {"moved": len(copied), "conflicts": conflicts, "failed": [], "unchanged": False}


def slugify(title: str) -> str:
    """Filesystem-safe folder name for a note title.

    Removing a character can leave neighbouring separators touching (e.g.
    "Mitosis / Meiosis" -> "mitosis  meiosis"), so runs are collapsed to a
    single underscore — these names are meant to be read in File Explorer.
    """
    cleaned = re.sub(r'[<>:"/\\|?*]', " ", str(title).lower())
    cleaned = re.sub(r"[\s_]+", "_", cleaned)
    return cleaned.strip("_.") or "untitled"


def unique_slug(parent: Path, desired: str) -> str:
    """`desired`, suffixed if needed so it doesn't collide inside `parent`."""
    parent = Path(parent)
    slug, suffix = desired, 1
    while (parent / slug).exists():
        suffix += 1
        slug = f"{desired}_{suffix}"
    return slug


def rename_note(md_path, new_title: str, note_filename: str = "note.md"):
    """Rename a note on disk to match `new_title`.

    Returns (new_md_path, new_index_filename) where new_index_filename is the
    path relative to the category folder, matching how db.py keys notes.
    Raises FileExistsError if something already occupies the new name.
    """
    md_path = Path(md_path)
    slug = slugify(new_title)
    category_dir = md_path.parent.parent if md_path.name == note_filename else md_path.parent

    if md_path.name == note_filename:
        new_dir = category_dir / slug
        if new_dir.exists() and new_dir.resolve() != md_path.parent.resolve():
            raise FileExistsError(f'A note folder named "{slug}" already exists.')
        md_path.parent.rename(new_dir)
        return new_dir / note_filename, f"{slug}/{note_filename}"

    # Legacy flat layout: <category>/<slug>.md alongside <slug>.wav
    new_md = category_dir / f"{slug}.md"
    if new_md.exists() and new_md.resolve() != md_path.resolve():
        raise FileExistsError(f'A note named "{slug}.md" already exists.')
    old_audio = md_path.with_suffix(".wav")
    md_path.rename(new_md)
    if old_audio.exists():
        old_audio.rename(category_dir / f"{slug}.wav")
    return new_md, f"{slug}.md"
