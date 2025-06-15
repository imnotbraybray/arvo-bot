# main.py (for Arvo ERLC Bot)
import discord
from discord.ext import commands
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
ROBLOX_USERS_FILE = "roblox_users.json" # NEW: For account linking

# --- Default Guild Configuration Structure ---
DEFAULT_GUILD_CONFIG = {
    "command_states": {}, # Retaining for potential future use
    "erlc_config": {
        "session_logs_channel_id": None,
        "session_announcements_channel_id": None,
        "session_host_role_id": None,
        "loa_channel_id": None, # Placeholder for future LOA system
        "api_key": None # For external API integrations
    }
}

# --- Data Storage ---
guild_configurations: Dict[int, Dict[str, Any]] = {} 
active_sessions_data: Dict[int, Dict[str, Any]] = {} 
roblox_users_data: Dict[str, Dict[str, Any]] = {} # NEW: discord_id -> {roblox_id, roblox_username}

def get_guild_config(guild_id: int) -> Dict[str, Any]:
    """Gets the config for a guild, creating a default if one doesn't exist."""
    if guild_id not in guild_configurations:
        print(f"INFO: No config found for guild {guild_id}. Creating default.")
        guild_configurations[guild_id] = json.loads(json.dumps(DEFAULT_GUILD_CONFIG)) # Deep copy
        save_to_json(guild_configurations, CONFIG_FILE)
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
    except (FileNotFoundError): print(f"INFO: '{filename}' not found. Will create if needed or use default data.")
    except json.JSONDecodeError: print(f"ERROR: Invalid JSON in '{filename}'. Using default/empty data.")
    return default_data

def save_to_json(data: Any, filename: str):
    try:
        data_to_save = {str(k): v for k, v in data.items()}
        with open(filename, 'w') as f:
            json.dump(data_to_save, f, indent=4)
    except Exception as e: print(f"ERROR: Could not save data to '{filename}': {e}")


def load_all_data():
    global guild_configurations, active_sessions_data, roblox_users_data
    raw_guild_configs = load_from_json(CONFIG_FILE, {})
    guild_configurations = {int(k): v for k, v in raw_guild_configs.items()} 
    
    raw_active_sessions = load_from_json(ERLC_ACTIVE_SESSIONS_FILE, {})
    active_sessions_data = {int(k): v for k, v in raw_active_sessions.items()}
    
    roblox_users_data = load_from_json(ROBLOX_USERS_FILE, {}) # NEW
    print(f"INFO ({ARVO_BOT_NAME}): All data loaded from JSON files.")

# --- Flask App ---
app = Flask(__name__) 
app.secret_key = FLASK_SECRET_KEY

@app.route('/')
def index(): 
    return f"{ARVO_BOT_NAME} is running!"

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
account_group = app_commands.Group(name="account", description="Link your Discord to your Roblox account.", guild_only=True) # NEW

# --- Custom Bot Class ---
class ArvoBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def setup_hook(self): 
        self.tree.add_command(erlc_config_group)
        self.tree.add_command(session_group)
        self.tree.add_command(account_group) # NEW
        
# --- Discord Bot Instance ---
intents = discord.Intents.default()
intents.members = True 
intents.message_content = True 
bot = ArvoBot(command_prefix=commands.when_mentioned_or("!arvo-erlc-unused!"), intents=intents)

# --- Bot Event Listeners ---
@bot.event
async def on_ready():
    print(f'{ARVO_BOT_NAME} has logged in as {bot.user.name} (ID: {bot.user.id})')
    print(f'Discord.py Version: {discord.__version__}')
    
    try:
        print("Attempting to sync commands globally...")
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands globally.")
    except Exception as e:
        print(f"An error occurred during global command sync: {e}")

    print(f'{ARVO_BOT_NAME} is ready and online!')
    await bot.change_presence(activity=discord.Game(name=f"Managing ERLC Servers"))

