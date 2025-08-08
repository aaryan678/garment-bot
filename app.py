# app.py  — minimal “hi → hello” bot
import os, re, json, csv, io
from dotenv import load_dotenv
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_sdk import WebClient





# ----------  LOCAL DB SETUP  ----------
from database_setup import (
    STAGE_LABELS,
    add_style,
    get_all_styles,
    get_style_by_id,
    get_styles_by_merchant,
    update_style_stage,
    update_style_quantities,
    update_style_info,
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
    # Compute selections first to decide whether to push a follow-up modal
    style_id = int(view["state"]["values"]["style"]["val"]["selected_option"]["value"])
    new_stage= int(view["state"]["values"]["stage"]["val"]["selected_option"]["value"])
    user_id  = body["user"]["id"]

    sty = get_style_by_id(style_id)
    if not sty:
        ack()
        logger.warning(f"Style {style_id} vanished")
        return

    # Flow stages: Cutting sheet (8), Inline (9), Stitching (10), Finishing (11), Packing (12)
    if new_stage in (8, 9, 10, 11, 12):
        # Push a follow-up modal to collect quantities
        qty_view = {
            "type": "modal",
            "callback_id": "qty_update_submit",
            "private_metadata": json.dumps({"style_id": style_id, "new_stage": new_stage}),
            "title": {"type": "plain_text", "text": "Update Quantities"},
            "submit": {"type": "plain_text", "text": "Save"},
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*{sty.brand}* • {sty.style_no} \nProvide quantities for the flow:"}},
                {"type": "input", "block_id": "cut", "optional": True,
                 "element": {"type": "plain_text_input", "action_id": "val"},
                 "label": {"type": "plain_text", "text": "Cutting qty"}},
                {"type": "input", "block_id": "stitch", "optional": True,
                 "element": {"type": "plain_text_input", "action_id": "val"},
                 "label": {"type": "plain_text", "text": "Stitching qty"}},
                {"type": "input", "block_id": "finish", "optional": True,
                 "element": {"type": "plain_text_input", "action_id": "val"},
                 "label": {"type": "plain_text", "text": "Finishing qty"}},
                {"type": "input", "block_id": "pack", "optional": True,
                 "element": {"type": "plain_text_input", "action_id": "val"},
                 "label": {"type": "plain_text", "text": "Packing qty"}},
            ],
        }
        ack(response_action="push", view=qty_view)
        return

    # Otherwise, just update and notify
    ack()
    update_style_stage(style_id, new_stage)
    client.chat_postMessage(
        channel=user_id,
        text=(f":truck: *Stage updated*\n"
              f"{sty.brand}·{sty.style_no} is now "
              f"*{STAGE_LABELS[new_stage]}*")
    )

