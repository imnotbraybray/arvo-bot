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
AUTOMESSAGES_FILE = "automessages.json" # NEW: For automated server messages

# --- Default Guild Configuration Structure ---
DEFAULT_GUILD_CONFIG = {
    "erlc_config": {
        "session_logs_channel_id": None,
        "session_announcements_channel_id": None,
        "session_host_role_id": None,
        "server_management_role_id": None, # NEW: Role for using /server commands
        "api_key": None 
    }
}

# --- Data Storage ---
guild_configurations: Dict[int, Dict[str, Any]] = {} 
active_sessions_data: Dict[int, Dict[str, Any]] = {} 
roblox_users_data: Dict[str, Dict[str, Any]] = {} 
automessages_data: Dict[str, List[Dict[str, Any]]] = {} # NEW: guild_id -> list of message configs

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
server_group = app_commands.Group(name="server", description="Interact with the ERLC game server.", guild_only=True) # NEW
automessage_group = app_commands.Group(name="automessage", description="Manage automated game server messages.", guild_only=True) # NEW

# --- Custom Bot Class ---
class ArvoBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    async def setup_hook(self): 
        self.tree.add_command(erlc_config_group)
        self.tree.add_command(session_group)
        self.tree.add_command(account_group)
        self.tree.add_command(server_group) # NEW
        self.tree.add_command(automessage_group) # NEW
        automated_message_sender.start() # Start the background task
        
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
    """Sends a request to the configured game server API."""
    guild_config = get_guild_config(guild_id).get("erlc_config", {})
    api_key = guild_config.get("api_key")
    if not api_key:
        return {"success": False, "message": "API key is not configured for this server."}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    url = f"{GAME_SERVER_API_BASE_URL.rstrip('/')}/{endpoint}"

    try:
        # Run the blocking 'requests' call in a separate thread
        response = await asyncio.to_thread(
            requests.post, url, headers=headers, json=payload, timeout=10
        )
        response.raise_for_status()
        return {"success": True, "data": response.json()}
    except requests.Timeout:
        return {"success": False, "message": "Request to game server timed out."}
    except requests.HTTPError as e:
        return {"success": False, "message": f"Game server returned an error: {e.response.status_code} {e.response.reason}"}
    except requests.RequestException as e:
        return {"success": False, "message": f"Could not connect to the game server: {e}"}

# --- Permission Checks ---
def is_session_host(): # ... (code unchanged)
    async def predicate(interaction: Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, Member): return False
        if interaction.user.guild_permissions.administrator: return True
        guild_config = get_guild_config(interaction.guild_id).get("erlc_config", {})
        host_role_id = guild_config.get("session_host_role_id")
        if not host_role_id: raise app_commands.CheckFailure("The Session Host role has not been configured.")
        if any(role.id == host_role_id for role in interaction.user.roles): return True
        host_role = interaction.guild.get_role(host_role_id)
        raise app_commands.CheckFailure(f"You need the `{host_role.name if host_role else 'Session Host'}` role.")
    return app_commands.check(predicate)

def is_server_manager():
    """Custom check for the new Server Management role."""
    async def predicate(interaction: Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, Member): return False
        if interaction.user.guild_permissions.administrator: return True
        guild_config = get_guild_config(interaction.guild_id).get("erlc_config", {})
        manager_role_id = guild_config.get("server_management_role_id")
        if not manager_role_id: raise app_commands.CheckFailure("The Server Management role has not been configured.")
        if any(role.id == manager_role_id for role in interaction.user.roles): return True
        manager_role = interaction.guild.get_role(manager_role_id)
        raise app_commands.CheckFailure(f"You need the `{manager_role.name if manager_role else 'Server Manager'}` role.")
    return app_commands.check(predicate)

# --- ERLC Config Group Commands ---
config_set_group = app_commands.Group(name="set", description="Set a configuration value.", parent=erlc_config_group)
@config_set_group.command(name="roles", description="Set the roles for permissions.")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    session_host_role="Role required to start/end ERLC sessions.",
    server_manager_role="Role for broadcasting messages and executing commands on the server."
)
async def set_roles(interaction: discord.Interaction, session_host_role: discord.Role, server_manager_role: discord.Role):
    if not interaction.guild_id: return
    guild_config = get_guild_config(interaction.guild_id)
    guild_config["erlc_config"]["session_host_role_id"] = session_host_role.id
    guild_config["erlc_config"]["server_management_role_id"] = server_manager_role.id # NEW
    save_to_json(guild_configurations, CONFIG_FILE)
    embed = Embed(title="✅ ERLC Roles Configured", color=Color.green())
    embed.add_field(name="Session Host Role", value=session_host_role.mention, inline=False)
    embed.add_field(name="Server Manager Role", value=server_manager_role.mention, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)
# ... (rest of config commands unchanged)

