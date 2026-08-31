#!/usr/bin/env python3
"""Prepare, transcribe, review, verify, package, and catalogue piano scores."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


SCRIPT_DIR = Path(__file__).resolve().parent
APPLE_OCR = SCRIPT_DIR / "apple_vision_ocr.swift"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".webp"}
REVIEW_STATUSES = {"pending", "matched", "uncertain"}
CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="score.musicxml" media-type="application/vnd.recordare.musicxml+xml"/>
  </rootfiles>
</container>
"""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-") or "untitled-score"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(
    command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, capture_output=True, cwd=cwd, env=env)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def children(root: ET.Element, name: str) -> list[ET.Element]:
    return [element for element in list(root) if local_name(element.tag) == name]


def descendants(root: ET.Element, name: str) -> list[ET.Element]:
    return [element for element in root.iter() if local_name(element.tag) == name]


def first_text(root: ET.Element, name: str, default: str = "") -> str:
    for element in root.iter():
        if local_name(element.tag) == name and element.text:
            return element.text.strip()
    return default


def parse_rotation(value: str) -> tuple[int, int]:
    try:
        page_text, degrees_text = value.split(":", 1)
        page, degrees = int(page_text), int(degrees_text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("rotation must be PAGE:DEGREES, for example 7:180") from error
    if page < 1 or degrees not in {0, 90, 180, 270}:
        raise argparse.ArgumentTypeError("page must be positive and degrees must be 0, 90, 180, or 270")
    return page, degrees


def rotate_page(path: Path, degrees: int) -> None:
    if degrees == 0:
        return
    if shutil.which("sips"):
        run(["sips", "-r", str(degrees), str(path)])
        return
    try:
        from PIL import Image
    except ImportError as error:
        raise SystemExit("Page rotation requires macOS sips or Pillow.") from error
    with Image.open(path) as image:
        image.rotate(-degrees, expand=True).save(path)


def prepare(args: argparse.Namespace) -> int:
    source = Path(args.input).expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Input does not exist: {source}")
    title = args.title or source.stem.replace("_", " ").replace("-", " ").strip()
    slug = args.slug or slugify(title)
    root = Path(args.project_root).expanduser().resolve()
    output = Path(args.output).expanduser().resolve() if args.output else root / "tmp" / "score-intake" / slug
    pages_dir = output / "pages"
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)

    suffix = source.suffix.lower()
    if suffix == ".pdf":
        if not shutil.which("pdftoppm"):
            raise SystemExit("pdftoppm is required for PDF input (install Poppler).")
        run(["pdftoppm", "-png", "-r", str(args.dpi), str(source), str(pages_dir / "page")])
        pages = sorted(pages_dir.glob("page-*.png"), key=lambda path: int(path.stem.rsplit("-", 1)[-1]))
    elif suffix in IMAGE_SUFFIXES:
        destination = pages_dir / f"page-001{suffix}"
        shutil.copy2(source, destination)
        pages = [destination]
    else:
        raise SystemExit(f"Unsupported input type: {suffix or '(none)'}")
    if not pages:
        raise SystemExit("No page images were produced.")

    rotations = dict(args.rotate or [])
    for page, degrees in rotations.items():
        if page > len(pages):
            raise SystemExit(f"Rotation refers to page {page}, but only {len(pages)} page(s) were rendered.")
        rotate_page(pages[page - 1], degrees)

    ocr: list[dict[str, object]] = []
    ocr_status = "skipped"
    ocr_error = None
    if not args.no_apple_ocr and sys.platform == "darwin" and shutil.which("swift"):
        ocr_env = os.environ.copy()
        xcode = Path("/Applications/Xcode.app/Contents/Developer")
        if xcode.is_dir():
            ocr_env["DEVELOPER_DIR"] = str(xcode)
        module_cache = output / ".swift-module-cache"
        module_cache.mkdir(parents=True, exist_ok=True)
        ocr_env["CLANG_MODULE_CACHE_PATH"] = str(module_cache)
        ocr_env["SWIFT_MODULECACHE_PATH"] = str(module_cache)
        try:
            result = run(["swift", str(APPLE_OCR), *map(str, pages)], env=ocr_env)
            ocr = json.loads(result.stdout)
            ocr_status = "apple-vision" if any(page.get("lines") for page in ocr) else "apple-vision-unavailable"
        except (subprocess.CalledProcessError, json.JSONDecodeError) as error:
            ocr_status = "apple-vision-failed"
            if isinstance(error, subprocess.CalledProcessError):
                ocr_error = (error.stderr or error.stdout or str(error)).strip()
            else:
                ocr_error = str(error)

    manifest = {
        "schemaVersion": 2,
        "title": title,
        "slug": slug,
        "source": str(source),
        "sourceSha256": sha256_file(source),
        "createdAt": utc_now(),
        "pageCount": len(pages),
        "pages": [str(page.relative_to(output)) for page in pages],
        "pageRotations": {str(page): degrees for page, degrees in sorted(rotations.items())},
        "ocr": {
            "engine": ocr_status,
            "purpose": "printed-text-metadata-only",
            "pages": ocr,
            "error": ocr_error,
        },
        "rights": {"privateUse": not args.public_domain},
        "transcription": {"status": "not-started", "score": None, "engine": None},
        "sourceComparison": {"status": "pending", "reviewFile": None},
    }
    write_json(output / "intake.json", manifest)
    print(output / "intake.json")
    return 0


