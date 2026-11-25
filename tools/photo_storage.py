"""Offline, read-only inventory audit; bounded compression of private copies only.

No application imports, database initialization, network access or source writes.
Run from the project: python tools/photo_storage.py --help
"""

import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from html import escape
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sqlite3
import tempfile
import warnings

from PIL import Image, ImageOps


PROJECT = Path(__file__).resolve().parents[1]
PRIVATE = PROJECT / ".photo-audit"
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PIXELS = 40_000_000
MAX_OUTPUT = 512 * 1024 * 1024
MAX_FILE = 24 * 1024 * 1024
RESERVE = 1024 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def no_links(path):
    """Reject symbolic links and Windows junctions in every existing component."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError("Symbolic links/junctions are not allowed")
    return path


def source_path(root, relative):
    if not isinstance(relative, str):
        raise ValueError("Non-text registered path")
    normalized = relative.replace("\\", "/")
    parts = normalized.split("/")
    if (not normalized or "\x00" in normalized or PureWindowsPath(normalized).drive
            or PurePosixPath(normalized).is_absolute()
            or any(p in {"", ".", ".."} or ":" in p for p in parts)):
        raise ValueError("Unsafe registered path")
    candidate = no_links(root.joinpath(*parts))
    if not candidate.is_relative_to(root) or candidate.suffix.lower() not in EXTENSIONS:
        raise ValueError("Path outside supported photo scope")
    return candidate


def atomic_new(path, data):
    """Publish a complete new file atomically; hard link never replaces a target."""
    path = Path(path)
    no_links(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        os.unlink(temporary)


def new_run(name, data_root):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
        raise ValueError("Run name must be 1-64 ASCII letters/digits, hyphens or underscores")
    private = no_links(PRIVATE)
    root = no_links(data_root)
    # Outputs must never be discoverable by the application's normal/legacy scans.
    if private.is_relative_to(root) and private != root / ".photo-audit":
        raise ValueError("Output overlaps an inventory location")
    if root.is_relative_to(private):
        raise ValueError("Data root overlaps private output")
    if shutil.disk_usage(private.parent).free < RESERVE + MAX_OUTPUT:
        raise ValueError("Insufficient free space (reserve + bounded output budget)")
    private.mkdir(exist_ok=True)
    run = private / name
    run.mkdir()  # deliberately refuses reuse/overwrite
    return run


def audit(data_root):
    root = no_links(data_root)
    if not root.is_dir():
        raise ValueError("Data root is not an existing directory")
    report = {"version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
              "data_root": str(root), "scope": {
                  "normal": "PALETY recursively (including files outside sync folder depth)",
                  "legacy": "direct images in database-known root/pallet/shoe folders, plus registered matching images",
                  "dimensions": "header only; no full collection pixel decode"},
              "database": "missing", "normal_root_exists": (root / "PALETY").is_dir(),
              "registered_rows": 0, "errors": [], "files": [], "case_collisions": [],
              "portability_warnings": [], "legacy_folders_checked": 0, "legacy_folders_found": 0}
    errors = report["errors"]
    candidates = {}
    directory_names = {}

    def check_case(path):
        parent = root
        for part in path.relative_to(root).parts:
            if parent not in directory_names:
                directory_names[parent] = set(os.listdir(parent))
            names = directory_names[parent]
            if part not in names and any(name.casefold() == part.casefold() for name in names):
                report["portability_warnings"].append({"path": path.relative_to(root).as_posix(),
                                                       "kind": "registered_case_mismatch"})
                break
            parent = parent / part

    def add(path, origin):
        try:
            relative = path.relative_to(root).as_posix()
            checked = source_path(root, relative)
            if not checked.is_file():
                raise ValueError("Missing or non-file image")
            # On case-insensitive hosts, registration aliases must not double-count
            # the same normal image. Link checks happen before canonicalization.
            relative = checked.resolve().relative_to(root.resolve()).as_posix()
            candidates.setdefault(relative, set()).add(origin)
        except (OSError, ValueError) as exc:
            errors.append({"path": str(path), "error": str(exc)})

    photos = root / "PALETY"
    if photos.exists():
        try:
            no_links(photos)
            def walk_error(exc):
                errors.append({"path": str(exc.filename), "error": str(exc)})
            for directory, dirs, files in os.walk(photos, followlinks=False, onerror=walk_error):
                safe_dirs = []
                for name in sorted(dirs):
                    try:
                        no_links(Path(directory) / name)
                        safe_dirs.append(name)
                    except ValueError as exc:
                        errors.append({"path": str(Path(directory) / name), "error": str(exc)})
                dirs[:] = safe_dirs
                for name in sorted(files):
                    path = Path(directory) / name
                    if path.suffix.lower() in EXTENSIONS:
                        add(path, "PALETY")
        except (OSError, ValueError) as exc:
            errors.append({"path": str(photos), "error": str(exc)})

    database = root / "inventory.db"
    if database.exists():
        try:
            no_links(database)
            # Immutable avoids even SQLite WAL/SHM creation or lock-file writes.
            # Never silently ignore a live WAL: refuse that database instead.
            if any(Path(str(database) + suffix).exists() for suffix in ("-wal", "-journal")):
                raise ValueError("WAL/journal present: stop application and recover/checkpoint separately before audit")
            before_db = database.stat()
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
                db.execute("PRAGMA query_only=ON")
                db.execute("BEGIN")
                for pallet, shoe in db.execute("SELECT b.code, s.internal_id FROM shoes s "
                                               "JOIN pallets b ON b.id=s.pallet_id"):
                    try:
                        # Match identifier safety without importing/initializing the application.
                        if not all(isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", v)
                                   for v in (pallet, shoe)) or pallet == "PALETY":
                            raise ValueError("Unsafe legacy folder identifiers")
                        folder = no_links(root / pallet / shoe)
                        report["legacy_folders_checked"] += 1
                        if folder.is_dir():
                            report["legacy_folders_found"] += 1
                            for path in sorted(folder.iterdir()):
                                if path.suffix.lower() in EXTENSIONS:
                                    add(path, "known_legacy_folder")
                    except (OSError, ValueError) as exc:
                        errors.append({"path": f"{pallet}/{shoe}", "error": str(exc)})
                rows = db.execute("SELECT p.file_path, b.code, s.internal_id FROM shoe_photos p "
                                  "JOIN shoes s ON s.id=p.shoe_id "
                                  "JOIN pallets b ON b.id=s.pallet_id")
                for relative, pallet, shoe in rows:
                    report["registered_rows"] += 1
                    try:
                        path = source_path(root, relative)
                        parts = path.relative_to(root).parts
                        check_case(path)
                        if parts[0] == "PALETY":
                            add(path, "registered_normal")
                        elif len(parts) == 3 and parts[:2] == (pallet, shoe):
                            add(path, "registered_legacy")
                        else:
                            raise ValueError("Registered path does not match allowed legacy folder")
                        if "\\" in relative:
                            report["portability_warnings"].append({"path": relative, "kind": "backslashes"})
                    except (OSError, ValueError) as exc:
                        errors.append({"path": str(relative), "error": str(exc)})
                after_db = database.stat()
                if (any(Path(str(database) + suffix).exists() for suffix in ("-wal", "-journal"))
                        or (before_db.st_size, before_db.st_mtime_ns)
                        != (after_db.st_size, after_db.st_mtime_ns)):
                    raise ValueError("Database changed during audit; rerun with application stopped")
                report["database"] = "read-only immutable read completed (requires quiescent database)"
        except (OSError, ValueError, sqlite3.Error) as exc:
            report["database"] = "failed"
            errors.append({"path": str(database), "error": str(exc)})

    case_paths = defaultdict(set)
    for relative, origins in sorted(candidates.items()):
        try:
            path = source_path(root, relative)
            stat = path.stat()
            record = {"path": relative, "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                      "extension": path.suffix.lower(), "origins": sorted(origins)}
            try:
                # Header inspection only, bomb warnings recorded rather than decoding pixels.
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(path) as image:
                        record.update(width=image.width, height=image.height, format=image.format,
                                      frames=getattr(image, "n_frames", 1))
            except (OSError, ValueError, Image.DecompressionBombError,
                    Image.DecompressionBombWarning) as exc:
                record["header_error"] = str(exc)
                errors.append({"path": relative, "error": "Header: " + str(exc)})
            report["files"].append(record)
            parts = PurePosixPath(relative).parts
            for index in range(1, len(parts) + 1):
                prefix = "/".join(parts[:index])
                case_paths[prefix.casefold()].add(prefix)
            if len(parts) != 4 and parts[0] == "PALETY":
                report["portability_warnings"].append({"path": relative, "kind": "outside_sync_depth"})
        except (OSError, ValueError) as exc:
            errors.append({"path": relative, "error": str(exc)})
    report["case_collisions"] = [sorted(paths) for paths in case_paths.values() if len(paths) > 1]
    report["summary"] = summarize(report)
    return report


def summarize(report):
    files = report["files"]
    types = {}
    dimensions = Counter()
    for record in files:
        bucket = types.setdefault(record["extension"], {"count": 0, "bytes": 0})
        bucket["count"] += 1
        bucket["bytes"] += record["bytes"]
        if "width" in record:
            dimensions[f'{record["width"]}x{record["height"]}'] += 1
    return {"count": len(files), "bytes": sum(r["bytes"] for r in files),
            "types": types, "dimensions": dict(dimensions.most_common()),
            "header_failures": sum("header_error" in r for r in files),
            "errors": len(report["errors"]),
            "legacy_count": sum(bool({"registered_legacy", "known_legacy_folder"}.intersection(r["origins"]))
                                for r in files),
            "case_collisions": len(report["case_collisions"])}


def select_sample(records, count):
    """Deterministic coverage of type, size range and resolution; not a random estimate."""
    groups = defaultdict(list)
    for record in records:
        if ("header_error" in record or record.get("frames", 1) != 1
                or record.get("width", 0) * record.get("height", 0) > MAX_PIXELS):
            continue
        edge = max(record["width"], record["height"])
        groups[(record["extension"], "small" if edge <= 1600 else "medium" if edge <= 2000 else "large")].append(record)
    queues = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda r: (r["bytes"], r["path"]))
        # Visit evenly distributed size ranks before adjacent entries.
        order = []
        pending = [(0, len(group) - 1)]
        while pending:
            lo, hi = pending.pop(0)
            if lo > hi:
                continue
            mid = (lo + hi) // 2
            order.append(group[mid])
            pending.extend([(lo, mid - 1), (mid + 1, hi)])
        queues.append(order)
    # Reserve coverage for uncommon formats/resolutions, then allocate remaining
    # slots proportionally. A huge JPEG collection should dominate the trial,
    # not be outvoted by a handful of small PNG/WebP files.
    total = sum(len(q) for q in queues)
    target = min(count, total)
    quotas = [0] * len(queues)
    for _ in range(target):
        eligible = [i for i, q in enumerate(queues) if quotas[i] < len(q)]
        uncovered = [i for i in eligible if quotas[i] == 0]
        index = (uncovered[0] if uncovered else
                 max(eligible, key=lambda i: (target * len(queues[i]) / total - quotas[i], -i)))
        quotas[index] += 1
    queues = [q[:quota] for q, quota in zip(queues, quotas) if quota]
    selected = []
    while queues and len(selected) < count:
        for queue in queues:
            if queue and len(selected) < count:
                selected.append(queue.pop(0))
        queues = [q for q in queues if q]
    return selected


def compress_samples(report, run, count=36, budget=MAX_OUTPUT):
    if not 1 <= count <= 48 or not 1 <= budget <= MAX_OUTPUT:
        raise ValueError("Sample count must be 1-48 and budget at most 512 MiB")
    root = no_links(report["data_root"])
    run = no_links(run)
    if run.parent != no_links(PRIVATE) or not run.is_dir():
        raise ValueError("Samples require a dedicated private run directory")
    if shutil.disk_usage(run).free < RESERVE + budget:
        raise ValueError("Insufficient free space for bounded sample")
    result = {"requested": count, "selected": 0, "completed": 0, "bytes_written": 0,
              "budget_bytes": budget, "max_source_pixels": MAX_PIXELS,
              "selection": "deterministic stratified type/resolution/size; not statistically representative",
              "outputs": [], "errors": [], "stopped": None}
    records = select_sample(report["files"], count)
    result["selected"] = len(records)
    for index, record in enumerate(records, 1):
        try:
            path = source_path(root, record["path"])
            before = path.stat()
            if (before.st_size, before.st_mtime_ns) != (record["bytes"], record["mtime_ns"]):
                raise ValueError("Source changed since audit")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    if image.width * image.height > MAX_PIXELS or getattr(image, "n_frames", 1) != 1:
                        raise ValueError("Source exceeds pixel limit or is animated")
                    oriented = ImageOps.exif_transpose(image)
                    # Explicit white alpha compositing; new RGB canvas has no EXIF/GPS/ICC/XMP.
                    rgba = oriented.convert("RGBA")
                    clean = Image.new("RGB", rgba.size, "white")
                    clean.paste(rgba, mask=rgba.getchannel("A"))
                    rgba.close()
                    oriented.close()
            try:
                for edge in (None, 1600, 2000):
                    variant = clean.copy()
                    try:
                        if edge:
                            variant.thumbnail((edge, edge), Image.Resampling.LANCZOS)
                        for fmt, quality, suffix in (("JPEG", 85, "jpg"), ("WEBP", 82, "webp")):
                            buffer = io.BytesIO()
                            options = {"optimize": True} if fmt == "JPEG" else {"method": 4}
                            variant.save(buffer, format=fmt, quality=quality, **options)
                            data = buffer.getvalue()
                            if len(data) > MAX_FILE:
                                raise ValueError("Encoded file exceeds 24 MiB limit")
                            if result["bytes_written"] + len(data) > budget:
                                result["stopped"] = "output byte budget reached"
                                return result
                            if shutil.disk_usage(run).free < RESERVE + len(data):
                                result["stopped"] = "free-space reserve reached"
                                return result
                            label = f'{"native" if edge is None else edge}-{suffix}'
                            filename = f"sample-{index:03d}-{label}.{suffix}"
                            atomic_new(run / filename, data)
                            result["bytes_written"] += len(data)
                            result["outputs"].append({"sample": index, "source": record["path"],
                                "source_bytes": record["bytes"], "variant": label,
                                "width": variant.width, "height": variant.height,
                                "bytes": len(data), "file": filename,
                                "saving_percent": round(100 * (1 - len(data) / record["bytes"]), 2)})
                    finally:
                        variant.close()
            finally:
                clean.close()
            result["completed"] += 1
        except (OSError, ValueError, Image.DecompressionBombError,
                Image.DecompressionBombWarning) as exc:
            result["errors"].append({"source": record["path"], "error": str(exc)})
    return result


def comparison_summary(samples):
    groups = defaultdict(list)
    for output in samples["outputs"]:
        groups[output["variant"]].append(output)
    summary = {}
    for variant, rows in sorted(groups.items()):
        original = sum(r["source_bytes"] for r in rows)
        encoded = sum(r["bytes"] for r in rows)
        summary[variant] = {"count": len(rows), "source_bytes": original, "output_bytes": encoded,
                            "saving_percent": round(100 * (1 - encoded / original), 2)}
    return summary


def save_report(run, report):
    atomic_new(run / "report.json", json.dumps(report, ensure_ascii=True, indent=2).encode())
    rows = ["<!doctype html><meta charset='utf-8'><title>Private photo comparison</title>",
            "<h1>Private local comparison — never upload</h1>",
            "<p>Original links retain original metadata. Copies have no metadata. "
            "Sizes are measured; visual quality requires human review. No SSIM claims.</p>",
            "<style>img{max-width:360px;max-height:300px}article{display:inline-block;"
            "vertical-align:top;margin:12px}section{border-top:1px solid}body{font-family:sans-serif}</style>"]
    previous = None
    for output in report.get("samples", {}).get("outputs", []):
        if previous != output["sample"]:
            if previous is not None:
                rows.append("</section>")
            previous = output["sample"]
            original = source_path(Path(report["data_root"]), output["source"]).as_uri()
            rows.append(f"<section><h2>Sample {previous:03d}</h2><article>Original (local only)<br>"
                        f"<a href='{escape(original, quote=True)}'><img loading='lazy' src='{escape(original, quote=True)}'></a></article>")
        filename = escape(output["file"], quote=True)
        rows.append(f"<article>{escape(output['variant'])}: {output['bytes']:,} bytes; "
                    f"{output['width']}×{output['height']}; saving {output['saving_percent']}%<br>"
                    f"<a href='{filename}'><img loading='lazy' src='{filename}'></a></article>")
    if previous is not None:
        rows.append("</section>")
    atomic_new(run / "comparison.html", "\n".join(rows).encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("audit", "sample", "report"))
    parser.add_argument("--data-root", type=Path, default=PROJECT,
                        help="Actual configured DATA_ROOT, not independent PHOTOS_ROOT")
    parser.add_argument("--run", required=True, help="New private run name; existing name for report")
    parser.add_argument("--count", type=int, default=36, help="1-48 images, default 36")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.run):
        parser.error("Unsafe run name")
    if not 1 <= args.count <= 48:
        parser.error("Count must be 1-48")
    if args.mode == "report":
        path = no_links(PRIVATE / args.run / "report.json")
        report = json.loads(path.read_text(encoding="utf-8"))
    else:
        report = audit(args.data_root)
        run = new_run(args.run, args.data_root)
        if args.mode == "sample":
            report["samples"] = compress_samples(report, run, args.count)
            report["comparison"] = comparison_summary(report["samples"])
        save_report(run, report)
    # Terminal summary deliberately omits inventory-identifying paths and names.
    print(json.dumps({"summary": report["summary"], "database": report["database"],
                      "normal_root_exists": report["normal_root_exists"],
                      "registered_rows": report["registered_rows"],
                      "legacy_folders_checked": report.get("legacy_folders_checked"),
                      "legacy_folders_found": report.get("legacy_folders_found"),
                      "comparison": report.get("comparison"),
                      "samples": {k: v for k, v in report.get("samples", {}).items()
                                  if k not in {"outputs", "errors"}},
                      "sample_error_count": len(report.get("samples", {}).get("errors", []))}, indent=2))


if __name__ == "__main__":
    main()
