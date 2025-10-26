import os
import datetime
import discord
from discord.ext import commands
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Load environment variables
load_dotenv()

# Google Calendar API scopes
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix='!', intents=intents)


def get_calendar_service():
    """
    Authenticate and return a Google Calendar API service object.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    
    # If there are no (valid) credentials available, let the user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    
    return build("calendar", "v3", credentials=creds)


def fetch_calendar_events(max_results=10):
    """
    Fetch upcoming events from Google Calendar.
    
    Args:
        max_results: Maximum number of events to fetch
        
    Returns:
        List of calendar events
    """
    try:
        service = get_calendar_service()
        
        # Get events from now onwards
        now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        
        events = events_result.get("items", [])
        return events
        
    except HttpError as error:
        print(f"An error occurred fetching calendar events: {error}")
        return []


def parse_event_time(event):
    """
    Parse event start and end times from calendar event.
    
    Args:
        event: Google Calendar event dictionary
        
    Returns:
        Tuple of (start_time, end_time) as datetime objects
    """
    start = event["start"].get("dateTime", event["start"].get("date"))
    end = event["end"].get("dateTime", event["end"].get("date"))
    
    # Parse datetime strings
    if "T" in start:  # DateTime format
        start_time = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_time = datetime.datetime.fromisoformat(end.replace("Z", "+00:00"))
    else:  # Date only format
        start_time = datetime.datetime.fromisoformat(start + "T00:00:00+00:00")
        end_time = datetime.datetime.fromisoformat(end + "T23:59:59+00:00")
    
    return start_time, end_time


async def create_discord_event(guild, event):
    """
    Create a scheduled event on Discord based on a calendar event.
    
    Args:
        guild: Discord guild (server) object
        event: Google Calendar event dictionary
        
    Returns:
        Created Discord scheduled event or None if failed
    """
    try:
        start_time, end_time = parse_event_time(event)
        
        # Discord requires timezone-aware datetime objects
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=datetime.timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=datetime.timezone.utc)
        
        # Get event details
        summary = event.get("summary", "Untitled Event")
        description = event.get("description", "")
        location = event.get("location", "")
        
        # Combine description and location
        full_description = description
        if location:
            full_description = f"{description}\n\nLocation: {location}" if description else f"Location: {location}"
        
        # Truncate description if too long (Discord has a 1000 character limit)
        if len(full_description) > 1000:
            full_description = full_description[:997] + "..."
        
        # Create scheduled event on Discord
        discord_event = await guild.create_scheduled_event(
            name=summary[:100],  # Discord has a 100 character limit for event names
            description=full_description,
            start_time=start_time,
            end_time=end_time,
            entity_type=discord.EntityType.external,
            location=location[:100] if location else "See description"
        )
        
        return discord_event
        
    except Exception as e:
        print(f"Error creating Discord event: {e}")
        return None


@bot.event
async def on_ready():
    """
    Event handler called when the bot successfully connects to Discord.
    """
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is in {len(bot.guilds)} guild(s)')


@bot.command(name='sync_events')
async def sync_events(ctx, count: int = 10):
    """
    Sync upcoming Google Calendar events to Discord.
    
    Usage: !sync_events [count]
    
    Args:
        count: Number of events to sync (default: 10)
    """
    await ctx.send(f"Fetching {count} upcoming events from Google Calendar...")
    
    # Fetch calendar events
    events = fetch_calendar_events(max_results=count)
    
    if not events:
        await ctx.send("No upcoming events found in Google Calendar.")
        return
    
    await ctx.send(f"Found {len(events)} events. Creating Discord events...")
    
    # Create Discord events
    created_count = 0
    failed_count = 0
    
    for event in events:
        summary = event.get("summary", "Untitled Event")
        discord_event = await create_discord_event(ctx.guild, event)
        
        if discord_event:
            created_count += 1
            print(f"Created Discord event: {summary}")
        else:
            failed_count += 1
            print(f"Failed to create Discord event: {summary}")
    
    # Send summary
    result_message = f"✅ Successfully created {created_count} Discord event(s)"
    if failed_count > 0:
        result_message += f"\n⚠️ Failed to create {failed_count} event(s)"
    
    await ctx.send(result_message)


@bot.command(name='list_events')
async def list_events(ctx, count: int = 5):
    """
    List upcoming Google Calendar events.
    
    Usage: !list_events [count]
    
    Args:
        count: Number of events to list (default: 5)
    """
    events = fetch_calendar_events(max_results=count)
    
    if not events:
        await ctx.send("No upcoming events found in Google Calendar.")
        return
    
    message = "📅 **Upcoming Calendar Events:**\n\n"
    
    for event in events:
        summary = event.get("summary", "Untitled Event")
        start = event["start"].get("dateTime", event["start"].get("date"))
        message += f"• **{summary}**\n  {start}\n\n"
    
    await ctx.send(message)


def main():
    """
    Main function to run the Discord bot.
    """
    # Get Discord bot token from environment variable
    token = os.getenv("DISCORD_BOT_TOKEN")
    
    if not token:
        print("Error: DISCORD_BOT_TOKEN not found in environment variables")
        print("Please create a .env file with your Discord bot token")
        return
    
    # Run the bot
    try:
        bot.run(token)
    except Exception as e:
        print(f"Error running bot: {e}")


if __name__ == "__main__":
    main()
