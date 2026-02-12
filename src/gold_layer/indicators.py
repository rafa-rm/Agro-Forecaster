import pandas as pd
import numpy as np

def get_rsi(series, period=14):
    """
    Calculates RSI using Wilder's Smoothing.
    Returns a pd.Series aligned with the input index.
    """
    delta = series.diff()
    
    # Separate gains/losses
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)

    # Wilder's Smoothing
    ema_up = up.ewm(com=period - 1, adjust=False).mean()
    ema_down = down.ewm(com=period - 1, adjust=False).mean()
    
    rs = ema_up / ema_down
    rsi = 100 - (100 / (1 + rs))
    
    return rsi
