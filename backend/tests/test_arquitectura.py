"""Reglas de dependencia del monolito modular hexagonal (ver docs/arquitectura.md).

1. El núcleo (`app/nucleo`) no depende de ningún módulo (salvo tipos en `if TYPE_CHECKING`).
2. El dominio de cada módulo (`dominio/`) no depende de frameworks ni de infraestructura.
3. Un módulo no usa los adaptadores, el dominio ni la API de otro módulo: solo su servicio o sus puertos.
4. Solo la raíz de composición (`app/main.py`) une los módulos con sus adaptadores.
"""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
INFRA = ("fastapi", "sqlalchemy", "httpx", "starlette", "psycopg", "app.nucleo.db")
# excepciones documentadas: el entrenamiento usa la simulación como fuente de datos históricos
PERMITIDAS = {("pronostico", "app.modulos.simulacion.historico"), ("pronostico", "app.modulos.simulacion.dominio.escenario")}


def _importaciones(archivo: Path) -> list[str]:
    arbol = ast.parse(archivo.read_text(encoding="utf-8"))
    tipos = set()
    for n in ast.walk(arbol):  # importaciones solo para el verificador de tipos
        if isinstance(n, ast.If) and "TYPE_CHECKING" in ast.unparse(n.test):
            tipos.update(id(x) for x in ast.walk(n))
    mods = []
    for n in ast.walk(arbol):
        if id(n) in tipos:
            continue
        if isinstance(n, ast.ImportFrom) and n.module:
            if n.module.count(".") == 2 and n.module.startswith("app.modulos."):  # from app.modulos.x import servicio
                mods.extend(f"{n.module}.{a.name}" for a in n.names)
            else:
                mods.append(n.module)
        elif isinstance(n, ast.Import):
            mods.extend(a.name for a in n.names)
    return mods


def _modulo(archivo: Path) -> str | None:
    partes = archivo.relative_to(APP).parts
    return partes[1] if partes[0] == "modulos" and len(partes) > 2 else None


def test_nucleo_no_depende_de_modulos():
    for f in (APP / "nucleo").rglob("*.py"):
        assert not [m for m in _importaciones(f) if m.startswith("app.modulos")], f


def test_dominio_sin_infraestructura():
    for f in APP.glob("modulos/*/dominio/*.py"):
        malas = [m for m in _importaciones(f) if m.startswith(INFRA)]
        assert not malas, f"{f.relative_to(APP)} importa {malas}"


def test_modulos_solo_usan_servicios_o_puertos_de_otros():
    for f in (APP / "modulos").rglob("*.py"):
        propio = _modulo(f)
        for m in _importaciones(f):
            if not m.startswith("app.modulos.") or (propio, m) in PERMITIDAS:
                continue
            otro = m.split(".")[2]
            if otro == propio:
                continue
            interno = m.split(".")[3:4]
            assert interno and interno[0] in ("servicio", "puertos", "pronosticador"), (
                f"{f.relative_to(APP)} usa {m}: usa el servicio o los puertos de '{otro}'")


def test_consumidores_dependen_del_puerto_no_del_simulador():
    for nombre in ("citas", "mensajeria", "publico", "pronostico", "agencias"):
        for f in (APP / "modulos" / nombre).rglob("*.py"):
            assert "app.modulos.simulacion.dominio.motor" not in _importaciones(f), f
