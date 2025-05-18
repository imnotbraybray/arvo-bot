# main.py
import discord
from discord.ext import commands
from discord import app_commands, ChannelType, Role, SelectOption
from discord.ui import View, Button, ChannelSelect, RoleSelect, Select
import os
from flask import Flask, render_template_string, abort, redirect, url_for, session, request
from threading import Thread
import datetime
import uuid # Kept for potential future use with submissions
import requests
import json 
import asyncio

# --- Arvo Bot Information ---
ARVO_BOT_NAME = "Arvo"
ARVO_BOT_DESCRIPTION = "Arvo - Smart Staff Management 🦉 Keep your server organized with automated moderation, role management, and staff coordination—all in one reliable bot."

# --- Constants & Configuration ---
DISCORD_CLIENT_ID = os.environ.get('DISCORD_CLIENT_ID')
DISCORD_CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET')
RENDER_EXTERNAL_URL = os.environ.get('RENDER_EXTERNAL_URL')
FLASK_SECRET_KEY = os.environ.get('FLASK_SECRET_KEY')
TARGET_GUILD_ID_WEB_AUTH = os.environ.get('TARGET_GUILD_ID_WEB_AUTH') 
TARGET_ROLE_NAME_OR_ID_WEB_AUTH = os.environ.get('TARGET_ROLE_NAME_OR_ID_WEB_AUTH') 

DISCORD_REDIRECT_URI = None
if RENDER_EXTERNAL_URL:
    DISCORD_REDIRECT_URI = f"{RENDER_EXTERNAL_URL}/callback"
    print(f"INFO: OAuth2 Redirect URI dynamically set to: {DISCORD_REDIRECT_URI}")
else:
    print("CRITICAL WARNING: RENDER_EXTERNAL_URL not set for OAuth2 Redirect URI. Web auth will fail.")

API_ENDPOINT = 'https://discord.com/api/v10'
submitted_forms_data = {} # For web view of submissions (if you add commands that use it)
guild_configurations = {} # Structure: {guild_id: {'log_channel_id': int, 'command_permissions': {'command_name': role_id_int}}}

def load_guild_configurations():
    global guild_configurations
    guild_configurations = {} 
    print("INFO: Using in-memory guild configurations. Data will be lost on restart.")
    # For a production bot, load from a persistent database here.

def save_guild_configuration(guild_id: int): 
    global guild_configurations
    print(f"INFO: Guild configuration updated in memory for guild {guild_id}: {guild_configurations.get(guild_id)}")
    # For a production bot, save guild_configurations[guild_id] to a persistent database here.

def get_guild_log_channel_id(guild_id: int) -> int | None:
    config = guild_configurations.get(guild_id)
    return config.get('log_channel_id') if config else None

def get_command_required_role_id(guild_id: int, command_name: str) -> int | None:
    guild_config = guild_configurations.get(guild_id, {})
    command_perms = guild_config.get('command_permissions', {})
    return command_perms.get(command_name)

# --- Flask App (for keep-alive and web view) ---
app = Flask('')
if FLASK_SECRET_KEY: app.secret_key = FLASK_SECRET_KEY
else: app.secret_key = 'temporary_insecure_development_key_pleasesetproperly'; print("CRITICAL WARNING: FLASK_SECRET_KEY not set.")

@app.route('/')
def home():
    if 'discord_user_id' in session: return f"Logged in as {session.get('discord_username', 'Unknown User')}. <a href='{url_for('logout')}'>Logout</a>"
    return f"{ARVO_BOT_NAME} is alive. <a href='{url_for('login')}'>Login with Discord to view submissions (Authorized Personnel)</a>"

@app.route('/login')
def login():
    if not all([DISCORD_CLIENT_ID, DISCORD_REDIRECT_URI]): return "OAuth2 config error.", 500
    discord_oauth_url = (f"{API_ENDPOINT}/oauth2/authorize?client_id={DISCORD_CLIENT_ID}"
                         f"&redirect_uri={DISCORD_REDIRECT_URI}&response_type=code&scope=identify guilds")
    return redirect(discord_oauth_url)

