from decimal import Decimal, ROUND_HALF_UP 
import config_precios as cfg


def _money(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calcular_precio(tipo_item, kilos, cantidad, servicio, perfumado):
    subtotal = Decimal("0.00")

    if tipo_item == "kilos":
        subtotal = _money(Decimal(kilos) * Decimal(cfg.PRECIO_KILO))
    elif tipo_item == "edredon":
        subtotal = _money(Decimal(cantidad) * Decimal(cfg.PRECIO_EDREDON))
    elif tipo_item == "terno":
        subtotal = _money(Decimal(cantidad) * Decimal(cfg.PRECIO_TERNO))

    # Recargos opcionales por servicio
    subtotal += _money(cfg.RECARGO_SERVICIO.get(servicio, 0))
    if perfumado:
        subtotal += _money(cfg.RECARGO_PERFUMADO)

    return float(subtotal)
