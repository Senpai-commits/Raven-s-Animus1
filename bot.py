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

# ── Bot setup ──────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
db = Database("roleshop.db")

ANIMUS_CHANNEL = "animus"  # auto-message channel name

# Active heists and blackjack games stored in memory
active_heists = {}   # guild_id -> {starter, pot, members, message}
active_blackjack = {}  # user_id -> {deck, player_hand, dealer_hand, bet, guild_id}
active_races = {}    # guild_id -> {horses, bets, message}

# ── Helpers ────────────────────────────────────────────────────────────────
def get_animus(guild: discord.Guild):
    return discord.utils.get(guild.text_channels, name=ANIMUS_CHANNEL)

def card_value(card):
    rank = card[:-1]
    if rank in ["J","Q","K"]: return 10
    if rank == "A": return 11
    return int(rank)

def hand_value(hand):
    total = sum(card_value(c) for c in hand)
    aces = sum(1 for c in hand if c[:-1] == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total

def new_deck():
    suits = ["♠","♥","♦","♣"]
    ranks = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
    deck = [r+s for s in suits for r in ranks]
    random.shuffle(deck)
    return deck

def hand_str(hand):
    return " ".join(hand)

async def check_badges(interaction, guild_id, user_id):
    user = db.get_user(guild_id, user_id)
    awarded = []
    # First purchase
    if db.get_purchase_count(guild_id, user_id) >= 1:
        if db.award_badge(guild_id, user_id, "🛍️ First Purchase"):
            awarded.append("🛍️ First Purchase")
    # 7 day streak
    if user.get("checkin_streak", 0) >= 7:
        if db.award_badge(guild_id, user_id, "🔥 Week Warrior"):
            awarded.append("🔥 Week Warrior")
    # Level 10
    if user.get("level", 0) >= 10:
        if db.award_badge(guild_id, user_id, "⭐ Level 10"):
            awarded.append("⭐ Level 10")
    # Rich (10000 coins)
    if user.get("coins", 0) >= 10000:
        if db.award_badge(guild_id, user_id, "💎 Rich"):
            awarded.append("💎 Rich")
    # Prestige
    if user.get("prestige", 0) >= 1:
        if db.award_badge(guild_id, user_id, "👑 Prestige"):
            awarded.append("👑 Prestige")
    if awarded:
        try:
            await interaction.followup.send(
                f"🎖️ **Badge unlocked!** {', '.join(awarded)}", ephemeral=True
            )
        except:
            pass

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
    if message.author.bot or not message.guild:
        return
    db.ensure_user(message.guild.id, message.author.id)
    db.add_message_coins(message.guild.id, message.author.id)
    result = db.add_xp(message.guild.id, message.author.id, 10)
    if result["leveled_up"]:
        ch = get_animus(message.guild)
        if ch:
            await ch.send(
                f"⬆️ {message.author.mention} leveled up to **Level {result['level']}**! 🎉"
            )

    # Trivia check
    trivia = db.get_active_trivia(message.guild.id)
    if trivia and message.content.lower().strip() == trivia["answer"].lower().strip():
        db.end_trivia(message.guild.id)
        db.ensure_user(message.guild.id, message.author.id)
        db.add_coins(message.guild.id, message.author.id, trivia["reward"])
        await message.channel.send(
            f"🎉 **{message.author.display_name}** got it! The answer was **{trivia['answer']}**!\n"
            f"💰 +**{trivia['reward']} coins** awarded!"
        )

    await bot.process_commands(message)

# ── Background tasks ───────────────────────────────────────────────────────
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
        if not ch:
            continue
        stats = db.get_daily_stats(guild.id)
        top_name = "Nobody"
        if stats["top_user"]:
            member = guild.get_member(stats["top_user"]["user_id"])
            top_name = member.display_name if member else "Unknown"
        embed = discord.Embed(title="📊 Daily Server Report", color=0x9b59b6,
                              timestamp=datetime.utcnow())
        embed.add_field(name="🏆 Top Earner", value=top_name, inline=True)
        embed.add_field(name="🛍️ Purchases Today", value=str(stats["purchases_today"]), inline=True)
        embed.add_field(name="💬 Active Members", value=str(stats["active_today"]), inline=True)
        embed.add_field(name="💰 Total Coins in Server", value=f"{stats['total_coins']:,}", inline=False)
        await ch.send(embed=embed)

@voice_tracker.before_loop
@daily_report.before_loop
async def before_tasks():
    await bot.wait_until_ready()

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
        streak, earned, total = result["streak"], result["earned"], result["balance"]
        streak_msg = f" 🔥 **{streak}-day streak!**" if streak > 1 else ""
        db.log_action(interaction.guild_id, interaction.user.id, "CHECKIN", f"Streak: {streak}", earned)
        await interaction.response.send_message(
            f"✅ Check-in successful!{streak_msg}\n+**{earned} coins** earned. Balance: **{total:,} coins**"
        )
        await check_badges(interaction, interaction.guild_id, interaction.user.id)
    else:
        await interaction.response.send_message(
            f"⏳ Already checked in! Come back in **{result['hours_left']}h**.", ephemeral=True
        )

# ── /rank ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="rank", description="View your rank card")
@app_commands.describe(member="Member to view (leave empty for yourself)")
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    db.ensure_user(interaction.guild_id, member.id)
    user = db.get_user(interaction.guild_id, member.id)
    badges = db.get_badges(interaction.guild_id, member.id)
    level = user.get("level", 0)
    xp = user.get("xp", 0)
    prestige = user.get("prestige", 0)
    needed = db.xp_for_level(level)
    bar_filled = int((xp / needed) * 20) if needed else 0
    bar = "█" * bar_filled + "░" * (20 - bar_filled)

    embed = discord.Embed(color=0x9b59b6)
    embed.set_author(name=f"{member.display_name}'s Rank Card", icon_url=member.display_avatar.url)
    if prestige > 0:
        embed.add_field(name="👑 Prestige", value=str(prestige), inline=True)
    embed.add_field(name="⭐ Level", value=str(level), inline=True)
    embed.add_field(name="💰 Coins", value=f"{user.get('coins',0):,}", inline=True)
    embed.add_field(name="🔥 Streak", value=f"{user.get('checkin_streak',0)} days", inline=True)
    embed.add_field(name=f"XP — {xp}/{needed}", value=f"`{bar}`", inline=False)
    if badges:
        embed.add_field(name="🎖️ Badges", value=" ".join(badges), inline=False)
    await interaction.response.send_message(embed=embed)

# ── /prestige ──────────────────────────────────────────────────────────────
@bot.tree.command(name="prestige", description="Reset to level 0 for a prestige rank (requires level 20)")
async def prestige_cmd(interaction: discord.Interaction):
    db.ensure_user(interaction.guild_id, interaction.user.id)
    result = db.prestige(interaction.guild_id, interaction.user.id)
    if result["success"]:
        db.award_badge(interaction.guild_id, interaction.user.id, "👑 Prestige")
        ch = get_animus(interaction.guild)
        if ch:
            await ch.send(
                f"👑 **{interaction.user.display_name}** just prestiged! They are now **Prestige {result['prestige']}**! 🎉"
            )
        await interaction.response.send_message(
            f"👑 You prestiged! You are now **Prestige {result['prestige']}**. Level reset to 0. Keep grinding! 💪"
        )
    else:
        await interaction.response.send_message(
            f"❌ You need to be **Level 20** to prestige. You are Level **{result['level']}**.", ephemeral=True
        )

# ── /shop ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="shop", description="Browse the role shop")
async def shop(interaction: discord.Interaction):
    items = db.get_shop_items(interaction.guild_id)
    if not items:
        await interaction.response.send_message("🏪 The shop is empty! An admin can add items with `/additem`.", ephemeral=True)
        return
    embed = discord.Embed(title="🛍️ RoleShop", color=0x9b59b6)
    embed.description = "Use `/buy <item name>` to purchase a role!\n\n"
    for item in items:
        role = interaction.guild.get_role(item["role_id"])
        role_mention = role.mention if role else f"`{item['role_name']}`"
        duration = f" *(expires in {item['duration_days']}d)*" if item["duration_days"] else ""
        embed.add_field(name=f"{item['name']}  —  💰 {item['price']:,} coins",
                        value=f"{role_mention}{duration}", inline=False)
    embed.set_footer(text=f"Your balance: {db.get_balance(interaction.guild_id, interaction.user.id):,} coins")
    await interaction.response.send_message(embed=embed)

# ── /buy ───────────────────────────────────────────────────────────────────
@bot.tree.command(name="buy", description="Buy an item from the shop")
@app_commands.describe(item_name="Name of the item to buy")
async def buy(interaction: discord.Interaction, item_name: str):
    db.ensure_user(interaction.guild_id, interaction.user.id)
    item = db.get_item_by_name(interaction.guild_id, item_name)
    if not item:
        await interaction.response.send_message(f"❌ No item called **{item_name}** found.", ephemeral=True)
        return
    balance = db.get_balance(interaction.guild_id, interaction.user.id)
    if balance < item["price"]:
        await interaction.response.send_message(
            f"❌ Need **{item['price']-balance:,} more coins**. Try `/checkin` or games!", ephemeral=True)
        return
    role = interaction.guild.get_role(item["role_id"])
    if not role:
        await interaction.response.send_message("❌ Role no longer exists.", ephemeral=True)
        return
    if role in interaction.user.roles:
        await interaction.response.send_message(f"❌ You already have **{role.name}**!", ephemeral=True)
        return
    new_balance = db.deduct_coins(interaction.guild_id, interaction.user.id, item["price"])
    await interaction.user.add_roles(role)
    db.log_purchase(interaction.guild_id, interaction.user.id, item["id"])
    db.log_action(interaction.guild_id, interaction.user.id, "PURCHASE",
                  f"Bought '{item['name']}' ({role.name})", -item["price"])
    await interaction.response.send_message(
        f"✅ You bought **{item['name']}** and got {role.mention}!\n💰 Balance: **{new_balance:,} coins**"
    )
    # Public purchase announcement
    ch = get_animus(interaction.guild)
    if ch:
        await ch.send(f"🎉 **{interaction.user.display_name}** just bought the **{item['name']}** role for {item['price']:,} coins!")
    await check_badges(interaction, interaction.guild_id, interaction.user.id)

# ── /give ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="give", description="Give coins to another member")
@app_commands.describe(member="Who to give coins to", amount="How many coins")
async def give(interaction: discord.Interaction, member: discord.Member, amount: int):
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("❌ Invalid recipient.", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
        return
    db.ensure_user(interaction.guild_id, interaction.user.id)
    db.ensure_user(interaction.guild_id, member.id)
    if db.get_balance(interaction.guild_id, interaction.user.id) < amount:
        await interaction.response.send_message("❌ Not enough coins.", ephemeral=True)
        return
    db.deduct_coins(interaction.guild_id, interaction.user.id, amount)
    db.add_coins(interaction.guild_id, member.id, amount)
    db.log_action(interaction.guild_id, interaction.user.id, "GIVE", f"Gave {amount} to {member.display_name}", -amount)
    await interaction.response.send_message(
        f"💸 **{interaction.user.display_name}** gave **{amount:,} coins** to {member.mention}!"
    )

# ── /leaderboard ───────────────────────────────────────────────────────────
@bot.tree.command(name="leaderboard", description="Top coin earners")
async def leaderboard(interaction: discord.Interaction):
    rows = db.get_leaderboard(interaction.guild_id)
    if not rows:
        await interaction.response.send_message("📊 No data yet!", ephemeral=True)
        return
    embed = discord.Embed(title="🏆 Coin Leaderboard", color=0xf1c40f)
    medals = ["🥇","🥈","🥉"]
    lines = []
    for i, (user_id, coins) in enumerate(rows[:10]):
        member = interaction.guild.get_member(user_id)
        name = member.display_name if member else f"User {user_id}"
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        lines.append(f"{medal} **{name}** — {coins:,} coins")
    embed.description = "\n".join(lines)
    await interaction.response.send_message(embed=embed)

# ── /levelboard ────────────────────────────────────────────────────────────
@bot.tree.command(name="levelboard", description="Top levels in the server")
async def levelboard(interaction: discord.Interaction):
    rows = db.get_level_leaderboard(interaction.guild_id)
    if not rows:
        await interaction.response.send_message("📊 No data yet!", ephemeral=True)
        return
    embed = discord.Embed(title="⭐ Level Leaderboard", color=0x3498db)
    medals = ["🥇","🥈","🥉"]
    lines = []
    for i, row in enumerate(rows):
        member = interaction.guild.get_member(row["user_id"])
        name = member.display_name if member else f"User {row['user_id']}"
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        prestige_str = f" P{row['prestige']}" if row["prestige"] > 0 else ""
        lines.append(f"{medal} **{name}** — Level {row['level']}{prestige_str}")
    embed.description = "\n".join(lines)
    await interaction.response.send_message(embed=embed)

# ── /coinflip ──────────────────────────────────────────────────────────────
@bot.tree.command(name="coinflip", description="Bet coins against another member")
@app_commands.describe(member="Member to challenge", amount="Amount to bet")
async def coinflip(interaction: discord.Interaction, member: discord.Member, amount: int):
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("❌ Invalid opponent.", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("❌ Bet must be positive.", ephemeral=True)
        return
    db.ensure_user(interaction.guild_id, interaction.user.id)
    db.ensure_user(interaction.guild_id, member.id)
    if db.get_balance(interaction.guild_id, interaction.user.id) < amount:
        await interaction.response.send_message("❌ You don't have enough coins.", ephemeral=True)
        return
    if db.get_balance(interaction.guild_id, member.id) < amount:
        await interaction.response.send_message(f"❌ {member.display_name} doesn't have enough coins.", ephemeral=True)
        return
    winner = random.choice([interaction.user, member])
    loser = member if winner == interaction.user else interaction.user
    db.deduct_coins(interaction.guild_id, loser.id, amount)
    db.add_coins(interaction.guild_id, winner.id, amount)
    db.log_action(interaction.guild_id, winner.id, "COINFLIP", f"Won coinflip vs {loser.display_name}", amount)
    result = "🪙 Heads!" if winner == interaction.user else "🪙 Tails!"
    await interaction.response.send_message(
        f"{result}\n🏆 **{winner.display_name}** wins **{amount:,} coins** from {loser.mention}!"
    )

# ── /slots ─────────────────────────────────────────────────────────────────
@bot.tree.command(name="slots", description="Spin the slot machine")
@app_commands.describe(amount="Amount to bet")
async def slots(interaction: discord.Interaction, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Bet must be positive.", ephemeral=True)
        return
    db.ensure_user(interaction.guild_id, interaction.user.id)
    if db.get_balance(interaction.guild_id, interaction.user.id) < amount:
        await interaction.response.send_message("❌ Not enough coins.", ephemeral=True)
        return
    symbols = ["🍒","🍋","🍊","⭐","💎","7️⃣"]
    weights = [30, 25, 20, 15, 7, 3]
    s = random.choices(symbols, weights=weights, k=3)
    if s[0] == s[1] == s[2]:
        if s[0] == "💎": mult = 10
        elif s[0] == "7️⃣": mult = 7
        elif s[0] == "⭐": mult = 5
        else: mult = 3
        winnings = amount * mult
        db.add_coins(interaction.guild_id, interaction.user.id, winnings - amount)
        new_bal = db.get_balance(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(
            f"🎰 | {s[0]} {s[1]} {s[2]} |\n🎉 **JACKPOT! {mult}x!** +**{winnings:,} coins**!\nBalance: **{new_bal:,}**"
        )
    elif s[0] == s[1] or s[1] == s[2]:
        winnings = int(amount * 1.5)
        db.add_coins(interaction.guild_id, interaction.user.id, winnings - amount)
        new_bal = db.get_balance(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(
            f"🎰 | {s[0]} {s[1]} {s[2]} |\n✨ **Two of a kind!** +**{winnings:,} coins**!\nBalance: **{new_bal:,}**"
        )
    else:
        db.deduct_coins(interaction.guild_id, interaction.user.id, amount)
        new_bal = db.get_balance(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(
            f"🎰 | {s[0]} {s[1]} {s[2]} |\n💸 No match. Lost **{amount:,} coins**. Balance: **{new_bal:,}**"
        )

# ── /rob ───────────────────────────────────────────────────────────────────
@bot.tree.command(name="rob", description="Attempt to rob another member (1hr cooldown)")
@app_commands.describe(member="Who to rob")
async def rob(interaction: discord.Interaction, member: discord.Member):
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("❌ Invalid target.", ephemeral=True)
        return
    db.ensure_user(interaction.guild_id, interaction.user.id)
    db.ensure_user(interaction.guild_id, member.id)
    can, mins_left = db.can_rob(interaction.guild_id, interaction.user.id)
    if not can:
        await interaction.response.send_message(f"⏳ Rob cooldown! Wait **{mins_left} more minutes**.", ephemeral=True)
        return
    victim_bal = db.get_balance(interaction.guild_id, member.id)
    if victim_bal < 100:
        await interaction.response.send_message(f"❌ {member.display_name} is too broke to rob!", ephemeral=True)
        return
    db.set_last_rob(interaction.guild_id, interaction.user.id)
    if random.random() < 0.45:  # 45% success
        stolen = random.randint(int(victim_bal * 0.1), int(victim_bal * 0.3))
        db.deduct_coins(interaction.guild_id, member.id, stolen)
        db.add_coins(interaction.guild_id, interaction.user.id, stolen)
        db.log_action(interaction.guild_id, interaction.user.id, "ROB", f"Robbed {member.display_name}", stolen)
        await interaction.response.send_message(
            f"🦹 Success! You stole **{stolen:,} coins** from {member.mention}! 💰"
        )
    else:
        fine = random.randint(50, 200)
        robber_bal = db.get_balance(interaction.guild_id, interaction.user.id)
        fine = min(fine, robber_bal)
        db.deduct_coins(interaction.guild_id, interaction.user.id, fine)
        db.add_coins(interaction.guild_id, member.id, fine)
        await interaction.response.send_message(
            f"🚔 You got caught! Paid **{fine:,} coins** as a fine to {member.mention}!"
        )

# ── /blackjack ─────────────────────────────────────────────────────────────
@bot.tree.command(name="blackjack", description="Play blackjack against the bot")
@app_commands.describe(amount="Amount to bet")
async def blackjack(interaction: discord.Interaction, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Bet must be positive.", ephemeral=True)
        return
    db.ensure_user(interaction.guild_id, interaction.user.id)
    if db.get_balance(interaction.guild_id, interaction.user.id) < amount:
        await interaction.response.send_message("❌ Not enough coins.", ephemeral=True)
        return
    if interaction.user.id in active_blackjack:
        await interaction.response.send_message("❌ You already have an active game! Use `/hit` or `/stand`.", ephemeral=True)
        return
    deck = new_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    active_blackjack[interaction.user.id] = {
        "deck": deck, "player": player, "dealer": dealer,
        "bet": amount, "guild_id": interaction.guild_id
    }
    db.deduct_coins(interaction.guild_id, interaction.user.id, amount)
    pval = hand_value(player)
    embed = discord.Embed(title="🃏 Blackjack", color=0x2ecc71)
    embed.add_field(name="Your hand", value=f"{hand_str(player)} = **{pval}**", inline=False)
    embed.add_field(name="Dealer shows", value=f"{dealer[0]} ?", inline=False)
    if pval == 21:
        embed.add_field(name="🎉 BLACKJACK!", value="You win!", inline=False)
        winnings = int(amount * 2.5)
        db.add_coins(interaction.guild_id, interaction.user.id, winnings)
        del active_blackjack[interaction.user.id]
        embed.set_footer(text=f"+{winnings:,} coins!")
        await interaction.response.send_message(embed=embed)
    else:
        embed.set_footer(text="Use /hit to draw or /stand to hold")
        await interaction.response.send_message(embed=embed)

@bot.tree.command(name="hit", description="Draw a card in blackjack")
async def hit(interaction: discord.Interaction):
    if interaction.user.id not in active_blackjack:
        await interaction.response.send_message("❌ No active blackjack game. Use `/blackjack`.", ephemeral=True)
        return
    game = active_blackjack[interaction.user.id]
    game["player"].append(game["deck"].pop())
    pval = hand_value(game["player"])
    embed = discord.Embed(title="🃏 Blackjack", color=0x2ecc71)
    embed.add_field(name="Your hand", value=f"{hand_str(game['player'])} = **{pval}**", inline=False)
    embed.add_field(name="Dealer shows", value=f"{game['dealer'][0]} ?", inline=False)
    if pval > 21:
        embed.color = 0xe74c3c
        embed.add_field(name="💥 Bust!", value=f"Lost **{game['bet']:,} coins**.", inline=False)
        del active_blackjack[interaction.user.id]
    elif pval == 21:
        embed.add_field(name="✅ 21!", value="Use /stand to collect.", inline=False)
        embed.set_footer(text="Use /stand to hold")
    else:
        embed.set_footer(text="Use /hit to draw or /stand to hold")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="stand", description="Hold your hand in blackjack")
async def stand(interaction: discord.Interaction):
    if interaction.user.id not in active_blackjack:
        await interaction.response.send_message("❌ No active blackjack game.", ephemeral=True)
        return
    game = active_blackjack[interaction.user.id]
    while hand_value(game["dealer"]) < 17:
        game["dealer"].append(game["deck"].pop())
    pval = hand_value(game["player"])
    dval = hand_value(game["dealer"])
    embed = discord.Embed(title="🃏 Blackjack Result", color=0x9b59b6)
    embed.add_field(name="Your hand", value=f"{hand_str(game['player'])} = **{pval}**", inline=False)
    embed.add_field(name="Dealer hand", value=f"{hand_str(game['dealer'])} = **{dval}**", inline=False)
    bet = game["bet"]
    guild_id = game["guild_id"]
    del active_blackjack[interaction.user.id]
    if dval > 21 or pval > dval:
        winnings = bet * 2
        db.add_coins(guild_id, interaction.user.id, winnings)
        embed.color = 0x2ecc71
        embed.add_field(name="🏆 You Win!", value=f"+**{winnings:,} coins**!", inline=False)
    elif pval == dval:
        db.add_coins(guild_id, interaction.user.id, bet)
        embed.add_field(name="🤝 Push!", value="Bet returned.", inline=False)
    else:
        embed.color = 0xe74c3c
        embed.add_field(name="💸 Dealer Wins", value=f"Lost **{bet:,} coins**.", inline=False)
    await interaction.response.send_message(embed=embed)

# ── /race ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="race", description="Start a horse race! Bet on a horse to win")
@app_commands.describe(horse="Horse number 1-4", amount="Amount to bet")
async def race(interaction: discord.Interaction, horse: int, amount: int):
    if horse < 1 or horse > 4:
        await interaction.response.send_message("❌ Pick horse 1, 2, 3, or 4.", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("❌ Bet must be positive.", ephemeral=True)
        return
    db.ensure_user(interaction.guild_id, interaction.user.id)
    if db.get_balance(interaction.guild_id, interaction.user.id) < amount:
        await interaction.response.send_message("❌ Not enough coins.", ephemeral=True)
        return
    db.deduct_coins(interaction.guild_id, interaction.user.id, amount)
    horses = ["🐴","🦄","🐎","🏇"]
    names = ["Thunder","Blaze","Shadow","Storm"]
    positions = [0, 0, 0, 0]
    await interaction.response.send_message("🏁 Race starting...")
    msg = await interaction.original_response()
    for _ in range(8):
        for i in range(4):
            positions[i] += random.randint(1, 5)
        track = ""
        for i in range(4):
            bar = "─" * min(positions[i], 20)
            track += f"{horses[i]} {names[i]}: `{bar:<20}` {positions[i]}m\n"
        await msg.edit(content=f"🏁 **Horse Race!**\n{track}")
        await asyncio.sleep(1)
    winner_idx = positions.index(max(positions))
    winner_name = names[winner_idx]
    if winner_idx + 1 == horse:
        winnings = amount * 3
        db.add_coins(interaction.guild_id, interaction.user.id, winnings)
        await msg.edit(content=
            f"🏆 **{winner_name}** wins the race!\n"
            f"🎉 You picked the right horse! +**{winnings:,} coins**!"
        )
    else:
        await msg.edit(content=
            f"🏆 **{winner_name}** wins the race!\n"
            f"💸 Your horse lost. Better luck next time!"
        )

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

@bot.tree.command(name="trivia", description="Start a trivia question — first correct answer wins coins!")
@app_commands.describe(reward="Coin reward for correct answer (default 200)")
async def trivia(interaction: discord.Interaction, reward: int = 200):
    existing = db.get_active_trivia(interaction.guild_id)
    if existing:
        await interaction.response.send_message("❌ There's already an active trivia question!", ephemeral=True)
        return
    q, a = random.choice(TRIVIA_QUESTIONS)
    db.start_trivia(interaction.guild_id, q, a, reward)
    embed = discord.Embed(title="🧠 Trivia Time!", color=0xe67e22)
    embed.description = f"**{q}**\n\nType your answer in chat! First correct answer wins **{reward:,} coins**!"
    await interaction.response.send_message(embed=embed)

# ── /heist ─────────────────────────────────────────────────────────────────
@bot.tree.command(name="heist", description="Start a coin heist — get members to join!")
@app_commands.describe(pot="Total coins in the heist pot")
async def heist(interaction: discord.Interaction, pot: int = 1000):
    if interaction.guild_id in active_heists:
        await interaction.response.send_message("❌ A heist is already active!", ephemeral=True)
        return
    db.ensure_user(interaction.guild_id, interaction.user.id)

    class HeistView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.members = [interaction.user]

        @discord.ui.button(label="Join Heist", style=discord.ButtonStyle.danger, emoji="⚔️")
        async def join(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            if btn_interaction.user in self.members:
                await btn_interaction.response.send_message("❌ Already joined!", ephemeral=True)
                return
            self.members.append(btn_interaction.user)
            await btn_interaction.response.send_message(f"✅ Joined the heist! ({len(self.members)}/5 members)", ephemeral=True)
            if len(self.members) >= 5:
                await self.finish(btn_interaction)

        async def on_timeout(self):
            await self.finish(None)

        async def finish(self, btn_interaction):
            self.stop()
            if interaction.guild_id in active_heists:
                del active_heists[interaction.guild_id]
            if len(self.members) >= 3:
                share = pot // len(self.members)
                names = []
                for m in self.members:
                    db.ensure_user(interaction.guild_id, m.id)
                    db.add_coins(interaction.guild_id, m.id, share)
                    names.append(m.display_name)
                ch = get_animus(interaction.guild)
                result = (
                    f"⚔️ **Heist successful!** {len(self.members)} members cracked the vault!\n"
                    f"💰 Each gets **{share:,} coins**!\n"
                    f"👥 {', '.join(names)}"
                )
                if ch:
                    await ch.send(result)
            else:
                ch = get_animus(interaction.guild)
                if ch:
                    await ch.send(f"❌ Heist failed! Not enough members joined ({len(self.members)}/3 needed).")

    view = HeistView()
    active_heists[interaction.guild_id] = True
    embed = discord.Embed(title="⚔️ Coin Heist!", color=0xe74c3c)
    embed.description = (
        f"**{interaction.user.display_name}** started a heist!\n"
        f"💰 Pot: **{pot:,} coins**\n"
        f"👥 Need at least **3 members** to join!\n"
        f"⏳ 60 seconds to join!"
    )
    await interaction.response.send_message(embed=embed, view=view)

# ── Admin commands ─────────────────────────────────────────────────────────
@bot.tree.command(name="additem", description="[Admin] Add an item to the shop")
@app_commands.describe(name="Item name", role="Role to grant", price="Cost in coins", duration_days="Days until expires (0=permanent)")
@app_commands.checks.has_permissions(administrator=True)
async def additem(interaction: discord.Interaction, name: str, role: discord.Role, price: int, duration_days: int = 0):
    db.add_shop_item(interaction.guild_id, name, role.id, role.name, price, duration_days or None)
    await interaction.response.send_message(
        f"✅ Added **{name}** → {role.mention} for **{price:,} coins**."
    )

@bot.tree.command(name="removeitem", description="[Admin] Remove an item from the shop")
@app_commands.describe(name="Item name to remove")
@app_commands.checks.has_permissions(administrator=True)
async def removeitem(interaction: discord.Interaction, name: str):
    removed = db.remove_shop_item(interaction.guild_id, name)
    if removed:
        await interaction.response.send_message(f"🗑️ **{name}** removed.")
    else:
        await interaction.response.send_message(f"❌ Item **{name}** not found.", ephemeral=True)

@bot.tree.command(name="grantcoins", description="[Admin] Grant coins to a member")
@app_commands.describe(member="Member to reward", amount="Coins to grant")
@app_commands.checks.has_permissions(administrator=True)
async def grantcoins(interaction: discord.Interaction, member: discord.Member, amount: int):
    db.ensure_user(interaction.guild_id, member.id)
    new_bal = db.add_coins(interaction.guild_id, member.id, amount)
    db.log_action(interaction.guild_id, interaction.user.id, "ADMIN_GRANT", f"Granted {amount} to {member.display_name}", amount)
    await interaction.response.send_message(f"✅ Granted **{amount:,} coins** to {member.mention}. Balance: **{new_bal:,}**.")

@bot.tree.command(name="removecoins", description="[Admin] Remove coins from a member")
@app_commands.describe(member="Member", amount="Coins to remove")
@app_commands.checks.has_permissions(administrator=True)
async def removecoins(interaction: discord.Interaction, member: discord.Member, amount: int):
    db.ensure_user(interaction.guild_id, member.id)
    balance = db.get_balance(interaction.guild_id, member.id)
    amount = min(amount, balance)
    new_bal = db.deduct_coins(interaction.guild_id, member.id, amount)
    db.log_action(interaction.guild_id, interaction.user.id, "ADMIN_REMOVE", f"Removed {amount} from {member.display_name}", -amount)
    await interaction.response.send_message(f"✅ Removed **{amount:,} coins** from {member.mention}. Balance: **{new_bal:,}**.")

@bot.tree.command(name="resetcheckin", description="[Admin] Reset daily checkin for a member")
@app_commands.describe(member="Member to reset")
@app_commands.checks.has_permissions(administrator=True)
async def resetcheckin(interaction: discord.Interaction, member: discord.Member):
    db.ensure_user(interaction.guild_id, member.id)
    db.reset_checkin(interaction.guild_id, member.id)
    await interaction.response.send_message(f"✅ Checkin reset for {member.mention}.")

@bot.tree.command(name="setrate", description="[Admin] Set coin earn rates")
@app_commands.describe(message_coins="Per message", checkin_coins="Daily checkin", voice_coins="Per minute in VC")
@app_commands.checks.has_permissions(administrator=True)
async def setrate(interaction: discord.Interaction, message_coins: int = None, checkin_coins: int = None, voice_coins: int = None):
    changes = []
    if message_coins is not None:
        db.set_config(interaction.guild_id, "message_coins", message_coins)
        changes.append(f"Message: **{message_coins}**")
    if checkin_coins is not None:
        db.set_config(interaction.guild_id, "checkin_coins", checkin_coins)
        changes.append(f"Checkin: **{checkin_coins}**")
    if voice_coins is not None:
        db.set_config(interaction.guild_id, "voice_coins", voice_coins)
        changes.append(f"Voice/min: **{voice_coins}**")
    if changes:
        await interaction.response.send_message("⚙️ Rates updated:\n" + "\n".join(changes))
    else:
        await interaction.response.send_message("⚠️ No values provided.", ephemeral=True)

@bot.tree.command(name="logs", description="[Admin] View recent bot activity")
@app_commands.describe(limit="How many entries (default 50, max 100)")
@app_commands.checks.has_permissions(administrator=True)
async def logs(interaction: discord.Interaction, limit: int = 50):
    limit = min(limit, 100)
    rows = db.get_logs(interaction.guild_id, limit)
    if not rows:
        await interaction.response.send_message("📋 No activity yet.", ephemeral=True)
        return
    action_icons = {"CHECKIN":"✅","PURCHASE":"🛍️","GIVE":"💸","ADMIN_GRANT":"⚙️",
                    "ADMIN_REMOVE":"❌","ADMIN_RESET":"🔄","ROB":"🦹","COINFLIP":"🪙"}
    embed = discord.Embed(title="📋 Activity Log", color=0x5b4a9e)
    lines = []
    for row in rows:
        member = interaction.guild.get_member(row["user_id"])
        name = member.display_name if member else f"User {row['user_id']}"
        icon = action_icons.get(row["action"], "•")
        coins_str = f" (+{row['coins']} 💰)" if row["coins"] > 0 else (f" ({row['coins']} 💰)" if row["coins"] < 0 else "")
        created = datetime.fromisoformat(row["created_at"])
        diff = datetime.utcnow() - created
        if diff.total_seconds() < 60: time_str = "just now"
        elif diff.total_seconds() < 3600: time_str = f"{int(diff.total_seconds()//60)}m ago"
        elif diff.days == 0: time_str = f"{int(diff.total_seconds()//3600)}h ago"
        else: time_str = f"{diff.days}d ago"
        lines.append(f"{icon} **{name}** — {row['detail']}{coins_str} · *{time_str}*")
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
        await interaction.response.send_message("❌ You need **Administrator** permission.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Error: {error}", ephemeral=True)

# ── Run ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ DISCORD_TOKEN not found. Make sure your .env file exists.")
        exit(1)
    bot.run(token)
