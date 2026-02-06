import discord
from discord import app_commands
from discord.ext import tasks
import os
import asyncio
import random
from datetime import datetime
import csv
import io
from dotenv import load_dotenv
import database as db
import core_logic
import urllib.parse
import aiohttp
import pytz
from deep_translator import GoogleTranslator
from local_brain import LocalBrain

# Load environment variables
load_dotenv()

# Configuration
TOKEN = os.getenv('DISCORD_TOKEN')

# Initialize Local Brain
brain = LocalBrain()

async def create_trip_structure(guild, trip_name):
    """Creates the Discord category and channels for a trip."""
    traveler_role = discord.utils.get(guild.roles, name="Traveler")
    muted_role = discord.utils.get(guild.roles, name="Muted")
    
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        muted_role: discord.PermissionOverwrite(send_messages=False, speak=False) if muted_role else discord.PermissionOverwrite(send_messages=False)
    }
    
    # Create Category
    cat_name = f"✈️ {trip_name.upper()}"
    # Check if category already exists to avoid duplicates
    existing_cat = discord.utils.get(guild.categories, name=cat_name)
    if existing_cat:
        return existing_cat.channels[0].id if existing_cat.channels else None

    category = await guild.create_category(cat_name, overwrites=overwrites)
    
    # Create Channels with Specific Perms
    
    # 1. Chat & Logistics & Activities (Open to all travelers)
    await guild.create_text_channel("chat", category=category)
    await guild.create_text_channel("logistics", category=category)
    await guild.create_text_channel("activities", category=category)
    
    # 2. Itinerary (Read-Only for most, Editable by Planners)
    planner_role = discord.utils.get(guild.roles, name="Core Planner")
    trip_lead = discord.utils.get(guild.roles, name="Trip Lead")
    
    itin_overwrites = overwrites.copy()
    itin_overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=True, send_messages=False) # Read Only
    if planner_role:
        itin_overwrites[planner_role] = discord.PermissionOverwrite(send_messages=True)
    if trip_lead:
        itin_overwrites[trip_lead] = discord.PermissionOverwrite(send_messages=True)
        
    itinerary_channel = await guild.create_text_channel("itinerary", category=category, overwrites=itin_overwrites)
    
    # 3. Budget (Private to Budget Viewers & Admins)
    budget_role = discord.utils.get(guild.roles, name="Budget Viewer")
    
    budget_overwrites = overwrites.copy()
    budget_overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False) # Hidden
    if budget_role:
        budget_overwrites[budget_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
    if trip_lead:
        budget_overwrites[trip_lead] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        
    await guild.create_text_channel("budget", category=category, overwrites=budget_overwrites)
    
    return itinerary_channel.id


def create_dashboard_embed(trip_name, trip_data, expenses_data, itinerary, reminders):
    embed = discord.Embed(title=f"🚀 Mission Control: {trip_name}", color=discord.Color.brand_green())
    
    # 1. Countdown
    try:
        target_date = datetime.strptime(trip_data['date'], "%Y-%m-%d")
        remaining = (target_date - datetime.now()).days + 1
        embed.add_field(name="⏳ Countdown", value=f"**{remaining}** days until {trip_data['date']}", inline=True)
    except:
        embed.add_field(name="⏳ Countdown", value="Invalid Date", inline=True)

    # 2. Budget
    total_spent = sum(float(e['amount']) for e in expenses_data['entries'])
    embed.add_field(name="💰 Total Spent", value=f"${total_spent:.2f}", inline=True)

    # 3. Next Activity
    now = datetime.now()
    next_activity = "None"
    for item in itinerary:
        try:
            start_dt = datetime.fromisoformat(item['start_time'])
            if start_dt > now:
                next_activity = f"**{item['title']}**\n{start_dt.strftime('%a %H:%M')}"
                if item['location']:
                    next_activity += f" @ {item['location']}"
                break
        except:
            pass
            
    embed.add_field(name="📍 Next Activity", value=next_activity, inline=False)

    # 4. Pending Reminders
    if reminders:
        reminder_list = ""
        count = 0
        for r in reminders:
            if count >= 3: 
                reminder_list += f"...and {len(reminders)-3} more"
                break
            try:
                remind_dt = datetime.fromisoformat(r['remind_at'])
                reminder_list += f"• {r['message']} ({remind_dt.strftime('%m-%d %H:%M')})\n"
                count += 1
            except:
                pass
        embed.add_field(name="⏰ Pending Reminders", value=reminder_list if reminder_list else "None", inline=False)
    else:
        embed.add_field(name="⏰ Pending Reminders", value="All clear!", inline=False)

    embed.set_footer(text="Last updated: " + datetime.now().strftime("%H:%M:%S"))
    return embed

class SetupBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.guilds = True
        intents.message_content = True # Needed for /clear check if reading content, though usually not for just delete
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        
        # Print Invite Link
        invite_link = discord.utils.oauth_url(
            self.user.id, 
            permissions=discord.Permissions(administrator=True), 
            scopes=("bot", "applications.commands")
        )
        print(f"\n🔗 Invite Link: {invite_link}&integration_type=0\n")
        
        try:
            # Fast per-guild sync to avoid global propagation delays
            for guild in self.guilds:
                # Copy global commands to guild to make them available immediately
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
            print(f'Commands synced for {len(self.guilds)} guild(s). Ready to deploy.')
        except Exception as e:
            print(f'Command sync failed: {e}')
        
        if not self.keep_alive_task.is_running():
            self.keep_alive_task.start()
            
        if not self.reminder_task.is_running():
            self.reminder_task.start()

        if not self.daily_itinerary_task.is_running():
            self.daily_itinerary_task.start()

        if not self.dashboard_refresh_task.is_running():
            self.dashboard_refresh_task.start()
            
        if not self.dashboard_sync_task.is_running():
            self.dashboard_sync_task.start()

    @tasks.loop(hours=24)
    async def keep_alive_task(self):
        print("🔄 Running keep-alive task...")
        await self.loop.run_in_executor(None, db.keep_alive)

    @keep_alive_task.before_loop
    async def before_keep_alive(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=1)
    async def reminder_task(self):
        try:
            due = await self.loop.run_in_executor(None, db.get_due_reminders)
            if due:
                print(f"⏰ Found {len(due)} due reminders.")
                
            for r in due:
                try:
                    sent = False
                    channel = None
                    user = None
                    
                    # Try to fetch channel
                    if r.get('channel_id'):
                        try:
                            cid = int(r['channel_id'])
                            channel = self.get_channel(cid)
                            if not channel:
                                channel = await self.fetch_channel(cid)
                        except Exception as e:
                            print(f"Failed to fetch channel {r.get('channel_id')}: {e}")
                    
                    # Try to fetch user
                    if r.get('user_id'):
                        try:
                            uid = int(r['user_id'])
                            user = self.get_user(uid)
                            if not user:
                                user = await self.fetch_user(uid)
                        except Exception as e:
                            print(f"Failed to fetch user {r.get('user_id')}: {e}")
                    
                    msg = f"⏰ **REMINDER for {r.get('trip_name', 'Trip')}**:\n{r.get('message', '')}"
                    
                    # Attempt 1: Send to Channel
                    if channel:
                        try:
                            await channel.send(f"{user.mention} {msg}" if user else msg)
                            sent = True
                        except Exception as e:
                            print(f"Failed to send to channel: {e}")
                            
                    # Attempt 2: DM User (fallback)
                    if not sent and user:
                        try:
                            await user.send(msg)
                            sent = True
                        except Exception as e:
                            print(f"Failed to DM user: {e}")
                    
                    # Cleanup
                    if sent:
                        await self.loop.run_in_executor(None, db.delete_reminder, r['id'])
                        print(f"✅ Reminder {r['id']} delivered and deleted.")
                    else:
                        print(f"⚠️ Could not deliver reminder {r['id']}. Channel: {channel}, User: {user}")
                        # We don't delete it immediately so it can retry, 
                        # but we might want a retry limit eventually.
                        
                except Exception as e:
                    print(f"Error processing reminder {r['id']}: {e}")
        except Exception as e:
            print(f"Error in reminder_task loop: {e}")

    @reminder_task.before_loop
    async def before_reminder_task(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=1)
    async def daily_itinerary_task(self):
        now = datetime.now()
        # Pin at 8:00 AM
        if now.hour == 8 and now.minute == 0:
            trips = await self.loop.run_in_executor(None, db.get_all_trips)
            for trip in trips:
                if not trip.get('channel_id'): continue
                
                try:
                    channel_id = int(trip['channel_id'])
                    channel = self.get_channel(channel_id)
                    if not channel:
                        channel = await self.fetch_channel(channel_id)
                except:
                    continue
                
                if not channel: continue
                
                # Get today's items
                all_items = await self.loop.run_in_executor(None, db.get_itinerary, trip['name'])
                today_items = []
                today_str = now.strftime("%Y-%m-%d")
                
                for item in all_items:
                    try:
                        dt = datetime.fromisoformat(item['start_time'])
                        if dt.strftime("%Y-%m-%d") == today_str:
                            today_items.append(item)
                    except:
                        pass
                        
                if today_items:
                    # Create Pin Message
                    embed = discord.Embed(title=f"📅 Today's Plan: {trip['name']}", color=discord.Color.gold())
                    desc = ""
                    for item in today_items:
                         dt = datetime.fromisoformat(item['start_time'])
                         time_str = dt.strftime("%H:%M")
                         loc = f" @ {item['location']}" if item['location'] else ""
                         people = f" ({item['assigned_to']})" if item['assigned_to'] else ""
                         desc += f"`{time_str}` **{item['title']}**{loc}{people}\n"
                    
                    embed.description = desc
                    embed.set_footer(text=f"Have a great day! | {today_str}")
                    
                    try:
                        msg = await channel.send(embed=embed)
                        await msg.pin(reason="Daily Itinerary")
                    except Exception as e:
                        print(f"Failed to pin itinerary for {trip['name']}: {e}")

    @daily_itinerary_task.before_loop
    async def before_daily_itinerary(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=10)
    async def dashboard_refresh_task(self):
        trips = await self.loop.run_in_executor(None, db.get_all_trips)
        for trip in trips:
            if not trip.get('dashboard_message_id') or not trip.get('channel_id'):
                continue
                
            try:
                channel_id = int(trip['channel_id'])
                message_id = int(trip['dashboard_message_id'])
                
                channel = self.get_channel(channel_id)
                if not channel:
                    channel = await self.fetch_channel(channel_id)
                if not channel: continue
                
                try:
                    message = await channel.fetch_message(message_id)
                except discord.NotFound:
                    continue
                except:
                    continue

                # Regenerate Embed
                expenses_data = await self.loop.run_in_executor(None, db.load_expenses, trip['name'])
                itinerary = await self.loop.run_in_executor(None, db.get_itinerary, trip['name'])
                reminders = await self.loop.run_in_executor(None, db.get_reminders, trip['name'])
                
                embed = create_dashboard_embed(trip['name'], trip, expenses_data, itinerary, reminders)
                
                await message.edit(embed=embed)
                
            except Exception as e:
                print(f"Error refreshing dashboard for {trip['name']}: {e}")

    @dashboard_refresh_task.before_loop
    async def before_dashboard_refresh(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=30)
    async def dashboard_sync_task(self):
        # 1. Get all trips
        trips = await self.loop.run_in_executor(None, db.get_all_trips)
        
        if not self.guilds: return
        guild = self.guilds[0] # Assume single server for now
        
        # 2. Check for creations (Trip in DB, no Channel ID)
        for trip in trips:
            if not trip.get('channel_id') or trip.get('channel_id') == "None":
                print(f"🔄 Syncing creation for {trip['name']}...")
                try:
                    chan_id = await create_trip_structure(guild, trip['name'])
                    if chan_id:
                        await self.loop.run_in_executor(None, db.update_trip_channel_id, trip['name'], chan_id)
                        print(f"✅ Synced creation for {trip['name']}")
                except Exception as e:
                    print(f"❌ Failed to sync creation for {trip['name']}: {e}")

        # 3. Check for deletions (Trip Category exists, Trip not in DB)
        trip_names_in_db = [t['name'].upper() for t in trips]
        
        for category in guild.categories:
            if category.name.startswith("✈️ "):
                # Extract name: "✈️ JAPAN 2025" -> "JAPAN 2025"
                cat_trip_name = category.name[3:]
                
                # Check if this name exists in DB (DB names might be mixed case, but we uppercase for comparison)
                found = False
                for t in trips:
                    if t['name'].upper() == cat_trip_name:
                        found = True
                        break
                
                if not found:
                    print(f"🔄 Syncing deletion for {cat_trip_name}...")
                    try:
                        for channel in category.channels:
                            await channel.delete()
                        await category.delete()
                        print(f"✅ Synced deletion for {cat_trip_name}")
                    except Exception as e:
                        print(f"❌ Failed to sync deletion for {cat_trip_name}: {e}")

    @dashboard_sync_task.before_loop
    async def before_dashboard_sync(self):
        await self.wait_until_ready()

    async def on_member_join(self, member):
        welcome_channel_id = 1468276547369697342
        channel = self.get_channel(welcome_channel_id)
        if channel:
            await channel.send(f"👋 Welcome {member.mention} to the **Travel Hub**! 🌍\nGet started by picking your roles with `/selfrole`!")
        else:
            print(f"Could not find welcome channel with ID {welcome_channel_id}")

    async def on_message(self, message):
        # Don't reply to self
        if message.author == self.user:
            return
            
        # Emergency Sync Command (Text-based fallback)
        if message.content.startswith("!sync") and message.author.guild_permissions.administrator:
            args = message.content.split()
            await message.channel.send("🔄 **Processing Sync Request...**")
            
            try:
                if len(args) > 1 and args[1] == "global":
                    # !sync global: Syncs to global (Slow, removes duplicates eventually if guild commands are cleared)
                    await self.tree.sync()
                    await message.channel.send("✅ **Synced Globally!**\n*Note: Global updates can take up to 1 hour to propagate.*")
                
                elif len(args) > 1 and args[1] == "clear":
                    # !sync clear: Removes guild commands (Fixes duplicates, relies on Global)
                    self.tree.clear_commands(guild=message.guild)
                    await self.tree.sync(guild=message.guild)
                    await message.channel.send("🧹 **Cleared Server Commands!**\n*Slash commands will now rely on the Global list (may be slower to update).*")
                
                else:
                    # !sync (default): Copies global to local (Fast, causes duplicates)
                    self.tree.copy_global_to(guild=message.guild)
                    await self.tree.sync(guild=message.guild)
                    await message.channel.send("✅ **Synced to Server!**\n*Commands should appear immediately. If you see duplicates, use `!sync clear` to remove the server-specific copies.*")
            except Exception as e:
                await message.channel.send(f"❌ Sync failed: {e}")
            return

        # Check if user is in an active conversation state with Local Brain
        # We only intervene if they are NOT running a slash command
        if not message.content.startswith("/"):
            user_id = str(message.author.id)
            
            # Check context directly from brain instance
            ctx = brain.context.get(user_id, {})
            state = ctx.get("state", "IDLE")
            
            if state == "PLANNING":
                # Process the message through Local Brain
                response_payload = brain.generate_response(user_id, message.content)
                
                # Unpack response (could be str or dict now)
                response_text = ""
                action = None
                
                if isinstance(response_payload, dict):
                    response_text = response_payload.get("text", "")
                    action = response_payload.get("action")
                    params = response_payload.get("params", {})
                else:
                    response_text = response_payload
                
                if response_text:
                    # 1. Send the text response
                    embed = discord.Embed(description=response_text, color=discord.Color.green())
                    embed.set_footer(text="Local Brain 🧠 (Conversational Mode)")
                    msg = await message.channel.send(embed=embed)
                    
                    # 2. Execute Action if present
                    if action == "create_trip":
                        # Verify Permissions (Safety)
                        if not message.author.guild_permissions.administrator:
                             await message.channel.send("⚠️ **Safety Check:** You need Administrator permissions to auto-create trips.")
                             return
                             
                        trip_name = params.get("trip_name")
                        
                        # Add a Confirmation/Undo View
                        class ConfirmAction(discord.ui.View):
                            def __init__(self):
                                super().__init__(timeout=60)
                                self.value = None

                            @discord.ui.button(label="✅ Confirm & Create", style=discord.ButtonStyle.green)
                            async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
                                if interaction.user.id != message.author.id:
                                    await interaction.response.send_message("❌ Not your session.", ephemeral=True)
                                    return
                                    
                                await interaction.response.send_message(f"🚀 **Executing Autonomous Action:** Creating trip to **{trip_name}**...")
                                
                                # Call the logic from newtrip command
                                # We can't call the slash command directly easily, so we reuse logic or call a helper
                                # For now, we'll invoke a helper method if we extracted one, but let's just do the DB calls here
                                # or better, separate the logic in newtrip.
                                
                                # Replicating newtrip logic for autonomy:
                                guild = message.guild
                                traveler_role = discord.utils.get(guild.roles, name="Traveler")
                                muted_role = discord.utils.get(guild.roles, name="Muted")
                                overwrites = {
                                    guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                                    muted_role: discord.PermissionOverwrite(send_messages=False)
                                }
                                
                                cat_name = f"✈️ {trip_name.upper()}"
                                category = await guild.create_category(cat_name, overwrites=overwrites)
                                await guild.create_text_channel("chat", category=category)
                                await guild.create_text_channel("logistics", category=category)
                                await guild.create_text_channel("itinerary", category=category)
                                await guild.create_text_channel("budget", category=category)
                                await guild.create_text_channel("activities", category=category)
                                
                                db.create_trip(trip_name, "2025-01-01", category.id) # Default date if not parsed
                                
                                await interaction.followup.send(f"✅ **Autonomous Trip Creation Complete!** Check the new category for **{trip_name}**.")
                                self.stop()

                            @discord.ui.button(label="🛑 Cancel", style=discord.ButtonStyle.red)
                            async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                                await interaction.response.send_message("🛑 Action cancelled.", ephemeral=True)
                                self.stop()

                        await message.channel.send("🤖 **Autonomous Action Proposed**", view=ConfirmAction())

client = SetupBot()

# --- HELPERS FOR IDEMPOTENCY ---

async def check_module(interaction: discord.Interaction, module_name: str) -> bool:
    if not interaction.guild: return True
    is_enabled = db.get_module_status(interaction.guild.id, module_name)
    if not is_enabled:
        msg = f"❌ The **{module_name}** module is disabled on this server."
        if interaction.response.is_done():
             await interaction.followup.send(msg, ephemeral=True)
        else:
             await interaction.response.send_message(msg, ephemeral=True)
        return False
    return True

async def check_guest_read_only(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator: return True
    
    user_roles = [r.name for r in interaction.user.roles]
    # If explicitly Guest/Observer and NOT a participant/admin
    if "Guest" in user_roles or "Observer" in user_roles:
        allowed = ["Traveler", "Explorer", "Trip Lead", "Core Planner", "Finance Manager", "Owner", "Co-Owner", "Moderator"]
        if not any(r in allowed for r in user_roles):
             msg = "❌ **Guests/Observers** are in Read-Only mode."
             if interaction.response.is_done():
                 await interaction.followup.send(msg, ephemeral=True)
             else:
                 await interaction.response.send_message(msg, ephemeral=True)
             return False
    return True

async def get_or_create_role(guild, name, color, hoist, permissions, reason):
    # Check if role exists
    for role in guild.roles:
        if role.name == name:
            return role
    
    # Create if not exists
    return await guild.create_role(
        name=name,
        color=color,
        hoist=hoist,
        permissions=permissions,
        reason=reason
    )

async def get_or_create_category(guild, name, position, overwrites):
    for cat in guild.categories:
        if cat.name == name:
            # We update overwrites to ensure compliance
            await cat.edit(position=position, overwrites=overwrites)
            return cat
    
    return await guild.create_category(name, position=position, overwrites=overwrites)

async def get_or_create_text_channel(guild, name, category):
    for channel in category.text_channels:
        if channel.name == name:
            return channel
    return await guild.create_text_channel(name, category=category)

async def get_or_create_voice_channel(guild, name, category):
    for channel in category.voice_channels:
        if channel.name == name:
            return channel
    return await guild.create_voice_channel(name, category=category)


@client.tree.command(name="clear", description="Deletes the bot's own messages in this channel.")
async def clear(interaction: discord.Interaction):
    await interaction.response.send_message("🧹 **Cleaning up my messages...**", ephemeral=True)
    
    deleted_count = 0
    try:
        # Iterate through history and delete own messages
        # We use a limit to prevent infinite loops, e.g., 100 recent messages
        async for message in interaction.channel.history(limit=100):
            if message.author == client.user:
                try:
                    await message.delete()
                    deleted_count += 1
                    await asyncio.sleep(0.5) # Rate limit protection
                except discord.NotFound:
                    pass # Message already deleted
                except Exception as e:
                    print(f"Failed to delete message: {e}")
        
        await interaction.followup.send(f"✅ Deleted {deleted_count} of my own messages.", ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error cleaning up: {e}", ephemeral=True)


@client.tree.command(name="purge", description="Admin: Bulk delete messages in this channel.")
@app_commands.describe(amount="Number of messages to delete (max 100)")
@app_commands.checks.has_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: int):
    if amount > 100:
        await interaction.response.send_message("❌ You can only delete up to 100 messages at a time.", ephemeral=True)
        return
        
    if amount < 1:
        await interaction.response.send_message("❌ Amount must be at least 1.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    
    try:
        # purge returns the list of deleted messages
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🗑️ Deleted **{len(deleted)}** messages.", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ I don't have permission to manage messages.", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.followup.send(f"❌ Failed to purge messages: {e}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ An error occurred: {e}", ephemeral=True)


# --- SELF ROLE VIEWS ---

class SelfRoleSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Traveler", emoji="🌍", description="I love to travel!"),
            discord.SelectOption(label="Explorer", emoji="🗺️", description="Always looking for new places."),
            discord.SelectOption(label="Guest", emoji="👋", description="Just visiting."),
            discord.SelectOption(label="Observer", emoji="👀", description="Watching the chaos."),
            discord.SelectOption(label="Poll Voter", emoji="✅", description="I want to vote on polls."),
            discord.SelectOption(label="Budget Viewer", emoji="💰", description="I want to see budget channels."),
        ]
        super().__init__(placeholder="Choose your roles...", min_values=0, max_values=len(options), options=options)

    async def callback(self, interaction: discord.Interaction):
        # Get all role names from options to know which ones to manage
        possible_role_names = [opt.label for opt in self.options]
        
        # Find actual role objects in the guild
        guild_roles = {r.name: r for r in interaction.guild.roles}
        
        roles_to_add = []
        roles_to_remove = []
        
        selected_names = self.values
        
        for name in possible_role_names:
            role = guild_roles.get(name)
            if not role:
                continue
                
            if name in selected_names:
                if role not in interaction.user.roles:
                    roles_to_add.append(role)
            else:
                if role in interaction.user.roles:
                    roles_to_remove.append(role)
        
        try:
            if roles_to_add:
                await interaction.user.add_roles(*roles_to_add)
            if roles_to_remove:
                await interaction.user.remove_roles(*roles_to_remove)
            
            await interaction.response.send_message(f"✅ **Roles updated!**\nAdded: {', '.join([r.name for r in roles_to_add]) if roles_to_add else 'None'}\nRemoved: {', '.join([r.name for r in roles_to_remove]) if roles_to_remove else 'None'}", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to manage these roles. Please move my 'Bot' role higher than the roles I'm trying to assign.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error updating roles: {e}", ephemeral=True)

class SelfRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SelfRoleSelect())

@client.tree.command(name="trip", description="Manage trips (create, list, archive, etc).")
@app_commands.describe(action="create/list/set-active/archive", name="Trip Name (for create/set/archive)", date="Start Date (YYYY-MM-DD)")
@app_commands.choices(action=[
    app_commands.Choice(name="Create Trip", value="create"),
    app_commands.Choice(name="List Trips", value="list"),
    app_commands.Choice(name="Set Active Trip", value="active"),
    app_commands.Choice(name="Archive Trip", value="archive")
])
async def trip(interaction: discord.Interaction, action: app_commands.Choice[str], name: str = None, date: str = None):
    if action.value == "create":
        # ... logic from old newtrip ...
        # For simplicity, let's redirect them or just copy logic.
        # Since I'm refactoring, let's keep it simple and just do archive for now
        # But wait, user wants new features.
        if not name:
            await interaction.response.send_message("❌ Trip Name required.", ephemeral=True)
            return
            
        # Call the existing newtrip logic (refactored) or just tell them to use /newtrip
        # Better: consolidate. But for now, let's just add the archive logic here
        # and maybe eventually replace /newtrip.
        await interaction.response.send_message("ℹ️ Please use `/newtrip` to create a trip for now.", ephemeral=True)

    elif action.value == "list":
        trips = db.get_all_trips()
        if not trips:
            await interaction.response.send_message("📭 No trips found.", ephemeral=True)
            return
            
        msg = "🌍 **Your Trips:**\n"
        for t in trips:
            msg += f"• **{t['name']}** ({t['date']})\n"
        await interaction.response.send_message(msg, ephemeral=True)

    elif action.value == "active":
        if not name:
            await interaction.response.send_message("❌ Trip Name required.", ephemeral=True)
            return
        
        # Verify it exists
        if not db.get_trip(name):
             await interaction.response.send_message(f"❌ Trip **{name}** does not exist.", ephemeral=True)
             return
             
        db.set_active_trip(interaction.user.id, name)
        await interaction.response.send_message(f"✅ Active trip set to **{name}**.", ephemeral=True)

    elif action.value == "archive":
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return
            
        if not name:
            await interaction.response.send_message("❌ Trip Name required.", ephemeral=True)
            return
            
        trip_data = db.get_trip(name)
        if not trip_data:
            await interaction.response.send_message(f"❌ Trip **{name}** not found.", ephemeral=True)
            return
            
        # Find Category
        category = None
        for cat in interaction.guild.categories:
            if name.lower() in cat.name.lower(): # Fuzzy match
                category = cat
                break
        
        if category:
            await interaction.response.defer()
            new_name = f"💤 ARCHIVED - {name}"
            await category.edit(name=new_name, position=len(interaction.guild.categories))
            
            # Lock channels
            for channel in category.channels:
                await channel.set_permissions(interaction.guild.default_role, send_messages=False)
                
            await interaction.followup.send(f"✅ Trip **{name}** has been archived and locked.")
        else:
            await interaction.response.send_message(f"⚠️ Trip data exists but Discord category for **{name}** not found.", ephemeral=True)

@client.tree.command(name="weather", description="Get weather for a location.")
async def weather(interaction: discord.Interaction, location: str):
    await interaction.response.defer()
    result = await core_logic.cmd_weather(location)
    if result["status"] == "success":
        await interaction.followup.send(f"🌦️ **{result['message']}**:\n{result['data']}")
    else:
        await interaction.followup.send(f"❌ {result['message']}")

@client.tree.command(name="translate", description="Translate text to any language.")
@app_commands.describe(text="Text to translate", target_lang="Target language code (e.g., 'es', 'fr', 'ja')")
async def translate(interaction: discord.Interaction, text: str, target_lang: str):
    await interaction.response.defer()
    result = await core_logic.cmd_translate(text, target_lang)
    
    if result["status"] == "success":
        embed = discord.Embed(color=discord.Color.blue())
        embed.add_field(name="Original", value=result["data"]["original"], inline=False)
        embed.add_field(name=f"Translated ({result['data']['lang']})", value=result["data"]["translated"], inline=False)
        embed.set_footer(text="Powered by deep-translator")
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(f"❌ Translation failed: {result['message']}")

@client.tree.command(name="worldclock", description="Check time in different timezones.")
@app_commands.describe(timezone="Timezone name (e.g., 'Europe/Paris', 'Asia/Tokyo', 'US/Eastern')")
async def worldclock(interaction: discord.Interaction, timezone: str):
    result = await core_logic.cmd_worldclock(timezone)
    
    if result["status"] == "success":
        data = result["data"]
        await interaction.response.send_message(f"🕒 **{data['city']}** ({data['timezone']})\n`{data['time']}`")
    else:
        # Check if it's the specific timezone error for suggestions
        if "Unknown timezone" in result["message"]:
             common = ["Europe/London", "Europe/Paris", "Asia/Tokyo", "America/New_York", "Australia/Sydney", "UTC"]
             suggestions = ", ".join([f"`{c}`" for c in common])
             await interaction.response.send_message(f"❌ {result['message']}\nCommon ones: {suggestions}", ephemeral=True)
        else:
             await interaction.response.send_message(f"❌ Error: {result['message']}", ephemeral=True)


@client.tree.command(name="currency", description="Convert currency amounts.")
@app_commands.describe(amount="Amount to convert", from_currency="From Currency (USD, EUR, etc)", to_currency="To Currency")
async def currency(interaction: discord.Interaction, amount: float, from_currency: str, to_currency: str):
    await interaction.response.defer()
    
    result = await core_logic.cmd_currency(amount, from_currency, to_currency)
    
    if result["status"] == "success":
        data = result["data"]
        await interaction.followup.send(f"💱 **{data['original_amount']:,.2f} {data['from']}** = **{data['converted_amount']:,.2f} {data['to']}**\n*(Rate: 1 {data['from']} = {data['rate']} {data['to']})*")
    else:
        await interaction.followup.send(f"❌ {result['message']}")


@client.tree.command(name="summary", description="Get a statistical summary of a trip.")
async def summary(interaction: discord.Interaction, trip_name: str = None):
    trip_name = await resolve_trip(interaction, trip_name)
    if not trip_name: return
    
    await interaction.response.defer()
    
    # Use Core Logic
    result = core_logic.logic_trip_summary(trip_name)
    
    if result["status"] == "error":
        await interaction.followup.send(f"❌ {result['message']}")
        return

    data = result["data"]
    trip = data["trip"]
    
    # Date calculation (View logic)
    try:
        start_date = datetime.strptime(trip['date'], "%Y-%m-%d")
        delta = (start_date - datetime.now()).days + 1
        time_msg = f"In {delta} days" if delta > 0 else f"{abs(delta)} days ago"
    except:
        time_msg = "Unknown date"

    # Build Embed
    embed = discord.Embed(title=f"📊 Trip Summary: {trip_name}", color=discord.Color.blue())
    embed.add_field(name="📅 Date", value=f"{trip['date']} ({time_msg})", inline=True)
    embed.add_field(name="🎒 Packing List", value=f"{data['packing_count']} items", inline=True)
    embed.add_field(name="💰 Total Budget", value=f"${data['total_spend']:,.2f}", inline=True)
    
    top_spender_text = "None"
    if data['top_spender'] != "None":
        top_spender_text = f"{data['top_spender']} (${data['top_spender_amount']:.2f})"
        
    embed.add_field(name="🏆 Top Spender", value=top_spender_text, inline=True)
    embed.add_field(name="⏰ Reminders", value=f"{data['reminder_count']} pending", inline=True)
    
    await interaction.followup.send(embed=embed)


# --- ADVANCED POLLING ---

class PollButton(discord.ui.Button):
    def __init__(self, label, index):
        super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id=f"poll_btn_{index}")
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view: PollPlusView = self.view
        user = interaction.user
        
        # Weight Logic: Admin = 2, Others = 1
        weight = 2 if user.guild_permissions.administrator else 1
        
        # Record Vote via Core Logic
        result = core_logic.logic_poll("vote", trip_name=None, poll_id=view.poll_id, user_id=user.id, option_index=self.index, weight=weight)
        
        if result["status"] == "success":
            data = result["data"]
        else:
            print(f"Vote failed: {result['message']}")
            data = {}

        results = data.get('results', {})
        total_votes = data.get('total', 0)
        
        # Update Embed
        embed = interaction.message.embeds[0]
        description = ""
        
        # Calculate max for bar graph
        max_val = max(results.values()) if results else 0
        
        for i, opt in enumerate(view.options):
            score = results.get(str(i), 0) # JSON keys are strings
            if score == 0 and i in results: score = results[i] # int keys?

            # Simple bar
            bar = "█" * int((score / max_val * 10) if max_val > 0 else 0)
            description += f"**{opt}**: {score} \n`{bar}`\n\n"
            
        embed.description = description
        embed.set_footer(text=f"Total Votes: {total_votes} | Auto-closes in {view.timeout_min} min")
        
        await interaction.response.edit_message(embed=embed)

class PollPlusView(discord.ui.View):
    def __init__(self, poll_id, options, timeout_min):
        super().__init__(timeout=timeout_min * 60)
        self.poll_id = poll_id
        self.options = options
        self.timeout_min = timeout_min
        self.message = None
        
        for i, opt in enumerate(options):
            self.add_item(PollButton(label=opt, index=i))

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        
        if self.message:
            embed = self.message.embeds[0]
            embed.title = f"🛑 [CLOSED] {embed.title}"
            embed.color = discord.Color.greyple()
            await self.message.edit(view=self, embed=embed)
            await self.message.reply("📊 **Poll Closed!** Check the final results above.")

@client.tree.command(name="poll_plus", description="Advanced Polling (Anonymous, Weighted).")
@app_commands.describe(question="The question", options="Comma-separated options", duration="Duration in minutes (default 60)", trip_name="Trip Name")
async def poll_plus(interaction: discord.Interaction, question: str, options: str, duration: int = 60, trip_name: str = None):
    if not await check_module(interaction, "polls"): return
    if not await check_guest_read_only(interaction): return
    trip_name = await resolve_trip(interaction, trip_name)
    if not trip_name: return

    option_list = [opt.strip() for opt in options.split(",") if opt.strip()]
    
    if len(option_list) < 2:
        await interaction.response.send_message("❌ Need at least 2 options.", ephemeral=True)
        return
    if len(option_list) > 5:
        await interaction.response.send_message("❌ Max 5 options for Poll+ (Discord Button Limit per row).", ephemeral=True)
        return

    # Create in DB
    expires_at = datetime.now() + datetime.timedelta(minutes=duration)
    result = core_logic.logic_poll("create", trip_name, question=question, options=option_list, creator_id=interaction.user.id, expires_at=expires_at)
    
    if result["status"] == "success":
        poll = result["data"]
    else:
        await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)
        return

    embed = discord.Embed(title=f"📊 {question}", description="Vote below! (Admins = 2x weight)", color=discord.Color.gold())
    for opt in option_list:
        embed.description += f"**{opt}**: 0\n\n"
        
    view = PollPlusView(poll['id'], option_list, duration)
    
    await interaction.response.send_message(embed=embed, view=view)
    view.message = await interaction.original_response()
    
    db.update_poll_message(poll['id'], interaction.channel.id, view.message.id)

