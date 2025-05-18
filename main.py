# main.py (for Main Arvo Bot - serving arvobot.xyz AND dash.arvobot.xyz)
import discord
from discord.ext import commands
from discord import app_commands, ChannelType, Role, SelectOption
from discord.ui import View, Button, ChannelSelect, RoleSelect, Select # For /setup UI
import os
from flask import Flask, render_template, url_for, session, redirect, request, flash # Added flash for messages
from threading import Thread
import datetime
import uuid 
import requests
import json 
import asyncio

# --- Arvo Bot Information ---
ARVO_BOT_NAME = "Arvo"
ARVO_BOT_DESCRIPTION = "Arvo - Smart Staff Management 🦉 Keep your server organized with automated moderation, role management, and staff coordination—all in one reliable bot."

# --- Configuration (Fetched from Environment Variables) ---
BOT_TOKEN = os.getenv("DISCORD_TOKEN") 
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL') 
DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID') # For Dashboard OAuth
DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET') # For Dashboard OAuth
ARVO_BOT_CLIENT_ID_FOR_INVITE = os.getenv('ARVO_BOT_CLIENT_ID_FOR_INVITE', DISCORD_CLIENT_ID) # For invite link on dashboard

# For Web View of specific submissions (if you re-add that feature from Walter)
TARGET_GUILD_ID_WEB_AUTH = os.getenv('TARGET_GUILD_ID_WEB_AUTH') 
TARGET_ROLE_NAME_OR_ID_WEB_AUTH = os.getenv('TARGET_ROLE_NAME_OR_ID_WEB_AUTH') 

DISCORD_REDIRECT_URI = None
APP_BASE_URL_CONFIG = os.getenv('APP_BASE_URL', RENDER_EXTERNAL_URL) 
if APP_BASE_URL_CONFIG:
    DISCORD_REDIRECT_URI = f"{APP_BASE_URL_CONFIG.rstrip('/')}/callback"
    print(f"INFO ({ARVO_BOT_NAME}): OAuth2 Redirect URI will be: {DISCORD_REDIRECT_URI}")
else:
    print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): APP_BASE_URL or RENDER_EXTERNAL_URL not set. OAuth2 will fail.")

API_ENDPOINT = 'https://discord.com/api/v10' 

if BOT_TOKEN is None: print(f"CRITICAL ({ARVO_BOT_NAME}): DISCORD_TOKEN not set."); exit()

# --- In-memory storage ---
submitted_forms_data = {} 
guild_configurations = {} 
# Structure: {guild_id: {
#               'log_channel_id': int, 
#               'command_permissions': {'command_name': role_id_int},
#               'command_enabled_states': {'command_name': True/False}
#            }}

def load_guild_configurations():
    global guild_configurations
    guild_configurations = {} 
    print("INFO: Using in-memory guild configurations. Will be lost on restart.")
    # TODO: Implement persistent storage (DB/file) for production

def save_guild_configuration(guild_id: int): 
    global guild_configurations
    print(f"INFO: Guild config updated in memory for guild {guild_id}: {guild_configurations.get(guild_id)}")
    # TODO: Implement persistent storage (DB/file) for production

def get_guild_log_channel_id(guild_id: int) -> int | None:
    return guild_configurations.get(guild_id, {}).get('log_channel_id')

def get_command_required_role_id(guild_id: int, command_name: str) -> int | None:
    return guild_configurations.get(guild_id, {}).get('command_permissions', {}).get(command_name)

def is_command_enabled_for_guild(guild_id: int, command_name: str) -> bool:
    """Checks if a command is enabled for a guild. Defaults to True if not specified."""
    enabled_states = guild_configurations.get(guild_id, {}).get('command_enabled_states', {})
    # If command_name is not in enabled_states, it's considered enabled by default.
    return enabled_states.get(command_name, True) 

# --- Flask App ---
app = Flask(__name__) 
if FLASK_SECRET_KEY: app.secret_key = FLASK_SECRET_KEY
else: app.secret_key = 'temporary_insecure_key_for_arvo_dashboard_CHANGE_ME'; print("CRITICAL WARNING: FLASK_SECRET_KEY not set.")

