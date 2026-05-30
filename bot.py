from dotenv import load_dotenv
load_dotenv()

import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import os
import random
from datetime import datetime
from database import Database

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
db = Database("roleshop.db")

ANIMUS_CHANNEL = "animus"
OWNER_ID = 335927174701907968

active_heists = {}
active_blackjack = {}

# ── MMR helpers ────────────────────────────────────────────────────────────
MMR_GAINS = {
    "coinflip": (8, 6),
    "slots":    (10, 5),
    "rob":      (12, 8),
    "blackjack":(15, 10),
    "race":     (15, 10),
    "heist":    (18, 5),
}

async def apply_mmr(interaction, guild_id, user_id, game, won):
    gain, loss = MMR_GAINS.get(game, (10, 8))
    delta = gain if won else -loss
    old_mmr, new_mmr = db.update_mmr(guild_id, user_id, delta)
    old_rank = db.get_rank(old_mmr)
    new_rank = db.get_rank(new_mmr)
    ch = get_animus(interaction.guild)
    if old_rank != new_rank and ch:
        if won and new_mmr > old_mmr:
            await ch.send(f"🎉 {interaction.user.mention} ranked up to **{new_rank}**! 🏆")
        else:
            await ch.send(f"📉 {interaction.user.mention} dropped to **{new_rank}**.")
    return delta, new_mmr, new_rank

def get_animus(guild):
    return discord.utils.get(guild.text_channels, name=ANIMUS_CHANNEL)

def only_owner(i): return i.user.id == OWNER_ID

# ── Card helpers ───────────────────────────────────────────────────────────
def card_value(card):
    r = card[:-1]
    if r in ["J","Q","K"]: return 10
    if r == "A": return 11
    return int(r)

def hand_value(hand):
    total = sum(card_value(c) for c in hand)
    aces = sum(1 for c in hand if c[:-1] == "A")
    while total > 21 and aces:
        total -= 10; aces -= 1
    return total

def new_deck():
    suits = ["♠","♥","♦","♣"]
    ranks = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
    deck = [r+s for s in suits for r in ranks]
    random.shuffle(deck)
    return deck

def hand_str(hand): return " ".join(hand)

async def check_badges(interaction, guild_id, user_id):
    user = db.get_user(guild_id, user_id)
    awarded = []
    if db.get_purchase_count(guild_id, user_id) >= 1:
        if db.award_badge(guild_id, user_id, "🛍️ First Purchase"): awarded.append("🛍️ First Purchase")
    if user.get("checkin_streak", 0) >= 7:
        if db.award_badge(guild_id, user_id, "🔥 Week Warrior"): awarded.append("🔥 Week Warrior")
    if user.get("level", 0) >= 10:
        if db.award_badge(guild_id, user_id, "⭐ Level 10"): awarded.append("⭐ Level 10")
    if user.get("coins", 0) >= 10000:
        if db.award_badge(guild_id, user_id, "💎 Rich"): awarded.append("💎 Rich")
    if user.get("prestige", 0) >= 1:
        if db.award_badge(guild_id, user_id, "👑 Prestige"): awarded.append("👑 Prestige")
    if user.get("mmr", 0) >= 1200:
        if db.award_badge(guild_id, user_id, "👾 Weld9a7ba"): awarded.append("👾 Weld9a7ba")
    if awarded:
        try:
            await interaction.followup.send(f"🎖️ **Badge unlocked!** {', '.join(awarded)}", ephemeral=True)
        except: pass

# ── Events ─────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    db.init()
    guild = discord.Object(id=774680905209348097)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)
    print(f"✅ RoleShop is online as {bot.user}")
    voice_tracker.start()
    daily_report.start()

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    db.ensure_user(message.guild.id, message.author.id)
    db.add_message_coins(message.guild.id, message.author.id)
    result = db.add_xp(message.guild.id, message.author.id, 10)
    if result["leveled_up"]:
        ch = get_animus(message.guild)
        if ch:
            await ch.send(f"⬆️ {message.author.mention} leveled up to **Level {result['level']}**! 🎉")
    trivia = db.get_active_trivia(message.guild.id)
    if trivia and message.content.lower().strip() == trivia["answer"].lower().strip():
        db.end_trivia(message.guild.id)
        db.add_coins(message.guild.id, message.author.id, trivia["reward"])
        await message.channel.send(
            f"🎉 **{message.author.display_name}** got it! Answer: **{trivia['answer']}**!\n💰 +**{trivia['reward']} coins**!")
    await bot.process_commands(message)

@tasks.loop(minutes=1)
async def voice_tracker():
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if not member.bot:
                    db.ensure_user(guild.id, member.id)
                    db.add_voice_coins(guild.id, member.id)

@tasks.loop(hours=24)
async def daily_report():
    for guild in bot.guilds:
        ch = get_animus(guild)
        if not ch: continue
        stats = db.get_daily_stats(guild.id)
        top_name = "Nobody"
        if stats["top_user"]:
            m = guild.get_member(stats["top_user"]["user_id"])
            top_name = m.display_name if m else "Unknown"
        embed = discord.Embed(title="📊 Daily Server Report", color=0x9b59b6, timestamp=datetime.utcnow())
        embed.add_field(name="🏆 Top Earner", value=top_name, inline=True)
        embed.add_field(name="🛍️ Purchases Today", value=str(stats["purchases_today"]), inline=True)
        embed.add_field(name="💬 Active Members", value=str(stats["active_today"]), inline=True)
        embed.add_field(name="💰 Total Coins", value=f"{stats['total_coins']:,}", inline=False)
        await ch.send(embed=embed)