@client.tree.command(name="setup", description="Sets up the Trip Planning server structure (Idempotent).")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    """
    Sets up the server structure for Trip Planning.
    """
    await interaction.response.send_message("🚀 **Starting Trip Planning Server Setup...**", ephemeral=False)
    status_msg = await interaction.channel.send("⏳ **Phase 1:** Configuring Roles...")
    
    guild = interaction.guild
    
    # ---------------------------------------------------------
    # 1. ROLES CONFIGURATION
    # ---------------------------------------------------------
    
    # Governance Roles
    roles_governance = [
        {"name": "Owner", "color": discord.Color.gold(), "hoist": True, "permissions": discord.Permissions(administrator=True)},
        {"name": "Co-Owner", "color": discord.Color.dark_gold(), "hoist": True, "permissions": discord.Permissions(manage_guild=True, manage_roles=True, manage_channels=True, kick_members=True, ban_members=True)},
        {"name": "Trip Lead", "color": discord.Color.blue(), "hoist": True, "permissions": discord.Permissions(manage_channels=True, manage_messages=True, mute_members=True)},
        {"name": "Core Planner", "color": discord.Color.teal(), "hoist": True, "permissions": discord.Permissions(manage_threads=True, manage_messages=True)}, # Can pin via manage_messages
        {"name": "Finance Manager", "color": discord.Color.green(), "hoist": True, "permissions": discord.Permissions(manage_messages=True)},
        {"name": "Moderator", "color": discord.Color.red(), "hoist": True, "permissions": discord.Permissions(kick_members=True, moderate_members=True, manage_messages=True)},
    ]
    
    # Participation Roles
    roles_participation = [
        {"name": "Traveler", "color": discord.Color.green(), "hoist": True, "permissions": discord.Permissions(send_messages=True, connect=True, attach_files=True, embed_links=True, use_external_emojis=True)},
        {"name": "Explorer", "color": discord.Color.orange(), "hoist": False, "permissions": discord.Permissions(send_messages=True, connect=True, attach_files=True, embed_links=True, use_external_emojis=True)},
        {"name": "Guest", "color": discord.Color.light_grey(), "hoist": False, "permissions": discord.Permissions(send_messages=True, connect=True, attach_files=True, embed_links=True)},
        {"name": "Observer", "color": discord.Color.default(), "hoist": False, "permissions": discord.Permissions(read_messages=True, send_messages=False, add_reactions=True)}, 
    ]
    
    # Utility Roles
    roles_utility = [
        {"name": "Poll Voter", "color": discord.Color.blue(), "hoist": False, "permissions": discord.Permissions()},
        {"name": "Budget Viewer", "color": discord.Color.dark_green(), "hoist": False, "permissions": discord.Permissions()},
        {"name": "Muted", "color": discord.Color.dark_gray(), "hoist": False, "permissions": discord.Permissions(send_messages=False, speak=False)},
        {"name": "Bot", "color": discord.Color.purple(), "hoist": True, "permissions": discord.Permissions.all()},
    ]

    all_roles_config = roles_governance + roles_participation + roles_utility
    role_objects = {}

    for role_data in all_roles_config:
        role = await get_or_create_role(
            guild, 
            role_data["name"], 
            role_data["color"], 
            role_data["hoist"], 
            role_data["permissions"],
            "Trip Planner Setup"
        )
        role_objects[role_data["name"]] = role
        await asyncio.sleep(0.1) # Avoid rate limits

    # Assign Bot role to self if not present
    if "Bot" in role_objects:
        try:
            if role_objects["Bot"] not in guild.me.roles:
                await guild.me.add_roles(role_objects["Bot"])
        except Exception as e:
            print(f"Failed to assign Bot role: {e}")

    await status_msg.edit(content="✅ Roles Configured. \n⏳ **Phase 2:** configuring Permissions & Categories...")

    # ---------------------------------------------------------
    # 2. PERMISSION OVERWRITES
    # ---------------------------------------------------------
    
    # Helper to get role safely
    def r(name):
        return role_objects.get(name, guild.default_role)

    everyone = guild.default_role
    
    # Base Overwrites
    
    # Muted (Global Override ideally, but applied per category here)
    muted_overwrite = discord.PermissionOverwrite(send_messages=False, speak=False, add_reactions=False)
    
    # INFORMATION: Read-only for most, Writable by Governance
    perms_info = {
        everyone: discord.PermissionOverwrite(view_channel=True, send_messages=False),
        r("Observer"): discord.PermissionOverwrite(view_channel=True, send_messages=False),
        r("Trip Lead"): discord.PermissionOverwrite(send_messages=True),
        r("Core Planner"): discord.PermissionOverwrite(send_messages=True),
        r("Moderator"): discord.PermissionOverwrite(send_messages=True),
        r("Muted"): muted_overwrite
    }

    # PLANNING HUB: Writable by everyone (Hub concept)
    perms_hub = {
        everyone: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        r("Muted"): muted_overwrite
    }

    # SOCIAL: Open chat
    perms_social = {
        everyone: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        r("Observer"): discord.PermissionOverwrite(view_channel=True, send_messages=False), # Observer must NOT send messages
        r("Muted"): muted_overwrite
    }

    # FINANCE: Restricted
    perms_finance = {
        everyone: discord.PermissionOverwrite(view_channel=False), # Hidden
        r("Finance Manager"): discord.PermissionOverwrite(view_channel=True, send_messages=True),
        r("Trip Lead"): discord.PermissionOverwrite(view_channel=True, send_messages=True),
        r("Core Planner"): discord.PermissionOverwrite(view_channel=True, send_messages=False), # Read-only for planners?
        r("Budget Viewer"): discord.PermissionOverwrite(view_channel=True, send_messages=False), # Read-only for assigned viewers
        r("Muted"): muted_overwrite
    }

    # ---------------------------------------------------------
    # 3. CATEGORIES & CHANNELS
    # ---------------------------------------------------------
    
    # 📢 HUB INFORMATION
    cat_info = await get_or_create_category(guild, "📢 HUB INFORMATION", 0, perms_info)
    await get_or_create_text_channel(guild, "welcome", cat_info)
    await get_or_create_text_channel(guild, "hub-rules", cat_info)
    await get_or_create_text_channel(guild, "announcements", cat_info)

    # 💰 FINANCE & BUDGET
    cat_finance = await get_or_create_category(guild, "💰 FINANCE & BUDGET", 1, perms_finance)
    await get_or_create_text_channel(guild, "budget-planning", cat_finance)
    await get_or_create_text_channel(guild, "expense-log", cat_finance)

    # 🌍 TRAVEL LOUNGE
    cat_lounge = await get_or_create_category(guild, "🌍 TRAVEL LOUNGE", 2, perms_hub)
    await get_or_create_text_channel(guild, "general-chat", cat_lounge)
    await get_or_create_text_channel(guild, "trip-ideas", cat_lounge)
    await get_or_create_text_channel(guild, "bucket-list", cat_lounge)
    await get_or_create_text_channel(guild, "travel-hacks", cat_lounge)
    await get_or_create_text_channel(guild, "food-and-drink", cat_lounge)

    # 📸 MEMORIES
    cat_memories = await get_or_create_category(guild, "📸 MEMORIES", 2, perms_social)
    await get_or_create_text_channel(guild, "photo-dump", cat_memories)
    await get_or_create_text_channel(guild, "past-trips", cat_memories)

    # 🔊 VOICE
    # Voice perms: similar to Social
    perms_voice = {
        everyone: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True),
        r("Muted"): discord.PermissionOverwrite(speak=False),
        r("Observer"): discord.PermissionOverwrite(connect=True, speak=False) # Observer can listen? Usually yes.
    }
    cat_voice = await get_or_create_category(guild, "🔊 VOICE", 3, perms_voice)
    await get_or_create_voice_channel(guild, "Lounge", cat_voice)
    await get_or_create_voice_channel(guild, "Gaming", cat_voice)
    await get_or_create_voice_channel(guild, "Music", cat_voice)

    # Final Message
    await status_msg.edit(content="✅ **Setup Complete!** \n\nTrip Planning Hub Template applied successfully.")
    if not interaction.response.is_done():
         await interaction.followup.send("🎉 **Hub Setup Complete!** Use `/newtrip` to start planning a specific adventure.")
    else:
         await interaction.channel.send("🎉 **Hub Setup Complete!** Use `/newtrip` to start planning a specific adventure.")

