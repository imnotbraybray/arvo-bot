# main.py (for Arvo ERLC Bot)
import discord
from discord.ext import commands, tasks
from discord import app_commands, ChannelType, Role, SelectOption, Embed, Color, Member, User, Interaction, CategoryChannel, TextChannel, ButtonStyle, File, PermissionOverwrite, SelectMenu
from discord.ui import View, Button, Modal, TextInput, UserSelect
import os
from flask import Flask, render_template, url_for, session, redirect, request, flash, abort 
from threading import Thread
import datetime
import time # Using time module for Unix timestamps
import uuid 
import requests
import json 
import asyncio
from typing import Optional, List, Dict, Any, Union

# --- Arvo Bot Information ---
ARVO_BOT_NAME = "Arvo ERLC"
ARVO_BOT_DESCRIPTION = "Arvo - A comprehensive ERLC Management Bot for Discord."

# --- Configuration (Fetched from Environment Variables) ---
BOT_TOKEN = os.getenv("DISCORD_TOKEN") 
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL') 
DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID') 
DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')
ARVO_BOT_CLIENT_ID_FOR_INVITE = os.getenv('ARVO_BOT_CLIENT_ID_FOR_INVITE', DISCORD_CLIENT_ID) 

# --- IMPORTANT API CONFIGURATION ---
# You must change this URL to the actual endpoint your Roblox game server listens to.
GAME_SERVER_API_BASE_URL = "https://your-roblox-game-api.example.com"


DISCORD_REDIRECT_URI = None
APP_BASE_URL_CONFIG = os.getenv('APP_BASE_URL', RENDER_EXTERNAL_URL) 
if APP_BASE_URL_CONFIG:
    DISCORD_REDIRECT_URI = f"{APP_BASE_URL_CONFIG.rstrip('/')}/callback"
else:
    print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): APP_BASE_URL or RENDER_EXTERNAL_URL not set. OAuth2 will fail.")

API_ENDPOINT = 'https://discord.com/api/v10' 

if BOT_TOKEN is None: print(f"CRITICAL ({ARVO_BOT_NAME}): DISCORD_TOKEN not set."); exit()
if FLASK_SECRET_KEY is None: print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): FLASK_SECRET_KEY not set."); FLASK_SECRET_KEY = "temporary_insecure_key"


# --- Data Storage Files ---
CONFIG_FILE = "arvo_guild_configs.json"
ERLC_ACTIVE_SESSIONS_FILE = "erlc_active_sessions.json" 
ROBLOX_USERS_FILE = "roblox_users.json"
AUTOMESSAGES_FILE = "automessages.json" 

# --- Default Guild Configuration Structure ---
DEFAULT_GUILD_CONFIG = {
    "erlc_config": {
        "session_logs_channel_id": None,
        "session_announcements_channel_id": None,
        "session_host_role_id": None,
        "server_management_role_id": None,
        "api_key": None 
    }
}

# --- Data Storage ---
guild_configurations: Dict[int, Dict[str, Any]] = {} 
active_sessions_data: Dict[int, Dict[str, Any]] = {} 
roblox_users_data: Dict[str, Dict[str, Any]] = {} 
automessages_data: Dict[str, List[Dict[str, Any]]] = {} 

def get_guild_config(guild_id: int) -> Dict[str, Any]:
    if guild_id not in guild_configurations:
        guild_configurations[guild_id] = json.loads(json.dumps(DEFAULT_GUILD_CONFIG))
    if "erlc_config" not in guild_configurations[guild_id]:
         guild_configurations[guild_id]["erlc_config"] = json.loads(json.dumps(DEFAULT_GUILD_CONFIG["erlc_config"]))
    return guild_configurations[guild_id]


def load_from_json(filename: str, default_data: Any = None) -> Any:
    if default_data is None: default_data = {}
    try:
        with open(filename, 'r') as f:
            content = f.read()
            if not content: return default_data 
            return json.loads(content)
    except (FileNotFoundError): pass
    except json.JSONDecodeError: print(f"ERROR: Invalid JSON in '{filename}'.")
    return default_data

def save_to_json(data: Any, filename: str):
    try:
        data_to_save = {str(k): v for k, v in data.items()}
        with open(filename, 'w') as f:
            json.dump(data_to_save, f, indent=4)
    except Exception as e: print(f"ERROR: Could not save data to '{filename}': {e}")


