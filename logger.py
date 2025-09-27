import json
import csv
import os
from datetime import datetime

LOG_ESTADO_PATH = "data/log_estado.json"
LOG_HISTORICO_PATH = "data/log_historico.csv"

def guardar_estado_vivo(contexto):
    with open(LOG_ESTADO_PATH, "w") as f:
        json.dump(contexto, f, indent=2, default=str)

def guardar_historico(contexto):
    existe = os.path.exists(LOG_HISTORICO_PATH)
    with open(LOG_HISTORICO_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        if not existe:
            # header
            writer.writerow([
                "timestamp","signal","last_price","position_qty","position_avg","fees",
                "open_orders","take_profits","stop_loss","bot_version","symbol"
            ])
        writer.writerow([
            contexto["timestamp"],
            contexto.get("signal"),
            contexto.get("last_price"),
            contexto.get("position", {}).get("qty"),
            contexto.get("position", {}).get("avg"),
            contexto.get("position", {}).get("fees"),
            json.dumps(contexto.get("open_orders", [])),
            json.dumps(contexto.get("take_profits", [])),
            contexto.get("stop_loss", {}).get("price"),
            contexto.get("bot_version", "v1"),
            contexto.get("symbol", "ETHUSDT"),
        ])