@client.tree.command(name="newtrip", description="Creates channels for a new trip.")
@app_commands.describe(trip_name="The name of the trip (e.g., 'Japan 2025')", date="Start date YYYY-MM-DD (optional)")
@app_commands.checks.has_permissions(administrator=True)
async def newtrip(interaction: discord.Interaction, trip_name: str, date: str = None):
    await interaction.response.send_message(f"🚀 **Creating Trip: {trip_name}...**")
    guild = interaction.guild
    
    # 1. Create Structure
    itinerary_channel_id = await create_trip_structure(guild, trip_name)
    
    if not itinerary_channel_id:
        await interaction.followup.send(f"⚠️ Category for **{trip_name}** likely already exists.")
        return

    # 2. Register in DB
    result = core_logic.logic_trip("create", trip_name, date=date, itinerary_channel_id=itinerary_channel_id)
    
    if result["status"] == "success":
        db_msg = f"\n• ℹ️ {result['message']}"
    else:
        db_msg = f"\n• ⚠️ DB Error: {result['message']}"

    await interaction.followup.send(f"✅ **Trip '{trip_name}' Created!**\n• 🔒 `budget` restricted to Budget Viewers.\n• 🔒 `itinerary` read-only for guests.{db_msg}")

@client.tree.command(name="poll", description="Creates a poll for the group to vote on.")
@app_commands.describe(question="The question to ask", options="Comma-separated options (e.g., Japan, Italy, Spain)", trip_name="Trip Name")
async def poll(interaction: discord.Interaction, question: str, options: str, trip_name: str = None):
    if not await check_module(interaction, "polls"): return
    
    trip_name = await resolve_trip(interaction, trip_name)
    if not trip_name: return

    option_list = [opt.strip() for opt in options.split(",") if opt.strip()]
    
    if len(option_list) < 2:
        await interaction.response.send_message("❌ You need at least 2 options for a poll!", ephemeral=True)
        return
    if len(option_list) > 5:
        await interaction.response.send_message("❌ Maximum 5 options allowed (Discord Button Limit)!", ephemeral=True)
        return
        
    # Default 24h duration
    expires_at = datetime.now() + datetime.timedelta(hours=24)
    
    result = core_logic.logic_poll("create", trip_name, question=question, options=option_list, creator_id=interaction.user.id, expires_at=expires_at)
    
    if result["status"] == "success":
        poll = result["data"]
        embed = discord.Embed(title=f"📊 {question}", description="Vote below!", color=discord.Color.blue())
        for opt in option_list:
            embed.description += f"**{opt}**: 0\n\n"
        
        # Use PollPlusView (reusing the advanced view for consistency)
        view = PollPlusView(poll['id'], option_list, 1440)
        
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()
        
        db.update_poll_message(poll['id'], interaction.channel.id, view.message.id)
    else:
        await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)

