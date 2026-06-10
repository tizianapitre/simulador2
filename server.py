from __future__ import annotations

import ast
import json
import math
import mimetypes
import os
from dataclasses import dataclass
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable


ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "static"


def nroot(value: float, degree: float) -> float:
    if degree == 0:
        raise ValueError("nroot requiere un indice distinto de cero.")
    if value < 0:
        nearest_integer = round(degree)
        if not math.isclose(degree, nearest_integer) or nearest_integer % 2 == 0:
            raise ValueError("nroot de un numero negativo requiere indice impar entero.")
        return -((-value) ** (1.0 / degree))
    return value ** (1.0 / degree)


SAFE_FUNCTIONS: dict[str, Callable[..., float]] = {
    "abs": abs,
    "acos": math.acos,
    "asin": math.asin,
    "atan": math.atan,
    "ceil": math.ceil,
    "cos": math.cos,
    "cosh": math.cosh,
    "exp": math.exp,
    "floor": math.floor,
    "log": math.log,
    "log10": math.log10,
    "ln": math.log,
    "max": max,
    "min": min,
    "nroot": nroot,
    "pow": pow,
    "raiz": math.sqrt,
    "sen": math.sin,
    "sin": math.sin,
    "sinh": math.sinh,
    "sqrt": math.sqrt,
    "tan": math.tan,
    "tg": math.tan,
    "tanh": math.tanh,
}

SAFE_CONSTANTS = {"e": math.e, "pi": math.pi}

ALLOWED_AST_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
)


@dataclass(frozen=True)
class Model:
    key: str
    label: str
    expression: str
    default_parameter: float
    x_range: tuple[float, float]
    r_range: tuple[float, float]
    description: str


MODELS: dict[str, Model] = {
    "saddle-node": Model(
        key="saddle-node",
        label="Silla-Nodo",
        expression="r + x**2",
        default_parameter=-1.0,
        x_range=(-3.0, 3.0),
        r_range=(-4.0, 2.0),
        description="x' = r + x^2",
    ),
    "pitchfork": Model(
        key="pitchfork",
        label="Tridente",
        expression="r*x - x**3",
        default_parameter=-1.0,
        x_range=(-3.0, 3.0),
        r_range=(-3.0, 3.0),
        description="x' = r x - x^3",
    ),
    "transcritical": Model(
        key="transcritical",
        label="Transcrítica",
        expression="r*x - x**2",
        default_parameter=-1.0,
        x_range=(-3.0, 3.0),
        r_range=(-3.0, 3.0),
        description="x' = r x - x^2",
    ),
}

MANUAL_MODEL = Model(
    key="manual",
    label="Manual",
    expression="r*x - x**2",
    default_parameter=-1.0,
    x_range=(-3.0, 3.0),
    r_range=(-3.0, 3.0),
    description="x' = f(x, r)",
)


class ExpressionError(ValueError):
    pass