# New handler: quantities modal submission (single)
@bolt_app.view("qty_update_submit")
def save_qty_update(ack, body, view, client, logger):
    try:
        meta = json.loads(view.get("private_metadata") or "{}")
        style_id = int(meta.get("style_id"))
        new_stage = int(meta.get("new_stage"))
    except Exception:
        logger.error("qty_update_submit: invalid private_metadata")
        ack(response_action="clear")
        return

    user_id = body["user"]["id"]
    sty = get_style_by_id(style_id)
    if not sty:
        logger.warning(f"Style {style_id} vanished in qty submit")
        ack(response_action="clear")
        return

    def _to_int(v):
        try:
            return int(v) if v is not None and str(v).strip() != "" else None
        except Exception:
            return None

    vals = view["state"]["values"]
    cut_qty    = _to_int(vals.get("cut", {}).get("val", {}).get("value"))
    stitch_qty = _to_int(vals.get("stitch", {}).get("val", {}).get("value"))
    finish_qty = _to_int(vals.get("finish", {}).get("val", {}).get("value"))
    pack_qty   = _to_int(vals.get("pack", {}).get("val", {}).get("value"))

    update_style_stage(style_id, new_stage)
    update_style_quantities(style_id, cut_qty=cut_qty, stitch_qty=stitch_qty, finish_qty=finish_qty, pack_qty=pack_qty)

    parts = [f":truck: *Stage updated*", f"{sty.brand}·{sty.style_no} is now *{STAGE_LABELS[new_stage]}*"]
    qparts = []
    if cut_qty is not None:    qparts.append(f"Cut: {cut_qty}")
    if stitch_qty is not None: qparts.append(f"Stitch: {stitch_qty}")
    if finish_qty is not None: qparts.append(f"Finish: {finish_qty}")
    if pack_qty is not None:   qparts.append(f"Pack: {pack_qty}")
    if qparts:
        parts.append("Quantities — " + ", ".join(qparts))
    parts.append("\nTo download a CSV of your styles, type `/export-csv`.")
    client.chat_postMessage(channel=user_id, text="\n".join(parts))
    ack(response_action="clear")

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
    # Parse desired changes first
    user_id = body["user"]["id"]
    prof = client.users_info(user=user_id)["user"]["profile"]
    merchant = prof.get("display_name") or prof["real_name"]

    desired_changes = []  # [{style_id, new_stage}]
    flow_changes = []     # subset where new_stage in flow
    for blk_id, blk_val in view["state"]["values"].items():
        if not blk_id.startswith("style_"):
            continue
        style_id = int(blk_id.split("_")[1])
        new_stage = int(blk_val["stage_select"]["selected_option"]["value"])
        sty = get_style_by_id(style_id)
        if not sty or sty.stage == new_stage:
            continue
        desired_changes.append({"style_id": style_id, "new_stage": new_stage})
        if new_stage in (8, 9, 10, 11, 12):
            flow_changes.append({"style_id": style_id, "new_stage": new_stage, "brand": sty.brand, "style_no": sty.style_no})

    # If any flow stages selected, push a quantity collection modal
    if flow_changes:
        # Build blocks asking for quantities for each flow style
        blocks = []
        for fc in flow_changes[:20]:  # safety cap
            sid = fc["style_id"]
            title = f"*{fc['brand']}* • {fc['style_no']}"
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": title}})
            blocks.append({"type": "input", "block_id": f"cut_{sid}", "optional": True,
                           "element": {"type": "plain_text_input", "action_id": "val"},
                           "label": {"type": "plain_text", "text": "Cutting qty"}})
            blocks.append({"type": "input", "block_id": f"stitch_{sid}", "optional": True,
                           "element": {"type": "plain_text_input", "action_id": "val"},
                           "label": {"type": "plain_text", "text": "Stitching qty"}})
            blocks.append({"type": "input", "block_id": f"finish_{sid}", "optional": True,
                           "element": {"type": "plain_text_input", "action_id": "val"},
                           "label": {"type": "plain_text", "text": "Finishing qty"}})
            blocks.append({"type": "input", "block_id": f"pack_{sid}", "optional": True,
                           "element": {"type": "plain_text_input", "action_id": "val"},
                           "label": {"type": "plain_text", "text": "Packing qty"}})
            blocks.append({"type": "divider"})

        ack(response_action="push", view={
            "type": "modal",
            "callback_id": "bulk_qty_submit",
            "private_metadata": json.dumps({"changes": desired_changes}),
            "title": {"type": "plain_text", "text": "Enter Quantities"},
            "submit": {"type": "plain_text", "text": "Save"},
            "blocks": blocks or [{"type": "section", "text": {"type": "mrkdwn", "text": "No changes."}}],
        })
        return

    # No flow stages: proceed with original logic
    ack()
    changes, dispatched = [], []
    for ch in desired_changes:
        style_id = ch["style_id"]
        new_stage = ch["new_stage"]
        sty = get_style_by_id(style_id)
        if not sty:
            continue
        update_style_stage(style_id, new_stage)
        if new_stage == 13:
            dispatched.append(f"{sty.brand}·{sty.style_no}")
        changes.append(f"{sty.brand}·{sty.style_no} → *{STAGE_LABELS[new_stage]}*")

    txt = ["✅ *Morning update received!*"]
    if changes:    txt += ["\n".join(changes)]
    if dispatched: txt += ["\n_Dispatched:_ " + ", ".join(dispatched)]
    txt += ["\nTo download a CSV of your styles, type `/export-csv`."]
    client.chat_postMessage(channel=user_id, text="\n".join(txt))

    harsh_id = get_harsh_user_id()
    if harsh_id and (changes or dispatched):
        summary = [f"Morning update from {merchant}:"]
        if changes:    summary += ["\n".join(changes)]
        if dispatched: summary += ["\n_Dispatched:_ " + ", ".join(dispatched)]
        try:
            bolt_app.client.chat_postMessage(channel=harsh_id, text="\n".join(summary))
        except Exception as e:
            print(f"Failed to send summary to Harsh Lalwani: {e}")