@client.tree.command(name="decide", description="Can't decide? Let the bot pick for you!")
@app_commands.describe(options="Comma-separated options (e.g., Sushi, Pizza, Tacos)")
async def decide(interaction: discord.Interaction, options: str):
    choices = [opt.strip() for opt in options.split(",") if opt.strip()]
    
    result = core_logic.logic_decide(choices)
    
    if result["status"] == "success":
        await interaction.response.send_message(f"🎲 {result['message']} 🎉")
    else:
        await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)

# Old trip command removed to avoid duplication
# Helper to resolve trip name
async def resolve_trip(interaction, trip_name_arg):
    if trip_name_arg:
        return trip_name_arg
    
    active = db.get_active_trip(interaction.user.id)
    if active:
        return active
    
    msg = "❌ No trip specified and no active trip set. Please specify a trip or use `/trip set-active`."
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)
    return None

@client.tree.command(name="countdown", description="Manage trip countdowns.")
@app_commands.describe(action="set/show/list/delete", trip_name="Name of the trip (optional if active)", date="YYYY-MM-DD")
@app_commands.choices(action=[
    app_commands.Choice(name="Set Date", value="set"),
    app_commands.Choice(name="Show Countdown", value="show"),
    app_commands.Choice(name="List All", value="list"),
    app_commands.Choice(name="Delete", value="delete")
])
async def countdown(interaction: discord.Interaction, action: app_commands.Choice[str], trip_name: str = None, date: str = None):
    if not await check_module(interaction, "itinerary"): return
    
    # Resolve trip name for non-list actions
    if action.value != "list":
        trip_name = await resolve_trip(interaction, trip_name)
        if not trip_name: return

    if action.value == "list":
        result = core_logic.logic_trip("list")
        if result["status"] == "success":
            trips = result["data"]
            if not trips:
                await interaction.response.send_message("📭 No countdowns set yet.", ephemeral=True)
                return
            
            msg = "📅 **Upcoming Trips:**\n"
            for t in trips:
                 rem = f"({t['days_left']} days left)" if t.get('days_left') is not None else ""
                 msg += f"• **{t['name']}**: {t['date']} {rem}\n"
            await interaction.response.send_message(msg)
        else:
            await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)

    elif action.value == "set":
        if not date:
            await interaction.response.send_message("❌ You must provide a date (YYYY-MM-DD).", ephemeral=True)
            return
            
        result = core_logic.logic_trip("set", trip_name, date=date)
        if result["status"] == "success":
             await interaction.response.send_message(f"✅ {result['message']}")
        else:
             await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)

    elif action.value == "show":
        result = core_logic.logic_trip("show", trip_name)
        if result["status"] == "success":
            trip = result["data"]
            days = trip.get("days_left")
            if days is not None:
                await interaction.response.send_message(f"⏳ **{trip['name']}** is in **{days} days**! ({trip['date']})")
            else:
                await interaction.response.send_message(f"📅 **{trip['name']}** is set for {trip['date']} (no countdown).")
        else:
            await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)

    elif action.value == "delete":
        result = core_logic.logic_trip("delete", trip_name)
        if result["status"] == "success":
             await interaction.response.send_message(f"🗑️ {result['message']}")
        else:
             await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)

