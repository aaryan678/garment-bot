# Slack Style Management Bot

A Slack bot for managing fashion styles with local TinyDB (JSON) storage.

## Features

- **Slash Commands**: `/add-style` to add new styles via modal
- **Stage Management**: `/update-stage` to progress styles through the workflow
- **Style Tracking**: `/current-styles` to view active styles with current stages
- **Custom Garment Types**: When "Other" is selected, users can type custom garment types
- **Local Database**: All data stored in a TinyDB JSON file for portability and simplicity
- **User-Friendly**: Simple modal interface for style entry
- **Workflow Stages**: 14-stage workflow from Pre-fit to Dispatch

## Setup

### 1. Install Dependencies

```bash
pip install slack-bolt[flask] tinydb python-dotenv
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

The bot now uses [TinyDB](https://tinydb.readthedocs.io/), which stores JSON
documents on disk (`production.json`). Each style is saved with fields such as
`merchant`, `brand`, `style_no`, `garment`, `colour`, and workflow `stage`.

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
├── app.py            # Main Slack bot application
├── database_setup.py # TinyDB configuration and helpers
├── production.json   # TinyDB data file (created at runtime)
├── .env              # Environment variables
└── README.md         # This file
```

## Backup

The database is stored in `production.json`. To create a backup:

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
```