@bot.event
async def on_guild_join(guild: discord.Guild):
    print(f"INFO: Joined new guild: {guild.name} (ID: {guild.id})")
    get_guild_config(guild.id)
    try:
        print(f"Syncing commands for new guild: {guild.name} ({guild.id})")
        await bot.tree.sync(guild=guild)
        print(f"Commands synced successfully for new guild.")
    except Exception as e:
        print(f"ERROR: Failed to sync commands for new guild {guild.name} ({guild.id}): {e}")

# --- Modals for Configuration ---
class ApiKeyModal(Modal, title="Set Guild API Key"):
    api_key_input = TextInput(label="API Key", placeholder="Paste your secret API key here.", style=discord.TextStyle.short, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild_id: return
        api_key = self.api_key_input.value
        guild_config = get_guild_config(interaction.guild_id)
        guild_config["erlc_config"]["api_key"] = api_key
        save_to_json(guild_configurations, CONFIG_FILE)
        await interaction.response.send_message("✅ Your API key has been securely saved. It will not be shown again.", ephemeral=True)

# --- Permission Checks ---
def is_session_host():
    async def predicate(interaction: Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, Member): return False
        if interaction.user.guild_permissions.administrator: return True
        guild_config = get_guild_config(interaction.guild_id).get("erlc_config", {})
        host_role_id = guild_config.get("session_host_role_id")
        if not host_role_id: raise app_commands.CheckFailure("The Session Host role has not been configured.")
        if any(role.id == host_role_id for role in interaction.user.roles): return True
        host_role = interaction.guild.get_role(host_role_id)
        raise app_commands.CheckFailure(f"You need the `{host_role.name if host_role else 'Session Host'}` role to use this command.")
    return app_commands.check(predicate)

# --- ERLC Config Group Commands ---
config_set_group = app_commands.Group(name="set", description="Set a configuration value.", parent=erlc_config_group)

@config_set_group.command(name="channels", description="Set the channels for announcements and logs.")
@app_commands.checks.has_permissions(administrator=True)
async def set_channels(interaction: discord.Interaction, announcements_channel: discord.TextChannel, logs_channel: discord.TextChannel):
    if not interaction.guild_id: return
    guild_config = get_guild_config(interaction.guild_id)
    guild_config["erlc_config"]["session_announcements_channel_id"] = announcements_channel.id
    guild_config["erlc_config"]["session_logs_channel_id"] = logs_channel.id
    save_to_json(guild_configurations, CONFIG_FILE)
    embed = Embed(title="✅ ERLC Channels Configured", color=Color.green())
    embed.add_field(name="Announcements Channel", value=announcements_channel.mention, inline=False)
    embed.add_field(name="Logs Channel", value=logs_channel.mention, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@config_set_group.command(name="roles", description="Set the roles for permissions.")
@app_commands.checks.has_permissions(administrator=True)
async def set_roles(interaction: discord.Interaction, session_host_role: discord.Role):
    if not interaction.guild_id: return
    guild_config = get_guild_config(interaction.guild_id)
    guild_config["erlc_config"]["session_host_role_id"] = session_host_role.id
    save_to_json(guild_configurations, CONFIG_FILE)
    embed = Embed(title="✅ ERLC Roles Configured", color=Color.green())
    embed.add_field(name="Session Host Role", value=session_host_role.mention, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@config_set_group.command(name="api-key", description="Securely set the API key for this guild.")
@app_commands.checks.has_permissions(administrator=True)
async def set_api_key(interaction: discord.Interaction):
    await interaction.response.send_modal(ApiKeyModal())

@erlc_config_group.command(name="view", description="View the current ERLC configuration.")
@app_commands.checks.has_permissions(administrator=True)
async def view_config(interaction: discord.Interaction):
    if not interaction.guild or not interaction.guild_id: return
    guild_config = get_guild_config(interaction.guild_id).get("erlc_config", {})
    ann_ch = interaction.guild.get_channel(guild_config.get("session_announcements_channel_id"))
    log_ch = interaction.guild.get_channel(guild_config.get("session_logs_channel_id"))
    host_role = interaction.guild.get_role(guild_config.get("session_host_role_id"))
    api_key_status = "Set" if guild_config.get("api_key") else "Not Set"
    embed = Embed(title=f"ERLC Configuration for {interaction.guild.name}", color=Color.blue())
    embed.add_field(name="📢 Announcements Channel", value=getattr(ann_ch, 'mention', "Not Set"), inline=False)
    embed.add_field(name="📋 Logs Channel", value=getattr(log_ch, 'mention', "Not Set"), inline=False)
    embed.add_field(name="👑 Session Host Role", value=getattr(host_role, 'mention', "Not Set"), inline=False)
    embed.add_field(name="🔑 API Key Status", value=f"`{api_key_status}`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- Account Linking Commands ---
async def get_roblox_user_info(roblox_username: str) -> Optional[Dict[str, Any]]:
    """Fetches user ID and validated username from Roblox API."""
    try:
        response = requests.post("https://users.roblox.com/v1/usernames/users", json={"usernames": [roblox_username]})
        response.raise_for_status()
        data = response.json().get('data')
        if data and len(data) > 0:
            return {"id": data[0]['id'], "name": data[0]['name']}
    except requests.RequestException as e:
        print(f"Roblox API error: {e}")
    return None

@account_group.command(name="link", description="Link your Discord account to a Roblox account.")
@app_commands.describe(roblox_username="Your exact Roblox username.")
async def link_account(interaction: Interaction, roblox_username: str):
    await interaction.response.defer(ephemeral=True)
    discord_id = str(interaction.user.id)

    if discord_id in roblox_users_data:
        await interaction.followup.send("❌ Your Discord account is already linked to a Roblox account. Use `/account unlink` first.", ephemeral=True)
        return
        
    roblox_info = await get_roblox_user_info(roblox_username)
    
    if not roblox_info:
        await interaction.followup.send(f"❌ Could not find a Roblox user named `{roblox_username}`. Please check the spelling.", ephemeral=True)
        return

    roblox_id = roblox_info['id']
    validated_username = roblox_info['name']

    # Check if this Roblox account is already linked by someone else
    for D_id, R_data in roblox_users_data.items():
        if R_data.get('roblox_id') == roblox_id:
            other_user = bot.get_user(int(D_id))
            await interaction.followup.send(f"❌ That Roblox account is already linked by {other_user.mention if other_user else 'another user'}.", ephemeral=True)
            return

    roblox_users_data[discord_id] = {"roblox_id": roblox_id, "roblox_username": validated_username}
    save_to_json(roblox_users_data, ROBLOX_USERS_FILE)
    
    await interaction.followup.send(f"✅ Your Discord account has been successfully linked to the Roblox account: **{validated_username}**.", ephemeral=True)

@account_group.command(name="unlink", description="Unlink your Roblox account from your Discord account.")
async def unlink_account(interaction: Interaction):
    discord_id = str(interaction.user.id)
    if discord_id in roblox_users_data:
        del roblox_users_data[discord_id]
        save_to_json(roblox_users_data, ROBLOX_USERS_FILE)
        await interaction.response.send_message("✅ Your Roblox account has been unlinked.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ You do not have a Roblox account linked.", ephemeral=True)

@account_group.command(name="profile", description="View the linked Roblox profile for a Discord user.")
@app_commands.describe(user="The Discord user to view the profile of (optional, defaults to you).")
async def view_profile(interaction: Interaction, user: Optional[Member] = None):
    target_user = user or interaction.user
    discord_id = str(target_user.id)

    if discord_id not in roblox_users_data:
        if target_user.id == interaction.user.id:
             await interaction.response.send_message("❌ You do not have a Roblox account linked. Use `/account link`.", ephemeral=True)
        else:
             await interaction.response.send_message(f"❌ {target_user.mention} does not have a Roblox account linked.", ephemeral=True)
        return

    user_data = roblox_users_data[discord_id]
    roblox_id = user_data["roblox_id"]
    roblox_username = user_data["roblox_username"]
    
    embed = Embed(title=f"Linked Profile for {target_user.display_name}", color=target_user.color)
    embed.set_thumbnail(url=target_user.display_avatar.url)
    embed.add_field(name="Discord Account", value=target_user.mention, inline=False)
    embed.add_field(name="Roblox Account", value=f"[{roblox_username}](https://www.roblox.com/users/{roblox_id}/profile)", inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


# --- Session Management Commands ---
@session_group.command(name="start", description="Starts a new ERLC session.")
@app_commands.describe(session_type="The type of session.", description="A brief description of the session.")
@is_session_host()
async def session_start(interaction: Interaction, session_type: str, description: Optional[str] = None):
    if not interaction.guild or not interaction.guild_id or not isinstance(interaction.user, Member): return
    if interaction.guild_id in active_sessions_data:
        await interaction.response.send_message("❌ A session is already active.", ephemeral=True); return
    guild_config = get_guild_config(interaction.guild_id).get("erlc_config", {})
    announcement_channel_id = guild_config.get("session_announcements_channel_id")
    if not announcement_channel_id:
        await interaction.response.send_message("❌ Announcements channel not configured.", ephemeral=True); return
    announcement_channel = interaction.guild.get_channel(announcement_channel_id)
    if not isinstance(announcement_channel, TextChannel):
        await interaction.response.send_message("❌ Announcements channel is invalid.", ephemeral=True); return
    start_time = int(time.time())
    session_data = { "host_id": interaction.user.id, "start_time": start_time, "session_type": session_type, "description": description, "attendees": [interaction.user.id] }
    active_sessions_data[interaction.guild_id] = session_data
    save_to_json(active_sessions_data, ERLC_ACTIVE_SESSIONS_FILE)
    embed = Embed(title="ERLC Session Started", color=Color.green())
    embed.set_author(name=f"Host: {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
    embed.add_field(name="Session Type", value=session_type, inline=True)
    embed.add_field(name="Starts", value=f"<t:{start_time}:R>", inline=True)
    if description: embed.add_field(name="Description", value=description, inline=False)
    embed.set_footer(text=f"Server: {interaction.guild.name}")
    try:
        await announcement_channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Session started in {announcement_channel.mention}.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(f"❌ Could not send announcement to {announcement_channel.mention}.", ephemeral=True)

@session_group.command(name="end", description="Ends the currently active ERLC session.")
@is_session_host()
async def session_end(interaction: Interaction):
    if not interaction.guild or not interaction.guild_id or not isinstance(interaction.user, Member): return
    if interaction.guild_id not in active_sessions_data:
        await interaction.response.send_message("❌ No active session to end.", ephemeral=True); return
    session_data = active_sessions_data[interaction.guild_id]
    if session_data.get("host_id") != interaction.user.id and not interaction.user.guild_permissions.administrator:
        original_host = interaction.guild.get_member(session_data.get("host_id"))
        await interaction.response.send_message(f"❌ Only the host ({original_host.mention if original_host else 'Unknown'}) or an Admin can end this.", ephemeral=True); return
    start_time = session_data.get("start_time", int(time.time()))
    end_time = int(time.time())
    duration_seconds = end_time - start_time
    duration_str = str(datetime.timedelta(seconds=duration_seconds))
    guild_config = get_guild_config(interaction.guild_id).get("erlc_config", {})
    announcement_channel_id = guild_config.get("session_announcements_channel_id")
    logs_channel_id = guild_config.get("session_logs_channel_id")
    host = interaction.guild.get_member(session_data.get("host_id")) or "Unknown Host"
    if announcement_channel_id and (ann_ch := interaction.guild.get_channel(announcement_channel_id)):
        try:
            ann_embed = Embed(title="ERLC Session Ended", color=Color.red())
            ann_embed.add_field(name="Session Type", value=session_data.get("session_type", "N/A"), inline=True).add_field(name="Duration", value=duration_str, inline=True)
            ann_embed.set_author(name=f"Host: {getattr(host, 'display_name', 'Unknown')}", icon_url=getattr(host, 'display_avatar', None))
            await ann_ch.send(embed=ann_embed)
        except discord.Forbidden: await interaction.followup.send("⚠️ Could not send end announcement.", ephemeral=True)
    if logs_channel_id and (log_ch := interaction.guild.get_channel(logs_channel_id)):
        try:
            log_embed = Embed(title="Session Log", color=Color.light_gray(), timestamp=datetime.datetime.now(datetime.timezone.utc))
            log_embed.add_field(name="Session Type", value=session_data.get("session_type", "N/A"), inline=True)
            log_embed.add_field(name="Host", value=f"{getattr(host, 'mention', 'Unknown')} ({getattr(host, 'id', 'N/A')})", inline=True)
            log_embed.add_field(name="Duration", value=duration_str, inline=True)
            log_embed.add_field(name="Started At", value=f"<t:{start_time}:F>", inline=False).add_field(name="Ended At", value=f"<t:{end_time}:F>", inline=False)
            log_embed.add_field(name="Attendees", value="Attendee tracking not yet implemented.", inline=False)
            await log_ch.send(embed=log_embed)
        except discord.Forbidden: await interaction.followup.send("⚠️ Could not send session log.", ephemeral=True)
    del active_sessions_data[interaction.guild_id]
    save_to_json(active_sessions_data, ERLC_ACTIVE_SESSIONS_FILE)
    await interaction.response.send_message("✅ Session ended.", ephemeral=True)

@session_group.command(name="info", description="Displays information about the current session.")
async def session_info(interaction: Interaction):
    if not interaction.guild or not interaction.guild_id: return
    if interaction.guild_id not in active_sessions_data:
        await interaction.response.send_message("ℹ️ No active session.", ephemeral=True); return
    session_data = active_sessions_data[interaction.guild_id]
    host = interaction.guild.get_member(session_data.get("host_id"))
    start_time = session_data.get("start_time")
    embed = Embed(title="Active ERLC Session Information", color=Color.blue())
    if host: embed.set_author(name=f"Host: {host.display_name}", icon_url=host.display_avatar.url)
    embed.add_field(name="Session Type", value=session_data.get("session_type", "N/A"), inline=False)
    if session_data.get("description"): embed.add_field(name="Description", value=session_data.get("description"), inline=False)
    if start_time: embed.add_field(name="Active Since", value=f"<t:{start_time}:F> (<t:{start_time}:R>)", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- Global Error Handler ---
async def global_app_command_error_handler(interaction: discord.Interaction, error: app_commands.AppCommandError): 
    user_readable_error = "An unexpected error occurred."
    if isinstance(error, app_commands.CommandOnCooldown): user_readable_error = f"This command is on cooldown. Try again in {error.retry_after:.2f}s."
    elif isinstance(error, app_commands.MissingPermissions): user_readable_error = f"You lack permissions: `{' '.join(error.missing_permissions)}`"
    elif isinstance(error, app_commands.BotMissingPermissions): user_readable_error = f"I lack permissions: `{' '.join(error.missing_permissions)}`"
    elif isinstance(error, app_commands.CheckFailure): user_readable_error = str(error)
    print(f"ERROR: User: {interaction.user}, Guild: {interaction.guild_id}, Cmd: {interaction.command.qualified_name if interaction.command else 'N/A'}, Error: {type(error).__name__} - {error}")
    try:
        if interaction.response.is_done(): await interaction.followup.send(f"⚠️ {user_readable_error}", ephemeral=True)
        else: await interaction.response.send_message(f"⚠️ {user_readable_error}", ephemeral=True)
    except Exception as e_resp: print(f"ERROR sending error response: {e_resp}")
bot.tree.on_error = global_app_command_error_handler

# --- Main Execution ---
async def main_async():
    async with bot: 
        start_keep_alive_server()
        print(f"Flask web server thread started.")
        print(f"Attempting to connect {ARVO_BOT_NAME} to Discord...")
        await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("CRITICAL: DISCORD_TOKEN environment variable is not set.")
    else:
        load_all_data() 
        try: asyncio.run(main_async())
        except KeyboardInterrupt: print(f"{ARVO_BOT_NAME} shutting down manually...")
        except Exception as e: print(f"CRITICAL BOT RUN ERROR for {ARVO_BOT_NAME}: {e}")
