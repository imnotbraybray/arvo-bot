# main.py (for Main Arvo Bot - serving arvobot.xyz AND dash.arvobot.xyz)
import discord
from discord.ext import commands
from discord import app_commands, ChannelType, Role, SelectOption, Embed, Color
from discord.ui import View, Button, ChannelSelect, RoleSelect, Select # For /setup UI and confirmations
import os
from flask import Flask, render_template, url_for, session, redirect, request, flash, abort # Added abort
from threading import Thread
import datetime
import uuid 
import requests
import json 
import asyncio
from typing import Optional, List, Dict, Any, Union

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

DISCORD_REDIRECT_URI = None
APP_BASE_URL_CONFIG = os.getenv('APP_BASE_URL', RENDER_EXTERNAL_URL) 
if APP_BASE_URL_CONFIG:
    DISCORD_REDIRECT_URI = f"{APP_BASE_URL_CONFIG.rstrip('/')}/callback"
    print(f"INFO ({ARVO_BOT_NAME}): OAuth2 Redirect URI will be: {DISCORD_REDIRECT_URI}")
else:
    print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): APP_BASE_URL or RENDER_EXTERNAL_URL not set. OAuth2 will fail.")

API_ENDPOINT = 'https://discord.com/api/v10' 

if BOT_TOKEN is None: print(f"CRITICAL ({ARVO_BOT_NAME}): DISCORD_TOKEN not set."); exit()

# --- Data Storage Files ---
CONFIG_FILE = "arvo_guild_configs.json"
INFRACTIONS_FILE = "arvo_infractions.json"

# --- Default Guild Configuration Structure ---
DEFAULT_GUILD_CONFIG = {
    "log_channel_id": None,
    "promotion_log_channel_id": None, # New: For staff promotions
    "staff_infraction_log_channel_id": None, # New: For staff infractions
    "staff_role_ids": [], # General staff roles
    "high_rank_staff_role_id": None, # Specific role for staff management commands
    "command_states": {} 
}

# --- In-memory storage (will be loaded from/saved to JSON files) ---
guild_configurations: Dict[int, Dict[str, Any]] = {} 
infractions_data: Dict[str, List[Dict[str, Any]]] = {} # Key: "guildid-userid", Value: list of infractions

def load_from_json(filename: str, default_data: Any = None) -> Any:
    """Loads data from a JSON file. Returns default_data if file not found or error."""
    if default_data is None:
        default_data = {}
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"INFO: '{filename}' not found or invalid. Using default/empty data.")
        return default_data

def save_to_json(data: Any, filename: str):
    """Saves data to a JSON file."""
    try:
        with open(filename, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"ERROR: Could not save data to '{filename}': {e}")

def load_all_data():
    """Loads all configurations and data from JSON files."""
    global guild_configurations, infractions_data
    raw_guild_configs = load_from_json(CONFIG_FILE, {})
    # Ensure guild_ids are integers if they were stored as strings
    guild_configurations = {int(k): v for k, v in raw_guild_configs.items()}
    
    infractions_data = load_from_json(INFRACTIONS_FILE, {})
    print(f"INFO ({ARVO_BOT_NAME}): All data loaded from JSON files.")

def get_guild_config(guild_id: int) -> Dict[str, Any]:
    """Gets a specific guild's config, creating it with defaults if it doesn't exist."""
    if guild_id not in guild_configurations:
        guild_configurations[guild_id] = json.loads(json.dumps(DEFAULT_GUILD_CONFIG)) # Deep copy
        # Initialize command states for newly created config
        guild_configurations[guild_id]["command_states"] = {
            cmd_key: True for cmd_key in ALL_CONFIGURABLE_COMMANDS_FLAT 
        }
        save_to_json(guild_configurations, CONFIG_FILE)
        print(f"INFO: Created default config for guild {guild_id}")
    
    # Ensure all keys from DEFAULT_GUILD_CONFIG are present for existing configs
    # And ensure command_states are up-to-date
    config = guild_configurations[guild_id]
    updated = False
    for key, default_value in DEFAULT_GUILD_CONFIG.items():
        if key not in config:
            config[key] = default_value
            updated = True
    if "command_states" not in config: # Should be handled by above, but as a fallback
        config["command_states"] = {}
        updated = True
    
    for cmd_key in ALL_CONFIGURABLE_COMMANDS_FLAT: # Use the flat list defined later
        if cmd_key not in config["command_states"]:
            config["command_states"][cmd_key] = True # Default new commands to enabled
            updated = True
            
    if updated:
        save_to_json(guild_configurations, CONFIG_FILE)
    return config

def get_guild_log_channel_id(guild_id: int, log_type: str = "main") -> Optional[int]:
    """Gets the ID of a specific type of log channel for a guild."""
    config = get_guild_config(guild_id)
    if log_type == "main": return config.get('log_channel_id')
    elif log_type == "promotion": return config.get('promotion_log_channel_id')
    elif log_type == "staff_infraction": return config.get('staff_infraction_log_channel_id')
    return None

def is_command_enabled_for_guild(guild_id: int, command_name: str) -> bool:
    """Checks if a command is enabled for a guild. Defaults to True if not specified."""
    config = get_guild_config(guild_id)
    # Command names in config might be "group_subcommand" or just "command"
    # Ensure command_name matches the key format used in command_states
    return config.get('command_enabled_states', {}).get(command_name, True) 

# --- Flask App ---
app = Flask(__name__) 
if FLASK_SECRET_KEY: app.secret_key = FLASK_SECRET_KEY
else: app.secret_key = 'temporary_insecure_key_for_arvo_dashboard_CHANGE_ME'; print("CRITICAL WARNING: FLASK_SECRET_KEY not set.")

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

@app.route('/dashboard') 
@app.route('/dashboard/servers') 
def dashboard_servers():
    if 'discord_user_id' not in session: return redirect(url_for('login', next=request.url))
    access_token = session.get('discord_oauth_token', {}).get('access_token')
    if not access_token: return redirect(url_for('logout')) # Token expired or missing
    headers = {'Authorization': f'Bearer {access_token}'}
    manageable_servers = []; other_servers_with_bot = []; user_avatar_url = None
    if session.get('discord_avatar'): user_avatar_url = f"https://cdn.discordapp.com/avatars/{session['discord_user_id']}/{session['discord_avatar']}.png"
    session['discord_avatar_url'] = user_avatar_url
    try:
        guilds_response = requests.get(f'{API_ENDPOINT}/users/@me/guilds', headers=headers); guilds_response.raise_for_status()
        user_guilds_data = guilds_response.json()
        for guild_data in user_guilds_data:
            guild_id = int(guild_data['id']); bot_guild_instance = bot.get_guild(guild_id) # bot needs to be accessible here
            if bot_guild_instance: # Check if bot is in the guild
                user_perms_in_guild = discord.Permissions(int(guild_data['permissions']))
                icon_hash = guild_data.get('icon'); icon_url = f"https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.png" if icon_hash else None
                server_info = {'id': str(guild_id), 'name': guild_data['name'], 'icon_url': icon_url}
                if user_perms_in_guild.manage_guild: manageable_servers.append(server_info)
                else: other_servers_with_bot.append(server_info)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching user guilds for dashboard: {e}")
        if hasattr(e, 'response') and e.response is not None:
            if e.response.status_code == 401: flash("Your Discord session may have expired. Please log in again.", "error"); return redirect(url_for('logout'))
            flash(f"Error fetching server list: {e.response.status_code}", "error")
        else:
            flash("An unknown error occurred while fetching your server list.", "error")
        return redirect(url_for('index')) # Or a dedicated error page
    except Exception as e_bot_check: print(f"Error checking bot's presence in guilds: {e_bot_check}")

    return render_template('dashboard_servers.html', ARVO_BOT_NAME=ARVO_BOT_NAME, manageable_servers=manageable_servers,
                           other_servers_with_bot=other_servers_with_bot, DISCORD_CLIENT_ID_BOT=ARVO_BOT_CLIENT_ID_FOR_INVITE, session=session)