# New handler: bulk quantities submission
@bolt_app.view("bulk_qty_submit")
def handle_bulk_qty_submit(ack, body, view, client, logger):
    ack(response_action="clear")
    try:
        data = json.loads(view.get("private_metadata") or "{}")
        desired_changes = data.get("changes", [])
    except Exception:
        desired_changes = []

    user_id = body["user"]["id"]
    prof = client.users_info(user=user_id)["user"]["profile"]
    merchant = prof.get("display_name") or prof["real_name"]

    def _to_int(v):
        try:
            return int(v) if v is not None and str(v).strip() != "" else None
        except Exception:
            return None

    vals = view["state"]["values"]

    changes, dispatched = [], []
    for ch in desired_changes:
        style_id = int(ch["style_id"])
        new_stage = int(ch["new_stage"])
        sty = get_style_by_id(style_id)
        if not sty:
            continue
        update_style_stage(style_id, new_stage)
        cut_qty    = _to_int(vals.get(f"cut_{style_id}", {}).get("val", {}).get("value"))
        stitch_qty = _to_int(vals.get(f"stitch_{style_id}", {}).get("val", {}).get("value"))
        finish_qty = _to_int(vals.get(f"finish_{style_id}", {}).get("val", {}).get("value"))
        pack_qty   = _to_int(vals.get(f"pack_{style_id}", {}).get("val", {}).get("value"))
        qty_parts = []
        if cut_qty is not None:    qty_parts.append(f"Cut {cut_qty}")
        if stitch_qty is not None: qty_parts.append(f"Stitch {stitch_qty}")
        if finish_qty is not None: qty_parts.append(f"Finish {finish_qty}")
        if pack_qty is not None:   qty_parts.append(f"Pack {pack_qty}")
        if any(q is not None for q in (cut_qty, stitch_qty, finish_qty, pack_qty)):
            update_style_quantities(style_id, cut_qty=cut_qty, stitch_qty=stitch_qty, finish_qty=finish_qty, pack_qty=pack_qty)
        if new_stage == 13:
            dispatched.append(f"{sty.brand}·{sty.style_no}")
        change_line = f"{sty.brand}·{sty.style_no} → *{STAGE_LABELS[new_stage]}*"
        if qty_parts:
            change_line += " (" + ", ".join(qty_parts) + ")"
        changes.append(change_line)

    txt = ["✅ *Morning update received!*"]
    if changes:    txt += ["\n".join(changes)]
    if dispatched: txt += ["\n_Dispatched:_ " + ", ".join(dispatched)]
    txt += ["\nTo download a CSV of your styles, type `/export-csv`."]
    client.chat_postMessage(channel=user_id, text="\n".join(txt))

    harsh_id = get_harsh_user_id()
    if harsh_id and (changes or dispatched):
        summary = [f"Morning update from {merchant}:"]
        if changes:    summary += ["\n".join(changes)]
        if dispatched: summary += ["\n_Dispatched:_ " + ", ".join(dispatched)]
        try:
            bolt_app.client.chat_postMessage(channel=harsh_id, text="\n".join(summary))
        except Exception as e:
            print(f"Failed to send summary to Harsh Lalwani: {e}")

