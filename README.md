# Simulador 1D autónomo

Backend Python y frontend estático para analizar sistemas autónomos de una dimensión:

```text
x' = f(x, r)
```

Incluye modelos por defecto:

- Silla-Nodo: `x' = r + x**2`
- Tridente: `x' = r*x - x**3`
- Transcrítica: `x' = r*x - x**2`
- Manual: expresión ingresada con variables `x` y `r`

La entrada manual admite constantes y funciones como:

- `e`, `pi`
- `sin`, `sen`, `cos`, `tan`, `tg`
- `sqrt`, `raiz`, `nroot(valor, indice)`
- `log`, `ln`, `log10`, `exp`

## Ejecución

```powershell
python server.py
```

Si `python` no está en el PATH, se puede usar cualquier Python 3.10+ apuntando a `server.py`.
En este workspace también queda disponible:

```powershell
.\run_server.cmd
```

Luego abrir:

```text
http://127.0.0.1:8000
```

## API

- `GET /api/models`
- `POST /api/analyze`
- `POST /api/frame`

Ejemplo de cuerpo para `POST /api/analyze`:

```json
{
  "model": "pitchfork",
  "expression": "r*x - x**3",
  "parameter": -1,
  "xRange": [-3, 3],
  "rRange": [-3, 3]
}
```
