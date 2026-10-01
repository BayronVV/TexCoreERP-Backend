"""Espera el resultado real del despliegue de Render para el commit actual.

Lo usa el workflow "Despliegue en Render". Consulta la API de Render hasta que el despliegue de
GITHUB_SHA termina y sale con código 0 si quedó en línea o con 1 si falló, de modo que el
despliegue de GitHub (y con él Jira) refleje lo que pasó de verdad en Render.

Variables: RENDER_API_KEY, RENDER_SERVICE_ID, GITHUB_SHA. Opcionales (para pruebas):
RENDER_API_URL, POLL_SECONDS, WAIT_START_SECONDS, WAIT_TOTAL_SECONDS.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("RENDER_API_URL", "https://api.render.com").rstrip("/")
SERVICE = os.environ.get("RENDER_SERVICE_ID", "")
KEY = os.environ.get("RENDER_API_KEY", "")
SHA = os.environ.get("GITHUB_SHA", "")
POLL = int(os.environ.get("POLL_SECONDS", "15"))
WAIT_START = int(os.environ.get("WAIT_START_SECONDS", "300"))  # tiempo máximo para que Render lo inicie
WAIT_TOTAL = int(os.environ.get("WAIT_TOTAL_SECONDS", "1200"))  # tiempo máximo para que termine

# "deactivated": estuvo en línea y otro despliegue posterior lo reemplazó.
SUCCEEDED = {"live", "deactivated"}
FAILED = {"build_failed", "update_failed", "pre_deploy_failed", "canceled"}


def fail(message):
    print(f"::error::{message}", flush=True)
    sys.exit(1)


def deploys():
    request = urllib.request.Request(
        f"{API}/v1/services/{SERVICE}/deploys?limit=20",
        headers={"Authorization": f"Bearer {KEY}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def deploy_for_commit(items):
    """El más reciente que corresponde al commit. La API envuelve cada uno en {"deploy": {...}}."""
    for item in items:
        deploy = item.get("deploy", item)
        if (deploy.get("commit") or {}).get("id") == SHA:
            return deploy
    return None


def main():
    if not KEY:
        fail("Falta el secreto RENDER_API_KEY (GitHub: Settings > Secrets and variables > Actions).")
    if not SERVICE or not SHA:
        fail("Faltan RENDER_SERVICE_ID o GITHUB_SHA.")

    started = time.time()
    consecutive_errors = 0
    last = None
    while True:
        try:
            deploy = deploy_for_commit(deploys())
            consecutive_errors = 0
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                fail("Render rechazó la clave de API: revisa el secreto RENDER_API_KEY.")
            consecutive_errors += 1
            deploy = None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            consecutive_errors += 1
            deploy = None
        if consecutive_errors >= 5:
            fail("No se pudo consultar la API de Render (5 intentos seguidos).")

        status = deploy["status"] if deploy else "sin_despliegue"
        if status != last:
            print(f"Render ({SHA[:7]}): {status}", flush=True)
            last = status

        if status in SUCCEEDED:
            print("Despliegue en Render completado.")
            return
        if status in FAILED:
            fail(f"El despliegue en Render terminó con estado {status}.")
        elapsed = time.time() - started
        if deploy is None and consecutive_errors == 0 and elapsed > WAIT_START:
            fail("Render no inició un despliegue para este commit (¿auto-deploy desactivado?).")
        if elapsed > WAIT_TOTAL:
            fail("El despliegue de Render no terminó a tiempo.")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
