"""Worker de tareas programadas. Ejecutar con: python -m src.jobs.worker"""
import json
import logging
import os
import time
from datetime import date, datetime

from src.application.scheduled_tasks import (
    generar_alertas_vencimiento,
    procesar_membresias_vencidas,
    procesar_promociones_expiradas,
)
from src.infrastructure.database import make_engine, make_session
from src.infrastructure.repositories import SqlOutboxNotificador

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("fitzone.worker")


def _hora_alertas() -> tuple[int, int]:
    valor = os.getenv("FITZONE_ALERTA_HORA", "08:00")
    try:
        hora, minuto = (int(parte) for parte in valor.split(":", 1))
        if not (0 <= hora <= 23 and 0 <= minuto <= 59):
            raise ValueError
        return hora, minuto
    except ValueError as exc:
        raise ValueError("FITZONE_ALERTA_HORA debe usar formato HH:MM") from exc


def ejecutar_ciclo(engine, ultima_fecha_alerta: date | None) -> date | None:
    """Ejecuta el barrido de promociones y, una vez al día, genera alertas."""
    session = make_session(engine)
    try:
        vencimientos = procesar_membresias_vencidas(session)
        if vencimientos["procesadas"]:
            logger.info("Membresías vencidas procesadas: %s", json.dumps(vencimientos, ensure_ascii=False))
        resultado = procesar_promociones_expiradas(session)
        if resultado["procesadas"]:
            logger.info("Promociones expiradas: %s", json.dumps(resultado, ensure_ascii=False))
    finally:
        session.close()

    ahora = datetime.now()
    hora, minuto = _hora_alertas()
    if ahora.hour == hora and ahora.minute >= minuto and ultima_fecha_alerta != ahora.date():
        session = make_session(engine)
        try:
            dias = int(os.getenv("FITZONE_ALERTA_DIAS", "7"))
            alertas = generar_alertas_vencimiento(session, dias_anticipacion=dias)
            # Se conserva el digest diario en outbox para el administrador.
            if alertas["total_alertas"]:
                resumen = "\n".join(
                    f"{item['socio_id']} — {item['nombre']}: vence {item['fecha_vencimiento']} "
                    f"(faltan {item['dias_restantes']} días)"
                    for item in alertas["alertas"]
                )
                SqlOutboxNotificador(session).enviar_notificacion(
                    "ADMIN", "Alertas diarias de vencimiento de membresías", resumen
                )
                session.commit()
            # También se registra salida estructurada para observabilidad.
            logger.info("ALERTAS_VENCIMIENTO %s", json.dumps(alertas, ensure_ascii=False))
            ultima_fecha_alerta = ahora.date()
        finally:
            session.close()
    return ultima_fecha_alerta


def main() -> None:
    engine = make_engine()
    intervalo = max(10, int(os.getenv("FITZONE_WORKER_INTERVAL_SECONDS", "60")))
    logger.info("Worker FitZone iniciado; intervalo=%ss", intervalo)
    try:
        ultima_fecha_alerta = None
        while True:
            try:
                ultima_fecha_alerta = ejecutar_ciclo(engine, ultima_fecha_alerta)
            except Exception:
                logger.exception("Error en ciclo de tareas programadas; se reintentará")
            time.sleep(intervalo)
    except KeyboardInterrupt:
        logger.info("Worker detenido")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
