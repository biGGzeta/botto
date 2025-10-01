import pandas as pd
import json
import ast
from datetime import datetime
from collections import Counter

# Configuración de paths
CSV_PATH = "data/log_historico.csv"
OUT_PATH = "data/botto_ml_features.csv"

def safe_json_load(s):
    try:
        # Corrige comillas dobles y formato dict
        if isinstance(s, str):
            s = s.replace('""', '"').replace("'", '"')
            return json.loads(s)
        return s
    except Exception:
        try:
            return ast.literal_eval(s)
        except Exception:
            return []

def extract_features(row):
    features = {}
    # Parse timestamp
    try:
        features["timestamp"] = pd.to_datetime(row["timestamp"])
    except Exception:
        features["timestamp"] = row["timestamp"]
    
    # Signal
    sig = row["signal"]
    if isinstance(sig, str) and sig.startswith("{"):
        try:
            sig_dict = ast.literal_eval(sig)
            features["signal_tipo"] = sig_dict.get("tipo", "UNKNOWN")
            features["signal_precio"] = float(sig_dict.get("precio", 0))
            features["signal_vol"] = float(sig_dict.get("volumen", 0))
        except Exception:
            features["signal_tipo"] = str(sig)
            features["signal_precio"] = 0
            features["signal_vol"] = 0
    else:
        features["signal_tipo"] = str(sig)
        features["signal_precio"] = 0
        features["signal_vol"] = 0
    
    # Price & Position
    features["last_price"] = float(row.get("last_price", 0))
    features["position_qty"] = float(row.get("position_qty", 0) or 0)
    features["position_avg"] = float(row.get("position_avg", 0) or 0)
    features["fees"] = float(row.get("fees", 0) or 0)
    
    # Open orders
    open_orders = safe_json_load(row.get("open_orders", "[]"))
    features["num_open_orders"] = len(open_orders)
    buy_orders = [o for o in open_orders if o.get("side") == "BUY" and float(o.get("qty", 0)) > 0]
    sell_orders = [o for o in open_orders if o.get("side") == "SELL" and float(o.get("qty", 0)) > 0]
    features["num_buy_orders"] = len(buy_orders)
    features["num_sell_orders"] = len(sell_orders)
    # Buy prices for spacing
    buy_prices = sorted([float(o["price"]) for o in buy_orders if float(o["price"]) > 0])
    if len(buy_prices) > 1:
        spacings = [buy_prices[i+1] - buy_prices[i] for i in range(len(buy_prices)-1)]
        features["buy_spacing_avg"] = sum(spacings)/len(spacings)
        features["buy_spacing_min"] = min(spacings)
        features["buy_spacing_max"] = max(spacings)
    else:
        features["buy_spacing_avg"] = 0
        features["buy_spacing_min"] = 0
        features["buy_spacing_max"] = 0
    # Buy accumulation (same price)
    price_counts = Counter(buy_prices)
    features["num_buy_same_price"] = sum(1 for p in price_counts if price_counts[p] > 1)
    features["buy_vol_total"] = sum(float(o["qty"]) for o in buy_orders)
    features["buy_vol_avg"] = features["buy_vol_total"] / len(buy_orders) if buy_orders else 0

    # TP and SL
    take_profits = safe_json_load(row.get("take_profits", "[]"))
    if take_profits and isinstance(take_profits, list):
        tp = take_profits[-1]
        features["tp_price"] = float(tp.get("price", 0))
        features["tp_qty"] = float(tp.get("qty", 0))
        features["tp_distance"] = features["tp_price"] - features["position_avg"] if features["position_avg"] else 0
    else:
        features["tp_price"] = 0
        features["tp_qty"] = 0
        features["tp_distance"] = 0
    features["sl_price"] = float(row.get("stop_loss", 0) or 0)
    features["sl_distance"] = features["sl_price"] - features["position_avg"] if features["position_avg"] else 0

    # Meta info
    features["bot_version"] = row.get("bot_version", "v1")
    features["symbol"] = row.get("symbol", "ETHUSDT")

    # Secuencia de fills/órdenes abiertas
    features["fills_seq"] = ";".join([f"{o.get('side','')}:{o.get('price','')}:{o.get('qty','')}" for o in open_orders if float(o.get("qty",0))>0])
    return features

# Lee el CSV original
df = pd.read_csv(CSV_PATH)
df.columns = [
    "timestamp","signal","last_price","position_qty","position_avg","fees",
    "open_orders","take_profits","stop_loss","bot_version","symbol"
]

# Extrae features por línea
features_list = [extract_features(row) for _, row in df.iterrows()]
features_df = pd.DataFrame(features_list)

# Volatilidad y drawdown (rolling window de 5 ciclos)
features_df['volatilidad'] = features_df['last_price'].rolling(window=5).std().fillna(0)
features_df['drawdown'] = features_df['position_avg'] - features_df['last_price']
features_df['drawdown_max_5'] = features_df['drawdown'].rolling(window=5).max().fillna(0)

# Sugerencia ML: revisa que no haya NaN, outliers, ni tipos incorrectos antes de entrenar
features_df = features_df.fillna(0)

# Guarda el dataset limpio para ML
features_df.to_csv(OUT_PATH, index=False)
print(f"Dataset limpio para ML guardado en {OUT_PATH}")