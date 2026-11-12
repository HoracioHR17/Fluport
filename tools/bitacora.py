"""Control de commits para la bitácora del README.

Muestra los commits del repositorio (más antiguo primero) junto a las entradas de la bitácora, y señala las que
aún tienen un número provisional (`#NNN`) en lugar del hash de su commit. Solo lee: no modifica el repositorio.

Uso (desde la raíz del proyecto):
    python3 tools/bitacora.py            # commits y entradas pendientes
    python3 tools/bitacora.py --todos    # además, todas las entradas de la bitácora
"""
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ENTRADA = re.compile(r"^### (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) · `([^`]+)` · (.+)$", re.M)


def commits() -> list[tuple[str, str, str]]:
    salida = subprocess.run(
        ["git", "log", "--reverse", "--date=format:%Y-%m-%d %H:%M", "--pretty=format:%h\t%ad\t%s"],
        cwd=RAIZ, capture_output=True, text=True, check=True,
    ).stdout
    return [tuple(linea.split("\t", 2)) for linea in salida.splitlines() if linea]


def entradas() -> list[tuple[str, str, str]]:
    return ENTRADA.findall((RAIZ / "README.md").read_text(encoding="utf-8"))


def main() -> None:
    lista = commits()
    hashes = {h for h, _, _ in lista}
    print(f"Commits ({len(lista)}):")
    for h, fecha, msg in lista:
        print(f"  {h} · {fecha} · {msg}")
    ents = entradas()
    pendientes = [e for e in ents if e[1].startswith("#")]
    desconocidos = [e for e in ents if not e[1].startswith("#") and e[1] not in hashes]
    print(f"\nEntradas de la bitácora: {len(ents)} · con número provisional: {len(pendientes)}")
    for fecha, ref, titulo in pendientes:
        print(f"  {ref} · {fecha} · {titulo}")
    if desconocidos:
        print("\nEntradas con un hash que no está en el historial (revisar):")
        for fecha, ref, titulo in desconocidos:
            print(f"  {ref} · {fecha} · {titulo}")
    if "--todos" in sys.argv:
        print("\nTodas las entradas:")
        for fecha, ref, titulo in ents:
            print(f"  {ref} · {fecha} · {titulo}")


if __name__ == "__main__":
    main()
