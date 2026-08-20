---
name: piano-score-intake
description: Prepare piano sheet-music PDFs or images, run real Audiveris OMR when installed, review notation measure by measure, validate MusicXML/MXL with the Graditone importer, and add approved scores to the piano tutor family's private practice catalogue. Use when the user supplies scanned or photographed piano music and asks to convert, import, catalogue, label, or make it available for MIDI-graded practice.
---

# Piano Score Intake

Convert user-supplied sheet music into a private, validated practice score.

## Workflow

1. Prepare the source from the piano tutor repository. Record known page rotations explicitly:

   ```bash
   python3 .agent/skills/piano-score-intake/scripts/score_intake.py prepare INPUT \
     --project-root . --title "TITLE" --rotate 7:180
   ```

   This renders every PDF page at 200 DPI and runs macOS Vision OCR locally. Treat OCR as metadata assistance only; it does not recognize musical notation.

2. Read `intake.json` and inspect every rendered image. Never infer missing measures from another edition without the user's permission. The manifest defaults to private use and records the source SHA-256.

3. Determine rights before proceeding:

   - Create original MusicXML freely for public-domain compositions.
   - Transcribe user-supplied copyrighted pages only for the user's private practice and mark the catalogue entry `privateUse: true`.
   - Do not search for or bundle pirated MusicXML.

4. If Audiveris is installed, generate a real OMR draft:

   ```bash
   python3 .agent/skills/piano-score-intake/scripts/score_intake.py omr INPUT \
     --output tmp/score-intake/TITLE/omr --sheets 1 2
   ```

   Treat every OMR result as `unverified-omr-draft`. If Audiveris is unavailable or its draft is poor, transcribe or correct the score in a notation editor. Preserve visible signatures, voices, rests, chords, tuplets, ties, slurs, repeats, dynamics, articulations, fingering, tempo, pickups, and pedal marks.

5. Run structural/timeline validation. This deliberately reports `sourceAccuracyVerified: false`; a passing result does not prove correspondence to the scan:

   ```bash
   python3 .agent/skills/piano-score-intake/scripts/score_intake.py validate PATH/score.musicxml
   ```

   Resolve every validation error.

   For short/simple scores, create a trusted expected-event JSON while visually transcribing the scan. Build the practice MusicXML from that manifest and compare it deterministically:

   ```bash
   python3 .agent/skills/piano-score-intake/scripts/verify_score_events.py build \
     EXPECTED.json SCORE.musicxml
   python3 .agent/skills/piano-score-intake/scripts/verify_score_events.py check \
     SCORE.musicxml EXPECTED.json --source ORIGINAL.pdf --report EVENTS_REPORT.json
   ```

   This exact comparison covers measure count, time signatures, staves, rests, order, pitches, chords, and durations. It does not independently prove that the human-authored expected manifest matches the image; bind the manifest to the source SHA-256 and complete the visual review once.

6. Create and complete the visual review checklist. Compare every measure on both staves; do not use `--all-measures` until that comparison is genuinely complete:

   ```bash
   python3 .agent/skills/piano-score-intake/scripts/score_intake.py review-init SCORE \
     --intake INTAKE_JSON --source-page 5
   python3 .agent/skills/piano-score-intake/scripts/score_intake.py review-mark REVIEW_JSON \
     --measure 1 --status matched --reviewer "NAME"
   ```

   Use `uncertain` for unreadable or ambiguous notation. Only all-`matched` reviews become approved.

7. Package and run the repository's actual Rust importer:

   ```bash
   python3 .agent/skills/piano-score-intake/scripts/score_intake.py package SCORE \
     --review REVIEW_JSON --output CANDIDATE.mxl --title "TITLE" --composer "COMPOSER"
   python3 .agent/skills/piano-score-intake/scripts/verify_score_events.py check \
     CANDIDATE.mxl EXPECTED.json --source ORIGINAL.pdf \
     --provenance CANDIDATE.provenance.json
   python3 .agent/skills/piano-score-intake/scripts/score_intake.py verify-import CANDIDATE.mxl \
     --project-root . --provenance CANDIDATE.provenance.json
   ```

   Use `package --draft` only for an explicitly unverified artifact. Never call a generic XML parser a Graditone compatibility test.

8. Add only the approved, importer-tested score to the app:

   ```bash
   python3 .agent/skills/piano-score-intake/scripts/score_intake.py catalogue CANDIDATE.mxl \
     --provenance CANDIDATE.provenance.json --project-root . \
     --title "TITLE" --composer "COMPOSER" --difficulty 1 \
     --source-note "Private transcription from user-supplied scan"
   ```

9. Run the frontend catalogue tests and load the score through the app's Practice screen. Report uncertainty rather than silently guessing.

## Apple OCR boundary

Use the bundled Apple Vision helper for printed text and metadata. Do not describe it as Apple Intelligence or as music OCR. Vision OCR does not replace optical music recognition or visual verification of notation.

## Commands

- `prepare`: render and rotate pages, hash the source, run local printed-text OCR, and create an intake manifest.
- `omr`: invoke the real Audiveris CLI and record its output as an unverified draft.
- `validate`: check structure, simple measure timelines, and exact 960-PPQ conversion without claiming source accuracy.
- `verify_score_events.py build/check/extract`: generate a simple practice score and compare normalized musical events exactly against a source-bound expected manifest.
- `review-init` / `review-mark`: maintain an explicit measure-by-measure source comparison.
- `package`: create standard `.mxl` plus truthful provenance; unreviewed output requires `--draft`.
- `verify-import`: run the repository's actual Graditone Rust importer and update provenance.
- `catalogue`: require approved source review and importer verification before updating `Our Songs`.
- `status`: list prepared intake packages and family catalogue entries.
