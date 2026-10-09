
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
MAX_REPEATS = 500


def register_command():
    """Register /raid for user-installed apps."""
    if not APP_ID or not BOT_TOKEN:
        print("Missing APP_ID or BOT_TOKEN.")
        return

    command = {
        "name": "raid",
        "description": "Send a custom message a few times",
        "integration_types": [1],
        "contexts": [0, 2],
        "options": [
            {
                "type": 3,
                "name": "message",
                "description": "Your custom message",
                "required": True,
                "max_length": 2000
            },
            {
                "type": 4,
                "name": "repeats",
                "description": "Number of copies (1 to 5)",
                "required": False,
                "min_value": 1,
                "max_value": MAX_REPEATS
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
        print("Slash command /raid registered successfully.")

    except requests.RequestException as error:
        print("Command registration failed:", error)


def send_extra_copies(app_id, token, message, repeats):
    """Send remaining copies as interaction follow-ups."""
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
                print(
                    "Follow-up failed:",
                    response.status_code,
                    response.text[:300]
                )
                break

        except requests.RequestException as error:
            print("Follow-up request failed:", error)
            break


@app.get("/")
def health():
    return "Discord interaction endpoint is online.", 200


@app.post("/interactions")
def interactions():
    # Verify that the request came from Discord.
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

    # Discord endpoint verification.
    if payload.get("type") == 1:
        return jsonify({"type": 1})

    # Handle application commands only.
    if payload.get("type") != 2:
        return jsonify({
            "type": 4,
            "data": {
                "content": "Unsupported interaction.",
                "flags": 64
            }
        })

    # The registered command and handler must match.
    if payload.get("data", {}).get("name") != "raid":
        return jsonify({
            "type": 4,
            "data": {
                "content": "Unknown command. Try /raid.",
                "flags": 64
            }
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
                "content": "Please enter a message.",
                "flags": 64
            }
        })

    if not isinstance(repeats, int) or not 1 <= repeats <= MAX_REPEATS:
        return jsonify({
            "type": 4,
            "data": {
                "content": "Repeats must be between 1 and 5.",
                "flags": 64
            }
        })

    # Send the first copy as the interaction response.
    result = jsonify({
        "type": 4,
        "data": {
            "content": message,
            "allowed_mentions": {"parse": []}
        }
    })

    # Send any remaining copies after the initial response.
    if repeats > 1:
        threading.Thread(
            target=send_extra_copies,
            args=(
                APP_ID,
                payload["token"],
                message,
                repeats
            ),
            daemon=True
        ).start()

    return result


# Register /raid when the service starts.
register_command()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000"))
    )
