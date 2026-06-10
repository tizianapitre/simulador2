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


class Linear2DAnalysisTests(unittest.TestCase):
    def test_saddle_classification_for_opposite_real_eigenvalues(self) -> None:
        result = server.linear2d_analysis({"a": 1, "b": 0, "c": 0, "d": -2})
        self.assertEqual(result["classification"]["type"], "punto silla")
        self.assertEqual([item["real"] for item in result["eigenvalues"]], [1.0, -2.0])
        self.assertEqual(result["solution"]["case"], "autovalores reales distintos")

    def test_center_classification_for_pure_rotation(self) -> None:
        result = server.linear2d_analysis({"a": 0, "b": -1, "c": 1, "d": 0})
        self.assertEqual(result["classification"]["type"], "centro")
        self.assertEqual(result["solution"]["case"], "autovalores complejos conjugados")
        self.assertAlmostEqual(result["eigenvalues"][0]["imag"], 1.0)

    def test_repeated_defective_solution_case(self) -> None:
        result = server.linear2d_analysis({"a": 1, "b": 1, "c": 0, "d": 1})
        self.assertEqual(result["classification"]["type"], "nodo inestable")
        self.assertEqual(result["solution"]["case"], "autovalores reales repetidos no diagonalizables")
        self.assertIn("t v + w", result["solution"]["text"])

    def test_rejects_non_numeric_coefficients(self) -> None:
        with self.assertRaises(ValueError):
            server.linear2d_analysis({"a": "x", "b": 0, "c": 0, "d": 1})


class Nonhomogeneous2DAnalysisTests(unittest.TestCase):
    def test_constant_forcing_shifts_equilibrium(self) -> None:
        result = server.nonhomogeneous2d_analysis(
            {
                "a": -1,
                "b": 0,
                "c": 0,
                "d": -2,
                "forcingType": "constant",
                "fxExpression": "1",
                "fyExpression": "2",
                "time": 0,
                "tRange": [0, 4],
                "xRange": [-3, 3],
                "yRange": [-3, 3],
            }
        )
        self.assertEqual(result["particular"]["kind"], "constant")
        self.assertAlmostEqual(result["particular"]["point"]["x"], 1.0)
        self.assertAlmostEqual(result["particular"]["point"]["y"], 1.0)
        self.assertEqual(result["homogeneous"]["classification"]["type"], "nodo estable")

    def test_exponential_forcing_builds_particular_point(self) -> None:
        result = server.nonhomogeneous2d_analysis(
            {
                "a": -1,
                "b": 0,
                "c": 0,
                "d": -2,
                "forcingType": "exponential",
                "fxExpression": "exp(t)",
                "fyExpression": "0",
                "lambda": 1,
                "time": 0,
                "tRange": [0, 2],
                "xRange": [-3, 3],
                "yRange": [-3, 3],
            }
        )
        self.assertEqual(result["particular"]["kind"], "exponential")
        self.assertAlmostEqual(result["particular"]["point"]["x"], 0.5)
        self.assertAlmostEqual(result["particular"]["point"]["y"], 0.0)


class Nonlinear2DAnalysisTests(unittest.TestCase):
    def test_finds_predator_prey_equilibrium_and_nullclines(self) -> None:
        result = server.nonlinear2d_analysis(
            {
                "xExpression": "x*(1-y)",
                "yExpression": "y*(x-1)",
                "xRange": [-1, 4],
                "yRange": [-1, 4],
            }
        )
        self.assertTrue(any(abs(item["x"] - 1) < 1e-5 and abs(item["y"] - 1) < 1e-5 for item in result["equilibria"]))
        self.assertEqual(len(result["nullclines"]), 2)
        self.assertTrue(result["nullclines"][0]["segments"])
        self.assertTrue(result["vectorField"])

    def test_rejects_unknown_variables(self) -> None:
        with self.assertRaises(server.ExpressionError):
            server.nonlinear2d_analysis({"xExpression": "z + x", "yExpression": "y", "xRange": [-1, 1], "yRange": [-1, 1]})


if __name__ == "__main__":
    unittest.main()