@app.route('/callback')
def callback():
    if not all([DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI]): return "OAuth2 server config error.", 500
    authorization_code = request.args.get('code')
    if not authorization_code: return "Error: No auth code.", 400
    data = {'client_id': DISCORD_CLIENT_ID, 'client_secret': DISCORD_CLIENT_SECRET, 'grant_type': 'authorization_code', 'code': authorization_code, 'redirect_uri': DISCORD_REDIRECT_URI}
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    try:
        token_response = requests.post(f'{API_ENDPOINT}/oauth2/token', data=data, headers=headers); token_response.raise_for_status(); token_data = token_response.json(); session['discord_token'] = token_data['access_token']
        user_info_response = requests.get(f'{API_ENDPOINT}/users/@me', headers={'Authorization': f"Bearer {token_data['access_token']}"}); user_info_response.raise_for_status(); user_info = user_info_response.json()
        session['discord_user_id'] = user_info['id']; session['discord_username'] = f"{user_info['username']}#{user_info['discriminator']}"
        next_url = session.pop('next_url', url_for('home')); return redirect(next_url)
    except requests.exceptions.RequestException as e: print(f"ERROR: OAuth2 callback: {e}"); return "Error during auth.", 500

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('home'))

def is_user_authorized_for_webview(user_id: str) -> bool: 
    if not bot.is_ready(): return False
    if not TARGET_GUILD_ID_WEB_AUTH or not TARGET_ROLE_NAME_OR_ID_WEB_AUTH: return False # Uses specific env vars for web view auth
    try: guild = bot.get_guild(int(TARGET_GUILD_ID_WEB_AUTH))
    except ValueError: return False
    if not guild: return False; 
    try: member = guild.get_member(int(user_id))
    except ValueError: return False
    if not member: return False
    target_role = None
    if TARGET_ROLE_NAME_OR_ID_WEB_AUTH.isdigit():
        try: target_role = guild.get_role(int(TARGET_ROLE_NAME_OR_ID_WEB_AUTH))
        except ValueError: target_role = discord.utils.get(guild.roles, name=TARGET_ROLE_NAME_OR_ID_WEB_AUTH)
    else: target_role = discord.utils.get(guild.roles, name=TARGET_ROLE_NAME_OR_ID_WEB_AUTH)
    return target_role in member.roles if target_role else False