# ... (Flask routes: /, /privacy-policy, /terms-and-conditions, /keep-alive, /login, /callback, /logout) ...
# These are the same as in `arvo_main_bot_website_flask` (ID for the previous main.py)
# Ensure they are present in your actual file. For brevity, only /dashboard routes are detailed below.
@app.route('/')
def index(): return render_template('index.html', ARVO_BOT_NAME=ARVO_BOT_NAME)
@app.route('/privacy-policy')
def privacy_policy(): return render_template('privacy_policy.html', ARVO_BOT_NAME=ARVO_BOT_NAME)
@app.route('/terms-and-conditions')
def terms_and_conditions(): return render_template('terms_and_conditions.html', ARVO_BOT_NAME=ARVO_BOT_NAME)
@app.route('/keep-alive') 
def keep_alive_route(): return f"{ARVO_BOT_NAME} site and dashboard server is alive!", 200
@app.route('/login')
def login():
    if not all([DISCORD_CLIENT_ID, DISCORD_REDIRECT_URI]): print("ERROR: OAuth2 misconfig in /login."); return "OAuth2 config error.", 500
    discord_oauth_url = (f"{API_ENDPOINT}/oauth2/authorize?client_id={DISCORD_CLIENT_ID}"
                         f"&redirect_uri={DISCORD_REDIRECT_URI}&response_type=code&scope=identify guilds")
    return redirect(discord_oauth_url)
@app.route('/callback')
def callback():
    if not all([DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI]): print("ERROR: OAuth2 server misconfig in /callback."); return "OAuth2 server config error.", 500
    authorization_code = request.args.get('code')
    if not authorization_code: return "Error: No auth code.", 400
    data = {'client_id': DISCORD_CLIENT_ID, 'client_secret': DISCORD_CLIENT_SECRET, 'grant_type': 'authorization_code', 'code': authorization_code, 'redirect_uri': DISCORD_REDIRECT_URI}
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    try:
        token_response = requests.post(f'{API_ENDPOINT}/oauth2/token', data=data, headers=headers); token_response.raise_for_status(); token_data = token_response.json(); session['discord_oauth_token'] = token_data
        user_info_response = requests.get(f'{API_ENDPOINT}/users/@me', headers={'Authorization': f"Bearer {token_data['access_token']}"}); user_info_response.raise_for_status(); user_info = user_info_response.json()
        session['discord_user_id'] = user_info['id']; session['discord_username'] = f"{user_info['username']}#{user_info['discriminator']}"; session['discord_avatar'] = user_info.get('avatar')
        return redirect(url_for('dashboard_servers'))
    except requests.exceptions.RequestException as e: print(f"ERROR: OAuth2 callback exception: {e}"); return "Error during auth.", 500
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('index'))

# --- Dashboard Routes ---
@app.route('/dashboard') 
@app.route('/dashboard/servers') 
def dashboard_servers():
    if 'discord_user_id' not in session: return redirect(url_for('login', next=request.url))
    access_token = session['discord_oauth_token']['access_token']; headers = {'Authorization': f'Bearer {access_token}'}
    manageable_servers = []; other_servers_with_bot = []; user_avatar_url = None
    if session.get('discord_avatar'): user_avatar_url = f"https://cdn.discordapp.com/avatars/{session['discord_user_id']}/{session['discord_avatar']}.png"
    session['discord_avatar_url'] = user_avatar_url
    try:
        guilds_response = requests.get(f'{API_ENDPOINT}/users/@me/guilds', headers=headers); guilds_response.raise_for_status()
        user_guilds_data = guilds_response.json()
        for guild_data in user_guilds_data:
            guild_id = int(guild_data['id']); bot_guild_instance = bot.get_guild(guild_id)
            if bot_guild_instance:
                user_perms_in_guild = discord.Permissions(int(guild_data['permissions']))
                icon_hash = guild_data.get('icon'); icon_url = f"https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.png" if icon_hash else None
                server_info = {'id': str(guild_id), 'name': guild_data['name'], 'icon_url': icon_url}
                if user_perms_in_guild.manage_guild: manageable_servers.append(server_info)
                else: other_servers_with_bot.append(server_info)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching user guilds for dashboard: {e}")
        if hasattr(e, 'response') and e.response is not None and e.response.status_code == 401: return redirect(url_for('logout'))
    except Exception as e_bot_check: print(f"Error checking bot's presence in guilds: {e_bot_check}")
    return render_template('dashboard_servers.html', ARVO_BOT_NAME=ARVO_BOT_NAME, manageable_servers=manageable_servers,
                           other_servers_with_bot=other_servers_with_bot, DISCORD_CLIENT_ID_BOT=ARVO_BOT_CLIENT_ID_FOR_INVITE, session=session)