def load_all_data():
    global guild_configurations, active_sessions_data, roblox_users_data, automessages_data
    raw_guild_configs = load_from_json(CONFIG_FILE, {})
    guild_configurations = {int(k): v for k, v in raw_guild_configs.items()} 
    
    raw_active_sessions = load_from_json(ERLC_ACTIVE_SESSIONS_FILE, {})
    active_sessions_data = {int(k): v for k, v in raw_active_sessions.items()}
    
    roblox_users_data = load_from_json(ROBLOX_USERS_FILE, {})
    automessages_data = load_from_json(AUTOMESSAGES_FILE, {})
    print(f"INFO ({ARVO_BOT_NAME}): All data loaded from JSON files.")

# --- Flask App ---
app = Flask(__name__) 
app.secret_key = FLASK_SECRET_KEY
@app.route('/')
def index(): return f"{ARVO_BOT_NAME} is running!"
def run_flask():
  port = int(os.environ.get('PORT', 8080)) 
  app.run(host='0.0.0.0', port=port) 
def start_keep_alive_server(): 
    server_thread = Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()

# --- ERLC Command Groups ---
erlc_config_group = app_commands.Group(name="erlc-config", description="Configure Arvo ERLC bot for this server.", guild_only=True)
session_group = app_commands.Group(name="session", description="ERLC session management commands.", guild_only=True)
account_group = app_commands.Group(name="account", description="Link your Discord to your Roblox account.", guild_only=True)
server_group = app_commands.Group(name="server", description="Interact with the ERLC game server.", guild_only=True)
automessage_group = app_commands.Group(name="automessage", description="Manage automated game server messages.", guild_only=True)

# --- Custom Bot Class ---
class ArvoBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    async def setup_hook(self): 
        self.tree.add_command(erlc_config_group)
        self.tree.add_command(session_group)
        self.tree.add_command(account_group)
        self.tree.add_command(server_group)
        self.tree.add_command(automessage_group)
        automated_message_sender.start()
        
# --- Discord Bot Instance ---
intents = discord.Intents.default()
intents.members = True 
intents.message_content = True 
bot = ArvoBot(command_prefix=commands.when_mentioned_or("!arvo-erlc-unused!"), intents=intents)

# --- Bot Event Listeners ---
@bot.event
async def on_ready():
    print(f'{ARVO_BOT_NAME} has logged in as {bot.user.name} (ID: {bot.user.id})')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands globally.")
    except Exception as e: print(f"Error syncing commands: {e}")
    await bot.change_presence(activity=discord.Game(name=f"Managing ERLC Servers"))

# --- Game Server API Communication ---
async def send_to_gameserver_api(guild_id: int, endpoint: str, payload: Dict) -> Dict:
    guild_config = get_guild_config(guild_id).get("erlc_config", {})
    api_key = guild_config.get("api_key")
    if not api_key: return {"success": False, "message": "API key is not configured."}

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = f"{GAME_SERVER_API_BASE_URL.rstrip('/')}/{endpoint}"

    try:
        print(f"Sending API request to {url}")
        response = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        return {"success": True, "data": response.json()}
    except requests.Timeout: return {"success": False, "message": "Request to game server timed out."}
    except requests.HTTPError as e: return {"success": False, "message": f"Game server error: {e.response.status_code}"}
    except requests.RequestException as e: return {"success": False, "message": f"Could not connect to game server."}

# --- Permission Checks ---
def is_session_host():
    async def predicate(interaction: Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, Member): return False
        if interaction.user.guild_permissions.administrator: return True
        guild_config = get_guild_config(interaction.guild_id).get("erlc_config", {})
        host_role_id = guild_config.get("session_host_role_id")
        if not host_role_id: raise app_commands.CheckFailure("Session Host role not configured.")
        if any(role.id == host_role_id for role in interaction.user.roles): return True
        host_role = interaction.guild.get_role(host_role_id)
        raise app_commands.CheckFailure(f"You need the `{host_role.name if host_role else 'Session Host'}` role.")
    return app_commands.check(predicate)

def is_server_manager():
    async def predicate(interaction: Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, Member): return False
        if interaction.user.guild_permissions.administrator: return True
        guild_config = get_guild_config(interaction.guild_id).get("erlc_config", {})
        manager_role_id = guild_config.get("server_management_role_id")
        if not manager_role_id: raise app_commands.CheckFailure("Server Management role not configured.")
        if any(role.id == manager_role_id for role in interaction.user.roles): return True
        manager_role = interaction.guild.get_role(manager_role_id)
        raise app_commands.CheckFailure(f"You need the `{manager_role.name if manager_role else 'Server Manager'}` role.")
    return app_commands.check(predicate)

