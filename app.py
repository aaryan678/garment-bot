# app.py  — minimal “hi → hello” bot
import os, re
from dotenv import load_dotenv
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler





# ----------  LOCAL DB SETUP  ----------
from database_setup import (
    STAGE_LABELS,
    add_style,
    get_all_styles,
    get_style_by_id,
    get_styles_by_merchant,
    update_style_stage,
)

load_dotenv()  # pulls SLACK_BOT_TOKEN + SLACK_SIGNING_SECRET from .env

bolt_app = App(                 # Slack Bolt instance
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
)

@bolt_app.message(re.compile(r"(?i)^\s*hi\s*$"))
def say_hello(message, say, logger):
    logger.info(f"Got hi from {message['user']}")
    say(f"Hey there, <@{message['user']}>! :wave:"        )

# ---------- /current-styles slash-command ----------
@bolt_app.command("/current-styles")
def list_current_styles(ack, body, client, logger):
    ack()                                    # must respond within 3 s

    user_id    = body["user_id"]
    channel_id = body["channel_id"]

    # Map Slack user ➜ merchant name (same rule we used when saving)
    prof = client.users_info(user=user_id)["user"]["profile"]
    merchant = prof.get("display_name") or prof["real_name"]

    # Pull this merchant's styles from TinyDB
    rows = get_styles_by_merchant(merchant, active_only=True)

    if not rows:
        client.chat_postEphemeral(
            channel=channel_id, user=user_id,
            text="🟢 You don't have any styles yet."
        )
        return

    # Build a neat text list
    lines = [
        f"*{r.brand}* • {r.style_no} • {r.garment} • {r.colour} • {STAGE_LABELS[r.stage]}"
        for r in rows
    ]
    message = "*Your active styles:*\n" + "\n".join(lines[:50])   # cap at 50 lines

    # Ephemeral = only the invoking user sees it
    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=message
    )

# ---------- /update-stage (open modal) ----------
@bolt_app.command("/update-stage")
def open_stage_modal(ack, body, client, logger):
    ack()

    user_id = body["user_id"]
    prof    = client.users_info(user=user_id)["user"]["profile"]
    merchant = prof.get("display_name") or prof["real_name"]

    rows = sorted(
        get_styles_by_merchant(merchant, active_only=True),
        key=lambda r: r.created_at,
    )

    if not rows:
        client.chat_postEphemeral(
            channel=body["channel_id"], user=user_id,
            text="You have no active styles."
        )
        return

    # turn rows → Slack select-options
    style_opts = [{
        "text":  { "type":"plain_text",
                   "text": f"{r.brand}·{r.style_no} ({STAGE_LABELS[r.stage]})" },
        "value": str(r.id)
    } for r in rows]

    stage_opts = [{
        "text":  { "type":"plain_text", "text": f"{i} · {label}" },
        "value": str(i)
    } for i, label in enumerate(STAGE_LABELS)]

    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type":"modal",
            "callback_id":"stage_update_submit",
            "title":  { "type":"plain_text", "text":"Update Stage" },
            "submit": { "type":"plain_text", "text":"Save" },
            "blocks":[
                { "type":"input", "block_id":"style",
                  "element": { "type":"static_select",
                               "action_id":"val",
                               "options":style_opts },
                  "label": { "type":"plain_text", "text":"Select Style" }},

                { "type":"input", "block_id":"stage",
                  "element": { "type":"static_select",
                               "action_id":"val",
                               "options":stage_opts },
                  "label": { "type":"plain_text", "text":"New Stage" }}
            ]
        }
    )

# ---------- modal submit ----------
@bolt_app.view("stage_update_submit")
def save_stage_update(ack, body, view, client, logger):
    ack()

    style_id = int(view["state"]["values"]["style"]["val"]["selected_option"]["value"])
    new_stage= int(view["state"]["values"]["stage"]["val"]["selected_option"]["value"])
    user_id  = body["user"]["id"]

    sty = get_style_by_id(style_id)
    if not sty:
        logger.warning(f"Style {style_id} vanished")
        return

    update_style_stage(style_id, new_stage)

    client.chat_postMessage(
        channel=user_id,
        text=(f":truck: *Stage updated*\n"
              f"{sty.brand}·{sty.style_no} is now "
              f"*{STAGE_LABELS[new_stage]}*")
    )

