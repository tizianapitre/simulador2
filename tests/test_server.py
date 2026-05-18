import math
import unittest

import server


class SafeExpressionTests(unittest.TestCase):
    def test_spanish_aliases_and_constants(self) -> None:
        expression = server.SafeExpression("sen(pi / 2) + cos(0) + nroot(27, 3) + ln(e) + raiz(9)")
        self.assertAlmostEqual(expression(0, 0), 9.0)

    def test_negative_odd_root(self) -> None:
        expression = server.SafeExpression("nroot(-8, 3)")
        self.assertAlmostEqual(expression(0, 0), -2.0)

    def test_even_root_of_negative_number_is_rejected_at_evaluation(self) -> None:
        expression = server.SafeExpression("nroot(-8, 2)")
        with self.assertRaises(ValueError):
            expression(0, 0)


class FrameEndpointLogicTests(unittest.TestCase):
    def test_frame_keeps_current_state_without_rebuilding_bifurcation(self) -> None:
        result = server.frame(
            {
                "model": "manual",
                "expression": "sen(x) + r",
                "parameter": 0.0,
                "xRange": [-math.pi, math.pi],
                "rRange": [-1.0, 1.0],
            }
        )
        self.assertEqual(result["model"]["key"], "manual")
        self.assertIn("phase", result)
        self.assertNotIn("bifurcation", result)
        self.assertTrue(any(abs(item["x"]) < 1e-6 for item in result["equilibria"]))


if __name__ == "__main__":
    unittest.main()
