    # main.py (for Main Arvo Bot - serving arvobot.xyz AND dash.arvobot.xyz)
    import discord
    from discord.ext import commands
    from discord import app_commands 
    import os
    from flask import Flask, render_template, url_for, session, redirect, request 
    from threading import Thread
    import asyncio
    import requests 

    # --- Arvo Bot Information ---
    ARVO_BOT_NAME = "Arvo"
    ARVO_BOT_DESCRIPTION = "Arvo - Smart Staff Management 🦉 Keep your server organized with automated moderation, role management, and staff coordination—all in one reliable bot."

    # --- Configuration (Fetched from Environment Variables) ---
    BOT_TOKEN = os.getenv("DISCORD_TOKEN") 
    FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")
    RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL') 
    
    # OAuth2 Client Credentials (Needed for dashboard login)
    DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
    DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')

    # This is the Client ID of your Arvo Bot application (from Discord Dev Portal -> General Information -> Application ID)
    ARVO_BOT_CLIENT_ID_FOR_INVITE = os.getenv('ARVO_BOT_CLIENT_ID_FOR_INVITE', DISCORD_CLIENT_ID) 

    # --- CONFIGURE THE REDIRECT URI ---
    # Prioritize APP_BASE_URL for constructing the redirect URI if set for custom domain.
    # Fallback to RENDER_EXTERNAL_URL if APP_BASE_URL is not set.
    APP_BASE_URL_CONFIG = os.getenv('APP_BASE_URL', RENDER_EXTERNAL_URL) 
    DISCORD_REDIRECT_URI = None
    if APP_BASE_URL_CONFIG:
        DISCORD_REDIRECT_URI = f"{APP_BASE_URL_CONFIG.rstrip('/')}/callback" # Ensure no double slashes
        print(f"INFO ({ARVO_BOT_NAME}): OAuth2 Redirect URI will be: {DISCORD_REDIRECT_URI}")
    else:
        print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): Neither APP_BASE_URL nor RENDER_EXTERNAL_URL is set. OAuth2 redirect URI cannot be constructed. Dashboard login will fail.")

    API_ENDPOINT = 'https://discord.com/api/v10' 

    if BOT_TOKEN is None:
        print(f"CRITICAL ({ARVO_BOT_NAME}): DISCORD_TOKEN environment variable not set. Bot cannot start.")
        exit()

    # --- Flask App ---
    app = Flask(__name__) 

    if FLASK_SECRET_KEY:
        app.secret_key = FLASK_SECRET_KEY
    else:
        print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): FLASK_SECRET_KEY not set. Flask sessions will be insecure and OAuth may not work reliably.")
        app.secret_key = "temporary_insecure_key_for_arvo_dashboard_fallback_CHANGE_ME"

    # ... (Rest of your Flask routes: / , /privacy-policy, /terms-and-conditions, /keep-alive, 
    #      /login, /callback, /logout, /dashboard, /dashboard/guild/<guild_id_str>
    #      and the SUBMISSION_HTML_TEMPLATE should remain the same as in the version
    #      from immersive ID: arvo_main_bot_website_flask, with the BuildError fix for dashboard_guild) ...
    # For brevity, I'm not re-pasting all of them here, but ensure they are present.
    # The key change is the DISCORD_REDIRECT_URI logic above.

    # --- Example of /login route showing usage of DISCORD_REDIRECT_URI ---
    @app.route('/login')
    def login():
        """Redirects user to Discord for OAuth2 login."""
        if not all([DISCORD_CLIENT_ID, DISCORD_REDIRECT_URI]): # Check if DISCORD_REDIRECT_URI is now properly set
            print("ERROR: OAuth2 misconfiguration in /login. Check DISCORD_CLIENT_ID and ensure APP_BASE_URL or RENDER_EXTERNAL_URL is set for DISCORD_REDIRECT_URI.")
            return "OAuth2 is not configured correctly on the server. Please contact support.", 500
        
        discord_oauth_url = (
            f"{API_ENDPOINT}/oauth2/authorize?client_id={DISCORD_CLIENT_ID}"
            f"&redirect_uri={DISCORD_REDIRECT_URI}" # This will now use your APP_BASE_URL if set
            f"&response_type=code&scope=identify guilds"
        )
        return redirect(discord_oauth_url)

    # --- (Include all other Flask routes and helper functions from previous version) ---
    @app.route('/')
    def index():
        return render_template('index.html', ARVO_BOT_NAME=ARVO_BOT_NAME)

    @app.route('/privacy-policy')
    def privacy_policy():
        return render_template('privacy_policy.html', ARVO_BOT_NAME=ARVO_BOT_NAME)

    @app.route('/terms-and-conditions')
    def terms_and_conditions():
        return render_template('terms_and_conditions.html', ARVO_BOT_NAME=ARVO_BOT_NAME)

    @app.route('/keep-alive') 
    def keep_alive_route():
        return f"{ARVO_BOT_NAME} informational site and dashboard server is alive!", 200

    @app.route('/callback')
    def callback():
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
            'redirect_uri': DISCORD_REDIRECT_URI, # Uses the configured redirect URI
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

            return redirect(url_for('dashboard_servers')) 
        except requests.exceptions.RequestException as e:
            print(f"ERROR: Exception during OAuth2 callback token/user fetch: {e}")
            if hasattr(e, 'response') and e.response is not None: 
                print(f"Discord API Response content: {e.response.text}")
            return "Error during authentication with Discord. Please try again or contact support.", 500

    @app.route('/logout')
    def logout():
        session.pop('discord_oauth_token', None)
        session.pop('discord_user_id', None)
        session.pop('discord_username', None)
        session.pop('discord_avatar', None)
        return redirect(url_for('index')) 

    @app.route('/dashboard') 
    @app.route('/dashboard/servers') 
    def dashboard_servers():
        if 'discord_user_id' not in session or 'discord_oauth_token' not in session:
            return redirect(url_for('login', next=request.url)) 

        access_token = session['discord_oauth_token']['access_token']
        headers = {'Authorization': f'Bearer {access_token}'}
        
        manageable_servers = []
        other_servers_with_bot = []
        user_avatar_url = None

        if session.get('discord_avatar'):
            user_avatar_url = f"https://cdn.discordapp.com/avatars/{session['discord_user_id']}/{session['discord_avatar']}.png"
        session['discord_avatar_url'] = user_avatar_url

        try:
            guilds_response = requests.get(f'{API_ENDPOINT}/users/@me/guilds', headers=headers)
            guilds_response.raise_for_status()
            user_guilds_data = guilds_response.json()

            for guild_data in user_guilds_data:
                guild_id = int(guild_data['id'])
                bot_guild_instance = bot.get_guild(guild_id) 

                if bot_guild_instance: 
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
                if e.response.status_code == 401: 
                    return redirect(url_for('logout')) 
        except Exception as e_bot_check: 
            print(f"Error checking bot's presence in guilds: {e_bot_check}")

        return render_template('dashboard_servers.html', 
                               ARVO_BOT_NAME=ARVO_BOT_NAME,
                               manageable_servers=manageable_servers,
                               other_servers_with_bot=other_servers_with_bot,
                               DISCORD_CLIENT_ID_BOT=ARVO_BOT_CLIENT_ID_FOR_INVITE,
                               session=session 
                               )

    @app.route('/dashboard/guild/<guild_id_str>') 
    def dashboard_guild(guild_id_str: str):
        if 'discord_user_id' not in session:
            return redirect(url_for('login', next=request.url))
        try:
            guild_id = int(guild_id_str)
        except ValueError:
            return "Invalid Guild ID format.", 400
        access_token = session['discord_oauth_token']['access_token']
        headers = {'Authorization': f'Bearer {access_token}'}
        can_manage_this_guild = False
        guild_name_for_dashboard = "Server"
        try:
            guilds_response = requests.get(f'{API_ENDPOINT}/users/@me/guilds', headers=headers)
            guilds_response.raise_for_status()
            user_guilds_list = guilds_response.json()
            for g_data in user_guilds_list:
                if g_data['id'] == guild_id_str: 
                    if discord.Permissions(int(g_data['permissions'])).manage_guild:
                        can_manage_this_guild = True
                        guild_name_for_dashboard = g_data['name']
                    break
        except Exception as e:
            print(f"Error re-fetching guilds for specific dashboard page /dashboard/guild/{guild_id_str}: {e}")
            return redirect(url_for('dashboard_servers')) 
        if not can_manage_this_guild:
            return "You do not have permission to manage this server's Arvo settings, or the server was not found.", 403
        actual_guild_object = bot.get_guild(guild_id)
        if not actual_guild_object:
             return f"{ARVO_BOT_NAME} is not currently in the server '{guild_name_for_dashboard}' (ID: {guild_id}). Cannot display dashboard.", 404
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
        if RENDER_EXTERNAL_URL: print(f"INFO ({ARVO_BOT_NAME}): Website accessible via {RENDER_EXTERNAL_URL}")
        else: print(f"INFO ({ARVO_BOT_NAME}): RENDER_EXTERNAL_URL is not set.")
        if not all([DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, FLASK_SECRET_KEY]):
            print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): Core OAuth/Flask env vars missing. Dashboard login will fail.")
        try:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} application commands for {ARVO_BOT_NAME}.")
        except Exception as e: print(f"Failed to sync commands for {ARVO_BOT_NAME}: {e}")
        print(f'{ARVO_BOT_NAME} is ready and online!')
        await bot.change_presence(activity=discord.Game(name=f"/arvohelp | {ARVO_BOT_NAME}"))

    @bot.tree.command(name="ping", description=f"Check {ARVO_BOT_NAME}'s responsiveness.")
    async def ping(interaction: discord.Interaction):
        latency = bot.latency * 1000 
        await interaction.response.send_message(f"{ARVO_BOT_NAME} Pong! 🏓 Latency: {latency:.2f}ms", ephemeral=True)

    @bot.tree.command(name="arvohelp", description=f"Get information about {ARVO_BOT_NAME}.")
    async def arvohelp(interaction: discord.Interaction):
        embed = discord.Embed(title=f"{ARVO_BOT_NAME} - Smart Staff Management", description=ARVO_BOT_DESCRIPTION, color=discord.Color.blue())
        embed.add_field(name="How to Use", value="Use slash commands (e.g., `/setup`, `/ping`) to interact with me.", inline=False)
        website_url = APP_BASE_URL_CONFIG if APP_BASE_URL_CONFIG else "https://arvobot.xyz" 
        embed.add_field(name="Website", value=f"Visit [{website_url.replace('https://','').replace('http://','')}]( {website_url} ) for more information!", inline=False)
        embed.set_footer(text=f"{ARVO_BOT_NAME} - Your reliable staff management assistant.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="setup", description=f"Configure {ARVO_BOT_NAME} for this server (Admin only).")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup(interaction: discord.Interaction):
        await interaction.response.send_message("Arvo setup panel is under construction! Check back soon.", ephemeral=True)

    async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        error_message_to_user = "An unexpected error occurred."
        if isinstance(error, app_commands.CommandOnCooldown): error_message_to_user = f"Cooldown. Try in {error.retry_after:.2f}s."
        elif isinstance(error, app_commands.CheckFailure): error_message_to_user = "You don't meet requirements."
        print(f"Global slash error for '{interaction.command.name if interaction.command else 'Unknown'}': {type(error).__name__} - {error}")
        response_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        try:
            if not interaction.response.is_done(): await response_method(error_message_to_user, ephemeral=True)
        except: pass 
    bot.tree.on_error = on_app_command_error

    async def main_async():
        async with bot:
            start_keep_alive_server() 
            print(f"Flask web server thread started for {ARVO_BOT_NAME}.")
            print(f"Attempting to connect {ARVO_BOT_NAME} to Discord...")
            await bot.start(BOT_TOKEN)

    if __name__ == "__main__":
        if not APP_BASE_URL_CONFIG: # Check if the primary URL for OAuth is determined
            print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): APP_BASE_URL or RENDER_EXTERNAL_URL env var not set. Dashboard OAuth will likely fail.")
        if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
            print(f"CRITICAL WARNING ({ARVO_BOT_NAME}): DISCORD_CLIENT_ID or DISCORD_CLIENT_SECRET env vars not set. Dashboard login will fail.")
        try:
            asyncio.run(main_async())
        except KeyboardInterrupt: print(f"{ARVO_BOT_NAME} shutting down manually...")
        except Exception as e: print(f"CRITICAL BOT RUN ERROR for {ARVO_BOT_NAME}: {e}")
    