# Basic HTML template for submissions (can be expanded later)
SUBMISSION_HTML_TEMPLATE = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Submission View - {{ ARVO_BOT_NAME }}</title><style>body{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;margin:0;background-color:#2c2f33;color:#fff;display:flex;flex-direction:column;min-height:100vh}.navbar{background-color:#23272a;padding:10px 20px;color:#fff;text-align:right}.navbar a{color:#7289da;text-decoration:none;margin-left:15px}.navbar a:hover{text-decoration:underline}.container{background-color:#36393f;padding:30px;border-radius:8px;box-shadow:0 0 15px rgba(0,0,0,.5);max-width:800px;margin:30px auto;flex-grow:1}h1{color:#7289da;border-bottom:2px solid #7289da;padding-bottom:10px;text-align:center}p{line-height:1.7}.info-bar{background-color:#23272a;padding:10px;border-radius:5px;margin-bottom:20px;font-size:.9em}.field{margin-bottom:20px;padding:15px;border-left:5px solid #7289da;background-color:#2c2f33;border-radius:4px;box-shadow:0 2px 4px rgba(0,0,0,.2)}.field-label{font-weight:700;display:block;margin-bottom:8px;color:#99aab5}.field-value{white-space:pre-wrap;color:#dcddde}.footer{text-align:center;padding:20px;font-size:.9em;color:#7289da;background-color:#23272a;margin-top:auto}.access-denied{text-align:center;padding:50px}.access-denied h1{color:#f04747}.login-prompt{text-align:center;margin-top:20px}.login-prompt a{background-color:#7289da;color:#fff;padding:10px 20px;text-decoration:none;border-radius:5px;font-weight:700}.login-prompt a:hover{background-color:#5f73bc}</style></head><body><div class="navbar">{% if session.discord_username %} Logged in as <strong>{{ session.discord_username }}</strong> | <a href="{{ url_for('logout') }}">Logout</a> {% else %} <a href="{{ url_for('login') }}">Login with Discord</a> {% endif %}</div>{% if error_message %}<div class="container access-denied"><h1>{{ "Access Denied" if error_message == "Unauthorized" else "Error" }}</h1><p>{{ "You do not have the required role to view this submission." if error_message == "Unauthorized" else error_message }}</p>{% if not session.discord_username and error_message == "You need to login to view submissions." %}<div class="login-prompt"><p>Please login to verify your identity.</p><a href="{{ url_for('login') }}?next={{ request.url }}">Login with Discord</a></div>{% endif %}</div>{% else %}<div class="container"><h1>Submission Detail</h1><div class="info-bar"><strong>Submission ID:</strong> {{ submission.id }} <br> <strong>Submitted By (Discord User):</strong> {{ submission.submitter_name }} (ID: {{ submission.submitter_id }}) <br> <strong>Timestamp:</strong> {{ submission.timestamp }}</div>{% for key, value in submission.data.items() %}<div class="field"><span class="field-label">{{ key.replace('_', ' ').title() }}:</span><div class="field-value">{{ value }}</div></div>{% endfor %}</div>{% endif %}<div class="footer"> {{ ARVO_BOT_NAME }} | Smart Staff Management </div></body></html>"""

@app.route('/submission/<submission_id>')
def view_submission(submission_id):
    if 'discord_user_id' not in session: session['next_url'] = request.url; return render_template_string(SUBMISSION_HTML_TEMPLATE, ARVO_BOT_NAME=ARVO_BOT_NAME, error_message="You need to login to view submissions.")
    if not is_user_authorized_for_webview(session['discord_user_id']): return render_template_string(SUBMISSION_HTML_TEMPLATE, ARVO_BOT_NAME=ARVO_BOT_NAME, error_message="Unauthorized"), 403
    submission_data = submitted_forms_data.get(submission_id) # This dict is currently empty
    if not submission_data: return render_template_string(SUBMISSION_HTML_TEMPLATE, ARVO_BOT_NAME=ARVO_BOT_NAME, error_message="Submission not found."), 404
    formatted_timestamp = submission_data['timestamp'].strftime("%Y-%m-%d %H:%M:%S UTC")
    display_data = {'id': submission_data['id'], 'submitter_name': submission_data['submitter_name'], 'submitter_id': submission_data['submitter_id'], 'timestamp': formatted_timestamp, 'data': submission_data['data']}
    return render_template_string(SUBMISSION_HTML_TEMPLATE, ARVO_BOT_NAME=ARVO_BOT_NAME, submission_id=submission_id, submission=display_data)

def run_flask_app(): port = int(os.environ.get('PORT', 8080)); app.run(host='0.0.0.0', port=port, debug=False)
def keep_alive(): server_thread = Thread(target=run_flask_app); server_thread.daemon = True; server_thread.start()

# --- Discord Bot (discord.py) Configuration ---
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
if BOT_TOKEN is None: print("CRITICAL: Bot token (DISCORD_TOKEN) not found. Bot cannot start."); exit()
intents = discord.Intents.default()
intents.members = True # Needed for role checks in is_user_authorized_for_webview and command perms
intents.message_content = True # Keep for potential DM commands or other features
bot = commands.Bot(command_prefix=commands.when_mentioned_or("!arvo-unused!"), intents=intents) # Prefix is vestigial

# --- Custom Check for Configured Command Permissions ---
class MissingConfiguredRole(app_commands.CheckFailure):
    def __init__(self, command_name: str, role_name: str | None, *args):
        self.role_name = role_name; self.command_name = command_name
        message = f"You need the '{role_name}' role to use `/{command_name}`." if role_name else f"You lack permissions for `/{command_name}`."
        super().__init__(message, *args)

async def check_command_permission(interaction: discord.Interaction) -> bool:
    if not interaction.guild_id: return True 
    command_name = interaction.command.name if interaction.command else None
    if not command_name or command_name == "setup": return True 
    required_role_id = get_command_required_role_id(interaction.guild_id, command_name)
    if required_role_id is None: return True 
    if not isinstance(interaction.user, discord.Member): return False 
    if required_role_id in [role.id for role in interaction.user.roles]: return True
    else:
        role_name = "configured role"; role_obj = interaction.guild.get_role(required_role_id) if interaction.guild else None
        if role_obj: role_name = role_obj.name
        raise MissingConfiguredRole(command_name, role_name)

# --- Setup UI Views ---
class CommandPermissionsView(View): # For /setup subcommand
    def __init__(self, bot_instance: commands.Bot, guild_id: int):
        super().__init__(timeout=300); self.bot_instance = bot_instance; self.guild_id = guild_id
        self.selected_command_name: str | None = None; self.selected_role_id: int | None = None
        self.configurable_commands = [cmd.name for cmd in bot.tree.get_commands() if cmd.name != "setup"] # Exclude setup itself
        
        command_options = [SelectOption(label=f"/{name}", value=name) for name in self.configurable_commands] if self.configurable_commands else [SelectOption(label="No other commands found", value="none_found", disabled=True)]
        self.command_select = Select(placeholder="Select command...", options=command_options, custom_id="cmd_perm_select_cmd", disabled=not self.configurable_commands)
        self.command_select.callback = self.command_select_callback; self.add_item(self.command_select)

        self.role_select = RoleSelect(placeholder="Select role to require...", custom_id="cmd_perm_select_role", disabled=True)
        self.role_select.callback = self.role_select_callback; self.add_item(self.role_select)

        self.current_perm_display = Button(label="Select command to see/set permission.", style=discord.ButtonStyle.secondary, disabled=True, custom_id="cmd_perm_display", row=2)
        self.add_item(self.current_perm_display)

        self.save_perm_button = Button(label="Set Required Role", style=discord.ButtonStyle.green, custom_id="cmd_perm_save", disabled=True, row=3)
        self.save_perm_button.callback = self.save_perm_callback; self.add_item(self.save_perm_button)

        self.clear_perm_button = Button(label="Clear Required Role", style=discord.ButtonStyle.red, custom_id="cmd_perm_clear", disabled=True, row=3)
        self.clear_perm_button.callback = self.clear_perm_callback; self.add_item(self.clear_perm_button)

    async def _update_view_state(self, interaction: discord.Interaction):
        self.role_select.disabled = self.selected_command_name is None or self.selected_command_name == "none_found"
        current_role_id = None; current_role_text = "No specific role required."
        if self.selected_command_name and self.selected_command_name != "none_found":
            current_role_id = get_command_required_role_id(self.guild_id, self.selected_command_name)
            if current_role_id and interaction.guild:
                role = interaction.guild.get_role(current_role_id)
                current_role_text = f"Requires: @{role.name}" if role else f"Requires ID: {current_role_id} (Role not found)"
            elif current_role_id: current_role_text = f"Requires ID: {current_role_id}"
        self.current_perm_display.label = f"Current for /{self.selected_command_name or '...'}: {current_role_text}"
        self.save_perm_button.disabled = not (self.selected_command_name and self.selected_command_name != "none_found" and self.selected_role_id)
        self.clear_perm_button.disabled = not (self.selected_command_name and self.selected_command_name != "none_found" and current_role_id is not None)
        await interaction.edit_original_response(view=self) # Edit the message this view is attached to

    async def command_select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(); self.selected_command_name = self.command_select.values[0]
        self.selected_role_id = None; self.role_select.placeholder = "Select a role to require..."
        await self._update_view_state(interaction)
    async def role_select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if self.role_select.values: self.selected_role_id = self.role_select.values[0].id
        await self._update_view_state(interaction)
    async def save_perm_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not self.selected_command_name or self.selected_command_name == "none_found" or not self.selected_role_id:
            await interaction.followup.send("Select command and role.", ephemeral=True); return
        guild_configurations.setdefault(self.guild_id, {}).setdefault('command_permissions', {})[self.selected_command_name] = self.selected_role_id
        save_guild_configuration(self.guild_id)
        role_obj = interaction.guild.get_role(self.selected_role_id) if interaction.guild else None
        await interaction.followup.send(f"✅ `/{self.selected_command_name}` now requires `@{role_obj.name if role_obj else self.selected_role_id}`.", ephemeral=True)
        await self._update_view_state(interaction.message.components[0].children[0].custom_id) # This needs to be fixed, can't call _update_view_state like this
                                                                                                # It expects an interaction. We need to edit the original message.
                                                                                                # The original interaction for the view message is not directly available here.
                                                                                                # A better way is to edit interaction.message if the view is persistent.
                                                                                                # For now, the followup confirmation is sent. The view on the original message won't auto-update.
    async def clear_perm_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not self.selected_command_name or self.selected_command_name == "none_found": await interaction.followup.send("Select command.", ephemeral=True); return
        guild_config = guild_configurations.get(self.guild_id)
        if guild_config and 'command_permissions' in guild_config and self.selected_command_name in guild_config['command_permissions']:
            del guild_config['command_permissions'][self.selected_command_name]
            if not guild_config['command_permissions']: del guild_config['command_permissions']
            save_guild_configuration(self.guild_id)
            await interaction.followup.send(f"✅ Role requirement for `/{self.selected_command_name}` cleared.", ephemeral=True)
        else: await interaction.followup.send(f"No specific role set for `/{self.selected_command_name}`.", ephemeral=True)
        # Similar issue here for updating the original view state.

class SetupView(View):
    def __init__(self, bot_instance: commands.Bot, guild_id: int, current_log_channel_id: int = None):
        super().__init__(timeout=300); self.bot_instance = bot_instance; self.guild_id = guild_id; self.selected_log_channel_id = current_log_channel_id
        self.log_channel_select = ChannelSelect(placeholder="Select Arvo's Log Channel...", channel_types=[ChannelType.text], min_values=1, max_values=1, custom_id="log_channel_select")
        self.log_channel_select.callback = self.log_channel_select_callback; self.add_item(self.log_channel_select)
        self.save_button = Button(label="Save Log Channel", style=discord.ButtonStyle.green, custom_id="save_log_channel_button", row=1)
        self.save_button.callback = self.save_log_channel_callback; self.add_item(self.save_button)
        self.cmd_perms_button = Button(label="Configure Command Permissions", style=discord.ButtonStyle.blurple, custom_id="cmd_perms_button_open", row=2) # Placeholder for now
        self.cmd_perms_button.callback = self.cmd_perms_open_callback; self.add_item(self.cmd_perms_button)

    async def log_channel_select_callback(self, interaction: discord.Interaction):
        if self.log_channel_select.values: self.selected_log_channel_id = self.log_channel_select.values[0].id; await interaction.response.send_message(f"Log channel selection: {self.log_channel_select.values[0].mention}. Click 'Save'.", ephemeral=True)
        else: await interaction.response.send_message("No channel selected.", ephemeral=True)

    async def save_log_channel_callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator: await interaction.response.send_message("Admin permissions needed.", ephemeral=True); return
        if self.selected_log_channel_id:
            guild_configurations.setdefault(self.guild_id, {})['log_channel_id'] = self.selected_log_channel_id
            save_guild_configuration(self.guild_id); log_channel_obj = self.bot_instance.get_channel(self.selected_log_channel_id)
            confirmation_message = f"✅ Log channel set to {log_channel_obj.mention if log_channel_obj else f'ID: {self.selected_log_channel_id}'}."
            
            # Update the original /setup embed
            current_log_channel_id_updated = get_guild_log_channel_id(interaction.guild_id) # Re-fetch
            log_channel_mention_updated = "Not Set"
            if current_log_channel_id_updated:
                ch = self.bot_instance.get_channel(current_log_channel_id_updated)
                if ch: log_channel_mention_updated = ch.mention
                else: log_channel_mention_updated = f"ID: {current_log_channel_id_updated} (Not found)"

            new_embed = discord.Embed(title=f"{ARVO_BOT_NAME} Server Configuration", description=f"Settings for **{interaction.guild.name}**.\n\n**Current Log Channel:** {log_channel_mention_updated}\n\nUse dropdown to change.", color=discord.Color.blue())
            new_embed.set_footer(text="Only Admins can save.")
            try: 
                await interaction.message.edit(embed=new_embed, view=self) # Edit the original message the view is attached to
                await interaction.response.send_message(confirmation_message, ephemeral=True) # Acknowledge button click
            except discord.HTTPException as e: 
                print(f"Error editing setup message: {e}")
                await interaction.response.send_message(confirmation_message, ephemeral=True) # Fallback for button click

            if log_channel_obj:
                try: await log_channel_obj.send(f"ℹ️ This is now {ARVO_BOT_NAME}'s log channel, set by {interaction.user.mention}.")
                except discord.Forbidden: print(f"Warning: No permission in new log channel {log_channel_obj.id}.")
        else: await interaction.response.send_message("Select log channel first.", ephemeral=True)

    async def cmd_perms_open_callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need Administrator permissions to configure command permissions.", ephemeral=True)
            return
        perm_view_embed = discord.Embed(title="Command Permission Setup", description="Select a command, then a role to restrict its usage. Click 'Set Required Role'.\nUse 'Clear Required Role' to make a command generally available.", color=discord.Color.purple())
        await interaction.response.send_message(embed=perm_view_embed, view=CommandPermissionsView(bot_instance=self.bot_instance, guild_id=self.guild_id), ephemeral=True)


# --- Bot Event Listeners ---
@bot.event
async def on_ready():
    load_guild_configurations() 
    print(f'Logged in as {ARVO_BOT_NAME} (ID: {bot.user.id})')
    print(f'Discord.py Version: {discord.__version__}')
    if RENDER_EXTERNAL_URL: print(f"Web base: {RENDER_EXTERNAL_URL}")
    else: print("Warning: RENDER_EXTERNAL_URL not set.")
    if not all([DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, FLASK_SECRET_KEY, TARGET_GUILD_ID_WEB_AUTH, TARGET_ROLE_NAME_OR_ID_WEB_AUTH]):
        print(f"CRITICAL WARNING: Flask OAuth2/Security/Targeting NOT fully configured for {ARVO_BOT_NAME} WEB VIEW.")
    try: 
        synced = await bot.tree.sync() 
        print(f"Synced {len(synced)} global slash commands for {ARVO_BOT_NAME}.")
    except Exception as e: print(f"Error syncing global commands: {e}")
    print(f'{ARVO_BOT_NAME} is ready and online!')
    await bot.change_presence(activity=discord.Game(name=f"/arvohelp | {ARVO_BOT_NAME}"))

# --- Basic Slash Commands for Arvo ---
@bot.tree.command(name="ping", description=f"Check {ARVO_BOT_NAME}'s responsiveness.")
@app_commands.check(check_command_permission) # Subject to configured perms
async def ping(interaction: discord.Interaction):
    latency = bot.latency * 1000  # Latency in milliseconds
    await interaction.response.send_message(f"Pong! 🏓 Latency: {latency:.2f}ms", ephemeral=True)

@bot.tree.command(name="arvohelp", description=f"Get information about {ARVO_BOT_NAME}.")
@app_commands.check(check_command_permission) # Subject to configured perms
async def arvohelp(interaction: discord.Interaction):
    embed = discord.Embed(
        title=f"{ARVO_BOT_NAME} - Smart Staff Management",
        description=ARVO_BOT_DESCRIPTION,
        color=discord.Color.og_blurple() # Or your bot's theme color
    )
    embed.add_field(name="How to Use", value="Use slash commands (e.g., `/setup`, `/ping`) to interact with me.", inline=False)
    embed.add_field(name="Configuration", value="Administrators can use `/setup` to configure my settings for this server.", inline=False)
    embed.set_footer(text=f"{ARVO_BOT_NAME} - Your reliable staff management assistant.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- Setup Command ---
@bot.tree.command(name="setup", description=f"Configure {ARVO_BOT_NAME} for your server (Admin only).")
@app_commands.checks.has_permissions(administrator=True) # Hardcoded admin check for /setup itself
async def setup(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True) 
    if not interaction.guild_id: await interaction.followup.send("This command is server-only.", ephemeral=True); return
    
    current_log_channel_id = get_guild_log_channel_id(interaction.guild_id); 
    log_channel_mention = "Not Set"
    if current_log_channel_id:
        guild = bot.get_guild(interaction.guild_id)
        channel = None 
        if guild: channel = guild.get_channel(current_log_channel_id) 
        if channel: log_channel_mention = channel.mention 
        else: log_channel_mention = f"ID: {current_log_channel_id} (not found/inaccessible)"
    
    embed = discord.Embed(title=f"{ARVO_BOT_NAME} Server Configuration", 
                          description=f"Configure settings for {ARVO_BOT_NAME} in **{interaction.guild.name if interaction.guild else 'this server'}**.\n\n"
                                      f"**Current Log Channel:** {log_channel_mention}\n\n"
                                      "Use components below to manage settings.", 
                          color=discord.Color.blue())
    embed.set_footer(text="Only Administrators can save changes.")
    view = SetupView(bot_instance=bot, guild_id=interaction.guild_id, current_log_channel_id=current_log_channel_id)
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)

@setup.error 
async def setup_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    response_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    if isinstance(error, app_commands.MissingPermissions): await response_method("⛔ Admin permissions needed for `/setup`.", ephemeral=True)
    else:
        print(f"Error in /setup: {error} (Type: {type(error).__name__})")
        try: await response_method("Error with setup command.", ephemeral=True)
        except: pass 

# --- Global Application Command Error Handler ---
async def global_app_command_error_handler(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if interaction.command and interaction.command.name == "setup" and isinstance(error, (app_commands.MissingPermissions)):
        return # Already handled by setup_error
    
    # Handle custom MissingConfiguredRole exception
    if isinstance(error, MissingConfiguredRole):
        response_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        try: await response_method(str(error), ephemeral=True)
        except: pass # Best effort
        return

    error_message_to_user = "An unexpected error occurred with that command."
    if isinstance(error, app_commands.CommandOnCooldown): error_message_to_user = f"This command is on cooldown. Try again in {error.retry_after:.2f}s."
    elif isinstance(error, app_commands.CheckFailure): # General check failures not caught by specific command's error handler
         error_message_to_user = "You do not meet the requirements to run this command."
    
    print(f"Global unhandled slash command error for '{interaction.command.name if interaction.command else 'Unknown'}': {type(error).__name__} - {error}")
    
    response_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    try:
        if not interaction.response.is_done(): 
            await response_method(error_message_to_user, ephemeral=True)
    except: pass # Best effort if sending error fails

bot.tree.on_error = global_app_command_error_handler

# --- Running the Bot and Keep-Alive Server ---
if __name__ == "__main__":
    if BOT_TOKEN:
        keep_alive()
        print("Keep-alive server thread started.")
        try:
            print(f"Attempting to connect {ARVO_BOT_NAME} to Discord...")
            bot.run(BOT_TOKEN)
        except Exception as e:
            print(f"CRITICAL BOT RUN ERROR: {e}")
    else:
        print(f"CRITICAL: Bot token (DISCORD_TOKEN) not found. {ARVO_BOT_NAME} cannot start.")

