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
    def __init__(self, expression: str):
        self.original = expression.strip()
        self.expression = self.original.replace("^", "**")
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
                if node.id not in {"x", "r", *SAFE_FUNCTIONS.keys(), *SAFE_CONSTANTS.keys()}:
                    raise ExpressionError(f"Nombre no permitido: {node.id}. Usá solo x, r y funciones matemáticas.")
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in SAFE_FUNCTIONS:
                    raise ExpressionError("Solo se admiten llamadas a funciones matemáticas permitidas.")

    def __call__(self, x: float, r: float) -> float:
        env = {**SAFE_FUNCTIONS, **SAFE_CONSTANTS, "x": x, "r": r}
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
        if not (self.path.startswith("/api/analyze") or self.path.startswith("/api/frame")):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length)
            payload = json.loads(raw.decode("utf-8") or "{}")
            result = frame(payload) if self.path.startswith("/api/frame") else analyze(payload)
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