# --- ERLC Config Group Commands ---
config_set_group = app_commands.Group(name="set", description="Set a configuration value.", parent=erlc_config_group)
# ... (set_channels and other config commands are here, unchanged)
@config_set_group.command(name="roles", description="Set the roles for permissions.")
@app_commands.checks.has_permissions(administrator=True)
async def set_roles(interaction: discord.Interaction, session_host_role: discord.Role, server_manager_role: discord.Role):
    if not interaction.guild_id: return
    guild_config = get_guild_config(interaction.guild_id)
    guild_config["erlc_config"]["session_host_role_id"] = session_host_role.id
    guild_config["erlc_config"]["server_management_role_id"] = server_manager_role.id
    save_to_json(guild_configurations, CONFIG_FILE)
    embed = Embed(title="✅ ERLC Roles Configured", color=Color.green())
    embed.add_field(name="Session Host Role", value=session_host_role.mention, inline=False)
    embed.add_field(name="Server Manager Role", value=server_manager_role.mention, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

class ApiKeyModal(Modal, title="Set Guild API Key"):
    api_key_input = TextInput(label="API Key", placeholder="Paste your secret API key here.", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild_id: return
        guild_config = get_guild_config(interaction.guild_id)
        guild_config["erlc_config"]["api_key"] = self.api_key_input.value
        save_to_json(guild_configurations, CONFIG_FILE)
        await interaction.response.send_message("✅ API key securely saved.", ephemeral=True)

@config_set_group.command(name="api-key", description="Securely set the API key for this guild.")
@app_commands.checks.has_permissions(administrator=True)
async def set_api_key(interaction: discord.Interaction):
    await interaction.response.send_modal(ApiKeyModal())

# --- Account Linking Commands ---
async def get_roblox_user_info(roblox_username: str) -> Optional[Dict[str, Any]]:
    try:
        response = requests.post("https://users.roblox.com/v1/usernames/users", json={"usernames": [roblox_username]})
        response.raise_for_status()
        data = response.json().get('data')
        if data: return {"id": data[0]['id'], "name": data[0]['name']}
    except requests.RequestException: pass
    return None

@account_group.command(name="link", description="Link your Discord account to a Roblox account.")
@app_commands.describe(roblox_username="Your exact Roblox username.")
async def link_account(interaction: Interaction, roblox_username: str):
    await interaction.response.defer(ephemeral=True)
    discord_id = str(interaction.user.id)
    if discord_id in roblox_users_data:
        await interaction.followup.send("❌ Your account is already linked. Use `/account unlink` first.", ephemeral=True)
        return
    roblox_info = await get_roblox_user_info(roblox_username)
    if not roblox_info:
        await interaction.followup.send(f"❌ Could not find Roblox user `{roblox_username}`.", ephemeral=True)
        return
    roblox_id, validated_username = roblox_info['id'], roblox_info['name']
    for D_id, R_data in roblox_users_data.items():
        if R_data.get('roblox_id') == roblox_id:
            other_user = bot.get_user(int(D_id))
            await interaction.followup.send(f"❌ Roblox account is already linked by {other_user.mention if other_user else 'another user'}.", ephemeral=True)
            return
    roblox_users_data[discord_id] = {"roblox_id": roblox_id, "roblox_username": validated_username}
    save_to_json(roblox_users_data, ROBLOX_USERS_FILE)
    await interaction.followup.send(f"✅ Successfully linked to Roblox account: **{validated_username}**.", ephemeral=True)

@account_group.command(name="profile", description="View the linked Roblox profile for a user.")
@app_commands.describe(user="The user to view (defaults to you).")
async def view_profile(interaction: Interaction, user: Optional[Member] = None):
    target_user = user or interaction.user
    discord_id = str(target_user.id)
    if discord_id not in roblox_users_data:
        msg = "You do not have a Roblox account linked." if target_user == interaction.user else f"{target_user.mention} does not have a Roblox account linked."
        await interaction.response.send_message(f"❌ {msg}", ephemeral=True)
        return
    user_data = roblox_users_data[discord_id]
    embed = Embed(title=f"Linked Profile for {target_user.display_name}", color=target_user.color)
    embed.set_thumbnail(url=target_user.display_avatar.url)
    embed.add_field(name="Roblox Account", value=f"[{user_data['roblox_username']}](https://www.roblox.com/users/{user_data['roblox_id']}/profile)")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- Server Management Commands ---
@server_group.command(name="broadcast", description="Broadcast a message to the ERLC game server.")
@is_server_manager()
@app_commands.describe(message="The message to send.")
async def server_broadcast(interaction: Interaction, message: str):
    await interaction.response.defer(ephemeral=True)
    result = await send_to_gameserver_api(interaction.guild_id, "message", {"type": "broadcast", "message": message})
    if result["success"]:
        await interaction.followup.send("✅ Message broadcasted.", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ Failed: `{result['message']}`", ephemeral=True)

@server_group.command(name="execute", description="Execute a command on the ERLC game server.")
@is_server_manager()
@app_commands.describe(command_string="The full command to execute (e.g., kick PlayerName 'reason').")
async def server_execute(interaction: Interaction, command_string: str):
    await interaction.response.defer(ephemeral=True)
    result = await send_to_gameserver_api(interaction.guild_id, "execute", {"type": "command", "command": command_string})
    if result["success"]:
        await interaction.followup.send(f"✅ Command executed. Response: `{result.get('data', 'None')}`", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ Failed: `{result['message']}`", ephemeral=True)

# --- Automated Message Commands ---
@automessage_group.command(name="add", description="Add a new automated message.")
@app_commands.checks.has_permissions(administrator=True)
async def automessage_add(interaction: Interaction, interval: app_commands.Range[int, 1, 1440], message: str):
    guild_id_str = str(interaction.guild_id)
    if guild_id_str not in automessages_data: automessages_data[guild_id_str] = []
    message_id = str(uuid.uuid4())[:8]
    automessages_data[guild_id_str].append({"id": message_id, "interval_minutes": interval, "message": message, "last_sent_timestamp": 0})
    save_to_json(automessages_data, AUTOMESSAGES_FILE)
    await interaction.response.send_message(f"✅ Automessage added with ID `{message_id}`.", ephemeral=True)

@automessage_group.command(name="list", description="List all configured automated messages.")
@app_commands.checks.has_permissions(administrator=True)
async def automessage_list(interaction: Interaction):
    messages = automessages_data.get(str(interaction.guild_id), [])
    if not messages:
        await interaction.response.send_message("No automessages configured.", ephemeral=True)
        return
    description = "\n".join([f"**ID:** `{m['id']}` | **Interval:** {m['interval_minutes']}m | **Message:** \"{m['message']}\"" for m in messages])
    embed = Embed(title="Automated Messages", description=description, color=Color.blue())
    await interaction.response.send_message(embed=embed, ephemeral=True)

@automessage_group.command(name="remove", description="Remove an automated message.")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(message_id="The ID of the message to remove.")
async def automessage_remove(interaction: Interaction, message_id: str):
    guild_id_str = str(interaction.guild_id)
    messages = automessages_data.get(guild_id_str, [])
    original_len = len(messages)
    automessages_data[guild_id_str] = [m for m in messages if m['id'] != message_id]
    if len(automessages_data[guild_id_str]) < original_len:
        save_to_json(automessages_data, AUTOMESSAGES_FILE)
        await interaction.response.send_message(f"✅ Removed automessage with ID `{message_id}`.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ No automessage found with ID `{message_id}`.", ephemeral=True)

# --- Automated Message Background Task ---
@tasks.loop(minutes=1)
async def automated_message_sender():
    current_timestamp = int(time.time())
    for guild_id_str, messages in list(automessages_data.items()):
        for msg_config in messages:
            if (current_timestamp - msg_config.get("last_sent_timestamp", 0)) >= (msg_config["interval_minutes"] * 60):
                await send_to_gameserver_api(int(guild_id_str), "message", {"type": "broadcast", "message": msg_config["message"]})
                msg_config["last_sent_timestamp"] = current_timestamp
    save_to_json(automessages_data, AUTOMESSAGES_FILE)

@automated_message_sender.before_loop
async def before_automessage_sender():
    await bot.wait_until_ready()

# --- Main Execution ---
async def main_async():
    async with bot: 
        start_keep_alive_server()
        await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    if not BOT_TOKEN: print("CRITICAL: DISCORD_TOKEN not set.")
    else:
        load_all_data() 
        try: asyncio.run(main_async())
        except KeyboardInterrupt: print(f"{ARVO_BOT_NAME} shutting down...")
        except Exception as e: print(f"CRITICAL BOT RUN ERROR: {e}")
