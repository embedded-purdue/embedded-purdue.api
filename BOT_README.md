# Discord Bot Setup and Usage

This Discord bot integrates with Google Calendar API to sync calendar events to Discord scheduled events.

## Features

- Fetch upcoming events from Google Calendar
- Create Discord scheduled events based on calendar events
- List upcoming calendar events in Discord
- Configurable number of events to sync

## Prerequisites

1. Python 3.7 or higher
2. Google Calendar API credentials
3. Discord bot token

## Setup Instructions

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Google Calendar API Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Google Calendar API
4. Create OAuth 2.0 credentials (Desktop application type)
5. Download the credentials and save as `credentials.json` in the project root
6. Run the bot for the first time - it will open a browser for authentication
7. The `token.json` file will be created automatically after authentication

### 3. Discord Bot Setup

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to the "Bot" section and click "Add Bot"
4. Under "Privileged Gateway Intents", enable:
   - Message Content Intent
   - Server Members Intent
5. Copy the bot token
6. Go to OAuth2 > URL Generator
7. Select scopes: `bot` and `applications.commands`
8. Select bot permissions:
   - Manage Events
   - Send Messages
   - Read Messages/View Channels
9. Use the generated URL to invite the bot to your Discord server

### 4. Configure Environment Variables

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your Discord bot token:
   ```
   DISCORD_BOT_TOKEN=your_actual_bot_token_here
   ```

## Running the Bot

```bash
python bot.py
```

On first run, the bot will open a browser window for Google Calendar authentication.

## Bot Commands

### `!sync_events [count]`
Syncs upcoming Google Calendar events to Discord scheduled events.

**Usage:**
```
!sync_events        # Sync 10 events (default)
!sync_events 5      # Sync 5 events
```

### `!list_events [count]`
Lists upcoming Google Calendar events in the Discord channel.

**Usage:**
```
!list_events        # List 5 events (default)
!list_events 10     # List 10 events
```

## File Structure

- `bot.py` - Main Discord bot implementation
- `requirements.txt` - Python dependencies
- `credentials.json` - Google Calendar API credentials (not in repo)
- `token.json` - Google Calendar API token (auto-generated, not in repo)
- `.env` - Environment variables for bot token (not in repo)
- `.env.example` - Template for environment variables

## Troubleshooting

### Bot doesn't respond to commands
- Ensure the bot has "Message Content Intent" enabled in Discord Developer Portal
- Check that the bot has permission to read messages in your server

### Google Calendar authentication fails
- Make sure `credentials.json` is in the correct location
- Delete `token.json` and re-authenticate if you encounter auth errors

### Events not creating on Discord
- Ensure the bot has "Manage Events" permission
- Check that event times are in the future (Discord doesn't allow past events)

## Security Notes

- Never commit `credentials.json`, `token.json`, or `.env` to version control
- These files are already in `.gitIgnore`
- Keep your Discord bot token secret
