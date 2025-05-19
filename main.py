# main.py (for Main Arvo Bot - serving arvobot.xyz AND dash.arvobot.xyz)
import discord
from discord.ext import commands
from discord import app_commands, ChannelType, Role, SelectOption, Embed, Color, Member, User # Added Member, User here for clarity
from discord.ui import View, Button, ChannelSelect, RoleSelect, Select 
import os
from flask import Flask, render_template, url_for, session, redirect, request, flash, abort 
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
DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID') 
DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')
ARVO_BOT_CLIENT_ID_FOR_INVITE = os.getenv('ARVO_BOT_CLIENT_ID_FOR_INVITE', DISCORD_CLIENT_ID) 

DISCORD_REDIRECT_URI = None
APP_BASE_URL_CONFIG = os.getenv('APP_BASE_URL', RENDER_EXTERNAL_URL) 
if APP_BASE_URL_CONFIG:
    DISCORD_REDIRECT_URI = f"{APP_BASE_URL_CONFIG.rstrip('/')}/callback"
    print(f"INFO ({ARVO_BOT_NAME}): OAuth2 Redirect URI will be: {DISCORD_REDIRECT_URI}")
else:
    print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): APP_BASE_URL or RENDER_EXTERNAL_URL not set. OAuth2 will fail.")

API_ENDPOINT = 'https://discord.com/api/v10' 

if BOT_TOKEN is None: print(f"CRITICAL ({ARVO_BOT_NAME}): DISCORD_TOKEN not set."); exit()
if FLASK_SECRET_KEY is None: print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): FLASK_SECRET_KEY not set. Session security is compromised."); FLASK_SECRET_KEY = "temporary_insecure_key_CHANGE_ME_IMMEDIATELY"


# --- Data Storage Files ---
CONFIG_FILE = "arvo_guild_configs.json"
INFRACTIONS_FILE = "arvo_infractions.json"

# --- Default Guild Configuration Structure ---
DEFAULT_GUILD_CONFIG = {
    "log_channel_id": None,
    "promotion_log_channel_id": None,
    "staff_infraction_log_channel_id": None,
    "staff_role_ids": [], 
    "high_rank_staff_role_id": None, 
    "command_states": {} 
}

# --- Data Storage ---
guild_configurations: Dict[int, Dict[str, Any]] = {} 
infractions_data: Dict[str, List[Dict[str, Any]]] = {} 

def load_from_json(filename: str, default_data: Any = None) -> Any:
    if default_data is None: default_data = {}
    try:
        with open(filename, 'r') as f:
            content = f.read()
            if not content: return default_data # Handle empty file
            return json.loads(content)
    except (FileNotFoundError): print(f"INFO: '{filename}' not found. Will create if needed or use default data.")
    except json.JSONDecodeError: print(f"ERROR: Invalid JSON in '{filename}'. Using default/empty data.")
    return default_data