COMMAND_CATEGORIES = {
    "Utility": ["ping", "arvohelp"], # Removed statuschange
    "Staff & Infraction Management": [
        "infract_warn", "infract_mute", "infract_kick", "infract_ban", 
        "staffmanage_promote", "staffmanage_demote", "staffmanage_terminate",
        "staffinfract_warning", "staffinfract_strike", 
        "viewinfractions" 
    ],
    "Configuration": ["setup"] 
}
ALL_CONFIGURABLE_COMMANDS_FLAT = [cmd for sublist in COMMAND_CATEGORIES.values() for cmd in sublist if cmd != "setup"]


@app.route('/dashboard/guild/<guild_id_str>', methods=['GET'])
def dashboard_guild(guild_id_str: str):
    if 'discord_user_id' not in session: return redirect(url_for('login', next=request.url))
    try: guild_id = int(guild_id_str)
    except ValueError: return "Invalid Guild ID format.", 400

    access_token = session.get('discord_oauth_token', {}).get('access_token')
    if not access_token: return redirect(url_for('logout'))
    headers = {'Authorization': f'Bearer {access_token}'}
    can_manage_this_guild = False; guild_name_for_dashboard = "Server"
    try:
        guilds_response = requests.get(f'{API_ENDPOINT}/users/@me/guilds', headers=headers); guilds_response.raise_for_status()
        user_guilds_list = guilds_response.json()
        for g_data in user_guilds_list:
            if g_data['id'] == guild_id_str:
                if discord.Permissions(int(g_data['permissions'])).manage_guild: can_manage_this_guild = True; guild_name_for_dashboard = g_data['name']
                break
    except Exception as e: print(f"Error re-fetching guilds for /dashboard/guild/{guild_id_str}: {e}"); return redirect(url_for('dashboard_servers')) 
    if not can_manage_this_guild: flash("You do not have permission to manage this server's Arvo settings.", "error"); return redirect(url_for('dashboard_servers'))
    
    actual_guild_object = bot.get_guild(guild_id) # bot needs to be accessible
    if not actual_guild_object: flash(f"{ARVO_BOT_NAME} is not in '{guild_name_for_dashboard}'. Please invite it first.", "error"); return redirect(url_for('dashboard_servers'))

    guild_config = get_guild_config(guild_id) # Use the refined get_guild_config
    command_states = guild_config.get('command_enabled_states', {})
    for cmd_name in ALL_CONFIGURABLE_COMMANDS_FLAT:
        if cmd_name not in command_states:
            command_states[cmd_name] = True 

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

    access_token = session.get('discord_oauth_token', {}).get('access_token')
    if not access_token: return redirect(url_for('logout'))
    headers = {'Authorization': f'Bearer {access_token}'}
    can_manage_this_guild = False
    try:
        guilds_response = requests.get(f'{API_ENDPOINT}/users/@me/guilds', headers=headers); guilds_response.raise_for_status()
        user_guilds_list = guilds_response.json()
        for g_data in user_guilds_list:
            if g_data['id'] == guild_id_str and discord.Permissions(int(g_data['permissions'])).manage_guild:
                can_manage_this_guild = True; break
    except Exception: pass 
    if not can_manage_this_guild: abort(403, "You do not have permission to manage this server's settings.")
    
    guild_config = get_guild_config(guild_id) # Use the refined get_guild_config
    command_enabled_states = guild_config.setdefault('command_enabled_states', {})
    something_changed = False
    for cmd_name in ALL_CONFIGURABLE_COMMANDS_FLAT:
        is_enabled = f'cmd_{cmd_name}' in request.form 
        if command_enabled_states.get(cmd_name, True) != is_enabled: # Check if state actually changed
            something_changed = True
        command_enabled_states[cmd_name] = is_enabled
    
    save_to_json(guild_configurations, CONFIG_FILE) # Save the updated config
    
    if something_changed:
        # Schedule command sync for the bot (important!)
        # This needs to be thread-safe or use asyncio.run_coroutine_threadsafe if bot runs in different loop
        async def do_sync():
            target_guild = bot.get_guild(guild_id)
            if target_guild:
                await sync_guild_commands(target_guild) # New function to handle sync logic
        bot.loop.create_task(do_sync()) # Assuming bot.loop is accessible and running
        flash('Command settings saved and sync initiated!', 'success')
    else:
        flash('No changes detected in command settings.', 'info')

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
bot.loop = asyncio.get_event_loop() # Store the loop for create_task from other threads

# --- Custom Check Exceptions ---
class CommandDisabledInGuild(app_commands.CheckFailure):
    def __init__(self, command_name: str, *args):
        super().__init__(f"The command `/{command_name}` is currently disabled in this server by an administrator.", *args)

class MissingConfiguredRole(app_commands.CheckFailure):
    def __init__(self, command_name: str, role_name: str | None, *args):
        message = f"You need the '{role_name}' role to use `/{command_name}`." if role_name else f"You lack permissions for `/{command_name}`."
        super().__init__(message, *args)

class HierarchyError(app_commands.CheckFailure):
    def __init__(self, message: str, *args):
        super().__init__(message, *args)

# --- Permission Check Functions ---
def is_general_staff(interaction: Interaction) -> bool:
    """Checks if user has a configured general staff role or is admin."""
    if not interaction.guild or not isinstance(interaction.user, Member): return False
    if interaction.user.guild_permissions.administrator: return True
    config = get_guild_config(interaction.guild_id)
    staff_role_ids = config.get("staff_role_ids", [])
    return any(role.id in staff_role_ids for role in interaction.user.roles)

def is_high_rank_staff(interaction: Interaction) -> bool:
    """Checks if user has the configured high-rank staff role or is admin."""
    if not interaction.guild or not isinstance(interaction.user, Member): return False
    if interaction.user.guild_permissions.administrator: return True # Admins are always high rank
    config = get_guild_config(interaction.guild_id)
    high_rank_role_id = config.get("high_rank_staff_role_id")
    if not high_rank_role_id: # If no high-rank role is configured, only admins can use these commands
        return False 
    return any(role.id == high_rank_role_id for role in interaction.user.roles)

# --- Decorators for Permission Checks ---
def require_general_staff():
    async def predicate(interaction: Interaction) -> bool:
        if not is_general_staff(interaction):
            raise MissingConfiguredRole(interaction.command.name if interaction.command else "this command", "configured Staff")
        return True
    return app_commands.check(predicate)

def require_high_rank_staff():
    async def predicate(interaction: Interaction) -> bool:
        # Admins bypass the specific high_rank_staff_role_id check if it's not set
        config = get_guild_config(interaction.guild_id)
        high_rank_role_id = config.get("high_rank_staff_role_id")
        
        if interaction.user.guild_permissions.administrator:
            return True
        if not high_rank_role_id: # No specific role set, and user is not admin
             raise MissingConfiguredRole(interaction.command.name if interaction.command else "this command", "configured High-Rank Staff (or Administrator)")
        if not is_high_rank_staff(interaction): # Specific role is set, but user doesn't have it
            role_name = "configured High-Rank Staff"
            role_obj = interaction.guild.get_role(high_rank_role_id) if interaction.guild else None
            if role_obj: role_name = role_obj.name
            raise MissingConfiguredRole(interaction.command.name if interaction.command else "this command", role_name)
        return True
    return app_commands.check(predicate)

# --- Combined Check: Enabled & Permission ---
def check_command_status_and_permission(permission_level: str = "general_staff"):
    async def predicate(interaction: Interaction) -> bool:
        if not interaction.guild_id: return True # Not a guild command, skip checks
        command_name = interaction.command.qualified_name if interaction.command else "unknown_command"
        
        # 1. Check if command is enabled
        if not is_command_enabled_for_guild(interaction.guild_id, command_name):
            raise CommandDisabledInGuild(command_name)

        # 2. Check permission level
        if permission_level == "general_staff":
            if not is_general_staff(interaction):
                raise MissingConfiguredRole(command_name, "configured Staff")
        elif permission_level == "high_rank_staff":
            # Logic from require_high_rank_staff decorator
            config = get_guild_config(interaction.guild_id)
            high_rank_role_id = config.get("high_rank_staff_role_id")
            if not interaction.user.guild_permissions.administrator: # If not admin, check role
                if not high_rank_role_id:
                     raise MissingConfiguredRole(command_name, "configured High-Rank Staff (or Administrator)")
                if not any(role.id == high_rank_role_id for role in interaction.user.roles):
                    role_name = "configured High-Rank Staff"
                    role_obj = interaction.guild.get_role(high_rank_role_id) if interaction.guild else None
                    if role_obj: role_name = role_obj.name
                    raise MissingConfiguredRole(command_name, role_name)
        # Add more levels like "admin_only" if needed, which would check interaction.user.guild_permissions.administrator
        return True
    return app_commands.check(predicate)

