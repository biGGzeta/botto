import csv
from datetime import datetime

DATA_FILE = "botto_ml_data.csv"

def log_ciclo_ml(ciclo_data):
    fieldnames = [
        "timestamp_start", "timestamp_end", "precio_entrada", "precio_salida",
        "spacing_grid", "rango_grid", "num_fills", "qty_total", "pnl", "drawdown_max",
        "tipo_senal", "volatilidad", "tiempo_duracion", "hit_stop_loss", "hit_take_profit",
        "comision_total", "balance_final"
    ]
    with open(DATA_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if f.tell() == 0:
            writer.writeheader()
        writer.writerow(ciclo_data)