@client.tree.command(name="packing", description="Manage packing lists for trips.")
@app_commands.describe(action="add/remove/list/claim/template", trip_name="Name of the trip (optional if active)", item="Item name or Template Name (beach, ski, etc)")
@app_commands.choices(action=[
    app_commands.Choice(name="Add Item", value="add"),
    app_commands.Choice(name="Remove Item", value="remove"),
    app_commands.Choice(name="List Items", value="list"),
    app_commands.Choice(name="Claim Item", value="claim"),
    app_commands.Choice(name="Apply Template", value="template")
])
async def packing(interaction: discord.Interaction, action: app_commands.Choice[str], item: str = None, trip_name: str = None):
    if not await check_module(interaction, "packing"): return
    trip_name = await resolve_trip(interaction, trip_name)
    if not trip_name: return

    if action.value in ["add", "remove", "claim", "template"] and not await check_guest_read_only(interaction): return

    if action.value == "template":
        template_name = item if item else "generic"
        
        await interaction.response.defer()
        result = core_logic.logic_packing_template(trip_name, template_name)
        
        if result["status"] == "success":
            await interaction.followup.send(f"✅ {result['message']}")
        else:
            await interaction.followup.send(f"❌ {result['message']}")

    elif action.value == "add":
        result = core_logic.logic_packing("add", trip_name, item=item)
        if result["status"] == "success":
            await interaction.response.send_message(f"✅ {result['message']}")
        else:
            await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)

    elif action.value == "remove":
        result = core_logic.logic_packing("remove", trip_name, item=item)
        if result["status"] == "success":
            await interaction.response.send_message(f"🗑️ {result['message']}")
        else:
            await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)

    elif action.value == "list":
        result = core_logic.logic_packing("list", trip_name)
        if result["status"] == "error":
             await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)
             return

        items = result["data"]
        if not items:
            await interaction.response.send_message(f"📭 Packing list for **{trip_name}** is empty.", ephemeral=True)
            return
            
        msg = f"🎒 **Packing List for {trip_name}:**\n"
        for i in items:
            status = "✅" if i["claimed_by"] else "⬜"
            claimer = f" (Claimed by {i['claimed_by']})" if i["claimed_by"] else ""
            msg += f"{status} **{i['item']}**{claimer}\n"
            
        await interaction.response.send_message(msg)

    elif action.value == "claim":
        result = core_logic.logic_packing("claim", trip_name, item=item, user=interaction.user.display_name)
        if result["status"] == "success":
            await interaction.response.send_message(f"✅ {result['message']}")
        else:
            await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)