# --- Confirmation View ---
class ConfirmationView(View):
    def __init__(self, author_id: int):
        super().__init__(timeout=60.0) # 60 seconds timeout
        self.value = None # Stores the result (True for confirm, False for cancel)
        self.author_id = author_id

    async def interaction_check(self, interaction: Interaction) -> bool:
        # Only allow the original command user to interact
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This confirmation is not for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm_button(self, interaction: Interaction, button: Button):
        self.value = True
        self.stop() # Stop listening for interactions
        # Disable buttons after click
        for item in self.children:
            if isinstance(item, Button):
                item.disabled = True
        await interaction.response.edit_message(view=self) # Update the message to show disabled buttons

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel_button(self, interaction: Interaction, button: Button):
        self.value = False
        self.stop()
        for item in self.children:
            if isinstance(item, Button):
                item.disabled = True
        await interaction.response.edit_message(view=self)

# --- Bot Logging Helper ---
async def log_to_discord_channel(guild: discord.Guild, channel_type: str, embed: discord.Embed, content: Optional[str] = None):
    """Helper to send logs to configured discord channels."""
    log_channel_id = get_guild_log_channel_id(guild.id, log_type)
    if log_channel_id:
        log_channel = guild.get_channel(log_channel_id)
        if isinstance(log_channel, TextChannel):
            try:
                await log_channel.send(content=content, embed=embed)
            except discord.Forbidden:
                print(f"Log Error (Guild: {guild.id}, Type: {channel_type}): Missing permissions in log channel {log_channel_id}.")
            except Exception as e:
                print(f"Log Error (Guild: {guild.id}, Type: {channel_type}): {e}")
        else:
            print(f"Log Warning (Guild: {guild.id}, Type: {channel_type}): Channel ID {log_channel_id} is not a valid text channel or not found.")

# --- Infraction Management ---
def add_infraction_record(guild_id: int, user_id: int, type: str, reason: str, moderator_id: int, duration: Optional[str] = None, points: Optional[int] = 0) -> str:
    """Adds an infraction and returns its unique ID."""
    key = f"{guild_id}-{user_id}"
    infraction_id = str(uuid.uuid4())[:8] # Short unique ID
    infraction_record = {
        "id": infraction_id,
        "type": type,
        "reason": reason,
        "moderator_id": moderator_id,
        "timestamp": discord.utils.utcnow().isoformat(),
        "duration": duration,
        "points": points
    }
    if key not in infractions_data:
        infractions_data[key] = []
    infractions_data[key].append(infraction_record)
    save_to_json(infractions_data, INFRACTIONS_FILE)
    return infraction_id

# --- Hierarchy Check ---
def check_hierarchy(interaction: Interaction, target_member: Member) -> bool:
    """Checks if the command user can action the target member."""
    # User cannot action themselves
    if interaction.user.id == target_member.id:
        raise HierarchyError("You cannot perform this action on yourself.")
    
    # If command user is guild owner, they can do anything
    if interaction.user.id == interaction.guild.owner_id:
        return True
        
    # Staff cannot action other staff of equal or higher roles
    # (Assuming 'is_general_staff' correctly identifies staff members based on configured roles)
    # This check is a bit simplified: if both are staff, compare top roles.
    # A more robust check might involve specific "staff tier" roles.
    # For now, if target is staff (has any staff role) and has higher/equal top role, deny.
    
    # Quick check: if target is owner, non-owner cannot action
    if target_member.id == interaction.guild.owner_id:
        raise HierarchyError("You cannot perform this action on the server owner.")

    # If interaction user is not admin, and target has admin, deny
    if not interaction.user.guild_permissions.administrator and target_member.guild_permissions.administrator:
        raise HierarchyError("You cannot perform this action on an administrator if you are not one.")

    # Compare top roles if both are members
    if isinstance(interaction.user, Member) and isinstance(target_member, Member):
        if interaction.user.top_role <= target_member.top_role:
            raise HierarchyError("You cannot perform this action on a member with an equal or higher role than yours.")
    return True


# --- Bot Event Listeners ---
@bot.event
async def on_ready():
    load_all_data() # Load configs and infractions
    print(f'{ARVO_BOT_NAME} has logged in as {bot.user.name} (ID: {bot.user.id})')
    print(f'Discord.py Version: {discord.__version__}')
    if RENDER_EXTERNAL_URL: print(f"INFO ({ARVO_BOT_NAME}): Website accessible via {RENDER_EXTERNAL_URL}")
    else: print(f"INFO ({ARVO_BOT_NAME}): RENDER_EXTERNAL_URL is not set.")
    if not all([DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, FLASK_SECRET_KEY]):
        print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): Core OAuth/Flask env vars missing. Dashboard login will fail.")
    
    # Initial command sync for all guilds bot is in
    for guild in bot.guilds:
        await sync_guild_commands(guild) # New function to handle this
    
    print(f'{ARVO_BOT_NAME} is ready and online!')
    await bot.change_presence(activity=discord.Game(name=f"/arvohelp | {ARVO_BOT_NAME}"))

@bot.event
async def on_guild_join(guild: discord.Guild):
    """Handles when the bot joins a new guild."""
    print(f"INFO: Joined new guild: {guild.name} (ID: {guild.id})")
    get_guild_config(guild.id) # Ensure default config is created and saved
    await sync_guild_commands(guild) # Sync commands for the new guild

async def sync_guild_commands(guild: discord.Guild):
    """Clears and re-adds commands for a specific guild based on current states."""
    print(f"INFO: Attempting to sync commands for guild: {guild.name} ({guild.id})")
    guild_config = get_guild_config(guild.id)
    
    try:
        # Clear existing commands for this guild first to ensure a clean slate
        bot.tree.clear_commands(guild=guild)
        
        # Add non-manageable core commands (like /togglecommand, /setup which is part of arvo_config)
        bot.tree.add_command(togglecommand_cmd, guild=guild) # togglecommand_cmd is defined later
        bot.tree.add_command(arvo_config_group, guild=guild) # arvo_config_group is defined later
        
        # Add manageable command groups and their subcommands if they are enabled
        manageable_groups_to_add = {} # Store groups to avoid adding multiple times

        for cmd_key, cmd_data in bot.COMMAND_REGISTRY.items(): # COMMAND_REGISTRY needs to be populated
            if not cmd_data.get("manageable", True): continue # Skip non-manageable here

            app_cmd_obj = cmd_data.get("app_command_obj")
            if not app_cmd_obj: 
                print(f"WARNING: No app_command_obj for {cmd_key} during sync for {guild.name}")
                continue

            is_enabled = guild_config.get("command_states", {}).get(cmd_key, True)
            if is_enabled:
                parent_group_name = cmd_data.get("group_name")
                if parent_group_name:
                    # If it's a subcommand, ensure its parent group is added
                    # The app_cmd_obj for subcommands IS the subcommand itself.
                    # The parent group object needs to be added to the tree first.
                    if parent_group_name not in manageable_groups_to_add:
                        # Find the actual group object (e.g., infract_group, staffmanage_group)
                        # This assumes these group objects are globally defined and accessible
                        if parent_group_name == "infract": group_obj_to_add = infract_group
                        elif parent_group_name == "staffmanage": group_obj_to_add = staffmanage_group
                        elif parent_group_name == "staffinfract": group_obj_to_add = staffinfract_group
                        # Add other groups as needed
                        else: group_obj_to_add = None
                        
                        if group_obj_to_add:
                            bot.tree.add_command(group_obj_to_add, guild=guild)
                            manageable_groups_to_add[parent_group_name] = group_obj_to_add
                    # The subcommand (app_cmd_obj) itself is part of the group,
                    # so adding the group should suffice if discord.py handles showing enabled subcommands.
                    # However, to be explicit, if a group is added, its subcommands are defined within it.
                    # The COMMAND_REGISTRY's app_cmd_obj for a subcommand IS the subcommand.
                    # It seems we don't need to add subcommands individually if their parent group is added.
                    # Let's test this: if a group is added, all its defined subcommands are registered.
                    # The dashboard toggle will then control if the check passes.
                else: # Top-level manageable command
                    bot.tree.add_command(app_cmd_obj, guild=guild)
        
        await bot.tree.sync(guild=guild)
        print(f"SUCCESS: Synced commands for guild {guild.name} ({guild.id}).")
    except discord.errors.Forbidden:
        print(f"FORBIDDEN: Cannot sync commands for guild {guild.name} ({guild.id}). Check 'application.commands' scope and bot permissions.")
    except Exception as e:
        print(f"ERROR: Failed to sync commands for guild {guild.name} ({guild.id}): {type(e).__name__} - {e}")


