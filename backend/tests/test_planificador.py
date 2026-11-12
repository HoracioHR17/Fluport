"""Planificador de franjas (Mundo B)."""
from app.modulos.simulacion.dominio.planificador import FRANJA_MIN, Planificador


def test_elige_la_franja_menos_cargada(esc):
    pl = Planificador(esc)
    deseada = 600.0  # 10:00 simulado
    f = int(deseada // FRANJA_MIN)
    pl.ocupacion[("A1", f)] = 999  # la franja deseada está saturada
    acceso, inicio = pl.asignar(deseada, "A1")
    assert (acceso, int(inicio // FRANJA_MIN)) != ("A1", f)


def test_sin_carga_respeta_la_hora_y_el_acceso(esc):
    acceso, inicio = Planificador(esc).asignar(600.0, "A2")
    assert acceso == "A2" and inicio == 600.0


def test_carga_prioritaria_conserva_su_horario(esc):
    pl = Planificador(esc)
    pl.ocupacion[("A1", 20)] = 999
    assert pl.asignar(605.0, "A1", prioritario=True) == ("A1", 605.0)


def test_acceso_cerrado_se_evita(esc):
    pl = Planificador(esc)
    pl.cerrados.add("A3")
    acceso, _ = pl.asignar(600.0, "A3")
    assert acceso != "A3"


def test_asignar_reserva_lugar(esc):
    pl = Planificador(esc)
    acceso, inicio = pl.asignar(600.0, "A1")
    assert pl.ocupacion[(acceso, int(inicio // FRANJA_MIN))] == 1


def test_candidatos_ordenados_por_puntaje(esc):
    c = Planificador(esc).candidatos(600.0, "A1")
    assert c == sorted(c) and len(c) > 1


def test_cierre_reasigna_dentro_del_mismo_corredor(esc):
    """Si su entrada del norte se cierra, el camión va a otra entrada del norte, no al sur."""
    pl = Planificador(esc)
    pl.cerrados.add("A3")
    acceso, _ = pl.asignar(600.0, "A3")
    assert esc.acceso(acceso).entrada == esc.acceso("A3").entrada


def test_rodeo_entre_corredores():
    from app.nucleo.corredores import rodeo_min

    assert rodeo_min("norte", "norte") == 0 and rodeo_min(None, "sur") == 0
    assert rodeo_min("norte", "sur") > rodeo_min("norte", "urbana") > 0