@voice_tracker.before_loop
@daily_report.before_loop
async def before_tasks():
    await bot.wait_until_ready()

# ── /balance ───────────────────────────────────────────────────────────────
@bot.tree.command(name="balance", description="Check your coin balance")
async def balance(interaction: discord.Interaction):
    db.ensure_user(interaction.guild_id, interaction.user.id)
    data = db.get_bank(interaction.guild_id, interaction.user.id)
    await interaction.response.send_message(
        f"💰 **{interaction.user.display_name}**\nWallet: **{data['wallet']:,} coins**\n🏦 Bank: **{data['bank']:,} coins**", ephemeral=True)

# ── /deposit ───────────────────────────────────────────────────────────────
@bot.tree.command(name="deposit", description="Deposit coins into the bank")
@app_commands.describe(amount="Amount to deposit")
async def deposit(interaction: discord.Interaction, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True); return
    db.ensure_user(interaction.guild_id, interaction.user.id)
    result = db.deposit(interaction.guild_id, interaction.user.id, amount)
    if result["success"]:
        await interaction.response.send_message(
            f"🏦 Deposited **{amount:,} coins**!\nWallet: **{result['wallet']:,}** | Bank: **{result['bank']:,}**")
    else:
        await interaction.response.send_message(f"❌ {result['reason']}", ephemeral=True)

# ── /withdraw ──────────────────────────────────────────────────────────────
@bot.tree.command(name="withdraw", description="Withdraw coins from the bank")
@app_commands.describe(amount="Amount to withdraw")
async def withdraw(interaction: discord.Interaction, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True); return
    db.ensure_user(interaction.guild_id, interaction.user.id)
    result = db.withdraw(interaction.guild_id, interaction.user.id, amount)
    if result["success"]:
        await interaction.response.send_message(
            f"🏦 Withdrew **{amount:,} coins**!\nWallet: **{result['wallet']:,}** | Bank: **{result['bank']:,}**")
    else:
        await interaction.response.send_message(f"❌ {result['reason']}", ephemeral=True)

# ── /bank ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="bank", description="Check your bank balance")
async def bank(interaction: discord.Interaction):
    db.ensure_user(interaction.guild_id, interaction.user.id)
    data = db.get_bank(interaction.guild_id, interaction.user.id)
    embed = discord.Embed(title="🏦 Bank Account", color=0xf1c40f)
    embed.add_field(name="💰 Wallet", value=f"{data['wallet']:,} coins", inline=True)
    embed.add_field(name="🏦 Bank", value=f"{data['bank']:,} coins", inline=True)
    embed.add_field(name="💎 Total", value=f"{data['wallet']+data['bank']:,} coins", inline=False)
    embed.set_footer(text=f"Min wallet: 500 coins | Min deposit: 200 coins (first: 1,000)")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ── /mmr ───────────────────────────────────────────────────────────────────