# --- Command Groups (defined globally) ---
arvo_config_group = Group(name="arvo_config", description="Configure Arvo bot for this server.", guild_only=True)
infract_group = Group(name="infract", description="User infraction management commands.", guild_only=True)
staffmanage_group = Group(name="staffmanage", description="Staff management commands.", guild_only=True)
staffinfract_group = Group(name="staffinfract", description="Staff infraction commands.", guild_only=True)

# --- COMMAND_REGISTRY (populated by decorators) ---
# This needs to be accessible by the setup_hook and sync logic
# We'll define it on the bot instance as self.COMMAND_REGISTRY
# For now, ensure commands are registered before setup_hook tries to use it.
# The bot.register_manageable_command decorator will populate bot.COMMAND_REGISTRY
# The ALL_CONFIGURABLE_COMMANDS_FLAT list is used by the dashboard.

# --- Basic Slash Commands (Utility) ---
@bot.tree.command(name="ping", description=f"Check {ARVO_BOT_NAME}'s responsiveness.")
@check_command_status_and_permission(permission_level=None) # No specific role, just enabled check
async def ping(interaction: discord.Interaction):
    latency = bot.latency * 1000 
    await interaction.response.send_message(f"{ARVO_BOT_NAME} Pong! 🏓 Latency: {latency:.2f}ms", ephemeral=True)
bot.COMMAND_REGISTRY = getattr(bot, "COMMAND_REGISTRY", {}) # Ensure it exists
bot.COMMAND_REGISTRY["ping"] = {"app_command_obj": ping, "manageable": True, "group_name": None}


@bot.tree.command(name="arvohelp", description=f"Get information about {ARVO_BOT_NAME}.")
@check_command_status_and_permission(permission_level=None)
async def arvohelp(interaction: discord.Interaction):
    embed = discord.Embed(title=f"{ARVO_BOT_NAME} - Smart Staff Management", description=ARVO_BOT_DESCRIPTION, color=discord.Color.blue())
    embed.add_field(name="How to Use", value="Use slash commands to interact with me. Manage settings via the dashboard.", inline=False)
    website_url = APP_BASE_URL_CONFIG if APP_BASE_URL_CONFIG else "https://arvobot.xyz" 
    embed.add_field(name="Website & Dashboard", value=f"Visit [{website_url.replace('https://','').replace('http://','')}]( {website_url} )", inline=False)
    embed.set_footer(text=f"{ARVO_BOT_NAME} - Your reliable staff management assistant.")
    await interaction.response.send_message(embed=embed, ephemeral=True)
bot.COMMAND_REGISTRY["arvohelp"] = {"app_command_obj": arvohelp, "manageable": True, "group_name": None}


# --- Configuration Commands (Part of arvo_config_group) ---
@arvo_config_group.command(name="setup", description=f"Get links to {ARVO_BOT_NAME}'s configuration dashboard.")
@app_commands.checks.has_permissions(administrator=True) # Admin only to get the link
# This command is not "manageable" in the sense of being toggled by users, it's core.
async def config_setup(interaction: Interaction): # Renamed to avoid conflict with dashboard's "setup" command name
    dashboard_link_base = APP_BASE_URL_CONFIG.rstrip('/') if APP_BASE_URL_CONFIG else None
    if not dashboard_link_base:
        await interaction.response.send_message("Dashboard link not available (APP_BASE_URL not set). Please configure this environment variable.", ephemeral=True)
        return
        
    dashboard_link_servers = f"{dashboard_link_base}/dashboard/servers"
    message_content = f"Hello Admin! Here are your links for managing {ARVO_BOT_NAME}:\n" \
                      f"- **Server Selection:** {dashboard_link_servers}\n"
    if interaction.guild:
        dashboard_link_guild = f"{dashboard_link_base}/dashboard/guild/{interaction.guild.id}"
        message_content += f"- **Direct Dashboard for this Server ({interaction.guild.name}):** {dashboard_link_guild}\n\n"
    message_content += "Use the dashboard to configure log channels, staff roles, and command settings."
    await interaction.response.send_message(message_content, ephemeral=True)
# Note: config commands are not added to COMMAND_REGISTRY as "manageable" by users. They are core.


# --- User Infraction Commands ---
@infract_group.command(name="warn", description="Warns a user.")
@check_command_status_and_permission(permission_level="general_staff")
@app_commands.describe(member="The member to warn.", reason="The reason for the warning.")
async def infract_warn(interaction: Interaction, member: Member, reason: str):
    if not interaction.guild: return # Should be caught by guild_only on group
    try: check_hierarchy(interaction, member)
    except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return

    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"You are about to warn {member.mention} for: \"{reason}\".\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()

    if view.value is True:
        infraction_id = add_infraction_record(interaction.guild_id, member.id, "warn", reason, interaction.user.id, points=1)
        
        log_embed = Embed(title="User Warned", color=Color.gold(), timestamp=discord.utils.utcnow())
        log_embed.set_author(name=f"Moderator: {interaction.user}", icon_url=interaction.user.display_avatar.url)
        log_embed.add_field(name="User", value=f"{member.mention} ({member.id})", inline=False)
        log_embed.add_field(name="Reason", value=reason, inline=False)
        log_embed.set_footer(text=f"Infraction ID: {infraction_id} | Guild: {interaction.guild.name}")
        await log_to_discord_channel(interaction.guild, "main", log_embed)

        try:
            await member.send(f"You have been warned in **{interaction.guild.name}**.\n**Reason:** {reason}\n*Infraction ID: {infraction_id}*")
        except discord.Forbidden:
            await interaction.followup.send(f"✅ {member.mention} warned. Could not DM the user.", ephemeral=True)
            return
        await interaction.followup.send(f"✅ {member.mention} has been warned. Reason: {reason}", ephemeral=True)
    elif view.value is False:
        await interaction.followup.send("⚠️ Warning cancelled.", ephemeral=True)
    else: # Timeout
        await interaction.followup.send("⚠️ Warning confirmation timed out.", ephemeral=True)
bot.COMMAND_REGISTRY["infract_warn"] = {"app_command_obj": infract_warn, "manageable": True, "group_name": "infract"}