# ---------- /morning-update (open huge modal) ----------
@bolt_app.command("/morning-update")
def open_bulk_modal(ack, body, client):
    ack()

    user_id = body["user_id"]
    prof    = client.users_info(user=user_id)["user"]["profile"]
    merchant = prof.get("display_name") or prof["real_name"]

    # grab active styles
    rows = sorted(
        get_styles_by_merchant(merchant, active_only=True),
        key=lambda r: r.created_at,
    )

    if not rows:
        client.chat_postEphemeral(
            channel=body["channel_id"], user=user_id,
            text="🎉 You have no active styles this morning."
        )
        return

    blocks = []
    for r in rows[:40]:                         # safety: Slack modal ≤ 50 blocks
        stage_opts = [{
            "text":  {"type":"plain_text", "text": f"{i} · {label}"},
            "value": str(i)
        } for i, label in enumerate(STAGE_LABELS)]

        blocks.append(                          # a section block with a select
            { "type":"section",
              "block_id": f"style_{r.id}",
              "text": {"type":"mrkdwn",
                       "text": f"*{r.brand}* • {r.style_no} • {r.garment} • {r.colour}" },
              "accessory": {
                  "type":"static_select",
                  "action_id":"stage_select",
                  "initial_option": {
                      "text": {"type":"plain_text",
                               "text": f"{r.stage} · {STAGE_LABELS[r.stage]}"},
                      "value": str(r.stage)
                  },
                  "options": stage_opts
              }
            }
        )
        blocks.append({ "type":"divider" })

    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type":"modal",
            "callback_id":"bulk_stage_submit",
            "title":  {"type":"plain_text", "text":"Morning Update"},
            "submit": {"type":"plain_text", "text":"Save"},
            "blocks": blocks
        }
    )

# ---------- modal submit ----------
@bolt_app.view("bulk_stage_submit")
def save_bulk_update(ack, body, view, client, logger):
    ack()
    user_id = body["user"]["id"]
    # Get merchant name for summary
    prof = client.users_info(user=user_id)["user"]["profile"]
    merchant = prof.get("display_name") or prof["real_name"]
    changes, dispatched = [], []

    for blk_id, blk_val in view["state"]["values"].items():
        if not blk_id.startswith("style_"):
            continue
        style_id = int(blk_id.split("_")[1])
        new_stage = int(blk_val["stage_select"]["selected_option"]["value"])
        sty = get_style_by_id(style_id)
        if not sty or sty.stage == new_stage:
            continue
        update_style_stage(style_id, new_stage)
        if new_stage == 13:
            dispatched.append(f"{sty.brand}·{sty.style_no}")
        changes.append(f"{sty.brand}·{sty.style_no} → *{STAGE_LABELS[new_stage]}*")

    # Confirmation DM to merchant
    txt = ["✅ *Morning update received!*"]
    if changes:    txt += ["\n".join(changes)]
    if dispatched: txt += ["\n_Dispatched:_ " + ", ".join(dispatched)]
    client.chat_postMessage(channel=user_id, text="\n".join(txt))

    # Also send summary to Harsh Lalwani
    harsh_id = get_harsh_user_id()
    if harsh_id and (changes or dispatched):
        summary = [f"Morning update from {merchant}:"]
        if changes:    summary += ["\n".join(changes)]
        if dispatched: summary += ["\n_Dispatched:_ " + ", ".join(dispatched)]
        try:
            bolt_app.client.chat_postMessage(channel=harsh_id, text="\n".join(summary))
        except Exception as e:
            print(f"Failed to send summary to Harsh Lalwani: {e}")


flask_app = Flask(__name__)     # single Flask wrapper
handler = SlackRequestHandler(bolt_app)

@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)   # Bolt handles URL-verification, etc.

@flask_app.route("/slack/command", methods=["POST"])
def slack_command():
    return handler.handle(request)   # Bolt handles slash commands





# ---------- /add-style slash-command ----------
@bolt_app.command("/add-style")
def open_add_style_modal(ack, body, client):
    ack()                                         # 1) acknowledge Slack
    client.views_open(                            # 2) push a modal
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "add_style_submit",
            "title": { "type": "plain_text", "text": "Add New Style" },
            "submit": { "type": "plain_text", "text": "Save" },
            "close":  { "type": "plain_text", "text": "Cancel" },
            "blocks": [
                { "type": "input", "block_id": "brand",
                  "element": { "type": "plain_text_input", "action_id": "val" },
                  "label": { "type": "plain_text", "text": "Brand" } },

                { "type": "input", "block_id": "style_no",
                  "element": { "type": "plain_text_input", "action_id": "val" },
                  "label": { "type": "plain_text", "text": "Exact Style No." } },

                { "type": "input", "block_id": "garment",
                  "element": {
                      "type": "static_select", "action_id": "garment_select",
                      "options": [
                          *[{ "text": { "type": "plain_text", "text": g },
                              "value": g.lower() } for g in
                              ["Kurta", "Shirt", "Dress", "Tunic", "Pant", "Jacket", "Skirts","Blouses", "Jumpsuits","Other"]]
                      ]
                  },
                  "label": { "type": "plain_text", "text": "Garment Type" } },

                { "type": "input", "block_id": "custom_garment",
                  "element": { "type": "plain_text_input", "action_id": "val" },
                  "label": { "type": "plain_text", "text": "Custom Garment Type" },
                  "optional": True },

                { "type": "input", "block_id": "color",
                  "element": { "type": "plain_text_input", "action_id": "val" },
                  "label": { "type": "plain_text", "text": "Colour" } }
            ]
        }
    )