def save_to_json(data: Any, filename: str):
    try:
        with open(filename, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e: print(f"ERROR: Could not save data to '{filename}': {e}")

def load_all_data():
    global guild_configurations, infractions_data
    raw_guild_configs = load_from_json(CONFIG_FILE, {})
    guild_configurations = {int(k): v for k, v in raw_guild_configs.items()} # Ensure keys are int
    infractions_data = load_from_json(INFRACTIONS_FILE, {})
    print(f"INFO ({ARVO_BOT_NAME}): All data loaded from JSON files.")

def get_guild_config(guild_id: int) -> Dict[str, Any]:
    if guild_id not in guild_configurations:
        guild_configurations[guild_id] = json.loads(json.dumps(DEFAULT_GUILD_CONFIG))
        guild_configurations[guild_id]["command_states"] = {
            cmd_key: True for cmd_key in ALL_CONFIGURABLE_COMMANDS_FLAT 
        }
        save_to_json(guild_configurations, CONFIG_FILE)
        print(f"INFO: Created default config for guild {guild_id}")
    
    config = guild_configurations[guild_id]
    updated = False
    for key, default_value in DEFAULT_GUILD_CONFIG.items():
        if key not in config:
            config[key] = json.loads(json.dumps(default_value)) 
            updated = True
    if "command_states" not in config: config["command_states"] = {}; updated = True
    
    for cmd_key in ALL_CONFIGURABLE_COMMANDS_FLAT:
        if cmd_key not in config["command_states"]:
            config["command_states"][cmd_key] = True; updated = True
            
    if updated: save_to_json(guild_configurations, CONFIG_FILE)
    return config

def get_guild_log_channel_id(guild_id: int, log_type: str = "main") -> Optional[int]:
    config = get_guild_config(guild_id)
    if log_type == "main": return config.get('log_channel_id')
    elif log_type == "promotion": return config.get('promotion_log_channel_id')
    elif log_type == "staff_infraction": return config.get('staff_infraction_log_channel_id')
    return None

def is_command_enabled_for_guild(guild_id: int, command_name: str) -> bool:
    config = get_guild_config(guild_id)
    return config.get('command_enabled_states', {}).get(command_name, True) 

# --- Flask App ---
app = Flask(__name__) 
app.secret_key = FLASK_SECRET_KEY

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
    except requests.exceptions.RequestException as e: print(f"ERROR: OAuth2 callback exception: {e}"); flash("Error during Discord authentication. Please try again.", "error"); return redirect(url_for('index'))
@app.route('/logout')
def logout(): session.clear(); flash("You have been logged out.", "success"); return redirect(url_for('index'))

@app.route('/dashboard') 
@app.route('/dashboard/servers') 
def dashboard_servers():
    if 'discord_user_id' not in session: return redirect(url_for('login', next=request.url))
    access_token = session.get('discord_oauth_token', {}).get('access_token')
    if not access_token: flash("Your session has expired. Please log in again.", "error"); return redirect(url_for('logout'))
    headers = {'Authorization': f'Bearer {access_token}'}
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
        if hasattr(e, 'response') and e.response is not None and e.response.status_code == 401: flash("Your Discord session may have expired. Please log in again.", "error"); return redirect(url_for('logout'))
        flash("An error occurred while fetching your server list. Please try again.", "error")
    return render_template('dashboard_servers.html', ARVO_BOT_NAME=ARVO_BOT_NAME, manageable_servers=manageable_servers,
                           other_servers_with_bot=other_servers_with_bot, DISCORD_CLIENT_ID_BOT=ARVO_BOT_CLIENT_ID_FOR_INVITE, session=session)

COMMAND_CATEGORIES = {
    "Utility": ["ping", "arvohelp"],
    "Staff & Infraction Management": [
        "infract_warn", "infract_mute", "infract_kick", "infract_ban", 
        "staffmanage_promote", "staffmanage_demote", "staffmanage_terminate",
        "staffinfract_warning", "staffinfract_strike", 
        "viewinfractions" 
    ],
    "Configuration": ["arvo_config_setup"] 
}
ALL_CONFIGURABLE_COMMANDS_FLAT = [cmd for sublist in COMMAND_CATEGORIES.values() for cmd in sublist if cmd != "arvo_config_setup"]


@app.route('/dashboard/guild/<guild_id_str>', methods=['GET'])
def dashboard_guild(guild_id_str: str):
    if 'discord_user_id' not in session: return redirect(url_for('login', next=request.url))
    try: guild_id = int(guild_id_str)
    except ValueError: flash("Invalid Server ID format.", "error"); return redirect(url_for('dashboard_servers'))

    access_token = session.get('discord_oauth_token', {}).get('access_token')
    if not access_token: flash("Your session has expired. Please log in again.", "error"); return redirect(url_for('logout'))
    headers = {'Authorization': f'Bearer {access_token}'}
    can_manage_this_guild = False; guild_name_for_dashboard = "Server"
    try:
        guilds_response = requests.get(f'{API_ENDPOINT}/users/@me/guilds', headers=headers); guilds_response.raise_for_status()
        user_guilds_list = guilds_response.json()
        for g_data in user_guilds_list:
            if g_data['id'] == guild_id_str:
                if discord.Permissions(int(g_data['permissions'])).manage_guild: can_manage_this_guild = True; guild_name_for_dashboard = g_data['name']
                break
    except Exception as e: print(f"Error re-fetching guilds for /dashboard/guild/{guild_id_str}: {e}"); flash("Error verifying server permissions.", "error"); return redirect(url_for('dashboard_servers')) 
    if not can_manage_this_guild: flash("You do not have permission to manage this server's Arvo settings.", "error"); return redirect(url_for('dashboard_servers'))
    
    actual_guild_object = bot.get_guild(guild_id)
    if not actual_guild_object: flash(f"{ARVO_BOT_NAME} is not in '{guild_name_for_dashboard}'. Please invite it first.", "error"); return redirect(url_for('dashboard_servers'))

    guild_config = get_guild_config(guild_id)
    command_states = guild_config.get('command_enabled_states', {})
    for cmd_name in ALL_CONFIGURABLE_COMMANDS_FLAT: 
        if cmd_name not in command_states: command_states[cmd_name] = True 

    guild_channels = [{'id': str(ch.id), 'name': ch.name} for ch in sorted(actual_guild_object.text_channels, key=lambda c: c.name) if ch.permissions_for(actual_guild_object.me).send_messages]
    guild_roles = [{'id': str(r.id), 'name': r.name} for r in sorted(actual_guild_object.roles, key=lambda role: role.position, reverse=True) if not r.is_default()]


    return render_template('dashboard_guild.html', 
                           ARVO_BOT_NAME=ARVO_BOT_NAME, 
                           guild_name=guild_name_for_dashboard, 
                           guild_id=guild_id_str,
                           command_categories=COMMAND_CATEGORIES,
                           command_states=command_states,
                           guild_channels=guild_channels,
                           guild_roles=guild_roles,
                           current_main_log_channel_id=str(guild_config.get("log_channel_id")) if guild_config.get("log_channel_id") else "",
                           current_promotion_log_channel_id=str(guild_config.get("promotion_log_channel_id")) if guild_config.get("promotion_log_channel_id") else "",
                           current_staff_infraction_log_channel_id=str(guild_config.get("staff_infraction_log_channel_id")) if guild_config.get("staff_infraction_log_channel_id") else "",
                           current_staff_role_ids=[str(r_id) for r_id in guild_config.get("staff_role_ids", [])],
                           current_high_rank_staff_role_id=str(guild_config.get("high_rank_staff_role_id")) if guild_config.get("high_rank_staff_role_id") else "",
                           session=session)

@app.route('/dashboard/guild/<guild_id_str>/save_command_settings', methods=['POST'])
def save_command_settings(guild_id_str: str):
    if 'discord_user_id' not in session: return redirect(url_for('login', next=request.referrer or url_for('dashboard_servers')))
    try: guild_id = int(guild_id_str)
    except ValueError: abort(400, "Invalid Guild ID")

    access_token = session.get('discord_oauth_token', {}).get('access_token')
    if not access_token: flash("Your session has expired.", "error"); return redirect(url_for('logout'))
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
    
    guild_config = get_guild_config(guild_id)
    command_enabled_states = guild_config.setdefault('command_enabled_states', {})
    something_changed = False
    for cmd_name in ALL_CONFIGURABLE_COMMANDS_FLAT:
        is_enabled = f'cmd_{cmd_name}' in request.form 
        if command_enabled_states.get(cmd_name, True) != is_enabled: something_changed = True
        command_enabled_states[cmd_name] = is_enabled
    
    save_to_json(guild_configurations, CONFIG_FILE)
    
    if something_changed:
        async def do_sync():
            target_guild = bot.get_guild(guild_id)
            if target_guild: await sync_guild_commands(target_guild)
        if bot.loop: bot.loop.create_task(do_sync())
        flash('Command settings saved and sync initiated!', 'success')
    else:
        flash('No changes detected in command settings.', 'info')
    return redirect(url_for('dashboard_guild', guild_id_str=guild_id_str))

@app.route('/dashboard/guild/<guild_id_str>/save_log_channel_settings', methods=['POST'])
def save_log_channel_settings(guild_id_str: str):
    if 'discord_user_id' not in session: return redirect(url_for('login', next=request.referrer or url_for('dashboard_guild', guild_id_str=guild_id_str)))
    try: guild_id = int(guild_id_str)
    except ValueError: abort(400, "Invalid Guild ID")

    actual_guild_object = bot.get_guild(guild_id)
    if not actual_guild_object: abort(404, "Bot not in guild or guild not found")
    user_discord_id = session.get('discord_user_id')
    if not user_discord_id: abort(403, "User session error.") 
    
    member = actual_guild_object.get_member(int(user_discord_id))
    if not member or not member.guild_permissions.administrator:
        abort(403, "You must be an Administrator to change log channel settings.")

    guild_config = get_guild_config(guild_id)
    try:
        guild_config['log_channel_id'] = int(request.form.get('main_log_channel')) if request.form.get('main_log_channel') else None
        guild_config['promotion_log_channel_id'] = int(request.form.get('promotion_log_channel')) if request.form.get('promotion_log_channel') else None
        guild_config['staff_infraction_log_channel_id'] = int(request.form.get('staff_infraction_log_channel')) if request.form.get('staff_infraction_log_channel') else None
    except ValueError:
        flash("Invalid channel ID submitted.", "error")
        return redirect(url_for('dashboard_guild', guild_id_str=guild_id_str))

    save_to_json(guild_configurations, CONFIG_FILE)
    flash('Log channel settings saved successfully!', 'success')
    return redirect(url_for('dashboard_guild', guild_id_str=guild_id_str))

@app.route('/dashboard/guild/<guild_id_str>/save_staff_role_settings', methods=['POST'])
def save_staff_role_settings(guild_id_str: str):
    if 'discord_user_id' not in session: return redirect(url_for('login', next=request.referrer or url_for('dashboard_guild', guild_id_str=guild_id_str)))
    try: guild_id = int(guild_id_str)
    except ValueError: abort(400, "Invalid Guild ID")

    actual_guild_object = bot.get_guild(guild_id)
    if not actual_guild_object: abort(404, "Bot not in guild or guild not found")
    user_discord_id = session.get('discord_user_id')
    if not user_discord_id: abort(403, "User session error.")

    member = actual_guild_object.get_member(int(user_discord_id))
    if not member or not member.guild_permissions.administrator:
        abort(403, "You must be an Administrator to change staff role settings.")

    guild_config = get_guild_config(guild_id)
    try:
        guild_config['staff_role_ids'] = [int(r_id) for r_id in request.form.getlist('staff_role_ids')]
        guild_config['high_rank_staff_role_id'] = int(request.form.get('high_rank_staff_role_id')) if request.form.get('high_rank_staff_role_id') else None
    except ValueError:
        flash("Invalid role ID submitted.", "error")
        return redirect(url_for('dashboard_guild', guild_id_str=guild_id_str))

    save_to_json(guild_configurations, CONFIG_FILE)
    flash('Staff role settings saved successfully!', 'success')
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
bot.loop = asyncio.get_event_loop() 
bot.COMMAND_REGISTRY = {} 

# --- Custom Check Exceptions ---
class CommandDisabledInGuild(app_commands.CheckFailure):
    def __init__(self, command_name: str, *args):
        super().__init__(f"The command `/{command_name.replace('_', ' ')}` is currently disabled in this server.", *args)

class MissingConfiguredRole(app_commands.CheckFailure):
    def __init__(self, command_name: str, role_name: str | None, *args):
        message = f"You need the '{role_name}' role to use `/{command_name.replace('_', ' ')}`." if role_name else f"You lack permissions for `/{command_name.replace('_', ' ')}`."
        super().__init__(message, *args)

class HierarchyError(app_commands.CheckFailure):
    def __init__(self, message: str, *args): super().__init__(message, *args)

# --- Permission Check Functions & Decorators ---
def is_general_staff(interaction: discord.Interaction) -> bool: 
    if not interaction.guild or not isinstance(interaction.user, discord.Member): return False 
    if interaction.user.guild_permissions.administrator: return True
    config = get_guild_config(interaction.guild_id)
    staff_role_ids = config.get("staff_role_ids", [])
    return any(role.id in staff_role_ids for role in interaction.user.roles)

def is_high_rank_staff(interaction: discord.Interaction) -> bool: 
    if not interaction.guild or not isinstance(interaction.user, discord.Member): return False 
    if interaction.user.guild_permissions.administrator: return True
    config = get_guild_config(interaction.guild_id)
    high_rank_role_id = config.get("high_rank_staff_role_id")
    if not high_rank_role_id: return False 
    return any(role.id == high_rank_role_id for role in interaction.user.roles)

def check_command_status_and_permission(permission_level: Optional[str] = "general_staff"):
    async def predicate(interaction: discord.Interaction) -> bool: 
        if not interaction.guild_id: return True 
        
        cmd_obj = interaction.command
        command_name_key = cmd_obj.name
        if cmd_obj.parent: 
            command_name_key = f"{cmd_obj.parent.name}_{cmd_obj.name}"
        
        if not is_command_enabled_for_guild(interaction.guild_id, command_name_key):
            raise CommandDisabledInGuild(command_name_key)

        if permission_level == "general_staff":
            if not is_general_staff(interaction):
                raise MissingConfiguredRole(command_name_key, "configured Staff")
        elif permission_level == "high_rank_staff":
            config = get_guild_config(interaction.guild_id)
            high_rank_role_id = config.get("high_rank_staff_role_id")
            if not interaction.user.guild_permissions.administrator:
                if not high_rank_role_id: raise MissingConfiguredRole(command_name_key, "configured High-Rank Staff (or Administrator)")
                if not isinstance(interaction.user, discord.Member) or not any(role.id == high_rank_role_id for role in interaction.user.roles): 
                    role_name = "configured High-Rank Staff"; role_obj = interaction.guild.get_role(high_rank_role_id)
                    if role_obj: role_name = role_obj.name
                    raise MissingConfiguredRole(command_name_key, role_name)
        elif permission_level == "admin_only":
            if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator: 
                raise MissingConfiguredRole(command_name_key, "Discord Administrator")
        return True
    return app_commands.check(predicate)

# --- Confirmation View & Logging Helper ---
class ConfirmationView(View):
    def __init__(self, author_id: int):
        super().__init__(timeout=60.0); self.value = None; self.author_id = author_id
    async def interaction_check(self, interaction: discord.Interaction) -> bool: 
        if interaction.user.id != self.author_id: await interaction.response.send_message("This confirmation is not for you.", ephemeral=True); return False
        return True
    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm_button(self, interaction: discord.Interaction, button: Button): 
        self.value = True; self.stop()
        for item in self.children: 
            if isinstance(item, Button): item.disabled = True 
        await interaction.response.edit_message(view=self)
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel_button(self, interaction: discord.Interaction, button: Button): 
        self.value = False; self.stop()
        for item in self.children: 
            if isinstance(item, Button): item.disabled = True 
        await interaction.response.edit_message(view=self)

async def log_to_discord_channel(guild: discord.Guild, channel_type: str, embed: discord.Embed, content: Optional[str] = None):
    log_channel_id = get_guild_log_channel_id(guild.id, channel_type)
    if not log_channel_id and channel_type != "main": 
        log_channel_id = get_guild_log_channel_id(guild.id, "main")
        if log_channel_id: embed.set_footer(text=f"{embed.footer.text if embed.footer and embed.footer.text else ''} (Sent to main log: {channel_type} log channel not set)".strip())
            
    if log_channel_id:
        log_channel = guild.get_channel(log_channel_id)
        if isinstance(log_channel, TextChannel):
            try: await log_channel.send(content=content, embed=embed)
            except discord.Forbidden: print(f"Log Error (Guild: {guild.id}, Type: {channel_type}): Missing permissions in log channel {log_channel_id}.")
            except Exception as e: print(f"Log Error (Guild: {guild.id}, Type: {channel_type}): {e}")
        else: print(f"Log Warning (Guild: {guild.id}, Type: {channel_type}): Channel ID {log_channel_id} not valid.")

def add_infraction_record(guild_id: int, user_id: int, type: str, reason: str, moderator_id: int, duration: Optional[str] = None, points: Optional[int] = 0) -> str:
    key = f"{guild_id}-{user_id}"; infraction_id = str(uuid.uuid4())[:8]
    infraction_record = {"id": infraction_id, "type": type, "reason": reason, "moderator_id": moderator_id, "timestamp": discord.utils.utcnow().isoformat(), "duration": duration, "points": points}
    if key not in infractions_data: infractions_data[key] = []
    infractions_data[key].append(infraction_record); save_to_json(infractions_data, INFRACTIONS_FILE)
    return infraction_id

def check_hierarchy(interaction: discord.Interaction, target_member: discord.Member) -> bool: 
    if interaction.user.id == target_member.id: raise HierarchyError("You cannot perform this action on yourself.")
    if not isinstance(interaction.user, discord.Member) : return False 
    if interaction.user.id == interaction.guild.owner_id: return True
    if target_member.id == interaction.guild.owner_id: raise HierarchyError("You cannot perform this action on the server owner.")
    if not interaction.user.guild_permissions.administrator and target_member.guild_permissions.administrator: raise HierarchyError("You cannot perform this action on an administrator if you are not one.")
    if isinstance(interaction.user, discord.Member) and isinstance(target_member, discord.Member): 
        if interaction.user.top_role <= target_member.top_role: raise HierarchyError("You cannot perform this action on a member with an equal or higher role.")
    return True

# --- Bot Event Listeners ---
@bot.event
async def on_ready():
    load_all_data() 
    print(f'{ARVO_BOT_NAME} has logged in as {bot.user.name} (ID: {bot.user.id})')
    print(f'Discord.py Version: {discord.__version__}')
    if RENDER_EXTERNAL_URL: print(f"INFO ({ARVO_BOT_NAME}): Website accessible via {RENDER_EXTERNAL_URL}")
    if not all([DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, FLASK_SECRET_KEY]): print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): Core OAuth/Flask env vars missing.")
    
    await bot.COMMAND_REGISTRY_READY.wait() 
    for guild in bot.guilds: await sync_guild_commands(guild)
    
    print(f'{ARVO_BOT_NAME} is ready and online!')
    await bot.change_presence(activity=discord.Game(name=f"/arvohelp | {ARVO_BOT_NAME}"))

