"""Isolated HTTP worker: the parent can stop a request despite provider keepalives."""
import json
import sys
import requests


def main():
    request = json.load(sys.stdin)
    try:
        response = requests.post(request["endpoint"], json=request["payload"],
                                 headers=request["headers"], timeout=request["timeout"])
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError) as error:
        # Never send provider bodies, credentials or source excerpts into logs.
        json.dump({"transport_error": type(error).__name__}, sys.stdout)
    else:
        json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
