import os
from datetime import datetime
from itertools import zip_longest
from functools import wraps
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, flash, Response, session

import database
from pricing import calcular_precio

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-only-change-me')

# === Config del negocio ===
WHATSAPP_NUMBER = os.getenv("LAVA_WHATSAPP", "51999999999")
LAVA_DIRECCION = os.getenv("LAVA_DIRECCION", "Tu calle #123, Huánuco")
PROMO_BANNER = os.getenv("LAVA_PROMO", "🌿 Martes: perfumado GRATIS en lavados por kilo")

# Inicializar BD
database.crear_bd()

# Inyectar datos globales a los templates
@app.context_processor
def inject_globals():
    return dict(
        WHATSAPP_NUMBER=WHATSAPP_NUMBER,
        LAVA_DIRECCION=LAVA_DIRECCION,
        PROMO_BANNER=PROMO_BANNER,
        logged_in=session.get('user_logged_in', False),
        admin_logged_in=session.get('admin_logged_in', False)
    )

# --- Helpers ---
def to_float(x, default=0.0):
    """Convierte un valor a float de forma segura."""
    try: return float(str(x or "0").replace(",", "."))
    except (ValueError, TypeError): return default

def to_int(x, default=0):
    """Convierte un valor a int de forma segura."""
    try: return int(float(x or 0))
    except (ValueError, TypeError): return default

