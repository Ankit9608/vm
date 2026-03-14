import os

from py_clob_client import client
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    ApiCreds,
    OrderArgs,
    OrderType,
    BalanceAllowanceParams,
    AssetType,
)
from dotenv import load_dotenv
from py_clob_client.constants import AMOY
from py_clob_client.order_builder.constants import BUY
from web3 import Web3
import time

# from py_clob_client.clob_types import AllowanceParams

load_dotenv()


def main():
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

    # Create and sign a limit order buying 100 YES tokens for 0.0005 each
    order_args = OrderArgs(
        price=0.05,
        size=5,
        side=BUY,
        token_id="29423590008031401316499370971285625877393675153292371695375914221270876044252",
    )
    time1 = time.time()
    signed_order = client.create_order(order_args)
    time2 = time.time()
    print(f"Time taken to create and sign order: {time2 - time1} seconds")
    # print(signed_order)
    try:
        resp = client.post_order(signed_order, OrderType.GTC, post_only=True)
        time3 = time.time()
        print(f"Time taken to post order: {time3 - time2} seconds")
        print(
            "Total time taken to create, sign, and post order:",
            time3 - time1,
            "seconds",
        )
        print(type(resp))
        print(resp.get("orderID"))
        print(resp.get("success"))

    except Exception as e:
        print(e)
    print("Done!")


main()

# ---------------------
# order response example:
# {
#     "errorMsg": "",
#     "orderID": "0x2c1fdf49068adc726916d24b5c33df840f308e69e9b74209df0f901e45635dca",
#     "takingAmount": "",
#     "makingAmount": "",
#     "status": "live",
#     "success": True,
# }