# ---------- Export CSV command ----------
@bolt_app.command("/export-csv")
def export_csv(ack, body, client, respond, logger):
    ack()
    respond(text=":hourglass_flowing_sand: Generating your CSV, I’ll DM it to you shortly…", response_type="ephemeral")
    try:
        user_id = body.get("user_id")
        profile = client.users_info(user=user_id)["user"]["profile"]
        merchant = profile.get("display_name") or profile["real_name"]
        rows = get_styles_by_merchant(merchant, active_only=True)
        # Build CSV
        buf = io.StringIO()
        writer = csv.writer(buf)
        header = [
            "Brand", "Style No", "Description", "Colour", "Stage", "Total Qty",
            "Total Cutting", "Cutting Balance",
            "Total Stitching", "Stitching Balance",
            "Total Finishing", "Finishing Balance",
            "Total Packing", "Packing Balance",
            "Dispatch Date", "Created At", "Active"
        ]
        writer.writerow(header)

        def norm_num(n):
            try:
                n_int = int(n)
                return "" if n_int <= 0 else n_int
            except Exception:
                return ""

        def balance(total, qty):
            try:
                t = int(total)
                q = int(qty)
                if t <= 0 or q <= 0:
                    return ""
                b = t - q
                return b if b >= 0 else 0
            except Exception:
                return ""

        for r in rows:
            total_qty = getattr(r, "total_qty", None)
            cut = getattr(r, "cut_qty", None)
            stitch = getattr(r, "stitch_qty", None)
            finish = getattr(r, "finish_qty", None)
            pack = getattr(r, "pack_qty", None)

            writer.writerow([
                r.brand,
                r.style_no,
                r.garment,
                r.colour,
                STAGE_LABELS[r.stage],
                norm_num(total_qty) if isinstance(total_qty, int) else (total_qty if isinstance(total_qty, str) else total_qty) or "",
                norm_num(cut),
                balance(total_qty, cut),
                norm_num(stitch),
                balance(total_qty, stitch),
                norm_num(finish),
                balance(total_qty, finish),
                norm_num(pack),
                balance(total_qty, pack),
                getattr(r, "dispatch_date", "") or "",
                r.created_at.isoformat(),
                getattr(r, "active", True),
            ])
        content = buf.getvalue()
        buf.close()

        # Open IM and upload file (use v2 API for robustness)
        im = client.conversations_open(users=user_id)
        channel_id = im["channel"]["id"]
        filename = f"styles_{merchant.replace(' ', '_').lower()}.csv"
        try:
            client.files_upload_v2(
                channel=channel_id,
                initial_comment=":arrow_down: Here is your CSV export of active styles.",
                filename=filename,
                content=content,
                title=f"{merchant} styles export",
                filetype="csv",
            )
        except Exception as upload_err:
            # Fallback to legacy API
            client.files_upload(
                channels=channel_id,
                content=content,
                filename=filename,
                filetype="csv",
                initial_comment=":arrow_down: Here is your CSV export of active styles.",
                title=f"{merchant} styles export"
            )
        respond(text=":white_check_mark: Sent you a DM with the CSV.", response_type="ephemeral")
    except Exception as e:
        logger.error(f"/export-csv failed: {e}")
        respond(text=f":warning: Failed to generate CSV: {e}", response_type="ephemeral")


flask_app = Flask(__name__)     # single Flask wrapper
handler = SlackRequestHandler(bolt_app)

@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)   # Bolt handles URL-verification, etc.

@flask_app.route("/slack/command", methods=["POST"])
def slack_command():
    return handler.handle(request)   # Bolt handles slash commands

@flask_app.route("/healthz", methods=["GET"])
def healthz():
    return "ok", 200


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
                  "label": { "type": "plain_text", "text": "Colour" } },

                { "type": "input", "block_id": "total_qty",
                  "optional": True,
                  "element": { "type": "plain_text_input", "action_id": "val" },
                  "label": { "type": "plain_text", "text": "Total Quantity (optional)" } },

                { "type": "input", "block_id": "dispatch_date",
                  "optional": True,
                  "element": { "type": "plain_text_input", "action_id": "val", "placeholder": {"type":"plain_text","text":"YYYY-MM-DD"}},
                  "label": { "type": "plain_text", "text": "Dispatch Date (optional)" } }
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
                      "label": { "type": "plain_text", "text": "Colour" } },

                    { "type": "input", "block_id": "total_qty",
                      "optional": True,
                      "element": { "type": "plain_text_input", "action_id": "val" },
                      "label": { "type": "plain_text", "text": "Total Quantity (optional)" } },

                    { "type": "input", "block_id": "dispatch_date",
                      "optional": True,
                      "element": { "type": "plain_text_input", "action_id": "val", "placeholder": {"type":"plain_text","text":"YYYY-MM-DD"}},
                      "label": { "type": "plain_text", "text": "Dispatch Date (optional)" } }
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
                      "label": { "type": "plain_text", "text": "Colour" } },

                    { "type": "input", "block_id": "total_qty",
                      "optional": True,
                      "element": { "type": "plain_text_input", "action_id": "val" },
                      "label": { "type": "plain_text", "text": "Total Quantity (optional)" } },

                    { "type": "input", "block_id": "dispatch_date",
                      "optional": True,
                      "element": { "type": "plain_text_input", "action_id": "val", "placeholder": {"type":"plain_text","text":"YYYY-MM-DD"}},
                      "label": { "type": "plain_text", "text": "Dispatch Date (optional)" } }
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

    def _to_int(v):
        try:
            return int(v) if v is not None and str(v).strip() != "" else None
        except Exception:
            return None

    total_qty = _to_int(vals.get("total_qty", {}).get("val", {}).get("value"))
    dispatch_date = vals.get("dispatch_date", {}).get("val", {}).get("value")
    if dispatch_date is not None and str(dispatch_date).strip() == "":
        dispatch_date = None

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
        total_qty=total_qty,
        dispatch_date=dispatch_date,
    )

    logger.info(f"New style from {user_id}: {brand}-{style_no}")

    msg = (
        f"• *Brand:* {brand}\n"
        f"• *Style No.:* {style_no}\n"
        f"• *Type:* {garment}\n"
        f"• *Colour:* {color}"
    )
    if total_qty is not None:
        msg += f"\n• *Total Qty:* {total_qty}"
    if dispatch_date:
        msg += f"\n• *Dispatch Date:* {dispatch_date}"
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
                            "`/update-stage` – Update the production stage of an existing style\n"
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