class SafeExpression:
    def __init__(self, expression: str, variables: tuple[str, ...] = ("x", "r")):
        self.original = expression.strip()
        self.expression = self.original.replace("^", "**")
        self.variables = set(variables)
        if not self.expression:
            raise ExpressionError("La expresión no puede estar vacía.")

        try:
            tree = ast.parse(self.expression, mode="eval")
        except SyntaxError as exc:
            raise ExpressionError(f"Expresión inválida: {exc.msg}.") from exc

        self._validate(tree)
        self._code = compile(tree, "<manual-expression>", "eval")

    def _validate(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if not isinstance(node, ALLOWED_AST_NODES):
                raise ExpressionError(f"No se admite {node.__class__.__name__} en la expresión.")
            if isinstance(node, ast.Name):
                if node.id not in {*self.variables, *SAFE_FUNCTIONS.keys(), *SAFE_CONSTANTS.keys()}:
                    allowed = ", ".join(sorted(self.variables))
                    raise ExpressionError(f"Nombre no permitido: {node.id}. Usá solo {allowed} y funciones matemáticas.")
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in SAFE_FUNCTIONS:
                    raise ExpressionError("Solo se admiten llamadas a funciones matemáticas permitidas.")

    def __call__(self, x: float, r: float) -> float:
        return self.evaluate(x=x, r=r)

    def evaluate(self, **variables: float) -> float:
        missing = self.variables - variables.keys()
        if missing:
            raise ValueError(f"Faltan variables: {', '.join(sorted(missing))}.")
        env = {**SAFE_FUNCTIONS, **SAFE_CONSTANTS}
        env.update({key: float(variables[key]) for key in self.variables})
        try:
            value = eval(self._code, {"__builtins__": {}}, env)
        except (ArithmeticError, ValueError, OverflowError) as exc:
            raise ValueError(str(exc)) from exc
        return float(value)


def finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def clean_number(value: float, digits: int = 8) -> float:
    rounded = round(value, digits)
    return 0.0 if abs(rounded) < 10 ** (-digits) else rounded


def clean_complex(value: complex, digits: int = 8) -> complex:
    return complex(clean_number(value.real, digits), clean_number(value.imag, digits))


def scalar_payload(value: complex) -> dict[str, float]:
    value = clean_complex(value)
    return {"real": value.real, "imag": value.imag}


def real_vector_payload(values: list[complex], label: str) -> dict[str, Any]:
    return {
        "label": label,
        "vector": [clean_number(values[0].real), clean_number(values[1].real)],
        "vectorText": format_vector([complex(values[0].real, 0), complex(values[1].real, 0)]),
    }


def format_scalar(value: complex) -> str:
    value = clean_complex(value, 6)
    if abs(value.imag) < 1e-9:
        return f"{value.real:g}"
    sign = "+" if value.imag >= 0 else "-"
    return f"{value.real:g} {sign} {abs(value.imag):g}i"


def format_vector(values: list[complex]) -> str:
    return "(" + ", ".join(format_scalar(value) for value in values) + ")"


def normalize_complex_vector(values: list[complex]) -> list[complex]:
    scale = max((abs(value) for value in values), default=0.0)
    if scale < 1e-12:
        return [0j for _ in values]
    normalized = [value / scale for value in values]
    pivot = next((value for value in normalized if abs(value) > 1e-12), 1 + 0j)
    if abs(pivot.imag) < 1e-12 and pivot.real < 0:
        normalized = [-value for value in normalized]
    return [clean_complex(value) for value in normalized]


def eigenvector_for(a: float, b: float, c: float, d: float, eigenvalue: complex) -> list[complex]:
    # A vector perpendicular to a non-zero row of A - lambda I spans the nullspace.
    rows = [
        (complex(a, 0) - eigenvalue, complex(b, 0)),
        (complex(c, 0), complex(d, 0) - eigenvalue),
    ]
    row = max(rows, key=lambda item: abs(item[0]) + abs(item[1]))
    if abs(row[0]) + abs(row[1]) < 1e-12:
        return [1 + 0j, 0j]
    return normalize_complex_vector([-row[1], row[0]])


def eigenspace_dimension(a: float, b: float, c: float, d: float, eigenvalue: float) -> int:
    rows = [
        (a - eigenvalue, b),
        (c, d - eigenvalue),
    ]
    if all(abs(p) < 1e-9 and abs(q) < 1e-9 for p, q in rows):
        return 2
    return 1


def generalized_eigenvector(
    a: float,
    b: float,
    c: float,
    d: float,
    eigenvalue: float,
    vector: list[complex],
) -> list[complex]:
    # For a defective repeated eigenvalue, solve (A-lambda I)w = v.
    matrix = [[a - eigenvalue, b], [c, d - eigenvalue]]
    target = [vector[0].real, vector[1].real]
    candidates: list[list[complex]] = []
    for row, rhs in zip(matrix, target):
        p, q = row
        if abs(p) > 1e-10:
            candidates.append([complex(rhs / p, 0), 0j])
        if abs(q) > 1e-10:
            candidates.append([0j, complex(rhs / q, 0)])

    def residual(candidate: list[complex]) -> float:
        x_value, y_value = candidate[0].real, candidate[1].real
        return math.hypot(
            matrix[0][0] * x_value + matrix[0][1] * y_value - target[0],
            matrix[1][0] * x_value + matrix[1][1] * y_value - target[1],
        )

    best = min(candidates, key=residual) if candidates else [0j, 0j]
    return [clean_complex(value) for value in best]


def classify_linear_equilibrium(
    trace: float,
    determinant: float,
    discriminant: float,
    a: float,
    b: float,
    c: float,
    d: float,
) -> dict[str, str]:
    eps = 1e-9
    if abs(a) < eps and abs(b) < eps and abs(c) < eps and abs(d) < eps:
        return {
            "type": "caso degenerado",
            "stability": "degenerate",
            "detail": "La matriz nula hace que todos los puntos del plano sean equilibrios.",
        }
    if abs(determinant) < eps:
        non_zero = trace
        tendency = "estable transversalmente" if non_zero < -eps else "inestable transversalmente" if non_zero > eps else "degenerado"
        return {
            "type": "caso degenerado",
            "stability": "degenerate",
            "detail": f"det(A)=0: hay una recta de equilibrios y el origen no es aislado ({tendency}).",
        }
    if determinant < 0:
        return {"type": "punto silla", "stability": "unstable", "detail": "Autovalores reales con signos opuestos."}
    if discriminant < -eps:
        if abs(trace) < eps:
            return {"type": "centro", "stability": "neutral", "detail": "Autovalores imaginarios puros."}
        if trace < 0:
            return {
                "type": "espiral/foco estable",
                "stability": "stable",
                "detail": "Autovalores complejos conjugados con parte real negativa.",
            }
        return {
            "type": "espiral/foco inestable",
            "stability": "unstable",
            "detail": "Autovalores complejos conjugados con parte real positiva.",
        }
    if discriminant > eps:
        lambda_1 = (trace + math.sqrt(discriminant)) / 2.0
        lambda_2 = (trace - math.sqrt(discriminant)) / 2.0
        if lambda_1 < -eps and lambda_2 < -eps:
            return {"type": "nodo estable", "stability": "stable", "detail": "Autovalores reales distintos y negativos."}
        if lambda_1 > eps and lambda_2 > eps:
            return {"type": "nodo inestable", "stability": "unstable", "detail": "Autovalores reales distintos y positivos."}
        return {"type": "caso degenerado", "stability": "degenerate", "detail": "Al menos un autovalor es cero."}

    eigenvalue = trace / 2.0
    dimension = eigenspace_dimension(a, b, c, d, eigenvalue)
    shape = "nodo propio" if dimension == 2 else "nodo degenerado/impropio"
    if eigenvalue < -eps:
        return {"type": "nodo estable", "stability": "stable", "detail": f"Autovalor real repetido negativo; {shape}."}
    if eigenvalue > eps:
        return {"type": "nodo inestable", "stability": "unstable", "detail": f"Autovalor real repetido positivo; {shape}."}
    return {"type": "caso degenerado", "stability": "degenerate", "detail": "Autovalor real repetido igual a cero."}


def rk4_linear_step(a: float, b: float, c: float, d: float, x: float, y: float, h: float) -> tuple[float, float]:
    def field(px: float, py: float) -> tuple[float, float]:
        return a * px + b * py, c * px + d * py

    k1x, k1y = field(x, y)
    k2x, k2y = field(x + 0.5 * h * k1x, y + 0.5 * h * k1y)
    k3x, k3y = field(x + 0.5 * h * k2x, y + 0.5 * h * k2y)
    k4x, k4y = field(x + h * k3x, y + h * k3y)
    return (
        x + h * (k1x + 2 * k2x + 2 * k3x + k4x) / 6.0,
        y + h * (k1y + 2 * k2y + 2 * k3y + k4y) / 6.0,
    )


def representative_trajectories(a: float, b: float, c: float, d: float, limit: float = 5.0) -> list[list[dict[str, float]]]:
    seeds = [
        (-3.0, -1.5),
        (-3.0, 1.5),
        (-1.5, 3.0),
        (1.5, 3.0),
        (3.0, 1.5),
        (3.0, -1.5),
        (1.5, -3.0),
        (-1.5, -3.0),
        (-1.0, 0.0),
        (0.0, 1.0),
        (1.0, 0.0),
        (0.0, -1.0),
    ]
    trajectories: list[list[dict[str, float]]] = []
    h = 0.035
    steps = 240

    def in_bounds(x_value: float, y_value: float) -> bool:
        return -limit <= x_value <= limit and -limit <= y_value <= limit

    def trace(seed_x: float, seed_y: float, step: float) -> list[tuple[float, float]]:
        points = [(seed_x, seed_y)]
        x_value, y_value = seed_x, seed_y
        for _ in range(steps):
            next_x, next_y = rk4_linear_step(a, b, c, d, x_value, y_value, step)
            if not in_bounds(next_x, next_y):
                break
            points.append((next_x, next_y))
            x_value, y_value = next_x, next_y
        return points

    for seed_x, seed_y in seeds:
        backward = trace(float(seed_x), float(seed_y), -h)
        forward = trace(float(seed_x), float(seed_y), h)
        points = list(reversed(backward))[::3] + forward[1::3]
        if len(points) >= 2:
            trajectories.append([{"x": clean_number(x), "y": clean_number(y)} for x, y in points])
    return trajectories


def line_description(p: float, q: float) -> str:
    if abs(p) < 1e-9 and abs(q) < 1e-9:
        return "todo el plano"
    if abs(q) < 1e-9:
        return "x = 0"
    if abs(p) < 1e-9:
        return "y = 0"
    return f"y = {clean_number(-p / q, 6):g} x"


def parse_linear2d_payload(payload: dict[str, Any]) -> tuple[float, float, float, float]:
    values = []
    for key in ("a", "b", "c", "d"):
        try:
            value = float(payload.get(key))
        except (TypeError, ValueError) as exc:
            raise ValueError("Todos los coeficientes a, b, c y d deben ser numericos.") from exc
        if not math.isfinite(value):
            raise ValueError("Todos los coeficientes a, b, c y d deben ser finitos.")
        values.append(value)
    return values[0], values[1], values[2], values[3]


def linear2d_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    a, b, c, d = parse_linear2d_payload(payload)
    trace = a + d
    determinant = a * d - b * c
    discriminant = trace * trace - 4.0 * determinant
    eps = 1e-9

    eigenvalues: list[complex]
    if discriminant >= -eps:
        root = math.sqrt(max(0.0, discriminant))
        eigenvalues = [complex((trace + root) / 2.0, 0), complex((trace - root) / 2.0, 0)]
    else:
        real = trace / 2.0
        imag = math.sqrt(-discriminant) / 2.0
        eigenvalues = [complex(real, imag), complex(real, -imag)]

    repeated_real = abs(discriminant) <= eps
    unique_eigenvalues = [eigenvalues[0]] if repeated_real else eigenvalues
    eigenvectors = []
    for eigenvalue in unique_eigenvalues:
        vector = eigenvector_for(a, b, c, d, eigenvalue)
        eigenvectors.append(
            {
                "eigenvalue": scalar_payload(eigenvalue),
                "eigenvalueText": format_scalar(eigenvalue),
                "vector": [scalar_payload(value) for value in vector],
                "vectorText": format_vector(vector),
                "multiplicity": 2 if repeated_real else 1,
            }
        )

    classification = classify_linear_equilibrium(trace, determinant, discriminant, a, b, c, d)
    vector_lines: list[dict[str, Any]] = []

    if discriminant > eps:
        solution_case = "autovalores reales distintos"
        solution_text = (
            "X(t) = C1 exp(lambda1 t) v1 + C2 exp(lambda2 t) v2, "
            f"con lambda1={format_scalar(eigenvalues[0])}, v1={eigenvectors[0]['vectorText']} y "
            f"lambda2={format_scalar(eigenvalues[1])}, v2={eigenvectors[1]['vectorText']}."
        )
        vector_lines = [
            real_vector_payload(eigenvector_for(a, b, c, d, eigenvalues[0]), "v1"),
            real_vector_payload(eigenvector_for(a, b, c, d, eigenvalues[1]), "v2"),
        ]
        solution_formula = {
            "kind": "realDistinct",
            "lambda1": format_scalar(eigenvalues[0]),
            "lambda2": format_scalar(eigenvalues[1]),
            "v1": vector_lines[0]["vector"],
            "v2": vector_lines[1]["vector"],
        }
    elif repeated_real:
        eigenvalue = eigenvalues[0].real
        vector = eigenvector_for(a, b, c, d, complex(eigenvalue, 0))
        if eigenspace_dimension(a, b, c, d, eigenvalue) == 2:
            solution_case = "autovalores reales repetidos diagonalizables"
            solution_text = (
                f"X(t) = exp({format_scalar(complex(eigenvalue, 0))} t) "
                "(C1 (1, 0) + C2 (0, 1))."
            )
            vector_lines = [
                {"label": "v1", "vector": [1.0, 0.0], "vectorText": "(1, 0)"},
                {"label": "v2", "vector": [0.0, 1.0], "vectorText": "(0, 1)"},
            ]
            solution_formula = {
                "kind": "realRepeatedDiagonalizable",
                "lambda": format_scalar(complex(eigenvalue, 0)),
                "v1": vector_lines[0]["vector"],
                "v2": vector_lines[1]["vector"],
            }
        else:
            generalized = generalized_eigenvector(a, b, c, d, eigenvalue, vector)
            solution_case = "autovalores reales repetidos no diagonalizables"
            solution_text = (
                "X(t) = exp(lambda t) [C1 v + C2 (t v + w)], "
                f"con lambda={format_scalar(complex(eigenvalue, 0))}, v={format_vector(vector)} "
                f"y w={format_vector(generalized)}."
            )
            vector_lines = [
                real_vector_payload(vector, "v1"),
                real_vector_payload(generalized, "v2"),
            ]
            solution_formula = {
                "kind": "realRepeatedDefective",
                "lambda": format_scalar(complex(eigenvalue, 0)),
                "v1": vector_lines[0]["vector"],
                "v2": vector_lines[1]["vector"],
            }
    else:
        alpha = eigenvalues[0].real
        beta = abs(eigenvalues[0].imag)
        vector = eigenvector_for(a, b, c, d, eigenvalues[0])
        p_vector = [complex(value.real, 0) for value in vector]
        q_vector = [complex(value.imag, 0) for value in vector]
        solution_case = "autovalores complejos conjugados"
        solution_text = (
            "Si v=p+iq es un autovector de alpha+beta i, entonces "
            "X(t)=exp(alpha t){C1[p cos(beta t)-q sin(beta t)] + "
            "C2[p sin(beta t)+q cos(beta t)]}. "
            f"Aqui alpha={format_scalar(complex(alpha, 0))}, beta={clean_number(beta, 6):g}, "
            f"p={format_vector(p_vector)} y q={format_vector(q_vector)}."
        )
        vector_lines = [
            real_vector_payload(p_vector, "p"),
            real_vector_payload(q_vector, "q"),
        ]
        solution_formula = {
            "kind": "complexConjugate",
            "alpha": format_scalar(complex(alpha, 0)),
            "beta": f"{clean_number(beta, 6):g}",
            "p": vector_lines[0]["vector"],
            "q": vector_lines[1]["vector"],
        }

    return {
        "matrix": [[clean_number(a), clean_number(b)], [clean_number(c), clean_number(d)]],
        "trace": clean_number(trace),
        "determinant": clean_number(determinant),
        "discriminant": clean_number(discriminant),
        "eigenvalues": [scalar_payload(value) for value in eigenvalues],
        "eigenvectors": eigenvectors,
        "classification": classification,
        "solution": {"case": solution_case, "text": solution_text, "formula": solution_formula},
        "nullclines": [
            {
                "id": "dx",
                "label": "dx/dt = 0",
                "equation": f"{clean_number(a):g}x + {clean_number(b):g}y = 0",
                "description": line_description(a, b),
                "coefficients": [clean_number(a), clean_number(b)],
            },
            {
                "id": "dy",
                "label": "dy/dt = 0",
                "equation": f"{clean_number(c):g}x + {clean_number(d):g}y = 0",
                "description": line_description(c, d),
                "coefficients": [clean_number(c), clean_number(d)],
            },
        ],
        "phase": {"range": [-5, 5], "trajectories": representative_trajectories(a, b, c, d), "vectorLines": vector_lines},
    }


def parse_nonlinear2d_payload(payload: dict[str, Any]) -> tuple[str, str, tuple[float, float], tuple[float, float]]:
    x_expression = str(payload.get("xExpression") or "x*(1-y)")
    y_expression = str(payload.get("yExpression") or "y*(x-1)")
    x_range = parse_range(payload, "xRange", (-1.0, 4.0))
    y_range = parse_range(payload, "yRange", (-1.0, 4.0))
    return x_expression, y_expression, x_range, y_range


def safe_eval2d(func: SafeExpression, x: float, y: float) -> float | None:
    try:
        value = func.evaluate(x=x, y=y)
    except Exception:
        return None
    return value if math.isfinite(value) else None


def field2d(
    x_func: SafeExpression,
    y_func: SafeExpression,
    x: float,
    y: float,
) -> tuple[float, float] | None:
    x_value = safe_eval2d(x_func, x, y)
    y_value = safe_eval2d(y_func, x, y)
    if not finite(x_value) or not finite(y_value):
        return None
    return x_value, y_value


def interpolate_zero(
    point_a: tuple[float, float],
    value_a: float,
    point_b: tuple[float, float],
    value_b: float,
) -> tuple[float, float]:
    if abs(value_a - value_b) < 1e-14:
        t = 0.5
    else:
        t = value_a / (value_a - value_b)
    t = min(1.0, max(0.0, t))
    return (point_a[0] + t * (point_b[0] - point_a[0]), point_a[1] + t * (point_b[1] - point_a[1]))


def zero_contours(
    func: SafeExpression,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    samples: int = 88,
) -> list[list[dict[str, float]]]:
    x_min, x_max = x_range
    y_min, y_max = y_range
    xs = [x_min + (x_max - x_min) * i / samples for i in range(samples + 1)]
    ys = [y_min + (y_max - y_min) * i / samples for i in range(samples + 1)]
    values = [[safe_eval2d(func, x, y) for x in xs] for y in ys]
    segments: list[list[dict[str, float]]] = []

    for row in range(samples):
        for col in range(samples):
            corners = [
                ((xs[col], ys[row]), values[row][col]),
                ((xs[col + 1], ys[row]), values[row][col + 1]),
                ((xs[col + 1], ys[row + 1]), values[row + 1][col + 1]),
                ((xs[col], ys[row + 1]), values[row + 1][col]),
            ]
            if any(not finite(value) for _, value in corners):
                continue

            crossings: list[tuple[float, float]] = []
            for first, second in ((0, 1), (1, 2), (2, 3), (3, 0)):
                point_a, value_a = corners[first]
                point_b, value_b = corners[second]
                assert value_a is not None and value_b is not None
                crosses = value_a == 0 or value_b == 0 or value_a * value_b < 0
                if crosses:
                    point = interpolate_zero(point_a, value_a, point_b, value_b)
                    if not any(math.hypot(point[0] - other[0], point[1] - other[1]) < 1e-8 for other in crossings):
                        crossings.append(point)

            if len(crossings) >= 2:
                for index in range(0, len(crossings) - 1, 2):
                    start, end = crossings[index], crossings[index + 1]
                    if math.hypot(start[0] - end[0], start[1] - end[1]) < 1e-10:
                        continue
                    segments.append(
                        [
                            {"x": clean_number(start[0]), "y": clean_number(start[1])},
                            {"x": clean_number(end[0]), "y": clean_number(end[1])},
                        ]
                    )
    return segments


def jacobian2d(
    x_func: SafeExpression,
    y_func: SafeExpression,
    x: float,
    y: float,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
) -> tuple[float, float, float, float] | None:
    hx = max(1e-5, (x_range[1] - x_range[0]) * 1e-6, abs(x) * 1e-6)
    hy = max(1e-5, (y_range[1] - y_range[0]) * 1e-6, abs(y) * 1e-6)
    fx_plus = safe_eval2d(x_func, x + hx, y)
    fx_minus = safe_eval2d(x_func, x - hx, y)
    fx_y_plus = safe_eval2d(x_func, x, y + hy)
    fx_y_minus = safe_eval2d(x_func, x, y - hy)
    fy_x_plus = safe_eval2d(y_func, x + hx, y)
    fy_x_minus = safe_eval2d(y_func, x - hx, y)
    fy_plus = safe_eval2d(y_func, x, y + hy)
    fy_minus = safe_eval2d(y_func, x, y - hy)
    values = [fx_plus, fx_minus, fx_y_plus, fx_y_minus, fy_x_plus, fy_x_minus, fy_plus, fy_minus]
    if any(not finite(value) for value in values):
        return None
    assert all(value is not None for value in values)
    return (
        (fx_plus - fx_minus) / (2.0 * hx),
        (fx_y_plus - fx_y_minus) / (2.0 * hy),
        (fy_x_plus - fy_x_minus) / (2.0 * hx),
        (fy_plus - fy_minus) / (2.0 * hy),
    )


def newton_equilibrium(
    x_func: SafeExpression,
    y_func: SafeExpression,
    seed_x: float,
    seed_y: float,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
) -> tuple[float, float] | None:
    x_value, y_value = seed_x, seed_y
    for _ in range(36):
        field = field2d(x_func, y_func, x_value, y_value)
        if field is None:
            return None
        fx, fy = field
        if math.hypot(fx, fy) < 1e-10:
            break
        jacobian = jacobian2d(x_func, y_func, x_value, y_value, x_range, y_range)
        if jacobian is None:
            return None
        a, b, c, d = jacobian
        determinant = a * d - b * c
        if abs(determinant) < 1e-12:
            return None
        dx = (-fx * d + b * fy) / determinant
        dy = (c * fx - a * fy) / determinant
        step_scale = 1.0
        while step_scale >= 1 / 16:
            next_x = x_value + step_scale * dx
            next_y = y_value + step_scale * dy
            if (
                x_range[0] - 0.2 * (x_range[1] - x_range[0]) <= next_x <= x_range[1] + 0.2 * (x_range[1] - x_range[0])
                and y_range[0] - 0.2 * (y_range[1] - y_range[0]) <= next_y <= y_range[1] + 0.2 * (y_range[1] - y_range[0])
            ):
                x_value, y_value = next_x, next_y
                break
            step_scale *= 0.5
        else:
            return None

    if not (x_range[0] <= x_value <= x_range[1] and y_range[0] <= y_value <= y_range[1]):
        return None
    field = field2d(x_func, y_func, x_value, y_value)
    if field is None or math.hypot(field[0], field[1]) > 1e-6:
        return None
    return x_value, y_value


def classify_nonlinear_equilibrium(
    jacobian: tuple[float, float, float, float] | None,
) -> dict[str, Any]:
    if jacobian is None:
        return {
            "type": "indeterminado",
            "stability": "unknown",
            "detail": "No se pudo calcular el Jacobiano numérico.",
            "trace": None,
            "determinant": None,
            "discriminant": None,
            "eigenvalues": [],
        }
    a, b, c, d = jacobian
    trace = a + d
    determinant = a * d - b * c
    discriminant = trace * trace - 4.0 * determinant
    classification = classify_linear_equilibrium(trace, determinant, discriminant, a, b, c, d)
    if discriminant >= 0:
        root = math.sqrt(max(0.0, discriminant))
        eigenvalues = [complex((trace + root) / 2.0, 0), complex((trace - root) / 2.0, 0)]
    else:
        eigenvalues = [complex(trace / 2.0, math.sqrt(-discriminant) / 2.0), complex(trace / 2.0, -math.sqrt(-discriminant) / 2.0)]
    return {
        **classification,
        "trace": clean_number(trace),
        "determinant": clean_number(determinant),
        "discriminant": clean_number(discriminant),
        "eigenvalues": [scalar_payload(value) for value in eigenvalues],
    }


def find_nonlinear_equilibria(
    x_func: SafeExpression,
    y_func: SafeExpression,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
) -> list[dict[str, Any]]:
    seeds: list[tuple[float, float]] = []
    grid = 22
    for i in range(grid + 1):
        x = x_range[0] + (x_range[1] - x_range[0]) * i / grid
        for j in range(grid + 1):
            y = y_range[0] + (y_range[1] - y_range[0]) * j / grid
            seeds.append((x, y))
    if x_range[0] <= 0 <= x_range[1] and y_range[0] <= 0 <= y_range[1]:
        seeds.append((0.0, 0.0))

    roots: list[tuple[float, float]] = []
    merge_tolerance = max(x_range[1] - x_range[0], y_range[1] - y_range[0]) * 8e-4
    for seed_x, seed_y in seeds:
        root = newton_equilibrium(x_func, y_func, seed_x, seed_y, x_range, y_range)
        if root is None:
            continue
        if not any(math.hypot(root[0] - other[0], root[1] - other[1]) <= merge_tolerance for other in roots):
            roots.append(root)

    items: list[dict[str, Any]] = []
    for x_value, y_value in sorted(roots, key=lambda point: (point[0], point[1])):
        jacobian = jacobian2d(x_func, y_func, x_value, y_value, x_range, y_range)
        classification = classify_nonlinear_equilibrium(jacobian)
        items.append(
            {
                "x": clean_number(x_value),
                "y": clean_number(y_value),
                "classification": classification,
                "jacobian": None
                if jacobian is None
                else [[clean_number(jacobian[0]), clean_number(jacobian[1])], [clean_number(jacobian[2]), clean_number(jacobian[3])]],
            }
        )
    return items[:24]


def sample_vector_field(
    x_func: SafeExpression,
    y_func: SafeExpression,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    samples: int = 17,
) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    for i in range(samples):
        x = x_range[0] + (x_range[1] - x_range[0]) * (i + 0.5) / samples
        for j in range(samples):
            y = y_range[0] + (y_range[1] - y_range[0]) * (j + 0.5) / samples
            value = field2d(x_func, y_func, x, y)
            if value is None:
                continue
            vx, vy = value
            if math.hypot(vx, vy) < 1e-12:
                continue
            points.append({"x": clean_number(x), "y": clean_number(y), "vx": clean_number(vx), "vy": clean_number(vy)})
    return points


def nonlinear2d_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    x_expression, y_expression, x_range, y_range = parse_nonlinear2d_payload(payload)
    x_func = SafeExpression(x_expression, ("x", "y"))
    y_func = SafeExpression(y_expression, ("x", "y"))

    return {
        "expressions": {"x": x_func.expression, "y": y_func.expression},
        "xRange": list(x_range),
        "yRange": list(y_range),
        "equilibria": find_nonlinear_equilibria(x_func, y_func, x_range, y_range),
        "nullclines": [
            {
                "id": "dx",
                "label": "x' = 0",
                "expression": x_func.expression,
                "segments": zero_contours(x_func, x_range, y_range),
            },
            {
                "id": "dy",
                "label": "y' = 0",
                "expression": y_func.expression,
                "segments": zero_contours(y_func, x_range, y_range),
            },
        ],
        "vectorField": sample_vector_field(x_func, y_func, x_range, y_range),
    }


def parse_nonhomogeneous2d_payload(
    payload: dict[str, Any],
) -> tuple[float, float, float, float, str, str, str, float, float, tuple[float, float], tuple[float, float], tuple[float, float]]:
    a, b, c, d = parse_linear2d_payload(payload)
    forcing_type = str(payload.get("forcingType") or "constant")
    allowed_types = {"constant", "exponential", "sinusoidal", "polynomial", "custom"}
    if forcing_type not in allowed_types:
        raise ValueError("La forma de f(t) no es valida.")
    fx_expression = str(payload.get("fxExpression") or "1")
    fy_expression = str(payload.get("fyExpression") or "0")
    try:
        lambda_value = float(payload.get("lambda", 0.0))
        time = float(payload.get("time", 0.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("lambda y t deben ser numericos.") from exc
    if not math.isfinite(lambda_value) or not math.isfinite(time):
        raise ValueError("lambda y t deben ser finitos.")
    t_range = parse_range(payload, "tRange", (0.0, 6.0))
    if t_range[0] < 0:
        raise ValueError("El rango temporal debe comenzar en un valor no negativo.")
    x_range = parse_range(payload, "xRange", (-5.0, 5.0))
    y_range = parse_range(payload, "yRange", (-5.0, 5.0))
    return a, b, c, d, forcing_type, fx_expression, fy_expression, lambda_value, time, t_range, x_range, y_range


def safe_eval_time(func: SafeExpression, time: float) -> float | None:
    try:
        value = func.evaluate(t=time)
    except Exception:
        return None
    return value if math.isfinite(value) else None


def forcing_at(x_func: SafeExpression, y_func: SafeExpression, time: float) -> tuple[float, float] | None:
    x_value = safe_eval_time(x_func, time)
    y_value = safe_eval_time(y_func, time)
    if not finite(x_value) or not finite(y_value):
        return None
    assert x_value is not None and y_value is not None
    return x_value, y_value


def derivative_time(func: SafeExpression, time: float = 0.0) -> float | None:
    h = 1e-5
    f_plus = safe_eval_time(func, time + h)
    f_minus = safe_eval_time(func, time - h)
    if not finite(f_plus) or not finite(f_minus):
        return None
    assert f_plus is not None and f_minus is not None
    return (f_plus - f_minus) / (2.0 * h)


def solve_2x2(p: float, q: float, r: float, s: float, u: float, v: float) -> tuple[float, float] | None:
    determinant = p * s - q * r
    if abs(determinant) < 1e-10:
        return None
    return ((u * s - q * v) / determinant, (p * v - u * r) / determinant)


def solve_linear_system(matrix: list[list[float]], values: list[float]) -> list[float] | None:
    size = len(values)
    augmented = [row[:] + [values[index]] for index, row in enumerate(matrix)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-10:
            return None
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        divisor = augmented[col][col]
        for j in range(col, size + 1):
            augmented[col][j] /= divisor
        for row in range(size):
            if row == col:
                continue
            factor = augmented[row][col]
            for j in range(col, size + 1):
                augmented[row][j] -= factor * augmented[col][j]
    return [augmented[row][size] for row in range(size)]


def nonhomogeneous_particular(
    a: float,
    b: float,
    c: float,
    d: float,
    forcing_type: str,
    x_func: SafeExpression,
    y_func: SafeExpression,
    lambda_value: float,
    time: float,
) -> dict[str, Any]:
    current_forcing = forcing_at(x_func, y_func, time)
    base_forcing = forcing_at(x_func, y_func, 0.0)
    empty_point = None

    if forcing_type == "constant":
        if base_forcing is None:
            return {"kind": "unknown", "summary": "f(t) no se pudo evaluar como constante.", "point": empty_point}
        solution = solve_2x2(a, b, c, d, -base_forcing[0], -base_forcing[1])
        if solution is None:
            return {
                "kind": "degenerate",
                "summary": "A no es invertible: puede no haber equilibrio unico o puede haber una recta de particulares.",
                "point": empty_point,
            }
        return {
            "kind": "constant",
            "summary": "Constante: el equilibrio se desplaza y cumple A xp = -b.",
            "point": {"x": clean_number(solution[0]), "y": clean_number(solution[1])},
            "formula": "A xp = -b",
        }

    if forcing_type == "exponential":
        if base_forcing is None:
            return {"kind": "unknown", "summary": "No se pudo evaluar el vector v de e^(lambda t) v.", "point": empty_point}
        solution = solve_2x2(lambda_value - a, -b, -c, lambda_value - d, base_forcing[0], base_forcing[1])
        if solution is None:
            return {
                "kind": "resonant",
                "summary": "Resonancia: lambda coincide con un autovalor y puede aparecer t e^(lambda t).",
                "point": empty_point,
                "formula": "(lambda I - A) w = v",
            }
        scale = math.exp(lambda_value * time)
        return {
            "kind": "exponential",
            "summary": "Exponencial: Xp(t) = e^(lambda t) w, con (lambda I - A)w = v.",
            "point": {"x": clean_number(scale * solution[0]), "y": clean_number(scale * solution[1])},
            "formula": "(lambda I - A) w = v",
        }

    if forcing_type == "sinusoidal":
        if base_forcing is None:
            return {"kind": "unknown", "summary": "No se pudo evaluar el termino senoidal.", "point": empty_point}
        derivative_x = derivative_time(x_func, 0.0)
        derivative_y = derivative_time(y_func, 0.0)
        if derivative_x is None or derivative_y is None:
            return {"kind": "unknown", "summary": "No se pudo estimar la componente seno de f(t).", "point": empty_point}
        # Xp = P cos(t) + Q sin(t).  Q - AP = u and -P - AQ = v.
        matrix = [
            [-a, -b, 1.0, 0.0],
            [-c, -d, 0.0, 1.0],
            [-1.0, 0.0, -a, -b],
            [0.0, -1.0, -c, -d],
        ]
        solution = solve_linear_system(matrix, [base_forcing[0], base_forcing[1], derivative_x, derivative_y])
        if solution is None:
            return {
                "kind": "resonant",
                "summary": "Caso resonante: la particular periodica simple puede no existir.",
                "point": empty_point,
            }
        p1, p2, q1, q2 = solution
        point_x = p1 * math.cos(time) + q1 * math.sin(time)
        point_y = p2 * math.cos(time) + q2 * math.sin(time)
        return {
            "kind": "sinusoidal",
            "summary": "Senoidal: la particular esperada es periodica.",
            "point": {"x": clean_number(point_x), "y": clean_number(point_y)},
            "formula": "Xp(t) = P cos(t) + Q sin(t)",
        }

    if forcing_type == "polynomial":
        return {
            "kind": "polynomial",
            "summary": "Polinomica: se busca una particular polinomica del mismo grado, salvo resonancia.",
            "point": empty_point,
        }

    if current_forcing is None:
        return {"kind": "unknown", "summary": "No se pudo evaluar f(t) en el tiempo actual.", "point": empty_point}
    return {
        "kind": "custom",
        "summary": "Manual: aplica variacion de constantes para obtener Xp(t).",
        "point": empty_point,
    }


def nonhomogeneous_behavior(forcing_type: str, classification: dict[str, str], lambda_value: float, eigenvalues: list[dict[str, float]]) -> str:
    if forcing_type == "constant":
        return "Constante: preserva el comportamiento asintotico y desplaza la particular."
    if forcing_type == "sinusoidal":
        return "Periodica: produce respuesta particular oscilatoria."
    if forcing_type == "polynomial":
        return "Polinomica: puede dominar si el homogeneo decae."
    if forcing_type == "exponential":
        spectral = max((item["real"] for item in eigenvalues), default=0.0)
        if lambda_value > spectral:
            return "Exponencial: puede romper el comportamiento asintotico del homogeneo."
        return "Exponencial: su peso se compara con los autovalores de A."
    return f"Manual: se superpone a un homogeneo tipo {classification['type']}."


def nonhomogeneous_field(
    a: float,
    b: float,
    c: float,
    d: float,
    x_func: SafeExpression,
    y_func: SafeExpression,
    x: float,
    y: float,
    time: float,
) -> tuple[float, float] | None:
    forcing = forcing_at(x_func, y_func, time)
    if forcing is None:
        return None
    return a * x + b * y + forcing[0], c * x + d * y + forcing[1]


def rk4_nonhomogeneous_step(
    a: float,
    b: float,
    c: float,
    d: float,
    x_func: SafeExpression,
    y_func: SafeExpression,
    x: float,
    y: float,
    time: float,
    h: float,
) -> tuple[float, float] | None:
    def field(px: float, py: float, pt: float) -> tuple[float, float] | None:
        return nonhomogeneous_field(a, b, c, d, x_func, y_func, px, py, pt)

    k1 = field(x, y, time)
    if k1 is None:
        return None
    k2 = field(x + 0.5 * h * k1[0], y + 0.5 * h * k1[1], time + 0.5 * h)
    if k2 is None:
        return None
    k3 = field(x + 0.5 * h * k2[0], y + 0.5 * h * k2[1], time + 0.5 * h)
    if k3 is None:
        return None
    k4 = field(x + h * k3[0], y + h * k3[1], time + h)
    if k4 is None:
        return None
    return (
        x + h * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0]) / 6.0,
        y + h * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1]) / 6.0,
    )


