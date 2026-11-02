"""Checks for Smokeview plane discovery used by the capture window."""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Utilities" / "Scripts"))

from smv_planes import available_planes, parse_plane_selection


class PlaneSelectionTests(unittest.TestCase):
    def test_cell_and_node_centered_slice_positions(self) -> None:
        case = ROOT / "vistest" / "facecenter" / "facetest.smv"
        self.assertEqual(available_planes(case), ["Y=0.400", "Y=0.450", "Y=0.700"])

    def test_multiple_positions_and_invalid_input(self) -> None:
        self.assertEqual(parse_plane_selection("Y=3, y=5, Y=3"), "y=3.000,y=5.000")
        for value in ("Y=", "A=3", "Y=nan", "Y=3;X=2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_plane_selection(value)


if __name__ == "__main__":
    unittest.main()
