#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt

# Crear la base de datos al construir la aplicación
python -c "import database; database.crear_bd()"