@infract_group.command(name="mute", description="Mutes a user for a specified number of hours.")
@check_command_status_and_permission(permission_level="general_staff")
@app_commands.describe(member="The member to mute.", hours="Duration in hours (e.g., 1, 24). Max 672 (28 days).", reason="The reason for the mute.")
async def infract_mute(interaction: Interaction, member: Member, hours: app_commands.Range[int, 1, 672], reason: str):
    if not interaction.guild: return
    try: check_hierarchy(interaction, member)
    except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return

    duration_str = f"{hours} hour{'s' if hours > 1 else ''}"
    delta = datetime.timedelta(hours=hours)

    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"You are about to mute {member.mention} for {duration_str}. Reason: \"{reason}\".\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()

    if view.value is True:
        try:
            await member.timeout(delta, reason=f"Muted by {interaction.user.name}: {reason}")
            infraction_id = add_infraction_record(interaction.guild_id, member.id, "mute", reason, interaction.user.id, duration=duration_str, points=3)
            
            log_embed = Embed(title="User Muted", color=Color.orange(), timestamp=discord.utils.utcnow())
            log_embed.set_author(name=f"Moderator: {interaction.user}", icon_url=interaction.user.display_avatar.url)
            log_embed.add_field(name="User", value=f"{member.mention} ({member.id})", inline=False)
            log_embed.add_field(name="Duration", value=duration_str, inline=True)
            log_embed.add_field(name="Reason", value=reason, inline=False)
            log_embed.set_footer(text=f"Infraction ID: {infraction_id} | Guild: {interaction.guild.name}")
            await log_to_discord_channel(interaction.guild, "main", log_embed)

            try:
                await member.send(f"You have been muted in **{interaction.guild.name}** for **{duration_str}**.\n**Reason:** {reason}\n*Infraction ID: {infraction_id}*")
            except discord.Forbidden: pass
            await interaction.followup.send(f"✅ {member.mention} has been muted for {duration_str}. Reason: {reason}", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(f"🚫 Failed to mute {member.mention}. I may lack permissions or they have a higher role.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"An error occurred while muting: {e}", ephemeral=True)
    elif view.value is False:
        await interaction.followup.send("⚠️ Mute cancelled.", ephemeral=True)
    else:
        await interaction.followup.send("⚠️ Mute confirmation timed out.", ephemeral=True)
bot.COMMAND_REGISTRY["infract_mute"] = {"app_command_obj": infract_mute, "manageable": True, "group_name": "infract"}


@infract_group.command(name="kick", description="Kicks a user from the server.")
@check_command_status_and_permission(permission_level="general_staff")
@app_commands.describe(member="The member to kick.", reason="The reason for the kick.")
async def infract_kick(interaction: Interaction, member: Member, reason: str):
    if not interaction.guild: return
    try: check_hierarchy(interaction, member)
    except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return

    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"You are about to kick {member.mention}. Reason: \"{reason}\".\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()

    if view.value is True:
        infraction_id = "N/A" # User will be gone, ID less relevant for DM
        dm_message = f"You have been kicked from **{interaction.guild.name}**.\n**Reason:** {reason}"
        try: await member.send(dm_message)
        except discord.Forbidden: pass 
        
        try:
            await member.kick(reason=f"Kicked by {interaction.user.name}: {reason}")
            infraction_id = add_infraction_record(interaction.guild_id, member.id, "kick", reason, interaction.user.id, points=5) # Record after successful kick
            
            log_embed = Embed(title="User Kicked", color=Color.dark_orange(), timestamp=discord.utils.utcnow())
            log_embed.set_author(name=f"Moderator: {interaction.user}", icon_url=interaction.user.display_avatar.url)
            log_embed.add_field(name="User", value=f"{member.mention} ({member.id})", inline=False) # Logged before they are gone
            log_embed.add_field(name="Reason", value=reason, inline=False)
            log_embed.set_footer(text=f"Infraction ID: {infraction_id} | Guild: {interaction.guild.name}")
            await log_to_discord_channel(interaction.guild, "main", log_embed)
            
            await interaction.followup.send(f"✅ {member.display_name} has been kicked. Reason: {reason}", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(f"🚫 Failed to kick {member.display_name}. I may lack permissions or they have a higher role.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"An error occurred while kicking: {e}", ephemeral=True)
    elif view.value is False:
        await interaction.followup.send("⚠️ Kick cancelled.", ephemeral=True)
    else:
        await interaction.followup.send("⚠️ Kick confirmation timed out.", ephemeral=True)
bot.COMMAND_REGISTRY["infract_kick"] = {"app_command_obj": infract_kick, "manageable": True, "group_name": "infract"}


@infract_group.command(name="ban", description="Bans a user from the server.")
@check_command_status_and_permission(permission_level="general_staff")
@app_commands.describe(user="The user to ban (can be ID if not in server).", reason="The reason for the ban.", delete_message_days="Days of messages to delete (0-7).")
async def infract_ban(interaction: Interaction, user: User, reason: str, delete_message_days: app_commands.Range[int, 0, 7] = 0):
    if not interaction.guild: return
    
    # Hierarchy check is a bit different for ban as user might not be a Member
    # We'll check if they *are* a member first.
    target_member = interaction.guild.get_member(user.id)
    if target_member:
        try: check_hierarchy(interaction, target_member)
        except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return
    # If not a member, hierarchy check is implicitly passed against command user unless target is owner (checked in check_hierarchy)

    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"You are about to ban {user.mention} ({user.id}). Reason: \"{reason}\". Delete messages from last {delete_message_days} days.\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()

    if view.value is True:
        dm_message = f"You have been banned from **{interaction.guild.name}**.\n**Reason:** {reason}"
        try: await user.send(dm_message)
        except discord.Forbidden: pass # User might have DMs closed or not be reachable
        
        try:
            await interaction.guild.ban(user, reason=f"Banned by {interaction.user.name}: {reason}", delete_message_days=delete_message_days)
            infraction_id = add_infraction_record(interaction.guild_id, user.id, "ban", reason, interaction.user.id, points=10)
            
            log_embed = Embed(title="User Banned", color=Color.red(), timestamp=discord.utils.utcnow())
            log_embed.set_author(name=f"Moderator: {interaction.user}", icon_url=interaction.user.display_avatar.url)
            log_embed.add_field(name="User", value=f"{user.mention} ({user.id})", inline=False)
            log_embed.add_field(name="Reason", value=reason, inline=False)
            log_embed.add_field(name="Messages Deleted", value=f"{delete_message_days} days", inline=True)
            log_embed.set_footer(text=f"Infraction ID: {infraction_id} | Guild: {interaction.guild.name}")
            await log_to_discord_channel(interaction.guild, "main", log_embed)

            await interaction.followup.send(f"✅ {user.display_name} ({user.id}) has been banned. Reason: {reason}", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(f"🚫 Failed to ban {user.display_name}. I may lack permissions.", ephemeral=True) # Simplified error for ban
        except Exception as e:
            await interaction.followup.send(f"An error occurred while banning: {e}", ephemeral=True)
    elif view.value is False:
        await interaction.followup.send("⚠️ Ban cancelled.", ephemeral=True)
    else:
        await interaction.followup.send("⚠️ Ban confirmation timed out.", ephemeral=True)
bot.COMMAND_REGISTRY["infract_ban"] = {"app_command_obj": infract_ban, "manageable": True, "group_name": "infract"}


# --- Staff Management Commands ---
@staffmanage_group.command(name="promote", description="Promotes a staff member and assigns a new role.")
@check_command_status_and_permission(permission_level="high_rank_staff")
@app_commands.describe(staff_member="The staff member to promote.", new_role="The new role to assign.", reason="Reason for promotion.")
async def staffmanage_promote(interaction: Interaction, staff_member: Member, new_role: Role, reason: str):
    if not interaction.guild: return
    try: check_hierarchy(interaction, staff_member) # Check if promoter can action this staff member
    except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return

    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"You are about to promote {staff_member.mention} to {new_role.mention}. Reason: \"{reason}\".\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()

    if view.value is True:
        try:
            await staff_member.add_roles(new_role, reason=f"Promoted by {interaction.user.name}: {reason}")
            
            # Main Log
            log_embed_main = Embed(title="Staff Promoted (Action Log)", color=Color.teal(), timestamp=discord.utils.utcnow())
            log_embed_main.set_author(name=f"Promoting Manager: {interaction.user}", icon_url=interaction.user.display_avatar.url)
            log_embed_main.add_field(name="Staff Member", value=f"{staff_member.mention} ({staff_member.id})", inline=False)
            log_embed_main.add_field(name="New Role Assigned", value=new_role.mention, inline=True)
            log_embed_main.add_field(name="Reason", value=reason, inline=False)
            log_embed_main.set_footer(text=f"Guild: {interaction.guild.name}")
            await log_to_discord_channel(interaction.guild, "main", log_embed_main)

            # Dedicated Promotion Log (using your example's style)
            promo_log_embed = Embed(title="🎉 Staff Promotion 🎉", description="The Executive team has decided to promote you! Congratulations!", color=Color.gold(), timestamp=discord.utils.utcnow())
            promo_log_embed.set_author(name=staff_member.display_name, icon_url=staff_member.display_avatar.url) # Or a generic guild icon
            promo_log_embed.add_field(name="Staff member:", value=staff_member.mention, inline=False)
            promo_log_embed.add_field(name="New Rank:", value=new_role.mention, inline=False)
            promo_log_embed.add_field(name="Reason:", value=reason, inline=False)
            promo_log_embed.add_field(name="Promoted by:", value=interaction.user.mention, inline=False)
            await log_to_discord_channel(interaction.guild, "promotion", promo_log_embed, content=staff_member.mention) # Ping in content

            try:
                await staff_member.send(f"Congratulations! You have been promoted in **{interaction.guild.name}** to **{new_role.name}**.\n**Reason:** {reason}\n*Promoted by: {interaction.user.mention}*")
            except discord.Forbidden: pass

            await interaction.followup.send(f"✅ {staff_member.mention} has been promoted to {new_role.mention}. Reason: {reason}", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(f"🚫 Failed to promote {staff_member.mention}. I may lack permissions to assign roles or the role hierarchy is incorrect.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"An error occurred during promotion: {e}", ephemeral=True)
    elif view.value is False:
        await interaction.followup.send("⚠️ Promotion cancelled.", ephemeral=True)
    else:
        await interaction.followup.send("⚠️ Promotion confirmation timed out.", ephemeral=True)
bot.COMMAND_REGISTRY["staffmanage_promote"] = {"app_command_obj": staffmanage_promote, "manageable": True, "group_name": "staffmanage"}


@staffmanage_group.command(name="demote", description="Demotes a staff member and removes a role.")
@check_command_status_and_permission(permission_level="high_rank_staff")
@app_commands.describe(staff_member="The staff member to demote.", role_to_remove="The role to remove.", reason="Reason for demotion.")
async def staffmanage_demote(interaction: Interaction, staff_member: Member, role_to_remove: Role, reason: str):
    if not interaction.guild: return
    try: check_hierarchy(interaction, staff_member)
    except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return
    if role_to_remove not in staff_member.roles:
        await interaction.response.send_message(f"{staff_member.mention} does not have the role {role_to_remove.mention} to remove.", ephemeral=True)
        return

    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"You are about to demote {staff_member.mention} by removing the role {role_to_remove.mention}. Reason: \"{reason}\".\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()

    if view.value is True:
        try:
            await staff_member.remove_roles(role_to_remove, reason=f"Demoted by {interaction.user.name}: {reason}")
            
            log_embed_main = Embed(title="Staff Demoted (Action Log)", color=Color.dark_gold(), timestamp=discord.utils.utcnow())
            log_embed_main.set_author(name=f"Demoting Manager: {interaction.user}", icon_url=interaction.user.display_avatar.url)
            log_embed_main.add_field(name="Staff Member", value=f"{staff_member.mention} ({staff_member.id})", inline=False)
            log_embed_main.add_field(name="Role Removed", value=role_to_remove.mention, inline=True)
            log_embed_main.add_field(name="Reason", value=reason, inline=False)
            log_embed_main.set_footer(text=f"Guild: {interaction.guild.name}")
            await log_to_discord_channel(interaction.guild, "main", log_embed_main)
            
            # No specific "demotion log" example given, so only main log for now. User can be DMed.
            try:
                await staff_member.send(f"You have been demoted in **{interaction.guild.name}**. The role **{role_to_remove.name}** was removed.\n**Reason:** {reason}\n*Action by: {interaction.user.mention}*")
            except discord.Forbidden: pass

            await interaction.followup.send(f"✅ {staff_member.mention} has been demoted (role {role_to_remove.mention} removed). Reason: {reason}", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(f"🚫 Failed to demote {staff_member.mention}. I may lack permissions to remove roles or the role hierarchy is incorrect.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"An error occurred during demotion: {e}", ephemeral=True)
    elif view.value is False:
        await interaction.followup.send("⚠️ Demotion cancelled.", ephemeral=True)
    else:
        await interaction.followup.send("⚠️ Demotion confirmation timed out.", ephemeral=True)
bot.COMMAND_REGISTRY["staffmanage_demote"] = {"app_command_obj": staffmanage_demote, "manageable": True, "group_name": "staffmanage"}


@staffmanage_group.command(name="terminate", description="Logs a staff termination. Manual role removal required by admin.")
@check_command_status_and_permission(permission_level="high_rank_staff")
@app_commands.describe(staff_member="The staff member being terminated.", reason="Reason for termination.")
async def staffmanage_terminate(interaction: Interaction, staff_member: Member, reason: str):
    if not interaction.guild: return
    try: check_hierarchy(interaction, staff_member)
    except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return

    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"You are about to log the termination of {staff_member.mention}. Reason: \"{reason}\".\n**Note: You must manually remove their staff roles.**\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()

    if view.value is True:
        # This command only logs the termination as per user spec.
        infraction_id = add_infraction_record(interaction.guild_id, staff_member.id, "staff_termination", reason, interaction.user.id, points=0) # Points for termination itself might be high, or handled by 3 strikes
            
        log_embed_main = Embed(title="Staff Termination Logged", color=Color.dark_red(), timestamp=discord.utils.utcnow())
        log_embed_main.set_author(name=f"Terminating Manager: {interaction.user}", icon_url=interaction.user.display_avatar.url)
        log_embed_main.add_field(name="Staff Member", value=f"{staff_member.mention} ({staff_member.id})", inline=False)
        log_embed_main.add_field(name="Reason", value=reason, inline=False)
        log_embed_main.add_field(name="Action Required", value="Administrator must manually remove all staff roles from this user.", inline=False)
        log_embed_main.set_footer(text=f"Termination Record ID: {infraction_id} | Guild: {interaction.guild.name}")
        await log_to_discord_channel(interaction.guild, "main", log_embed_main)
        
        # Also log to staff infraction channel if configured, as it's a major staff action
        staff_infraction_log_embed = Embed(title="Staff Termination", color=Color.dark_red(), timestamp=discord.utils.utcnow())
        staff_infraction_log_embed.add_field(name="Member:", value=f"{staff_member.mention} ({staff_member.id})", inline=False)
        staff_infraction_log_embed.add_field(name="Reasoning:", value=reason, inline=True)
        staff_infraction_log_embed.add_field(name="Punishment:", value="Termination", inline=True)
        staff_infraction_log_embed.add_field(name="Issued by:", value=interaction.user.mention, inline=False)
        staff_infraction_log_embed.set_footer(text=f"Ref No: {infraction_id}")
        await log_to_discord_channel(interaction.guild, "staff_infraction", staff_infraction_log_embed, content=staff_member.mention)

        try:
            await staff_member.send(f"You have been terminated from your staff position in **{interaction.guild.name}**.\n**Reason:** {reason}\n*Action by: {interaction.user.mention}*")
        except discord.Forbidden: pass

        await interaction.followup.send(f"✅ Termination of {staff_member.mention} has been logged. Reason: {reason}. Remember to manually remove their roles.", ephemeral=True)
    elif view.value is False:
        await interaction.followup.send("⚠️ Termination logging cancelled.", ephemeral=True)
    else:
        await interaction.followup.send("⚠️ Termination confirmation timed out.", ephemeral=True)
bot.COMMAND_REGISTRY["staffmanage_terminate"] = {"app_command_obj": staffmanage_terminate, "manageable": True, "group_name": "staffmanage"}


# --- Staff Infraction Commands ---
@staffinfract_group.command(name="warning", description="Issues an official warning to a staff member.")
@check_command_status_and_permission(permission_level="high_rank_staff")
@app_commands.describe(staff_member="The staff member to warn.", reason="The reason for the staff warning.")
async def staffinfract_warning(interaction: Interaction, staff_member: Member, reason: str):
    if not interaction.guild: return
    try: check_hierarchy(interaction, staff_member)
    except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return

    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"You are about to issue a staff warning to {staff_member.mention}. Reason: \"{reason}\".\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()

    if view.value is True:
        infraction_id = add_infraction_record(interaction.guild_id, staff_member.id, "staff_warning", reason, interaction.user.id, points=1) # Example: 1 point for staff warning
        
        # Main Log
        log_embed_main = Embed(title="Staff Warning Issued (Action Log)", color=Color.orange(), timestamp=discord.utils.utcnow())
        log_embed_main.set_author(name=f"Issuing Manager: {interaction.user}", icon_url=interaction.user.display_avatar.url)
        log_embed_main.add_field(name="Staff Member", value=f"{staff_member.mention} ({staff_member.id})", inline=False)
        log_embed_main.add_field(name="Reason", value=reason, inline=False)
        log_embed_main.set_footer(text=f"Infraction ID: {infraction_id} | Guild: {interaction.guild.name}")
        await log_to_discord_channel(interaction.guild, "main", log_embed_main)

        # Dedicated Staff Infraction Log
        staff_infraction_embed = Embed(title=f"{interaction.guild.name} | Staff Infraction", color=Color.orange(), timestamp=discord.utils.utcnow())
        staff_infraction_embed.add_field(name="Member:", value=f"{staff_member.mention} ({staff_member.id})", inline=False)
        staff_infraction_embed.add_field(name="Reasoning:", value=reason, inline=True)
        staff_infraction_embed.add_field(name="Punishment:", value="Staff Warning", inline=True)
        staff_infraction_embed.add_field(name="Issued by:", value=interaction.user.mention, inline=False)
        staff_infraction_embed.set_footer(text=f"Ref No: {infraction_id}")
        # staff_infraction_embed.add_field(name="This infraction is appealable", value="Yes/No or Link", inline=False) # Optional based on your system
        await log_to_discord_channel(interaction.guild, "staff_infraction", staff_infraction_embed, content=staff_member.mention)

        try:
            await staff_member.send(f"You have received an official staff warning in **{interaction.guild.name}**.\n**Reason:** {reason}\n*Issued by: {interaction.user.mention}*\n*Infraction ID: {infraction_id}*")
        except discord.Forbidden: pass
        await interaction.followup.send(f"✅ Staff warning issued to {staff_member.mention}. Reason: {reason}", ephemeral=True)
    elif view.value is False:
        await interaction.followup.send("⚠️ Staff warning cancelled.", ephemeral=True)
    else:
        await interaction.followup.send("⚠️ Staff warning confirmation timed out.", ephemeral=True)
bot.COMMAND_REGISTRY["staffinfract_warning"] = {"app_command_obj": staffinfract_warning, "manageable": True, "group_name": "staffinfract"}


@staffinfract_group.command(name="strike", description="Issues a strike to a staff member.")
@check_command_status_and_permission(permission_level="high_rank_staff")
@app_commands.describe(staff_member="The staff member to issue a strike to.", reason="The reason for the staff strike.")
async def staffinfract_strike(interaction: Interaction, staff_member: Member, reason: str):
    if not interaction.guild: return
    try: check_hierarchy(interaction, staff_member)
    except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return

    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"You are about to issue a staff strike to {staff_member.mention}. Reason: \"{reason}\".\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()

    if view.value is True:
        infraction_id = add_infraction_record(interaction.guild_id, staff_member.id, "staff_strike", reason, interaction.user.id, points=3) # Example: 3 points for staff strike
        
        log_embed_main = Embed(title="Staff Strike Issued (Action Log)", color=Color.red(), timestamp=discord.utils.utcnow())
        log_embed_main.set_author(name=f"Issuing Manager: {interaction.user}", icon_url=interaction.user.display_avatar.url)
        log_embed_main.add_field(name="Staff Member", value=f"{staff_member.mention} ({staff_member.id})", inline=False)
        log_embed_main.add_field(name="Reason", value=reason, inline=False)
        log_embed_main.set_footer(text=f"Infraction ID: {infraction_id} | Guild: {interaction.guild.name}")
        await log_to_discord_channel(interaction.guild, "main", log_embed_main)

        staff_infraction_embed = Embed(title=f"{interaction.guild.name} | Staff Infraction", color=Color.red(), timestamp=discord.utils.utcnow())
        staff_infraction_embed.add_field(name="Member:", value=f"{staff_member.mention} ({staff_member.id})", inline=False)
        staff_infraction_embed.add_field(name="Reasoning:", value=reason, inline=True)
        staff_infraction_embed.add_field(name="Punishment:", value="Staff Strike", inline=True)
        staff_infraction_embed.add_field(name="Issued by:", value=interaction.user.mention, inline=False)
        staff_infraction_embed.set_footer(text=f"Ref No: {infraction_id}")
        await log_to_discord_channel(interaction.guild, "staff_infraction", staff_infraction_embed, content=staff_member.mention)

        try:
            await staff_member.send(f"You have received an official staff strike in **{interaction.guild.name}**.\n**Reason:** {reason}\n*Issued by: {interaction.user.mention}*\n*Infraction ID: {infraction_id}*")
        except discord.Forbidden: pass
        await interaction.followup.send(f"✅ Staff strike issued to {staff_member.mention}. Reason: {reason}", ephemeral=True)
    elif view.value is False:
        await interaction.followup.send("⚠️ Staff strike cancelled.", ephemeral=True)
    else:
        await interaction.followup.send("⚠️ Staff strike confirmation timed out.", ephemeral=True)
bot.COMMAND_REGISTRY["staffinfract_strike"] = {"app_command_obj": staffinfract_strike, "manageable": True, "group_name": "staffinfract"}


@bot.tree.command(name="viewinfractions", description="Views infractions for a given user.")
@check_command_status_and_permission(permission_level="general_staff")
@app_commands.describe(user="The user whose infractions you want to view.")
async def viewinfractions(interaction: Interaction, user: User):
    if not interaction.guild_id: return # Should not happen with guild_only group
    
    user_key = f"{interaction.guild_id}-{user.id}"
    user_infractions = infractions_data.get(user_key, [])

    if not user_infractions:
        await interaction.response.send_message(f"{user.mention} has no recorded infractions in this server.", ephemeral=True)
        return

    embed = Embed(title=f"Infractions for {user.display_name} ({user.id})", color=Color.light_grey(), timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)

    normal_infractions_text = ""
    staff_infractions_text = ""

    for infr in sorted(user_infractions, key=lambda x: x['timestamp'], reverse=True): # Show newest first
        mod_user = await bot.fetch_user(infr['moderator_id']) if infr.get('moderator_id') else "Unknown Mod"
        timestamp_dt = datetime.datetime.fromisoformat(infr['timestamp'])
        # Format timestamp to be more readable, e.g., "May 19, 2025, 09:30 AM"
        # Or use discord.utils.format_dt for relative time
        formatted_ts = discord.utils.format_dt(timestamp_dt, style='f') # 'f' for short date/time

        entry = (f"**ID:** `{infr['id']}`\n"
                 f"**Type:** {infr['type'].replace('_', ' ').title()}\n"
                 f"**Reason:** {infr['reason']}\n"
                 f"**Moderator:** {mod_user}\n"
                 f"**Date:** {formatted_ts}\n")
        if infr.get('duration'): entry += f"**Duration:** {infr['duration']}\n"
        if infr.get('points'): entry += f"**Points:** {infr['points']}\n"
        entry += "---\n"

        if infr['type'].startswith("staff_"):
            staff_infractions_text += entry
        else:
            normal_infractions_text += entry
    
    if normal_infractions_text:
        # Discord embed field value limit is 1024 characters. Paginate if too long.
        if len(normal_infractions_text) > 1020: normal_infractions_text = normal_infractions_text[:1020] + "..."
        embed.add_field(name="📜 User Infractions", value=normal_infractions_text or "None", inline=False)
    
    if staff_infractions_text:
        if len(staff_infractions_text) > 1020: staff_infractions_text = staff_infractions_text[:1020] + "..."
        embed.add_field(name="🛡️ Staff Infractions", value=staff_infractions_text or "None", inline=False)

    if not normal_infractions_text and not staff_infractions_text: # Should be caught by earlier check but as a safeguard
        await interaction.response.send_message(f"No infractions found for {user.mention} after filtering.", ephemeral=True)
        return
        
    await interaction.response.send_message(embed=embed, ephemeral=True)
bot.COMMAND_REGISTRY["viewinfractions"] = {"app_command_obj": viewinfractions, "manageable": True, "group_name": None} # Assuming it's top-level or decide group


# --- Toggle Command ---
@app_commands.command(name="togglecommand", description="Enables or disables a manageable command for this server.")
@app_commands.checks.has_permissions(administrator=True) # Admin only
@app_commands.guild_only()
@app_commands.describe(command_name="The command to toggle.", enable="Set to True to enable, False to disable.")
async def togglecommand_cmd(interaction: Interaction, command_name: str, enable: bool):
    if not interaction.guild_id: return
    guild_config = get_guild_config(interaction.guild_id)
    
    # Validate command_name against ALL_CONFIGURABLE_COMMANDS_FLAT or bot.COMMAND_REGISTRY keys
    if command_name not in ALL_CONFIGURABLE_COMMANDS_FLAT and command_name not in bot.COMMAND_REGISTRY:
        await interaction.response.send_message(f"⚠️ Command `{command_name}` is not a known manageable command.", ephemeral=True)
        return

    current_status = guild_config["command_states"].get(command_name, True)
    if current_status == enable:
        status_text = "enabled" if enable else "disabled"
        await interaction.response.send_message(f"ℹ️ Command `{command_name}` is already {status_text}.", ephemeral=True)
        return

    guild_config["command_states"][command_name] = enable
    save_to_json(guild_configurations, CONFIG_FILE)
    
    # Schedule command sync for the bot
    async def do_sync():
        target_guild = bot.get_guild(interaction.guild_id)
        if target_guild: await sync_guild_commands(target_guild)
    bot.loop.create_task(do_sync())

    status_text = "enabled" if enable else "disabled"
    await interaction.response.send_message(f"✅ Command `{command_name}` has been {status_text}. Changes may take a moment to reflect.", ephemeral=True)
    
    log_embed = Embed(title="Command Toggled", color=Color.purple(), timestamp=discord.utils.utcnow())
    log_embed.set_author(name=f"Administrator: {interaction.user}", icon_url=interaction.user.display_avatar.url)
    log_embed.add_field(name="Command", value=f"`/{command_name}`", inline=True)
    log_embed.add_field(name="New Status", value=status_text.title(), inline=True)
    log_embed.set_footer(text=f"Guild: {interaction.guild.name}")
    await log_to_discord_channel(interaction.guild, "main", log_embed)

@togglecommand_cmd.autocomplete('command_name')
async def togglecommand_autocomplete(interaction: Interaction, current: str) -> List[Choice[str]]:
    choices = []
    # Use ALL_CONFIGURABLE_COMMANDS_FLAT which is derived from COMMAND_CATEGORIES
    # This ensures consistency with what the dashboard shows.
    for cmd_key in ALL_CONFIGURABLE_COMMANDS_FLAT:
        if current.lower() in cmd_key.lower():
            choices.append(Choice(name=cmd_key, value=cmd_key))
    return choices[:25]

# --- Global Application Command Error Handler ---
async def global_app_command_error_handler(interaction: discord.Interaction, error: app_commands.AppCommandError):
    user_readable_error = "An unexpected error occurred. Please try again later."
    ephemeral_response = True

    if isinstance(error, CommandDisabledInGuild):
        user_readable_error = str(error)
    elif isinstance(error, MissingConfiguredRole):
        user_readable_error = str(error)
    elif isinstance(error, HierarchyError):
        user_readable_error = str(error)
    elif isinstance(error, app_commands.CommandOnCooldown):
        user_readable_error = f"This command is on cooldown. Please try again in {error.retry_after:.2f} seconds."
    elif isinstance(error, app_commands.MissingPermissions): # Catches has_permissions
        user_readable_error = f"You lack the required Discord permissions: {', '.join(error.missing_permissions)}"
    elif isinstance(error, app_commands.BotMissingPermissions):
        user_readable_error = f"I lack the required Discord permissions to do that: {', '.join(error.missing_permissions)}"
    elif isinstance(error, app_commands.CheckFailure): # Generic check failure
        user_readable_error = "You do not meet the requirements to use this command."
    # Add more specific error handling as needed

    # Log the full error for debugging
    print(f"ERROR (Slash Command): User: {interaction.user} ({interaction.user.id}), Guild: {interaction.guild.name if interaction.guild else 'DM'} ({interaction.guild_id}), Command: {interaction.command.name if interaction.command else 'Unknown'}, Error: {type(error).__name__} - {error}")

    try:
        if interaction.response.is_done():
            await interaction.followup.send(user_readable_error, ephemeral=ephemeral_response)
        else:
            await interaction.response.send_message(user_readable_error, ephemeral=ephemeral_response)
    except discord.NotFound: # Interaction might have expired
        print(f"WARNING: Could not send error response for command '{interaction.command.name if interaction.command else 'Unknown'}' as interaction was not found (likely expired).")
    except Exception as e_resp:
        print(f"ERROR: Further error while trying to send command error response: {e_resp}")
bot.tree.on_error = global_app_command_error_handler

# --- Setup Hook (Called once before bot connects, good for initial registrations) ---
@bot.setup_hook
async def initial_setup():
    """Performs initial setup like populating COMMAND_REGISTRY from decorated commands."""
    # This is where we ensure COMMAND_REGISTRY is correctly populated
    # by iterating through bot.tree.get_commands() if necessary,
    # or by ensuring decorators have already populated bot.COMMAND_REGISTRY.
    # The current decorator approach should work if commands are defined before setup_hook runs.
    
    # Let's explicitly build/verify COMMAND_REGISTRY here from the tree
    # This ensures app_command_obj is correctly linked.
    
    temp_command_registry = {}
    all_app_commands = bot.tree.get_commands(type=discord.AppCommandType.chat_input)

    for app_cmd in all_app_commands:
        manageable_flag = True # Default to manageable
        group_name_val = None
        
        if isinstance(app_cmd, app_commands.Group):
            # For commands within groups
            for sub_cmd in app_cmd.commands:
                if isinstance(sub_cmd, app_commands.Command):
                    # Determine if this group/subcommand is considered "manageable"
                    # Config group commands are not manageable by users in this way.
                    if app_cmd.name == arvo_config_group.name: # Example: skip config group
                        manageable_flag = False
                    
                    # Construct the key as used in dashboard/toggling
                    cmd_key = f"{app_cmd.name}_{sub_cmd.name}" if app_cmd.name else sub_cmd.name
                    
                    temp_command_registry[cmd_key] = {
                        "app_command_obj": sub_cmd, # Store the actual subcommand object
                        "manageable": manageable_flag,
                        "group_name": app_cmd.name,
                        "base_name": sub_cmd.name
                    }
        elif isinstance(app_cmd, app_commands.Command):
            # For top-level commands
            if app_cmd.name == togglecommand_cmd.name: # togglecommand itself is not manageable
                manageable_flag = False
            
            temp_command_registry[app_cmd.name] = {
                "app_command_obj": app_cmd,
                "manageable": manageable_flag,
                "group_name": None,
                "base_name": app_cmd.name
            }
            
    # Update the bot's main registry
    # This ensures that the app_command_obj is correctly linked for sync_guild_commands
    bot.COMMAND_REGISTRY.update(temp_command_registry)
    print(f"INFO ({ARVO_BOT_NAME}): COMMAND_REGISTRY populated/updated in setup_hook with {len(bot.COMMAND_REGISTRY)} entries.")
    # print(f"DEBUG: Registry keys: {list(bot.COMMAND_REGISTRY.keys())}")


# --- Running the Bot and Keep-Alive Server ---
async def main_async():
    async with bot:
        await initial_setup() # Call setup_hook logic
        start_keep_alive_server() 
        print(f"Flask web server thread started for {ARVO_BOT_NAME}.")
        print(f"Attempting to connect {ARVO_BOT_NAME} to Discord...")
        await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    if not APP_BASE_URL_CONFIG: print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): APP_BASE_URL or RENDER_EXTERNAL_URL env var not set. Dashboard OAuth will likely fail.")
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET: print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): OAuth env vars not set. Dashboard login will fail.")
    
    # Ensure bot.loop is set before starting flask if flask needs to schedule tasks on it
    # This is now done when bot instance is created.
    
    try: 
        asyncio.run(main_async())
    except KeyboardInterrupt: print(f"{ARVO_BOT_NAME} shutting down manually...")
    except Exception as e: print(f"CRITICAL BOT RUN ERROR for {ARVO_BOT_NAME}: {e}")