# ---------- handle garment type selection ----------
@bolt_app.action("garment_select")
def handle_garment_selection(ack, body, client, logger):
    ack()
    
    selected_value = body["actions"][0]["selected_option"]["value"]
    
    if selected_value == "other":
        # Show the custom garment input field
        client.views_update(
            view_id=body["view"]["id"],
            view={
                "type": "modal",
                "callback_id": "add_style_submit",
                "title": { "type": "plain_text", "text": "Add New Style" },
                "submit": { "type": "plain_text", "text": "Save" },
                "close":  { "type": "plain_text", "text": "Cancel" },
                "blocks": [
                    { "type": "input", "block_id": "brand",
                      "element": { "type": "plain_text_input", "action_id": "val" },
                      "label": { "type": "plain_text", "text": "Brand" } },

                    { "type": "input", "block_id": "style_no",
                      "element": { "type": "plain_text_input", "action_id": "val" },
                      "label": { "type": "plain_text", "text": "Exact Style No." } },

                    { "type": "input", "block_id": "garment",
                      "element": {
                          "type": "static_select", "action_id": "garment_select",
                          "options": [
                              *[{ "text": { "type": "plain_text", "text": g },
                                  "value": g.lower() } for g in
                                  ["Kurta", "Shirt", "Dress", "Tunic", "Pant", "Jacket", "Skirts","Blouses", "Jumpsuits","Other"]]
                          ],
                          "initial_option": { "text": { "type": "plain_text", "text": "Other" }, "value": "other" }
                      },
                      "label": { "type": "plain_text", "text": "Garment Type" } },

                    { "type": "input", "block_id": "custom_garment",
                      "element": { "type": "plain_text_input", "action_id": "val" },
                      "label": { "type": "plain_text", "text": "Custom Garment Type" } },

                    { "type": "input", "block_id": "color",
                      "element": { "type": "plain_text_input", "action_id": "val" },
                      "label": { "type": "plain_text", "text": "Colour" } }
                ]
            }
        )
    else:
        # Hide the custom garment input field
        client.views_update(
            view_id=body["view"]["id"],
            view={
                "type": "modal",
                "callback_id": "add_style_submit",
                "title": { "type": "plain_text", "text": "Add New Style" },
                "submit": { "type": "plain_text", "text": "Save" },
                "close":  { "type": "plain_text", "text": "Cancel" },
                "blocks": [
                    { "type": "input", "block_id": "brand",
                      "element": { "type": "plain_text_input", "action_id": "val" },
                      "label": { "type": "plain_text", "text": "Brand" } },

                    { "type": "input", "block_id": "style_no",
                      "element": { "type": "plain_text_input", "action_id": "val" },
                      "label": { "type": "plain_text", "text": "Exact Style No." } },

                    { "type": "input", "block_id": "garment",
                      "element": {
                          "type": "static_select", "action_id": "garment_select",
                          "options": [
                              *[{ "text": { "type": "plain_text", "text": g },
                                  "value": g.lower() } for g in
                                  ["Kurta", "Shirt", "Dress", "Tunic", "Pant", "Jacket", "Skirts","Blouses", "Jumpsuits","Other"]]
                          ],
                          "initial_option": { "text": { "type": "plain_text", "text": selected_value.title() }, "value": selected_value }
                      },
                      "label": { "type": "plain_text", "text": "Garment Type" } },

                    { "type": "input", "block_id": "custom_garment",
                      "element": { "type": "plain_text_input", "action_id": "val" },
                      "label": { "type": "plain_text", "text": "Custom Garment Type" },
                      "optional": True },

                    { "type": "input", "block_id": "color",
                      "element": { "type": "plain_text_input", "action_id": "val" },
                      "label": { "type": "plain_text", "text": "Colour" } }
                ]
            }
        )

