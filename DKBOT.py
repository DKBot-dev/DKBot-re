import discord
from discord.ext import commands, tasks
import threading
from dotenv import load_dotenv
import os
import logging
import datetime
import asyncio
from twitchAPI.twitch import Twitch
from twitchAPI.oauth import UserAuthenticator  # Correct import for user authentication
from twitchAPI.oauth import AuthScope  # Correct import for OAuth scopes

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
TWITCH_USERNAME = os.getenv("TWITCH_USERNAME")
LOOP_INTERVAL = int(os.getenv("LOOP_INTERVAL", 30))
GUILD_ID = int(os.getenv("GUILD_ID"))

# Validate environment variables
if not DISCORD_BOT_TOKEN or not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET or not DISCORD_CHANNEL_ID:
    raise ValueError("Missing environment variables. Check your .env file.")

# Initialize Discord bot using commands.Bot for slash commands
intents = discord.Intents.default()  # Add intents if needed
intents.message_content = True

bot = commands.Bot(command_prefix='/', intents=intents)

# Initialize the Twitch object
twitch = Twitch(TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET)

# Setup Twitch API with your Client ID and Secret
twitch = Twitch("your_client_id", "your_client_secret")

# Define the authenticate_twitch function
async def authenticate_twitch():
    try:
        twitch = await Twitch(TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET)
        await twitch.authenticate_app([])
        print("Twitch Authentication successful.")
    except Exception as e:
        print(f"Error authenticating with Twitch: {e}")

# State management class
class LiveStatus:
    def __init__(self):
        self.twitch_live = False
        self.tiktok_live = False
        self.last_message_id = None
        self.twitch_live_since = None  # Track when Twitch went live
        self.tiktok_live_since = None  # Track when TikTok went live

live_status = LiveStatus()

# Flag to manage TikTok synchronization with Twitch
sync_tiktok_with_twitch = False  # Default is off (independent)


# Function to get Twitch stream data
async def get_twitch_stream_data(username):
    try:
        # Fetch user info from Twitch
        user_info_generator = twitch.get_users(logins=[username])  # This is an async generator
        user_info = await anext(user_info_generator, None)  # Get first result safely

        # Debug: Print user info
        print(f"User Info: {user_info}")

        if not user_info or not user_info["data"]:
            return False, None, None

        user_id = user_info["data"][0]["id"]
        streams_generator = twitch.get_streams(user_id=user_id)  # This is an async generator

        # Fetch stream info
        async for stream in streams_generator:  # Iterate over async generator
            # Debug: Print stream info
            print(f"Authenticated: {twitch.user.id}")
            print(f"User Info: {user_info}")
            print(f"Stream Info: {stream}")

            started_at = datetime.datetime.strptime(stream["started_at"], "%Y-%m-%dT%H:%M:%SZ")
            started_at_epoch = int(started_at.timestamp())
            return True, stream.get("game_name", "Unknown Game"), started_at_epoch

    except Exception as e:
        logger.error(f"Twitch API Error: {e}")
    return False, None, None


# List of user IDs allowed to run admin commands without admin permission
allowed_admins = ["703983156063109211", "359342822517768192"]  # Replace with actual user IDs

# Register slash commands using bot.tree.command (instead of bot.command)
@bot.tree.command(name='tiktokislive', description="Set TikTok as live.")
async def tiktokislive(interaction: discord.Interaction):
    if not (interaction.user.guild_permissions.administrator or str(interaction.user.id) in allowed_admins):
        await interaction.response.send_message("You don't have permission to run this command.", ephemeral=True)
        return

    live_status.tiktok_live = True
    live_status.tiktok_live_since = int(datetime.datetime.now().timestamp())  # Set the time when TikTok went live
    message = await interaction.response.send_message("TikTok is now live.", ephemeral=True)
    
    if message:
        await asyncio.sleep(30)  # Wait for 30 seconds
        await message.delete()  # Delete the message after 30 seconds
        await update_live_status()  # Trigger live status update to send embed

        # Trigger live status update with no changes to Twitch live state
    await update_live_status(skip_twitch_api=True)  # Pass skip_twitch_api to avoid API calls

@bot.tree.command(name='tiktokisoffline', description="Set TikTok as offline.")
async def tiktokisoffline(interaction: discord.Interaction):
    if not (interaction.user.guild_permissions.administrator or str(interaction.user.id) in allowed_admins):
        await interaction.response.send_message("You don't have permission to run this command.", ephemeral=True)
        return

    live_status.tiktok_live = False
    live_status.tiktok_live_since = None  # Reset the TikTok live time
    message = await interaction.response.send_message("TikTok is now offline.", ephemeral=True)
    
    if message:
        await asyncio.sleep(30)  # Wait for 30 seconds
        await message.delete()  # Delete the message after 30 seconds
        await update_live_status()  # Trigger live status update to send embed

        # Skip Twitch API call to avoid 403 error
    await update_live_status(skip_twitch_api=True)  # Trigger live status update without checking Twitch API    