# --- Define Command Categories for Dashboard ---
COMMAND_CATEGORIES = {
    "Utility": ["ping", "arvohelp", "statuschange"],
    "Staff & Infraction Management": [
        # These will be placeholders until actual commands are built
        "infract_warn", "infract_mute", "infract_kick", "infract_ban", 
        "staffmanage_promote", "staffmanage_demote", "staffmanage_terminate",
        "staffinfract_warning", "staffinfract_strike", 
        "viewinfractions" 
    ],
    "Configuration": ["setup"] # Note: /setup itself has admin perms, toggling here is for its sub-features if any
}
# Flattened list of all known commands for easy lookup
ALL_CONFIGURABLE_COMMANDS = [cmd for sublist in COMMAND_CATEGORIES.values() for cmd in sublist if cmd != "setup"]


@app.route('/dashboard/guild/<guild_id_str>', methods=['GET'])
def dashboard_guild(guild_id_str: str):
    if 'discord_user_id' not in session: return redirect(url_for('login', next=request.url))
    try: guild_id = int(guild_id_str)
    except ValueError: return "Invalid Guild ID format.", 400

    # --- Permission Check for this specific guild (copied from previous version) ---
    access_token = session['discord_oauth_token']['access_token']; headers = {'Authorization': f'Bearer {access_token}'}
    can_manage_this_guild = False; guild_name_for_dashboard = "Server"
    try:
        guilds_response = requests.get(f'{API_ENDPOINT}/users/@me/guilds', headers=headers); guilds_response.raise_for_status()
        user_guilds_list = guilds_response.json()
        for g_data in user_guilds_list:
            if g_data['id'] == guild_id_str:
                if discord.Permissions(int(g_data['permissions'])).manage_guild: can_manage_this_guild = True; guild_name_for_dashboard = g_data['name']
                break
    except Exception as e: print(f"Error re-fetching guilds for /dashboard/guild/{guild_id_str}: {e}"); return redirect(url_for('dashboard_servers')) 
    if not can_manage_this_guild: return "You do not have permission to manage this server's Arvo settings.", 403
    
    actual_guild_object = bot.get_guild(guild_id)
    if not actual_guild_object: return f"{ARVO_BOT_NAME} is not in '{guild_name_for_dashboard}'.", 404

    # Fetch current command enabled states for this guild
    command_states = guild_configurations.get(guild_id, {}).get('command_enabled_states', {})
    # Ensure all known commands have a default state (True) if not explicitly set
    for cmd_name in ALL_CONFIGURABLE_COMMANDS:
        if cmd_name not in command_states:
            command_states[cmd_name] = True # Default to enabled

    return render_template('dashboard_guild.html', 
                           ARVO_BOT_NAME=ARVO_BOT_NAME, 
                           guild_name=guild_name_for_dashboard, 
                           guild_id=guild_id_str,
                           command_categories=COMMAND_CATEGORIES,
                           command_states=command_states,
                           session=session)

@app.route('/dashboard/guild/<guild_id_str>/save_command_settings', methods=['POST'])
def save_command_settings(guild_id_str: str):
    if 'discord_user_id' not in session: return redirect(url_for('login', next=request.referrer or url_for('dashboard_servers')))
    try: guild_id = int(guild_id_str)
    except ValueError: abort(400, "Invalid Guild ID")

    # --- Permission Check (crucial for POST requests) ---
    access_token = session['discord_oauth_token']['access_token']; headers = {'Authorization': f'Bearer {access_token}'}
    can_manage_this_guild = False
    try:
        guilds_response = requests.get(f'{API_ENDPOINT}/users/@me/guilds', headers=headers); guilds_response.raise_for_status()
        user_guilds_list = guilds_response.json()
        for g_data in user_guilds_list:
            if g_data['id'] == guild_id_str and discord.Permissions(int(g_data['permissions'])).manage_guild:
                can_manage_this_guild = True; break
    except Exception: pass # Error during check, will default to no permission
    if not can_manage_this_guild: abort(403, "You do not have permission to manage this server's settings.")
    # --- End Permission Check ---

    guild_config = guild_configurations.setdefault(guild_id, {})
    command_enabled_states = guild_config.setdefault('command_enabled_states', {})

    for cmd_name in ALL_CONFIGURABLE_COMMANDS:
        # Checkboxes send 'enabled' if checked, otherwise the key is not present in request.form
        is_enabled = f'cmd_{cmd_name}' in request.form 
        command_enabled_states[cmd_name] = is_enabled
    
    save_guild_configuration(guild_id) # Save the updated config
    flash('Command settings saved successfully!', 'success')
    return redirect(url_for('dashboard_guild', guild_id_str=guild_id_str))


