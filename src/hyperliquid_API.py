import requests
import json


def GetOpenPositionDetails(base_url, general_public_key):

    payload = json.dumps(
        {"type": "clearinghouseState", "user": general_public_key, "dex": ""}
    )
    headers = {"Content-Type": "application/json"}

    response = requests.request("POST", base_url, headers=headers, data=payload)
    return response.json()


# TODO: very long response, check with ML engineer what to keep of it
