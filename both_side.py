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


sys.stdout = Tee("log_gapfive_stoploss.txt")

# load_dotenv()
# host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
# key = os.getenv("PRIVATE_KEY")
# creds = ApiCreds(
#     api_key=os.getenv("CLOB_API_KEY"),
#     api_secret=os.getenv("CLOB_SECRET"),
#     api_passphrase=os.getenv("CLOB_PASS_PHRASE"),
# )
# signature_type = 2
# funder = os.getenv("FUNDER_ADDRESS")

# chain_id = int(os.getenv("CHAIN_ID", AMOY))
# client = ClobClient(
#     host,
#     key=key,
#     chain_id=chain_id,
#     creds=creds,
#     signature_type=signature_type,
#     funder=funder,
# )

# ----------------------------setup for redeem
# builder_config = BuilderConfig(
#     local_builder_creds=BuilderApiKeyCreds(
#         key=os.getenv("POLY_BUILDER_API_KEY"),
#         secret=os.getenv("POLY_BUILDER_SECRET"),
#         passphrase=os.getenv("POLY_BUILDER_PASSPHRASE"),
#     )
# )

# client2 = RelayClient("https://relayer-v2.polymarket.com", 137, key, builder_config)
# CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
# parent_collection_id = b"\x00" * 32
# collateral_token = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
# index_sets = [1, 2]


# order_queue = queue.LifoQueue()
# redeem_queue = queue.Queue()

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

# placed_order = threading.Event()
# bet_up = threading.Event()
# bet_down = threading.Event()

# signal_lock = threading.Lock()


# def order_worker():
#     print("started order worker")
#     while True:
#         global buy_price
#         if not placed_order.is_set():
#             try:
#                 item = order_queue.get()
#             except Exception as e:
#                 print(f"Error getting item from queue: {e}")
#                 continue
#             # {"id": id_one, "price": major_side, "side": "UP"}
#             asset_id = item.get("id")

#             price = item.get("price")
#             price = math.floor(price * 100) / 100
#             side = item.get("side")
#             amount = price * 2
#             amount = math.floor(amount * 100) / 100
#             # print(asset_id, price, side)

#             if side == "UP":
#                 order_args1 = MarketOrderArgs(
#                     token_id=asset_id, side=BUY, amount=amount, price=price
#                 )
#                 signed_order1 = client.create_market_order(order_args1)
#                 try:
#                     resp = client.post_order(signed_order1, OrderType.FOK)

#                     if resp.get("success") == True:
#                         print(resp)
#                         buy_price = price
#                         placed_order.set()
#                         bet_up.set()

#                         min, sec = get_time_left()
#                         print(
#                             "placed order",
#                             asset_id,
#                             price,
#                             side,
#                             "| time left:",
#                             f"{min}m {sec}s",
#                         )

#                 except Exception as e:
#                     print("excepion 5", e)

#             if side == "DOWN":
#                 order_args2 = MarketOrderArgs(
#                     token_id=asset_id, side=BUY, amount=amount, price=price
#                 )
#                 signed_order2 = client.create_market_order(order_args2)
#                 try:
#                     resp = client.post_order(signed_order2, OrderType.FOK)
#                     if resp.get("success") == True:
#                         print(resp)
#                         placed_order.set()
#                         bet_down.set()
#                         buy_price = price
#                         min, sec = get_time_left()
#                         print(
#                             "placed order",
#                             asset_id,
#                             price,
#                             side,
#                             "| time left:",
#                             f"{min}m {sec}s",
#                         )
#                 except Exception as e:
#                     print("excepion 5", e)


# ─── BOT ─────────────────────────────────────────────────────────────────────
# def get_time_left():
#     global target_time
#     if not target_time:
#         return -1, -1
#     now = datetime.now(timezone.utc)
#     diff = target_time - now
#     seconds = int(diff.total_seconds())
#     if seconds < 0:
#         return 0, 0
#     mins = seconds // 60
#     secs = seconds % 60
#     # return f"{mins}m {secs}s"
#     return mins, secs


