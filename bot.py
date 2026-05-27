from dotenv import load_dotenv
load_dotenv()

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os
from datetime import datetime
from database import Database

# ── Bot setup ──────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
db = Database("roleshop.db")

# ── Events ─────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    db.init()
    guild = discord.Object(id=774680905209348097)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)
    print(f"✅ RoleShop is online as {bot.user}")
    bot.loop.create_task(voice_tracker())

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return
    db.ensure_user(message.guild.id, message.author.id)
    earned = db.add_message_coins(message.guild.id, message.author.id)
    if earned:
        pass  # silent earn — no spam
    await bot.process_commands(message)

# ── Voice tracker (background task) ───────────────────────────────────────
async def voice_tracker():
    await bot.wait_until_ready()
    while not bot.is_closed():
        for guild in bot.guilds:
            for vc in guild.voice_channels:
                for member in vc.members:
                    if not member.bot:
                        db.ensure_user(guild.id, member.id)
                        db.add_voice_coins(guild.id, member.id)
        await asyncio.sleep(60)

# ── /balance ───────────────────────────────────────────────────────────────
@bot.tree.command(name="balance", description="Check your coin balance")
async def balance(interaction: discord.Interaction):
    db.ensure_user(interaction.guild_id, interaction.user.id)
    coins = db.get_balance(interaction.guild_id, interaction.user.id)
    await interaction.response.send_message(
        f"💰 **{interaction.user.display_name}**, you have **{coins:,} coins**.", ephemeral=True
    )

# ── /checkin ───────────────────────────────────────────────────────────────
@bot.tree.command(name="checkin", description="Daily check-in to earn coins")
async def checkin(interaction: discord.Interaction):
    db.ensure_user(interaction.guild_id, interaction.user.id)
    result = db.daily_checkin(interaction.guild_id, interaction.user.id)
    if result["success"]:
        streak = result["streak"]
        earned = result["earned"]
        total = result["balance"]
        streak_msg = f" 🔥 **{streak}-day streak!**" if streak > 1 else ""
        db.log_action(interaction.guild_id, interaction.user.id, "CHECKIN",
                      f"Streak: {streak}", earned)
        await interaction.response.send_message(
            f"✅ Check-in successful!{streak_msg}\n+**{earned} coins** earned. Balance: **{total:,} coins**"
        )
    else:
        hours = result["hours_left"]
        await interaction.response.send_message(
            f"⏳ Already checked in today! Come back in **{hours}h** for your next bonus.", ephemeral=True
        )

# ── /shop ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="shop", description="Browse the role shop")
async def shop(interaction: discord.Interaction):
    items = db.get_shop_items(interaction.guild_id)
    if not items:
        await interaction.response.send_message(
            "🏪 The shop is empty! An admin can add items with `/additem`.", ephemeral=True
        )
        return

    embed = discord.Embed(title="🛍️ RoleShop", color=0x9b59b6)
    embed.description = "Use `/buy <item name>` to purchase a role!\n\n"

    for item in items:
        role = interaction.guild.get_role(item["role_id"])
        role_mention = role.mention if role else f"`{item['role_name']}`"
        duration = f" *(expires in {item['duration_days']}d)*" if item["duration_days"] else ""
        embed.add_field(
            name=f"{item['name']}  —  💰 {item['price']:,} coins",
            value=f"{role_mention}{duration}",
            inline=False,
        )

    embed.set_footer(text=f"Your balance: {db.get_balance(interaction.guild_id, interaction.user.id):,} coins")
    await interaction.response.send_message(embed=embed)

# ── /buy ───────────────────────────────────────────────────────────────────
@bot.tree.command(name="buy", description="Buy an item from the shop")
@app_commands.describe(item_name="Name of the item to buy")
async def buy(interaction: discord.Interaction, item_name: str):
    db.ensure_user(interaction.guild_id, interaction.user.id)
    item = db.get_item_by_name(interaction.guild_id, item_name)

    if not item:
        await interaction.response.send_message(
            f"❌ No item called **{item_name}** found. Check `/shop` for available items.", ephemeral=True
        )
        return

    balance = db.get_balance(interaction.guild_id, interaction.user.id)
    if balance < item["price"]:
        needed = item["price"] - balance
        await interaction.response.send_message(
            f"❌ Not enough coins! You need **{needed:,} more coins**. Try `/checkin` or chat to earn some. 💬", ephemeral=True
        )
        return

    role = interaction.guild.get_role(item["role_id"])
    if not role:
        await interaction.response.send_message("❌ That role no longer exists. Please contact an admin.", ephemeral=True)
        return

    if role in interaction.user.roles:
        await interaction.response.send_message(f"❌ You already have the **{role.name}** role!", ephemeral=True)
        return

    new_balance = db.deduct_coins(interaction.guild_id, interaction.user.id, item["price"])
    await interaction.user.add_roles(role)
    db.log_purchase(interaction.guild_id, interaction.user.id, item["id"])
    db.log_action(interaction.guild_id, interaction.user.id, "PURCHASE",
                  f"Bought '{item['name']}' ({role.name})", -item["price"])

    await interaction.response.send_message(
        f"✅ Cha-ching! You bought **{item['name']}** and now have the {role.mention} role!\n💰 New balance: **{new_balance:,} coins**"
    )