# Use Slack user group to control who receives reminders
MERCHANT_USERGROUP_HANDLE = "merchant"

def _get_user_scoped_client() -> WebClient:
    """Return a WebClient using a user token if provided, else the bot token.
    For usergroups.* APIs, Slack typically requires a user token with usergroups:read.
    """
    user_token = os.environ.get("SLACK_USER_TOKEN")
    if user_token:
        return WebClient(token=user_token)
    # Fallback to bot token (may fail with missing_scope)
    return WebClient(token=os.environ.get("SLACK_BOT_TOKEN"))


def get_usergroup_member_ids(handle_or_name: str = MERCHANT_USERGROUP_HANDLE):
    """Return a set of Slack user IDs who are members of the given user group.
    Requires appropriate Slack scopes (usergroups:read) on a user token.
    """
    try:
        client_user = _get_user_scoped_client()
        usergroups = client_user.usergroups_list().get("usergroups", [])
        target = next(
            (
                ug for ug in usergroups
                if ug.get("handle", "").lower() == handle_or_name.lower()
                or ug.get("name", "").lower() == handle_or_name.lower()
            ),
            None,
        )
        if not target:
            print(f"User group '{handle_or_name}' not found. Check the handle/name.")
            return set()
        users = client_user.usergroups_users_list(usergroup=target["id"]).get("users", [])
        return set(users)
    except Exception as e:
        print(
            "Could not fetch user group members. Likely missing 'SLACK_USER_TOKEN' with usergroups:read. "
            f"Error: {e}"
        )
        return set()

def send_daily_reminder():
    # Fetch Slack user IDs that are members of the merchant user group
    merchant_group_member_ids = get_usergroup_member_ids(MERCHANT_USERGROUP_HANDLE)
    if not merchant_group_member_ids:
        print("No members found in 'merchant' user group or missing scope; skipping reminders.")
        return

    # Fetch all users to filter out bots/deactivated and for logging if needed
    try:
        members = bolt_app.client.users_list().get("members", [])
        id_to_member = {m.get("id"): m for m in members}
    except Exception as e:
        print(f"Could not fetch Slack users_list: {e}")
        id_to_member = {}

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

    for user_id in sorted(merchant_group_member_ids):
        m = id_to_member.get(user_id, {})
        if m.get("deleted") or m.get("is_bot") or m.get("id") is None:
            continue
        try:
            # Ensure we have an open DM channel to the user
            im = bolt_app.client.conversations_open(users=user_id)
            channel_id = im["channel"]["id"]
            bolt_app.client.chat_postMessage(channel=channel_id, text=msg)
        except Exception as e:
            print(f"Failed to send DM to {user_id}: {e}")

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

@bolt_app.command("/remind-merchants")
def remind_merchants(ack, body, client, respond, logger):
    ack()
    try:
        user_id = body.get("user_id")
        prof = client.users_info(user=user_id)["user"]["profile"]
        caller_name = prof.get("display_name") or prof.get("real_name")
        if caller_name != "Aaryan":
            respond(text=":no_entry: You are not authorized to use this command.", response_type="ephemeral")
            return
        # Trigger the same reminder flow used by the daily scheduler
        send_daily_reminder()
        respond(text=":white_check_mark: Morning reminder sent to the merchant group.", response_type="ephemeral")
    except Exception as e:
        logger.error(f"/remind-merchants failed: {e}")
        respond(text=":warning: Failed to send reminders. Please try again.", response_type="ephemeral")

