import requests
import json
import time
from datetime import datetime, timezone, timedelta

# import ssl
import websocket
import urllib3
import threading
import queue
import math
import os
import argparse

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
from dotenv import load_dotenv
from py_clob_client.constants import AMOY

from py_clob_client.order_builder.constants import BUY

from datetime import datetime
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


class Tee:
    def __init__(self, filename):
        self.file = open(filename, "a", encoding="utf-8", buffering=1)
        self.stdout = sys.stdout

    def write(self, message):
        # if message.strip():
        #     message = f"[{datetime.now()}] {message}"
        self.stdout.write(message)
        self.file.write(message)

    def flush(self):
        self.stdout.flush()
        self.file.flush()


sys.stdout = Tee("bot_log.txt")

load_dotenv()
host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
key = os.getenv("PRIVATE_KEY")
creds = ApiCreds(
    api_key=os.getenv("CLOB_API_KEY"),
    api_secret=os.getenv("CLOB_SECRET"),
    api_passphrase=os.getenv("CLOB_PASS_PHRASE"),
)
signature_type = 2
funder = os.getenv("FUNDER_ADDRESS")
chain_id = int(os.getenv("CHAIN_ID", AMOY))
client = ClobClient(
    host,
    key=key,
    chain_id=chain_id,
    creds=creds,
    signature_type=signature_type,
    funder=funder,
)


order_queue = queue.LifoQueue()

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── DATABASE ────────────────────────────────────────────────────────────────


# ─── HTTP HELPER ─────────────────────────────────────────────────────────────


def make_request_with_fallback(url, timeout=30):
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        print("✅ Request successful with SSL verification")
        return response.json()
    except requests.exceptions.SSLError:
        print("⚠️ SSL Error, falling back to verify=False...")
    except Exception as e:
        print(f"❌ Request failed: {type(e).__name__}: {e}, trying verify=False...")

    response = requests.get(url, timeout=timeout, verify=False)
    response.raise_for_status()
    print("✅ Request successful with verify=False")
    return response.json()


# ─── ORDER WORKER ────────────────────────────────────────────────────────────

placed_order = threading.Event()
bet_up = threading.Event()
bet_down = threading.Event()

signal_lock = threading.Lock()


def order_worker():
    print("started order worker")
    while True:
        global buy_price
        while not placed_order.is_set():
            try:
                item = order_queue.get()
            except Exception as e:
                print(f"Error getting item from queue: {e}")
                continue
            # {"id": id_one, "price": major_side, "side": "UP"}
            asset_id = item.get("id")

            price = item.get("price")
            price = math.floor(price * 100) / 100
            side = item.get("side")
            amount = price * 2
            amount = math.floor(amount * 100) / 100
            print("ammount", amount)
            print("price", price)
            print(asset_id, price, side)

            if side == "UP":
                signed_order = client.create_market_order(
                    token_id=asset_id,
                    side=BUY,
                    amount=amount,
                    price=price,
                )
                try:
                    resp = client.post_order(signed_order, OrderType.FOK)
                    print(resp)
                    if resp.get("success") == True:
                        placed_order.set()
                        bet_up.set()

                        buy_price = price
                        print("placed order from thread", price, side)

                except Exception as e:
                    print("excepion 5", e)
                    continue

            if side == "DOWN":
                signed_order = client.create_market_order(
                    token_id=asset_id,
                    price=price,
                    amount=amount,
                    side=BUY,
                )
                try:
                    resp = client.post_order(signed_order, OrderType.FOK)
                    print(resp)
                    if resp.get("success") == True:
                        placed_order.set()
                        bet_down.set()

                        buy_price = price

                        print("placed order from thread", price, side)

                except Exception as e:
                    print("excepion 5", e)
                    continue
            time.sleep(0.2)