@bot.event
async def on_guild_join(guild: discord.Guild):
    print(f"INFO: Joined new guild: {guild.name} (ID: {guild.id})")
    get_guild_config(guild.id) 
    await bot.COMMAND_REGISTRY_READY.wait()
    await sync_guild_commands(guild)

async def sync_guild_commands(guild: discord.Guild):
    print(f"INFO: Attempting to sync commands for guild: {guild.name} ({guild.id})")
    guild_config = get_guild_config(guild.id)
    try:
        bot.tree.clear_commands(guild=guild)
        
        bot.tree.add_command(arvo_config_group, guild=guild) 
        bot.tree.add_command(togglecommand_cmd, guild=guild)
        
        added_groups_this_sync = set()

        for cmd_key, cmd_data in bot.COMMAND_REGISTRY.items():
            if not cmd_data.get("manageable", True): continue
            app_cmd_obj = cmd_data.get("app_command_obj")
            if not app_cmd_obj: print(f"WARNING: No app_command_obj for {cmd_key} during sync for {guild.name}"); continue

            is_enabled = guild_config.get("command_states", {}).get(cmd_key, True)
            if is_enabled:
                parent_group_name = cmd_data.get("group_name")
                if parent_group_name:
                    if parent_group_name not in added_groups_this_sync:
                        group_to_add = None
                        if parent_group_name == "infract": group_to_add = infract_group
                        elif parent_group_name == "staffmanage": group_to_add = staffmanage_group
                        elif parent_group_name == "staffinfract": group_to_add = staffinfract_group
                        
                        if group_to_add:
                            try: bot.tree.add_command(group_to_add, guild=guild); added_groups_this_sync.add(parent_group_name)
                            except discord.app_commands.CommandAlreadyRegistered: pass 
                        else: print(f"WARNING: Could not find group object for {parent_group_name}")
                else: 
                    bot.tree.add_command(app_cmd_obj, guild=guild)
        
        await bot.tree.sync(guild=guild)
        print(f"SUCCESS: Synced commands for guild {guild.name} ({guild.id}).")
    except discord.errors.Forbidden: print(f"FORBIDDEN: Cannot sync commands for guild {guild.name}. Check 'application.commands' scope.")
    except Exception as e: print(f"ERROR: Failed to sync commands for guild {guild.name}: {type(e).__name__} - {e}")

