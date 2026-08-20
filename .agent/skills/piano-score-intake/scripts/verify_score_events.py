#!/usr/bin/env python3
"""Build and deterministically compare simple piano MusicXML event sequences."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


PPQ = 960
DURATION_TICKS = {
    "whole": 3840,
    "dotted-half": 2880,
    "half": 1920,
    "dotted-quarter": 1440,
    "quarter": 960,
    "eighth": 480,
    "sixteenth": 240,
}
TYPE_AND_DOTS = {
    3840: ("whole", 0),
    2880: ("half", 1),
    1920: ("half", 0),
    1440: ("quarter", 1),
    960: ("quarter", 0),
    480: ("eighth", 0),
    240: ("16th", 0),
}
PITCH_PATTERN = re.compile(r"^([A-G])([#b]?)(-?\d+)$")


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def read_xml(path: Path) -> ET.Element:
    if path.suffix.lower() != ".mxl":
        return ET.parse(path).getroot()
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
        document = rootfile or (candidates[0] if candidates else None)
        if not document:
            raise ValueError("MXL contains no MusicXML document")
        return ET.fromstring(archive.read(document))


def pitch_name(note: ET.Element) -> str:
    pitch = descendants(note, "pitch")
    if not pitch:
        raise ValueError("Expected a pitched note")
    step = first_text(pitch[0], "step")
    octave = first_text(pitch[0], "octave")
    alter = int(first_text(pitch[0], "alter", "0"))
    accidental = "#" if alter == 1 else "b" if alter == -1 else ""
    if alter not in {-1, 0, 1}:
        accidental = f"({alter:+d})"
    return f"{step}{accidental}{octave}"


def normalize_score(path: Path) -> dict[str, Any]:
    root = read_xml(path)
    parts = descendants(root, "part")
    if len(parts) != 1:
        raise ValueError(f"Expected one piano part, found {len(parts)}")
    divisions = 1
    beats, beat_type = 4, 4
    measures: list[dict[str, Any]] = []
    for measure in children(parts[0], "measure"):
        attributes = children(measure, "attributes")
        if attributes:
            divisions_text = first_text(attributes[-1], "divisions")
            if divisions_text:
                divisions = int(divisions_text)
            times = descendants(attributes[-1], "time")
            if times:
                beats = int(first_text(times[-1], "beats", str(beats)))
                beat_type = int(first_text(times[-1], "beat-type", str(beat_type)))
        if divisions <= 0:
            raise ValueError("MusicXML divisions must be positive")
        streams: dict[tuple[str, str], list[dict[str, Any]]] = {}
        positions: dict[tuple[str, str], int] = {}
        for note in children(measure, "note"):
            if descendants(note, "grace"):
                continue
            duration_text = first_text(note, "duration")
            if not duration_text:
                raise ValueError(f"Measure {measure.attrib.get('number')}: note has no duration")
            numerator = int(duration_text) * PPQ
            if numerator % divisions:
                raise ValueError(
                    f"Measure {measure.attrib.get('number')}: duration cannot convert exactly to {PPQ} PPQ"
                )
            duration = numerator // divisions
            key = (first_text(note, "staff", "1"), first_text(note, "voice", "1"))
            stream = streams.setdefault(key, [])
            if descendants(note, "chord"):
                if not stream or "pitches" not in stream[-1]:
                    raise ValueError(f"Measure {measure.attrib.get('number')}: orphan chord note")
                if stream[-1]["duration"] != duration:
                    raise ValueError(f"Measure {measure.attrib.get('number')}: chord duration mismatch")
                stream[-1]["pitches"].append(pitch_name(note))
                stream[-1]["pitches"].sort()
                continue
            event: dict[str, Any] = {
                "at": positions.get(key, 0),
                "duration": duration,
            }
            if descendants(note, "rest"):
                event["rest"] = True
            else:
                event["pitches"] = [pitch_name(note)]
            stream.append(event)
            positions[key] = event["at"] + duration
        staves: dict[str, list[dict[str, Any]]] = {}
        for (staff, voice), stream in streams.items():
            other_voices = [key for key in streams if key[0] == staff and key[1] != voice]
            if other_voices:
                raise ValueError(f"Measure {measure.attrib.get('number')}: multiple voices on staff {staff}")
            staves[staff] = stream
        measures.append(
            {
                "number": measure.attrib.get("number", str(len(measures) + 1)),
                "timeSignature": f"{beats}/{beat_type}",
                "staves": staves,
            }
        )
    return {"ppq": PPQ, "measures": measures}


def expected_normalized(expected: dict[str, Any]) -> dict[str, Any]:
    time_signature = expected.get("timeSignature", "4/4")
    measures: list[dict[str, Any]] = []
    for source_measure in expected.get("measures", []):
        staves: dict[str, list[dict[str, Any]]] = {}
        for staff, source_events in source_measure.get("staves", {}).items():
            at = 0
            events = []
            for source_event in source_events:
                duration_value = source_event["duration"]
                duration = DURATION_TICKS.get(duration_value, duration_value)
                if not isinstance(duration, int):
                    raise ValueError(f"Unknown duration: {duration_value}")
                event: dict[str, Any] = {"at": at, "duration": duration}
                if source_event.get("rest"):
                    event["rest"] = True
                else:
                    event["pitches"] = sorted(source_event.get("pitches", []))
                events.append(event)
                at += duration
            staves[str(staff)] = events
        measures.append(
            {
                "number": str(source_measure["number"]),
                "timeSignature": source_measure.get("timeSignature", time_signature),
                "staves": staves,
            }
        )
    return {"ppq": PPQ, "measures": measures}


def format_event(event: dict[str, Any]) -> str:
    content = "rest" if event.get("rest") else "+".join(event.get("pitches", []))
    return f"{content}@{event['at']}+{event['duration']}"


def compare(score: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    differences: list[str] = []
    actual_measures = score["measures"]
    expected_measures = expected["measures"]
    if len(actual_measures) != len(expected_measures):
        differences.append(f"measure count: expected {len(expected_measures)}, found {len(actual_measures)}")
    for index in range(max(len(actual_measures), len(expected_measures))):
        if index >= len(actual_measures):
            differences.append(f"measure {expected_measures[index]['number']}: missing from score")
            continue
        if index >= len(expected_measures):
            differences.append(f"measure {actual_measures[index]['number']}: unexpected extra measure")
            continue
        actual = actual_measures[index]
        wanted = expected_measures[index]
        label = wanted["number"]
        if actual["number"] != wanted["number"]:
            differences.append(f"measure index {index + 1}: expected number {wanted['number']}, found {actual['number']}")
        if actual["timeSignature"] != wanted["timeSignature"]:
            differences.append(
                f"measure {label}: expected time {wanted['timeSignature']}, found {actual['timeSignature']}"
            )
        for staff in sorted(set(actual["staves"]) | set(wanted["staves"])):
            actual_events = actual["staves"].get(staff, [])
            wanted_events = wanted["staves"].get(staff, [])
            if actual_events != wanted_events:
                differences.append(
                    f"measure {label} staff {staff}: expected "
                    f"[{', '.join(map(format_event, wanted_events))}], found "
                    f"[{', '.join(map(format_event, actual_events))}]"
                )
    return differences


def add_pitch(note: ET.Element, name: str) -> None:
    match = PITCH_PATTERN.match(name)
    if not match:
        raise ValueError(f"Unsupported pitch name: {name}")
    step, accidental, octave = match.groups()
    pitch = ET.SubElement(note, "pitch")
    ET.SubElement(pitch, "step").text = step
    if accidental:
        ET.SubElement(pitch, "alter").text = "1" if accidental == "#" else "-1"
    ET.SubElement(pitch, "octave").text = octave


def add_event(measure: ET.Element, event: dict[str, Any], staff: int, voice: int) -> None:
    duration_value = event["duration"]
    duration_ticks = DURATION_TICKS.get(duration_value, duration_value)
    if not isinstance(duration_ticks, int) or duration_ticks % (PPQ // 4):
        raise ValueError(f"Duration must resolve to a multiple of {PPQ // 4} ticks: {duration_value}")
    duration_divisions = duration_ticks // (PPQ // 4)
    pitches = event.get("pitches", [])
    note_count = len(pitches) if pitches else 1
    for index in range(note_count):
        note = ET.SubElement(measure, "note")
        if index:
            ET.SubElement(note, "chord")
        if event.get("rest"):
            ET.SubElement(note, "rest")
        else:
            add_pitch(note, pitches[index])
        ET.SubElement(note, "duration").text = str(duration_divisions)
        ET.SubElement(note, "voice").text = str(voice)
        note_type, dots = TYPE_AND_DOTS[duration_ticks]
        ET.SubElement(note, "type").text = note_type
        for _ in range(dots):
            ET.SubElement(note, "dot")
        ET.SubElement(note, "staff").text = str(staff)


def build_score(expected: dict[str, Any]) -> ET.ElementTree:
    root = ET.Element("score-partwise", {"version": "4.0"})
    work = ET.SubElement(root, "work")
    ET.SubElement(work, "work-title").text = expected.get("title", "Untitled")
    identification = ET.SubElement(root, "identification")
    ET.SubElement(identification, "creator", {"type": "composer"}).text = expected.get("composer", "")
    encoding = ET.SubElement(identification, "encoding")
    ET.SubElement(encoding, "software").text = "Piano Tutor deterministic event builder"
    part_list = ET.SubElement(root, "part-list")
    score_part = ET.SubElement(part_list, "score-part", {"id": "P1"})
    ET.SubElement(score_part, "part-name").text = "Piano"
    part = ET.SubElement(root, "part", {"id": "P1"})
    beats, beat_type = expected.get("timeSignature", "4/4").split("/", 1)
    measure_duration = int(int(beats) * PPQ * 4 / int(beat_type))
    dynamics = expected.get("dynamics", {})
    for index, source_measure in enumerate(expected.get("measures", [])):
        number = str(source_measure["number"])
        measure = ET.SubElement(part, "measure", {"number": number})
        if index == 0:
            attributes = ET.SubElement(measure, "attributes")
            ET.SubElement(attributes, "divisions").text = "4"
            key = ET.SubElement(attributes, "key")
            ET.SubElement(key, "fifths").text = str(expected.get("keyFifths", 0))
            time = ET.SubElement(attributes, "time")
            ET.SubElement(time, "beats").text = beats
            ET.SubElement(time, "beat-type").text = beat_type
            ET.SubElement(attributes, "staves").text = "2"
            clef1 = ET.SubElement(attributes, "clef", {"number": "1"})
            ET.SubElement(clef1, "sign").text = "G"
            ET.SubElement(clef1, "line").text = "2"
            clef2 = ET.SubElement(attributes, "clef", {"number": "2"})
            ET.SubElement(clef2, "sign").text = "F"
            ET.SubElement(clef2, "line").text = "4"
            if expected.get("tempoText"):
                direction = ET.SubElement(measure, "direction", {"placement": "above"})
                direction_type = ET.SubElement(direction, "direction-type")
                ET.SubElement(direction_type, "words").text = expected["tempoText"]
        if number in dynamics:
            direction = ET.SubElement(measure, "direction", {"placement": "below"})
            direction_type = ET.SubElement(direction, "direction-type")
            dynamic = ET.SubElement(direction_type, "dynamics")
            ET.SubElement(dynamic, dynamics[number])
            ET.SubElement(direction, "staff").text = "1"
        staves = source_measure.get("staves", {})
        for event in staves.get("1", []):
            add_event(measure, event, staff=1, voice=1)
        backup = ET.SubElement(measure, "backup")
        ET.SubElement(backup, "duration").text = str(measure_duration // (PPQ // 4))
        for event in staves.get("2", []):
            add_event(measure, event, staff=2, voice=2)
        if index == len(expected["measures"]) - 1:
            barline = ET.SubElement(measure, "barline", {"location": "right"})
            ET.SubElement(barline, "bar-style").text = "light-heavy"
    ET.indent(root, space="  ")
    return ET.ElementTree(root)


def build_command(args: argparse.Namespace) -> int:
    expected_path = Path(args.expected).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    output.parent.mkdir(parents=True, exist_ok=True)
    build_score(expected).write(output, encoding="utf-8", xml_declaration=True)
    print(output)
    return 0


def extract_command(args: argparse.Namespace) -> int:
    score = Path(args.score).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    write_json(output, normalize_score(score))
    print(output)
    return 0


def check_command(args: argparse.Namespace) -> int:
    score_path = Path(args.score).expanduser().resolve()
    expected_path = Path(args.expected).expanduser().resolve()
    expected_source = json.loads(expected_path.read_text(encoding="utf-8"))
    actual = normalize_score(score_path)
    wanted = expected_normalized(expected_source)
    differences = compare(actual, wanted)
    gate_errors: list[str] = []
    reference_review = expected_source.get("referenceReview", {})
    if reference_review.get("status") != "approved" or not reference_review.get("reviewer"):
        gate_errors.append("expected-event reference has not been explicitly visually reviewed")
    expected_source_sha = expected_source.get("sourceSha256")
    actual_source_sha = None
    if expected_source_sha:
        if not args.source:
            gate_errors.append("--source is required to verify the expected-event reference against its source hash")
        else:
            source_path = Path(args.source).expanduser().resolve()
            actual_source_sha = sha256_file(source_path)
            if actual_source_sha != expected_source_sha:
                gate_errors.append("source SHA-256 does not match the expected-event reference")
    provenance = None
    provenance_path = Path(args.provenance).expanduser().resolve() if args.provenance else None
    if provenance_path:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        if provenance.get("packagedScoreSha256") != sha256_file(score_path):
            gate_errors.append("provenance does not match the score being checked")
    is_valid = not differences and not gate_errors
    report = {
        "valid": is_valid,
        "status": "passed" if is_valid else "failed",
        "deterministic": True,
        "scope": ["measure-count", "time-signatures", "staves", "rests", "event-order", "pitches", "chords", "durations"],
        "score": str(score_path),
        "scoreSha256": sha256_file(score_path),
        "expected": str(expected_path),
        "expectedSha256": sha256_file(expected_path),
        "sourceSha256": expected_source_sha,
        "actualSourceSha256": actual_source_sha,
        "referenceReview": reference_review,
        "gateErrors": gate_errors,
        "differences": differences,
    }
    if args.report:
        write_json(Path(args.report).expanduser().resolve(), report)
    if provenance_path and provenance is not None:
        provenance.setdefault("verification", {})["deterministicEvents"] = report
        source_ok = provenance["verification"].get("sourceComparison", {}).get("status") == "approved"
        importer_ok = provenance["verification"].get("graditoneImporter", {}).get("status") == "passed"
        provenance["releaseStatus"] = "approved" if is_valid and source_ok and importer_ok else "candidate"
        write_json(provenance_path, provenance)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["valid"] else 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="Build simple piano MusicXML from an expected-event manifest")
    build.add_argument("expected")
    build.add_argument("output")
    build.set_defaults(func=build_command)
    extract = subparsers.add_parser("extract", help="Extract normalized events from MusicXML/MXL")
    extract.add_argument("score")
    extract.add_argument("output")
    extract.set_defaults(func=extract_command)
    check = subparsers.add_parser("check", help="Compare MusicXML/MXL exactly with an expected-event manifest")
    check.add_argument("score")
    check.add_argument("expected")
    check.add_argument("--source", help="Original PDF/image; required when expected JSON contains sourceSha256")
    check.add_argument("--report")
    check.add_argument("--provenance", help="Update packaged-score provenance with this deterministic result")
    check.set_defaults(func=check_command)
    return result


def main() -> int:
    try:
        args = parser().parse_args()
        return args.func(args)
    except (ET.ParseError, OSError, ValueError, zipfile.BadZipFile) as error:
        print(json.dumps({"valid": False, "error": str(error)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