# ── /give ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="give", description="Give coins to another member")
@app_commands.describe(member="Who to give coins to", amount="How many coins to give")
async def give(interaction: discord.Interaction, member: discord.Member, amount: int):
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("❌ Invalid recipient.", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
        return

    db.ensure_user(interaction.guild_id, interaction.user.id)
    db.ensure_user(interaction.guild_id, member.id)
    balance = db.get_balance(interaction.guild_id, interaction.user.id)

    if balance < amount:
        await interaction.response.send_message(f"❌ You only have **{balance:,} coins**.", ephemeral=True)
        return

    db.deduct_coins(interaction.guild_id, interaction.user.id, amount)
    db.add_coins(interaction.guild_id, member.id, amount)
    db.log_action(interaction.guild_id, interaction.user.id, "GIVE",
                  f"Gave {amount} coins to {member.display_name}", -amount)
    await interaction.response.send_message(
        f"💸 **{interaction.user.display_name}** gave **{amount:,} coins** to {member.mention}!"
    )

# ── /leaderboard ───────────────────────────────────────────────────────────
@bot.tree.command(name="leaderboard", description="Top coin earners in the server")
async def leaderboard(interaction: discord.Interaction):
    rows = db.get_leaderboard(interaction.guild_id)
    if not rows:
        await interaction.response.send_message("📊 No data yet!", ephemeral=True)
        return

    embed = discord.Embed(title="🏆 Coin Leaderboard", color=0xf1c40f)
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (user_id, coins) in enumerate(rows[:10]):
        member = interaction.guild.get_member(user_id)
        name = member.display_name if member else f"User {user_id}"
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        lines.append(f"{medal} **{name}** — {coins:,} coins")

    embed.description = "\n".join(lines)
    await interaction.response.send_message(embed=embed)

# ── /additem (admin) ───────────────────────────────────────────────────────
@bot.tree.command(name="additem", description="[Admin] Add an item to the shop")
@app_commands.describe(
    name="Item display name",
    role="Discord role to grant",
    price="Cost in coins",
    duration_days="Days until role expires (0 = permanent)"
)
@app_commands.checks.has_permissions(administrator=True)
async def additem(interaction: discord.Interaction, name: str, role: discord.Role, price: int, duration_days: int = 0):
    db.add_shop_item(interaction.guild_id, name, role.id, role.name, price, duration_days or None)
    duration_text = f" (expires after {duration_days}d)" if duration_days else " (permanent)"
    await interaction.response.send_message(
        f"✅ Added **{name}** to the shop — grants {role.mention} for **{price:,} coins**{duration_text}."
    )

# ── /removeitem (admin) ────────────────────────────────────────────────────
@bot.tree.command(name="removeitem", description="[Admin] Remove an item from the shop")
@app_commands.describe(name="Item name to remove")
@app_commands.checks.has_permissions(administrator=True)
async def removeitem(interaction: discord.Interaction, name: str):
    removed = db.remove_shop_item(interaction.guild_id, name)
    if removed:
        await interaction.response.send_message(f"🗑️ **{name}** removed from the shop.")
    else:
        await interaction.response.send_message(f"❌ No item called **{name}** found.", ephemeral=True)

# ── /grantcoins (admin) ────────────────────────────────────────────────────
@bot.tree.command(name="grantcoins", description="[Admin] Grant coins to a member")
@app_commands.describe(member="Member to reward", amount="Coins to grant")
@app_commands.checks.has_permissions(administrator=True)
async def grantcoins(interaction: discord.Interaction, member: discord.Member, amount: int):
    db.ensure_user(interaction.guild_id, member.id)
    new_bal = db.add_coins(interaction.guild_id, member.id, amount)
    db.log_action(interaction.guild_id, interaction.user.id, "ADMIN_GRANT",
                  f"Admin granted {amount} coins to {member.display_name}", amount)
    await interaction.response.send_message(
        f"✅ Granted **{amount:,} coins** to {member.mention}. New balance: **{new_bal:,} coins**."
    )

# ── /removecoins (admin) ──────────────────────────────────────────────────
@bot.tree.command(name="removecoins", description="[Admin] Remove coins from a member")
@app_commands.describe(member="Member to remove coins from", amount="Amount of coins to remove")
@app_commands.checks.has_permissions(administrator=True)
async def removecoins(interaction: discord.Interaction, member: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
        return
    db.ensure_user(interaction.guild_id, member.id)
    balance = db.get_balance(interaction.guild_id, member.id)
    if amount > balance:
        amount = balance
    new_bal = db.deduct_coins(interaction.guild_id, member.id, amount)
    db.log_action(interaction.guild_id, interaction.user.id, "ADMIN_REMOVE",
                  f"Admin removed {amount} coins from {member.display_name}", -amount)
    await interaction.response.send_message(
        f"✅ Removed **{amount:,} coins** from {member.mention}. New balance: **{new_bal:,} coins**."
    )

# ── /resetcheckin (admin) ──────────────────────────────────────────────────
@bot.tree.command(name="resetcheckin", description="[Admin] Reset daily checkin for a member")
@app_commands.describe(member="Member to reset checkin for")
@app_commands.checks.has_permissions(administrator=True)
async def resetcheckin(interaction: discord.Interaction, member: discord.Member):
    db.ensure_user(interaction.guild_id, member.id)
    db.reset_checkin(interaction.guild_id, member.id)
    db.log_action(interaction.guild_id, interaction.user.id, "ADMIN_RESET",
                  f"Admin reset checkin for {member.display_name}", 0)
    await interaction.response.send_message(
        f"✅ Daily checkin reset for {member.mention} — they can now `/checkin` again immediately."
    )

# ── /setrate (admin) ───────────────────────────────────────────────────────
@bot.tree.command(name="setrate", description="[Admin] Set coin earn rates")
@app_commands.describe(
    message_coins="Coins per message (default 5)",
    checkin_coins="Base coins per daily check-in (default 100)",
    voice_coins="Coins per minute in voice (default 2)"
)
@app_commands.checks.has_permissions(administrator=True)
async def setrate(interaction: discord.Interaction, message_coins: int = None, checkin_coins: int = None, voice_coins: int = None):
    changes = []
    if message_coins is not None:
        db.set_config(interaction.guild_id, "message_coins", message_coins)
        changes.append(f"Message coins: **{message_coins}**")
    if checkin_coins is not None:
        db.set_config(interaction.guild_id, "checkin_coins", checkin_coins)
        changes.append(f"Check-in coins: **{checkin_coins}**")
    if voice_coins is not None:
        db.set_config(interaction.guild_id, "voice_coins", voice_coins)
        changes.append(f"Voice coins/min: **{voice_coins}**")

    if changes:
        await interaction.response.send_message("⚙️ Rates updated:\n" + "\n".join(changes))
    else:
        await interaction.response.send_message("⚠️ No values provided.", ephemeral=True)

# ── /logs (admin) ─────────────────────────────────────────────────────────
@bot.tree.command(name="logs", description="[Admin] View recent bot activity")
@app_commands.describe(limit="How many entries to show (default 50, max 100)")
@app_commands.checks.has_permissions(administrator=True)
async def logs(interaction: discord.Interaction, limit: int = 50):
    limit = min(limit, 100)
    rows = db.get_logs(interaction.guild_id, limit)
    if not rows:
        await interaction.response.send_message("📋 No activity logged yet.", ephemeral=True)
        return

    action_icons = {
        "CHECKIN":     "✅",
        "PURCHASE":    "🛍️",
        "GIVE":        "💸",
        "ADMIN_GRANT": "⚙️",
        "ADMIN_REMOVE":"❌",
        "ADMIN_RESET": "🔄",
    }

    embed = discord.Embed(title="📋 Activity Log", color=0x5b4a9e)
    lines = []
    for row in rows:
        member = interaction.guild.get_member(row["user_id"])
        name = member.display_name if member else f"User {row['user_id']}"
        icon = action_icons.get(row["action"], "•")
        coins_str = f" (+{row['coins']} 💰)" if row["coins"] > 0 else (f" ({row['coins']} 💰)" if row["coins"] < 0 else "")
        created = datetime.fromisoformat(row["created_at"])
        diff = datetime.utcnow() - created
        if diff.total_seconds() < 60:
            time_str = "just now"
        elif diff.total_seconds() < 3600:
            time_str = f"{int(diff.total_seconds() // 60)}m ago"
        elif diff.days == 0:
            time_str = f"{int(diff.total_seconds() // 3600)}h ago"
        else:
            time_str = f"{diff.days}d ago"

        lines.append(f"{icon} **{name}** — {row['detail']}{coins_str} · *{time_str}*")

    # Discord embed limit is 4096 chars, split if needed
    chunk = ""
    page = 1
    for line in lines:
        if len(chunk) + len(line) + 1 > 4000:
            embed.description = chunk
            await interaction.response.send_message(embed=embed, ephemeral=True)
            embed = discord.Embed(title=f"📋 Activity Log (cont.)", color=0x5b4a9e)
            chunk = line + "\n"
            page += 1
        else:
            chunk += line + "\n"

    embed.description = chunk
    embed.set_footer(text=f"Showing last {len(rows)} actions")
    if page == 1:
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(embed=embed, ephemeral=True)

# ── Error handler ──────────────────────────────────────────────────────────
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You need **Administrator** permission for that.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Something went wrong: {error}", ephemeral=True)

# ── Run ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ DISCORD_TOKEN not found. Make sure your .env file exists.")
        exit(1)
    bot.run(token)
