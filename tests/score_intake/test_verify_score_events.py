import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agent/skills/piano-score-intake/scripts/verify_score_events.py"
SPEC = importlib.util.spec_from_file_location("verify_score_events", SCRIPT)
events = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(events)


EXPECTED = {
    "title": "Test",
    "composer": "",
    "timeSignature": "4/4",
    "referenceReview": {"status": "approved", "reviewer": "Test Reviewer"},
    "measures": [
        {
            "number": 1,
            "staves": {
                "1": [
                    {"pitches": ["C4"], "duration": "quarter"},
                    {"pitches": ["E4", "G4"], "duration": "half"},
                    {"rest": True, "duration": "quarter"},
                ],
                "2": [{"rest": True, "duration": "whole"}],
            },
        }
    ],
}


class VerifyScoreEventsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_built_score_matches_expected_events_exactly(self):
        score = self.root / "score.musicxml"
        events.build_score(EXPECTED).write(score, encoding="utf-8", xml_declaration=True)
        actual = events.normalize_score(score)
        wanted = events.expected_normalized(EXPECTED)
        self.assertEqual(events.compare(actual, wanted), [])

    def test_pitch_change_is_reported_with_measure_and_staff(self):
        score = self.root / "score.musicxml"
        tree = events.build_score(EXPECTED)
        first_step = next(element for element in tree.getroot().iter() if events.local_name(element.tag) == "step")
        first_step.text = "D"
        tree.write(score, encoding="utf-8", xml_declaration=True)
        differences = events.compare(events.normalize_score(score), events.expected_normalized(EXPECTED))
        self.assertEqual(len(differences), 1)
        self.assertIn("measure 1 staff 1", differences[0])
        self.assertIn("D4", differences[0])


if __name__ == "__main__":
    unittest.main()