# --- Command Groups ---
arvo_config_group = app_commands.Group(name="arvo_config", description="Configure Arvo bot for this server.", guild_only=True) 
infract_group = app_commands.Group(name="infract", description="User infraction management commands.", guild_only=True) 
staffmanage_group = app_commands.Group(name="staffmanage", description="Staff management commands.", guild_only=True) 
staffinfract_group = app_commands.Group(name="staffinfract", description="Staff infraction commands.", guild_only=True) 

# --- Utility Commands ---
@bot.tree.command(name="ping", description=f"Check {ARVO_BOT_NAME}'s responsiveness.")
@check_command_status_and_permission(permission_level=None)
async def ping(interaction: discord.Interaction): 
    await interaction.response.send_message(f"{ARVO_BOT_NAME} Pong! 🏓 Latency: {bot.latency * 1000:.2f}ms", ephemeral=True)

@bot.tree.command(name="arvohelp", description=f"Get information about {ARVO_BOT_NAME}.")
@check_command_status_and_permission(permission_level=None)
async def arvohelp(interaction: discord.Interaction): 
    embed = Embed(title=f"{ARVO_BOT_NAME} - Smart Staff Management", description=ARVO_BOT_DESCRIPTION, color=Color.blue())
    embed.add_field(name="How to Use", value="Use slash commands. Manage settings via the dashboard.", inline=False)
    website_url = APP_BASE_URL_CONFIG if APP_BASE_URL_CONFIG else "https://arvobot.xyz" 
    embed.add_field(name="Website & Dashboard", value=f"Visit [{website_url.replace('https://','').replace('http://','')}]( {website_url} )", inline=False)
    embed.set_footer(text=f"{ARVO_BOT_NAME} - Your reliable staff management assistant.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- Config Group Commands ---
@arvo_config_group.command(name="setup", description=f"Get links to {ARVO_BOT_NAME}'s configuration dashboard.")
@app_commands.checks.has_permissions(administrator=True) 
async def arvo_config_setup(interaction: discord.Interaction): 
    dashboard_link_base = APP_BASE_URL_CONFIG.rstrip('/') if APP_BASE_URL_CONFIG else None
    if not dashboard_link_base: await interaction.response.send_message("Dashboard link not available (APP_BASE_URL not set).", ephemeral=True); return
    db_link_servers = f"{dashboard_link_base}/dashboard/servers"
    msg = f"Hello Admin! Links for managing {ARVO_BOT_NAME}:\n- **Server Selection:** {db_link_servers}\n"
    if interaction.guild: msg += f"- **Direct Dashboard for {interaction.guild.name}:** {dashboard_link_base}/dashboard/guild/{interaction.guild.id}\n\n"
    msg += "Use the dashboard to configure log channels, staff roles, and command settings."
    await interaction.response.send_message(msg, ephemeral=True)

# --- Infraction Commands ---
@infract_group.command(name="warn", description="Warns a user.")
@check_command_status_and_permission(permission_level="general_staff")
@app_commands.describe(member="The member to warn.", reason="The reason for the warning.")
async def infract_warn(interaction: discord.Interaction, member: discord.Member, reason: str): 
    if not interaction.guild: return
    try: check_hierarchy(interaction, member)
    except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return
    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"Warn {member.mention} for: \"{reason}\"?\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()
    if view.value is True:
        inf_id = add_infraction_record(interaction.guild_id, member.id, "warn", reason, interaction.user.id, points=1)
        log_embed = Embed(title="User Warned", color=Color.gold(), timestamp=discord.utils.utcnow())
        log_embed.set_author(name=f"Mod: {interaction.user}", icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
        log_embed.add_field(name="User", value=f"{member.mention} ({member.id})", inline=False).add_field(name="Reason", value=reason, inline=False)
        log_embed.set_footer(text=f"Infraction ID: {inf_id} | Guild: {interaction.guild.name}")
        await log_to_discord_channel(interaction.guild, "main", log_embed)
        try: await member.send(f"You were warned in **{interaction.guild.name}** for: {reason}\n*ID: {inf_id}*")
        except: await interaction.followup.send(f"✅ {member.mention} warned. Could not DM.", ephemeral=True); return
        await interaction.followup.send(f"✅ {member.mention} warned. Reason: {reason}", ephemeral=True)
    elif view.value is False: await interaction.followup.send("⚠️ Warn cancelled.", ephemeral=True)
    else: await interaction.followup.send("⚠️ Warn confirmation timed out.", ephemeral=True)

@infract_group.command(name="mute", description="Mutes a user for a specified number of hours.")
@check_command_status_and_permission(permission_level="general_staff")
@app_commands.describe(member="The member to mute.", hours="Duration in hours (1-672).", reason="The reason for the mute.")
async def infract_mute(interaction: discord.Interaction, member: discord.Member, hours: app_commands.Range[int, 1, 672], reason: str): 
    if not interaction.guild: return
    try: check_hierarchy(interaction, member)
    except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return
    dur_str = f"{hours} hour{'s' if hours > 1 else ''}"; delta = datetime.timedelta(hours=hours)
    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"Mute {member.mention} for {dur_str}? Reason: \"{reason}\".\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()
    if view.value is True:
        try:
            await member.timeout(delta, reason=f"Muted by {interaction.user.name}: {reason}")
            inf_id = add_infraction_record(interaction.guild_id, member.id, "mute", reason, interaction.user.id, duration=dur_str, points=3)
            log_embed = Embed(title="User Muted", color=Color.orange(), timestamp=discord.utils.utcnow())
            log_embed.set_author(name=f"Mod: {interaction.user}", icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
            log_embed.add_field(name="User", value=f"{member.mention} ({member.id})", inline=False).add_field(name="Duration", value=dur_str, inline=True).add_field(name="Reason", value=reason, inline=False)
            log_embed.set_footer(text=f"Infraction ID: {inf_id} | Guild: {interaction.guild.name}")
            await log_to_discord_channel(interaction.guild, "main", log_embed)
            try: await member.send(f"You were muted in **{interaction.guild.name}** for **{dur_str}**. Reason: {reason}\n*ID: {inf_id}*")
            except: pass
            await interaction.followup.send(f"✅ {member.mention} muted for {dur_str}. Reason: {reason}", ephemeral=True)
        except discord.Forbidden: await interaction.followup.send(f"🚫 Failed to mute {member.mention}. Permissions error.", ephemeral=True)
        except Exception as e: await interaction.followup.send(f"Error muting: {e}", ephemeral=True)
    elif view.value is False: await interaction.followup.send("⚠️ Mute cancelled.", ephemeral=True)
    else: await interaction.followup.send("⚠️ Mute confirmation timed out.", ephemeral=True)

@infract_group.command(name="kick", description="Kicks a user from the server.")
@check_command_status_and_permission(permission_level="general_staff")
@app_commands.describe(member="The member to kick.", reason="The reason for the kick.")
async def infract_kick(interaction: discord.Interaction, member: discord.Member, reason: str): 
    if not interaction.guild: return
    try: check_hierarchy(interaction, member)
    except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return
    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"Kick {member.mention}? Reason: \"{reason}\".\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()
    if view.value is True:
        dm_msg = f"You were kicked from **{interaction.guild.name}**. Reason: {reason}"; inf_id = "N/A"
        try: await member.send(dm_msg)
        except: pass
        try:
            await member.kick(reason=f"Kicked by {interaction.user.name}: {reason}")
            inf_id = add_infraction_record(interaction.guild_id, member.id, "kick", reason, interaction.user.id, points=5)
            log_embed = Embed(title="User Kicked", color=Color.dark_orange(), timestamp=discord.utils.utcnow())
            log_embed.set_author(name=f"Mod: {interaction.user}", icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
            log_embed.add_field(name="User", value=f"{member.display_name} ({member.id})", inline=False).add_field(name="Reason", value=reason, inline=False)
            log_embed.set_footer(text=f"Infraction ID: {inf_id} | Guild: {interaction.guild.name}")
            await log_to_discord_channel(interaction.guild, "main", log_embed)
            await interaction.followup.send(f"✅ {member.display_name} kicked. Reason: {reason}", ephemeral=True)
        except discord.Forbidden: await interaction.followup.send(f"🚫 Failed to kick {member.display_name}. Permissions error.", ephemeral=True)
        except Exception as e: await interaction.followup.send(f"Error kicking: {e}", ephemeral=True)
    elif view.value is False: await interaction.followup.send("⚠️ Kick cancelled.", ephemeral=True)
    else: await interaction.followup.send("⚠️ Kick confirmation timed out.", ephemeral=True)

@infract_group.command(name="ban", description="Bans a user from the server.")
@check_command_status_and_permission(permission_level="general_staff")
@app_commands.describe(user="User to ban (ID if not in server).", reason="Reason for ban.", delete_message_days="Days of messages to delete (0-7).")
async def infract_ban(interaction: discord.Interaction, user: discord.User, reason: str, delete_message_days: app_commands.Range[int, 0, 7] = 0): 
    if not interaction.guild: return
    target_member = interaction.guild.get_member(user.id)
    if target_member:
        try: check_hierarchy(interaction, target_member)
        except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return
    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"Ban {user.mention} ({user.id})? Reason: \"{reason}\". Delete msgs: {delete_message_days} days.\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()
    if view.value is True:
        dm_msg = f"You were banned from **{interaction.guild.name}**. Reason: {reason}"
        try: await user.send(dm_msg)
        except: pass
        try:
            await interaction.guild.ban(user, reason=f"Banned by {interaction.user.name}: {reason}", delete_message_days=delete_message_days)
            inf_id = add_infraction_record(interaction.guild_id, user.id, "ban", reason, interaction.user.id, points=10)
            log_embed = Embed(title="User Banned", color=Color.red(), timestamp=discord.utils.utcnow())
            log_embed.set_author(name=f"Mod: {interaction.user}", icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
            log_embed.add_field(name="User", value=f"{user.mention} ({user.id})", inline=False).add_field(name="Reason", value=reason, inline=False).add_field(name="Msgs Deleted", value=f"{delete_message_days} days", inline=True)
            log_embed.set_footer(text=f"Infraction ID: {inf_id} | Guild: {interaction.guild.name}")
            await log_to_discord_channel(interaction.guild, "main", log_embed)
            await interaction.followup.send(f"✅ {user.display_name} ({user.id}) banned. Reason: {reason}", ephemeral=True)
        except discord.Forbidden: await interaction.followup.send(f"🚫 Failed to ban {user.display_name}. Permissions error.", ephemeral=True)
        except Exception as e: await interaction.followup.send(f"Error banning: {e}", ephemeral=True)
    elif view.value is False: await interaction.followup.send("⚠️ Ban cancelled.", ephemeral=True)
    else: await interaction.followup.send("⚠️ Ban confirmation timed out.", ephemeral=True)

# --- Staff Management Commands ---
@staffmanage_group.command(name="promote", description="Promotes a staff member and assigns a new role.")
@check_command_status_and_permission(permission_level="high_rank_staff")
@app_commands.describe(staff_member="Staff member to promote.", new_role="New role to assign.", reason="Reason for promotion.")
async def staffmanage_promote(interaction: discord.Interaction, staff_member: discord.Member, new_role: discord.Role, reason: str): 
    if not interaction.guild: return
    try: check_hierarchy(interaction, staff_member)
    except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return
    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"Promote {staff_member.mention} to {new_role.mention}? Reason: \"{reason}\".\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()
    if view.value is True:
        try:
            await staff_member.add_roles(new_role, reason=f"Promoted by {interaction.user.name}: {reason}")
            log_main = Embed(title="Staff Promoted (Log)", color=Color.teal(), timestamp=discord.utils.utcnow())
            log_main.set_author(name=f"Manager: {interaction.user}", icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
            log_main.add_field(name="Staff", value=f"{staff_member.mention} ({staff_member.id})", inline=False).add_field(name="New Role", value=new_role.mention, inline=True).add_field(name="Reason", value=reason, inline=False)
            log_main.set_footer(text=f"Guild: {interaction.guild.name}")
            await log_to_discord_channel(interaction.guild, "main", log_main)

            promo_log = Embed(title="🎉 Staff Promotion 🎉", description="The Executive team has decided to promote you! Congratulations!", color=Color.gold(), timestamp=discord.utils.utcnow())
            promo_log.set_author(name=staff_member.display_name, icon_url=staff_member.display_avatar.url if staff_member.display_avatar else None)
            promo_log.add_field(name="Staff member:", value=staff_member.mention, inline=False).add_field(name="New Rank:", value=new_role.mention, inline=False).add_field(name="Reason:", value=reason, inline=False).add_field(name="Promoted by:", value=interaction.user.mention, inline=False)
            await log_to_discord_channel(interaction.guild, "promotion", promo_log, content=staff_member.mention)
            try: await staff_member.send(f"Congrats! You've been promoted in **{interaction.guild.name}** to **{new_role.name}**. Reason: {reason}\n*By: {interaction.user.mention}*")
            except: pass
            await interaction.followup.send(f"✅ {staff_member.mention} promoted to {new_role.mention}. Reason: {reason}", ephemeral=True)
        except discord.Forbidden: await interaction.followup.send(f"🚫 Failed to promote {staff_member.mention}. Role/Perms error.", ephemeral=True)
        except Exception as e: await interaction.followup.send(f"Error promoting: {e}", ephemeral=True)
    elif view.value is False: await interaction.followup.send("⚠️ Promotion cancelled.", ephemeral=True)
    else: await interaction.followup.send("⚠️ Promotion confirmation timed out.", ephemeral=True)

@staffmanage_group.command(name="demote", description="Demotes a staff member and removes a role.")
@check_command_status_and_permission(permission_level="high_rank_staff")
@app_commands.describe(staff_member="Staff member to demote.", role_to_remove="Role to remove.", reason="Reason for demotion.")
async def staffmanage_demote(interaction: discord.Interaction, staff_member: discord.Member, role_to_remove: discord.Role, reason: str): 
    if not interaction.guild: return
    try: check_hierarchy(interaction, staff_member)
    except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return
    if role_to_remove not in staff_member.roles: await interaction.response.send_message(f"{staff_member.mention} doesn't have {role_to_remove.mention}.", ephemeral=True); return
    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"Demote {staff_member.mention} (remove {role_to_remove.mention})? Reason: \"{reason}\".\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()
    if view.value is True:
        try:
            await staff_member.remove_roles(role_to_remove, reason=f"Demoted by {interaction.user.name}: {reason}")
            log_main = Embed(title="Staff Demoted (Log)", color=Color.dark_gold(), timestamp=discord.utils.utcnow())
            log_main.set_author(name=f"Manager: {interaction.user}", icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
            log_main.add_field(name="Staff", value=f"{staff_member.mention} ({staff_member.id})", inline=False).add_field(name="Role Removed", value=role_to_remove.mention, inline=True).add_field(name="Reason", value=reason, inline=False)
            log_main.set_footer(text=f"Guild: {interaction.guild.name}")
            await log_to_discord_channel(interaction.guild, "main", log_main)
            try: await staff_member.send(f"You've been demoted in **{interaction.guild.name}**. Role **{role_to_remove.name}** removed. Reason: {reason}\n*By: {interaction.user.mention}*")
            except: pass
            await interaction.followup.send(f"✅ {staff_member.mention} demoted (role {role_to_remove.mention} removed). Reason: {reason}", ephemeral=True)
        except discord.Forbidden: await interaction.followup.send(f"🚫 Failed to demote {staff_member.mention}. Role/Perms error.", ephemeral=True)
        except Exception as e: await interaction.followup.send(f"Error demoting: {e}", ephemeral=True)
    elif view.value is False: await interaction.followup.send("⚠️ Demotion cancelled.", ephemeral=True)
    else: await interaction.followup.send("⚠️ Demotion confirmation timed out.", ephemeral=True)

@staffmanage_group.command(name="terminate", description="Logs staff termination. Manual role removal required.")
@check_command_status_and_permission(permission_level="high_rank_staff")
@app_commands.describe(staff_member="Staff member being terminated.", reason="Reason for termination.")
async def staffmanage_terminate(interaction: discord.Interaction, staff_member: discord.Member, reason: str): 
    if not interaction.guild: return
    try: check_hierarchy(interaction, staff_member)
    except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return
    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"Log termination of {staff_member.mention}? Reason: \"{reason}\".\n**Manual role removal required.**\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()
    if view.value is True:
        inf_id = add_infraction_record(interaction.guild_id, staff_member.id, "staff_termination", reason, interaction.user.id, points=0)
        log_main = Embed(title="Staff Termination Logged", color=Color.dark_red(), timestamp=discord.utils.utcnow())
        log_main.set_author(name=f"Manager: {interaction.user}", icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
        log_main.add_field(name="Staff", value=f"{staff_member.mention} ({staff_member.id})", inline=False).add_field(name="Reason", value=reason, inline=False).add_field(name="Action Required", value="Manually remove staff roles.", inline=False)
        log_main.set_footer(text=f"Termination Record ID: {inf_id} | Guild: {interaction.guild.name}")
        await log_to_discord_channel(interaction.guild, "main", log_main)
        
        staff_inf_log = Embed(title=f"{interaction.guild.name} | Staff Infraction", color=Color.dark_red(), timestamp=discord.utils.utcnow())
        staff_inf_log.add_field(name="Member:", value=f"{staff_member.mention} ({staff_member.id})", inline=False).add_field(name="Reasoning:", value=reason, inline=True).add_field(name="Punishment:", value="Termination", inline=True).add_field(name="Issued by:", value=interaction.user.mention, inline=False).set_footer(text=f"Ref No: {inf_id}")
        await log_to_discord_channel(interaction.guild, "staff_infraction", staff_inf_log, content=staff_member.mention)
        try: await staff_member.send(f"You've been terminated from staff in **{interaction.guild.name}**. Reason: {reason}\n*By: {interaction.user.mention}*")
        except: pass
        await interaction.followup.send(f"✅ Termination of {staff_member.mention} logged. Reason: {reason}. Manually remove roles.", ephemeral=True)
    elif view.value is False: await interaction.followup.send("⚠️ Termination logging cancelled.", ephemeral=True)
    else: await interaction.followup.send("⚠️ Termination confirmation timed out.", ephemeral=True)

# --- Staff Infraction Commands ---
@staffinfract_group.command(name="warning", description="Issues an official warning to a staff member.")
@check_command_status_and_permission(permission_level="high_rank_staff")
@app_commands.describe(staff_member="Staff member to warn.", reason="Reason for staff warning.")
async def staffinfract_warning(interaction: discord.Interaction, staff_member: discord.Member, reason: str): 
    if not interaction.guild: return
    try: check_hierarchy(interaction, staff_member)
    except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return
    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"Issue staff warning to {staff_member.mention}? Reason: \"{reason}\".\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()
    if view.value is True:
        inf_id = add_infraction_record(interaction.guild_id, staff_member.id, "staff_warning", reason, interaction.user.id, points=1)
        log_main = Embed(title="Staff Warning Issued (Log)", color=Color.orange(), timestamp=discord.utils.utcnow())
        log_main.set_author(name=f"Manager: {interaction.user}", icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
        log_main.add_field(name="Staff", value=f"{staff_member.mention} ({staff_member.id})", inline=False).add_field(name="Reason", value=reason, inline=False)
        log_main.set_footer(text=f"Infraction ID: {inf_id} | Guild: {interaction.guild.name}")
        await log_to_discord_channel(interaction.guild, "main", log_main)

        staff_inf_log = Embed(title=f"{interaction.guild.name} | Staff Infraction", color=Color.orange(), timestamp=discord.utils.utcnow())
        staff_inf_log.add_field(name="Member:", value=f"{staff_member.mention} ({staff_member.id})", inline=False).add_field(name="Reasoning:", value=reason, inline=True).add_field(name="Punishment:", value="Staff Warning", inline=True).add_field(name="Issued by:", value=interaction.user.mention, inline=False).set_footer(text=f"Ref No: {inf_id}")
        await log_to_discord_channel(interaction.guild, "staff_infraction", staff_inf_log, content=staff_member.mention)
        try: await staff_member.send(f"You received a staff warning in **{interaction.guild.name}**. Reason: {reason}\n*By: {interaction.user.mention}*\n*ID: {inf_id}*")
        except: pass
        await interaction.followup.send(f"✅ Staff warning issued to {staff_member.mention}. Reason: {reason}", ephemeral=True)
    elif view.value is False: await interaction.followup.send("⚠️ Staff warning cancelled.", ephemeral=True)
    else: await interaction.followup.send("⚠️ Staff warning confirmation timed out.", ephemeral=True)

@staffinfract_group.command(name="strike", description="Issues a strike to a staff member.")
@check_command_status_and_permission(permission_level="high_rank_staff")
@app_commands.describe(staff_member="Staff member to issue a strike to.", reason="Reason for staff strike.")
async def staffinfract_strike(interaction: discord.Interaction, staff_member: discord.Member, reason: str): 
    if not interaction.guild: return
    try: check_hierarchy(interaction, staff_member)
    except HierarchyError as he: await interaction.response.send_message(str(he), ephemeral=True); return
    view = ConfirmationView(author_id=interaction.user.id)
    await interaction.response.send_message(f"Issue staff strike to {staff_member.mention}? Reason: \"{reason}\".\n**Confirm?**", view=view, ephemeral=True)
    await view.wait()
    if view.value is True:
        inf_id = add_infraction_record(interaction.guild_id, staff_member.id, "staff_strike", reason, interaction.user.id, points=3)
        log_main = Embed(title="Staff Strike Issued (Log)", color=Color.red(), timestamp=discord.utils.utcnow())
        log_main.set_author(name=f"Manager: {interaction.user}", icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
        log_main.add_field(name="Staff", value=f"{staff_member.mention} ({staff_member.id})", inline=False).add_field(name="Reason", value=reason, inline=False)
        log_main.set_footer(text=f"Infraction ID: {inf_id} | Guild: {interaction.guild.name}")
        await log_to_discord_channel(interaction.guild, "main", log_main)

        staff_inf_log = Embed(title=f"{interaction.guild.name} | Staff Infraction", color=Color.red(), timestamp=discord.utils.utcnow())
        staff_inf_log.add_field(name="Member:", value=f"{staff_member.mention} ({staff_member.id})", inline=False).add_field(name="Reasoning:", value=reason, inline=True).add_field(name="Punishment:", value="Staff Strike", inline=True).add_field(name="Issued by:", value=interaction.user.mention, inline=False).set_footer(text=f"Ref No: {inf_id}")
        await log_to_discord_channel(interaction.guild, "staff_infraction", staff_inf_log, content=staff_member.mention)
        try: await staff_member.send(f"You received a staff strike in **{interaction.guild.name}**. Reason: {reason}\n*By: {interaction.user.mention}*\n*ID: {inf_id}*")
        except: pass
        await interaction.followup.send(f"✅ Staff strike issued to {staff_member.mention}. Reason: {reason}", ephemeral=True)
    elif view.value is False: await interaction.followup.send("⚠️ Staff strike cancelled.", ephemeral=True)
    else: await interaction.followup.send("⚠️ Staff strike confirmation timed out.", ephemeral=True)

# --- View Infractions Command ---
@bot.tree.command(name="viewinfractions", description="Views infractions for a given user.")
@check_command_status_and_permission(permission_level="general_staff")
@app_commands.describe(user="The user whose infractions you want to view.")
async def viewinfractions(interaction: discord.Interaction, user: discord.User): 
    if not interaction.guild_id: return
    user_key = f"{interaction.guild_id}-{user.id}"; user_infractions = infractions_data.get(user_key, [])
    if not user_infractions: await interaction.response.send_message(f"{user.mention} has no recorded infractions.", ephemeral=True); return
    embed = Embed(title=f"Infractions for {user.display_name} ({user.id})", color=Color.light_grey(), timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
    normal_infractions_text = ""; staff_infractions_text = ""
    for infr in sorted(user_infractions, key=lambda x: x['timestamp'], reverse=True):
        mod_user_obj = await bot.fetch_user(infr['moderator_id']) if infr.get('moderator_id') else "Unknown Mod"
        mod_display = str(mod_user_obj) if mod_user_obj else "Unknown Mod"
        ts_dt = datetime.datetime.fromisoformat(infr['timestamp']); formatted_ts = discord.utils.format_dt(ts_dt, style='f')
        entry = (f"**ID:** `{infr['id']}`\n**Type:** {infr['type'].replace('_', ' ').title()}\n**Reason:** {infr['reason']}\n"
                 f"**Moderator:** {mod_display}\n**Date:** {formatted_ts}\n")
        if infr.get('duration'): entry += f"**Duration:** {infr['duration']}\n"
        if infr.get('points'): entry += f"**Points:** {infr['points']}\n"; entry += "---\n" 
        if infr['type'].startswith("staff_"): staff_infractions_text += entry
        else: normal_infractions_text += entry
    if normal_infractions_text:
        if len(normal_infractions_text) > 1020: normal_infractions_text = normal_infractions_text[:1020] + "..."
        embed.add_field(name="📜 User Infractions", value=normal_infractions_text or "None", inline=False)
    if staff_infractions_text:
        if len(staff_infractions_text) > 1020: staff_infractions_text = staff_infractions_text[:1020] + "..."
        embed.add_field(name="🛡️ Staff Infractions", value=staff_infractions_text or "None", inline=False)
    if not normal_infractions_text and not staff_infractions_text: await interaction.response.send_message(f"No infractions found for {user.mention}.", ephemeral=True); return
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- Toggle Command ---
@app_commands.command(name="togglecommand", description="Enables or disables a manageable command for this server.")
@app_commands.checks.has_permissions(administrator=True) 
@app_commands.guild_only()
@app_commands.describe(command_name="The command to toggle.", enable="Set to True to enable, False to disable.")
async def togglecommand_cmd(interaction: discord.Interaction, command_name: str, enable: bool): 
    if not interaction.guild_id: return
    guild_config = get_guild_config(interaction.guild_id)
    if command_name not in ALL_CONFIGURABLE_COMMANDS_FLAT and command_name not in bot.COMMAND_REGISTRY: 
        await interaction.response.send_message(f"⚠️ Command `{command_name}` is not a known manageable command.", ephemeral=True); return
    current_status = guild_config["command_states"].get(command_name, True)
    if current_status == enable:
        await interaction.response.send_message(f"ℹ️ Command `{command_name}` is already {'enabled' if enable else 'disabled'}.", ephemeral=True); return
    guild_config["command_states"][command_name] = enable
    save_to_json(guild_configurations, CONFIG_FILE)
    async def do_sync():
        target_guild = bot.get_guild(interaction.guild_id)
        if target_guild: await sync_guild_commands(target_guild)
    if bot.loop: bot.loop.create_task(do_sync())
    status_text = "enabled" if enable else "disabled"
    await interaction.response.send_message(f"✅ Command `{command_name}` has been {status_text}. Changes may take a moment.", ephemeral=True)
    log_embed = Embed(title="Command Toggled", color=Color.purple(), timestamp=discord.utils.utcnow())
    log_embed.set_author(name=f"Admin: {interaction.user}", icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
    log_embed.add_field(name="Command", value=f"`/{command_name.replace('_',' ')}`", inline=True).add_field(name="New Status", value=status_text.title(), inline=True)
    log_embed.set_footer(text=f"Guild: {interaction.guild.name}")
    await log_to_discord_channel(interaction.guild, "main", log_embed)

@togglecommand_cmd.autocomplete('command_name')
async def togglecommand_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]: # Corrected Choice
    choices = [app_commands.Choice(name=cmd_key.replace("_", " "), value=cmd_key) for cmd_key in ALL_CONFIGURABLE_COMMANDS_FLAT if current.lower() in cmd_key.lower()] # Corrected Choice
    return choices[:25]

# --- Global Error Handler ---
async def global_app_command_error_handler(interaction: discord.Interaction, error: app_commands.AppCommandError): 
    user_readable_error = "An unexpected error occurred. Please try again later."
    ephemeral_response = True
    if isinstance(error, (CommandDisabledInGuild, MissingConfiguredRole, HierarchyError)): user_readable_error = str(error)
    elif isinstance(error, app_commands.CommandOnCooldown): user_readable_error = f"This command is on cooldown. Try again in {error.retry_after:.2f}s."
    elif isinstance(error, app_commands.MissingPermissions): user_readable_error = f"You lack Discord permissions: {', '.join(error.missing_permissions)}"
    elif isinstance(error, app_commands.BotMissingPermissions): user_readable_error = f"I lack Discord permissions: {', '.join(error.missing_permissions)}"
    elif isinstance(error, app_commands.CheckFailure): user_readable_error = "You do not meet the requirements for this command."
    
    cmd_name_for_log = interaction.command.qualified_name if interaction.command else "UnknownCmd"
    print(f"ERROR (Slash Command): User: {interaction.user}, Guild: {interaction.guild_id}, Cmd: {cmd_name_for_log}, Error: {type(error).__name__} - {error}")
    try:
        if interaction.response.is_done(): await interaction.followup.send(user_readable_error, ephemeral=ephemeral_response)
        else: await interaction.response.send_message(user_readable_error, ephemeral=ephemeral_response)
    except Exception as e_resp: print(f"ERROR sending error response: {e_resp}")
bot.tree.on_error = global_app_command_error_handler

# --- Setup Hook ---
@bot.setup_hook
async def initial_setup():
    bot.COMMAND_REGISTRY_READY = asyncio.Event() 
    
    temp_registry = {}
    all_tree_commands = bot.tree.get_commands(type=discord.AppCommandType.chat_input)

    def process_command(cmd_obj, group_name=None):
        key = f"{group_name}_{cmd_obj.name}" if group_name else cmd_obj.name
        is_manageable = key in ALL_CONFIGURABLE_COMMANDS_FLAT
        
        if group_name == "arvo_config" and cmd_obj.name == "setup": 
            is_manageable = False 

        temp_registry[key] = {
            "app_command_obj": cmd_obj,
            "manageable": is_manageable,
            "group_name": group_name,
            "base_name": cmd_obj.name
        }

    for cmd in all_tree_commands:
        if isinstance(cmd, app_commands.Group):
            for sub_cmd in cmd.commands: 
                if isinstance(sub_cmd, app_commands.Command):
                     process_command(sub_cmd, group_name=cmd.name)
        elif isinstance(cmd, app_commands.Command):
            process_command(cmd)
            
    bot.COMMAND_REGISTRY = temp_registry
    print(f"INFO ({ARVO_BOT_NAME}): COMMAND_REGISTRY populated in setup_hook with {len(bot.COMMAND_REGISTRY)} entries.")
    bot.COMMAND_REGISTRY_READY.set() 


# --- Running the Bot and Server ---
async def main_async():
    async with bot: 
        # initial_setup is called by bot.start() via setup_hook
        start_keep_alive_server() 
        print(f"Flask web server thread started for {ARVO_BOT_NAME}.")
        print(f"Attempting to connect {ARVO_BOT_NAME} to Discord...")
        await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    if not APP_BASE_URL_CONFIG: print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): APP_BASE_URL or RENDER_EXTERNAL_URL env var not set.")
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET: print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): OAuth env vars not set.")
    
    load_all_data() 
    
    try: asyncio.run(main_async())
    except KeyboardInterrupt: print(f"{ARVO_BOT_NAME} shutting down manually...")
    except Exception as e: print(f"CRITICAL BOT RUN ERROR for {ARVO_BOT_NAME}: {e}")

