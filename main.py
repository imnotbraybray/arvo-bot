# main.py (for Main Arvo Bot - serving arvobot.xyz)
import discord
from discord.ext import commands
from discord import app_commands
import os
from flask import Flask, render_template, url_for # Added render_template
from threading import Thread
import asyncio

# --- Arvo Bot Information ---
ARVO_BOT_NAME = "Arvo"
ARVO_BOT_DESCRIPTION = "Arvo - Smart Staff Management 🦉 Keep your server organized with automated moderation, role management, and staff coordination—all in one reliable bot."

# --- Flask App for Uptime Pinging AND Serving Website ---
app = Flask(__name__) # '__name__' tells Flask where to look for templates/static files

# This key is NOT for user sessions on the informational site,
# but Flask still likes to have it set. It would be critical for the dashboard.
FLASK_SECRET_KEY = os.environ.get('FLASK_SECRET_KEY')
if FLASK_SECRET_KEY:
    app.secret_key = FLASK_SECRET_KEY
else:
    print(f"WARNING ({ARVO_BOT_NAME}): FLASK_SECRET_KEY not set. This is fine for a static site but needed for secure sessions if login is added.")
    app.secret_key = "temporary_insecure_key_for_static_site"


@app.route('/')
def index():
    """Serves the main landing page (index.html)."""
    # You can pass variables to your template if needed, e.g., bot stats
    # For now, it's just rendering the static template.
    return render_template('index.html', ARVO_BOT_NAME=ARVO_BOT_NAME)

@app.route('/privacy-policy')
def privacy_policy():
    """Serves the privacy policy page."""
    return render_template('privacy_policy.html', ARVO_BOT_NAME=ARVO_BOT_NAME)

@app.route('/terms-and-conditions')
def terms_and_conditions():
    """Serves the terms and conditions page."""
    return render_template('terms_and_conditions.html', ARVO_BOT_NAME=ARVO_BOT_NAME)

@app.route('/keep-alive') # Renamed the keep-alive route for clarity
def keep_alive_route():
    """Endpoint for UptimeRobot to ping."""
    return f"{ARVO_BOT_NAME} informational site server is alive!", 200

def run_flask():
  port = int(os.environ.get('PORT', 8080)) 
  # Use '0.0.0.0' to be accessible externally by Render
  app.run(host='0.0.0.0', port=port, debug=False) # debug=False for production

def start_keep_alive_server(): # Renamed for clarity
    server_thread = Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()
# --- End Flask App ---

# --- Discord Bot Configuration ---
BOT_TOKEN = os.getenv("DISCORD_TOKEN") 

if BOT_TOKEN is None:
    print(f"CRITICAL ({ARVO_BOT_NAME}): DISCORD_TOKEN environment variable not set. Bot cannot start.")
    exit()

intents = discord.Intents.default()
intents.members = True 
intents.message_content = True 

bot = commands.Bot(command_prefix=commands.when_mentioned_or("!arvo-main-unused!"), intents=intents)

# --- Bot Event Listeners ---
@bot.event
async def on_ready():
    print(f'{ARVO_BOT_NAME} has logged in as {bot.user.name} (ID: {bot.user.id})')
    print(f'Discord.py Version: {discord.__version__}')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} application commands for {ARVO_BOT_NAME}.")
    except Exception as e:
        print(f"Failed to sync commands for {ARVO_BOT_NAME}: {e}")
    
    print(f'{ARVO_BOT_NAME} is ready and online!')
    await bot.change_presence(activity=discord.Game(name=f"/arvohelp | {ARVO_BOT_NAME}"))

# --- Basic Slash Commands for Arvo (Example) ---
@bot.tree.command(name="ping", description=f"Check {ARVO_BOT_NAME}'s responsiveness.")
async def ping(interaction: discord.Interaction):
    latency = bot.latency * 1000 
    await interaction.response.send_message(f"{ARVO_BOT_NAME} Pong! 🏓 Latency: {latency:.2f}ms", ephemeral=True)

@bot.tree.command(name="arvohelp", description=f"Get information about {ARVO_BOT_NAME}.")
async def arvohelp(interaction: discord.Interaction):
    embed = discord.Embed(
        title=f"{ARVO_BOT_NAME} - Smart Staff Management",
        description=ARVO_BOT_DESCRIPTION,
        color=discord.Color.blue() 
    )
    embed.add_field(name="How to Use", value="Use slash commands (e.g., `/setup`, `/ping`) to interact with me.", inline=False)
    embed.add_field(name="Website", value="Visit [arvobot.xyz](https://arvobot.xyz) for more information!", inline=False) # Update with your actual domain
    embed.set_footer(text=f"{ARVO_BOT_NAME} - Your reliable staff management assistant.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# You would add your /setup command and other Arvo bot specific commands here.
# For now, this base focuses on getting the website served.

# --- Global Application Command Error Handler ---
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    error_message_to_user = "An unexpected error occurred with that command."
    if isinstance(error, app_commands.CommandOnCooldown): 
        error_message_to_user = f"This command is on cooldown. Try again in {error.retry_after:.2f}s."
    elif isinstance(error, app_commands.CheckFailure): 
         error_message_to_user = "You do not meet the requirements to run this command or it cannot be run here."
    
    print(f"Global unhandled slash command error for '{interaction.command.name if interaction.command else 'Unknown Command'}': {type(error).__name__} - {error}")
    
    response_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    try:
        if not interaction.response.is_done(): 
            await response_method(error_message_to_user, ephemeral=True)
        else: 
            await interaction.followup.send(error_message_to_user, ephemeral=True)
    except: pass # Best effort
bot.tree.on_error = on_app_command_error

# --- Running the Bot and Keep-Alive/Website Server ---
async def main_async():
    async with bot:
        start_keep_alive_server() # Start the Flask server thread
        print(f"Flask web server (for website & keep-alive) thread started for {ARVO_BOT_NAME}.")
        print(f"Attempting to connect {ARVO_BOT_NAME} to Discord...")
        await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    # Ensure RENDER_EXTERNAL_URL is available for template linking if needed, though not strictly for rendering.
    if not RENDER_EXTERNAL_URL:
        print(f"INFO ({ARVO_BOT_NAME}): RENDER_EXTERNAL_URL is not set. If your templates use absolute URLs based on it, they might not work as expected locally.")
    
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print(f"{ARVO_BOT_NAME} shutting down manually...")
    except Exception as e:
        print(f"CRITICAL BOT RUN ERROR for {ARVO_BOT_NAME}: {e}")