def sample_nonhomogeneous_vector_field(
    a: float,
    b: float,
    c: float,
    d: float,
    x_func: SafeExpression,
    y_func: SafeExpression,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    time: float,
    samples: int = 17,
) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    for i in range(samples):
        x = x_range[0] + (x_range[1] - x_range[0]) * (i + 0.5) / samples
        for j in range(samples):
            y = y_range[0] + (y_range[1] - y_range[0]) * (j + 0.5) / samples
            value = nonhomogeneous_field(a, b, c, d, x_func, y_func, x, y, time)
            if value is None:
                continue
            vx, vy = value
            if math.hypot(vx, vy) < 1e-12:
                continue
            points.append({"x": clean_number(x), "y": clean_number(y), "vx": clean_number(vx), "vy": clean_number(vy)})
    return points


def representative_nonhomogeneous_trajectories(
    a: float,
    b: float,
    c: float,
    d: float,
    x_func: SafeExpression,
    y_func: SafeExpression,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    t_range: tuple[float, float],
) -> list[list[dict[str, float]]]:
    x_min, x_max = x_range
    y_min, y_max = y_range
    seeds = [
        (x_min + 0.2 * (x_max - x_min), y_min + 0.2 * (y_max - y_min)),
        (x_min + 0.2 * (x_max - x_min), y_min + 0.8 * (y_max - y_min)),
        (x_min + 0.8 * (x_max - x_min), y_min + 0.2 * (y_max - y_min)),
        (x_min + 0.8 * (x_max - x_min), y_min + 0.8 * (y_max - y_min)),
        ((x_min + x_max) / 2.0, y_min + 0.25 * (y_max - y_min)),
        ((x_min + x_max) / 2.0, y_min + 0.75 * (y_max - y_min)),
        (x_min + 0.25 * (x_max - x_min), (y_min + y_max) / 2.0),
        (x_min + 0.75 * (x_max - x_min), (y_min + y_max) / 2.0),
    ]
    steps = 240
    h = (t_range[1] - t_range[0]) / steps
    trajectories: list[list[dict[str, float]]] = []

    def in_bounds(px: float, py: float) -> bool:
        return x_min <= px <= x_max and y_min <= py <= y_max

    for seed_x, seed_y in seeds:
        x_value, y_value = seed_x, seed_y
        time = t_range[0]
        points = [{"x": clean_number(x_value), "y": clean_number(y_value)}]
        for _ in range(steps):
            next_point = rk4_nonhomogeneous_step(a, b, c, d, x_func, y_func, x_value, y_value, time, h)
            if next_point is None:
                break
            x_value, y_value = next_point
            time += h
            if not in_bounds(x_value, y_value):
                break
            if len(points) % 3 == 0:
                points.append({"x": clean_number(x_value), "y": clean_number(y_value)})
            else:
                points.append({"x": clean_number(x_value), "y": clean_number(y_value)})
        if len(points) >= 2:
            trajectories.append(points[::3])
    return trajectories


