# Slack Style Management Bot

A Slack bot for managing fashion styles with local SQLite database storage.

## Features

- **Slash Commands**: `/add-style` to add new styles via modal
- **Stage Management**: `/update-stage` to progress styles through the workflow
- **Style Tracking**: `/current-styles` to view active styles with current stages
- **Custom Garment Types**: When "Other" is selected, users can type custom garment types
- **Local Database**: All data stored in SQLite for portability and simplicity
- **User-Friendly**: Simple modal interface for style entry
- **Workflow Stages**: 14-stage workflow from Pre-fit to Dispatch

## Setup

### 1. Install Dependencies

```bash
pip install slack-bolt[flask] sqlalchemy python-dotenv
```

### 2. Environment Variables

Create a `.env` file with your Slack credentials:

```env
SLACK_BOT_TOKEN=xoxb-your-bot-token-here
SLACK_SIGNING_SECRET=your-signing-secret-here
```

### 3. Initialize Database

```bash
python3 database_setup.py
```

### 4. Run the Bot

```bash
python3 app.py
```

## Database Structure

The bot uses SQLite with the following table structure:

```sql
CREATE TABLE styles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant VARCHAR(64) NOT NULL,
    brand VARCHAR(64) NOT NULL,
    style_no VARCHAR(64) NOT NULL,
    garment VARCHAR(64) NOT NULL,
    colour VARCHAR(64) NOT NULL,
    stage INTEGER DEFAULT 0,
    active BOOLEAN DEFAULT TRUE,
    bulk_eta DATE,
    acc_barcode VARCHAR,
    acc_trims VARCHAR,
    acc_washcare VARCHAR,
    acc_other VARCHAR,
    stitch_qty INTEGER,
    finish_qty INTEGER,
    pack_qty INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## Usage

### Adding Styles

1. Type `/add-style` in any Slack channel
2. Fill out the modal with:
   - Brand
   - Style Number
   - Garment Type (select from dropdown or choose "Other" for custom)
   - Colour
3. Click "Save"

### Managing Stages

1. Type `/update-stage` to open the stage update modal
2. Select the style you want to update
3. Choose the new stage from the dropdown
4. Click "Save"

### Viewing Styles

1. Type `/current-styles` to see all your active styles
2. Shows: Brand • Style No • Garment • Colour • Current Stage

### Workflow Stages

The system supports 14 stages:
1. Pre-fit
2. Fit
3. Bulk
4. Bulk in-house
5. FPT
6. GPT
7. PP
8. Accessories in-house
9. Cutting sheet
10. Stitching
11. Finishing
12. Inline
13. Packing
14. Dispatch

When a style reaches "Dispatch" (stage 13), it's automatically marked as inactive and removed from the active styles list.

### Database Operations

The `database_setup.py` file provides these functions:

- `add_style(merchant, brand, style_no, garment, colour)` - Add new style
- `get_styles_by_merchant(merchant)` - Get styles for specific merchant
- `get_all_styles()` - Get all styles
- `update_style_stage(style_id, stage)` - Update style stage
- `backup_database()` - Create daily backup

## File Structure

```
slack_bot/
├── app.py              # Main Slack bot application
├── database_setup.py   # Database configuration and functions
├── test_db.py         # Database testing script
├── production.db      # SQLite database file
├── .env              # Environment variables
└── README.md         # This file
```

## Testing

Run the database test:

```bash
python3 test_db.py
```

## Backup

The database is stored in `production.db`. For backups:

```bash
python3 -c "from database_setup import backup_database; backup_database()"
```

## Slack App Configuration

Make sure your Slack app has:

1. **Bot Token Scopes**:
   - `chat:write`
   - `commands`
   - `users:read`

2. **Slash Commands**:
   - `/add-style` pointing to your server's `/slack/command` endpoint
   - `/update-stage` pointing to your server's `/slack/command` endpoint
   - `/current-styles` pointing to your server's `/slack/command` endpoint

3. **Event Subscriptions**:
   - Request URL: `https://your-domain.com/slack/events`
   - Subscribe to bot events: `message.channels`

## Development

The bot runs on port 3000 by default. For production, use a proper WSGI server like Gunicorn:

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:3000 app:flask_app
``` # garment-bot
