
import os
import json
import time
import threading

import requests
from flask import Flask, request, jsonify
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

app = Flask(__name__)

APP_ID = os.environ.get("APP_ID", "")
PUBLIC_KEY = os.environ.get("PUBLIC_KEY", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

DISCORD_API = "https://discord.com/api/v10"


def register_command():
    """Register /say for user-installed apps."""
    if not APP_ID or not BOT_TOKEN:
        print("Missing APP_ID or BOT_TOKEN; command not registered.")
        return

    command = {
        "name": "raid",
        "description": "raid or something yeah",
        "integration_types": [1],
        "contexts": [0, 2],
        "options": [
            {
                "type": 3,
                "name": "message",
                "description": "text",
                "required": True,
                "max_length": 2000
            },
            {
                "type": 4,
                "name": "repeats",
                "description": "Number of copies (1 to 5)",
                "required": False,
                "min_value": 1,
                "max_value": 500
            }
        ]
    }

    try:
        response = requests.put(
            f"{DISCORD_API}/applications/{APP_ID}/commands",
            headers={"Authorization": f"Bot {BOT_TOKEN}"},
            json=[command],
            timeout=15
        )
        response.raise_for_status()
        print("Slash command /say registered.")
    except requests.RequestException as error:
        print("Command registration failed:", error)


def send_extra_copies(app_id, token, message, repeats):
    """Send the remaining copies as interaction follow-ups."""
    url = f"{DISCORD_API}/webhooks/{app_id}/{token}"

    for _ in range(repeats - 1):
        time.sleep(1)

        try:
            response = requests.post(
                url,
                json={
                    "content": message,
                    "allowed_mentions": {"parse": []}
                },
                timeout=10
            )

            if not response.ok:
                print("Follow-up failed:", response.status_code)
                break

        except requests.RequestException as error:
            print("Follow-up request failed:", error)
            break


@app.get("/")
def health():
    return "Discord interaction endpoint is online.", 200


@app.post("/interactions")
def interactions():
    # Verify that this request really came from Discord.
    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")
    raw_body = request.get_data()

    if not PUBLIC_KEY or not signature or not timestamp:
        return "Missing signature information", 401

    try:
        verifier = VerifyKey(bytes.fromhex(PUBLIC_KEY))
        verifier.verify(
            timestamp.encode("utf-8") + raw_body,
            bytes.fromhex(signature)
        )
    except (BadSignatureError, ValueError):
        return "Invalid signature", 401

    try:
        payload = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError):
        return "Invalid JSON", 400

    # Discord uses PING to test the endpoint.
    if payload.get("type") == 1:
        return jsonify({"type": 1})

    # Only handle slash commands.
    if payload.get("type") != 2:
        return jsonify({
            "type": 4,
            "data": {
                "content": "This interaction isn't supported.",
                "flags": 64
            }
        })

    if payload.get("data", {}).get("name") != "say":
        return jsonify({
            "type": 4,
            "data": {"content": "Unknown command.", "flags": 64}
        })

    options = {
        option["name"]: option.get("value")
        for option in payload.get("data", {}).get("options", [])
    }

    message = options.get("message", "")
    repeats = options.get("repeats", 1)

    if not isinstance(message, str) or not message.strip():
        return jsonify({
            "type": 4,
            "data": {
                "content": "Please enter a non-empty message.",
                "flags": 64
            }
        })

    if not isinstance(repeats, int) or not 1 <= repeats <= 5:
        return jsonify({
            "type": 4,
            "data": {
                "content": "Repeats must be between 1 and 5.",
                "flags": 64
            }
        })

    # Respond immediately: Discord requires a response within 3 seconds.
    # This first response is also the first copy of the message.
    result = jsonify({
        "type": 4,
        "data": {
            "content": message,
            "allowed_mentions": {"parse": []}
        }
    })

    # Queue any remaining copies after preparing the initial response.
    if repeats > 1:
        threading.Thread(
            target=send_extra_copies,
            args=(APP_ID, payload["token"], message, repeats),
            daemon=True
        ).start()

    return result


# Register the slash command when the web service starts.
register_command()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000"))
    )
