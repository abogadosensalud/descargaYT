# run.py
import subprocess
import multiprocessing
import os
import signal
import sys

def run_gunicorn():
    """Inicia el servidor Gunicorn."""
    print("Iniciando Gunicorn...")
    # Usamos exec para reemplazar el proceso actual con gunicorn.
    # Esto asegura que gunicorn reciba las señales del sistema operativo correctamente.
    args = [
        "gunicorn",
        "--bind", "0.0.0.0:10000",
        "--worker-tmp-dir", "/dev/shm",
        "--timeout", "180",
        "app:app"
    ]
    os.execvp(args[0], args)

def run_celery_worker():
    """Inicia el worker de Celery."""
    print("Iniciando Celery Worker...")
    # Esperamos un poco para asegurarnos de que Redis esté listo, si es necesario.
    # import time
    # time.sleep(5)
    
    # Usamos exec para la misma razón que con gunicorn.
    args = [
        "celery",
        "-A", "app.celery",
        "worker",
        "--loglevel=info"
    ]
    os.execvp(args[0], args)


def main():
    # Creamos un proceso para Gunicorn
    gunicorn_process = multiprocessing.Process(target=run_gunicorn)
    gunicorn_process.start()

    # Creamos un proceso para el Worker de Celery
    celery_process = multiprocessing.Process(target=run_celery_worker)
    celery_process.start()
    
    # Función para manejar las señales de terminación de Render
    def signal_handler(signum, frame):
        print(f"Señal {signum} recibida. Terminando procesos hijos...")
        # Enviamos la señal a los procesos hijos
        if gunicorn_process.is_alive():
            os.kill(gunicorn_process.pid, signal.SIGTERM)
        if celery_process.is_alive():
            os.kill(celery_process.pid, signal.SIGTERM)
        
        # Esperamos a que terminen
        gunicorn_process.join()
        celery_process.join()
        print("Procesos terminados. Saliendo.")
        sys.exit(0)

    # Registramos los manejadores de señales
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Esperamos indefinidamente. El signal_handler se encargará de la salida.
    # O podemos esperar a que uno de los dos procesos termine.
    gunicorn_process.join()
    celery_process.join()


if __name__ == '__main__':
    main()