from auth import get_client
from datetime import datetime, timedelta

c = get_client()
r = c.get_option_chain(
    symbol="NVDA",
    contract_type=c.Options.ContractType.PUT,
    strike_count=5,
    from_date=datetime.now().date() + timedelta(days=30),
    to_date=datetime.now().date() + timedelta(days=40),
)
r.raise_for_status()
d = r.json()
print(f"NVDA: ${d.get('underlyingPrice', 0):.2f}")
print()
for exp, sd in d.get("putExpDateMap", {}).items():
    for sk, cl in sd.items():
        for x in cl:
            if 155 <= x["strikePrice"] <= 165:
                bid = x["bid"]
                ask = x["ask"]
                mid = (bid + ask) / 2
                print(f"  ${x['strikePrice']:.0f} put  Bid: ${bid:.2f}  Ask: ${ask:.2f}  Mid: ${mid:.2f}")
