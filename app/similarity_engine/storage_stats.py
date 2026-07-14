from __future__ import annotations

import os
from pathlib import Path


MILVUS_OBJECT_KINDS = ("insert_log", "stats_log", "delta_log")


def milvus_collection_storage_bytes(root: str, collection_id: int | str | None) -> int:
    """Return physical Milvus object bytes for one collection from MinIO volume layout."""
    if collection_id is None:
        return 0
    root_value = str(root or "").strip()
    if not root_value:
        return 0
    base = Path(root_value)
    if base.name != "files":
        base = base / "a-bucket" / "files"
    if not base.exists():
        return 0

    cid = str(collection_id)
    total = 0
    partition_ids: set[str] = set()

    for kind in MILVUS_OBJECT_KINDS:
        collection_dir = base / kind / cid
        if not collection_dir.exists():
            continue
        total += _tree_size(collection_dir)
        partition_ids.update(_direct_child_names(collection_dir))

    if partition_ids:
        total += _index_files_size(base / "index_files", partition_ids)
    return total


def _direct_child_names(path: Path) -> set[str]:
    try:
        return {item.name for item in path.iterdir() if item.is_dir()}
    except OSError:
        return set()


def _index_files_size(path: Path, partition_ids: set[str]) -> int:
    if not path.exists():
        return 0
    total = 0
    try:
        index_roots = [item for item in path.iterdir() if item.is_dir()]
    except OSError:
        return 0
    for index_root in index_roots:
        try:
            versions = [item for item in index_root.iterdir() if item.is_dir()]
        except OSError:
            continue
        for version in versions:
            try:
                partitions = [item for item in version.iterdir() if item.is_dir()]
            except OSError:
                continue
            for partition in partitions:
                if partition.name in partition_ids:
                    total += _tree_size(partition)
    return total


def _tree_size(path: Path) -> int:
    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total