def run_flask():
  port = int(os.environ.get('PORT', 8080)) 
  app.run(host='0.0.0.0', port=port, debug=False) 

def start_keep_alive_server(): 
    server_thread = Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()
# --- End Flask App ---

# --- Discord Bot (Arvo Main) ---
intents = discord.Intents.default()
intents.members = True 
intents.message_content = True 
bot = commands.Bot(command_prefix=commands.when_mentioned_or("!arvo-main-unused!"), intents=intents)

# --- Custom Check for Command Permissions (includes enabled state) ---
class CommandDisabledInGuild(app_commands.CheckFailure):
    def __init__(self, command_name: str, *args):
        super().__init__(f"The command `/{command_name}` is currently disabled in this server by an administrator.", *args)

class MissingConfiguredRole(app_commands.CheckFailure): # From previous version
    def __init__(self, command_name: str, role_name: str | None, *args):
        message = f"You need the '{role_name}' role to use `/{command_name}`." if role_name else f"You lack permissions for `/{command_name}`."
        super().__init__(message, *args)

async def check_command_permission(interaction: discord.Interaction) -> bool:
    if not interaction.guild_id: return True 
    command_name = interaction.command.name if interaction.command else None
    if not command_name: return False # Should not happen

    # 1. Check if command is enabled in this guild
    if not is_command_enabled_for_guild(interaction.guild_id, command_name):
        raise CommandDisabledInGuild(command_name)

    # 2. Check for role-specific permission (if command is enabled)
    #    /setup is always admin-only via its own decorator, not this dynamic check.
    if command_name == "setup": return True 
    
    required_role_id = get_command_required_role_id(interaction.guild_id, command_name)
    if required_role_id is None: return True # No specific role configured, so command is generally available
    if not isinstance(interaction.user, discord.Member): return False 
    if required_role_id in [role.id for role in interaction.user.roles]: return True
    else:
        role_name = "configured role"; role_obj = interaction.guild.get_role(required_role_id) if interaction.guild else None
        if role_obj: role_name = role_obj.name
        raise MissingConfiguredRole(command_name, role_name)

# --- Bot Event Listeners ---
@bot.event
async def on_ready():
    load_guild_configurations() 
    print(f'{ARVO_BOT_NAME} has logged in as {bot.user.name} (ID: {bot.user.id})')
    # ... (rest of on_ready from previous version) ...
    print(f'Discord.py Version: {discord.__version__}')
    if RENDER_EXTERNAL_URL: print(f"INFO ({ARVO_BOT_NAME}): Website accessible via {RENDER_EXTERNAL_URL}")
    else: print(f"INFO ({ARVO_BOT_NAME}): RENDER_EXTERNAL_URL is not set.")
    if not all([DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, FLASK_SECRET_KEY]):
        print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): Core OAuth/Flask env vars missing. Dashboard login will fail.")
    try: synced = await bot.tree.sync(); print(f"Synced {len(synced)} application commands for {ARVO_BOT_NAME}.")
    except Exception as e: print(f"Failed to sync commands for {ARVO_BOT_NAME}: {e}")
    print(f'{ARVO_BOT_NAME} is ready and online!')
    await bot.change_presence(activity=discord.Game(name=f"/arvohelp | {ARVO_BOT_NAME}"))