@bot.tree.command(name="mmr", description="Check your MMR and rank")
@app_commands.describe(member="Member to check (leave empty for yourself)")
async def mmr(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    db.ensure_user(interaction.guild_id, member.id)
    user = db.get_user(interaction.guild_id, member.id)
    mmr_val = user.get("mmr", 0)
    rank = db.get_rank(mmr_val)
    next_rank = None
    for threshold, name in db.MMR_RANKS:
        if threshold > mmr_val:
            next_rank = (threshold, name)
            break
    embed = discord.Embed(title=f"🏆 {member.display_name}'s MMR", color=0x9b59b6)
    embed.add_field(name="Current Rank", value=rank, inline=True)
    embed.add_field(name="MMR", value=f"{mmr_val}", inline=True)
    if next_rank:
        embed.add_field(name="Next Rank", value=f"{next_rank[1]} ({next_rank[0] - mmr_val} MMR away)", inline=False)
    else:
        embed.add_field(name="🎖️", value="MAX RANK!", inline=False)
    await interaction.response.send_message(embed=embed)

# ── /mmrboard ─────────────────────────────────────────────────────────────
@bot.tree.command(name="mmrboard", description="Top MMR players in the server")
async def mmrboard(interaction: discord.Interaction):
    rows = db.get_mmr_leaderboard(interaction.guild_id)
    if not rows:
        await interaction.response.send_message("📊 No data yet!", ephemeral=True); return
    embed = discord.Embed(title="🏆 MMR Leaderboard", color=0xe74c3c)
    medals = ["🥇","🥈","🥉"]
    lines = []
    for i, row in enumerate(rows):
        m = interaction.guild.get_member(row["user_id"])
        name = m.display_name if m else f"User {row['user_id']}"
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        rank = db.get_rank(row["mmr"])
        lines.append(f"{medal} **{name}** — {rank} ({row['mmr']} MMR)")
    embed.description = "\n".join(lines)
    await interaction.response.send_message(embed=embed)

# ── /checkin ───────────────────────────────────────────────────────────────
@bot.tree.command(name="checkin", description="Daily check-in to earn coins")
async def checkin(interaction: discord.Interaction):
    db.ensure_user(interaction.guild_id, interaction.user.id)
    result = db.daily_checkin(interaction.guild_id, interaction.user.id)
    if result["success"]:
        streak, earned, total = result["streak"], result["earned"], result["balance"]
        streak_msg = f" 🔥 **{streak}-day streak!**" if streak > 1 else ""
        db.log_action(interaction.guild_id, interaction.user.id, "CHECKIN", f"Streak: {streak}", earned)
        await interaction.response.send_message(
            f"✅ Check-in!{streak_msg}\n+**{earned} coins**. Balance: **{total:,}**")
        await check_badges(interaction, interaction.guild_id, interaction.user.id)
    else:
        await interaction.response.send_message(f"⏳ Come back in **{result['hours_left']}h**.", ephemeral=True)

# ── /rank ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="rank", description="View your rank card")
@app_commands.describe(member="Member to view")
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    db.ensure_user(interaction.guild_id, member.id)
    user = db.get_user(interaction.guild_id, member.id)
    badges = db.get_badges(interaction.guild_id, member.id)
    level = user.get("level", 0)
    xp = user.get("xp", 0)
    prestige = user.get("prestige", 0)
    mmr_val = user.get("mmr", 0)
    needed = db.xp_for_level(level)
    bar_filled = int((xp / needed) * 20) if needed else 0
    bar = "█" * bar_filled + "░" * (20 - bar_filled)
    embed = discord.Embed(color=0x9b59b6)
    embed.set_author(name=f"{member.display_name}'s Card", icon_url=member.display_avatar.url)
    if prestige > 0:
        embed.add_field(name="👑 Prestige", value=str(prestige), inline=True)
    embed.add_field(name="⭐ Level", value=str(level), inline=True)
    embed.add_field(name="🏆 Rank", value=db.get_rank(mmr_val), inline=True)
    embed.add_field(name="💰 Coins", value=f"{user.get('coins',0):,}", inline=True)
    embed.add_field(name="📊 MMR", value=str(mmr_val), inline=True)
    embed.add_field(name="🔥 Streak", value=f"{user.get('checkin_streak',0)}d", inline=True)
    embed.add_field(name=f"XP {xp}/{needed}", value=f"`{bar}`", inline=False)
    if badges:
        embed.add_field(name="🎖️ Badges", value=" ".join(badges), inline=False)
    await interaction.response.send_message(embed=embed)

# ── /prestige ──────────────────────────────────────────────────────────────
@bot.tree.command(name="prestige", description="Reset to level 0 for prestige (requires level 20)")
async def prestige_cmd(interaction: discord.Interaction):
    db.ensure_user(interaction.guild_id, interaction.user.id)
    result = db.prestige(interaction.guild_id, interaction.user.id)
    if result["success"]:
        db.award_badge(interaction.guild_id, interaction.user.id, "👑 Prestige")
        ch = get_animus(interaction.guild)
        if ch:
            await ch.send(f"👑 **{interaction.user.display_name}** just reached **Prestige {result['prestige']}**! 🎉")
        await interaction.response.send_message(f"👑 You are now **Prestige {result['prestige']}**! Level reset to 0.")
    else:
        await interaction.response.send_message(f"❌ Need **Level 20**. You are Level **{result['level']}**.", ephemeral=True)

# ── /shop ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="shop", description="Browse the role shop")
async def shop(interaction: discord.Interaction):
    items = db.get_shop_items(interaction.guild_id)
    if not items:
        await interaction.response.send_message("🏪 Shop is empty! Add items with `/additem`.", ephemeral=True); return
    embed = discord.Embed(title="🛍️ RoleShop", color=0x9b59b6, description="Use `/buy <name>` to purchase!\n\n")
    for item in items:
        role = interaction.guild.get_role(item["role_id"])
        role_mention = role.mention if role else f"`{item['role_name']}`"
        duration = f" *(expires {item['duration_days']}d)*" if item["duration_days"] else ""
        embed.add_field(name=f"{item['name']} — 💰 {item['price']:,}", value=f"{role_mention}{duration}", inline=False)
    embed.set_footer(text=f"Wallet: {db.get_balance(interaction.guild_id, interaction.user.id):,} coins")
    await interaction.response.send_message(embed=embed)

# ── /buy ───────────────────────────────────────────────────────────────────
@bot.tree.command(name="buy", description="Buy an item from the shop")
@app_commands.describe(item_name="Name of the item")
async def buy(interaction: discord.Interaction, item_name: str):
    db.ensure_user(interaction.guild_id, interaction.user.id)
    item = db.get_item_by_name(interaction.guild_id, item_name)
    if not item:
        await interaction.response.send_message(f"❌ No item **{item_name}** found.", ephemeral=True); return
    balance = db.get_balance(interaction.guild_id, interaction.user.id)
    if balance < item["price"]:
        await interaction.response.send_message(f"❌ Need **{item['price']-balance:,} more coins**.", ephemeral=True); return
    role = interaction.guild.get_role(item["role_id"])
    if not role:
        await interaction.response.send_message("❌ Role no longer exists.", ephemeral=True); return
    if role in interaction.user.roles:
        await interaction.response.send_message(f"❌ You already have **{role.name}**!", ephemeral=True); return
    new_balance = db.deduct_coins(interaction.guild_id, interaction.user.id, item["price"])
    await interaction.user.add_roles(role)
    db.log_purchase(interaction.guild_id, interaction.user.id, item["id"])
    db.log_action(interaction.guild_id, interaction.user.id, "PURCHASE", f"Bought '{item['name']}'", -item["price"])
    await interaction.response.send_message(f"✅ You bought **{item['name']}** → {role.mention}!\n💰 Balance: **{new_balance:,}**")
    ch = get_animus(interaction.guild)
    if ch:
        await ch.send(f"🎉 **{interaction.user.display_name}** bought **{item['name']}** for {item['price']:,} coins!")
    await check_badges(interaction, interaction.guild_id, interaction.user.id)

# ── /give ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="give", description="Give coins to another member")
@app_commands.describe(member="Recipient", amount="Amount")
async def give(interaction: discord.Interaction, member: discord.Member, amount: int):
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("❌ Invalid recipient.", ephemeral=True); return
    if amount <= 0:
        await interaction.response.send_message("❌ Must be positive.", ephemeral=True); return
    db.ensure_user(interaction.guild_id, interaction.user.id)
    db.ensure_user(interaction.guild_id, member.id)
    bal = db.get_balance(interaction.guild_id, interaction.user.id)
    if bal - amount < 500:
        await interaction.response.send_message("❌ You must keep at least **500 coins** in your wallet.", ephemeral=True); return
    db.deduct_coins(interaction.guild_id, interaction.user.id, amount)
    db.add_coins(interaction.guild_id, member.id, amount)
    db.log_action(interaction.guild_id, interaction.user.id, "GIVE", f"Gave {amount} to {member.display_name}", -amount)
    await interaction.response.send_message(f"💸 **{interaction.user.display_name}** gave **{amount:,} coins** to {member.mention}!")

# ── /leaderboard ───────────────────────────────────────────────────────────
@bot.tree.command(name="leaderboard", description="Top coin earners")
async def leaderboard(interaction: discord.Interaction):
    rows = db.get_leaderboard(interaction.guild_id)
    if not rows:
        await interaction.response.send_message("📊 No data yet!", ephemeral=True); return
    embed = discord.Embed(title="🏆 Coin Leaderboard", color=0xf1c40f)
    medals = ["🥇","🥈","🥉"]
    lines = [f"{medals[i] if i < 3 else f'`#{i+1}`'} **{(interaction.guild.get_member(uid) or type('x', (), {'display_name': f'User {uid}'})()).display_name}** — {c:,} coins"
             for i, (uid, c) in enumerate(rows[:10])]
    embed.description = "\n".join(lines)
    await interaction.response.send_message(embed=embed)

# ── /levelboard ────────────────────────────────────────────────────────────
@bot.tree.command(name="levelboard", description="Top levels in the server")
async def levelboard(interaction: discord.Interaction):
    rows = db.get_level_leaderboard(interaction.guild_id)
    if not rows:
        await interaction.response.send_message("📊 No data yet!", ephemeral=True); return
    embed = discord.Embed(title="⭐ Level Leaderboard", color=0x3498db)
    medals = ["🥇","🥈","🥉"]
    lines = []
    for i, row in enumerate(rows):
        m = interaction.guild.get_member(row["user_id"])
        name = m.display_name if m else f"User {row['user_id']}"
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        p = f" P{row['prestige']}" if row["prestige"] > 0 else ""
        lines.append(f"{medal} **{name}** — Level {row['level']}{p}")
    embed.description = "\n".join(lines)
    await interaction.response.send_message(embed=embed)

# ── /coinflip ──────────────────────────────────────────────────────────────
@bot.tree.command(name="coinflip", description="Bet coins against another member (35% win chance)")
@app_commands.describe(member="Member to challenge", amount="Amount to bet")
async def coinflip(interaction: discord.Interaction, member: discord.Member, amount: int):
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("❌ Invalid opponent.", ephemeral=True); return
    if amount <= 0:
        await interaction.response.send_message("❌ Bet must be positive.", ephemeral=True); return
    db.ensure_user(interaction.guild_id, interaction.user.id)
    db.ensure_user(interaction.guild_id, member.id)
    bal1 = db.get_balance(interaction.guild_id, interaction.user.id)
    bal2 = db.get_balance(interaction.guild_id, member.id)
    if bal1 - amount < 500:
        await interaction.response.send_message("❌ You must keep **500 coins** in wallet.", ephemeral=True); return
    if bal2 - amount < 500:
        await interaction.response.send_message(f"❌ {member.display_name} must keep **500 coins** in wallet.", ephemeral=True); return
    won = random.random() < 0.35
    winner = interaction.user if won else member
    loser = member if won else interaction.user
    db.deduct_coins(interaction.guild_id, loser.id, amount)
    db.add_coins(interaction.guild_id, winner.id, amount)
    db.log_action(interaction.guild_id, winner.id, "COINFLIP", f"Won vs {loser.display_name}", amount)
    delta, new_mmr, new_rank = await apply_mmr(interaction, interaction.guild_id, interaction.user.id, "coinflip", won)
    mmr_str = f"+{delta}" if delta > 0 else str(delta)
    await interaction.response.send_message(
        f"🪙 **{'Heads' if won else 'Tails'}!**\n🏆 **{winner.display_name}** wins **{amount:,} coins**!\n📊 MMR: {mmr_str} → **{new_rank}**")

# ── /slots ─────────────────────────────────────────────────────────────────
@bot.tree.command(name="slots", description="Spin the slot machine")
@app_commands.describe(amount="Amount to bet")
async def slots(interaction: discord.Interaction, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Bet must be positive.", ephemeral=True); return
    db.ensure_user(interaction.guild_id, interaction.user.id)
    bal = db.get_balance(interaction.guild_id, interaction.user.id)
    if bal - amount < 500:
        await interaction.response.send_message("❌ Must keep **500 coins** in wallet.", ephemeral=True); return
    symbols = ["🍒","🍋","🍊","⭐","💎","7️⃣"]
    weights = [35, 30, 20, 10, 4, 1]
    s = random.choices(symbols, weights=weights, k=3)
    if s[0] == s[1] == s[2]:
        mult = {" 💎": 10, "7️⃣": 7, "⭐": 5}.get(s[0], 3)
        winnings = amount * mult
        db.add_coins(interaction.guild_id, interaction.user.id, winnings - amount)
        new_bal = db.get_balance(interaction.guild_id, interaction.user.id)
        delta, new_mmr, new_rank = await apply_mmr(interaction, interaction.guild_id, interaction.user.id, "slots", True)
        await interaction.response.send_message(
            f"🎰 | {s[0]} {s[1]} {s[2]} |\n🎉 **JACKPOT {mult}x!** +**{winnings:,} coins**!\nBalance: **{new_bal:,}** | MMR: +{delta} → **{new_rank}**")
    elif s[0] == s[1] or s[1] == s[2]:
        winnings = int(amount * 1.5)
        db.add_coins(interaction.guild_id, interaction.user.id, winnings - amount)
        new_bal = db.get_balance(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(
            f"🎰 | {s[0]} {s[1]} {s[2]} |\n✨ Two of a kind! +**{winnings:,} coins**! Balance: **{new_bal:,}**")
    else:
        db.deduct_coins(interaction.guild_id, interaction.user.id, amount)
        new_bal = db.get_balance(interaction.guild_id, interaction.user.id)
        delta, new_mmr, new_rank = await apply_mmr(interaction, interaction.guild_id, interaction.user.id, "slots", False)
        await interaction.response.send_message(
            f"🎰 | {s[0]} {s[1]} {s[2]} |\n💸 No match. -{amount:,} coins. Balance: **{new_bal:,}** | MMR: {delta} → **{new_rank}**")

# ── /rob ───────────────────────────────────────────────────────────────────
@bot.tree.command(name="rob", description="Attempt to rob a member (25% success, 1hr cooldown)")
@app_commands.describe(member="Who to rob")
async def rob(interaction: discord.Interaction, member: discord.Member):
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("❌ Invalid target.", ephemeral=True); return
    db.ensure_user(interaction.guild_id, interaction.user.id)
    db.ensure_user(interaction.guild_id, member.id)
    can, mins = db.can_rob(interaction.guild_id, interaction.user.id)
    if not can:
        await interaction.response.send_message(f"⏳ Cooldown! Wait **{mins} more minutes**.", ephemeral=True); return
    victim_bal = db.get_balance(interaction.guild_id, member.id)
    if victim_bal <= 500:
        await interaction.response.send_message(f"❌ {member.display_name} only has the minimum wallet amount!", ephemeral=True); return
    db.set_last_rob(interaction.guild_id, interaction.user.id)
    won = random.random() < 0.25
    delta, new_mmr, new_rank = await apply_mmr(interaction, interaction.guild_id, interaction.user.id, "rob", won)
    mmr_str = f"+{delta}" if delta > 0 else str(delta)
    if won:
        stealable = victim_bal - 500
        stolen = random.randint(int(stealable * 0.1), int(stealable * 0.25))
        db.deduct_coins(interaction.guild_id, member.id, stolen)
        db.add_coins(interaction.guild_id, interaction.user.id, stolen)
        db.log_action(interaction.guild_id, interaction.user.id, "ROB", f"Robbed {member.display_name}", stolen)
        await interaction.response.send_message(
            f"🦹 Success! Stole **{stolen:,} coins** from {member.mention}!\nMMR: {mmr_str} → **{new_rank}**")
    else:
        robber_bal = db.get_balance(interaction.guild_id, interaction.user.id)
        fine = min(random.randint(50, 200), max(0, robber_bal - 500))
        db.deduct_coins(interaction.guild_id, interaction.user.id, fine)
        db.add_coins(interaction.guild_id, member.id, fine)
        await interaction.response.send_message(
            f"🚔 Caught! Paid **{fine:,} coins** fine to {member.mention}!\nMMR: {mmr_str} → **{new_rank}**")

# ── /blackjack ─────────────────────────────────────────────────────────────
@bot.tree.command(name="blackjack", description="Play blackjack against the bot")
@app_commands.describe(amount="Amount to bet")
async def blackjack(interaction: discord.Interaction, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Bet must be positive.", ephemeral=True); return
    db.ensure_user(interaction.guild_id, interaction.user.id)
    bal = db.get_balance(interaction.guild_id, interaction.user.id)
    if bal - amount < 500:
        await interaction.response.send_message("❌ Must keep **500 coins** in wallet.", ephemeral=True); return
    if interaction.user.id in active_blackjack:
        await interaction.response.send_message("❌ Already in a game! Use `/hit` or `/stand`.", ephemeral=True); return
    deck = new_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    active_blackjack[interaction.user.id] = {"deck": deck, "player": player, "dealer": dealer, "bet": amount, "guild_id": interaction.guild_id}
    db.deduct_coins(interaction.guild_id, interaction.user.id, amount)
    pval = hand_value(player)
    embed = discord.Embed(title="🃏 Blackjack", color=0x2ecc71)
    embed.add_field(name="Your hand", value=f"{hand_str(player)} = **{pval}**", inline=False)
    embed.add_field(name="Dealer shows", value=f"{dealer[0]} ?", inline=False)
    if pval == 21:
        winnings = int(amount * 2.5)
        db.add_coins(interaction.guild_id, interaction.user.id, winnings)
        del active_blackjack[interaction.user.id]
        embed.add_field(name="🎉 BLACKJACK!", value=f"+{winnings:,} coins!", inline=False)
    else:
        embed.set_footer(text="Use /hit to draw or /stand to hold")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="hit", description="Draw a card in blackjack")
async def hit(interaction: discord.Interaction):
    if interaction.user.id not in active_blackjack:
        await interaction.response.send_message("❌ No active game. Use `/blackjack`.", ephemeral=True); return
    game = active_blackjack[interaction.user.id]
    game["player"].append(game["deck"].pop())
    pval = hand_value(game["player"])
    embed = discord.Embed(title="🃏 Blackjack", color=0x2ecc71)
    embed.add_field(name="Your hand", value=f"{hand_str(game['player'])} = **{pval}**", inline=False)
    embed.add_field(name="Dealer shows", value=f"{game['dealer'][0]} ?", inline=False)
    if pval > 21:
        embed.color = 0xe74c3c
        embed.add_field(name="💥 Bust!", value=f"Lost **{game['bet']:,} coins**.", inline=False)
        delta, _, new_rank = await apply_mmr(interaction, game["guild_id"], interaction.user.id, "blackjack", False)
        embed.set_footer(text=f"MMR: {delta} → {new_rank}")
        del active_blackjack[interaction.user.id]
    else:
        embed.set_footer(text="Use /hit or /stand")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="stand", description="Hold your hand in blackjack")
async def stand(interaction: discord.Interaction):
    if interaction.user.id not in active_blackjack:
        await interaction.response.send_message("❌ No active game.", ephemeral=True); return
    game = active_blackjack[interaction.user.id]
    while hand_value(game["dealer"]) < 18:
        game["dealer"].append(game["deck"].pop())
    pval = hand_value(game["player"])
    dval = hand_value(game["dealer"])
    embed = discord.Embed(title="🃏 Blackjack Result", color=0x9b59b6)
    embed.add_field(name="Your hand", value=f"{hand_str(game['player'])} = **{pval}**", inline=False)
    embed.add_field(name="Dealer hand", value=f"{hand_str(game['dealer'])} = **{dval}**", inline=False)
    bet, guild_id = game["bet"], game["guild_id"]
    del active_blackjack[interaction.user.id]
    if dval > 21 or pval > dval:
        winnings = bet * 2
        db.add_coins(guild_id, interaction.user.id, winnings)
        embed.color = 0x2ecc71
        embed.add_field(name="🏆 You Win!", value=f"+**{winnings:,} coins**!", inline=False)
        delta, _, new_rank = await apply_mmr(interaction, guild_id, interaction.user.id, "blackjack", True)
    elif pval == dval:
        db.add_coins(guild_id, interaction.user.id, bet)
        embed.add_field(name="🤝 Push!", value="Bet returned.", inline=False)
        delta, new_rank = 0, db.get_rank(db.get_user(guild_id, interaction.user.id).get("mmr",0))
    else:
        embed.color = 0xe74c3c
        embed.add_field(name="💸 Dealer Wins", value=f"Lost **{bet:,} coins**.", inline=False)
        delta, _, new_rank = await apply_mmr(interaction, guild_id, interaction.user.id, "blackjack", False)
    mmr_str = f"+{delta}" if delta > 0 else str(delta)
    embed.set_footer(text=f"MMR: {mmr_str} → {new_rank}")
    await interaction.response.send_message(embed=embed)

# ── /race ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="race", description="Bet on a horse race")
@app_commands.describe(horse="Horse number 1-4", amount="Amount to bet")
async def race(interaction: discord.Interaction, horse: int, amount: int):
    if horse < 1 or horse > 4:
        await interaction.response.send_message("❌ Pick horse 1-4.", ephemeral=True); return
    if amount <= 0:
        await interaction.response.send_message("❌ Bet must be positive.", ephemeral=True); return
    db.ensure_user(interaction.guild_id, interaction.user.id)
    bal = db.get_balance(interaction.guild_id, interaction.user.id)
    if bal - amount < 500:
        await interaction.response.send_message("❌ Must keep **500 coins** in wallet.", ephemeral=True); return
    db.deduct_coins(interaction.guild_id, interaction.user.id, amount)
    horses = ["🐴","🦄","🐎","🏇"]
    names = ["Thunder","Blaze","Shadow","Storm"]
    positions = [0,0,0,0]
    await interaction.response.send_message("🏁 Race starting...")
    msg = await interaction.original_response()
    for _ in range(8):
        for i in range(4):
            positions[i] += random.randint(1, 5)
        track = "\n".join([f"{horses[i]} {names[i]}: `{'─'*min(positions[i],20):<20}` {positions[i]}m" for i in range(4)])
        await msg.edit(content=f"🏁 **Horse Race!**\n{track}")
        await asyncio.sleep(1)
    winner_idx = positions.index(max(positions))
    won = winner_idx + 1 == horse
    delta, new_mmr, new_rank = await apply_mmr(interaction, interaction.guild_id, interaction.user.id, "race", won)
    mmr_str = f"+{delta}" if delta > 0 else str(delta)
    if won:
        winnings = amount * 3
        db.add_coins(interaction.guild_id, interaction.user.id, winnings)
        await msg.edit(content=f"🏆 **{names[winner_idx]}** wins!\n🎉 Right horse! +**{winnings:,} coins**! MMR: {mmr_str} → **{new_rank}**")
    else:
        await msg.edit(content=f"🏆 **{names[winner_idx]}** wins!\n💸 Wrong horse. Lost **{amount:,} coins**. MMR: {mmr_str} → **{new_rank}**")

# ── /trivia ────────────────────────────────────────────────────────────────
TRIVIA_QUESTIONS = [
    ("What is the capital of France?", "paris"),
    ("How many sides does a hexagon have?", "6"),
    ("What is 12 x 12?", "144"),
    ("What planet is closest to the sun?", "mercury"),
    ("What is the largest ocean?", "pacific"),
    ("Who wrote Romeo and Juliet?", "shakespeare"),
    ("What is the chemical symbol for gold?", "au"),
    ("How many continents are there?", "7"),
    ("What is the fastest land animal?", "cheetah"),
    ("What year did World War 2 end?", "1945"),
]

@bot.tree.command(name="trivia", description="Start a trivia question")
@app_commands.describe(reward="Coin reward (default 200)")
async def trivia(interaction: discord.Interaction, reward: int = 200):
    if db.get_active_trivia(interaction.guild_id):
        await interaction.response.send_message("❌ Trivia already active!", ephemeral=True); return
    q, a = random.choice(TRIVIA_QUESTIONS)
    db.start_trivia(interaction.guild_id, q, a, reward)
    embed = discord.Embed(title="🧠 Trivia!", color=0xe67e22,
                          description=f"**{q}**\n\nFirst correct answer wins **{reward:,} coins**!")
    await interaction.response.send_message(embed=embed)

# ── /heist ─────────────────────────────────────────────────────────────────
@bot.tree.command(name="heist", description="Start a coin heist!")
@app_commands.describe(pot="Coin pot for the heist")
async def heist(interaction: discord.Interaction, pot: int = 1000):
    if interaction.guild_id in active_heists:
        await interaction.response.send_message("❌ Heist already active!", ephemeral=True); return
    db.ensure_user(interaction.guild_id, interaction.user.id)

    class HeistView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.members = [interaction.user]

        @discord.ui.button(label="Join Heist", style=discord.ButtonStyle.danger, emoji="⚔️")
        async def join(self, btn: discord.Interaction, button: discord.ui.Button):
            if btn.user in self.members:
                await btn.response.send_message("❌ Already joined!", ephemeral=True); return
            self.members.append(btn.user)
            await btn.response.send_message(f"✅ Joined! ({len(self.members)}/5)", ephemeral=True)
            if len(self.members) >= 5:
                await self.finish()

        async def on_timeout(self):
            await self.finish()

        async def finish(self):
            self.stop()
            if interaction.guild_id in active_heists:
                del active_heists[interaction.guild_id]
            ch = get_animus(interaction.guild)
            if len(self.members) >= 3:
                share = pot // len(self.members)
                names = []
                for m in self.members:
                    db.ensure_user(interaction.guild_id, m.id)
                    db.add_coins(interaction.guild_id, m.id, share)
                    db.update_mmr(interaction.guild_id, m.id, 18)
                    names.append(m.display_name)
                if ch:
                    await ch.send(f"⚔️ **Heist success!** Each gets **{share:,} coins**!\n👥 {', '.join(names)}")
            else:
                for m in self.members:
                    db.update_mmr(interaction.guild_id, m.id, -5)
                if ch:
                    await ch.send(f"❌ Heist failed! Not enough members ({len(self.members)}/3).")

    active_heists[interaction.guild_id] = True
    embed = discord.Embed(title="⚔️ Coin Heist!", color=0xe74c3c,
                          description=f"**{interaction.user.display_name}** started a heist!\n💰 Pot: **{pot:,} coins**\nNeed **3+ members** | 60 seconds!")
    await interaction.response.send_message(embed=embed, view=HeistView())

# ── Admin commands ─────────────────────────────────────────────────────────
@bot.tree.command(name="additem", description="[Admin] Add shop item")
@app_commands.describe(name="Item name", role="Role to grant", price="Cost", duration_days="Days until expires")
@app_commands.check(only_owner)
async def additem(interaction: discord.Interaction, name: str, role: discord.Role, price: int, duration_days: int = 0):
    db.add_shop_item(interaction.guild_id, name, role.id, role.name, price, duration_days or None)
    await interaction.response.send_message(f"✅ Added **{name}** → {role.mention} for **{price:,} coins**.")

@bot.tree.command(name="removeitem", description="[Admin] Remove shop item")
@app_commands.describe(name="Item name")
@app_commands.check(only_owner)
async def removeitem(interaction: discord.Interaction, name: str):
    if db.remove_shop_item(interaction.guild_id, name):
        await interaction.response.send_message(f"🗑️ **{name}** removed.")
    else:
        await interaction.response.send_message(f"❌ **{name}** not found.", ephemeral=True)

@bot.tree.command(name="grantcoins", description="[Admin] Grant coins")
@app_commands.describe(member="Member", amount="Amount")
@app_commands.check(only_owner)
async def grantcoins(interaction: discord.Interaction, member: discord.Member, amount: int):
    db.ensure_user(interaction.guild_id, member.id)
    new_bal = db.add_coins(interaction.guild_id, member.id, amount)
    db.log_action(interaction.guild_id, interaction.user.id, "ADMIN_GRANT", f"Granted {amount} to {member.display_name}", amount)
    await interaction.response.send_message(f"✅ Granted **{amount:,} coins** to {member.mention}. Balance: **{new_bal:,}**.")

@bot.tree.command(name="removecoins", description="[Admin] Remove coins")
@app_commands.describe(member="Member", amount="Amount")
@app_commands.check(only_owner)
async def removecoins(interaction: discord.Interaction, member: discord.Member, amount: int):
    db.ensure_user(interaction.guild_id, member.id)
    bal = db.get_balance(interaction.guild_id, member.id)
    amount = min(amount, bal)
    new_bal = db.deduct_coins(interaction.guild_id, member.id, amount)
    db.log_action(interaction.guild_id, interaction.user.id, "ADMIN_REMOVE", f"Removed {amount} from {member.display_name}", -amount)
    await interaction.response.send_message(f"✅ Removed **{amount:,} coins** from {member.mention}. Balance: **{new_bal:,}**.")

@bot.tree.command(name="resetcheckin", description="[Admin] Reset checkin")
@app_commands.describe(member="Member")
@app_commands.check(only_owner)
async def resetcheckin(interaction: discord.Interaction, member: discord.Member):
    db.ensure_user(interaction.guild_id, member.id)
    db.reset_checkin(interaction.guild_id, member.id)
    await interaction.response.send_message(f"✅ Checkin reset for {member.mention}.")

@bot.tree.command(name="setrate", description="[Admin] Set earn rates")
@app_commands.describe(message_coins="Per message", checkin_coins="Daily checkin", voice_coins="Per minute VC")
@app_commands.check(only_owner)
async def setrate(interaction: discord.Interaction, message_coins: int = None, checkin_coins: int = None, voice_coins: int = None):
    changes = []
    if message_coins is not None:
        db.set_config(interaction.guild_id, "message_coins", message_coins); changes.append(f"Message: **{message_coins}**")
    if checkin_coins is not None:
        db.set_config(interaction.guild_id, "checkin_coins", checkin_coins); changes.append(f"Checkin: **{checkin_coins}**")
    if voice_coins is not None:
        db.set_config(interaction.guild_id, "voice_coins", voice_coins); changes.append(f"Voice/min: **{voice_coins}**")
    if changes:
        await interaction.response.send_message("⚙️ Updated:\n" + "\n".join(changes))
    else:
        await interaction.response.send_message("⚠️ No values provided.", ephemeral=True)

@bot.tree.command(name="grantall", description="[Admin] Grant coins to ALL members")
@app_commands.describe(amount="Coins to grant to everyone")
@app_commands.check(only_owner)
async def grantall(interaction: discord.Interaction, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True); return
    await interaction.response.defer()
    count = 0
    for member in interaction.guild.members:
        if not member.bot:
            db.ensure_user(interaction.guild_id, member.id)
            db.add_coins(interaction.guild_id, member.id, amount)
            count += 1
    db.log_action(interaction.guild_id, interaction.user.id, "ADMIN_GRANT_ALL", f"Granted {amount} coins to all ({count} members)", amount * count)
    await interaction.followup.send(f"✅ Granted **{amount:,} coins** to **{count} members**! 💰")

@bot.tree.command(name="removeall", description="[Admin] Remove coins from ALL members")
@app_commands.describe(amount="Coins to remove from everyone")
@app_commands.check(only_owner)
async def removeall(interaction: discord.Interaction, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True); return
    await interaction.response.defer()
    count = 0
    for member in interaction.guild.members:
        if not member.bot:
            db.ensure_user(interaction.guild_id, member.id)
            bal = db.get_balance(interaction.guild_id, member.id)
            db.deduct_coins(interaction.guild_id, member.id, min(amount, bal))
            count += 1
    db.log_action(interaction.guild_id, interaction.user.id, "ADMIN_REMOVE_ALL", f"Removed {amount} coins from all ({count} members)", -amount * count)
    await interaction.followup.send(f"✅ Removed **{amount:,} coins** from **{count} members**!")

@bot.tree.command(name="setmmr", description="[Admin] Set a member's MMR manually")
@app_commands.describe(member="Member", mmr="New MMR value")
@app_commands.check(only_owner)
async def setmmr(interaction: discord.Interaction, member: discord.Member, mmr: int):
    db.ensure_user(interaction.guild_id, member.id)
    with db._conn() as c:
        c.execute("UPDATE users SET mmr=? WHERE guild_id=? AND user_id=?", (max(0, mmr), interaction.guild_id, member.id))
    rank = db.get_rank(mmr)
    await interaction.response.send_message(f"✅ Set {member.mention}'s MMR to **{mmr}** → **{rank}**.")

@bot.tree.command(name="logs", description="[Admin] View activity logs")
@app_commands.describe(limit="How many entries (max 100)")
@app_commands.check(only_owner)
async def logs(interaction: discord.Interaction, limit: int = 50):
    limit = min(limit, 100)
    rows = db.get_logs(interaction.guild_id, limit)
    if not rows:
        await interaction.response.send_message("📋 No activity yet.", ephemeral=True); return
    icons = {"CHECKIN":"✅","PURCHASE":"🛍️","GIVE":"💸","ADMIN_GRANT":"⚙️","ADMIN_REMOVE":"❌","ADMIN_RESET":"🔄","ROB":"🦹","COINFLIP":"🪙"}
    embed = discord.Embed(title="📋 Activity Log", color=0x5b4a9e)
    lines = []
    for row in rows:
        m = interaction.guild.get_member(row["user_id"])
        name = m.display_name if m else f"User {row['user_id']}"
        icon = icons.get(row["action"], "•")
        coins_str = f" (+{row['coins']}💰)" if row["coins"] > 0 else (f" ({row['coins']}💰)" if row["coins"] < 0 else "")
        created = datetime.fromisoformat(row["created_at"])
        diff = datetime.utcnow() - created
        if diff.total_seconds() < 60: t = "just now"
        elif diff.total_seconds() < 3600: t = f"{int(diff.total_seconds()//60)}m ago"
        elif diff.days == 0: t = f"{int(diff.total_seconds()//3600)}h ago"
        else: t = f"{diff.days}d ago"
        lines.append(f"{icon} **{name}** — {row['detail']}{coins_str} · *{t}*")
    chunk = ""
    page = 1
    for line in lines:
        if len(chunk) + len(line) + 1 > 4000:
            embed.description = chunk
            await interaction.response.send_message(embed=embed, ephemeral=True)
            embed = discord.Embed(title="📋 Log (cont.)", color=0x5b4a9e)
            chunk = line + "\n"; page += 1
        else:
            chunk += line + "\n"
    embed.description = chunk
    embed.set_footer(text=f"Showing {len(rows)} actions")
    if page == 1:
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(embed=embed, ephemeral=True)

# ── Error handler ──────────────────────────────────────────────────────────
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Error: {error}", ephemeral=True)

# ── Run ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ DISCORD_TOKEN not found.")
        exit(1)
    bot.run(token)