@client.tree.command(name="expense", description="Track shared expenses.")
@app_commands.describe(action="log/view/summary/settle/export", trip_name="Name of the trip (optional if active)", amount="Amount spent", description="What was it for?")
@app_commands.choices(action=[
    app_commands.Choice(name="Log Expense", value="log"),
    app_commands.Choice(name="View Log", value="view"),
    app_commands.Choice(name="Summary", value="summary"),
    app_commands.Choice(name="Settle Up", value="settle"),
    app_commands.Choice(name="Export CSV", value="export")
])
async def expense(interaction: discord.Interaction, action: app_commands.Choice[str], amount: float = None, description: str = None, trip_name: str = None):
    if not await check_module(interaction, "expenses"): return
    trip_name = await resolve_trip(interaction, trip_name)
    if not trip_name: return
    
    if action.value in ["log", "settle"] and not await check_guest_read_only(interaction): return
    
    if action.value == "log":
        result = core_logic.logic_expense("log", trip_name, amount=amount, description=description, payer=interaction.user.display_name)
        if result["status"] == "success":
            await interaction.response.send_message(f"✅ {result['message']}")
        else:
            await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)

    elif action.value == "view":
        result = core_logic.logic_expense("view", trip_name)
        if result["status"] == "error":
             await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)
             return
             
        expenses_data = result["data"]
        if not expenses_data["entries"]:
            await interaction.response.send_message(f"📭 No expenses logged for **{trip_name}**.", ephemeral=True)
            return
            
        msg = f"💸 **Expenses for {trip_name}:**\n"
        for e in expenses_data["entries"]:
            msg += f"• **${e['amount']}** - {e['description']} (by {e['payer']}) on {e['date']}\n"
            
        await interaction.response.send_message(msg)

    elif action.value == "summary":
        result = core_logic.logic_expense("summary", trip_name)
        if result["status"] == "error":
             await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)
             return
             
        data = result["data"]
        if data["total"] == 0:
            await interaction.response.send_message(f"📭 No expenses to summarize for **{trip_name}**.", ephemeral=True)
            return
            
        msg = f"💰 **Expense Summary for {trip_name}:**\n"
        msg += f"**Total Spent:** ${data['total']:.2f}\n\n"
        msg += "**Breakdown by Payer:**\n"
        
        for user, amt in data['breakdown'].items():
            msg += f"• {user}: ${amt:.2f}\n"
            
        await interaction.response.send_message(msg)

    elif action.value == "settle":
        result = core_logic.logic_expense_settle(trip_name)
        
        if result["status"] == "error":
             await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)
             return

        data = result["data"]
        
        embed = discord.Embed(title=f"⚖️ Settlement: {trip_name}", color=discord.Color.gold())
        embed.add_field(name="Total Trip Cost", value=f"${data['total']:.2f}", inline=True)
        embed.add_field(name="Cost Per Person", value=f"${data['per_person']:.2f}", inline=True)
        embed.add_field(name="Participants", value=", ".join(data['participants']), inline=False)
        
        if data['plan']:
            plan_lines = []
            for p in data['plan']:
                 plan_lines.append(f"• **{p['from']}** pays **{p['to']}**: ${p['amount']:.2f}")
            embed.add_field(name="💸 Payments Needed", value="\n".join(plan_lines), inline=False)
        else:
            embed.add_field(name="✅ All Settled", value="No payments needed!", inline=False)
            
        await interaction.response.send_message(embed=embed)

    elif action.value == "export":
        result = core_logic.logic_expense("view", trip_name)
        if result["status"] == "error":
             await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)
             return
             
        expenses_data = result["data"]
        if not expenses_data["entries"]:
            await interaction.response.send_message(f"📭 No expenses to export for **{trip_name}**.", ephemeral=True)
            return
            
        # Create CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Date", "Payer", "Amount", "Description"])
        
        for e in expenses_data["entries"]:
            writer.writerow([e['date'], e['payer'], e['amount'], e['description']])
            
        output.seek(0)
        file = discord.File(fp=io.BytesIO(output.getvalue().encode()), filename=f"{trip_name}_expenses.csv")
        
        await interaction.response.send_message(f"📊 Expense Report for **{trip_name}**", file=file)

@client.tree.command(name="itinerary", description="Manage trip itinerary.")
@app_commands.describe(
    action="add/view/delete", 
    trip_name="Name of the trip (optional if active)", 
    title="Event title", 
    start_time="YYYY-MM-DD HH:MM", 
    end_time="YYYY-MM-DD HH:MM (optional)", 
    location="Location (optional)", 
    notes="Notes (optional)", 
    assigned_to="Who is responsible? (optional)",
    item_id="ID of item to delete (for delete action)"
)
@app_commands.choices(action=[
    app_commands.Choice(name="Add Event", value="add"),
    app_commands.Choice(name="View Itinerary", value="view"),
    app_commands.Choice(name="Delete Event", value="delete")
])
async def itinerary(
    interaction: discord.Interaction, 
    action: app_commands.Choice[str], 
    title: str = None, 
    start_time: str = None, 
    end_time: str = None, 
    location: str = None, 
    notes: str = None, 
    assigned_to: str = None,
    item_id: int = None,
    trip_name: str = None
):
    if not await check_module(interaction, "itinerary"): return
    trip_name = await resolve_trip(interaction, trip_name)
    if not trip_name: return

    # Permission Check for Edits
    if action.value in ["add", "delete"]:
        has_perm = interaction.user.guild_permissions.administrator
        if not has_perm:
            for role in interaction.user.roles:
                if role.name in ["Core Planner", "Trip Lead"]:
                    has_perm = True
                    break
        
        if not has_perm:
            await interaction.response.send_message("❌ Only **Core Planners** and **Trip Leads** can edit the itinerary.", ephemeral=True)
            return

    if action.value == "add":
        await interaction.response.defer()
        result = core_logic.logic_itinerary(
            "add", trip_name, 
            title=title, start_time=start_time, end_time=end_time, 
            location=location, notes=notes, assigned_to=assigned_to
        )
        
        if result["status"] == "success":
            await interaction.followup.send(f"✅ {result['message']}")
        else:
            await interaction.followup.send(f"❌ {result['message']}")

    elif action.value == "view":
        await interaction.response.defer()
        result = core_logic.logic_itinerary("view", trip_name)
        
        if result["status"] == "error":
            await interaction.followup.send(f"❌ {result['message']}")
            return

        items = result["data"]
        if not items:
            await interaction.followup.send(f"📭 Itinerary for **{trip_name}** is empty.", ephemeral=True)
            return
            
        embed = discord.Embed(title=f"🗺️ Itinerary: {trip_name}", color=discord.Color.blue())
        
        # Group by Date
        by_date = {}
        for item in items:
            try:
                dt = datetime.fromisoformat(item['start_time'])
                date_str = dt.strftime("%Y-%m-%d (%A)")
                if date_str not in by_date:
                    by_date[date_str] = []
                by_date[date_str].append((dt, item))
            except Exception as e:
                print(f"Error parsing date for item {item}: {e}")
            
        for date_str, daily_items in by_date.items():
            desc = ""
            for dt, item in daily_items:
                time_str = dt.strftime("%H:%M")
                # Google Maps Link
                loc = ""
                if item['location']:
                    query = item['location'].replace(' ', '+')
                    loc = f" @ [{item['location']}](https://www.google.com/maps/search/?api=1&query={query})"
                
                people = f" ({item['assigned_to']})" if item['assigned_to'] else ""
                desc += f"`{time_str}` **{item['title']}**{loc}{people} [ID:{item['id']}]\n"
            
            embed.add_field(name=date_str, value=desc, inline=False)
            
        await interaction.followup.send(embed=embed)

    elif action.value == "delete":
        await interaction.response.defer()
        result = core_logic.logic_itinerary("delete", trip_name, item_id=item_id)
        
        if result["status"] == "success":
            await interaction.followup.send(f"🗑️ {result['message']}")
        else:
            await interaction.followup.send(f"❌ {result['message']}")

@client.tree.command(name="remind", description="Set reminders for trips.")
@app_commands.describe(
    action="add/delete/list", 
    trip_name="Name of the trip (optional if active)", 
    message="Reminder message", 
    time="YYYY-MM-DD HH:MM", 
    target="Who to remind? (User, defaults to you)",
    reminder_id="ID of reminder to delete"
)
@app_commands.choices(action=[
    app_commands.Choice(name="Add Reminder", value="add"),
    app_commands.Choice(name="List Reminders", value="list"),
    app_commands.Choice(name="Delete Reminder", value="delete")
])
async def remind(
    interaction: discord.Interaction, 
    action: app_commands.Choice[str], 
    message: str = None, 
    time: str = None, 
    target: discord.User = None, 
    reminder_id: int = None,
    trip_name: str = None
):
    await interaction.response.defer(ephemeral=True)
    if not await check_module(interaction, "reminders"): return
    trip_name = await resolve_trip(interaction, trip_name)
    if not trip_name: return

    if action.value == "add":
        user_id = target.id if target else interaction.user.id
        channel_id = interaction.channel.id
        
        result = core_logic.logic_reminders(
            "add", trip_name, 
            message=message, remind_at=time, 
            user_id=user_id, channel_id=channel_id
        )
        
        if result["status"] == "success":
            await interaction.followup.send(f"✅ {result['message']}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ {result['message']}", ephemeral=True)

    elif action.value == "list":
        result = core_logic.logic_reminders("list", trip_name)
        
        if result["status"] == "error":
            await interaction.followup.send(f"❌ {result['message']}", ephemeral=True)
            return
            
        reminders = result["data"]
        if not reminders:
            await interaction.followup.send(f"📭 No reminders set for **{trip_name}**.", ephemeral=True)
            return
            
        msg = f"⏰ **Reminders for {trip_name}:**\n"
        for r in reminders:
            try:
                dt = datetime.fromisoformat(r['remind_at'])
                msg += f"• **ID {r['id']}**: {r['message']} ({dt.strftime('%Y-%m-%d %H:%M')})\n"
            except:
                pass
                
        await interaction.followup.send(msg, ephemeral=True)

    elif action.value == "delete":
        result = core_logic.logic_reminders("delete", trip_name, reminder_id=reminder_id)
        
        if result["status"] == "success":
            await interaction.followup.send(f"🗑️ {result['message']}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ {result['message']}", ephemeral=True)

