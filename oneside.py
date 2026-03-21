# buy only major side when it goes above 90
import requests
import json
import time
from datetime import datetime, timezone, timedelta
import argparse

# import ssl
import websocket
import urllib3
import threading
import queue
import math
import os

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType, MarketOrderArgs
from dotenv import load_dotenv
from py_clob_client.constants import AMOY

from py_clob_client.order_builder.constants import BUY

from datetime import datetime
import sys
from web3 import Web3
from py_builder_relayer_client.client import RelayClient
from py_builder_relayer_client.models import OperationType, SafeTransaction
from py_builder_signing_sdk.config import BuilderConfig
from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds


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

# ----------------------------setup for redeem
builder_config = BuilderConfig(
    local_builder_creds=BuilderApiKeyCreds(
        key=os.getenv("POLY_BUILDER_API_KEY"),
        secret=os.getenv("POLY_BUILDER_SECRET"),
        passphrase=os.getenv("POLY_BUILDER_PASSPHRASE"),
    )
)

client2 = RelayClient("https://relayer-v2.polymarket.com", 137, key, builder_config)
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
parent_collection_id = b"\x00" * 32
collateral_token = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
index_sets = [1, 2]


order_queue = queue.LifoQueue()
redeem_queue = queue.Queue()

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
            # print(asset_id, price, side)

            if side == "UP":
                order_args1 = MarketOrderArgs(
                    token_id=asset_id, side=BUY, amount=amount, price=price
                )
                signed_order1 = client.create_market_order(order_args1)
                try:
                    resp = client.post_order(signed_order1, OrderType.FOK)

                    if resp.get("success") == True:
                        print(resp)
                        buy_price = price
                        placed_order.set()
                        bet_up.set()

                        min, sec = get_time_left()
                        print(
                            "placed order",
                            asset_id,
                            price,
                            side,
                            "| time left:",
                            f"{min}m {sec}s",
                        )

                except Exception as e:
                    print("excepion 5", e)

            if side == "DOWN":
                order_args2 = MarketOrderArgs(
                    token_id=asset_id, side=BUY, amount=amount, price=price
                )
                signed_order2 = client.create_market_order(order_args2)
                try:
                    resp = client.post_order(signed_order2, OrderType.FOK)
                    if resp.get("success") == True:
                        print(resp)
                        placed_order.set()
                        bet_down.set()
                        buy_price = price
                        min, sec = get_time_left()
                        print(
                            "placed order",
                            asset_id,
                            price,
                            side,
                            "| time left:",
                            f"{min}m {sec}s",
                        )
                except Exception as e:
                    print("excepion 5", e)


# ─── BOT ─────────────────────────────────────────────────────────────────────
def get_time_left():
    global target_time
    if not target_time:
        return -1, -1
    now = datetime.now(timezone.utc)
    diff = target_time - now
    seconds = int(diff.total_seconds())
    if seconds < 0:
        return 0, 0
    mins = seconds // 60
    secs = seconds % 60
    # return f"{mins}m {secs}s"
    return mins, secs


def bot():
    global initial_slug, buy_price, to_redeem

    while True:
        print("started for", initial_slug)

        # ── slug calculation ──────────────────────────────────────────────
        str_list = initial_slug.split("-")
        timestamp = str_list[-1]
        str_list.remove(timestamp)
        new_timestamp = int(timestamp) + 300
        new_slug = "-".join(str_list) + f"-{new_timestamp}"

        # ── fetch market data ─────────────────────────────────────────────
        url = f"https://gamma-api.polymarket.com/markets?slug={initial_slug}"
        try:
            response = make_request_with_fallback(url)
            response = response[0]
        except Exception as e:
            print(f"Failed to fetch market data: {e}")
            # initial_slug = new_slug
            time.sleep(2)
            continue

        ids = response.get("clobTokenIds").split(",")
        condition_id = response.get("conditionId")
        up_id = ids[0][2:-1]
        down_id = ids[1][2:-2]
        TARGET_ASSETS = [up_id, down_id]
        # print(TARGET_ASSETS)

        endtime = response.get("endDate")
        global target_time
        target_time = datetime.fromisoformat(endtime.replace("Z", "+00:00"))
        # FIX: skip already-expired markets immediately, don't bother connecting
        if datetime.now(timezone.utc) >= target_time:
            print(f"⏩ Market {initial_slug} already expired, skipping...")
            initial_slug = new_slug
            continue

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
            min, sec = get_time_left()
            if min > 0 or sec > 15:
                return
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
                if best_ask_one == 0.98:
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

                if best_ask_two == 0.98:
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
            to_redeem += 1
            redeem_queue.put(condition_id)

        elif not bet_down.is_set() and not bet_up.is_set():
            print("✅✅✅ TRADE SKIPPED! No loss for this market!")

        print("-" * 60)
        bet_up.clear()
        bet_down.clear()

        buy_price = 0.0
        time1 = time.time()
        print("size of queue", order_queue.qsize())
        while True:
            try:
                order_queue.get_nowait()
            except queue.Empty:
                break
        time2 = time.time()
        print("time required to clear queue", time2 - time1)

        print("Stack cleared", order_queue.empty())
        with signal_lock:
            placed_order.clear()
        time.sleep(5)

        if to_redeem % 4 == 0:
            condition_id = redeem_queue.get()
            redeem_tx = SafeTransaction(
                to=CTF,
                operation=OperationType.Call,
                data=Web3()
                .eth.contract(
                    address=CTF,
                    abi=[
                        {
                            "name": "redeemPositions",
                            "type": "function",
                            "inputs": [
                                {"name": "collateralToken", "type": "address"},
                                {"name": "parentCollectionId", "type": "bytes32"},
                                {"name": "conditionId", "type": "bytes32"},
                                {"name": "indexSets", "type": "uint256[]"},
                            ],
                            "outputs": [],
                        }
                    ],
                )
                .encode_abi(
                    abi_element_identifier="redeemPositions",
                    args=[
                        collateral_token,
                        parent_collection_id,
                        condition_id,
                        index_sets,
                    ],
                ),
                value="0",
            )

            response = client2.execute([redeem_tx], "Redeem positions")
            response.wait()
            print(type(response))
            print(response)

        print("switched new slug")
        initial_slug = new_slug  # advance only after intentional close


# ─── MAIN ────────────────────────────────────────────────────────────────────

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
    target_time = None
    to_redeem = 0
    threading.Thread(target=order_worker, daemon=True).start()
    print("PID:", os.getpid())
    try:
        bot()
    except KeyboardInterrupt:
        print(f"\n{'='*60}")
        print(f"📊 SESSION SUMMARY")
        print(f"{'='*60}")
