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

CONFIG_FILE = 'config.json'
required_keys = ['token', 'id', 'secret', 'main_server', 'farm_channel', 'add_bot_channel', 'verify_channel', 'confirm_channel']

# Make the script portable: auto-prompt if config is missing or missing any required keys
config_valid = False
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        if all(k in config for k in required_keys):
            config_valid = True
    except Exception:
        config_valid = False

if not config_valid:
    print("\n⚙️ Config file not found or incomplete! Let's set up your bot parameters for portability:")
    try:
        config = {
            'token': input("Enter Bot Token: ").strip(),
            'id': input("Enter Client ID: ").strip(),
            'secret': input("Enter Client Secret: ").strip(),
            'main_server': int(input("Enter Main Server ID: ").strip()),
            'farm_channel': int(input("Enter Farm Channel ID: ").strip()),
            'add_bot_channel': int(input("Enter Add Bot Channel ID: ").strip()),
            'verify_channel': int(input("Enter Verify Channel ID: ").strip()),
            'confirm_channel': int(input("Enter Confirm Channel ID: ").strip())
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        print("✅ Config created and saved successfully to config.json!\n")
    except Exception as e:
        print(f"❌ Error creating config file: {e}")
        exit(1)

# Load config
try:
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
     
    BOT_TOKEN = config['token']
    CLIENT_ID = config['id']
    CLIENT_SECRET = config['secret']
    MAIN_SERVER = int(config['main_server'])
    FARM_CHANNEL_ID = int(config['farm_channel'])
    ADD_BOT_CHANNEL_ID = int(config['add_bot_channel'])
    VERIFY_CHANNEL_ID = int(config['verify_channel'])
    CONFIRM_CHANNEL_ID = int(config['confirm_channel'])
     
    print(f"✅ Config loaded successfully")
    print(f"🔑 Token: {BOT_TOKEN[:20]}...")
    print(f"🆔 Client ID: {CLIENT_ID}")
    print(f"🏠 Main Server: {MAIN_SERVER}")
     
except Exception as e:
    print(f"❌ Config loading error: {e}")
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
        super().__init__(timeout=60)
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
        
        valid_token = get_valid_token(self.user_id, self.access_token, self.refresh_token)
        if not valid_token:
            await interaction.followup.edit_message(message_id=interaction.message.id, content="❌ Your session token has expired. Please re-authenticate using `*get_token`.", view=None)
            self.value = False
            self.stop()
            return

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
     
    bot.add_view(VerificationView())
     
    try:
        synced = await bot.tree.sync()
        print(f"🌲 Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"❌ Failed to sync slash commands: {e}")
     
    for guild in bot.guilds:
        if guild.id != MAIN_SERVER:
            server_join_times[guild.id] = datetime.now()
            print(f"📝 Tracking server: {guild.name} ({guild.id})")
     
    await check_and_send_add_bot_message()
    await check_and_send_verify_message()

    check_server_ages.start()

@bot.event
async def on_message(message):
    """Handle incoming messages (e.g. telling prefix when pinged)"""
    if message.author.bot:
        return
     
    if bot.user.mentioned_in(message) and not message.mention_everyone:
        await message.channel.send(f"👋 Hello {message.author.mention}! My command prefix is `*`.\nUse `*help` to see available commands.")
     
    await bot.process_commands(message)

async def check_and_send_add_bot_message():
    try:
        main_guild = bot.get_guild(MAIN_SERVER)
        if not main_guild:
            return

        target_channel = main_guild.get_channel(ADD_BOT_CHANNEL_ID)
        if not target_channel:
            return

        async for message in target_channel.history(limit=20):
            if message.author == bot.user and message.embeds:
                for embed in message.embeds:
                    if embed.title and "ADD BOT" in embed.title.upper():
                        return

        invite_url = f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&permissions=8&integration_type=0&scope=applications.commands+bot"
         
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
    try:
        main_guild = bot.get_guild(MAIN_SERVER)
        if not main_guild:
            return

        target_channel = main_guild.get_channel(VERIFY_CHANNEL_ID)
        if not target_channel:
            return

        async for message in target_channel.history(limit=20):
            if message.author == bot.user and message.embeds:
                for embed in message.embeds:
                    if embed.title and ("VERIFY" in embed.title.upper() or "AUTHENTICATION" in embed.title.upper()):
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

@tasks.loop(hours=24)
async def check_server_ages():
    print("🔍 Checking server ages...")
    for guild in bot.guilds:
        if guild.id == MAIN_SERVER:
            continue
         
        guild_id = guild.id
        guild_name = guild.name
         
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

@bot.event
async def on_guild_join(guild):
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
            return None
    except Exception as e:
        return None

def get_valid_token(user_id, access_token, refresh_token):
    headers = {'Authorization': f'Bearer {access_token}'}
    test_response = requests.get('https://discord.com/api/v10/users/@me', headers=headers)
     
    if test_response.status_code == 200:
        return access_token
     
    new_tokens = refresh_access_token(refresh_token)
    if new_tokens:
        update_token_in_file(user_id, new_tokens['access_token'], new_tokens['refresh_token'])
        return new_tokens['access_token']
    else:
        return None

def update_token_in_file(user_id, new_access_token, new_refresh_token):
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
            else:
                new_lines.append(line + '\n')
         
        if updated:
            with open('auths.txt', 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            return True
        return False
    except Exception as e:
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
        embed.add_field(name="🔗 Auth Link", value=f"[**👉 CLICK HERE TO AUTHENTICATE 👈**]({oauth_url})", inline=False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Error generating auth link: {str(e)}")

@bot.hybrid_command(name='auth')
async def authenticate_user(ctx, authorization_code: str):
    """Authenticate user with code"""
    try:
        authorization_code = authorization_code.strip()
        current_user_id = str(ctx.author.id)
        msg = await ctx.send("🔄 Starting authentication...")
         
        token_data = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'authorization_code', 
            'code': authorization_code,
            'redirect_uri': "https://free-members.vercel.app/index.html"
        }
         
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
            except:
                existing_entries = []
         
        cleaned_entries = [line for line in existing_entries if line.strip() and line.strip().split(',')[0] != current_user_id]
        cleaned_entries.append(auth_entry)
         
        with open('auths.txt', 'w', encoding='utf-8') as auth_file:
            auth_file.writelines(cleaned_entries)
         
        success_embed = discord.Embed(
            title="✅ AUTHENTICATION SUCCESSFUL!",
            description=f"**{username}** is now authenticated!",
            color=0x57F287
        )
        await msg.edit(content="", embed=success_embed)
    except Exception as error:
        await ctx.send(f"❌ Error: {str(error)}")

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
            invite_url = f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&permissions=8&integration_type=0&scope=applications.commands+bot"
            embed = discord.Embed(
                title="❌ BOT NOT IN SERVER",
                description=f"Bot is not in server `{target_server_id}`",
                color=0xED4245
            )
            embed.add_field(name="🚨 Solution", value=f"**[Add bot to server first]({invite_url})**", inline=False)
            await ctx.send(embed=embed)
            return
         
        if not os.path.exists('auths.txt'):
            await ctx.send("❌ No users are authenticated yet. Use `*get_token`.")
            return
         
        authenticated_users = []
        with open('auths.txt', 'r', encoding='utf-8') as auth_file:
            for line in auth_file:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(',')
                if len(parts) >= 3:
                    authenticated_users.append({
                        'user_id': parts[0],
                        'access_token': parts[1],
                        'refresh_token': parts[2]
                    })
         
        if not authenticated_users:
            await ctx.send("❌ No valid authenticated users found.")
            return
         
        total_users = len(authenticated_users)
        status_msg = await ctx.send(f"📥 **JOIN CONFIRMATION STARTED**\nSending join request DMs and channel prompts to **{total_users}** users for **{server_name}**...")
         
        confirm_channel = bot.get_channel(CONFIRM_CHANNEL_ID)
        asked_count = 0
        accepted_count = 0

        for user_data in authenticated_users:
            user_id = user_data['user_id']
            access_token = user_data['access_token']
            refresh_token = user_data['refresh_token']
             
            try:
                user_obj = await bot.fetch_user(int(user_id))
                if not user_obj:
                    continue

                embed = discord.Embed(
                    title="📥 Server Join Request",
                    description=f"Hello <@{user_id}>! An admin wants to add you to **{server_name}** (`{target_server_id}`).\n\nDo you want to join this server?",
                    color=0x5865F2
                )
                embed.set_footer(text="This request will expire in 60 seconds.")

                view = JoinConfirmView(target_server_id, server_name, user_id, access_token, refresh_token)
                
                try:
                    await user_obj.send(embed=embed, view=view)
                except Exception:
                    pass

                if confirm_channel:
                    await confirm_channel.send(content=f"<@{user_id}>", embed=embed, view=view)

                asked_count += 1
                await view.wait()
                if view.value is True:
                    accepted_count += 1
            except Exception as e:
                print(f"❌ Error processing user {user_id}: {e}")

            await asyncio.sleep(1)

        final_embed = discord.Embed(
            title="🎯 JOIN REQUEST ROUND COMPLETED",
            description=f"**Server:** {server_name}\n**Total Users Contacted:** {asked_count}/{total_users}",
            color=0x57F287
        )
        final_embed.add_field(name="✅ Accepted & Joined", value=accepted_count, inline=True)
        await status_msg.edit(content="", embed=final_embed)
    except Exception as error:
        await ctx.send(f"❌ Mass join error: {str(error)}")

@bot.hybrid_command(name='mc', aliases=['membercount'])
async def member_count(ctx):
    """Show the current server's member count"""
    try:
        guild = ctx.guild
        if not guild:
            await ctx.send("❌ This command must be used inside a server.")
            return
        
        embed = discord.Embed(
            title="👥 SERVER MEMBER COUNT",
            description=f"**{guild.name}** currently has **{guild.member_count}** members!",
            color=0x5865F2,
            timestamp=datetime.now()
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
            
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Error fetching member count: {e}")

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
         
        with open('auths.txt', 'r', encoding='utf-8') as auth_file:
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
            embed.add_field(name="Token Status", value="\n".join(users[:15]), inline=False)
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
        with open('auths.txt', 'r', encoding='utf-8') as auth_file:
            for line_num, line in enumerate(auth_file, 1):
                line = line.strip()
                if not line:
                    continue
                parts = line.split(',')
                if len(parts) >= 3:
                    user_id = parts[0]
                    users.append(f"`{line_num}.` <@{user_id}>")
         
        if not users:
            await ctx.send("❌ No valid authenticated users found.")
            return
         
        embed = discord.Embed(
            title="📋 AUTHENTICATED USERS",
            description=f"**Total: {len(users)} users**",
            color=0x5865F2
        )
        embed.add_field(name="Users", value="\n".join(users[:20]), inline=False)
        await ctx.send(embed=embed)
    except Exception as error:
        await ctx.send(f"❌ Error listing users: {str(error)}")

@bot.hybrid_command(name='invite')
async def generate_invite(ctx):
    """Generate bot invite link"""
    invite_url = f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&permissions=8&integration_type=0&scope=applications.commands+bot"
    embed = discord.Embed(
        title="🤖 BOT INVITE LINK",
        description=f"**[Click here to invite bot]({invite_url})**",
        color=0x5865F2
    )
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
                age = current_time - server_join_times[guild.id]
                age_days = f"{age.days} days"
            server_list.append(f"`{guild.id}` - **{guild.name}** (Members: {guild.member_count}) - Age: {age_days}")
         
        embed = discord.Embed(
            title="🏠 BOT SERVERS",
            description=f"**Total: {len(bot.guilds)} servers**",
            color=0x5865F2
        )
        embed.add_field(name="Servers", value="\n".join(server_list[:15]), inline=False)
        await ctx.send(embed=embed)
    except Exception as error:
        await ctx.send(f"❌ Error listing servers: {str(error)}")

@bot.hybrid_command(name='help')
async def show_help(ctx):
    """Show all available commands"""
    embed = discord.Embed(title="🤖 BOT COMMANDS - COMPLETE LIST", color=0x5865F2)
    embed.add_field(
        name="🔐 AUTHENTICATION & STATS", 
        value="`*get_token` - Get auth link\n`*auth CODE` - Authenticate with code\n`*check_tokens` - Check tokens\n`*mc` - Check server member count", 
        inline=False
    )
    embed.add_field(
        name="🚀 MASS JOINING & SERVERS", 
        value="`*djoin SERVER_ID` - Ask users to join server\n`*servers` - List bot servers\n`*list_users` - List verified users\n`*invite` - Get bot invite link", 
        inline=False
    )
    await ctx.send(embed=embed)

if __name__ == "__main__":
    bot.run(BOT_TOKEN)