def find_audiveris(explicit: str | None) -> Path | None:
    candidates = [
        Path(explicit).expanduser() if explicit else None,
        Path(shutil.which("audiveris")) if shutil.which("audiveris") else None,
        Path(shutil.which("Audiveris")) if shutil.which("Audiveris") else None,
        Path("/Applications/Audiveris.app/Contents/MacOS/Audiveris"),
    ]
    return next((path.resolve() for path in candidates if path and path.is_file()), None)


def omr(args: argparse.Namespace) -> int:
    source = Path(args.input).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Input does not exist: {source}")
    engine = find_audiveris(args.audiveris)
    if not engine:
        raise SystemExit(
            "Audiveris is not installed. Install the official macOS application, then rerun with "
            "--audiveris /Applications/Audiveris.app/Contents/MacOS/Audiveris."
        )

    output.mkdir(parents=True, exist_ok=True)
    command = [str(engine), "-batch", "-transcribe", "-export", "-save", "-output", str(output)]
    if args.force:
        command.append("-force")
    if args.sheets:
        command.extend(["-sheets", *args.sheets])
    command.extend(["--", str(source)])
    result = run(command)
    generated = sorted(
        str(path.resolve())
        for path in output.glob("*")
        if path.suffix.lower() in {".mxl", ".xml", ".musicxml", ".omr"}
    )
    score_outputs = [Path(path) for path in generated if Path(path).suffix.lower() in {".mxl", ".xml", ".musicxml"}]
    if not score_outputs:
        raise SystemExit("Audiveris completed without producing a MusicXML/MXL draft; inspect its log in the output directory.")
    validations: list[dict[str, object]] = []
    for score_output in score_outputs:
        try:
            validations.append(validate_score(score_output))
        except (ET.ParseError, OSError, ValueError, zipfile.BadZipFile) as error:
            validations.append({"valid": False, "file": str(score_output), "errors": [str(error)]})
    version = "unknown"
    try:
        version_result = run([str(engine), "-version"])
        version = (version_result.stdout or version_result.stderr).strip() or "unknown"
    except subprocess.CalledProcessError:
        pass
    report = {
        "schemaVersion": 1,
        "engine": {"name": "Audiveris", "version": version, "executable": str(engine)},
        "source": str(source),
        "sourceSha256": sha256_file(source),
        "sheets": args.sheets or "all",
        "generatedAt": utc_now(),
        "outputs": generated,
        "status": "unverified-omr-draft",
        "sourceComparison": "required",
        "structuralValidation": validations,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }
    report_path = output / "omr-run.json"
    write_json(report_path, report)
    print(report_path)
    return 0


def read_musicxml_bytes(path: Path) -> tuple[bytes, str]:
    if path.suffix.lower() != ".mxl":
        return path.read_bytes(), path.name
    if not zipfile.is_zipfile(path):
        raise ValueError("The .mxl file is not a ZIP archive")
    with zipfile.ZipFile(path) as archive:
        rootfile = None
        if "META-INF/container.xml" in archive.namelist():
            container = ET.fromstring(archive.read("META-INF/container.xml"))
            for element in container.iter():
                if local_name(element.tag) == "rootfile":
                    rootfile = element.attrib.get("full-path")
                    break
        candidates = [
            name for name in archive.namelist()
            if name.lower().endswith((".xml", ".musicxml")) and not name.startswith("META-INF/")
        ]
        name = rootfile or (sorted(candidates, key=lambda item: (item.count("/"), len(item)))[0] if candidates else None)
        if not name or name not in archive.namelist():
            raise ValueError("The .mxl archive has no readable MusicXML rootfile")
        return archive.read(name), name


