# For 5 min markets - SYNCHRONOUS VERSION

import requests
import json
import time
from datetime import datetime, timezone, timedelta

# import ssl
import websocket

# import peewee
import urllib3
import threading
import queue
import math


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


# ─── BOT ─────────────────────────────────────────────────────────────────────


def bot():
    global initial_slug, successfull, lost

    while True:
        print("started for", initial_slug)

        bet_for_up = False
        bet_for_down = False
        major_side = 0.0
        minor_side = 0.0

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
            print("Reconnected")
            subscribe(ws)
            time.sleep(1)

        def on_message(ws, message):
            nonlocal bet_for_up, bet_for_down, major_side, minor_side
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
                if 0.80 <= best_ask_one <= 0.85:
                    if id_one == up_id:
                        if not bet_for_up and not bet_for_down:
                            major_side = best_ask_one
                            print(
                                "up goes above 80 placing order for up.. 1 ---->",
                                major_side,
                            )
                            bet_for_up = True
                    else:
                        if not bet_for_down and not bet_for_up:
                            major_side = best_ask_one
                            print(
                                "down goes above 80 placing order for down.. 2---->",
                                major_side,
                            )
                            bet_for_down = True

                if 0.80 <= best_ask_two <= 0.85:
                    if id_two == up_id:
                        if not bet_for_up and not bet_for_down:
                            major_side = best_ask_two
                            print(
                                "up goes above 80 placing order for up.. 3 ----->",
                                major_side,
                            )
                            bet_for_up = True
                    else:
                        if not bet_for_down and not bet_for_up:
                            major_side = best_ask_two
                            bet_for_down = True
                            print(
                                "down goes above 80 placing order for down... 4---->",
                                major_side,
                            )

                # minor side
                if major_side != 0.00:
                    threshold = (1.00 - major_side) - 0.05
                    if best_ask_one <= threshold:
                        if id_one == up_id:
                            if not bet_for_up:
                                minor_side = best_ask_one
                                bet_for_up = True
                                print(
                                    "up goes below threshold placing order.. 5 ---->",
                                    minor_side,
                                )
                        else:
                            if not bet_for_down:
                                minor_side = best_ask_one
                                bet_for_down = True
                                print(
                                    "down goes below threshold placing order.. 6---->",
                                    minor_side,
                                )

                    if best_ask_two <= threshold:
                        if id_two == up_id:
                            if not bet_for_up:
                                minor_side = best_ask_two
                                bet_for_up = True
                                print(
                                    "up goes below threshold placing order.. 7 ---->",
                                    minor_side,
                                )
                        else:
                            if not bet_for_down:
                                minor_side = best_ask_two
                                bet_for_down = True
                                print(
                                    "down goes below threshold placing order.. 8 ---->",
                                    minor_side,
                                )

            except Exception as e:
                pass

        def on_error(ws, error):
            print(f"❌ WebSocket error: {error}")

        def on_close(ws, code, msg):
            print(f"WebSocket closed: {code} - {msg}")
            try:
                ws.sock.close()
            except Exception as e:
                print("excepion ", e)

        # ── connect ───────────────────────────────────────────────────────
        ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_reconnect=on_reconnect,
        )

        try:
            ws.run_forever(reconnect=3)
        except Exception as e:
            print("excepion3 =", e)
        finally:
            if ws.sock:
                ws.sock.close()

        print(f"✅ Market cycle complete for {initial_slug}")

        total = major_side + minor_side

        if bet_for_down and bet_for_up:
            successfull += 1
            print(f"✅✅✅ TRADE SUCCESSFUL!")
            print(
                f"   Major: {major_side:.3f}, Minor: {minor_side:.3f}, Total: {total:.3f}"
            )
        elif not bet_for_down and not bet_for_up:
            print("✅✅✅ TRADE SKIPPED! No loss for this market!")
        else:
            lost += 1
            print(f"❌❌❌ TRADE LOST")
            print(f"   UP: {bet_for_up}, DOWN: {bet_for_down}")
            print(f"   Major: {major_side:.3f}, Minor: {minor_side:.3f}")

        print("-" * 60)
        print("switched new slug")
        time.sleep(5)
        initial_slug = new_slug  # advance only after intentional close


# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    initial_slug = "btc-updown-5m-1773205200"
    successfull = 0
    lost = 0

    import os

    print("PID:", os.getpid())
    bot()

    total_trades = successfull + lost
    success_rate = (successfull / total_trades * 100) if total_trades > 0 else 0

    print(f"\n{'='*60}")
    print(f"📊 SESSION SUMMARY")
    print(f"{'='*60}")
    print(f"✅ Successful trades: {successfull}")
    print(f"❌ Lost trades:       {lost}")
    print(f"📈 Total trades:      {total_trades}")
    print(f"🎯 Success rate:      {success_rate:.1f}%")
    print(f"{'='*60}")
