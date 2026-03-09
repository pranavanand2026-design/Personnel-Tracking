"""Choose a video file from the footage folder."""
import subprocess
import sys
from pathlib import Path

VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".mpg", ".mpeg", ".m4v"}


def list_videos(folder: Path) -> list[Path]:
    """All videos under folder, including subfolders (skipping gt/ folders)."""
    return sorted(
        p for p in folder.rglob("*")
        if p.suffix.lower() in VIDEO_EXTS and "gt" not in p.relative_to(folder).parts
    )


def _mac_dialog(folder: Path) -> Path | None:
    """Native macOS file dialog. Returns None if cancelled or unavailable."""
    script = (
        f'POSIX path of (choose file with prompt "Choose a corridor video" '
        f'default location (POSIX file "{folder.resolve()}"))'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=300
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    path = result.stdout.strip()
    return Path(path) if result.returncode == 0 and path else None


def _terminal_menu(folder: Path) -> Path | None:
    videos = list_videos(folder)
    if not videos:
        print(f"No videos found in {folder}/")
        return None
    for i, v in enumerate(videos, 1):
        print(f"  {i}) {v.relative_to(folder)}")
    choice = input("Pick a video number: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(videos):
        return videos[int(choice) - 1]
    return None


def choose_video(folder: Path, use_dialog: bool = True) -> Path | None:
    folder.mkdir(exist_ok=True)
    if use_dialog and sys.platform == "darwin":
        path = _mac_dialog(folder)
        if path:
            return path
    return _terminal_menu(folder)