def bot():
    global initial_slug, buy_price
    url = f"https://gamma-api.polymarket.com/markets?slug={initial_slug}"
    try:
        response = make_request_with_fallback(url)
        response = response[0]
    except Exception as e:
        print(f"Failed to fetch market data: {e}")
        # initial_slug = new_slug
        time.sleep(2)
    ids = response.get("clobTokenIds").split(",")
    up_id = ids[0][2:-1]
    down_id = ids[1][2:-2]
    TARGET_ASSETS = [up_id, down_id]
    # print(TARGET_ASSETS)

    endtime = response.get("endDate")
    target_time = datetime.fromisoformat(endtime.replace("Z", "+00:00"))
    if datetime.now(timezone.utc) >= target_time:
        print(f"⏩ Market {initial_slug} already expired, skipping...")
        return

    ws_url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    def subscribe(ws):
        print("✅ WebSocket connected successfully!")
        subscribe_msg = {
            "assets_ids": TARGET_ASSETS,
            "type": "market",
            "custom_feature_enabled": True,
        }
        ws.send(json.dumps(subscribe_msg))
        print("✅ Subscription sent")

    def on_open(ws):
        print("Websocket opened successfully!")
        if datetime.now(timezone.utc) >= target_time:
            print("Market ended 2 ....")
            ws.close()
            return
        subscribe(ws)
        time.sleep(1)

    def on_reconnect(ws):
        print("Reconnected")
        time.sleep(1)
        subscribe(ws)

    def on_pong(ws, message):
        pass
        # print("Pong recieved =", message)

    def on_message(ws, message):

        ws_data = json.loads(message)
        try:
            event_type = ws_data.get("event_type")

            if datetime.now(timezone.utc) >= target_time:
                print("Market ended 1 ....")
                ws.close()

            if event_type != "price_change":
                return

            price_changes = ws_data.get("price_changes")
            if not price_changes or len(price_changes) < 2:
                return

            id_one = price_changes[0].get("asset_id")
            best_ask_one = float(price_changes[0].get("best_ask"))
            id_two = price_changes[1].get("asset_id")
            best_ask_two = float(price_changes[1].get("best_ask"))

            # major side 0.80–0.85
            if 0.98 == best_ask_one:
                if id_one == up_id:
                    if not bet_up.is_set() and not bet_down.is_set():
                        major_side = best_ask_one
                        major_side = math.floor(major_side * 100) / 100
                        # print(
                        #     "up goes above 80 placing order for up.. 1 ---->",
                        #     major_side,
                        # )
                        with signal_lock:
                            if not placed_order.is_set():
                                order_queue.put(
                                    {
                                        "id": id_one,
                                        "price": major_side,
                                        "side": "UP",
                                    }
                                )

                else:
                    if not bet_down.is_set() and not bet_up.is_set():
                        major_side = best_ask_one
                        major_side = math.floor(major_side * 100) / 100

                        # print(
                        #     "down goes above 80 placing order for down.. 2---->",
                        #     major_side,
                        # )
                        with signal_lock:
                            if not placed_order.is_set():
                                order_queue.put(
                                    {
                                        "id": id_one,
                                        "price": major_side,
                                        "side": "DOWN",
                                    }
                                )
                        # bet_for_down = True

            if 0.98 == best_ask_two:
                if id_two == up_id:
                    if not bet_up.is_set() and not bet_down.is_set():
                        major_side = best_ask_two
                        major_side = math.floor(major_side * 100) / 100

                        # print(
                        #     "up goes above 80 placing order for up.. 3 ----->",
                        #     major_side,
                        # )
                        with signal_lock:
                            if not placed_order.is_set():
                                order_queue.put(
                                    {
                                        "id": id_two,
                                        "price": major_side,
                                        "side": "UP",
                                    }
                                )

                else:
                    if not bet_down.is_set() and not bet_up.is_set():
                        major_side = best_ask_two
                        major_side = math.floor(major_side * 100) / 100
                        # print(
                        #     "down goes above 80 placing order for down... 4---->",
                        #     major_side,
                        # )
                        with signal_lock:
                            if not placed_order.is_set():
                                order_queue.put(
                                    {
                                        "id": id_two,
                                        "price": major_side,
                                        "side": "DOWN",
                                    }
                                )
                        # bet_for_down = True

        except Exception as e:
            pass

    def on_error(ws, error):
        print(f"❌ WebSocket error: {error}")

        print("Socket connected: 1", ws.sock and ws.sock.connected)
        if ws.sock and ws.sock.connected:
            try:
                print("⚠️ Old socket still alive, closing it...")
                ws.sock.close()
                ws.sock = None
            except Exception as e:
                print(f"Error closing old socket: {e}")
        print("Socket connected 2:", ws.sock and ws.sock.connected)

    def on_close(ws, code, msg):
        print(f"WebSocket closed: {code} - {msg}")
        try:
            ws.sock.close()
        except Exception as e:
            print("excepion 4", e)

    # ── connect ───────────────────────────────────────────────────────

    ws = websocket.WebSocketApp(
        ws_url,
        on_open=on_open,
        on_pong=on_pong,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_reconnect=on_reconnect,
    )

    try:
        ws.run_forever(ping_interval=10, ping_payload="PING", reconnect=3)
    except Exception as e:
        print("excepion3 =", e)
    finally:
        if ws.sock:
            ws.sock.close()

    print(f"✅ Market cycle complete for {initial_slug}")

    if bet_down.is_set() or bet_up.is_set():
        print(f"✅✅✅ TRADE SUCCESSFUL!")
        print(
            f"   Major: {buy_price:.3f}           Side:{'UP' if bet_up.is_set() else 'DOWN' if bet_down.is_set() else None}"
        )

    elif not bet_down.is_set() and not bet_up.is_set():
        print("✅✅✅ TRADE SKIPPED! No loss for this market!")
    print("size of queue", order_queue.qsize())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="pol trading bot")
    parser.add_argument(
        "--slug",
        type=str,
        required=True,
        help="market slug to trade, e.g. btc-updown-5m-1773685200",
    )
    args = parser.parse_args()
    initial_slug = args.slug

    buy_price = 0.0
    threading.Thread(target=order_worker, daemon=True).start()
    print("PID:", os.getpid())
    try:
        bot()
    except KeyboardInterrupt:
        print(f"\n{'='*60}")
        print(f"📊 SESSION SUMMARY")
        print(f"{'='*60}")