def nonhomogeneous_cases() -> list[dict[str, str]]:
    return [
        {"form": "x' = Ax + b", "particular": "Constante: A xp = -b."},
        {"form": "x' = Ax + e^(lambda t)v", "particular": "Exponencial; puede aparecer t e^(lambda t) si hay resonancia."},
        {"form": "x' = Ax + a cos(t) + b sin(t)", "particular": "Periodica cuando no hay resonancia."},
        {"form": "x' = Ax + p(t)", "particular": "Polinomica del mismo grado, salvo resonancia."},
    ]


def nonhomogeneous2d_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    a, b, c, d, forcing_type, fx_expression, fy_expression, lambda_value, time, t_range, x_range, y_range = parse_nonhomogeneous2d_payload(
        payload
    )
    x_func = SafeExpression(fx_expression, ("t",))
    y_func = SafeExpression(fy_expression, ("t",))
    homogeneous = linear2d_analysis({"a": a, "b": b, "c": c, "d": d})
    behavior = nonhomogeneous_behavior(forcing_type, homogeneous["classification"], lambda_value, homogeneous["eigenvalues"])
    particular = nonhomogeneous_particular(a, b, c, d, forcing_type, x_func, y_func, lambda_value, time)
    current_forcing = forcing_at(x_func, y_func, time)

    return {
        "matrix": [[clean_number(a), clean_number(b)], [clean_number(c), clean_number(d)]],
        "homogeneous": {
            "classification": homogeneous["classification"],
            "eigenvalues": homogeneous["eigenvalues"],
            "eigenvectors": homogeneous["eigenvectors"],
            "solution": homogeneous["solution"],
        },
        "forcing": {
            "type": forcing_type,
            "expressions": {"x": x_func.expression, "y": y_func.expression},
            "value": None
            if current_forcing is None
            else {"x": clean_number(current_forcing[0]), "y": clean_number(current_forcing[1])},
            "behavior": behavior,
        },
        "particular": particular,
        "solutionInterpretation": "La solucion general suma el homogeneo asociado y una particular.",
        "time": clean_number(time),
        "tRange": list(t_range),
        "xRange": list(x_range),
        "yRange": list(y_range),
        "vectorField": sample_nonhomogeneous_vector_field(a, b, c, d, x_func, y_func, x_range, y_range, time),
        "trajectories": representative_nonhomogeneous_trajectories(a, b, c, d, x_func, y_func, x_range, y_range, t_range),
        "cases": nonhomogeneous_cases(),
    }