@bolt_app.command("/edit-style")
def open_edit_style_selector(ack, body, client):
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

    style_opts = [{
        "text":  { "type":"plain_text",
                   "text": f"{r.brand}·{r.style_no} ({r.garment})" },
        "value": str(r.id)
    } for r in rows]

    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type":"modal",
            "callback_id":"edit_style_select_submit",
            "title":  { "type":"plain_text", "text":"Edit Style" },
            "submit": { "type":"plain_text", "text":"Next" },
            "blocks":[
                { "type":"input", "block_id":"style",
                  "element": { "type":"static_select",
                               "action_id":"val",
                               "options":style_opts },
                  "label": { "type":"plain_text", "text":"Select Style" }}
            ]
        }
    )

@bolt_app.view("edit_style_select_submit")
def open_prefilled_edit_modal(ack, body, view, client, logger):
    ack()
    try:
        style_id = int(view["state"]["values"]["style"]["val"]["selected_option"]["value"])
    except Exception:
        return
    sty = get_style_by_id(style_id)
    if not sty:
        return

    def txt(v):
        return {"type":"plain_text_input", "action_id":"val", "initial_value": str(v) if v is not None else ""}

    blocks = [
        {"type":"section", "text": {"type":"mrkdwn", "text": f"*Editing:* {sty.brand} • {sty.style_no}"}},
        {"type":"input", "block_id":"brand", "element": txt(sty.brand), "label": {"type":"plain_text", "text":"Brand"}},
        {"type":"input", "block_id":"style_no", "element": txt(sty.style_no), "label": {"type":"plain_text", "text":"Exact Style No."}},
        {"type":"input", "block_id":"garment", "element": txt(sty.garment), "label": {"type":"plain_text", "text":"Garment Type"}},
        {"type":"input", "block_id":"color", "element": txt(sty.colour), "label": {"type":"plain_text", "text":"Colour"}},
        {"type":"input", "block_id":"total_qty", "optional": True, "element": txt(getattr(sty, "total_qty", "") or ""), "label": {"type":"plain_text", "text":"Total Quantity (optional)"}},
        {"type":"input", "block_id":"dispatch_date", "optional": True, "element": txt(getattr(sty, "dispatch_date", "") or ""), "label": {"type":"plain_text", "text":"Dispatch Date (optional)"}},
    ]

    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type":"modal",
            "callback_id":"edit_style_submit",
            "private_metadata": json.dumps({"style_id": style_id}),
            "title":  { "type":"plain_text", "text":"Edit Style" },
            "submit": { "type":"plain_text", "text":"Save" },
            "blocks": blocks
        }
    )

@bolt_app.view("edit_style_submit")
def handle_edit_style_submit(ack, body, view, client, logger):
    ack(response_action="clear")
    try:
        meta = json.loads(view.get("private_metadata") or "{}")
        style_id = int(meta.get("style_id"))
    except Exception:
        return

    vals = view["state"]["values"]
    def _get(block):
        return vals.get(block, {}).get("val", {}).get("value")

    def _to_int(v):
        try:
            return int(v) if v is not None and str(v).strip() != "" else None
        except Exception:
            return None

    brand = _get("brand")
    style_no = _get("style_no")
    garment = _get("garment")
    colour = _get("color")
    total_qty = _to_int(_get("total_qty"))
    dispatch_date = _get("dispatch_date")
    if dispatch_date is not None and str(dispatch_date).strip() == "":
        dispatch_date = None

    update_style_info(
        style_id,
        brand=brand,
        style_no=style_no,
        garment=garment,
        colour=colour,
        total_qty=total_qty,
        dispatch_date=dispatch_date,
    )

    user_id = body["user"]["id"]
    client.chat_postMessage(
        channel=user_id,
        text=(
            ":white_check_mark: Style updated!\n"
            f"• Brand: {brand}\n"
            f"• Style No.: {style_no}\n"
            f"• Type: {garment}\n"
            f"• Colour: {colour}\n"
            + (f"• Total Qty: {total_qty}\n" if total_qty is not None else "")
            + (f"• Dispatch Date: {dispatch_date}\n" if dispatch_date else "")
        )
    )


@flask_app.route("/")
def index():
    return "✅ Slack bot is live!", 200

@flask_app.route("/ping")
def ping():
    return "pong", 200


if __name__ == "__main__":
    # Optional: print every incoming request for quick debugging
    import logging, sys, time
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

    # Local dev: run Flask; optional scheduler
    if os.getenv("RUN_SCHEDULER") == "1":
        start_scheduler()
        print("Scheduler started (RUN_SCHEDULER=1). Keeping process alive...")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    else:
        # Local dev server only; on Render use Gunicorn to serve flask_app
        start_scheduler()
        flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
