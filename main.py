# main.py (for Main Arvo Bot - serving arvobot.xyz AND dash.arvobot.xyz)
import discord
from discord.ext import commands
from discord import app_commands # For bot commands
import os
from flask import Flask, render_template, url_for, session, redirect, request # For web app
from threading import Thread
import asyncio
import requests # For making API calls to Discord from Flask

# --- Arvo Bot Information ---
ARVO_BOT_NAME = "Arvo"

# --- Configuration (Fetched from Environment Variables) ---
BOT_TOKEN = os.getenv("DISCORD_TOKEN") 
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL') 

# OAuth2 Client Credentials (Needed for dashboard login)
DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')

# For Web View of specific submissions (if you re-add that feature from Walter)
# These are not currently used by the dashboard's server selection but kept for potential future use
TARGET_GUILD_ID_WEB_AUTH = os.getenv('TARGET_GUILD_ID_WEB_AUTH') 
TARGET_ROLE_NAME_OR_ID_WEB_AUTH = os.getenv('TARGET_ROLE_NAME_OR_ID_WEB_AUTH')

# This is the Client ID of your Arvo Bot application (from Discord Dev Portal -> General Information -> Application ID)
# It's used to construct the "Invite Arvo" link on the dashboard.
ARVO_BOT_CLIENT_ID_FOR_INVITE = os.getenv('ARVO_BOT_CLIENT_ID_FOR_INVITE', DISCORD_CLIENT_ID) # Fallback to OAuth Client ID if specific one not set

DISCORD_REDIRECT_URI = None
if RENDER_EXTERNAL_URL:
    DISCORD_REDIRECT_URI = f"{RENDER_EXTERNAL_URL}/callback" # Used for OAuth2 login
    print(f"INFO ({ARVO_BOT_NAME}): OAuth2 Redirect URI dynamically set to: {DISCORD_REDIRECT_URI}")
else:
    # This is critical for OAuth2 to work when deployed.
    print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): RENDER_EXTERNAL_URL is not set. OAuth2 redirect URI cannot be constructed. Dashboard login will fail.")

API_ENDPOINT = 'https://discord.com/api/v10' # Discord API endpoint

if BOT_TOKEN is None:
    print(f"CRITICAL ({ARVO_BOT_NAME}): DISCORD_TOKEN environment variable not set. Bot cannot start.")
    exit()

# --- Flask App ---
app = Flask(__name__) # '__name__' tells Flask where to look for templates/static files

if FLASK_SECRET_KEY:
    app.secret_key = FLASK_SECRET_KEY
else:
    print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): FLASK_SECRET_KEY not set. Flask sessions will be insecure and OAuth may not work reliably.")
    app.secret_key = "temporary_insecure_key_for_arvo_dashboard_fallback" # Fallback for dev, VERY INSECURE

# --- Flask Routes for Informational Website & Dashboard ---
@app.route('/')
def index():
    """Serves the main informational landing page (index.html)."""
    return render_template('index.html', ARVO_BOT_NAME=ARVO_BOT_NAME)

@app.route('/privacy-policy')
def privacy_policy():
    """Serves the privacy policy page."""
    return render_template('privacy_policy.html', ARVO_BOT_NAME=ARVO_BOT_NAME)

@app.route('/terms-and-conditions')
def terms_and_conditions():
    """Serves the terms and conditions page."""
    return render_template('terms_and_conditions.html', ARVO_BOT_NAME=ARVO_BOT_NAME)

@app.route('/keep-alive') 
def keep_alive_route():
    """Endpoint for UptimeRobot to ping."""
    return f"{ARVO_BOT_NAME} informational site and dashboard server is alive!", 200

# --- OAuth2 Routes for Dashboard Login ---
@app.route('/login')
def login():
    """Redirects user to Discord for OAuth2 login."""
    if not all([DISCORD_CLIENT_ID, DISCORD_REDIRECT_URI]):
        print("ERROR: OAuth2 misconfiguration in /login. Check DISCORD_CLIENT_ID and RENDER_EXTERNAL_URL (for DISCORD_REDIRECT_URI).")
        return "OAuth2 is not configured correctly on the server. Please contact support.", 500
    
    # Scope 'guilds' is needed to fetch the list of servers the user is in.
    # Scope 'identify' gets basic user info (id, username, avatar).
    discord_oauth_url = (
        f"{API_ENDPOINT}/oauth2/authorize?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        f"&response_type=code&scope=identify guilds" # Added 'guilds' scope
    )
    return redirect(discord_oauth_url)

