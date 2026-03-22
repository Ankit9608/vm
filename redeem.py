import os
from web3 import Web3
from py_builder_relayer_client.client import RelayClient

from py_builder_relayer_client.models import OperationType, SafeTransaction

from py_builder_signing_sdk.config import BuilderConfig
from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds
from dotenv import load_dotenv

load_dotenv()

# Setup client
builder_config = BuilderConfig(
    local_builder_creds=BuilderApiKeyCreds(
        key=os.getenv("POLY_BUILDER_API_KEY"),
        secret=os.getenv("POLY_BUILDER_SECRET"),
        passphrase=os.getenv("POLY_BUILDER_PASSPHRASE"),
    )
)

PRIVATE_KEY = os.getenv("PRIVATE_KEY")


client = RelayClient(
    "https://relayer-v2.polymarket.com", 137, PRIVATE_KEY, builder_config
)
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
parent_collection_id = b"\x00" * 32
collateral_token = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
condition_id = "0x4e400c6b065f3de8aaed5137c0d6001a1427b8bb6c20dd5ff5c90f0db19fcaa2"
index_sets = [1, 2]


# class Transaction:
#     def __init__(self, to, data, value=0):
#         self.to = to
#         self.data = data
#         self.value = value


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
        args=[collateral_token, parent_collection_id, condition_id, index_sets],
    ),
    value="0",
)

response = client.execute([redeem_tx], "Redeem positions")
response.wait()
print(type(response))
print(response)