def safe_eval(func: Callable[[float, float], float], x: float, r: float) -> float | None:
    try:
        value = func(x, r)
    except Exception:
        return None
    return value if math.isfinite(value) else None


def derivative_x(func: Callable[[float, float], float], x: float, r: float, x_span: float) -> float | None:
    h = max(1e-5, abs(x_span) * 1e-6, abs(x) * 1e-6)
    f_plus = safe_eval(func, x + h, r)
    f_minus = safe_eval(func, x - h, r)
    if not finite(f_plus) or not finite(f_minus):
        return None
    return (f_plus - f_minus) / (2.0 * h)


def classify_stability(
    func: Callable[[float, float], float],
    x: float,
    r: float,
    x_range: tuple[float, float],
) -> tuple[str, float | None]:
    x_span = x_range[1] - x_range[0]
    derivative = derivative_x(func, x, r, x_span)
    if derivative is not None:
        threshold = max(1e-6, x_span * 1e-8)
        if derivative < -threshold:
            return "stable", derivative
        if derivative > threshold:
            return "unstable", derivative

    probe = max(1e-4, x_span * 1e-4)
    left = safe_eval(func, x - probe, r)
    right = safe_eval(func, x + probe, r)
    if not finite(left) or not finite(right):
        return "unknown", derivative

    left_sign = 1 if left > 0 else -1 if left < 0 else 0
    right_sign = 1 if right > 0 else -1 if right < 0 else 0
    if left_sign > 0 and right_sign < 0:
        return "stable", derivative
    if left_sign < 0 and right_sign > 0:
        return "unstable", derivative
    if left_sign == right_sign and left_sign != 0:
        return "semistable", derivative
    return "unknown", derivative


