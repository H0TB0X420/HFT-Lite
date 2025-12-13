"""
IBKR ForecastEx Contract Lookup

Usage:
    python ibkr_lookup.py --conid 733131966              # Lookup by conId
    python ibkr_lookup.py --search "Fed Funds"           # Search by name
    python ibkr_lookup.py --forecastex FF                # List ForecastEx contracts for symbol
"""
import argparse
from ib_insync import IB, Contract


def lookup_by_conid(ib: IB, con_id: int):
    """Get details for a specific conId."""
    print(f"\nLooking up conId: {con_id}\n")
    
    contract = Contract(conId=con_id, exchange="FORECASTX")
    ib.qualifyContracts(contract)
    
    details = ib.reqContractDetails(contract)
    
    if not details:
        print("No contract found.")
        return
    
    d = details[0]
    c = d.contract
    if c:
        print(f"conId:         {c.conId}")
        print(f"Symbol:        {c.symbol}")
        print(f"Local Symbol:  {c.localSymbol}")
        print(f"Sec Type:      {c.secType}")
        print(f"Exchange:      {c.exchange}")
        print(f"Right:         {c.right} ({'YES' if c.right == 'C' else 'NO'})")
        print(f"Strike:        {c.strike}")
        print(f"Expiry:        {c.lastTradeDateOrContractMonth}")
        print(f"Description:   {d.longName}")


def search_by_name(ib: IB, name: str):
    """Search ForecastEx contracts by name."""
    print(f"\nSearching for: {name}\n")
    
    matches = ib.reqMatchingSymbols(name)
    
    if not matches:
        print("No matches found.")
        return
    
    # Filter for FORECASTX
    for m in matches[:20]:
        c = m.contract
        if c and "FORECASTX" in str(getattr(m, 'description', '')):
            desc = getattr(m, 'description', '') or ''
            print(f"conId: {c.conId:>12} | {c.symbol:>10} | {desc}")


def lookup_forecastex(ib: IB, symbol: str):
    """List ForecastEx contracts for a symbol (e.g., FF, HORC)."""
    print(f"\nSearching ForecastEx contracts for: {symbol}\n")
    
    contract = Contract()
    contract.symbol = symbol.upper()
    contract.secType = "OPT"
    contract.exchange = "FORECASTX"
    contract.currency = "USD"
    
    details = ib.reqContractDetails(contract)
    
    if not details:
        print(f"No contracts found for {symbol} on FORECASTX")
        return
    
    print(f"Found {len(details)} contracts:\n")
    for d in details[:30]:
        c = d.contract
        if c:
            right = "YES" if c.right == "C" else "NO"
            print(f"conId: {c.conId:>12} | {c.localSymbol:>25} | {right:>3} | strike={c.strike}")


def main():
    parser = argparse.ArgumentParser(description="IBKR ForecastEx Contract Lookup")
    parser.add_argument("--conid", type=int, help="Lookup specific conId")
    parser.add_argument("--search", type=str, help="Search by name/description")
    parser.add_argument("--forecastex", type=str, help="List ForecastEx contracts for symbol (FF, HORC, etc)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4001)
    parser.add_argument("--client-id", type=int, default=99)
    
    args = parser.parse_args()
    
    if not any([args.conid, args.search, args.forecastex]):
        parser.print_help()
        return
    
    ib = IB()
    
    try:
        print(f"Connecting to {args.host}:{args.port}...")
        ib.connect(args.host, args.port, clientId=args.client_id)
        print("Connected.")
        
        if args.conid:
            lookup_by_conid(ib, args.conid)
        elif args.search:
            search_by_name(ib, args.search)
        elif args.forecastex:
            lookup_forecastex(ib, args.forecastex)
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if ib.isConnected():
            ib.disconnect()
            print("\nDisconnected.")


if __name__ == "__main__":
    main()