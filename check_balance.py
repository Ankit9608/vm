import requests
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON
import os
from dotenv import load_dotenv

load_dotenv()
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
HOST = "https://clob.polymarket.com"


def check_polymarket_balance():
    # Initialize client with your EOA (funder/signer wallet)
    client = ClobClient(host=HOST, key=PRIVATE_KEY, chain_id=POLYGON)

    eoa_address = client.get_address()
    print(f"EOA (Funder) Wallet: {eoa_address}")

    # ---- Step 1: Get your Proxy Wallet address ----
    try:
        proxy_address = client.get_proxy_wallet_address()
        print(f"Proxy Wallet Address: {proxy_address}")
    except Exception as e:
        print(f"Could not fetch proxy wallet via SDK: {e}")
        # Fallback: fetch proxy wallet from Polymarket API directly
        resp = requests.get(
            "https://data-api.polymarket.com/profile",
            params={"address": eoa_address.lower()},
        )
        if resp.status_code == 200:
            data = resp.json()
            proxy_address = data.get("proxyWallet") or data.get("proxy_wallet")
            print(f"Proxy Wallet Address (API): {proxy_address}")
        else:
            print(f"Error fetching profile: {resp.text}")
            return

    # ---- Step 2: Check USDC balance of proxy wallet on-chain ----
    USDC_CONTRACT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e on Polygon
    POLYGONSCAN_API_KEY = os.getenv("CLOB_API_KEY")

    url = (
        f"https://api.polygonscan.com/api"
        f"?module=account&action=tokenbalance"
        f"&contractaddress={USDC_CONTRACT}"
        f"&address={proxy_address}"
        f"&tag=latest"
        f"&apikey={POLYGONSCAN_API_KEY}"
    )
    res = requests.get(url)
    if res.status_code == 200:
        raw = int(res.json().get("result", 0))
        usdc_balance = raw / 1e6
        print(f"Proxy Wallet USDC Balance: ${usdc_balance:.2f}")

    # ---- Step 3: Check allowance approved to CTF Exchange ----
    # This shows how much USDC the proxy has approved for trading
    CTF_EXCHANGE = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
    allowance_url = (
        f"https://api.polygonscan.com/api"
        f"?module=account&action=tokenbalance"
        f"&contractaddress={USDC_CONTRACT}"
        f"&address={CTF_EXCHANGE}"
        f"&tag=latest"
        f"&apikey={POLYGONSCAN_API_KEY}"
    )

    # ---- Step 4: Polymarket internal balance (available to trade) ----
    clob_resp = requests.get(f"{HOST}/balance", params={"address": proxy_address})
    if clob_resp.status_code == 200:
        print(f"Tradeable Balance (CLOB): {clob_resp.json()}")
    else:
        print(f"CLOB balance error: {clob_resp.status_code} - {clob_resp.text}")

    # ---- Step 5: Open positions / shares ----
    try:
        api_creds = client.create_or_derive_api_creds()
        client.set_api_creds(api_creds)
        orders = client.get_orders()
        print(f"\nOpen Orders: {len(orders)}")
        for o in orders:
            print(
                f"  - Market: {o.get('market')} | Side: {o.get('side')} | Size: {o.get('size_matched')}"
            )
    except Exception as e:
        print(f"Could not fetch open orders: {e}")


if __name__ == "__main__":
    check_polymarket_balance()