def merge_roots(roots: list[float], tolerance: float) -> list[float]:
    if not roots:
        return []
    roots = sorted(roots)
    merged = [roots[0]]
    for root in roots[1:]:
        if abs(root - merged[-1]) <= tolerance:
            merged[-1] = (merged[-1] + root) / 2.0
        else:
            merged.append(root)
    return merged


def bisect_root(
    func: Callable[[float, float], float],
    r: float,
    left: float,
    right: float,
    iterations: int = 64,
) -> float | None:
    f_left = safe_eval(func, left, r)
    f_right = safe_eval(func, right, r)
    if not finite(f_left) or not finite(f_right):
        return None
    if abs(f_left) < 1e-12:
        return left
    if abs(f_right) < 1e-12:
        return right
    if f_left * f_right > 0:
        return None

    lo, hi = left, right
    flo, fhi = f_left, f_right
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        fmid = safe_eval(func, mid, r)
        if not finite(fmid):
            return None
        if abs(fmid) < 1e-12 or abs(hi - lo) < 1e-10:
            return mid
        if flo * fmid <= 0:
            hi, fhi = mid, fmid
        else:
            lo, flo = mid, fmid
    return (lo + hi) / 2.0


def minimize_abs_root(
    func: Callable[[float, float], float],
    r: float,
    left: float,
    right: float,
    tolerance: float,
) -> float | None:
    # Golden-section search over |f| catches tangent roots such as x^2 = 0.
    gr = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = left, right
    c = b - gr * (b - a)
    d = a + gr * (b - a)

    def score(x_value: float) -> float:
        y_value = safe_eval(func, x_value, r)
        return abs(y_value) if finite(y_value) else float("inf")

    fc = score(c)
    fd = score(d)
    for _ in range(48):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - gr * (b - a)
            fc = score(c)
        else:
            a, c, fc = c, d, fd
            d = a + gr * (b - a)
            fd = score(d)

    candidate = (a + b) / 2.0
    return candidate if score(candidate) <= tolerance else None


