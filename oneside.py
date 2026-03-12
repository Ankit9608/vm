# buy only major side when it goes above 90
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


order_queue = queue.Queue()

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


def order_worker():
    global buy_price
    print("started order worker")
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

        if side == "UP":
            buy_price = price
            time.sleep(2)
            bet_up.set()
            print("placing order from thread", price, side)
            placed_order.set()
            while not order_queue.empty():
                order_queue.get()

        if side == "DOWN":
            buy_price = price
            time.sleep(2)
            bet_down.set()
            print("placing order from thread", price, side)
            placed_order.set()
            while not order_queue.empty():
                order_queue.get()


# ─── BOT ─────────────────────────────────────────────────────────────────────


def bot():
    global initial_slug, buy_price

    while True:
        ping_stop = threading.Event()
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
        up_id = ids[0][2:-1]
        down_id = ids[1][2:-2]
        TARGET_ASSETS = [up_id, down_id]
        # print(TARGET_ASSETS)

        endtime = response.get("endDate")
        target_time = datetime.fromisoformat(endtime)
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
            subscribe(ws)
            time.sleep(1)
            print("Reconnected")

        def on_pong(ws, message):
            print("Pong recieved =", message)

        def on_message(ws, message):
            global bet_for_up, bet_for_down
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
                if 0.95 <= best_ask_one <= 0.98:
                    if id_one == up_id:
                        if not bet_up.is_set() and not bet_down.is_set():
                            major_side = best_ask_one
                            major_side = math.floor(major_side * 100) / 100
                            print(
                                "up goes above 80 placing order for up.. 1 ---->",
                                major_side,
                            )
                            if not placed_order.is_set():
                                order_queue.put(
                                    {"id": id_one, "price": major_side, "side": "UP"}
                                )
                            # bet_for_up = True
                    else:
                        if not bet_down.is_set() and not bet_up.is_set():
                            major_side = best_ask_one
                            major_side = math.floor(major_side * 100) / 100

                            print(
                                "down goes above 80 placing order for down.. 2---->",
                                major_side,
                            )
                            if not placed_order.is_set():

                                order_queue.put(
                                    {"id": id_two, "price": major_side, "side": "DOWN"}
                                )
                            # bet_for_down = True

                if 0.95 <= best_ask_two <= 0.98:
                    if id_two == up_id:
                        if not bet_up.is_set() and not bet_down.is_set():
                            major_side = best_ask_two
                            major_side = math.floor(major_side * 100) / 100

                            print(
                                "up goes above 80 placing order for up.. 3 ----->",
                                major_side,
                            )
                            if not placed_order.is_set():
                                order_queue.put(
                                    {"id": id_two, "price": major_side, "side": "UP"}
                                )
                            # bet_for_up = True
                    else:
                        if not bet_down.is_set() and not bet_up.is_set():
                            major_side = best_ask_two
                            major_side = math.floor(major_side * 100) / 100
                            print(
                                "down goes above 80 placing order for down... 4---->",
                                major_side,
                            )
                            if not placed_order.is_set():
                                order_queue.put(
                                    {"id": id_one, "price": major_side, "side": "DOWN"}
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
            ping_stop.set()
            try:
                ws.sock.close()
            except Exception as e:
                print("excepion ", e)

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
            ws.run_forever(
                ping_interval=20, ping_timeout=10, ping_payload="PING", reconnect=3
            )
        except Exception as e:
            print("excepion3 =", e)
        finally:
            ping_stop.set()
            if ws.sock:
                ws.sock.close()

        print(f"✅ Market cycle complete for {initial_slug}")

        if bet_down.is_set() or bet_up.is_set():
            print(f"✅✅✅ TRADE SUCCESSFUL!")
            print(
                f"   Major: {buy_price:.3f}           Side:{"UP" if bet_up.is_set() else "DOWN" if bet_down.is_set() else None}"
            )

        elif not bet_down.is_set() and not bet_up.is_set():
            print("✅✅✅ TRADE SKIPPED! No loss for this market!")

        print("-" * 60)
        bet_up.clear()
        bet_down.clear()
        buy_price = 0.0
        while not order_queue.empty():
            order_queue.get()
        print("Queue cleared", order_queue.empty())
        placed_order.clear()
        time.sleep(5)
        print("switched new slug")
        initial_slug = new_slug  # advance only after intentional close


# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    initial_slug = "btc-updown-5m-1773304500"
    buy_price = 0.0
    threading.Thread(target=order_worker, daemon=True).start()
    print("PID:", os.getpid())
    try:
        bot()
    except KeyboardInterrupt:
        print(f"\n{'='*60}")
        print(f"📊 SESSION SUMMARY")
        print(f"{'='*60}")