# --- Server Management Commands (NEW) ---
@server_group.command(name="broadcast", description="Broadcast a message to the ERLC game server.")
@is_server_manager()
@app_commands.describe(message="The message to send.")
async def server_broadcast(interaction: Interaction, message: str):
    await interaction.response.defer(ephemeral=True)
    payload = {"type": "broadcast", "message": message}
    result = await send_to_gameserver_api(interaction.guild_id, "message", payload)
    if result["success"]:
        await interaction.followup.send("✅ Message broadcasted successfully to the game server.", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ Failed to broadcast message: `{result['message']}`", ephemeral=True)

@server_group.command(name="execute", description="Execute a command on the ERLC game server.")
@is_server_manager()
@app_commands.describe(command_string="The full command to execute (e.g., kick PlayerName 'reason').")
async def server_execute(interaction: Interaction, command_string: str):
    await interaction.response.defer(ephemeral=True)
    payload = {"type": "command", "command": command_string}
    result = await send_to_gameserver_api(interaction.guild_id, "execute", payload)
    if result["success"]:
        response_data = result.get("data", "No response data.")
        await interaction.followup.send(f"✅ Command executed successfully.\n**Response:** `{response_data}`", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ Failed to execute command: `{result['message']}`", ephemeral=True)

# --- Automated Message Commands (NEW) ---
@automessage_group.command(name="add", description="Add a new automated message to be sent to the game server.")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(interval="How often to send the message, in minutes.", message="The message content.")
async def automessage_add(interaction: Interaction, interval: app_commands.Range[int, 1, 1440], message: str):
    guild_id_str = str(interaction.guild_id)
    if guild_id_str not in automessages_data:
        automessages_data[guild_id_str] = []
    
    message_id = str(uuid.uuid4())[:8]
    new_message = {
        "id": message_id,
        "interval_minutes": interval,
        "message": message,
        "last_sent_timestamp": 0 # Set to 0 to send on the next cycle
    }
    automessages_data[guild_id_str].append(new_message)
    save_to_json(automessages_data, AUTOMESSAGES_FILE)
    await interaction.response.send_message(f"✅ Automated message added with ID `{message_id}`. It will be sent every **{interval}** minutes.", ephemeral=True)

@automessage_group.command(name="list", description="List all currently configured automated messages.")
@app_commands.checks.has_permissions(administrator=True)
async def automessage_list(interaction: Interaction):
    guild_id_str = str(interaction.guild_id)
    messages = automessages_data.get(guild_id_str, [])
    if not messages:
        await interaction.response.send_message("There are no automated messages configured.", ephemeral=True)
        return
    
    embed = Embed(title="Automated Messages", color=Color.blue())
    description = ""
    for msg in messages:
        description += f"**ID:** `{msg['id']}` | **Interval:** {msg['interval_minutes']} mins\n"
        description += f"**Message:** \"{msg['message']}\"\n---\n"
    embed.description = description
    await interaction.response.send_message(embed=embed, ephemeral=True)

@automessage_group.command(name="remove", description="Remove an automated message.")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(message_id="The ID of the message to remove (from /automessage list).")
async def automessage_remove(interaction: Interaction, message_id: str):
    guild_id_str = str(interaction.guild_id)
    messages = automessages_data.get(guild_id_str, [])
    
    message_to_remove = next((msg for msg in messages if msg['id'] == message_id), None)
    
    if not message_to_remove:
        await interaction.response.send_message(f"❌ No automated message found with ID `{message_id}`.", ephemeral=True)
        return
        
    automessages_data[guild_id_str].remove(message_to_remove)
    save_to_json(automessages_data, AUTOMESSAGES_FILE)
    await interaction.response.send_message(f"✅ Successfully removed automated message with ID `{message_id}`.", ephemeral=True)


# --- Automated Message Background Task ---
@tasks.loop(minutes=1)
async def automated_message_sender():
    current_timestamp = int(time.time())
    # Create a copy to avoid issues if the dict changes during iteration
    for guild_id_str, messages in list(automessages_data.items()):
        guild_id = int(guild_id_str)
        for msg_config in messages:
            interval_seconds = msg_config["interval_minutes"] * 60
            last_sent = msg_config.get("last_sent_timestamp", 0)
            
            if (current_timestamp - last_sent) >= interval_seconds:
                print(f"Sending automessage for guild {guild_id}: {msg_config['message']}")
                payload = {"type": "broadcast", "message": msg_config["message"]}
                await send_to_gameserver_api(guild_id, "message", payload)
                # Update the timestamp
                msg_config["last_sent_timestamp"] = current_timestamp
        
    save_to_json(automessages_data, AUTOMESSAGES_FILE) # Save updated timestamps

@automated_message_sender.before_loop
async def before_automessage_sender():
    await bot.wait_until_ready() # Wait for the bot to be fully operational


# --- Main Execution ---
async def main_async():
    async with bot: 
        start_keep_alive_server()
        print(f"Flask web server thread started.")
        await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("CRITICAL: DISCORD_TOKEN environment variable is not set.")
    else:
        load_all_data() 
        try: asyncio.run(main_async())
        except KeyboardInterrupt: print(f"{ARVO_BOT_NAME} shutting down manually...")
        except Exception as e: print(f"CRITICAL BOT RUN ERROR: {e}")