def find_roots(
    func: Callable[[float, float], float],
    r: float,
    x_range: tuple[float, float],
    samples: int = 720,
) -> list[float]:
    x_min, x_max = x_range
    if x_min >= x_max:
        raise ValueError("El rango de x debe tener mínimo menor que máximo.")

    xs = [x_min + (x_max - x_min) * i / samples for i in range(samples + 1)]
    if x_min <= 0 <= x_max:
        xs.append(0.0)
    xs = sorted(set(round(x, 14) for x in xs))
    ys = [safe_eval(func, x, r) for x in xs]
    finite_values = [abs(y) for y in ys if finite(y)]
    scale = max(finite_values, default=1.0)
    zero_tolerance = max(1e-7, scale * 1e-5)
    exact_tolerance = max(1e-11, scale * 1e-11)
    merge_tolerance = max(1e-5, (x_max - x_min) * 2e-4)

    roots: list[float] = []

    for x_value, y_value in zip(xs, ys):
        if finite(y_value) and abs(y_value) <= exact_tolerance:
            roots.append(x_value)

    for i in range(len(xs) - 1):
        x_left, x_right = xs[i], xs[i + 1]
        y_left, y_right = ys[i], ys[i + 1]
        if not finite(y_left) or not finite(y_right):
            continue
        if y_left == 0 or y_right == 0:
            continue
        if y_left * y_right < 0:
            root = bisect_root(func, r, x_left, x_right)
            if root is not None:
                roots.append(root)

    for i in range(1, len(xs) - 1):
        y_prev, y_now, y_next = ys[i - 1], ys[i], ys[i + 1]
        if not finite(y_prev) or not finite(y_now) or not finite(y_next):
            continue
        if abs(y_now) <= abs(y_prev) and abs(y_now) <= abs(y_next) and abs(y_now) <= zero_tolerance:
            root = minimize_abs_root(func, r, xs[i - 1], xs[i + 1], zero_tolerance)
            if root is not None:
                roots.append(root)

    return merge_roots(roots, merge_tolerance)


def equilibrium_payload(
    roots: list[float],
    func: Callable[[float, float], float],
    r: float,
    x_range: tuple[float, float],
) -> list[dict[str, Any]]:
    items = []
    for root in roots:
        stability, derivative = classify_stability(func, root, r, x_range)
        items.append(
            {
                "x": clean_number(root),
                "stability": stability,
                "derivative": None if derivative is None else clean_number(derivative),
            }
        )
    return items


def sample_phase(
    func: Callable[[float, float], float],
    r: float,
    x_range: tuple[float, float],
    samples: int = 360,
) -> dict[str, Any]:
    x_min, x_max = x_range
    points = []
    for i in range(samples + 1):
        x = x_min + (x_max - x_min) * i / samples
        y = safe_eval(func, x, r)
        points.append({"x": clean_number(x), "y": None if not finite(y) else clean_number(y)})
    return {"points": points, "xRange": [x_min, x_max]}


def default_branches(
    model_key: str,
    r_range: tuple[float, float],
    x_range: tuple[float, float],
    samples: int = 260,
) -> list[dict[str, Any]]:
    r_min, r_max = r_range
    branches: list[dict[str, Any]] = []

    def in_x(x: float) -> bool:
        return x_range[0] <= x <= x_range[1]

    r_values = [r_min + (r_max - r_min) * i / samples for i in range(samples + 1)]
    if r_min <= 0 <= r_max:
        r_values.append(0.0)
    r_values = sorted(set(round(r, 14) for r in r_values))

    if model_key == "saddle-node":
        stable, unstable = [], []
        for r in r_values:
            if r <= 0:
                value = math.sqrt(max(0.0, -r))
                if in_x(-value):
                    stable.append({"r": clean_number(r), "x": clean_number(-value), "stability": "stable"})
                if in_x(value):
                    unstable.append({"r": clean_number(r), "x": clean_number(value), "stability": "unstable"})
        branches.append({"id": "stable-negative", "kind": "line", "points": stable})
        branches.append({"id": "unstable-positive", "kind": "line", "points": unstable})

    if model_key == "pitchfork":
        zero_branch, positive, negative = [], [], []
        for r in r_values:
            zero_branch.append(
                {
                    "r": clean_number(r),
                    "x": 0.0,
                    "stability": "stable" if r <= 0 else "unstable",
                }
            )
            if r >= 0:
                value = math.sqrt(max(0.0, r))
                if in_x(value):
                    positive.append({"r": clean_number(r), "x": clean_number(value), "stability": "stable"})
                if in_x(-value):
                    negative.append({"r": clean_number(r), "x": clean_number(-value), "stability": "stable"})
        branches.append({"id": "zero", "kind": "line", "points": zero_branch})
        branches.append({"id": "positive", "kind": "line", "points": positive})
        branches.append({"id": "negative", "kind": "line", "points": negative})

    if model_key == "transcritical":
        zero_branch, diagonal = [], []
        for r in r_values:
            zero_branch.append(
                {
                    "r": clean_number(r),
                    "x": 0.0,
                    "stability": "stable" if r < 0 else "unstable" if r > 0 else "semistable",
                }
            )
            if in_x(r):
                diagonal.append(
                    {
                        "r": clean_number(r),
                        "x": clean_number(r),
                        "stability": "unstable" if r < 0 else "stable" if r > 0 else "semistable",
                    }
                )
        branches.append({"id": "zero", "kind": "line", "points": zero_branch})
        branches.append({"id": "diagonal", "kind": "line", "points": diagonal})

    return branches


