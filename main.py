import discord
from discord.ext import commands
from discord import app_commands, Interaction, Member, Role, TextChannel, User
from discord.app_commands import Choice, Group # Added Group
import json
import os
import asyncio
import datetime # For mute duration
from typing import Optional, List, Dict, Any, Union

# --- Configuration ---
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

if not BOT_TOKEN:
    print("CRITICAL ERROR: The DISCORD_BOT_TOKEN environment variable is not set.")
    exit()

CONFIG_FILE = "arvo_guild_configs.json"
INFRACTIONS_FILE = "arvo_infractions.json" # For storing infraction records

# Default configuration for a new guild
DEFAULT_GUILD_CONFIG = {
    "log_channel_id": None,
    "staff_role_ids": [],
    "command_states": {} # Will be populated with actual command names
}

# --- Bot Subclass ---
class ArvoBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.guild_configs: Dict[str, Dict[str, Any]] = {}
        self.infractions: Dict[str, List[Dict[str, Any]]] = {} # { "guild_id-user_id": [infraction_list] }
        # COMMAND_REGISTRY stores metadata for manageable commands
        self.COMMAND_REGISTRY: Dict[str, Dict[str, Any]] = {}
        self.load_guild_configs()
        self.load_infractions()

    def load_guild_configs(self):
        try:
            with open(CONFIG_FILE, 'r') as f:
                self.guild_configs = json.load(f)
                self.guild_configs = {str(k): v for k, v in self.guild_configs.items()}
        except (FileNotFoundError, json.JSONDecodeError):
            self.guild_configs = {}
        print("Guild configurations loaded.")

    def save_guild_configs(self):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.guild_configs, f, indent=4)
        except Exception as e:
            print(f"Error saving guild configurations: {e}")

    def load_infractions(self):
        try:
            with open(INFRACTIONS_FILE, 'r') as f:
                self.infractions = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.infractions = {}
        print("Infraction records loaded.")

    def save_infractions(self):
        try:
            with open(INFRACTIONS_FILE, 'w') as f:
                json.dump(self.infractions, f, indent=4)
        except Exception as e:
            print(f"Error saving infractions: {e}")

    def get_guild_config(self, guild_id: int) -> Dict[str, Any]:
        guild_id_str = str(guild_id)
        if guild_id_str not in self.guild_configs:
            self.guild_configs[guild_id_str] = json.loads(json.dumps(DEFAULT_GUILD_CONFIG))
            self.guild_configs[guild_id_str]["command_states"] = {
                cmd_name: True for cmd_name in self.COMMAND_REGISTRY.keys() if self.COMMAND_REGISTRY[cmd_name].get("manageable", True)
            }
        elif self.COMMAND_REGISTRY:
            if "command_states" not in self.guild_configs[guild_id_str]:
                 self.guild_configs[guild_id_str]["command_states"] = {}
            for cmd_name in self.COMMAND_REGISTRY.keys():
                if self.COMMAND_REGISTRY[cmd_name].get("manageable", True) and cmd_name not in self.guild_configs[guild_id_str]["command_states"]:
                    self.guild_configs[guild_id_str]["command_states"][cmd_name] = True
        return self.guild_configs[guild_id_str]

    async def log_action(self, guild: discord.Guild, title: str, description: str, color: discord.Color = discord.Color.blue(), mod_user: Optional[User] = None, target_user: Optional[Union[User, Member]] = None, fields: Optional[List[Dict[str, Any]]] = None):
        config = self.get_guild_config(guild.id)
        log_channel_id = config.get("log_channel_id")
        if not log_channel_id: return

        log_channel = guild.get_channel(log_channel_id)
        if isinstance(log_channel, TextChannel):
            embed = discord.Embed(title=f"📜 {title}", description=description, color=color, timestamp=discord.utils.utcnow())
            if mod_user:
                embed.set_author(name=f"Moderator: {mod_user}", icon_url=mod_user.display_avatar.url if mod_user.display_avatar else None)
            if target_user:
                embed.add_field(name="Target User", value=f"{target_user.mention} ({target_user.id})", inline=False)
            if fields:
                for field in fields:
                    embed.add_field(name=field["name"], value=field["value"], inline=field.get("inline", False))
            embed.set_footer(text=f"Guild: {guild.name}")
            try:
                await log_channel.send(embed=embed)
            except discord.Forbidden:
                print(f"Log Error (Guild: {guild.id}): Missing permissions in log channel {log_channel_id}.")
            except Exception as e:
                print(f"Log Error (Guild: {guild.id}): {e}")

    def add_infraction(self, guild_id: int, user_id: int, type: str, reason: str, moderator_id: int, duration: Optional[str] = None, points: Optional[int] = 0):
        key = f"{guild_id}-{user_id}"
        infraction_record = {
            "type": type,
            "reason": reason,
            "moderator_id": moderator_id,
            "timestamp": discord.utils.utcnow().isoformat(),
            "duration": duration,
            "points": points # Example, can be expanded
        }
        if key not in self.infractions:
            self.infractions[key] = []
        self.infractions[key].append(infraction_record)
        self.save_infractions()

    def is_staff(self, interaction: Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, Member): return False
        if interaction.user.guild_permissions.administrator: return True
        config = self.get_guild_config(interaction.guild.id)
        staff_role_ids = config.get("staff_role_ids", [])
        if not staff_role_ids: return False
        return any(r.id in staff_role_ids for r in interaction.user.roles)

    def register_manageable_command(self, name: str, description: str, group: Optional[Group] = None, manageable: bool = True):
        def decorator(func):
            # If part of a group, the command name in registry might need to be group_name_command_name
            full_cmd_name = f"{group.name}_{name}" if group else name
            self.COMMAND_REGISTRY[full_cmd_name] = {
                "callback": func,
                "description": description,
                "app_command_obj": None,
                "group_name": group.name if group else None,
                "base_name": name,
                "manageable": manageable # Not all commands should be toggleable (e.g. togglecommand itself)
            }
            return func
        return decorator

    async def setup_hook(self):
        print("Running ArvoBot setup_hook...")
        self.load_guild_configs()
        self.load_infractions()

        # Create AppCommand objects
        for cmd_name_full, cmd_data in self.COMMAND_REGISTRY.items():
            # Check if it's a subcommand or a top-level command
            # This part is tricky because app_commands.Command doesn't directly take a group object for subcommands
            # The group structure is typically defined by decorating methods of a Group instance.
            # For simplicity here, we'll assume the decorators on the command functions handle group registration.
            # The app_command_obj will be the command itself.
            
            # We need to ensure that the command object is correctly created and associated,
            # especially for commands within groups.
            # The current `register_manageable_command` stores the callback.
            # The actual `app_commands.Command` or `app_commands.Group` structure is built by discord.py
            # when it processes the decorators on the command functions.
            # We'll retrieve the created command objects from the tree later.
            pass


        # Add command groups to the tree
        self.tree.add_command(config_group)
        self.tree.add_command(infract_group)
        self.tree.add_command(staffmanage_group)
        self.tree.add_command(staffinfract_group)
        # Add togglecommand globally (or it could be guild-specific if preferred)
        # self.tree.add_command(togglecommand_cmd) # togglecommand_cmd is defined later

        # Populate app_command_obj in COMMAND_REGISTRY
        all_app_commands = self.tree.get_commands(type=discord.AppCommandType.chat_input)
        for app_cmd in all_app_commands:
            if isinstance(app_cmd, app_commands.Group):
                for sub_cmd in app_cmd.commands:
                    if isinstance(sub_cmd, app_commands.Command): # Check if it's a Command, not another Group
                        registry_key = f"{app_cmd.name}_{sub_cmd.name}"
                        if registry_key in self.COMMAND_REGISTRY:
                            self.COMMAND_REGISTRY[registry_key]["app_command_obj"] = sub_cmd
            elif isinstance(app_cmd, app_commands.Command):
                 if app_cmd.name in self.COMMAND_REGISTRY: # For top-level commands
                    self.COMMAND_REGISTRY[app_cmd.name]["app_command_obj"] = app_cmd
                 elif app_cmd.name == "togglecommand": # Special case for togglecommand
                     if "togglecommand" not in self.COMMAND_REGISTRY: # If not already added by decorator
                        self.COMMAND_REGISTRY["togglecommand"] = {"app_command_obj": app_cmd, "manageable": False}


        # Initialize default command states for any new commands in existing configs
        for guild_id_str in self.guild_configs.keys():
            if "command_states" not in self.guild_configs[guild_id_str]:
                self.guild_configs[guild_id_str]["command_states"] = {}
            for cmd_key, cmd_data_reg in self.COMMAND_REGISTRY.items():
                if cmd_data_reg.get("manageable", True) and cmd_key not in self.guild_configs[guild_id_str]["command_states"]:
                    self.guild_configs[guild_id_str]["command_states"][cmd_key] = True

        # Register commands for each guild based on stored states
        for guild_discord_obj in self.guilds:
            guild_id_str = str(guild_discord_obj.id)
            guild_config = self.get_guild_config(guild_discord_obj.id)
            
            current_guild_commands = []
            for cmd_key, cmd_data_reg in self.COMMAND_REGISTRY.items():
                app_cmd_obj_to_register = cmd_data_reg.get("app_command_obj")
                if not app_cmd_obj_to_register:
                    # print(f"Warning: No app_command_obj for {cmd_key} in registry during setup_hook for guild {guild_discord_obj.name}")
                    continue

                is_enabled = guild_config.get("command_states", {}).get(cmd_key, True)
                is_manageable = cmd_data_reg.get("manageable", True)

                if is_manageable:
                    if is_enabled:
                        current_guild_commands.append(app_cmd_obj_to_register)
                else: # Non-manageable commands are always added (like togglecommand, config)
                    # Need to handle how these are added, groups vs individual
                    # For now, assume they are added globally or handled by their own registration logic
                    # Let's refine this: config commands and togglecommand should be added explicitly.
                    pass # They are added via self.tree.add_command(group) or self.tree.add_command(command_obj)

            # Add togglecommand and config group to every guild initially
            # The individual subcommands of config_group will be there.
            # Manageable commands are added/removed based on state.
            
            self.tree.clear_commands(guild=guild_discord_obj) # Clear existing to ensure clean state
            
            # Add non-manageable (core) commands first
            self.tree.add_command(config_group, guild=guild_discord_obj)
            self.tree.add_command(togglecommand_cmd, guild=guild_discord_obj) # Defined later

            # Add manageable commands based on their state
            for cmd_key, cmd_data_reg in self.COMMAND_REGISTRY.items():
                app_cmd_obj_to_register = cmd_data_reg.get("app_command_obj")
                if not app_cmd_obj_to_register or not cmd_data_reg.get("manageable", True) :
                    continue # Skip if no object or not manageable

                is_enabled = guild_config.get("command_states", {}).get(cmd_key, True)
                if is_enabled:
                    # This logic needs to correctly add grouped commands vs top-level
                    group_name = cmd_data_reg.get("group_name")
                    if group_name:
                        # Find the group object already added to the tree for this guild
                        # This is complex; simpler to add the whole group if any of its commands are enabled,
                        # then rely on Discord to not show disabled subcommands (not how it works).
                        # Instead, we add individual commands to their respective groups if the group is present.
                        # The current approach: add the group (e.g. infract_group) if *any* of its subcommands are enabled.
                        # Then, if a specific subcommand is disabled, it *should* not appear.
                        # However, discord.py manages this by not adding the command to the tree.
                        
                        # Let's try adding the parent group if not already added for this sync cycle
                        # This is getting complex. A simpler model:
                        # Sync all commands that are enabled. If a group has enabled commands, it will appear.
                        # If all commands in a group are disabled, the group itself might not show.
                        
                        # Re-simplification:
                        # Add all groups that contain at least one enabled command.
                        # Add all top-level commands that are enabled.
                        
                        # The `tree.add_command(app_cmd_obj_to_register, guild=guild_discord_obj)` should handle this.
                        # If app_cmd_obj_to_register is a subcommand, its parent group must be added.
                        # The initial self.tree.add_command(infract_group etc.) handles adding the groups.
                        # The sync will then show only enabled subcommands IF discord.py handles it that way.
                        # More likely: we must add the specific command object.
                        
                        # Let's assume app_cmd_obj_to_register is the specific command object.
                        # If it's part of a group, that group must be on the tree for the guild.
                        # The groups (config_group, infract_group etc.) are added above.
                        
                        # If the app_cmd_obj_to_register is a subcommand, add it.
                        # If it's a top-level command, add it.
                        self.tree.add_command(app_cmd_obj_to_register, guild=guild_discord_obj)
            try:
                await self.tree.sync(guild=guild_discord_obj)
                print(f"Synced commands for guild {guild_discord_obj.name}.")
            except discord.errors.Forbidden:
                print(f"FORBIDDEN: Cannot sync commands for guild {guild_discord_obj.name}. Check 'application.commands' scope.")
            except Exception as e:
                print(f"ERROR syncing commands for guild {guild_discord_obj.name}: {e}")
        
        self.save_guild_configs()
        print("ArvoBot setup_hook completed.")

    async def on_guild_join(self, guild: discord.Guild):
        print(f"Joined new guild: {guild.name} (ID: {guild.id})")
        self.get_guild_config(guild.id) # Creates default config
        
        self.tree.clear_commands(guild=guild)
        self.tree.add_command(config_group, guild=guild)
        self.tree.add_command(togglecommand_cmd, guild=guild)

        for cmd_key, cmd_data_reg in self.COMMAND_REGISTRY.items():
            if cmd_data_reg.get("manageable", True) and cmd_data_reg.get("app_command_obj"):
                # By default, all manageable commands are enabled for a new guild
                self.tree.add_command(cmd_data_reg["app_command_obj"], guild=guild)
        try:
            await self.tree.sync(guild=guild)
            print(f"Successfully synced commands for new guild {guild.name}.")
        except Exception as e:
            print(f"ERROR syncing commands for new guild {guild.name}: {e}")
        self.save_guild_configs()