def bot():
    global initial_slug, buy_price, to_redeem, total_trades, both_sides_but_hit_stoploss_later, hit_stoploss_first, profit, lost

    while True:
        print("started for", initial_slug)
        major_taken = False
        minor_order_placed = False

        stop_loss_hit = False
        minor_filled = False
        major_side = None
        minor_side = None
        major_id = None
        minor_id = None
        stop_loss_time = None
        minor_fill_time = None
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
            nonlocal major_taken, minor_order_placed, stop_loss_hit, minor_filled, major_side, minor_side, major_id, minor_id, stop_loss_time, minor_fill_time
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
                if not major_taken:
                    if 0.80 <= best_ask_one <= 0.85:
                        major_taken = True
                        major_side = "UP" if id_one == up_id else "DOWN"
                        major_id = id_one
                        print(
                            "major side taken ..1", major_id, best_ask_one, major_side
                        )

                    elif 0.80 <= best_ask_two <= 0.85:
                        major_taken = True
                        major_side = "UP" if id_two == up_id else "DOWN"
                        major_id = id_two
                        print(
                            "major side taken ..2", major_id, best_ask_two, major_side
                        )

                # Minor side
                if major_taken and not minor_order_placed:
                    minor_side = "DOWN" if major_side == "UP" else "UP"
                    minor_id = down_id if major_side == "UP" else up_id
                    minor_order_placed = True
                    print(f"placed minor side order for {minor_side} ..{minor_id}")

                if major_taken and not stop_loss_hit:
                    if id_one == major_id and best_ask_one <= 0.50:
                        stop_loss_hit = True
                        stop_loss_time = time.time()
                        print(
                            "stop loss hit and selling ..1",
                            id_one,
                            best_ask_one,
                            major_side,
                        )

                    if id_two == major_id and best_ask_two <= 0.50:
                        stop_loss_hit = True
                        stop_loss_time = time.time()
                        print(
                            "stop loss hit and selling ..2",
                            id_two,
                            best_ask_two,
                            major_side,
                        )

                if minor_order_placed and not minor_filled:
                    if id_one == minor_id and best_ask_one <= 0.14:
                        minor_filled = True
                        minor_fill_time = time.time()
                        print("minor filled ..1", minor_id, 0.15, minor_side)

                    if id_two == minor_id and best_ask_two <= 0.14:
                        minor_filled = True
                        minor_fill_time = time.time()
                        print("minor filled ..2", minor_id, 0.15, minor_side)

            except Exception as e:
                print(e)
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
        total_trades += 1
        if stop_loss_hit and not minor_filled:
            hit_stoploss_first += 1
            lost += 1
            print("❌ Stop loss hit first → cancel 0.15 order")

        elif minor_filled and not stop_loss_hit:
            profit += 1
            print("✅ 0.15 hit first → good trade")

        elif stop_loss_hit and minor_filled:
            if minor_fill_time < stop_loss_time:
                profit += 1
                both_sides_but_hit_stoploss_later += 1
                print("✅ 0.15 hit BEFORE stop loss")
            else:
                print("❌ Stop loss hit BEFORE 0.15")

        elif not stop_loss_hit and not minor_filled and major_taken:
            print(
                "⚠️ Neither stop loss nor minor fill hit,but major taken market ended?"
            )
        elif not major_taken and not minor_filled:
            print("⚠️ Major side not taken, minor not filled, market ended")
        print("-" * 60)

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
    total_trades = 0
    both_sides_but_hit_stoploss_later = 0
    hit_stoploss_first = 0
    profit = 0
    lost = 0
    # threading.Thread(target=order_worker, daemon=True).start()
    print("PID:", os.getpid())
    try:
        bot()
    except KeyboardInterrupt:
        print(f"\n{'='*60}")
        print(f"📊 SESSION SUMMARY")
        print(f"Total trades: {total_trades}")
        print(f"Profitable trades: {profit}")
        print(f"Unprofitable trades: {lost}")
        print(
            f"Both sides but hit stop loss later: {both_sides_but_hit_stoploss_later}"
        )
        print(f"stop loss first: {hit_stoploss_first}")
        print(f"Profit = {profit*0.05} - {lost*0.40} = net {profit*0.05 - lost*0.40}")
        print(f"{'='*60}")
