import sqlite3
from datetime import datetime


class Database:
    def __init__(self, path: str):
        self.path = path

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self):
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    guild_id        INTEGER NOT NULL,
                    user_id         INTEGER NOT NULL,
                    coins           INTEGER DEFAULT 0,
                    bank            INTEGER DEFAULT 0,
                    first_deposit   INTEGER DEFAULT 0,
                    last_checkin    TEXT,
                    checkin_streak  INTEGER DEFAULT 0,
                    last_message    TEXT,
                    xp              INTEGER DEFAULT 0,
                    level           INTEGER DEFAULT 0,
                    prestige        INTEGER DEFAULT 0,
                    last_rob        TEXT,
                    mmr             INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS shop_items (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id      INTEGER NOT NULL,
                    name          TEXT NOT NULL,
                    role_id       INTEGER NOT NULL,
                    role_name     TEXT NOT NULL,
                    price         INTEGER NOT NULL,
                    duration_days INTEGER
                );

                CREATE TABLE IF NOT EXISTS purchases (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id     INTEGER NOT NULL,
                    user_id      INTEGER NOT NULL,
                    item_id      INTEGER NOT NULL,
                    purchased_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS config (
                    guild_id INTEGER NOT NULL,
                    key      TEXT NOT NULL,
                    value    TEXT NOT NULL,
                    PRIMARY KEY (guild_id, key)
                );

                CREATE TABLE IF NOT EXISTS activity_logs (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id   INTEGER NOT NULL,
                    user_id    INTEGER NOT NULL,
                    action     TEXT NOT NULL,
                    detail     TEXT,
                    coins      INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS badges (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id  INTEGER NOT NULL,
                    user_id   INTEGER NOT NULL,
                    badge     TEXT NOT NULL,
                    earned_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS trivia (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id   INTEGER NOT NULL,
                    active     INTEGER DEFAULT 0,
                    question   TEXT,
                    answer     TEXT,
                    reward     INTEGER DEFAULT 200,
                    started_at TEXT DEFAULT (datetime('now'))
                );
            """)

    # ── Config ─────────────────────────────────────────────────────────────
    def get_config(self, guild_id, key, default):
        with self._conn() as c:
            row = c.execute("SELECT value FROM config WHERE guild_id=? AND key=?", (guild_id, key)).fetchone()
            if not row: return default
            try: return int(row["value"])
            except ValueError: return row["value"]

    def set_config(self, guild_id, key, value):
        with self._conn() as c:
            c.execute("INSERT INTO config(guild_id,key,value) VALUES(?,?,?) ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value",
                      (guild_id, key, str(value)))

    # ── User ───────────────────────────────────────────────────────────────
    def ensure_user(self, guild_id, user_id):
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO users(guild_id,user_id) VALUES(?,?)", (guild_id, user_id))

    def get_user(self, guild_id, user_id):
        with self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
            return dict(row) if row else {}

    def get_balance(self, guild_id, user_id):
        with self._conn() as c:
            row = c.execute("SELECT coins FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
            return row["coins"] if row else 0

    def add_coins(self, guild_id, user_id, amount):
        with self._conn() as c:
            c.execute("UPDATE users SET coins=coins+? WHERE guild_id=? AND user_id=?", (amount, guild_id, user_id))
            return c.execute("SELECT coins FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()["coins"]

    def deduct_coins(self, guild_id, user_id, amount):
        return self.add_coins(guild_id, user_id, -amount)

    # ── MMR ────────────────────────────────────────────────────────────────
    MMR_RANKS = [
        (0,    "🪣 Plastic"),
        (100,  "🪵 Wood"),
        (200,  "⚙️ Iron"),
        (300,  "🥉 Bronze"),
        (400,  "🥈 Silver"),
        (500,  "🥇 Gold"),
        (600,  "💎 Diamond"),
        (700,  "🔮 Platinum"),
        (800,  "⚡ Ascendant"),
        (900,  "💀 Immortal"),
        (1000, "🌟 Radiant"),
        (1200, "👾 Weld9a7ba"),
    ]

    def get_rank(self, mmr):
        rank = self.MMR_RANKS[0][1]
        for threshold, name in self.MMR_RANKS:
            if mmr >= threshold:
                rank = name
        return rank

    def update_mmr(self, guild_id, user_id, delta):
        with self._conn() as c:
            old = c.execute("SELECT mmr FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
            old_mmr = old["mmr"] if old else 0
            new_mmr = max(0, old_mmr + delta)
            c.execute("UPDATE users SET mmr=? WHERE guild_id=? AND user_id=?", (new_mmr, guild_id, user_id))
            return old_mmr, new_mmr

    def get_mmr_leaderboard(self, guild_id):
        with self._conn() as c:
            rows = c.execute("SELECT user_id, mmr FROM users WHERE guild_id=? ORDER BY mmr DESC LIMIT 10", (guild_id,)).fetchall()
            return [dict(r) for r in rows]

    # ── Banking ────────────────────────────────────────────────────────────
    MIN_WALLET   = 500   # must always keep 500 in wallet
    FIRST_DEP    = 1000  # first deposit minimum
    MIN_DEP      = 200   # subsequent deposit minimum

    def deposit(self, guild_id, user_id, amount):
        with self._conn() as c:
            row = c.execute("SELECT coins, bank, first_deposit FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
            coins, bank, first = row["coins"], row["bank"], row["first_deposit"]
            min_dep = self.FIRST_DEP if not first else self.MIN_DEP
            if amount < min_dep:
                return {"success": False, "reason": f"Minimum deposit is **{min_dep:,} coins**{'  (first deposit)' if not first else ''}."}
            if coins - amount < self.MIN_WALLET:
                return {"success": False, "reason": f"You must keep at least **{self.MIN_WALLET:,} coins** in your wallet."}
            c.execute("UPDATE users SET coins=coins-?, bank=bank+?, first_deposit=1 WHERE guild_id=? AND user_id=?",
                      (amount, amount, guild_id, user_id))
            row2 = c.execute("SELECT coins, bank FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
            return {"success": True, "wallet": row2["coins"], "bank": row2["bank"]}

    def withdraw(self, guild_id, user_id, amount):
        with self._conn() as c:
            row = c.execute("SELECT coins, bank FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
            if row["bank"] < amount:
                return {"success": False, "reason": f"You only have **{row['bank']:,} coins** in the bank."}
            c.execute("UPDATE users SET coins=coins+?, bank=bank-? WHERE guild_id=? AND user_id=?",
                      (amount, amount, guild_id, user_id))
            row2 = c.execute("SELECT coins, bank FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
            return {"success": True, "wallet": row2["wallet"] if "wallet" in row2.keys() else row2["coins"], "bank": row2["bank"]}

    def get_bank(self, guild_id, user_id):
        with self._conn() as c:
            row = c.execute("SELECT coins, bank FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
            return {"wallet": row["coins"], "bank": row["bank"]} if row else {"wallet": 0, "bank": 0}

    # ── XP & Levels ────────────────────────────────────────────────────────
    def xp_for_level(self, level):
        return 100 * (level + 1)

    def add_xp(self, guild_id, user_id, amount=10):
        with self._conn() as c:
            c.execute("UPDATE users SET xp=xp+? WHERE guild_id=? AND user_id=?", (amount, guild_id, user_id))
            row = c.execute("SELECT xp, level FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
            xp, level = row["xp"], row["level"]
            leveled_up = False
            while xp >= self.xp_for_level(level):
                xp -= self.xp_for_level(level)
                level += 1
                leveled_up = True
            c.execute("UPDATE users SET xp=?, level=? WHERE guild_id=? AND user_id=?", (xp, level, guild_id, user_id))
            return {"leveled_up": leveled_up, "level": level, "xp": xp}

    def prestige(self, guild_id, user_id):
        with self._conn() as c:
            row = c.execute("SELECT level, prestige FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
            if row["level"] < 20:
                return {"success": False, "level": row["level"]}
            new_prestige = row["prestige"] + 1
            c.execute("UPDATE users SET level=0, xp=0, prestige=? WHERE guild_id=? AND user_id=?",
                      (new_prestige, guild_id, user_id))
            return {"success": True, "prestige": new_prestige}

    # ── Badges ─────────────────────────────────────────────────────────────
    def award_badge(self, guild_id, user_id, badge):
        with self._conn() as c:
            if c.execute("SELECT id FROM badges WHERE guild_id=? AND user_id=? AND badge=?", (guild_id, user_id, badge)).fetchone():
                return False
            c.execute("INSERT INTO badges(guild_id,user_id,badge) VALUES(?,?,?)", (guild_id, user_id, badge))
            return True

    def get_badges(self, guild_id, user_id):
        with self._conn() as c:
            return [r["badge"] for r in c.execute("SELECT badge FROM badges WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchall()]

    def get_purchase_count(self, guild_id, user_id):
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) as cnt FROM purchases WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()["cnt"]

    # ── Earning ────────────────────────────────────────────────────────────
    def add_message_coins(self, guild_id, user_id):
        rate = self.get_config(guild_id, "message_coins", 5)
        now = datetime.utcnow()
        with self._conn() as c:
            row = c.execute("SELECT last_message FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
            last = datetime.fromisoformat(row["last_message"]) if row and row["last_message"] else None
            if last and (now - last).total_seconds() < 60:
                return False
            c.execute("UPDATE users SET coins=coins+?, last_message=? WHERE guild_id=? AND user_id=?",
                      (rate, now.isoformat(), guild_id, user_id))
            return True

    def add_voice_coins(self, guild_id, user_id):
        rate = self.get_config(guild_id, "voice_coins", 2)
        with self._conn() as c:
            c.execute("UPDATE users SET coins=coins+? WHERE guild_id=? AND user_id=?", (rate, guild_id, user_id))

    def daily_checkin(self, guild_id, user_id):
        base = self.get_config(guild_id, "checkin_coins", 100)
        now = datetime.utcnow()
        with self._conn() as c:
            row = c.execute("SELECT last_checkin, checkin_streak FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
            last = datetime.fromisoformat(row["last_checkin"]) if row["last_checkin"] else None
            if last:
                hours = (now - last).total_seconds() / 3600
                if hours < 24:
                    return {"success": False, "hours_left": int(24 - hours) + 1}
                streak = (row["checkin_streak"] + 1) if hours < 48 else 1
            else:
                streak = 1
            multiplier = 2 if streak > 0 and streak % 7 == 0 else 1
            earned = base * multiplier
            c.execute("UPDATE users SET coins=coins+?, last_checkin=?, checkin_streak=? WHERE guild_id=? AND user_id=?",
                      (earned, now.isoformat(), streak, guild_id, user_id))
            bal = c.execute("SELECT coins FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()["coins"]
            return {"success": True, "earned": earned, "streak": streak, "balance": bal}

    def reset_checkin(self, guild_id, user_id):
        with self._conn() as c:
            c.execute("UPDATE users SET last_checkin=NULL, checkin_streak=0 WHERE guild_id=? AND user_id=?", (guild_id, user_id))

    def can_rob(self, guild_id, user_id):
        with self._conn() as c:
            row = c.execute("SELECT last_rob FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
            if not row or not row["last_rob"]: return True, 0
            diff = (datetime.utcnow() - datetime.fromisoformat(row["last_rob"])).total_seconds()
            if diff < 3600: return False, int((3600 - diff) / 60)
            return True, 0

    def set_last_rob(self, guild_id, user_id):
        with self._conn() as c:
            c.execute("UPDATE users SET last_rob=? WHERE guild_id=? AND user_id=?", (datetime.utcnow().isoformat(), guild_id, user_id))

    # ── Shop ───────────────────────────────────────────────────────────────
    def get_shop_items(self, guild_id):
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM shop_items WHERE guild_id=? ORDER BY price", (guild_id,)).fetchall()]

    def get_item_by_name(self, guild_id, name):
        with self._conn() as c:
            row = c.execute("SELECT * FROM shop_items WHERE guild_id=? AND LOWER(name)=LOWER(?)", (guild_id, name)).fetchone()
            return dict(row) if row else None

    def add_shop_item(self, guild_id, name, role_id, role_name, price, duration_days=None):
        with self._conn() as c:
            c.execute("INSERT INTO shop_items(guild_id,name,role_id,role_name,price,duration_days) VALUES(?,?,?,?,?,?)",
                      (guild_id, name, role_id, role_name, price, duration_days))

    def remove_shop_item(self, guild_id, name):
        with self._conn() as c:
            return c.execute("DELETE FROM shop_items WHERE guild_id=? AND LOWER(name)=LOWER(?)", (guild_id, name)).rowcount > 0

    def log_purchase(self, guild_id, user_id, item_id):
        with self._conn() as c:
            c.execute("INSERT INTO purchases(guild_id,user_id,item_id) VALUES(?,?,?)", (guild_id, user_id, item_id))

    # ── Leaderboards ───────────────────────────────────────────────────────
    def get_leaderboard(self, guild_id):
        with self._conn() as c:
            return [(r["user_id"], r["coins"]) for r in
                    c.execute("SELECT user_id, coins FROM users WHERE guild_id=? ORDER BY coins DESC LIMIT 10", (guild_id,)).fetchall()]

    def get_level_leaderboard(self, guild_id):
        with self._conn() as c:
            return [dict(r) for r in
                    c.execute("SELECT user_id, level, xp, prestige FROM users WHERE guild_id=? ORDER BY prestige DESC, level DESC, xp DESC LIMIT 10", (guild_id,)).fetchall()]

    # ── Trivia ─────────────────────────────────────────────────────────────
    def start_trivia(self, guild_id, question, answer, reward):
        with self._conn() as c:
            c.execute("UPDATE trivia SET active=0 WHERE guild_id=?", (guild_id,))
            c.execute("INSERT INTO trivia(guild_id,active,question,answer,reward) VALUES(?,1,?,?,?)", (guild_id, question, answer, reward))

    def get_active_trivia(self, guild_id):
        with self._conn() as c:
            row = c.execute("SELECT * FROM trivia WHERE guild_id=? AND active=1", (guild_id,)).fetchone()
            return dict(row) if row else None

    def end_trivia(self, guild_id):
        with self._conn() as c:
            c.execute("UPDATE trivia SET active=0 WHERE guild_id=?", (guild_id,))

    # ── Logs ───────────────────────────────────────────────────────────────
    def log_action(self, guild_id, user_id, action, detail="", coins=0):
        with self._conn() as c:
            c.execute("INSERT INTO activity_logs(guild_id,user_id,action,detail,coins) VALUES(?,?,?,?,?)",
                      (guild_id, user_id, action, detail, coins))

    def get_logs(self, guild_id, limit=100):
        with self._conn() as c:
            return [dict(r) for r in
                    c.execute("SELECT * FROM activity_logs WHERE guild_id=? ORDER BY created_at DESC LIMIT ?", (guild_id, limit)).fetchall()]

    def get_daily_stats(self, guild_id):
        with self._conn() as c:
            top = c.execute("SELECT user_id, coins FROM users WHERE guild_id=? ORDER BY coins DESC LIMIT 1", (guild_id,)).fetchone()
            purchases = c.execute("SELECT COUNT(*) as cnt FROM purchases WHERE guild_id=? AND purchased_at >= datetime('now','-1 day')", (guild_id,)).fetchone()["cnt"]
            active = c.execute("SELECT COUNT(*) as cnt FROM users WHERE guild_id=? AND last_message >= datetime('now','-1 day')", (guild_id,)).fetchone()["cnt"]
            total = c.execute("SELECT SUM(coins) as t FROM users WHERE guild_id=?", (guild_id,)).fetchone()["t"] or 0
            return {"top_user": dict(top) if top else None, "purchases_today": purchases, "active_today": active, "total_coins": total}