# --- Bot Instance ---
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = False # Slash commands don't need it
bot = ArvoBot(command_prefix=commands.when_mentioned_or("!arvo "), intents=intents)

# --- Helper: Permission Check Decorators ---
def is_guild_staff():
    async def predicate(interaction: Interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return False
        if not bot.is_staff(interaction):
            await interaction.response.send_message("🚫 You do not have permission to use this command. This requires a configured staff role or administrator privileges.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

def is_guild_admin():
    async def predicate(interaction: Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, Member):
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return False
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("🚫 You must be an Administrator to use this command.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

# --- Command Groups ---
config_group = Group(name="arvo_config", description="Configure Arvo bot for this server.", guild_only=True)
infract_group = Group(name="infract", description="User infraction management commands.", guild_only=True)
staffmanage_group = Group(name="staffmanage", description="Staff management commands.", guild_only=True)
staffinfract_group = Group(name="staffinfract", description="Staff infraction commands.", guild_only=True)


# --- Configuration Commands ---
@bot.register_manageable_command(name="set_log_channel", description="Sets the channel for bot action logs.", group=config_group, manageable=False)
@is_guild_admin()
async def set_log_channel(interaction: Interaction, channel: TextChannel):
    guild_config = bot.get_guild_config(interaction.guild_id)
    guild_config["log_channel_id"] = channel.id
    bot.save_guild_configs()
    await interaction.response.send_message(f"✅ Log channel set to {channel.mention}.", ephemeral=True)
    await bot.log_action(interaction.guild, "Config Update", f"Log channel set to {channel.mention}", mod_user=interaction.user, color=discord.Color.green())

@bot.register_manageable_command(name="add_staff_role", description="Adds a role that grants staff permissions for bot commands.", group=config_group, manageable=False)
@is_guild_admin()
async def add_staff_role(interaction: Interaction, role: Role):
    guild_config = bot.get_guild_config(interaction.guild_id)
    if role.id not in guild_config["staff_role_ids"]:
        guild_config["staff_role_ids"].append(role.id)
        bot.save_guild_configs()
        await interaction.response.send_message(f"✅ Role {role.mention} added to staff roles.", ephemeral=True)
        await bot.log_action(interaction.guild, "Config Update", f"Staff role {role.mention} added.", mod_user=interaction.user, color=discord.Color.green())
    else:
        await interaction.response.send_message(f"⚠️ Role {role.mention} is already a staff role.", ephemeral=True)

@bot.register_manageable_command(name="remove_staff_role", description="Removes a role from staff permissions.", group=config_group, manageable=False)
@is_guild_admin()
async def remove_staff_role(interaction: Interaction, role: Role):
    guild_config = bot.get_guild_config(interaction.guild_id)
    if role.id in guild_config["staff_role_ids"]:
        guild_config["staff_role_ids"].remove(role.id)
        bot.save_guild_configs()
        await interaction.response.send_message(f"✅ Role {role.mention} removed from staff roles.", ephemeral=True)
        await bot.log_action(interaction.guild, "Config Update", f"Staff role {role.mention} removed.", mod_user=interaction.user, color=discord.Color.orange())
    else:
        await interaction.response.send_message(f"⚠️ Role {role.mention} is not a staff role.", ephemeral=True)

@bot.register_manageable_command(name="view_config", description="Views the current bot configuration for this server.", group=config_group, manageable=False)
@is_guild_staff() # Staff can view
async def view_config(interaction: Interaction):
    guild_config = bot.get_guild_config(interaction.guild_id)
    log_channel = interaction.guild.get_channel(guild_config['log_channel_id']) if guild_config['log_channel_id'] else "Not Set"
    staff_roles = [interaction.guild.get_role(r_id).mention for r_id in guild_config['staff_role_ids'] if interaction.guild.get_role(r_id)]
    
    embed = discord.Embed(title=f"Arvo Configuration for {interaction.guild.name}", color=discord.Color.blurple())
    embed.add_field(name="Log Channel", value=log_channel.mention if isinstance(log_channel, TextChannel) else str(log_channel), inline=False)
    embed.add_field(name="Staff Roles", value=", ".join(staff_roles) if staff_roles else "None Set", inline=False)
    
    enabled_commands = [cmd for cmd, state in guild_config.get("command_states", {}).items() if state]
    disabled_commands = [cmd for cmd, state in guild_config.get("command_states", {}).items() if not state]
    
    embed.add_field(name="Enabled Manageable Commands", value=f"```{', '.join(enabled_commands) if enabled_commands else 'None'}```", inline=False)
    embed.add_field(name="Disabled Manageable Commands", value=f"```{', '.join(disabled_commands) if disabled_commands else 'None'}```", inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


# --- Infraction Commands ---
@bot.register_manageable_command(name="warn", description="Warns a user.", group=infract_group)
@is_guild_staff()
@app_commands.describe(member="The member to warn.", reason="The reason for the warning.")
async def infract_warn(interaction: Interaction, member: Member, reason: str):
    if member == interaction.user:
        await interaction.response.send_message("You cannot warn yourself.", ephemeral=True)
        return
    if bot.is_staff(interaction) and member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id :
         await interaction.response.send_message("You cannot warn a staff member with equal or higher role.", ephemeral=True)
         return

    bot.add_infraction(interaction.guild_id, member.id, "warn", reason, interaction.user.id, points=1)
    await bot.log_action(interaction.guild, "User Warned", f"{member.mention} was warned by {interaction.user.mention}.", mod_user=interaction.user, target_user=member, fields=[{"name": "Reason", "value": reason}])
    try:
        await member.send(f"You have been warned in **{interaction.guild.name}** for: {reason}")
    except discord.Forbidden:
        await interaction.response.send_message(f"✅ {member.mention} warned. Could not DM the user.", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ {member.mention} has been warned. Reason: {reason}", ephemeral=True)

@bot.register_manageable_command(name="mute", description="Mutes a user for a specified duration (e.g., 10m, 1h, 1d).", group=infract_group)
@is_guild_staff()
@app_commands.describe(member="The member to mute.", duration_str="Duration (e.g., 5m, 2h, 1d, 1w). Max 28 days.", reason="The reason for the mute.")
async def infract_mute(interaction: Interaction, member: Member, duration_str: str, reason: str):
    if member == interaction.user:
        await interaction.response.send_message("You cannot mute yourself.", ephemeral=True)
        return
    if bot.is_staff(interaction) and member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id :
         await interaction.response.send_message("You cannot mute a staff member with equal or higher role.", ephemeral=True)
         return

    delta = None
    duration_seconds = 0
    unit = duration_str[-1].lower()
    value = int(duration_str[:-1])

    if unit == 'm': delta = datetime.timedelta(minutes=value); duration_seconds = value * 60
    elif unit == 'h': delta = datetime.timedelta(hours=value); duration_seconds = value * 3600
    elif unit == 'd': delta = datetime.timedelta(days=value); duration_seconds = value * 86400
    elif unit == 'w': delta = datetime.timedelta(weeks=value); duration_seconds = value * 604800
    else:
        await interaction.response.send_message("Invalid duration format. Use 'm' for minutes, 'h' for hours, 'd' for days, 'w' for weeks (e.g., 30m, 2h, 7d).", ephemeral=True)
        return

    if duration_seconds <= 0 or duration_seconds > 28 * 86400: # Max 28 days
        await interaction.response.send_message("Duration must be between 1 minute and 28 days.", ephemeral=True)
        return

    try:
        await member.timeout(delta, reason=f"Muted by {interaction.user.name}: {reason}")
        bot.add_infraction(interaction.guild_id, member.id, "mute", reason, interaction.user.id, duration=duration_str, points=3) # Example points
        await bot.log_action(interaction.guild, "User Muted", f"{member.mention} was muted by {interaction.user.mention} for {duration_str}.", mod_user=interaction.user, target_user=member, fields=[{"name": "Reason", "value": reason}])
        try:
            await member.send(f"You have been muted in **{interaction.guild.name}** for {duration_str}. Reason: {reason}")
        except discord.Forbidden:
            pass # User might have DMs closed
        await interaction.response.send_message(f"✅ {member.mention} has been muted for {duration_str}. Reason: {reason}", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(f"🚫 Failed to mute {member.mention}. I may lack permissions or they have a higher role.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)


@bot.register_manageable_command(name="kick", description="Kicks a user from the server.", group=infract_group)
@is_guild_staff()
@app_commands.describe(member="The member to kick.", reason="The reason for the kick.")
async def infract_kick(interaction: Interaction, member: Member, reason: str):
    if member == interaction.user:
        await interaction.response.send_message("You cannot kick yourself.", ephemeral=True)
        return
    if bot.is_staff(interaction) and member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id :
         await interaction.response.send_message("You cannot kick a staff member with equal or higher role.", ephemeral=True)
         return

    try:
        dm_message = f"You have been kicked from **{interaction.guild.name}**. Reason: {reason}"
        try:
            await member.send(dm_message)
        except discord.Forbidden:
            pass # User might have DMs closed
        
        await member.kick(reason=f"Kicked by {interaction.user.name}: {reason}")
        bot.add_infraction(interaction.guild_id, member.id, "kick", reason, interaction.user.id, points=5)
        await bot.log_action(interaction.guild, "User Kicked", f"{member.mention} was kicked by {interaction.user.mention}.", mod_user=interaction.user, target_user=member, fields=[{"name": "Reason", "value": reason}], color=discord.Color.orange())
        await interaction.response.send_message(f"✅ {member.mention} has been kicked. Reason: {reason}", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(f"🚫 Failed to kick {member.mention}. I may lack permissions or they have a higher role.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)

@bot.register_manageable_command(name="ban", description="Bans a user from the server.", group=infract_group)
@is_guild_staff()
@app_commands.describe(user="The user to ban (can be ID if not in server).", reason="The reason for the ban.", delete_message_days="Number of days of messages to delete (0-7). Default 0.")
async def infract_ban(interaction: Interaction, user: User, reason: str, delete_message_days: app_commands.Range[int, 0, 7] = 0):
    if user.id == interaction.user.id:
        await interaction.response.send_message("You cannot ban yourself.", ephemeral=True)
        return
    
    # Check if user is a member for role hierarchy check
    member_in_guild = interaction.guild.get_member(user.id)
    if member_in_guild and bot.is_staff(interaction) and member_in_guild.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
         await interaction.response.send_message("You cannot ban a staff member with equal or higher role.", ephemeral=True)
         return

    try:
        dm_message = f"You have been banned from **{interaction.guild.name}**. Reason: {reason}"
        try:
            await user.send(dm_message)
        except discord.Forbidden:
            pass # User might have DMs closed or not be in server
        
        await interaction.guild.ban(user, reason=f"Banned by {interaction.user.name}: {reason}", delete_message_days=delete_message_days)
        bot.add_infraction(interaction.guild_id, user.id, "ban", reason, interaction.user.id, points=10)
        await bot.log_action(interaction.guild, "User Banned", f"{user.mention} ({user.id}) was banned by {interaction.user.mention}.", mod_user=interaction.user, target_user=user, fields=[{"name": "Reason", "value": reason}, {"name": "Messages Deleted", "value": f"{delete_message_days} days"}], color=discord.Color.red())
        await interaction.response.send_message(f"✅ {user.mention} ({user.id}) has been banned. Reason: {reason}", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(f"🚫 Failed to ban {user.mention}. I may lack permissions or they have a higher role.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)

# --- Staff Management Commands ---
@bot.register_manageable_command(name="promote", description="Promotes a staff member (conceptual, logs action).", group=staffmanage_group)
@is_guild_admin() # Typically admin action
@app_commands.describe(member="The staff member to promote.", new_role="The new role to assign (optional).", reason="Reason for promotion.")
async def staffmanage_promote(interaction: Interaction, member: Member, reason: str, new_role: Optional[Role] = None):
    if not bot.is_staff(interaction): # Check if target is staff - might need refinement based on how "staff" is defined beyond bot perms
        pass # Allow promoting non-staff to staff via this, or add check. For now, focuses on existing staff.
    
    action_taken = f"{member.mention} was conceptually promoted by {interaction.user.mention}."
    if new_role:
        try:
            await member.add_roles(new_role, reason=f"Promoted by {interaction.user.name}: {reason}")
            action_taken += f" They were given the {new_role.mention} role."
        except discord.Forbidden:
            action_taken += f" Failed to assign {new_role.mention} due to permissions."
        except Exception as e:
            action_taken += f" Error assigning {new_role.mention}: {e}."

    await bot.log_action(interaction.guild, "Staff Promoted", action_taken, mod_user=interaction.user, target_user=member, fields=[{"name": "Reason", "value": reason}], color=discord.Color.gold())
    await interaction.response.send_message(f"✅ Promotion for {member.mention} logged. {('Role ' + new_role.name + ' assigned.' if new_role else '')}", ephemeral=True)

@bot.register_manageable_command(name="demote", description="Demotes a staff member (conceptual, logs action).", group=staffmanage_group)
@is_guild_admin()
@app_commands.describe(member="The staff member to demote.", old_role="The role to remove (optional).", reason="Reason for demotion.")
async def staffmanage_demote(interaction: Interaction, member: Member, reason: str, old_role: Optional[Role] = None):
    action_taken = f"{member.mention} was conceptually demoted by {interaction.user.mention}."
    if old_role:
        try:
            await member.remove_roles(old_role, reason=f"Demoted by {interaction.user.name}: {reason}")
            action_taken += f" Their {old_role.mention} role was removed."
        except discord.Forbidden:
            action_taken += f" Failed to remove {old_role.mention} due to permissions."
        except Exception as e:
            action_taken += f" Error removing {old_role.mention}: {e}."

    await bot.log_action(interaction.guild, "Staff Demoted", action_taken, mod_user=interaction.user, target_user=member, fields=[{"name": "Reason", "value": reason}], color=discord.Color.dark_gold())
    await interaction.response.send_message(f"✅ Demotion for {member.mention} logged. {('Role ' + old_role.name + ' removed.' if old_role else '')}", ephemeral=True)

@bot.register_manageable_command(name="terminate", description="Terminates a staff member (conceptual, logs action, removes staff roles).", group=staffmanage_group)
@is_guild_admin()
@app_commands.describe(member="The staff member to terminate.", reason="Reason for termination.")
async def staffmanage_terminate(interaction: Interaction, member: Member, reason: str):
    guild_config = bot.get_guild_config(interaction.guild_id)
    staff_role_ids_to_remove = guild_config.get("staff_role_ids", [])
    roles_removed_mentions = []

    for role_id in staff_role_ids_to_remove:
        role_obj = interaction.guild.get_role(role_id)
        if role_obj and role_obj in member.roles:
            try:
                await member.remove_roles(role_obj, reason=f"Staff termination by {interaction.user.name}: {reason}")
                roles_removed_mentions.append(role_obj.mention)
            except discord.Forbidden:
                await interaction.response.send_message(f"Could not remove role {role_obj.mention} from {member.mention} due to permissions during termination. Action logged.", ephemeral=True)
            except Exception as e:
                 await interaction.response.send_message(f"Error removing role {role_obj.mention}: {e}. Action logged.", ephemeral=True)


    action_taken = f"{member.mention} was terminated from staff by {interaction.user.mention}."
    if roles_removed_mentions:
        action_taken += f" Removed staff roles: {', '.join(roles_removed_mentions)}."
    else:
        action_taken += " No configured staff roles found on the user to remove."

    await bot.log_action(interaction.guild, "Staff Terminated", action_taken, mod_user=interaction.user, target_user=member, fields=[{"name": "Reason", "value": reason}], color=discord.Color.dark_red())
    await interaction.response.send_message(f"✅ Termination for {member.mention} processed and logged.", ephemeral=True)


# --- Staff Infraction Commands ---
@bot.register_manageable_command(name="warning", description="Issues an official warning to a staff member.", group=staffinfract_group)
@is_guild_admin() # Usually a higher-up action
@app_commands.describe(staff_member="The staff member to warn.", reason="The reason for the staff warning.")
async def staffinfract_warning(interaction: Interaction, staff_member: Member, reason: str):
    if not bot.is_staff(interaction): # Or a more specific check if target is actually staff
        # await interaction.response.send_message(f"⚠️ {staff_member.mention} is not recognized as a staff member based on configured roles.", ephemeral=True)
        # return # Decide if this check is needed or if any member can be "staff warned"
        pass

    bot.add_infraction(interaction.guild_id, staff_member.id, "staff_warning", reason, interaction.user.id, points=2) # Example points for staff infractions
    await bot.log_action(interaction.guild, "Staff Warning Issued", f"Staff member {staff_member.mention} was issued a warning by {interaction.user.mention}.", mod_user=interaction.user, target_user=staff_member, fields=[{"name": "Reason", "value": reason}], color=discord.Color.orange())
    try:
        await staff_member.send(f"You have received an official staff warning in **{interaction.guild.name}**. Reason: {reason}")
    except discord.Forbidden:
        pass
    await interaction.response.send_message(f"✅ Staff warning issued to {staff_member.mention}. Reason: {reason}", ephemeral=True)

@bot.register_manageable_command(name="strike", description="Issues a strike to a staff member.", group=staffinfract_group)
@is_guild_admin()
@app_commands.describe(staff_member="The staff member to issue a strike to.", reason="The reason for the staff strike.")
async def staffinfract_strike(interaction: Interaction, staff_member: Member, reason: str):
    # Similar logic to staff warning
    bot.add_infraction(interaction.guild_id, staff_member.id, "staff_strike", reason, interaction.user.id, points=5)
    await bot.log_action(interaction.guild, "Staff Strike Issued", f"Staff member {staff_member.mention} was issued a strike by {interaction.user.mention}.", mod_user=interaction.user, target_user=staff_member, fields=[{"name": "Reason", "value": reason}], color=discord.Color.red())
    try:
        await staff_member.send(f"You have received an official staff strike in **{interaction.guild.name}**. Reason: {reason}")
    except discord.Forbidden:
        pass
    await interaction.response.send_message(f"✅ Staff strike issued to {staff_member.mention}. Reason: {reason}", ephemeral=True)


# --- Toggle Command ---
@app_commands.command(name="togglecommand", description="Enables or disables a manageable command for this server.")
@is_guild_admin() # Only admins can toggle commands
@app_commands.guild_only()
@app_commands.describe(command_name="The command to toggle.", enable="Set to True to enable, False to disable.")
async def togglecommand_cmd(interaction: Interaction, command_name: str, enable: bool):
    guild_config = bot.get_guild_config(interaction.guild_id)
    
    if command_name not in bot.COMMAND_REGISTRY or not bot.COMMAND_REGISTRY[command_name].get("manageable", True):
        await interaction.response.send_message(f"⚠️ Command `{command_name}` is not a known manageable command.", ephemeral=True)
        return

    current_status = guild_config["command_states"].get(command_name, True) # Default to enabled if not set
    if current_status == enable:
        status_text = "enabled" if enable else "disabled"
        await interaction.response.send_message(f"ℹ️ Command `{command_name}` is already {status_text}.", ephemeral=True)
        return

    guild_config["command_states"][command_name] = enable
    bot.save_guild_configs()

    # Update the guild's command tree
    # This requires re-syncing commands for the guild.
    # We need to clear existing commands for the guild and re-add enabled ones.
    
    bot.tree.clear_commands(guild=interaction.guild)
    
    # Add non-manageable core commands
    bot.tree.add_command(config_group, guild=interaction.guild)
    bot.tree.add_command(togglecommand_cmd, guild=interaction.guild) # Add itself back

    # Add all manageable commands that are currently enabled for this guild
    for cmd_key, cmd_data in bot.COMMAND_REGISTRY.items():
        app_cmd_obj = cmd_data.get("app_command_obj")
        if not app_cmd_obj or not cmd_data.get("manageable", True):
            continue

        if guild_config["command_states"].get(cmd_key, True): # If enabled or not in states (default true)
            # Need to correctly add grouped vs. non-grouped commands
            # The app_cmd_obj in COMMAND_REGISTRY should be the actual command object
            # that can be added to the tree.
            bot.tree.add_command(app_cmd_obj, guild=interaction.guild)
            
    try:
        await bot.tree.sync(guild=interaction.guild)
        status_text = "enabled" if enable else "disabled"
        await interaction.response.send_message(f"✅ Command `{command_name}` has been {status_text}. Changes may take a moment to reflect.", ephemeral=True)
        await bot.log_action(interaction.guild, "Command Toggled", f"Command `{command_name}` was {status_text} by {interaction.user.mention}.", mod_user=interaction.user, color=discord.Color.purple())
    except discord.errors.Forbidden:
        await interaction.response.send_message("🚫 I lack permissions to update commands for this server ('application.commands'). State was updated but commands may not reflect change.", ephemeral=True)
        # State is already saved, but sync failed.
    except Exception as e:
        await interaction.response.send_message(f"An error occurred during command sync: {e}", ephemeral=True)

@togglecommand_cmd.autocomplete('command_name')
async def togglecommand_autocomplete(interaction: Interaction, current: str) -> List[Choice[str]]:
    choices = []
    for cmd_key, cmd_data in bot.COMMAND_REGISTRY.items():
        if cmd_data.get("manageable", True): # Only show manageable commands
            if current.lower() in cmd_key.lower():
                choices.append(Choice(name=cmd_key, value=cmd_key))
    return choices[:25] # Discord limit

# --- Bot Events ---
@bot.event
async def on_ready():
    print(fLogged in as {bot.user.name} (ID: {bot.user.id})")
    print(f"discord.py version: {discord.__version__}")
    print(f"ArvoBot is in {len(bot.guilds)} guilds.")
    print("------")
    # The setup_hook handles initial command syncing.
    # If you add commands while bot is running and want to globally refresh,
    # you might need a separate command for tree.sync() without guild arg.
    # For now, setup_hook and togglecommand handle guild-specific syncs.
    print("ArvoBot is ready.")

# --- Run the Bot ---
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("CRITICAL: Bot token not found. Ensure DISCORD_BOT_TOKEN environment variable is set.")
    else:
        try:
            bot.run(BOT_TOKEN)
        except discord.errors.LoginFailure:
            print("CRITICAL: Login failed. The provided bot token is likely invalid or incorrect.")
        except Exception as e:
            print(f"CRITICAL: An unexpected error occurred while trying to run the bot: {e}")

