# 🛍️ RoleShop Discord Bot

A Discord economy bot where members earn coins through activity and spend them in a shop to unlock custom roles and perks.

---

## ⚡ Quick Setup

### 1. Create a Discord Bot

1. Go to https://discord.com/developers/applications
2. Click **New Application** → give it a name
3. Go to **Bot** tab → click **Add Bot**
4. Under **Privileged Gateway Intents**, enable:
   - ✅ Server Members Intent
   - ✅ Message Content Intent
5. Copy your **Bot Token**

### 2. Invite the Bot to Your Server

In the Developer Portal → **OAuth2 → URL Generator**:
- Scopes: `bot`, `applications.commands`
- Bot Permissions: `Manage Roles`, `Send Messages`, `Read Message History`

Open the generated URL and invite the bot.

### 3. Install & Run

```bash
# Clone or download the files, then:
pip install -r requirements.txt

# Set your bot token
export DISCORD_TOKEN="your-token-here"   # Linux/Mac
set DISCORD_TOKEN=your-token-here        # Windows

# Run the bot
python bot.py
```

---

## 💬 Commands

### Member Commands
| Command | Description |
|---|---|
| `/balance` | Check your coin balance |
| `/checkin` | Daily check-in for coins (streak bonuses!) |
| `/shop` | Browse the role shop |
| `/buy <item>` | Purchase a role from the shop |
| `/give @user <amount>` | Transfer coins to another member |
| `/leaderboard` | Top coin earners |

### Admin Commands
| Command | Description |
|---|---|
| `/additem <name> <role> <price> [days]` | Add a role to the shop |
| `/removeitem <name>` | Remove an item from the shop |
| `/grantcoins @user <amount>` | Give coins to a member |
| `/setrate [message] [checkin] [voice]` | Configure earn rates |

---

## 💰 Default Earn Rates

| Activity | Coins |
|---|---|
| Message (60s cooldown) | 5 coins |
| Daily check-in | 100 coins |
| Check-in (7-day streak) | 200 coins |
| Voice channel (per minute) | 2 coins |

Adjust with `/setrate` anytime.

---

## 🗂️ File Structure

```
roleshop/
├── bot.py          # Main bot logic & slash commands
├── database.py     # SQLite database layer
├── requirements.txt
└── README.md
```

The bot creates `roleshop.db` automatically on first run.

---

## 🚀 Deploying 24/7

| Platform | Notes |
|---|---|
| **Railway** | Free tier, easiest — connect GitHub repo |
| **Fly.io** | Free tier, good for small bots |
| **VPS (DigitalOcean/Hetzner)** | Full control, run with `screen` or `systemd` |

---

## 🔧 Tips

- Make sure the bot's role is **above** the roles it needs to assign in Server Settings → Roles
- Use `/additem "Red Name" @RedRole 500` to add your first shop item
- Adjust prices with `/removeitem` + `/additem` to rebalance economy
