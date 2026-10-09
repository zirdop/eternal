
import os
import time
import threading
import requests

from flask import Flask, request
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

app = Flask(__name__)

# ==================================================
# SETTINGS — ONLY CHANGE THESE IN THE CODE
# ==================================================

SET_MESSAGE = "# GET RAIDED BY https://discord.gg/DdgNaCz8zR ! JOIN https://discord.gg/DdgNaCz8zR TO USE THIS RAID BOT YOURSELF! (0 SERVER PERMS NEEDED AND THE BOT DOES NOT NEED TO BE IN THE SERVER!)"

# Number of public messages sent per button click
REPEATS_PER_CLICK = 5

MAX_REPEATS = 100
CLICK_COOLDOWN_SECONDS = 1

# ==================================================
# DISCORD / RENDER SETTINGS
# Set these in Render Environment Variables
# ==================================================

APP_ID = os.environ["APP_ID"]
PUBLIC_KEY = os.environ["PUBLIC_KEY"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

API_BASE = "https://discord.com/api/v10"

last_click = {}
click_lock = threading.Lock()


def get_user_id(interaction):
    """Get the user ID in either a server or DM context."""
    if interaction.get("member"):
        return interaction["member"]["user"]["id"]

    return interaction.get("user", {}).get("id")


def private_response(content, components=None):
    """Return a response visible only to the person interacting."""
    data = {
        "content": content,
        "flags": 64
    }

    if components:
        data["components"] = components

    return {"type": 4, "data": data}


def register_command():
    """Register the global user-installed /raid command."""
    command = {
        "name": "raid",
        "description": "Open panel",
        "type": 1,
        "integration_types": [1],
        "contexts": [0, 2]
    }

    response = requests.put(
        f"{API_BASE}/applications/{APP_ID}/commands",
        headers={
            "Authorization": f"Bot {BOT_TOKEN}",
            "Content-Type": "application/json"
        },
        json=[command],
        timeout=15
    )

    print("Command registration:", response.status_code)
    if not response.ok:
        print("Registration error:", response.text)
    else:
        print("Slash command /raid registered successfully.")


@app.route("/", methods=["GET"])
def home():
    return "Discord interaction app is running!", 200


@app.route("/interactions", methods=["POST"])
def interactions():
    body = request.get_data()
    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")

    # Verify that this request really came from Discord.
    try:
        verify_key = VerifyKey(bytes.fromhex(PUBLIC_KEY))
        verify_key.verify(
            timestamp.encode() + body,
            bytes.fromhex(signature)
        )
    except (BadSignatureError, ValueError):
        return "Invalid request signature", 401

    interaction = request.get_json(silent=True) or {}
    interaction_type = interaction.get("type")

    # Discord endpoint verification ping
    if interaction_type == 1:
        return {"type": 1}

    # Slash command: /raid
    if interaction_type == 2:
        command = interaction.get("data", {}).get("name")

        if command != "raid":
            return private_response("Unknown command.")

        user_id = get_user_id(interaction)
        if not user_id:
            return private_response("Could not identify the user.")

        # Only the person who ran /raid is authorized to use its button.
        button_id = f"send_fixed_message:{user_id}"

        components = [{
            "type": 1,
            "components": [{
                "type": 2,
                "style": 1,
                "label": "Send message",
                "custom_id": button_id
            }]
        }]

        return private_response(
            "Spam button to raid!",
            components
        )

    # Button click
    if interaction_type == 3:
        custom_id = interaction.get("data", {}).get("custom_id", "")
        user_id = get_user_id(interaction)

        if not custom_id.startswith("send_fixed_message:"):
            return private_response("Unknown button.")

        allowed_user_id = custom_id.split(":", 1)[1]

        # Stop other people from using your private button.
        if not user_id or user_id != allowed_user_id:
            return private_response(
                "This button belongs to the person who opened it."
            )

        # Small per-user cooldown to prevent accidental channel flooding.
        now = time.time()

        with click_lock:
            previous_click = last_click.get(user_id, 0)

            if now - previous_click < CLICK_COOLDOWN_SECONDS:
                return private_response(
                    "Please wait a moment before clicking again."
                )

            last_click[user_id] = now

        repeats = max(1, min(REPEATS_PER_CLICK, MAX_REPEATS))

        # The first message is sent as the public button response.
        # Additional messages are sent as public follow-ups.
        token = interaction.get("token")

        if not token:
            return private_response("Missing interaction token.")

        threading.Thread(
            target=send_messages,
            args=(token, repeats - 1),
            daemon=True
        ).start()

        return {
            "type": 4,
            "data": {
                "content": SET_MESSAGE,
                "allowed_mentions": {"parse": []}
            }
        }

    return private_response("Unsupported interaction.")


def send_messages(interaction_token, additional_count):
    """Send the remaining fixed messages as public follow-ups."""
    if additional_count <= 0:
        return

    webhook_url = (
        f"{API_BASE}/webhooks/{APP_ID}/{interaction_token}"
    )

    for _ in range(additional_count):
        time.sleep(1)

        try:
            response = requests.post(
                webhook_url,
                json={
                    "content": SET_MESSAGE,
                    "allowed_mentions": {"parse": []}
                },
                timeout=15
            )

            if response.status_code == 429:
                # Respect Discord's rate-limit instruction.
                details = response.json()
                time.sleep(
                    min(float(details.get("retry_after", 1)), 5)
                )
                response = requests.post(
                    webhook_url,
                    json={
                        "content": SET_MESSAGE,
                        "allowed_mentions": {"parse": []}
                    },
                    timeout=15
                )

            if not response.ok:
                print(
                    "Could not send follow-up:",
                    response.status_code,
                    response.text
                )
                return

        except requests.RequestException as error:
            print("Follow-up error:", error)
            return


# Register the command when the app starts.
register_command()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