def read_musicxml(path: Path) -> tuple[ET.Element, str]:
    payload, document = read_musicxml_bytes(path)
    return ET.fromstring(payload), document


def validate_score(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ValueError(f"Score does not exist: {path}")
    root, document = read_musicxml(path)
    root_name = local_name(root.tag)
    if root_name not in {"score-partwise", "score-timewise"}:
        raise ValueError(f"Unexpected MusicXML root element: {root_name}")

    parts = descendants(root, "part")
    measures = descendants(root, "measure")
    notes = descendants(root, "note")
    pitched = sum(1 for note in notes if descendants(note, "pitch"))
    rests = sum(1 for note in notes if descendants(note, "rest"))
    titles = [
        element.text.strip()
        for element in descendants(root, "work-title") + descendants(root, "movement-title")
        if element.text and element.text.strip()
    ]
    errors: list[str] = []
    warnings: list[str] = []
    if not parts:
        errors.append("No <part> elements")
    if not measures:
        errors.append("No <measure> elements")
    if not notes:
        errors.append("No <note> elements")
    malformed = sum(
        1 for note in notes
        if not (descendants(note, "rest") or descendants(note, "pitch") or descendants(note, "unpitched"))
    )
    if malformed:
        errors.append(f"{malformed} note elements have no pitch, rest, or unpitched value")

    timing_checks = 0
    exact_ppq = True
    time_signatures: set[str] = set()
    for part_index, part in enumerate(parts, start=1):
        divisions = 1
        beats = 4
        beat_type = 4
        for measure in children(part, "measure"):
            number = measure.attrib.get("number", "?")
            attributes = children(measure, "attributes")
            if attributes:
                divisions_text = first_text(attributes[-1], "divisions")
                if divisions_text:
                    divisions = int(divisions_text)
                    if divisions <= 0:
                        errors.append(f"Part {part_index} measure {number}: divisions must be positive")
                        divisions = 1
                time_nodes = descendants(attributes[-1], "time")
                if time_nodes:
                    beats = int(first_text(time_nodes[-1], "beats", str(beats)))
                    beat_type = int(first_text(time_nodes[-1], "beat-type", str(beat_type)))
            time_signatures.add(f"{beats}/{beat_type}")
            expected = divisions * beats * 4 / beat_type
            voice_totals: dict[tuple[str, str], int] = {}
            skip_timeline = bool(children(measure, "forward"))
            for note in children(measure, "note"):
                duration_text = first_text(note, "duration")
                if duration_text and not descendants(note, "grace"):
                    duration = int(duration_text)
                    if (duration * 960) % divisions:
                        exact_ppq = False
                        errors.append(
                            f"Part {part_index} measure {number}: duration {duration}/{divisions} cannot convert exactly to 960 PPQ"
                        )
                    if not descendants(note, "chord"):
                        key = (first_text(note, "staff", "1"), first_text(note, "voice", "1"))
                        voice_totals[key] = voice_totals.get(key, 0) + duration
            if skip_timeline:
                warnings.append(f"Part {part_index} measure {number}: timeline check skipped because <forward> is present")
                continue
            voices_per_staff: dict[str, set[str]] = {}
            for staff, voice in voice_totals:
                voices_per_staff.setdefault(staff, set()).add(voice)
            if any(len(voices) > 1 for voices in voices_per_staff.values()):
                warnings.append(f"Part {part_index} measure {number}: timeline check skipped for multiple voices on one staff")
                continue
            if measure.attrib.get("implicit") != "yes":
                for (staff, voice), actual in voice_totals.items():
                    timing_checks += 1
                    if actual != expected:
                        errors.append(
                            f"Part {part_index} measure {number}, staff {staff}, voice {voice}: "
                            f"duration {actual}, expected {expected:g}"
                        )

    return {
        "valid": not errors,
        "scope": "structural-and-timeline-only",
        "sourceAccuracyVerified": False,
        "file": str(path),
        "document": document,
        "root": root_name,
        "title": titles[0] if titles else None,
        "parts": len(parts),
        "measures": len(measures),
        "measureNumbers": list(dict.fromkeys(
            element.attrib.get("number", str(index)) for index, element in enumerate(measures, 1)
        )),
        "notes": len(notes),
        "pitchedNotes": pitched,
        "rests": rests,
        "timeSignatures": sorted(time_signatures),
        "timelineChecks": timing_checks,
        "exact960Ppq": exact_ppq,
        "warnings": warnings,
        "errors": errors,
    }


def validate(args: argparse.Namespace) -> int:
    try:
        summary = validate_score(Path(args.score).expanduser().resolve())
    except (ET.ParseError, OSError, ValueError, zipfile.BadZipFile) as error:
        print(json.dumps({"valid": False, "errors": [str(error)]}, indent=2))
        return 1
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["valid"] else 1


def init_review(args: argparse.Namespace) -> int:
    score = Path(args.score).expanduser().resolve()
    intake_path = Path(args.intake).expanduser().resolve()
    intake = read_json(intake_path)
    summary = validate_score(score)
    if not summary["valid"]:
        raise SystemExit("Cannot review a structurally invalid score: " + "; ".join(summary["errors"]))
    output = Path(args.output).expanduser().resolve() if args.output else score.with_suffix(".review.json")
    available_pages = intake.get("pages", [])
    selected_pages = getattr(args, "source_page", None)
    if selected_pages and any(page < 1 or page > len(available_pages) for page in selected_pages):
        raise SystemExit(f"--source-page must be between 1 and {len(available_pages)}")
    review = {
        "schemaVersion": 1,
        "score": str(score),
        "scoreSha256": sha256_file(score),
        "source": intake.get("source"),
        "sourceSha256": intake.get("sourceSha256"),
        "sourcePages": [available_pages[page - 1] for page in selected_pages] if selected_pages else available_pages,
        "createdAt": utc_now(),
        "updatedAt": utc_now(),
        "reviewer": None,
        "status": "needs-review",
        "measures": [{"number": number, "status": "pending", "notes": ""} for number in summary["measureNumbers"]],
        "instructions": "Compare every measure, both staves, repeats, accidentals, rhythm, and fingering against the rendered source pages.",
    }
    write_json(output, review)
    print(output)
    return 0


def mark_review(args: argparse.Namespace) -> int:
    path = Path(args.review).expanduser().resolve()
    review = read_json(path)
    selected = set(args.measure or [])
    if args.all_measures:
        selected = {str(item["number"]) for item in review.get("measures", [])}
    if not selected:
        raise SystemExit("Select at least one --measure or use --all-measures.")
    found: set[str] = set()
    for item in review.get("measures", []):
        number = str(item.get("number"))
        if number in selected:
            item["status"] = args.status
            if args.note:
                item["notes"] = args.note
            found.add(number)
    missing = selected - found
    if missing:
        raise SystemExit("Unknown measure(s): " + ", ".join(sorted(missing)))
    review["reviewer"] = args.reviewer
    review["updatedAt"] = utc_now()
    statuses = {item.get("status") for item in review.get("measures", [])}
    review["status"] = "approved" if statuses == {"matched"} and args.reviewer else "needs-review"
    write_json(path, review)
    print(json.dumps({"review": str(path), "status": review["status"], "updatedMeasures": sorted(found)}, indent=2))
    return 0


def package_mxl(xml_payload: bytes, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "mimetype", "application/vnd.recordare.musicxml", compress_type=zipfile.ZIP_STORED
        )
        archive.writestr("META-INF/container.xml", CONTAINER_XML)
        archive.writestr("score.musicxml", xml_payload)


def package(args: argparse.Namespace) -> int:
    score = Path(args.score).expanduser().resolve()
    review_path = Path(args.review).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    review = read_json(review_path)
    summary = validate_score(score)
    if not summary["valid"]:
        raise SystemExit("Cannot package a structurally invalid score: " + "; ".join(summary["errors"]))
    if review.get("scoreSha256") != sha256_file(score):
        raise SystemExit("Review file does not match the current score bytes; initialize or repeat the review.")
    approved = review.get("status") == "approved"
    if not approved and not args.draft:
        raise SystemExit("Source comparison is not approved. Use --draft only for a clearly unverified package.")
    xml_payload, _ = read_musicxml_bytes(score)
    package_mxl(xml_payload, output)
    provenance_path = Path(args.provenance).expanduser().resolve() if args.provenance else output.with_suffix(".provenance.json")
    provenance = {
        "schemaVersion": 1,
        "title": args.title or summary.get("title") or score.stem,
        "composer": args.composer,
        "packagedScore": str(output),
        "packagedScoreSha256": sha256_file(output),
        "source": review.get("source"),
        "sourceSha256": review.get("sourceSha256"),
        "rights": {"privateUse": not args.public_domain},
        "createdAt": utc_now(),
        "verification": {
            "structural": {"status": "passed", "report": summary},
            "deterministicEvents": {"status": "pending"},
            "graditoneImporter": {"status": "pending"},
            "sourceComparison": {
                "status": "approved" if approved else "pending",
                "reviewer": review.get("reviewer"),
                "reviewFile": str(review_path),
            },
        },
        "releaseStatus": "candidate" if approved else "unverified-draft",
    }
    write_json(provenance_path, provenance)
    print(json.dumps({"score": str(output), "provenance": str(provenance_path), "status": provenance["releaseStatus"]}, indent=2))
    return 0


def importer_command(root: Path, score: Path) -> tuple[list[str], Path]:
    backend = root / "backend"
    for binary in (backend / "target/release/musicore-import", backend / "target/debug/musicore-import"):
        if binary.is_file():
            return [str(binary), str(score), "--validate-only", "--verbose"], backend
    if not shutil.which("cargo"):
        raise SystemExit("The Graditone importer is not built and cargo is unavailable.")
    return ["cargo", "run", "--quiet", "--bin", "musicore-import", "--", str(score), "--validate-only", "--verbose"], backend


def verify_import(args: argparse.Namespace) -> int:
    score = Path(args.score).expanduser().resolve()
    root = Path(args.project_root).expanduser().resolve()
    command, cwd = importer_command(root, score)
    result = run(command, cwd=cwd)
    report = {
        "status": "passed",
        "checkedAt": utc_now(),
        "command": command,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }
    if args.provenance:
        provenance_path = Path(args.provenance).expanduser().resolve()
        provenance = read_json(provenance_path)
        if provenance.get("packagedScoreSha256") != sha256_file(score):
            raise SystemExit("Provenance does not match the score passed to the importer.")
        provenance["verification"]["graditoneImporter"] = report
        source_ok = provenance["verification"]["sourceComparison"].get("status") == "approved"
        events_ok = provenance["verification"].get("deterministicEvents", {}).get("status") == "passed"
        provenance["releaseStatus"] = "approved" if source_ok and events_ok else "candidate"
        write_json(provenance_path, provenance)
    print(json.dumps(report, indent=2))
    return 0


def catalogue(args: argparse.Namespace) -> int:
    source = Path(args.score).expanduser().resolve()
    provenance_path = Path(args.provenance).expanduser().resolve()
    provenance = read_json(provenance_path)
    if provenance.get("packagedScoreSha256") != sha256_file(source):
        raise SystemExit("Provenance does not match the score being catalogued.")
    verification = provenance.get("verification", {})
    if verification.get("sourceComparison", {}).get("status") != "approved":
        raise SystemExit("Cannot catalogue: source comparison has not been approved.")
    if verification.get("graditoneImporter", {}).get("status") != "passed":
        raise SystemExit("Cannot catalogue: the actual Graditone importer has not passed.")
    if verification.get("deterministicEvents", {}).get("status") != "passed":
        raise SystemExit("Cannot catalogue: deterministic score-event validation has not passed.")
    summary = validate_score(source)
    if not summary["valid"]:
        raise SystemExit("Cannot catalogue invalid score: " + "; ".join(summary["errors"]))

    root = Path(args.project_root).expanduser().resolve()
    slug = args.slug or slugify(args.title)
    filename = f"{slug}.mxl"
    score_dir = root / "scores" / "family"
    score_dir.mkdir(parents=True, exist_ok=True)
    destination = score_dir / filename
    shutil.copy2(source, destination)
    shutil.copy2(provenance_path, score_dir / f"{slug}.provenance.json")

    catalog_path = root / "frontend" / "src" / "data" / "familyScores.private.json"
    catalog = read_json(catalog_path) if catalog_path.exists() else []
    if not isinstance(catalog, list):
        raise SystemExit(f"Expected a JSON array in {catalog_path}")
    display_name = f"{args.composer} — {args.title}" if args.composer else args.title
    entry = {
        "id": slug,
        "displayName": display_name,
        "filename": filename,
        "difficulty": args.difficulty,
        "privateUse": bool(provenance.get("rights", {}).get("privateUse", True)),
        "sourceNote": args.source_note,
    }
    catalog = [item for item in catalog if item.get("id") != slug]
    catalog.append(entry)
    catalog.sort(key=lambda item: str(item.get("displayName", "")).casefold())
    write_json(catalog_path, catalog)
    print(json.dumps({"score": str(destination), "catalog": str(catalog_path), "entry": entry}, indent=2))
    return 0


def status(args: argparse.Namespace) -> int:
    root = Path(args.project_root).expanduser().resolve()
    intake_root = root / "tmp" / "score-intake"
    manifests = sorted(intake_root.glob("*/intake.json")) if intake_root.exists() else []
    catalog_path = root / "frontend" / "src" / "data" / "familyScores.private.json"
    catalog = read_json(catalog_path) if catalog_path.exists() else []
    intakes = []
    for path in manifests:
        value = read_json(path)
        intakes.append({
            "manifest": str(path),
            "title": value.get("title"),
            "transcription": value.get("transcription"),
            "sourceComparison": value.get("sourceComparison"),
        })
    print(json.dumps({"intakes": intakes, "catalog": catalog}, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)

    prep = subparsers.add_parser("prepare", help="Render pages, hash the source, and run printed-text OCR")
    prep.add_argument("input")
    prep.add_argument("--project-root", default=".")
    prep.add_argument("--title")
    prep.add_argument("--slug")
    prep.add_argument("--output")
    prep.add_argument("--dpi", type=int, default=300)
    prep.add_argument("--rotate", action="append", type=parse_rotation, metavar="PAGE:DEGREES")
    prep.add_argument("--no-apple-ocr", action="store_true")
    prep.add_argument("--public-domain", action="store_true")
    prep.set_defaults(func=prepare)

    recognize = subparsers.add_parser("omr", help="Run a real Audiveris batch transcription and mark it unverified")
    recognize.add_argument("input")
    recognize.add_argument("--output", required=True)
    recognize.add_argument("--audiveris")
    recognize.add_argument("--sheets", nargs="+")
    recognize.add_argument("--force", action="store_true")
    recognize.set_defaults(func=omr)

    check = subparsers.add_parser("validate", help="Check MusicXML structure, simple timelines, and exact 960 PPQ conversion")
    check.add_argument("score")
    check.set_defaults(func=validate)

    review_init = subparsers.add_parser("review-init", help="Create a measure-by-measure visual review checklist")
    review_init.add_argument("score")
    review_init.add_argument("--intake", required=True)
    review_init.add_argument("--output")
    review_init.add_argument("--source-page", action="append", type=int)
    review_init.set_defaults(func=init_review)

    review_mark = subparsers.add_parser("review-mark", help="Record explicit source comparison results")
    review_mark.add_argument("review")
    review_mark.add_argument("--measure", action="append")
    review_mark.add_argument("--all-measures", action="store_true")
    review_mark.add_argument("--status", required=True, choices=sorted(REVIEW_STATUSES))
    review_mark.add_argument("--reviewer", required=True)
    review_mark.add_argument("--note")
    review_mark.set_defaults(func=mark_review)

    bundle = subparsers.add_parser("package", help="Create .mxl and provenance without overstating verification")
    bundle.add_argument("score")
    bundle.add_argument("--review", required=True)
    bundle.add_argument("--output", required=True)
    bundle.add_argument("--provenance")
    bundle.add_argument("--title")
    bundle.add_argument("--composer", default="")
    bundle.add_argument("--public-domain", action="store_true")
    bundle.add_argument("--draft", action="store_true")
    bundle.set_defaults(func=package)

    importer = subparsers.add_parser("verify-import", help="Run the repository's actual Graditone Rust importer")
    importer.add_argument("score")
    importer.add_argument("--project-root", default=".")
    importer.add_argument("--provenance")
    importer.set_defaults(func=verify_import)

    add = subparsers.add_parser("catalogue", help="Add only an approved, importer-tested score to Our Songs")
    add.add_argument("score")
    add.add_argument("--provenance", required=True)
    add.add_argument("--project-root", default=".")
    add.add_argument("--title", required=True)
    add.add_argument("--composer", default="")
    add.add_argument("--slug")
    add.add_argument("--difficulty", type=int, choices=(1, 2, 3), default=1)
    add.add_argument("--source-note", default="Private transcription from a user-supplied score")
    add.set_defaults(func=catalogue)

    show = subparsers.add_parser("status", help="Show prepared and catalogued scores")
    show.add_argument("--project-root", default=".")
    show.set_defaults(func=status)
    return result


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip() or str(error)
        print(f"Command failed: {detail}", file=sys.stderr)
        return error.returncode or 1
    except (ET.ParseError, OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
