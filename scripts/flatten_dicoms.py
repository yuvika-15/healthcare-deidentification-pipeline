"""
Script to flatten nested DICOM directory structures.

Moves all DICOM (.dcm) files from nested subdirectories directly into the root folder
and safely removes the empty parent directories.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def flatten_dicom_directory(
    source_dir: str | Path,
    target_dir: str | Path | None = None,
    dry_run: bool = False,
    copy_files: bool = False,
    remove_empty_dirs: bool = True,
) -> dict[str, int]:
    """
    Flattens all DICOM files in source_dir into target_dir (or source_dir itself if None).

    Args:
        source_dir: Directory containing nested DICOM files.
        target_dir: Destination directory. Defaults to source_dir if not specified.
        dry_run: If True, only simulates the operation without modifying files.
        copy_files: If True, copies files instead of moving them.
        remove_empty_dirs: If True, removes subdirectories after they become empty.

    Returns:
        Summary dictionary with counts of files moved, skipped, and directories removed.
    """
    source_path = Path(source_dir).resolve()
    if not source_path.exists() or not source_path.is_dir():
        raise ValueError(f"Source directory does not exist or is not a directory: {source_path}")

    target_path = Path(target_dir).resolve() if target_dir else source_path
    target_path.mkdir(parents=True, exist_ok=True)

    print(f"{'[DRY RUN] ' if dry_run else ''}{'Copying' if copy_files else 'Moving'} DICOM files...")
    print(f"Source: {source_path}")
    print(f"Target: {target_path}")
    print("-" * 60)

    # 1. Discover all DICOM files
    all_files: list[Path] = []
    for root, _, files in os.walk(source_path):
        for f in files:
            file_path = Path(root) / f
            # Match .dcm files or files without extension if needed
            if file_path.suffix.lower() == ".dcm" or not file_path.suffix:
                all_files.append(file_path)

    total_found = len(all_files)
    print(f"Discovered {total_found} DICOM file(s) across subdirectories.")

    stats = {
        "total_found": total_found,
        "already_at_target": 0,
        "transferred": 0,
        "renamed_collisions": 0,
        "dirs_removed": 0,
        "dirs_skipped": 0,
    }

    # 2. Move or copy files to target directory
    for src in all_files:
        if src.parent == target_path:
            stats["already_at_target"] += 1
            continue

        dest_name = src.name
        dest = target_path / dest_name

        # Resolve potential name collisions safely
        if dest.exists() and dest != src:
            counter = 1
            stem = src.stem
            suffix = src.suffix
            while dest.exists() and dest != src:
                dest = target_path / f"{stem}_{counter}{suffix}"
                counter += 1
            stats["renamed_collisions"] += 1
            print(f"  [Collision Handled] Renamed to: {dest.name}")

        if dry_run:
            stats["transferred"] += 1
        else:
            try:
                if copy_files:
                    shutil.copy2(src, dest)
                else:
                    shutil.move(str(src), str(dest))
                stats["transferred"] += 1
            except Exception as e:
                print(f"  [Error] Failed to process {src}: {e}", file=sys.stderr)

    # 3. Clean up empty directories if requested
    if remove_empty_dirs and not copy_files:
        print("\nCleaning up empty subdirectories...")
        # Walk bottom-up so deepest children are removed first
        for root, dirs, files in os.walk(source_path, topdown=False):
            current_dir = Path(root)
            if current_dir == target_path:
                continue

            try:
                # Check if directory has remaining entries
                entries = list(current_dir.iterdir())
                if len(entries) == 0:
                    if not dry_run:
                        current_dir.rmdir()
                    stats["dirs_removed"] += 1
                else:
                    stats["dirs_skipped"] += 1
                    print(f"  [Skipped Non-Empty] {current_dir} (contains {len(entries)} items)")
            except Exception as e:
                stats["dirs_skipped"] += 1
                print(f"  [Error] Could not remove {current_dir}: {e}", file=sys.stderr)

    # 4. Final summary
    print("\n" + "=" * 60)
    print(f"{'[DRY RUN] ' if dry_run else ''}Summary:")
    print(f"  Total DICOM files found:         {stats['total_found']}")
    print(f"  Already in target folder:        {stats['already_at_target']}")
    print(f"  Files {'copied' if copy_files else 'moved'}:                 {stats['transferred']}")
    if stats["renamed_collisions"] > 0:
        print(f"  Filename collisions handled:     {stats['renamed_collisions']}")
    if remove_empty_dirs and not copy_files:
        print(f"  Empty directories removed:       {stats['dirs_removed']}")
        if stats["dirs_skipped"] > 0:
            print(f"  Directories skipped (not empty): {stats['dirs_skipped']}")
    print("=" * 60)

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Flatten nested DICOM directories into a single folder and clean up empty folders."
    )
    parser.add_argument(
        "--source-dir",
        "-s",
        default="pseudo_phi_dicom_data",
        help="Path to source directory containing nested DICOM folders (default: pseudo_phi_dicom_data)",
    )
    parser.add_argument(
        "--target-dir",
        "-t",
        default=None,
        help="Path to target directory (default: same as source-dir, in-place flattening)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the operation without moving files or deleting directories",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy files instead of moving them (preserves original folders)",
    )
    parser.add_argument(
        "--keep-folders",
        action="store_true",
        help="Keep empty folders instead of removing them",
    )

    args = parser.parse_args()

    flatten_dicom_directory(
        source_dir=args.source_dir,
        target_dir=args.target_dir,
        dry_run=args.dry_run,
        copy_files=args.copy,
        remove_empty_dirs=not args.keep_folders,
    )


if __name__ == "__main__":
    main()
