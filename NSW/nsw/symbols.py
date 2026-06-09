"""Index symbol map.

Currently only the four indices are supported. Adding more (stocks, futures,
options) is a matter of extending INDEX_SYMBOLS.

The "fyers_symbol" is the exact string Fyers' v3 history endpoint expects.
The "name" is our short alias used in the database and in user-facing code.
"""

from __future__ import annotations

# alias -> Fyers symbol
INDEX_SYMBOLS: dict[str, str] = {
    "NIFTY":      "NSE:NIFTY50-INDEX",
    "BANKNIFTY":  "NSE:NIFTYBANK-INDEX",
    "FINNIFTY":   "NSE:FINNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
}

# Common alternative spellings users might type.
_ALIASES: dict[str, str] = {
    "NIFTY50":      "NIFTY",
    "NIFTY 50":     "NIFTY",
    "NIFTYBANK":    "BANKNIFTY",
    "NIFTY BANK":   "BANKNIFTY",
    "BANK NIFTY":   "BANKNIFTY",
    "FIN NIFTY":    "FINNIFTY",
    "MIDCAPNIFTY":  "MIDCPNIFTY",
    "MIDCPNIFTY50": "MIDCPNIFTY",
}


def resolve(symbol: str) -> str:
    """Return our canonical alias (NIFTY/BANKNIFTY/...) for the given input.

    Accepts either an alias (``"NIFTY"``), a known alternative spelling
    (``"NIFTY 50"``), or a Fyers symbol (``"NSE:NIFTY50-INDEX"``). Raises
    KeyError if the input isn't recognised.
    """
    s = symbol.strip().upper()
    if s in INDEX_SYMBOLS:
        return s
    if s in _ALIASES:
        return _ALIASES[s]
    # reverse lookup: full Fyers symbol -> alias
    for alias, fyers_sym in INDEX_SYMBOLS.items():
        if fyers_sym.upper() == s:
            return alias
    raise KeyError(
        f"Unknown symbol: {symbol!r}. Known aliases: {list(INDEX_SYMBOLS.keys())}"
    )


def fyers_symbol(symbol: str) -> str:
    """Return the Fyers symbol string for a given alias / spelling."""
    return INDEX_SYMBOLS[resolve(symbol)]


def all_aliases() -> list[str]:
    """List of canonical aliases known to NSW."""
    return list(INDEX_SYMBOLS.keys())