@app.route('/callback')
def callback():
    """Handles the OAuth2 callback from Discord after user authorization."""
    if not all([DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI]):
        print("ERROR: OAuth2 misconfiguration in /callback (server side).")
        return "OAuth2 is not configured correctly on the server.", 500
        
    authorization_code = request.args.get('code')
    if not authorization_code:
        return "Error: No authorization code provided by Discord. Did you deny access?", 400

    data = {
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': authorization_code,
        'redirect_uri': DISCORD_REDIRECT_URI,
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    try:
        token_response = requests.post(f'{API_ENDPOINT}/oauth2/token', data=data, headers=headers)
        token_response.raise_for_status() 
        token_data = token_response.json()
        session['discord_oauth_token'] = token_data 
        
        user_info_response = requests.get(f'{API_ENDPOINT}/users/@me', headers={
            'Authorization': f"Bearer {token_data['access_token']}"
        })
        user_info_response.raise_for_status()
        user_info = user_info_response.json()
        session['discord_user_id'] = user_info['id']
        session['discord_username'] = f"{user_info['username']}#{user_info['discriminator']}"
        session['discord_avatar'] = user_info.get('avatar') 

        return redirect(url_for('dashboard_servers')) # Redirect to dashboard server selection
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Exception during OAuth2 callback token/user fetch: {e}")
        if hasattr(e, 'response') and e.response is not None: 
            print(f"Discord API Response content: {e.response.text}")
        return "Error during authentication with Discord. Please try again or contact support.", 500

@app.route('/logout')
def logout():
    """Clears the user's session (logs them out of the dashboard)."""
    session.pop('discord_oauth_token', None)
    session.pop('discord_user_id', None)
    session.pop('discord_username', None)
    session.pop('discord_avatar', None)
    return redirect(url_for('index')) 

# --- Dashboard Routes ---
@app.route('/dashboard') 
@app.route('/dashboard/servers') # Alias for server selection
def dashboard_servers():
    """Displays the server selection page for the dashboard."""
    if 'discord_user_id' not in session or 'discord_oauth_token' not in session:
        return redirect(url_for('login', next=request.url)) # Redirect to login if not authenticated

    access_token = session['discord_oauth_token']['access_token']
    headers = {'Authorization': f'Bearer {access_token}'}
    
    manageable_servers = []
    other_servers_with_bot = []
    user_avatar_url = None

    if session.get('discord_avatar'):
        user_avatar_url = f"https://cdn.discordapp.com/avatars/{session['discord_user_id']}/{session['discord_avatar']}.png"
    session['discord_avatar_url'] = user_avatar_url # Store for template, even if None

    try:
        guilds_response = requests.get(f'{API_ENDPOINT}/users/@me/guilds', headers=headers)
        guilds_response.raise_for_status()
        user_guilds_data = guilds_response.json()

        for guild_data in user_guilds_data:
            guild_id = int(guild_data['id'])
            # Check if Arvo bot is in this guild using the bot's cache
            bot_guild_instance = bot.get_guild(guild_id) 

            if bot_guild_instance: # Arvo is in this server
                user_perms_in_guild = discord.Permissions(int(guild_data['permissions']))
                icon_hash = guild_data.get('icon')
                icon_url = f"https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.png" if icon_hash else None
                
                server_info = {
                    'id': str(guild_id), 
                    'name': guild_data['name'],
                    'icon_url': icon_url
                }
                if user_perms_in_guild.manage_guild:
                    manageable_servers.append(server_info)
                else:
                    other_servers_with_bot.append(server_info)
        
    except requests.exceptions.RequestException as e:
        print(f"Error fetching user guilds for dashboard: {e}")
        if hasattr(e, 'response') and e.response is not None: 
            print(f"Discord API Response content for guilds fetch: {e.response.text}")
            if e.response.status_code == 401: # Unauthorized (token expired/invalid)
                return redirect(url_for('logout')) 
    except Exception as e_bot_check: # Catch errors if bot isn't ready or guild not found
        print(f"Error checking bot's presence in guilds: {e_bot_check}")


    return render_template('dashboard_servers.html', 
                           ARVO_BOT_NAME=ARVO_BOT_NAME,
                           manageable_servers=manageable_servers,
                           other_servers_with_bot=other_servers_with_bot,
                           DISCORD_CLIENT_ID_BOT=ARVO_BOT_CLIENT_ID_FOR_INVITE,
                           session=session 
                           )

@app.route('/dashboard/guild/<guild_id_str>') # Changed to guild_id_str to avoid Werkzeug converter issues
def dashboard_guild(guild_id_str: str):
    """Placeholder for individual server dashboard page."""
    if 'discord_user_id' not in session:
        return redirect(url_for('login', next=request.url))
    
    try:
        guild_id = int(guild_id_str)
    except ValueError:
        return "Invalid Guild ID format.", 400

    # --- Permission Check for this specific guild (very important) ---
    # You must verify the user has manage_guild perms for THIS specific guild_id
    # Re-fetch /users/@me/guilds or use a more direct way if available
    access_token = session['discord_oauth_token']['access_token']
    headers = {'Authorization': f'Bearer {access_token}'}
    can_manage_this_guild = False
    guild_name_for_dashboard = "Server"
    try:
        guilds_response = requests.get(f'{API_ENDPOINT}/users/@me/guilds', headers=headers)
        guilds_response.raise_for_status()
        user_guilds_list = guilds_response.json()
        for g_data in user_guilds_list:
            if g_data['id'] == guild_id_str: # Compare as strings
                if discord.Permissions(int(g_data['permissions'])).manage_guild:
                    can_manage_this_guild = True
                    guild_name_for_dashboard = g_data['name']
                break
    except Exception as e:
        print(f"Error re-fetching guilds for specific dashboard page /dashboard/guild/{guild_id_str}: {e}")
        return redirect(url_for('dashboard_servers')) 

    if not can_manage_this_guild:
        return "You do not have permission to manage this server's Arvo settings, or Arvo is not in this server.", 403
    # --- End Permission Check ---

    # If Arvo bot needs to interact with this guild (e.g. to list channels for setup)
    actual_guild_object = bot.get_guild(guild_id)
    if not actual_guild_object:
         return f"{ARVO_BOT_NAME} is not currently in the server '{guild_name_for_dashboard}' (ID: {guild_id}). Cannot display dashboard.", 404

    # TODO: Fetch Arvo's settings for this guild from guild_configurations
    # For now, just a placeholder page
    return f"Welcome to the Arvo Dashboard for {guild_name_for_dashboard} (ID: {guild_id})! Configuration options coming soon."


def run_flask():
  port = int(os.environ.get('PORT', 8080)) 
  app.run(host='0.0.0.0', port=port, debug=False) 

def start_keep_alive_server(): 
    server_thread = Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()
# --- End Flask App ---

# --- Discord Bot (Arvo Main) Configuration & Commands ---
intents = discord.Intents.default()
intents.members = True 
intents.message_content = True 
bot = commands.Bot(command_prefix=commands.when_mentioned_or("!arvo-main-unused!"), intents=intents)

@bot.event
async def on_ready():
    print(f'{ARVO_BOT_NAME} has logged in as {bot.user.name} (ID: {bot.user.id})')
    print(f'Discord.py Version: {discord.__version__}')
    if RENDER_EXTERNAL_URL:
        print(f"INFO ({ARVO_BOT_NAME}): Website accessible via {RENDER_EXTERNAL_URL}")
    else:
        print(f"INFO ({ARVO_BOT_NAME}): RENDER_EXTERNAL_URL is not set.")
    # Check critical OAuth env vars for dashboard functionality
    if not all([DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, FLASK_SECRET_KEY]):
        print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): One or more core OAuth/Flask environment variables (DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, FLASK_SECRET_KEY) are missing. Dashboard login will fail.")

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
        color=discord.Color.blue() 
    )
    embed.add_field(name="How to Use", value="Use slash commands (e.g., `/setup`, `/ping`) to interact with me.", inline=False)
    website_url = RENDER_EXTERNAL_URL if RENDER_EXTERNAL_URL else "https://arvobot.xyz" 
    embed.add_field(name="Website", value=f"Visit [{website_url.replace('https://','').replace('http://','')}]( {website_url} ) for more information!", inline=False)
    embed.set_footer(text=f"{ARVO_BOT_NAME} - Your reliable staff management assistant.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- Placeholder for /setup command ---
# (You would integrate your full /setup command logic here from previous versions)
@bot.tree.command(name="setup", description=f"Configure {ARVO_BOT_NAME} for this server (Admin only).")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    # This is where your SetupView and CommandPermissionsView logic would go
    await interaction.response.send_message("Arvo setup panel is under construction for this version! Check back soon.", ephemeral=True)

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
            await interaction.followup.send(error_message_to_user, ephemeral=True) # Try followup if already deferred
    except: pass 
bot.tree.on_error = on_app_command_error

# --- Running the Bot and Keep-Alive/Website Server ---
async def main_async():
    async with bot:
        start_keep_alive_server() 
        print(f"Flask web server (for website & dashboard) thread started for {ARVO_BOT_NAME}.")
        print(f"Attempting to connect {ARVO_BOT_NAME} to Discord...")
        await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    if not RENDER_EXTERNAL_URL:
        print(f"INFO ({ARVO_BOT_NAME}): RENDER_EXTERNAL_URL env var not set. Dashboard OAuth might not work correctly when deployed.")
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
        print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): DISCORD_CLIENT_ID or DISCORD_CLIENT_SECRET env vars not set. Dashboard login will fail.")
    
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print(f"{ARVO_BOT_NAME} shutting down manually...")
    except Exception as e:
        print(f"CRITICAL BOT RUN ERROR for {ARVO_BOT_NAME}: {e}")
