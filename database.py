import sqlite3
from datetime import datetime, timedelta


class Database:
    def __init__(self, path: str):
        self.path = path

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Schema ─────────────────────────────────────────────────────────────
    def init(self):
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    guild_id    INTEGER NOT NULL,
                    user_id     INTEGER NOT NULL,
                    coins       INTEGER DEFAULT 0,
                    last_checkin TEXT,
                    checkin_streak INTEGER DEFAULT 0,
                    last_message TEXT,
                    PRIMARY KEY (guild_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS shop_items (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    INTEGER NOT NULL,
                    name        TEXT NOT NULL,
                    role_id     INTEGER NOT NULL,
                    role_name   TEXT NOT NULL,
                    price       INTEGER NOT NULL,
                    duration_days INTEGER
                );

                CREATE TABLE IF NOT EXISTS purchases (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    INTEGER NOT NULL,
                    user_id     INTEGER NOT NULL,
                    item_id     INTEGER NOT NULL,
                    purchased_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS config (
                    guild_id    INTEGER NOT NULL,
                    key         TEXT NOT NULL,
                    value       TEXT NOT NULL,
                    PRIMARY KEY (guild_id, key)
                );

                CREATE TABLE IF NOT EXISTS activity_logs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    INTEGER NOT NULL,
                    user_id     INTEGER NOT NULL,
                    action      TEXT NOT NULL,
                    detail      TEXT,
                    coins       INTEGER DEFAULT 0,
                    created_at  TEXT DEFAULT (datetime('now'))
                );
            """)

    # ── Config helpers ─────────────────────────────────────────────────────
    def get_config(self, guild_id: int, key: str, default):
        with self._conn() as c:
            row = c.execute(
                "SELECT value FROM config WHERE guild_id=? AND key=?", (guild_id, key)
            ).fetchone()
            return int(row["value"]) if row else default

    def set_config(self, guild_id: int, key: str, value):
        with self._conn() as c:
            c.execute(
                "INSERT INTO config(guild_id,key,value) VALUES(?,?,?) "
                "ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value",
                (guild_id, key, str(value))
            )

    # ── User helpers ───────────────────────────────────────────────────────
    def ensure_user(self, guild_id: int, user_id: int):
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO users(guild_id,user_id) VALUES(?,?)",
                (guild_id, user_id)
            )

    def get_balance(self, guild_id: int, user_id: int) -> int:
        with self._conn() as c:
            row = c.execute(
                "SELECT coins FROM users WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)
            ).fetchone()
            return row["coins"] if row else 0

    def add_coins(self, guild_id: int, user_id: int, amount: int) -> int:
        with self._conn() as c:
            c.execute(
                "UPDATE users SET coins = coins + ? WHERE guild_id=? AND user_id=?",
                (amount, guild_id, user_id)
            )
            return c.execute(
                "SELECT coins FROM users WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)
            ).fetchone()["coins"]

    def deduct_coins(self, guild_id: int, user_id: int, amount: int) -> int:
        return self.add_coins(guild_id, user_id, -amount)

    # ── Earning ────────────────────────────────────────────────────────────
    def add_message_coins(self, guild_id: int, user_id: int) -> bool:
        """Award coins for a message. Returns True if coins were awarded (respects 60s cooldown)."""
        rate = self.get_config(guild_id, "message_coins", 5)
        now = datetime.utcnow()
        with self._conn() as c:
            row = c.execute(
                "SELECT last_message FROM users WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)
            ).fetchone()
            last = datetime.fromisoformat(row["last_message"]) if row and row["last_message"] else None
            if last and (now - last).total_seconds() < 60:
                return False
            c.execute(
                "UPDATE users SET coins=coins+?, last_message=? WHERE guild_id=? AND user_id=?",
                (rate, now.isoformat(), guild_id, user_id)
            )
            return True

    def add_voice_coins(self, guild_id: int, user_id: int):
        rate = self.get_config(guild_id, "voice_coins", 2)
        with self._conn() as c:
            c.execute(
                "UPDATE users SET coins=coins+? WHERE guild_id=? AND user_id=?",
                (rate, guild_id, user_id)
            )

    def daily_checkin(self, guild_id: int, user_id: int) -> dict:
        base = self.get_config(guild_id, "checkin_coins", 100)
        now = datetime.utcnow()
        with self._conn() as c:
            row = c.execute(
                "SELECT last_checkin, checkin_streak, coins FROM users WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)
            ).fetchone()

            last = datetime.fromisoformat(row["last_checkin"]) if row["last_checkin"] else None

            if last:
                hours_since = (now - last).total_seconds() / 3600
                if hours_since < 24:
                    hours_left = int(24 - hours_since) + 1
                    return {"success": False, "hours_left": hours_left}
                # Streak logic: within 48h = continue, else reset
                streak = (row["checkin_streak"] + 1) if hours_since < 48 else 1
            else:
                streak = 1

            # Streak multiplier: every 7 days = 2x
            multiplier = 2 if streak % 7 == 0 else 1
            earned = base * multiplier

            c.execute(
                "UPDATE users SET coins=coins+?, last_checkin=?, checkin_streak=? "
                "WHERE guild_id=? AND user_id=?",
                (earned, now.isoformat(), streak, guild_id, user_id)
            )
            new_balance = c.execute(
                "SELECT coins FROM users WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)
            ).fetchone()["coins"]

            return {"success": True, "earned": earned, "streak": streak, "balance": new_balance}

    # ── Shop ───────────────────────────────────────────────────────────────
    def get_shop_items(self, guild_id: int) -> list:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM shop_items WHERE guild_id=? ORDER BY price", (guild_id,)
            ).fetchall()]

    def get_item_by_name(self, guild_id: int, name: str) -> dict | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM shop_items WHERE guild_id=? AND LOWER(name)=LOWER(?)",
                (guild_id, name)
            ).fetchone()
            return dict(row) if row else None

    def add_shop_item(self, guild_id, name, role_id, role_name, price, duration_days=None):
        with self._conn() as c:
            c.execute(
                "INSERT INTO shop_items(guild_id,name,role_id,role_name,price,duration_days) "
                "VALUES(?,?,?,?,?,?)",
                (guild_id, name, role_id, role_name, price, duration_days)
            )

    def remove_shop_item(self, guild_id: int, name: str) -> bool:
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM shop_items WHERE guild_id=? AND LOWER(name)=LOWER(?)",
                (guild_id, name)
            )
            return cur.rowcount > 0

    def log_purchase(self, guild_id: int, user_id: int, item_id: int):
        with self._conn() as c:
            c.execute(
                "INSERT INTO purchases(guild_id,user_id,item_id) VALUES(?,?,?)",
                (guild_id, user_id, item_id)
            )

    # ── Leaderboard ────────────────────────────────────────────────────────
    def get_leaderboard(self, guild_id: int) -> list:
        with self._conn() as c:
            rows = c.execute(
                "SELECT user_id, coins FROM users WHERE guild_id=? ORDER BY coins DESC LIMIT 10",
                (guild_id,)
            ).fetchall()
            return [(r["user_id"], r["coins"]) for r in rows]

    def reset_checkin(self, guild_id: int, user_id: int):
        with self._conn() as c:
            c.execute(
                "UPDATE users SET last_checkin=NULL, checkin_streak=0 WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)
            )

    # ── Activity Logs ──────────────────────────────────────────────────────
    def log_action(self, guild_id: int, user_id: int, action: str, detail: str = "", coins: int = 0):
        with self._conn() as c:
            c.execute(
                "INSERT INTO activity_logs(guild_id,user_id,action,detail,coins) VALUES(?,?,?,?,?)",
                (guild_id, user_id, action, detail, coins)
            )

    def get_logs(self, guild_id: int, limit: int = 100) -> list:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM activity_logs WHERE guild_id=? ORDER BY created_at DESC LIMIT ?",
                (guild_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]