@bot.tree.command(name='twitchislive', description="Set Twitch as live.")
async def twitchislive(interaction: discord.Interaction):
    if not (interaction.user.guild_permissions.administrator or str(interaction.user.id) in allowed_admins):
        await interaction.response.send_message("You don't have permission to run this command.", ephemeral=True)
        return

    live_status.twitch_live = True
    live_status.twitch_live_since = int(datetime.datetime.now().timestamp())  # Set the time when Twitch went live
    message = await interaction.response.send_message("Twitch is now live.", ephemeral=True)
    
    if message:
        await asyncio.sleep(30)  # Wait for 30 seconds
        await message.delete()  # Delete the message after 30 seconds
        await update_live_status()

        # Skip Twitch API call to avoid 403 error
    await update_live_status(skip_twitch_api=True)  # Trigger live status update without checking Twitch API
       
@bot.tree.command(name='twitchisoffline', description="Set Twitch as offline.")
async def twitchisoffline(interaction: discord.Interaction):
    if not (interaction.user.guild_permissions.administrator or str(interaction.user.id) in allowed_admins):
        await interaction.response.send_message("You don't have permission to run this command.", ephemeral=True)
        return

    live_status.twitch_live = False
    live_status.twitch_live_since = None  # Reset the Twitch live time
    message = await interaction.response.send_message("Twitch is now offline.", ephemeral=True)

    if message:
        await asyncio.sleep(30)  # Wait for 30 seconds
        await message.delete()  # Delete the message after 30 seconds
        await update_live_status()    

        # Skip Twitch API call to avoid 403 error
    await update_live_status(skip_twitch_api=True)  # Trigger live status update without checking Twitch API

@bot.tree.command(name='sync', description="Sync TikTok with Twitch live status.")
async def sync(interaction: discord.Interaction, status: str):
    # Check if the user has admin permissions or is in the allowed admin list
    if not (interaction.user.guild_permissions.administrator or str(interaction.user.id) in allowed_admins):
        await interaction.response.send_message("You don't have permission to run this command.", ephemeral=True)
        return

    global sync_tiktok_with_twitch

    # Handle the "on" case (TikTok follows Twitch)
    if status.lower() == 'on':
        sync_tiktok_with_twitch = True
        await interaction.response.send_message("TikTok will now follow Twitch's live status.", ephemeral=True)

    # Handle the "off" case (TikTok operates independently)
    elif status.lower() == 'off':
        sync_tiktok_with_twitch = False
        await interaction.response.send_message("TikTok will now operate independently of Twitch's live status.", ephemeral=True)

    # If invalid input is given, inform the user
    else:
        await interaction.response.send_message("Invalid option. Please choose 'on' or 'off'.", ephemeral=True)

