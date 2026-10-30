"""Finite fixtures for decision rules and the source-qualification boundary."""

import sys, unittest
from fractions import Fraction as F
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from decisions import choose, pack
from prepare_inputs import canonical, boolean, same, number, GROUPS


class Decisions(unittest.TestCase):
    def result(self, g):
        return choose({a: list(map(F, x)) for a, x in g.items()})

    def test_no_action(self):
        self.assertEqual(
            self.result({0: [0, 0]})[4], dict(nominal=0, maximin=0, minimax_regret=0)
        )

    def test_all_negative(self):
        self.assertEqual(set(self.result({0: [0, 0], 39: [-1, -2]})[4].values()), {0})

    def test_nominal_reversal(self):
        self.assertEqual(
            self.result({0: [0, 0], 39: [8, 1], 40: [6, 5]})[4]["nominal"], 39
        )

    def test_maximin(self):
        self.assertEqual(
            self.result({0: [0, 0], 39: [8, 1], 40: [6, 5]})[4]["maximin"], 40
        )

    def test_minimax(self):
        self.assertEqual(
            self.result({0: [0, 0], 39: [8, 1], 40: [6, 5]})[4]["minimax_regret"], 40
        )

    def test_zero_tie_first(self):
        self.assertEqual(set(self.result({0: [0, 0], 39: [0, 0]})[4].values()), {0})

    def test_lower_id_tie(self):
        self.assertEqual(
            set(self.result({0: [0, 0], 48: [5, 5], 39: [5, 5]})[4].values()), {39}
        )

    def test_full_top_sets(self):
        self.assertEqual(
            self.result({0: [0, 0], 39: [5, 2], 40: [5, 3]})[1], [[39, 40], [40]]
        )

    def test_exact_fraction(self):
        self.assertEqual(
            self.result({0: [0, 0], 39: [F(1, 3), F(1, 3)]})[2][39], F(1, 3)
        )

    def test_distinct_tiny_values(self):
        self.assertEqual(
            self.result(
                {0: [0, 0], 39: [F(1, 3), 1], 40: [F(1, 3) + F(1, 10**20), 1]}
            )[4]["nominal"],
            40,
        )

    def test_minimax_differs_maximin(self):
        self.assertNotEqual(
            self.result({0: [0, 0], 39: [100, 1], 40: [40, 40]})[4]["maximin"],
            self.result({0: [0, 0], 39: [100, 1], 40: [40, 40]})[4]["minimax_regret"],
        )

    def test_regret_exact(self):
        self.assertEqual(self.result({0: [0, 0], 39: [8, 1], 40: [6, 5]})[3][40], 2)

    def test_mathematical_bounds(self):
        for x in range(-3, 4):
            for y in range(-3, 4):
                _, _, worst, regret, selected, _ = self.result(
                    {0: [0, 0], 39: [x, y], 40: [y, x + 1]}
                )
                self.assertGreaterEqual(
                    worst[selected["maximin"]], worst[selected["nominal"]]
                )
                self.assertLessEqual(
                    regret[selected["minimax_regret"]], regret[selected["nominal"]]
                )

    def test_large_exact_serialization(self):
        row = {}
        pack(row, "value", F(1, 10**5000 + 1))
        self.assertTrue(row["value_exact"].startswith("1/"))
        self.assertEqual(row["value"], "0.000000000")

    def test_action_order_invariant(self):
        self.assertEqual(
            self.result({0: [0, 0], 39: [4, 2], 40: [2, 4]}),
            self.result({40: [2, 4], 39: [4, 2], 0: [0, 0]}),
        )


class SourceBoundary(unittest.TestCase):
    def row(self, v="1", kind="float"):
        return {
            "source_file": "a",
            "source_row": "1",
            "in.sqft": v,
            "in.sqft__type": kind,
        }

    def test_same_copy(self):
        self.assertIsNotNone(canonical([self.row(), self.row()], ["in.sqft"]))

    def test_conflicting_copy(self):
        self.assertIsNone(canonical([self.row(), self.row("2")], ["in.sqft"]))

    def test_source_order(self):
        a = self.row()
        b = self.row()
        b["source_row"] = "2"
        self.assertEqual(canonical([b, a], ["in.sqft"]), a)

    def test_reader_allowance(self):
        self.assertTrue(same(self.row(), self.row("1.0000000001"), ["in.sqft"]))

    def test_no_tolerance_relaxation(self):
        self.assertFalse(same(self.row(), self.row("1.000001"), ["in.sqft"]))

    def test_null_not_zero(self):
        self.assertIsNone(number(self.row("", "null"), "in.sqft"))

    def test_numeric_duration_text(self):
        self.assertEqual(number(self.row("12.5", "text"), "in.sqft"), F(25, 2))

    def test_invalid_number(self):
        self.assertIsNone(number(self.row("unknown", "text"), "in.sqft"))

    def test_infinite_not_numeric(self):
        self.assertIsNone(number(self.row("inf"), "in.sqft"))

    def test_unknown_applicability(self):
        self.assertIsNone(boolean({"applicability": "", "applicability__type": "null"}))

    def test_false_applicability(self):
        self.assertIs(
            boolean({"applicability": "false", "applicability__type": "bool"}), False
        )

    def test_text_not_boolean(self):
        self.assertIsNone(
            boolean({"applicability": "true", "applicability__type": "text"})
        )

    def test_roles_disjoint(self):
        self.assertFalse(
            set(k for k, v in GROUPS.items() if v in ["Office", "Retail"])
            & set(k for k, v in GROUPS.items() if v in ["Hotel", "Warehouse"])
        )

    def test_type_mismatch(self):
        self.assertFalse(same(self.row(), self.row("1", "text"), ["in.sqft"]))


if __name__ == "__main__":
    unittest.main()