def default_bifurcation_points(model_key: str) -> list[dict[str, Any]]:
    labels = {
        "saddle-node": "Silla-nodo",
        "pitchfork": "Tridente",
        "transcritical": "Transcrítica",
    }
    if model_key in labels:
        return [{"r": 0.0, "x": 0.0, "type": labels[model_key], "confidence": "analytic"}]
    return []


def manual_bifurcation(
    func: Callable[[float, float], float],
    r_range: tuple[float, float],
    x_range: tuple[float, float],
    samples: int = 170,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    r_min, r_max = r_range
    points: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    previous_roots: list[float] | None = None
    previous_r: float | None = None
    previous_count: int | None = None

    for i in range(samples + 1):
        r = r_min + (r_max - r_min) * i / samples
        roots = find_roots(func, r, x_range, samples=360)
        for root in roots:
            stability, derivative = classify_stability(func, root, r, x_range)
            points.append({"r": clean_number(r), "x": clean_number(root), "stability": stability})
            if derivative is not None and abs(derivative) < 2e-2:
                candidates.append(
                    {
                        "r": clean_number(r),
                        "x": clean_number(root),
                        "type": "candidato no hiperbólico",
                        "confidence": "numeric",
                    }
                )

        if previous_count is not None and previous_count != len(roots) and previous_r is not None:
            midpoint_r = (previous_r + r) / 2.0
            near_x = 0.0
            nearby = (previous_roots or []) + roots
            if nearby:
                near_x = sum(nearby) / len(nearby)
            candidates.append(
                {
                    "r": round(midpoint_r, 8),
                    "x": clean_number(near_x),
                    "type": "cambio en cantidad de equilibrios",
                    "confidence": "numeric",
                }
            )

        previous_roots = roots
        previous_count = len(roots)
        previous_r = r

    merged_candidates = merge_bifurcation_candidates(candidates, r_range, x_range)
    return [{"id": "manual-roots", "kind": "scatter", "points": points}], merged_candidates


def merge_bifurcation_candidates(
    candidates: list[dict[str, Any]],
    r_range: tuple[float, float],
    x_range: tuple[float, float],
) -> list[dict[str, Any]]:
    if not candidates:
        return []
    r_tol = max(1e-4, (r_range[1] - r_range[0]) / 80.0)
    x_tol = max(1e-4, (x_range[1] - x_range[0]) / 80.0)
    merged: list[dict[str, Any]] = []

    for candidate in sorted(candidates, key=lambda item: (item["r"], item["x"])):
        match = None
        for existing in merged:
            if abs(existing["r"] - candidate["r"]) <= r_tol and abs(existing["x"] - candidate["x"]) <= x_tol:
                match = existing
                break
        if match is None:
            merged.append(dict(candidate))
        else:
            match["r"] = round((match["r"] + candidate["r"]) / 2.0, 8)
            match["x"] = round((match["x"] + candidate["x"]) / 2.0, 8)
            if match["type"] != candidate["type"]:
                match["type"] = "candidato mixto"

    return merged[:12]


def parse_range(payload: dict[str, Any], key: str, fallback: tuple[float, float]) -> tuple[float, float]:
    value = payload.get(key, fallback)
    if not isinstance(value, list | tuple) or len(value) != 2:
        raise ValueError(f"{key} debe tener dos valores.")
    lo, hi = float(value[0]), float(value[1])
    if not math.isfinite(lo) or not math.isfinite(hi) or lo >= hi:
        raise ValueError(f"{key} debe ser un rango finito con mínimo menor que máximo.")
    return lo, hi


def prepare_analysis(
    payload: dict[str, Any],
) -> tuple[str, Model, SafeExpression, float, tuple[float, float], tuple[float, float], bool]:
    requested_key = str(payload.get("model", "saddle-node"))
    model = MODELS.get(requested_key, MANUAL_MODEL)
    expression = str(payload.get("expression") or model.expression)
    parameter = float(payload.get("parameter", model.default_parameter))
    if not math.isfinite(parameter):
        raise ValueError("El parámetro r debe ser finito.")

    x_range = parse_range(payload, "xRange", model.x_range)
    r_range = parse_range(payload, "rRange", model.r_range)
    safe_expression = SafeExpression(expression)

    is_default = requested_key in MODELS and safe_expression.expression.replace(" ", "") == model.expression.replace(" ", "")
    return requested_key, model, safe_expression, parameter, x_range, r_range, is_default


def frame(payload: dict[str, Any]) -> dict[str, Any]:
    requested_key, model, func, parameter, x_range, r_range, is_default = prepare_analysis(payload)
    roots = find_roots(func, parameter, x_range)
    equilibria = equilibrium_payload(roots, func, parameter, x_range)

    return {
        "model": {
            "key": requested_key if is_default else "manual",
            "label": model.label if is_default else MANUAL_MODEL.label,
            "expression": func.expression,
        },
        "parameter": parameter,
        "xRange": list(x_range),
        "rRange": list(r_range),
        "equilibria": equilibria,
        "phase": sample_phase(func, parameter, x_range),
    }


def analyze(payload: dict[str, Any]) -> dict[str, Any]:
    requested_key, model, func, parameter, x_range, r_range, is_default = prepare_analysis(payload)
    current_frame = frame(payload)

    if is_default:
        branches = default_branches(requested_key, r_range, x_range)
        bifurcation_points = default_bifurcation_points(requested_key)
    else:
        branches, bifurcation_points = manual_bifurcation(func, r_range, x_range)

    return {
        **current_frame,
        "bifurcationPoints": bifurcation_points,
        "bifurcation": {"branches": branches},
    }


class SimulatorHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        clean_path = path.split("?", 1)[0].split("#", 1)[0]
        static_root = STATIC_DIR.resolve()
        if clean_path == "/":
            return str(STATIC_DIR / "index.html")
        if clean_path.startswith("/static/"):
            requested = clean_path.removeprefix("/static/")
            target = (STATIC_DIR / requested).resolve()
        else:
            target = (STATIC_DIR / clean_path.lstrip("/")).resolve()
        if target != static_root and static_root not in target.parents:
            return str(STATIC_DIR / "__missing__")
        return str(target)

    def do_GET(self) -> None:
        if self.path.startswith("/api/health"):
            self.send_json({"ok": True})
            return
        if self.path.startswith("/api/models"):
            self.send_json(
                {
                    "models": [
                        {
                            "key": model.key,
                            "label": model.label,
                            "expression": model.expression,
                            "defaultParameter": model.default_parameter,
                            "xRange": list(model.x_range),
                            "rRange": list(model.r_range),
                            "description": model.description,
                        }
                        for model in [*MODELS.values(), MANUAL_MODEL]
                    ]
                }
            )
            return
        return super().do_GET()

    def do_POST(self) -> None:
        if not (
            self.path.startswith("/api/analyze")
            or self.path.startswith("/api/frame")
            or self.path.startswith("/api/linear2d")
            or self.path.startswith("/api/nonhomogeneous2d")
            or self.path.startswith("/api/nonlinear2d")
        ):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length)
            payload = json.loads(raw.decode("utf-8") or "{}")
            if self.path.startswith("/api/nonlinear2d"):
                result = nonlinear2d_analysis(payload)
            elif self.path.startswith("/api/nonhomogeneous2d"):
                result = nonhomogeneous2d_analysis(payload)
            elif self.path.startswith("/api/linear2d"):
                result = linear2d_analysis(payload)
            elif self.path.startswith("/api/frame"):
                result = frame(payload)
            else:
                result = analyze(payload)
        except (ExpressionError, ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            self.send_json({"error": f"Error interno: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.send_json(result)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def guess_type(self, path: str) -> str:
        if path.endswith(".js"):
            return "text/javascript"
        return mimetypes.guess_type(path)[0] or "application/octet-stream"

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run() -> None:
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), SimulatorHandler)
    print(f"Simulador disponible en http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