@client.tree.command(name="dashboard", description="View trip mission control.")
async def dashboard(interaction: discord.Interaction, trip_name: str = None):
    trip_name = await resolve_trip(interaction, trip_name)
    if not trip_name: return

    # Fetch Data
    trip_data = db.get_trip(trip_name)
    
    if not trip_data:
        await interaction.response.send_message(f"❌ Trip data for **{trip_name}** not found.", ephemeral=True)
        return

    expenses_data = db.load_expenses(trip_name)
    itinerary = db.get_itinerary(trip_name)
    reminders = db.get_reminders(trip_name)

    embed = create_dashboard_embed(trip_name, trip_data, expenses_data, itinerary, reminders)
    
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    
    try:
        await msg.pin(reason=f"Dashboard for {trip_name}")
    except:
        pass # Might fail if max pins reached or no perms

    db.update_trip_dashboard(trip_name, interaction.channel.id, msg.id)

@client.tree.command(name="location", description="Manage trip locations and check-ins.")
@app_commands.describe(action="add/list/checkin/status", trip_name="Optional trip name", name="Location name", address="Address/City", type="Type (Hotel, Restaurant, etc.)", url="Google Maps Link")
@app_commands.choices(action=[
    app_commands.Choice(name="Add Location", value="add"),
    app_commands.Choice(name="List Locations", value="list"),
    app_commands.Choice(name="Check In", value="checkin"),
    app_commands.Choice(name="Who's Nearby?", value="status"),
    app_commands.Choice(name="Delete Location", value="delete")
])
@app_commands.choices(type=[
    app_commands.Choice(name="Hotel/Stay", value="Hotel"),
    app_commands.Choice(name="Restaurant/Bar", value="Food"),
    app_commands.Choice(name="Activity/Spot", value="Activity"),
    app_commands.Choice(name="Meeting Point", value="Meetup"),
    app_commands.Choice(name="Other", value="Other")
])
async def location(interaction: discord.Interaction, action: app_commands.Choice[str], trip_name: str = None, name: str = None, address: str = None, type: app_commands.Choice[str] = None, url: str = None):
    if not await check_module(interaction, "locations"): return
    trip_name = await resolve_trip(interaction, trip_name)
    if not trip_name: return

    if action.value == "add":
        if not name or not type:
             await interaction.response.send_message("❌ You must provide a **name** and **type** to add a location.", ephemeral=True)
             return
        
        final_url = url
        if not final_url and address:
             query = urllib.parse.quote(f"{name} {address}")
             final_url = f"https://www.google.com/maps/search/?api=1&query={query}"
        elif not final_url:
             query = urllib.parse.quote(name)
             final_url = f"https://www.google.com/maps/search/?api=1&query={query}"
             
        result = core_logic.logic_location("add", trip_name, name=name, address=address, url=final_url, type=type.value, added_by=interaction.user.display_name)
        if result["status"] == "success":
             await interaction.response.send_message(f"📍 Added **{name}** ({type.value}) to **{trip_name}**!\n🔗 [Map Link]({final_url})")
        else:
             await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)

    elif action.value == "list":
        result = core_logic.logic_location("list", trip_name)
        if result["status"] == "success":
             locs = result["data"]
             if not locs:
                 await interaction.response.send_message(f"📭 No saved locations for **{trip_name}**.", ephemeral=True)
                 return
            
             embed = discord.Embed(title=f"🌍 Locations: {trip_name}", color=discord.Color.blue())
             for l in locs:
                 val = f"Type: {l['type']}\n"
                 if l.get('address'): val += f"Addr: {l['address']}\n"
                 if l.get('url'): val += f"[View on Map]({l['url']})\n"
                 val += f"Added by {l['added_by']}"
                 embed.add_field(name=l['name'], value=val, inline=True)
            
             await interaction.response.send_message(embed=embed)
        else:
             await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)

    elif action.value == "checkin":
        result = core_logic.logic_location("list", trip_name)
        if result["status"] == "success":
             locs = result["data"]
             if not locs:
                 await interaction.response.send_message(f"❌ No locations found to check in to.", ephemeral=True)
                 return
                 
             options = []
             for l in locs[:25]:
                 options.append(discord.SelectOption(label=l['name'], description=l['type'], value=str(l['id'])))
                 
             view = discord.ui.View()
             select = discord.ui.Select(placeholder="Select a location...", options=options)
            
             async def callback(interaction: discord.Interaction):
                 loc_id = select.values[0]
                 loc_name = next((l['name'] for l in locs if str(l['id']) == loc_id), "Unknown")
                 res = core_logic.logic_location("checkin", trip_name, user_id=interaction.user.id, user_name=interaction.user.display_name, location_id=int(loc_id))
                 if res["status"] == "success":
                     await interaction.response.send_message(f"📍 **{interaction.user.display_name}** checked in at **{loc_name}**!")
                 else:
                     await interaction.response.send_message(f"❌ Check-in failed: {res['message']}", ephemeral=True)
                 
             select.callback = callback
             view.add_item(select)
             await interaction.response.send_message("📍 Where are you?", view=view, ephemeral=True)
        else:
             await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)

    elif action.value == "status":
        result = core_logic.logic_location("latest_checkins", trip_name)
        if result["status"] == "success":
             checkins = result["data"]
             if not checkins:
                 await interaction.response.send_message(f"🤷‍♂️ No recent activity for **{trip_name}**.", ephemeral=True)
                 return
                 
             embed = discord.Embed(title=f"📡 Live Status: {trip_name}", color=discord.Color.green())
             for c in checkins:
                 loc = c.get('locations')
                 loc_name = loc['name'] if loc else "Unknown Location"
                 dt = datetime.fromisoformat(c['timestamp'])
                 time_str = dt.strftime("%H:%M")
                 embed.add_field(name=c['user_name'], value=f"📍 **{loc_name}**\n🕒 {time_str}", inline=True)
                 
             await interaction.response.send_message(embed=embed)
        else:
             await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)

    elif action.value == "delete":
        await interaction.response.send_message("❌ Delete not implemented yet.", ephemeral=True)

@client.tree.command(name="memory", description="Save and view trip memories.")
@app_commands.describe(action="upload/gallery", trip_name="Optional trip name", attachment="Photo/Video to upload", caption="Caption for the memory", day="Filter by Day Number (Gallery only)")
@app_commands.choices(action=[
    app_commands.Choice(name="Upload Memory", value="upload"),
    app_commands.Choice(name="View Gallery", value="gallery"),
    app_commands.Choice(name="Export Archive", value="export")
])
async def memory(interaction: discord.Interaction, action: app_commands.Choice[str], attachment: discord.Attachment = None, caption: str = None, trip_name: str = None, day: int = None):
    if not await check_module(interaction, "memories"): return
    trip_name = await resolve_trip(interaction, trip_name)
    if not trip_name: return

    if action.value == "upload":
        if not attachment:
             await interaction.response.send_message("❌ You must attach a photo or video!", ephemeral=True)
             return
        
        # Calculate Day
        day_num = None
        trip = db.get_trip(trip_name)
        if trip and trip.get('date'):
            try:
                start_date = datetime.strptime(trip['date'], "%Y-%m-%d").date()
                today = datetime.now().date()
                # Day 1 is the start date
                day_diff = (today - start_date).days + 1
                if day_diff > 0:
                    day_num = day_diff
            except Exception as e:
                print(f"Date calc error: {e}")
            
        db.add_memory(trip_name, attachment.url, caption or "No caption", interaction.user.id, day_num)
        
        day_str = f" (Day {day_num})" if day_num else ""
        await interaction.response.send_message(f"📸 **Memory saved!**{day_str}\n*{caption or ''}*")

        # Auto-Thread Creation for Days
        if day_num:
            thread_name = f"Day {day_num} Memories"
            thread = discord.utils.get(interaction.channel.threads, name=thread_name)
            
            if not thread:
                try:
                    msg = await interaction.original_response()
                    thread = await msg.create_thread(name=thread_name, auto_archive_duration=1440)
                    await thread.send(f"🌍 **Memories for Day {day_num}** collected here!")
                except Exception as e:
                    print(f"Failed to create thread: {e}")
            
            if thread:
                try:
                    # Repost media to thread
                    file = await attachment.to_file()
                    await thread.send(f"📸 **New Memory** (by {interaction.user.display_name})\n{caption or ''}", file=file)
                except Exception as e:
                    print(f"Failed to post to thread: {e}")

    elif action.value == "gallery":
        mems = db.get_memories(trip_name, day_filter=day)
        if not mems:
             filter_msg = f" for Day {day}" if day else ""
             await interaction.response.send_message(f"📭 No memories saved for **{trip_name}**{filter_msg} yet.", ephemeral=True)
             return
             
        title = f"📸 Memories: {trip_name}"
        if day:
            title += f" (Day {day})"
            
        embed = discord.Embed(title=title, color=discord.Color.purple())
        
        # Display latest
        latest = mems[0]
        embed.set_image(url=latest['url'])
        day_info = f"[Day {latest['day_number']}] " if latest.get('day_number') else ""
        embed.description = f"**Latest:** {day_info}{latest.get('caption', '')} (by <@{latest['user_id']}>)"
        
        if len(mems) > 1:
             others = []
             for m in mems[1:6]: # Show next 5 links
                  d_str = f"[Day {m['day_number']}] " if m.get('day_number') else ""
                  others.append(f"• {d_str}[{m.get('caption', 'View')}]({m['url']})")
             
             embed.add_field(name="Previous Memories", value="\n".join(others), inline=False)
             if len(mems) > 6:
                 embed.set_footer(text=f"And {len(mems)-6} more...")
                  
        await interaction.response.send_message(embed=embed)

    elif action.value == "export":
        mems = db.get_memories(trip_name)
        if not mems:
             await interaction.response.send_message(f"📭 No memories to export for **{trip_name}**.", ephemeral=True)
             return
        
        # Create HTML Archive
        html = f"<html><head><title>Memories: {trip_name}</title></head><body style='font-family: sans-serif;'><h1>📸 Memories: {trip_name}</h1>"
        for m in mems:
            day_str = f"Day {m['day_number']}" if m.get('day_number') else "General"
            caption_text = m.get('caption', 'No caption')
            user_id = m.get('user_id', 'Unknown')
            html += f"<div style='border:1px solid #ccc; padding:10px; margin:10px; border-radius:8px;'>"
            html += f"<h3>{day_str}</h3>"
            html += f"<p><strong>Caption:</strong> {caption_text} (by User {user_id})</p>"
            html += f"<img src='{m['url']}' style='max-width: 400px; max-height: 400px; border-radius: 4px;'><br>"
            html += f"<a href='{m['url']}' target='_blank'>View Full Size</a>"
            html += f"</div>"
        html += "</body></html>"
        
        file = discord.File(fp=io.BytesIO(html.encode()), filename=f"{trip_name}_memories.html")
        await interaction.response.send_message(f"📦 **Memory Archive for {trip_name}** (Download to view)", file=file)