# --- Basic Slash Commands for Arvo (Example) ---
@bot.tree.command(name="ping", description=f"Check {ARVO_BOT_NAME}'s responsiveness.")
@app_commands.check(check_command_permission)
async def ping(interaction: discord.Interaction):
    latency = bot.latency * 1000 
    await interaction.response.send_message(f"{ARVO_BOT_NAME} Pong! 🏓 Latency: {latency:.2f}ms", ephemeral=True)

@bot.tree.command(name="arvohelp", description=f"Get information about {ARVO_BOT_NAME}.")
@app_commands.check(check_command_permission)
async def arvohelp(interaction: discord.Interaction):
    embed = discord.Embed(title=f"{ARVO_BOT_NAME} - Smart Staff Management", description=ARVO_BOT_DESCRIPTION, color=discord.Color.blue())
    embed.add_field(name="How to Use", value="Use slash commands to interact with me.", inline=False)
    website_url = APP_BASE_URL_CONFIG if APP_BASE_URL_CONFIG and "dash" not in APP_BASE_URL_CONFIG else "https://arvobot.xyz" 
    embed.add_field(name="Website", value=f"Visit [{website_url.replace('https://','').replace('http://','')}]( {website_url} ) for more information!", inline=False)
    embed.set_footer(text=f"{ARVO_BOT_NAME} - Your reliable staff management assistant.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- Setup Command (Placeholder for full UI, now mostly handled by dashboard) ---
@bot.tree.command(name="setup", description=f"Access {ARVO_BOT_NAME}'s configuration dashboard link.")
@app_commands.checks.has_permissions(administrator=True) # Admin only to get the link
async def setup(interaction: discord.Interaction):
    dashboard_link = f"{APP_BASE_URL_CONFIG.rstrip('/')}/dashboard/servers" if APP_BASE_URL_CONFIG else "Dashboard link not available (APP_BASE_URL not set)."
    if interaction.guild:
        dashboard_link_guild = f"{APP_BASE_URL_CONFIG.rstrip('/')}/dashboard/guild/{interaction.guild.id}" if APP_BASE_URL_CONFIG else "Specific server dashboard link not available."
        message_content = (
            f"Hello Admin! Here are your links for managing {ARVO_BOT_NAME}:\n"
            f"- **Server Selection:** {dashboard_link}\n"
            f"- **Direct Dashboard for this Server ({interaction.guild.name}):** {dashboard_link_guild}\n\n"
            "Use the dashboard to configure log channels and command settings."
        )
    else: # Should not happen if command is guild-only
        message_content = f"Please use this command in a server. Dashboard: {dashboard_link}"
        
    await interaction.response.send_message(message_content, ephemeral=True)

# --- Global Application Command Error Handler ---
async def global_app_command_error_handler(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # ... (Error handler from previous version, ensure it catches CommandDisabledInGuild) ...
    if isinstance(error, (CommandDisabledInGuild, MissingConfiguredRole)):
        response_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        try: await response_method(str(error), ephemeral=True)
        except: pass
        return

    error_message_to_user = "An unexpected error occurred."
    if isinstance(error, app_commands.CommandOnCooldown): error_message_to_user = f"Cooldown. Try in {error.retry_after:.2f}s."
    elif isinstance(error, app_commands.CheckFailure): error_message_to_user = "You don't meet requirements." # Catches has_permissions too
    
    print(f"Global unhandled slash error for '{interaction.command.name if interaction.command else 'Unknown'}': {type(error).__name__} - {error}")
    response_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    try:
        if not interaction.response.is_done(): await response_method(error_message_to_user, ephemeral=True)
    except: pass 
bot.tree.on_error = global_app_command_error_handler

# --- Running the Bot and Keep-Alive Server ---
async def main_async():
    async with bot:
        start_keep_alive_server() 
        print(f"Flask web server thread started for {ARVO_BOT_NAME}.")
        print(f"Attempting to connect {ARVO_BOT_NAME} to Discord...")
        await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    if not APP_BASE_URL_CONFIG: print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): APP_BASE_URL or RENDER_EXTERNAL_URL env var not set. Dashboard OAuth will likely fail.")
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET: print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): OAuth env vars not set. Dashboard login will fail.")
    try: asyncio.run(main_async())
    except KeyboardInterrupt: print(f"{ARVO_BOT_NAME} shutting down manually...")
    except Exception as e: print(f"CRITICAL BOT RUN ERROR for {ARVO_BOT_NAME}: {e}")

