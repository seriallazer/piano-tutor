import importlib.util
import json
import stat
import tempfile
import unittest
import zipfile
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agent/skills/piano-score-intake/scripts/score_intake.py"
SPEC = importlib.util.spec_from_file_location("score_intake", SCRIPT)
score_intake = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(score_intake)


VALID_SCORE = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <work><work-title>Test Song</work-title></work>
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <staves>2</staves>
      </attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><staff>1</staff></note>
      <backup><duration>4</duration></backup>
      <note><rest/><duration>4</duration><voice>2</voice><staff>2</staff></note>
    </measure>
  </part>
</score-partwise>
"""


class ScoreIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.score = self.root / "score.musicxml"
        self.score.write_text(VALID_SCORE, encoding="utf-8")
        self.intake = self.root / "intake.json"
        score_intake.write_json(
            self.intake,
            {
                "source": "/private/family-score.pdf",
                "sourceSha256": "source-hash",
                "pages": ["pages/page-1.png"],
            },
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_validation_is_structural_and_does_not_claim_source_accuracy(self):
        report = score_intake.validate_score(self.score)
        self.assertTrue(report["valid"])
        self.assertEqual(report["scope"], "structural-and-timeline-only")
        self.assertFalse(report["sourceAccuracyVerified"])
        self.assertEqual(report["timeSignatures"], ["4/4"])
        self.assertEqual(report["timelineChecks"], 2)

    def test_non_exact_960_ppq_conversion_fails(self):
        score = self.root / "bad-ppq.musicxml"
        score.write_text(
            VALID_SCORE.replace("<divisions>1</divisions>", "<divisions>7</divisions>")
            .replace("<duration>4</duration>", "<duration>1</duration>"),
            encoding="utf-8",
        )
        report = score_intake.validate_score(score)
        self.assertFalse(report["valid"])
        self.assertFalse(report["exact960Ppq"])
        self.assertTrue(any("960 PPQ" in error for error in report["errors"]))

    def test_unreviewed_score_requires_explicit_draft_packaging(self):
        review = self.root / "score.review.json"
        score_intake.init_review(Namespace(score=str(self.score), intake=str(self.intake), output=str(review)))
        output = self.root / "score.mxl"
        args = Namespace(
            score=str(self.score),
            review=str(review),
            output=str(output),
            provenance=None,
            title="Test Song",
            composer="",
            public_domain=False,
            draft=False,
        )
        with self.assertRaises(SystemExit):
            score_intake.package(args)
        args.draft = True
        self.assertEqual(score_intake.package(args), 0)
        provenance = json.loads(output.with_suffix(".provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["releaseStatus"], "unverified-draft")
        self.assertTrue(provenance["rights"]["privateUse"])
        with zipfile.ZipFile(output) as archive:
            self.assertIn("META-INF/container.xml", archive.namelist())
            self.assertIn("score.musicxml", archive.namelist())
            self.assertEqual(archive.getinfo("mimetype").compress_type, zipfile.ZIP_STORED)

    def test_all_measures_must_be_explicitly_matched_for_approval(self):
        review = self.root / "score.review.json"
        score_intake.init_review(Namespace(score=str(self.score), intake=str(self.intake), output=str(review)))
        score_intake.mark_review(
            Namespace(
                review=str(review),
                measure=None,
                all_measures=True,
                status="matched",
                reviewer="Test Reviewer",
                note="Compared with the rendered source",
            )
        )
        value = json.loads(review.read_text(encoding="utf-8"))
        self.assertEqual(value["status"], "approved")
        self.assertEqual(value["measures"][0]["status"], "matched")

    def test_audiveris_adapter_runs_executable_and_labels_output_unverified(self):
        fake = self.root / "fake-audiveris"
        fake.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"-version\" ]; then echo 'Audiveris test'; exit 0; fi\n"
            "while [ $# -gt 0 ]; do\n"
            "  if [ \"$1\" = \"-output\" ]; then shift; out=$1; fi\n"
            "  shift\n"
            "done\n"
            "touch \"$out/generated.mxl\"\n",
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        source = self.root / "source.png"
        source.write_bytes(b"image")
        output = self.root / "omr"
        self.assertEqual(
            score_intake.omr(
                Namespace(
                    input=str(source),
                    output=str(output),
                    audiveris=str(fake),
                    force=False,
                    sheets=None,
                )
            ),
            0,
        )
        report = json.loads((output / "omr-run.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "unverified-omr-draft")
        self.assertEqual(report["sourceComparison"], "required")
        self.assertTrue(report["outputs"][0].endswith("generated.mxl"))
        self.assertFalse(report["structuralValidation"][0]["valid"])


if __name__ == "__main__":
    unittest.main()