# ---------- modal submit handler ----------
@bolt_app.view("add_style_submit")
def handle_add_style_submission(ack, body, view, client, logger):
    ack()                                         # tell Slack “got it”

    vals = view["state"]["values"]
    brand     = vals["brand"]["val"]["value"]
    style_no  = vals["style_no"]["val"]["value"]
    garment_selection = vals["garment"]["garment_select"]["selected_option"]["text"]["text"]
    color     = vals["color"]["val"]["value"]
    user_id   = body["user"]["id"]

    # Handle custom garment type
    if garment_selection == "Other":
        if "custom_garment" in vals and vals["custom_garment"]["val"]["value"]:
            garment = vals["custom_garment"]["val"]["value"]
        else:
            garment = "Other"
    else:
        garment = garment_selection

    # who is the merchant? use Slack display-name fallback to real-name
    profile = client.users_info(user=user_id)["user"]["profile"]
    merchant = profile.get("display_name") or profile["real_name"]

    # Save to database
    add_style(
        merchant=merchant,
        brand=brand,
        style_no=style_no,
        garment=garment,
        colour=color,
    )

    logger.info(f"New style from {user_id}: {brand}-{style_no}")

    msg = (
        f"• *Brand:* {brand}\n"
        f"• *Style No.:* {style_no}\n"
        f"• *Type:* {garment}\n"
        f"• *Colour:* {color}"
    )
    client.chat_postMessage(channel=user_id,
                            text=":white_check_mark: Style saved!\n" + msg)

@bolt_app.command("/get-info")
def handle_get_info(ack, respond):
    ack()
    respond(
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*👋 Welcome to Garment Bot!*\nHere’s everything you need to know:"
                }
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*🛠️ Available Commands:*\n"
                            "`/add-style` – Add a new garment style with optional photo\n"
                            "`/update-status` – Update the production stage of an existing style\n"
                            "`/current-styles` – View all styles you're handling\n"
                            "`/morning-update` – Bulk update all your styles for today\n"
                            "`/get-info` – Show this help message"
                }
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*⚠️ If the bot doesn’t respond right away…*\n"
                            "The bot might be asleep. This can happen if it hasn't been used recently.\n\n"
                            "• Type `hi`\n"
                            "• If no reply, wait ~50 seconds and type `hi` again\n"
                            "Once you get a wave 👋 back, the bot is live!"
                }
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*📦 Technical Notes:*\n"
                            "• Pings from UptimeRobot keep it awake"
                }
            },
            {"type": "divider"},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Have questions or ideas? Reach out to <@aaryan> 💬"
                    }
                ]
            }
        ]
    )





# ---------- DAILY REMINDER SCHEDULER ----------
from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone
import datetime

# Only send reminders to these merchants (for testing)
ALLOWED_MERCHANTS = {"Siddharth", "Megha"}

def send_daily_reminder():
    styles = get_all_styles()
    merchants = {s.merchant for s in styles if s.active}
    if not merchants:
        return
    for merchant in merchants:
        if merchant not in ALLOWED_MERCHANTS:
            continue
        merchant_styles = [s for s in styles if s.merchant == merchant and s.active]
        if not merchant_styles:
            continue
        merchant_styles.sort(key=lambda s: s.created_at, reverse=True)
        style = merchant_styles[0]
        # Try to find the Slack user_id for this merchant
        try:
            users = bolt_app.client.users_list()["members"]
            user_id = None
            for u in users:
                prof = u.get("profile", {})
                if prof.get("display_name") == merchant or prof.get("real_name") == merchant:
                    user_id = u["id"]
                    break
            if not user_id:
                continue
        except Exception as e:
            print(f"Could not find user for merchant {merchant}: {e}")
            continue
        # Compose the message
            msg = (
                "Good morning! ☀️\n\n"
                "Please fill in your daily style report using `/morning-update`.\n\n"
                "*Available commands:*\n"
                "• `/add-style` — Add a new style\n"
                "• `/current-styles` — See your active styles and their current stage\n"
                "• `/update-stage` — Update the stage for a single style\n"
                "• `/morning-update` — Bulk update all your styles for today\n\n"
                "Click the `/morning-update` command or type it in any channel to get started!"
            )
            try:
                bolt_app.client.chat_postMessage(channel=user_id, text=msg)
            except Exception as e:
                print(f"Failed to send DM to {merchant}: {e}")

# Schedule the job at 9:30 AM IST
def start_scheduler():
    scheduler = BackgroundScheduler(timezone=timezone('Asia/Kolkata'))
    scheduler.add_job(send_daily_reminder, 'cron', hour=9, minute=30)
    scheduler.start()

# Helper to get Harsh Lalwani's user ID
HARSH_NAME = "Harsh Lalwani"
def get_harsh_user_id():
    try:
        users = bolt_app.client.users_list()["members"]
        for u in users:
            prof = u.get("profile", {})
            if prof.get("display_name") == HARSH_NAME or prof.get("real_name") == HARSH_NAME:
                return u["id"]
    except Exception as e:
        print(f"Could not find Harsh Lalwani: {e}")
    return None



@flask_app.route("/")
def index():
    return "✅ Slack bot is live!", 200

@flask_app.route("/ping")
def ping():
    return "pong", 200


if __name__ == "__main__":
    # Optional: print every incoming request for quick debugging
    import logging, sys
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    start_scheduler()
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