# --- Autenticación ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Forzar login si no está logueado o si el día cambió
        today_str = datetime.now().strftime('%Y-%m-%d')
        if not session.get('user_logged_in') or session.get('login_date') != today_str:
            session.pop('user_logged_in', None)
            flash("Por favor, inicia sesión para acceder a esta página.", "info")
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        admin_password = database.get_config('ADMIN_PASSWORD', 'Cris123')
        user_password = database.get_config('USER_PASSWORD', 'Rios123')

        if password == admin_password:
            session['user_logged_in'] = True
            session['admin_logged_in'] = True
            session['login_date'] = datetime.now().strftime('%Y-%m-%d')
            flash('¡Inicio de sesión como Administrador!', 'success')
            next_url = request.args.get('next')
            return redirect(next_url or url_for('boletas'))
        elif password == user_password:
            session['user_logged_in'] = True
            session['login_date'] = datetime.now().strftime('%Y-%m-%d')
            flash('¡Inicio de sesión exitoso!', 'success')
            next_url = request.args.get('next')
            return redirect(next_url or url_for('boletas'))
        else:
            flash('Contraseña incorrecta. Inténtalo de nuevo.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    [session.pop(key, None) for key in ['user_logged_in', 'admin_logged_in', 'login_date']]
    flash('Has cerrado sesión.', 'info')
    return redirect(url_for('home'))

# --- Panel de Administración ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form.get('password')
        admin_password = database.get_config('ADMIN_PASSWORD', 'Cris123')
        if password == admin_password:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_panel'))
        else:
            flash('Contraseña de administrador incorrecta.', 'error')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    flash('Has cerrado la sesión de administrador.', 'info')
    return redirect(url_for('home'))

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    if request.method == 'POST':
        new_user_pass = request.form.get('new_user_password')
        new_admin_pass = request.form.get('new_admin_password')

        if new_user_pass:
            database.set_config('USER_PASSWORD', new_user_pass)
            flash('La contraseña de usuario ha sido actualizada.', 'success')
        
        if new_admin_pass:
            database.set_config('ADMIN_PASSWORD', new_admin_pass)
            flash('La contraseña de administrador ha sido actualizada.', 'success')
        return redirect(url_for('admin_panel'))
    return render_template('admin.html')

@app.route('/admin/reset-password-safely')
def reset_admin_password():
    """Ruta de emergencia para restablecer la contraseña de administrador."""
    database.set_config('ADMIN_PASSWORD', 'Cris123')
    flash('La contraseña de administrador ha sido restablecida a "Cris123".', 'success')
    return redirect(url_for('admin_login'))

# ------------------- PÁGINAS BASE -------------------
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/boletas")
@login_required
def boletas():
    pagina = int(request.args.get("page", 1))
    limite = 20
    offset = (pagina - 1) * limite

    cliente = (request.args.get("cliente") or "").strip() or None
    fecha_desde = request.args.get("desde") or None
    fecha_hasta = request.args.get("hasta") or None

    filas, total_registros = database.obtener_boletas_paginado(
        limit=limite, offset=offset, cliente=cliente,
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
    )
    total_paginas = max(1, (total_registros + limite - 1) // limite)
    # El total del período ahora se calcula sobre la tabla 'boleta'
    total_periodo = database.total_periodo(cliente=cliente, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)

    return render_template(
        "boletas.html", filas=filas, pagina=pagina, total_paginas=total_paginas,
        total_periodo=total_periodo,
        filtros={"cliente": cliente or "", "desde": fecha_desde or "", "hasta": fecha_hasta or ""},
    )

@app.route("/export.csv")
@login_required
def export_csv():
    POTENTIALLY_DANGEROUS = ("=", "+", "-", "@")

    def sanitize_cell(s):
        s = str(s or "")
        return ("'" + s) if (s and s[0] in POTENTIALLY_DANGEROUS) else s

    import csv, io
    # Exportar desde la nueva tabla de boletas
    filas = database.obtener_boletas_todas() 

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, delimiter=';')

    writer.writerow([
        # Info de la Boleta
        "Boleta_ID", "Fecha_Emision", "Cliente", "Telefono", "Direccion", 
        "Metodo_Pago_Boleta", "Estado_Boleta", "Total_Boleta", "A_Cuenta_Boleta", "Saldo_Boleta", "Notas_Boleta",
        # Info del Item
        "Item_ID", "Item_Descripcion", "Item_Tipo", "Item_Cantidad_Unidades", "Item_Cantidad_Kilos", 
        "Item_Servicio", "Item_Precio_Unitario", "Item_Importe"
    ])

    for boleta_header in filas:
        # Por cada boleta, obtener sus items
        _, items = database.obtener_boleta_detalle(boleta_header['id'])
        for item in items:
            writer.writerow([
                # Datos de la boleta (se repiten por cada item)
                boleta_header['id'], boleta_header['fecha'], sanitize_cell(boleta_header['cliente']), 
                sanitize_cell(boleta_header['telefono']), sanitize_cell(boleta_header['direccion']),
                boleta_header['metodo_pago'], boleta_header['estado'], boleta_header['total'], 
                boleta_header['a_cuenta'], boleta_header['saldo'], sanitize_cell(boleta_header['notas']),
                # Datos del item
                item['id'], sanitize_cell(item['descripcion']), item['tipo'],
                item['prendas'], item['kilos'], item['lavado'],
                item['p_unit'], item['importe']
            ])

    filename = f"boletas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output.getvalue(), mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# ------------------- NUEVO: BOLETA MULTI-ITEM -------------------
def _normalize_phone(raw: str|None) -> str|None:
    if not raw: return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits: return None
    if not digits.startswith("51"):
        digits = "51" + digits.lstrip("0")
    return digits

@app.route("/boleta/nueva", methods=["GET", "POST"])
def boleta_nueva():
    if request.method == "POST":
        try:
            # Cabecera
            cliente = (request.form.get("cliente") or "").strip()
            direccion = (request.form.get("direccion") or "").strip()
            telefono = (request.form.get("telefono") or "").strip()
            entrega_fecha = request.form.get("entrega_fecha") or ""
            entrega_hora = request.form.get("entrega_hora") or ""
            metodo_pago = request.form.get("metodo_pago") or "efectivo"
            a_cuenta = to_float(request.form.get("a_cuenta"), 0.0)
            notas = (request.form.get("notas") or "").strip()

            if not cliente:
                flash("El nombre del cliente es obligatorio", "error")
                return render_template("boleta_nueva.html")

            # Items (listas)
            tipos = request.form.getlist("item_tipo[]")
            descs = request.form.getlist("item_desc[]")
            cantidades_list = request.form.getlist("item_cantidad[]")
            servicios_list = request.form.getlist("item_servicio[]")
            punits_list = request.form.getlist("item_punit[]")

            items, total = [], 0.0
            for tipo, desc, cantidad_str, servicio, punit_str in zip_longest(
                tipos, descs, cantidades_list, servicios_list, punits_list, fillvalue=""
            ):
                tipo = (tipo or "otro").strip()
                desc = (desc or tipo.capitalize()).strip()
                cantidad = to_float(cantidad_str, 0.0)
                p_unit = to_float(punit_str, 0.0)
                servicio = (servicio or "normal").strip()

                # Saltar filas vacías
                if not desc and p_unit == 0 and cantidad == 0:
                    continue

                # Importe
                importe = round(cantidad * p_unit, 2)
                
                prendas = to_int(cantidad) if tipo == 'unidad' else 0
                kilos = cantidad if tipo == 'kilogramo' else 0

                total += importe
                items.append(dict( # El campo 'servicio' ahora se llama 'lavado' en la BD
                    descripcion=desc, tipo=tipo, prendas=prendas, kilos=kilos,
                    lavado=servicio, secado=None, p_unit=p_unit, importe=importe
                ))

            if not items:
                flash("Agrega al menos un ítem con cantidad/precio.", "error")
                return render_template("boleta_nueva.html")

            saldo = round(total - a_cuenta, 2)
            fecha_emision = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cabecera = dict(
                numero=None, cliente=cliente, direccion=direccion, telefono=telefono,
                fecha=fecha_emision, entrega_fecha=entrega_fecha, entrega_hora=entrega_hora,
                metodo_pago=metodo_pago, estado="registrado",
                a_cuenta=a_cuenta, saldo=saldo, total=round(total, 2), notas=notas
            )

            # Guardar en nuevo esquema (cabecera + items)
            boleta_id = database.insertar_boleta_compuesta(cabecera, items)

            # WhatsApp: al cliente si escribió teléfono, si no al número del negocio
            wa_destino = _normalize_phone(telefono) or WHATSAPP_NUMBER
            msg = (
                f"Hola {cliente}, gracias por elegir Lavandería RÍOS.%0A"
                f"Total: S/ {total:.2f}. A cuenta: S/ {a_cuenta:.2f}. Saldo: S/ {saldo:.2f}.%0A"
                f"Entrega: {entrega_fecha or '-'} {entrega_hora or ''}.%0A"
                f"Dirección: {(direccion or LAVA_DIRECCION)}.%0A"
                f"Detalle:%0A" + "%0A".join([f"• {it['descripcion']} — S/ {it['importe']:.2f}" for it in items])
            )
            wa_link = f"https://wa.me/{wa_destino}?text={quote(msg)}"

            flash("Boleta creada con éxito", "success")
            return redirect(url_for("boleta_detalle", boleta_id=boleta_id, wa=wa_link))

        except Exception as e:
            flash(f"Ocurrió un error: {e}", "error")
            return render_template("boleta_nueva.html")

    # GET
    return render_template("boleta_nueva.html")

@app.route("/boleta/<int:boleta_id>")
@login_required
def boleta_detalle(boleta_id):
    try:
        # Obtener la cabecera y los items de la boleta
        cab, items = database.obtener_boleta_detalle(boleta_id)
        
        if not cab:
            flash("Boleta no encontrada", "error")
            return redirect(url_for("boletas"))
        
        # Generar el enlace para WhatsApp con los datos de la boleta
        wa_link = request.args.get("wa")  # opcional, pasa por query string
        return render_template("boleta_detalle.html", cab=cab, items=items, wa_link=wa_link)
    except Exception as e:
        flash(f"Error al cargar la boleta: {e}", "error")
        return redirect(url_for("boletas"))

@app.route("/boleta/eliminar/<int:boleta_id>", methods=["POST"])
@admin_required
def eliminar_boleta(boleta_id):
    try:
        database.eliminar_boleta(boleta_id)
        flash(f"Boleta #{boleta_id} eliminada correctamente.", "success")
    except Exception as e:
        flash(f"Error al eliminar la boleta: {e}", "error")
    return redirect(url_for("boletas"))

@app.route("/boleta/cambiar-estado/<int:boleta_id>", methods=["POST"])
@admin_required
def cambiar_estado_boleta(boleta_id):
    try:
        cab, _ = database.obtener_boleta_detalle(boleta_id)
        if not cab:
            flash("Boleta no encontrada.", "error")
            return redirect(url_for("boletas"))
        
        nuevo_estado = "entregado" if cab['estado'] != 'entregado' else "registrado"
        database.actualizar_estado_boleta(boleta_id, nuevo_estado)
        flash(f"Estado de la boleta #{boleta_id} actualizado a '{nuevo_estado.upper()}'.", "success")
    except Exception as e:
        flash(f"Error al actualizar el estado: {e}", "error")
    return redirect(url_for("boletas"))

if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    app.run(debug=debug)