import google.generativeai as genai

@client.tree.command(name="ask", description="Ask the AI Assistant for trip advice.")
@app_commands.describe(question="What do you want to know?")
async def ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    if not await check_module(interaction, "ai"): return
    
    # 0. Try Local Brain (Fast, Offline, Privacy-First)
    local_response = brain.generate_response(str(interaction.user.id), question)
    
    # Handle structured response from Brain
    response_text = ""
    if isinstance(local_response, dict):
         response_text = local_response.get("text", "")
         # Note: We don't execute autonomous actions from /ask usually, but we could.
         # For now, just show the text.
    else:
         response_text = local_response

    if response_text:
        embed = discord.Embed(title=f"🧠 Q: {question}", description=response_text, color=discord.Color.green())
        embed.set_footer(text="Powered by Local Brain 🧠 (Offline Mode)")
        await interaction.followup.send(embed=embed)
        return

    api_key = os.getenv("GEMINI_API_KEY")
    
    answer = ""
    is_offline = False
    source_footer = "Powered by Google Gemini 🧠"
    
    # 1. Try Gemini
    if api_key:
        try:
            genai.configure(api_key=api_key)
            # User requested Gemini Flash 2.0
            model = genai.GenerativeModel('gemini-2.0-flash')
            
            prompt = f"You are a helpful travel assistant bot for a Discord server. Keep answers concise, fun, and formatted with Markdown. Question: {question}"
            response = model.generate_content(prompt)
            
            answer = response.text
        except Exception as e:
            print(f"Gemini API Error: {e}")
            # If rate limited or error, fall through to Web Search
            api_key = None 

    # 2. Try Web Search (DuckDuckGo) if Gemini failed
    if not api_key or not answer:
        try:
            from search_engine import SearchEngine
            engine = SearchEngine()
            results = engine.search(question)
            
            if results:
                answer = "**🌍 Found on the Web (Relevance Scored):**\n"
                for r in results:
                    answer += f"• **[{r['title']}]({r['href']})**\n{r['body']}\n\n"
                source_footer = "Powered by DuckDuckGo Search 🦆"
            else:
                # If search returns no relevant results, fall to heuristics
                is_offline = True
                
        except Exception as e:
             print(f"Web Search Error: {e}")
             is_offline = True

    # 3. Fallback to Heuristics if both failed
    if is_offline or not answer:
        # Heuristic "AI"
        q_lower = question.lower()
        heuristic_ans = ""
        
        if "plan" in q_lower or "itinerary" in q_lower:
            heuristic_ans = "**🤖 Offline AI Suggestion:**\nHere is a generic structure:\n• **Day 1:** Arrival & Chill. Check into hotel, find a local dinner spot.\n• **Day 2:** Adventure Day! Hike, beach, or museum.\n• **Day 3:** Relax & Departure. Souvenir shopping and brunch."
        elif "budget" in q_lower or "cost" in q_lower or "money" in q_lower:
            heuristic_ans = "**🤖 Offline AI Suggestion:**\n• Track every expense with `/expense add`.\n• Set a daily limit.\n• Use `/expense settle` at the end to avoid arguments!"
        elif "pack" in q_lower or "bring" in q_lower:
            heuristic_ans = "**🤖 Offline AI Suggestion:**\nDon't forget:\n• 🔌 Chargers\n• 💊 Meds\n• 🪪 ID/Passport\n• 🩲 Extra underwear (always)\nUse `/packing add` to list them!"
        elif "food" in q_lower or "eat" in q_lower or "drink" in q_lower:
            heuristic_ans = "**🤖 Offline AI Suggestion:**\nCheck Google Maps for highly rated spots nearby. Ask locals! And don't forget to stay hydrated. 🥤"
        else:
            heuristic_ans = "**🤖 Offline AI Suggestion:**\nI'm not sure about that. Try asking about 'planning', 'budget', 'packing', or 'food'.\n*(Add GEMINI_API_KEY to .env for real intelligence!)*"
        
        if "AI Error" in answer:
             answer += "\n\n" + heuristic_ans
        else:
             answer = heuristic_ans

    embed = discord.Embed(title=f"🤖 Q: {question}", description=answer, color=discord.Color.teal())
    if is_offline and not api_key:
        embed.set_footer(text="Running in Offline Mode. Add GEMINI_API_KEY to .env for real AI.")
    else:
        embed.set_footer(text=source_footer)
        
    await interaction.followup.send(embed=embed)

@client.tree.command(name="cleanup_orphans", description="Admin: Delete all channels not assigned to a category.")
@app_commands.checks.has_permissions(administrator=True)
async def cleanup_orphans(interaction: discord.Interaction):
    # 1. Identification
    orphans = []
    for channel in interaction.guild.channels:
        # We want channels that:
        # 1. Are NOT categories themselves
        # 2. Do NOT belong to a category
        if channel.type != discord.ChannelType.category and channel.category is None:
            orphans.append(channel)
    
    if not orphans:
        await interaction.response.send_message("✅ No orphaned channels found.", ephemeral=True)
        return

    # 2. Confirmation View
    class ConfirmView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)
            self.value = None

        @discord.ui.button(label=f"Delete {len(orphans)} Channels", style=discord.ButtonStyle.danger)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.value = True
            await interaction.response.defer() # Acknowledge the button click
            self.stop()

        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.value = False
            await interaction.response.defer()
            self.stop()

    view = ConfirmView()
    
    # Preview list (first 10)
    preview = "\n".join([f"• {c.name} ({c.type})" for c in orphans[:10]])
    if len(orphans) > 10:
        preview += f"\n...and {len(orphans)-10} more."
        
    await interaction.response.send_message(
        f"⚠️ **WARNING:** This will delete **{len(orphans)}** orphaned channels.\n\n**Channels to be deleted:**\n{preview}\n\nAre you sure?", 
        view=view, 
        ephemeral=True
    )
    
    await view.wait()
    
    if view.value is None:
        await interaction.followup.send("⏳ Timed out.", ephemeral=True)
        return
    elif view.value is False:
        await interaction.followup.send("❌ Operation cancelled.", ephemeral=True)
        return
        
    # 3. Execution
    deleted_count = 0
    errors = []
    
    # Send initial status
    status_msg = await interaction.followup.send(f"🗑️ Deleting {len(orphans)} channels... (0/{len(orphans)})", ephemeral=True)
    
    for i, channel in enumerate(orphans):
        try:
            await channel.delete(reason=f"Cleanup Orphans by {interaction.user}")
            deleted_count += 1
        except Exception as e:
            errors.append(f"{channel.name}: {str(e)}")
            
        # Update status every 5 items to avoid rate limits
        if i % 5 == 0:
             try:
                 await status_msg.edit(content=f"🗑️ Deleting {len(orphans)} channels... ({i+1}/{len(orphans)})")
             except:
                 pass
                 
    # 4. Final Report
    report = f"✅ **Cleanup Complete!**\n🗑️ Deleted: {deleted_count}\n"
    if errors:
        report += f"⚠️ Errors ({len(errors)}):\n" + "\n".join(errors[:5])
        if len(errors) > 5:
            report += f"\n...and {len(errors)-5} more."
            
    await interaction.followup.send(report, ephemeral=True)


@client.tree.command(name="sync", description="Admin: sync slash commands for this server.")
@app_commands.checks.has_permissions(administrator=True)
async def sync(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        client.tree.copy_global_to(guild=interaction.guild)
        await client.tree.sync(guild=interaction.guild)
        await interaction.followup.send("✅ Commands synced for this server.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Sync failed: {e}", ephemeral=True)

@client.tree.command(name="modules", description="Admin: Enable/Disable bot modules.")
@app_commands.describe(action="enable/disable", module="Module to toggle")
@app_commands.choices(action=[
    app_commands.Choice(name="Enable", value="enable"),
    app_commands.Choice(name="Disable", value="disable")
])
@app_commands.choices(module=[
    app_commands.Choice(name="Expenses", value="expenses"),
    app_commands.Choice(name="Packing", value="packing"),
    app_commands.Choice(name="Itinerary", value="itinerary"),
    app_commands.Choice(name="Polls", value="polls"),
    app_commands.Choice(name="AI Assistant", value="ai"),
    app_commands.Choice(name="Reminders", value="reminders"),
    app_commands.Choice(name="Locations", value="locations"),
    app_commands.Choice(name="Memories", value="memories")
])
@app_commands.checks.has_permissions(administrator=True)
async def modules(interaction: discord.Interaction, action: app_commands.Choice[str], module: app_commands.Choice[str]):
    is_enabled = (action.value == "enable")
    db.toggle_module(interaction.guild.id, module.value, is_enabled)
    status = "enabled" if is_enabled else "disabled"
    await interaction.response.send_message(f"✅ Module **{module.name}** has been **{status}**.", ephemeral=True)


@setup.error
async def setup_error(interaction: discord.Interaction, error: app_commands.AppCommandError):

    # Check if the interaction has already been responded to
    try:
        if interaction.response.is_done():
            sender = interaction.followup.send
        else:
            sender = interaction.response.send_message

        if isinstance(error, app_commands.MissingPermissions):
            await sender("❌ You need **Administrator** permissions to use this command.", ephemeral=True)
        else:
            await sender(f"❌ An error occurred: {error}", ephemeral=True)
    except Exception as e:
        print(f"Failed to handle error: {e}")

if __name__ == "__main__":
    if not TOKEN or TOKEN == "your_token_here":
        print("❌ Error: Please set the DISCORD_TOKEN in the .env file.")
    else:
        try:
            client.run(TOKEN)
        except Exception as e:
            print(f"❌ Error running bot: {e}")