# Example function to update live status
async def update_live_status(skip_twitch_api=False):
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if not channel:
        logger.error(f"Channel with ID {DISCORD_CHANNEL_ID} not found.")
        return

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        logger.error(f"Guild with ID {GUILD_ID} not found.")
        return

    role = guild.get_role(806578667940872214)  # Adjust role ID
    if not role:
        logger.error("Role with ID 806578667940872214 not found.")
        return

    # Define live and offline banners
    live_banner_url = "https://cdn.discordapp.com/attachments/1308131426910077100/1333883905945763940/Picsart_25-01-26_14-28-59-723.jpg?ex=67a466f1&is=67a31571&hm=ee1ec2978e204424ec2a80f16dc622f7944e95c5fe6b29bc6487bf44b89b0830&"
    offline_banner_url = "https://cdn.discordapp.com/attachments/1308131426910077100/1336392772151803986/Picsart_25-02-04_18-47-31-649.jpg?ex=67a4f5c1&is=67a3a441&hm=cd6b2ea11b73ee52c26583f81d9c44312251d05b34ae98fe9d75cb517f856875&"

    # Initialize embed variable
    embed = None

    # Only call Twitch API if we are not skipping it
    if not skip_twitch_api:
        # Get Twitch stream data
        twitch_live, twitch_game, twitch_started_at = await get_twitch_stream_data(TWITCH_USERNAME)
    else:
        twitch_live, twitch_game, twitch_started_at = live_status.twitch_live, None, live_status.twitch_live_since

    if sync_tiktok_with_twitch:  # Sync TikTok with Twitch
        live_status.tiktok_live = twitch_live

    # Set TikTok start time
    if live_status.tiktok_live and live_status.tiktok_live_since is None:
        live_status.tiktok_live_since = int(datetime.datetime.now().timestamp())  # Capture timestamp when TikTok goes live

    if not live_status.tiktok_live:
        live_status.tiktok_live_since = None  # Reset if offline

    # Check if both Twitch and TikTok are live
    if twitch_live and live_status.tiktok_live:
        embed = discord.Embed(
            title="DKsonic195 is Live on Twitch and TikTok!",
            description=f"|| {role.mention} ||\nCatch the streams on:\n"
                        f"- Twitch: [Link](https://www.twitch.tv/{TWITCH_USERNAME})\n"
                        f"- TikTok: [Link](https://www.tiktok.com/@dksonic195/live)",
            color=0x1DB954
        )

        if twitch_started_at:
            embed.add_field(name="Time Went Live (Twitch)", value=f"<t:{twitch_started_at}:R>", inline=False)

        if live_status.tiktok_live_since:
            embed.add_field(name="Time Went Live (TikTok)", value=f"<t:{live_status.tiktok_live_since}:R>", inline=False)

        embed.set_image(url=live_banner_url)

    # Check if Twitch is live but TikTok is not
    elif twitch_live:
        embed = discord.Embed(
            title="DKsonic195 is Live on Twitch!",
            description=f"|| {role.mention} ||\nCatch the stream on:\n"
                        f"- Twitch: [Link](https://www.twitch.tv/{TWITCH_USERNAME})",
            color=0x6441A5
        )

        if twitch_started_at:
            embed.add_field(name="Time Went Live (Twitch)", value=f"<t:{twitch_started_at}:R>", inline=False)

        embed.set_image(url=live_banner_url)

    # Check if TikTok is live but Twitch is not
    elif live_status.tiktok_live:
        embed = discord.Embed(
            title="DKsonic195 is Live on TikTok!",
            description=f"|| {role.mention} ||\nCatch the stream on:\n"
                        f"- TikTok: [Link](https://www.tiktok.com/@dksonic195/live)",
            color=0x00F2EA
        )

        if live_status.tiktok_live_since:
            embed.add_field(name="Time Went Live (TikTok)", value=f"<t:{live_status.tiktok_live_since}:R>", inline=False)

        embed.set_image(url=live_banner_url)

    # Both Twitch and TikTok are offline
    else:
        embed = discord.Embed(
            title="DKsonic195 is Offline",
            description=f"\nCheck <#1231013661099687977> to know when he's live next.",
            color=0xFF0000
        )
        embed.set_image(url=offline_banner_url)

    # Update or send the message
    if embed:
        if live_status.last_message_id is None:
            # Send a new message if no last message exists
            sent_message = await channel.send(embed=embed)
            live_status.last_message_id = sent_message.id
        else:
            try:
                # Update the existing message with new embed content
                sent_message = await channel.fetch_message(live_status.last_message_id)
                await sent_message.edit(embed=embed)
            except discord.NotFound:
                # If the message is not found (maybe deleted), send a new message
                logger.warning("Last message not found. Sending a new one.")
                sent_message = await channel.send(embed=embed)
                live_status.last_message_id = sent_message.id

# Task to periodically check live status (if needed)
@tasks.loop(seconds=LOOP_INTERVAL)
async def periodic_check():
    await update_live_status()    

@bot.event
async def on_ready():
    try:
        # Authenticate using the new OAuth method
        await authenticate_twitch()

        # Wait for a short time to ensure the bot is fully ready before syncing
        await asyncio.sleep(5)  # Adding a 5-second delay before syncing commands

        # Sync commands with Discord (ensure the bot commands are updated)
        await bot.tree.sync()
        print("Commands synced!")

        # Debug: Print all registered commands to the console
        print("Commands registered:")
        for command in bot.tree.get_commands():
            print(f"Command: {command.name}")

        # Confirmation message that the bot is ready
        print(f"Bot is ready and synced! Logged in as {bot.user}")
    except Exception as e:
        # Error handling for issues that occur during setup
        print(f"Error syncing commands: {e}")

# --- FLASK SERVER (For Render Hosting) ---
import flask

app = flask.Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

if __name__ == "__main__":
    import threading

    def run_flask():
        app.run(host="0.0.0.0", port=10000)

    # Run Flask server in a separate thread
    thread = threading.Thread(target=run_flask)
    thread.start()   

# Run the bot
bot.run(DISCORD_BOT_TOKEN)