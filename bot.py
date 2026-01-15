import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import asyncio
import sqlite3
import json
from datetime import datetime, timezone, timedelta
import random

# === НАСТРОЙКИ ===
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("❌ Файл .env должен содержать DISCORD_TOKEN=ваш_токен")

OWNER_ID = 1425864152563585158

# === ID РОЛЕЙ ===
LEADER_ROLE_ID = 605829120974258203
DEPUTY_LEADER_ROLE_ID = 1220118511549026364
FAMILY_MEMBER_ROLE_ID = 1460692962139836487

FAMILY_ROLES = {
    "member": FAMILY_MEMBER_ROLE_ID,
    "main_staff": 1460692954812387472,
    "recruit": 1460692951494688967,
    "high_staff": 1460692948458143848,
    "deputy_leader": DEPUTY_LEADER_ROLE_ID,
    "leader": LEADER_ROLE_ID
}

# === МАГАЗИН РОЛЕЙ ===
SHOP_ROLES = {
    1461403128330190982: 1_000_000,      # ЛУДИК
    1461403410124374282: 2_500_000,      # АЛЬТУХА
    1461403437756584126: 2_500_000,      # МЕРИКРИСТМАС
    1461403169342099626: 10_000_000,     # ПОВЕЛИТЕЛЬ
    1461403469175849137: 50_000_000,     # БИГ БОСС
    1461403498053767219: 100_000_000,    # СУПЕР БОСС
    1461403526302531686: 150_000_000,    # КОРОЛЬ ПЛАНЕТЫ
    1461403355145572444: 500_000_000,    # ТОП 1 ФОРБС
    1461403584360091651: 10_000_000_000   # РОЛЬ С ПРАВАМИ МОДЕРАТОРА
}

MANAGE_APPLICATIONS_ROLES = [
    FAMILY_ROLES["recruit"],
    FAMILY_ROLES["high_staff"],
    FAMILY_ROLES["deputy_leader"],
    FAMILY_ROLES["leader"]
]

LOG_CHANNEL_ID = 1461033301170192414

os.makedirs("backups", exist_ok=True)

# === НАСТРОЙКА БОТА ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents)

# === ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ===
def init_db():
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()

    # Голосовые сессии
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS voice_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT
        )
    ''')

    # Чёрный список
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS family_blacklist (
            user_id INTEGER PRIMARY KEY,
            reason TEXT NOT NULL,
            added_by INTEGER NOT NULL,
            added_at TEXT NOT NULL
        )
    ''')

    # Заявки
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            submitted_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        )
    ''')

    # Профили
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS profiles (
            user_id INTEGER PRIMARY KEY,
            nickname TEXT,
            static_id TEXT
        )
    ''')

    # Казино
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS casino_balance (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 10000
        )
    ''')

    # Ворк-таймер
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS work_timer (
            user_id INTEGER PRIMARY KEY,
            last_work TEXT
        )
    ''')

    conn.commit()
    conn.close()

init_db()

# === ФУНКЦИИ ДЛЯ РАБОТЫ С БД ===
def get_balance(user_id: int) -> int:
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM casino_balance WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result is None:
        cursor.execute("INSERT INTO casino_balance (user_id, balance) VALUES (?, 10000)", (user_id,))
        conn.commit()
        result = (10000,)
    conn.close()
    return result[0]

def set_balance(user_id: int, amount: int):
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO casino_balance (user_id, balance) VALUES (?, ?)", (user_id, max(0, amount)))
    conn.commit()
    conn.close()

def get_top_casino() -> list:
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, balance FROM casino_balance ORDER BY balance DESC LIMIT 10")
    result = cursor.fetchall()
    conn.close()
    return result

def can_work(user_id: int) -> bool:
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT last_work FROM work_timer WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    if not result:
        return True
    last_work = datetime.fromisoformat(result[0].replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - last_work > timedelta(hours=2)

def update_work_time(user_id: int):
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute("INSERT OR REPLACE INTO work_timer (user_id, last_work) VALUES (?, ?)", (user_id, now))
    conn.commit()
    conn.close()

def add_voice_session(user_id: int, channel_id: int, start_time: datetime):
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO voice_sessions (user_id, channel_id, start_time, end_time) VALUES (?, ?, ?, ?)",
        (user_id, channel_id, start_time.isoformat(), None)
    )
    conn.commit()
    conn.close()

def end_voice_session(user_id: int, end_time: datetime):
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE voice_sessions SET end_time = ? WHERE user_id = ? AND end_time IS NULL",
        (end_time.isoformat(), user_id)
    )
    conn.commit()
    conn.close()

def get_user_sessions(user_id: int):
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT channel_id, start_time, end_time FROM voice_sessions WHERE user_id = ? ORDER BY start_time DESC LIMIT 20",
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows

def add_to_family_blacklist(user_id: int, reason: str, added_by: int):
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        "INSERT OR REPLACE INTO family_blacklist (user_id, reason, added_by, added_at) VALUES (?, ?, ?, ?)",
        (user_id, reason, added_by, now)
    )
    conn.commit()
    conn.close()

def remove_from_family_blacklist(user_id: int):
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM family_blacklist WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def is_in_family_blacklist(user_id: int) -> bool:
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM family_blacklist WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def get_blacklist_reason(user_id: int) -> str:
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT reason FROM family_blacklist WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else "Не указана"

def can_submit_application(user_id: int) -> bool:
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    one_day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    cursor.execute(
        "SELECT 1 FROM applications WHERE user_id = ? AND submitted_at > ?",
        (user_id, one_day_ago)
    )
    result = cursor.fetchone()
    conn.close()
    return result is None

def record_application(user_id: int):
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        "INSERT INTO applications (user_id, submitted_at) VALUES (?, ?)",
        (user_id, now)
    )
    conn.commit()
    conn.close()

def get_pending_applications_count() -> int:
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM applications WHERE status = 'pending'")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_last_application_time() -> str:
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT submitted_at FROM applications ORDER BY submitted_at DESC LIMIT 1")
    result = cursor.fetchone()
    conn.close()
    if not result:
        return "Никогда"
    dt = datetime.fromisoformat(result[0].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    diff = now - dt
    hours = int(diff.total_seconds() // 3600)
    if hours < 1:
        return "менее часа назад"
    elif hours == 1:
        return "1 час назад"
    else:
        return f"{hours} часов назад"

def save_profile(user_id: int, nickname: str, static_id: str):
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO profiles (user_id, nickname, static_id) VALUES (?, ?, ?)",
        (user_id, nickname, static_id)
    )
    conn.commit()
    conn.close()

def get_profile(user_id: int):
    conn = sqlite3.connect("voice_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT nickname, static_id FROM profiles WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result

async def log_action(guild, action: str, details: str, color=0x2b2d31):
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed = discord.Embed(
            title="📋 Аудит действий",
            description=f"**Действие:** {action}\n{details}",
            color=color,
            timestamp=discord.utils.utcnow()
        )
        await log_channel.send(embed=embed)

def has_any_role(member: discord.Member, role_ids: list) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(role.id in role_ids for role in member.roles)

def backup_guild(guild: discord.Guild):
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "guild_id": guild.id,
        "guild_name": guild.name,
        "members": []
    }

    for member in guild.members:
        if member.bot:
            continue
        roles = [role.id for role in member.roles if role.id in FAMILY_ROLES.values()]
        if roles:
            data["members"].append({
                "user_id": member.id,
                "name": member.name,
                "display_name": member.display_name,
                "roles": roles,
                "joined_at": member.joined_at.isoformat() if member.joined_at else None
            })

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    filename = f"backups/backup_{timestamp}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    cutoff = datetime.now() - timedelta(days=30)
    for file in os.listdir("backups"):
        try:
            file_time = datetime.strptime(file.replace("backup_", "").replace(".json", ""), "%Y-%m-%d_%H-%M")
            if file_time < cutoff:
                os.remove(f"backups/{file}")
        except:
            pass

async def change_status():
    while True:
        pending = get_pending_applications_count()
        activity = discord.Game(f"Заявок: {pending}")
        await bot.change_presence(activity=activity)
        await asyncio.sleep(60)

async def backup_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        for guild in bot.guilds:
            backup_guild(guild)
        await asyncio.sleep(3600)

# === СОБЫТИЯ ===
@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    print(f'💡 Отправьте "!sync" для синхронизации слэш-команд.')
    bot.loop.create_task(change_status())
    bot.loop.create_task(backup_task())

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    now = datetime.now(timezone.utc)
    if before.channel and not after.channel:
        end_voice_session(member.id, now)
    elif before.channel and after.channel and before.channel != after.channel:
        end_voice_session(member.id, now)
        add_voice_session(member.id, after.channel.id, now)
    elif not before.channel and after.channel:
        add_voice_session(member.id, after.channel.id, now)

@bot.event
async def on_member_update(before, after):
    added_roles = set(after.roles) - set(before.roles)
    if not added_roles:
        return

    family_role_ids = set(FAMILY_ROLES.values())
    given_family_roles = [r for r in added_roles if r.id in family_role_ids]
    if not given_family_roles or not is_in_family_blacklist(after.id):
        return

    await after.remove_roles(*given_family_roles)

    issuer = None
    try:
        async for entry in after.guild.audit_logs(action=discord.AuditLogAction.member_role_update, limit=10):
            if entry.target.id == after.id and any(r.id in family_role_ids for r in getattr(entry.after, 'roles', [])):
                issuer = entry.user
                break
    except Exception:
        pass

    issuer_roles_to_remove = []
    if issuer and issuer != bot.user and issuer != after:
        issuer_roles_to_remove = [r for r in issuer.roles if r.id in family_role_ids]
        if issuer_roles_to_remove:
            await issuer.remove_roles(*issuer_roles_to_remove)

    reason = get_blacklist_reason(after.id)
    details = f"Участник: {after.mention} (ID: {after.id})\nПричина ЧС: {reason}"
    if issuer:
        details += f"\nВыдавший: {issuer.mention} (ID: {issuer.id})"
        if issuer_roles_to_remove:
            details += f"\nСняты роли с выдавшего: {', '.join(r.name for r in issuer_roles_to_remove)}"

    await log_action(after.guild, "Попытка выдать роль участнику из ЧС", details, color=0xff0000)

# === !sync ===
@bot.command(name="sync")
async def sync_command(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("❌ Только владелец может использовать эту команду.")
        return
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"✅ Синхронизировано {len(synced)} слэш-команд.")
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {e}")

# === /чс_семьи ===
@bot.tree.command(name="чс_семьи", description="Выдать чёрный список семьи участнику")
@app_commands.describe(user_id="ID пользователя", reason="Причина ЧС")
async def blacklist_family(interaction: discord.Interaction, user_id: str, reason: str):
    if FAMILY_ROLES["deputy_leader"] not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("❌ Эта команда доступна только Заместителю Лидера.", ephemeral=True)
        return

    try:
        uid = int(user_id)
    except ValueError:
        await interaction.response.send_message("❌ ID должен быть числом.", ephemeral=True)
        return

    member = interaction.guild.get_member(uid)
    if not member:
        await interaction.response.send_message("❌ Пользователь не найден на сервере.", ephemeral=True)
        return

    roles_to_remove = [interaction.guild.get_role(rid) for rid in FAMILY_ROLES.values()]
    roles_to_remove = [r for r in roles_to_remove if r and r in member.roles]
    if roles_to_remove:
        await member.remove_roles(*roles_to_remove)

    add_to_family_blacklist(uid, reason, interaction.user.id)
    await log_action(
        interaction.guild,
        "Выдача ЧС семьи",
        f"Участник: {member.mention} (ID: {uid})\nПричина: {reason}\nВыдал: {interaction.user.mention}",
        color=0xff0000
    )

    embed = discord.Embed(
        title="🚫 Чёрный список семьи",
        description=f"Пользователь {member.mention} добавлен в ЧС семьи.",
        color=0xff0000
    )
    embed.add_field(name="Причина", value=reason, inline=False)
    if roles_to_remove:
        embed.add_field(name="Снятые роли", value=", ".join(r.name for r in roles_to_remove), inline=False)
    embed.set_footer(text=f"Выдал: {interaction.user}")

    await interaction.response.send_message(embed=embed)

# === /снять_чс ===
@bot.tree.command(name="снять_чс", description="Снять чёрный список семьи с участника")
@app_commands.describe(user_id="ID пользователя")
async def unblacklist_family(interaction: discord.Interaction, user_id: str):
    if FAMILY_ROLES["deputy_leader"] not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("❌ Эта команда доступна только Заместителю Лидера.", ephemeral=True)
        return

    try:
        uid = int(user_id)
    except ValueError:
        await interaction.response.send_message("❌ ID должен быть числом.", ephemeral=True)
        return

    if not is_in_family_blacklist(uid):
        await interaction.response.send_message("❌ Пользователь не в чёрном списке семьи.", ephemeral=True)
        return

    remove_from_family_blacklist(uid)
    await log_action(
        interaction.guild,
        "Снятие ЧС семьи",
        f"Участник ID: {uid}\nСнял: {interaction.user.mention}",
        color=0x00ff00
    )

    member = interaction.guild.get_member(uid)
    mention = member.mention if member else f"ID: {uid}"

    embed = discord.Embed(
        title="✅ ЧС семьи снят",
        description=f"С пользователя {mention} снят чёрный список семьи.",
        color=0x00ff00
    )
    embed.set_footer(text=f"Снял: {interaction.user}")

    await interaction.response.send_message(embed=embed)

# === /набор ===
@bot.tree.command(name="набор", description="Открыть набор в указанном канале")
@app_commands.describe(channel_id="ID канала, куда будут приходить заявки")
async def recruitment(interaction: discord.Interaction, channel_id: str):
    allowed_roles = [FAMILY_ROLES["leader"], FAMILY_ROLES["deputy_leader"]]
    if not has_any_role(interaction.user, allowed_roles):
        await interaction.response.send_message("❌ Эта команда доступна только Лидеру и Заместителю.", ephemeral=True)
        return

    try:
        cid = int(channel_id)
    except ValueError:
        await interaction.response.send_message("❌ ID канала должен быть числом.", ephemeral=True)
        return

    target_channel = interaction.guild.get_channel(cid)
    if not target_channel or not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message("❌ Канал не найден или недоступен.", ephemeral=True)
        return

    if is_in_family_blacklist(interaction.user.id):
        await interaction.response.send_message("❌ Вы не можете открывать набор, находясь в ЧС семьи.", ephemeral=True)
        return

    embed = discord.Embed(
        title="🔥 Открыты заявки в **ᴋᴀᴅʏʀᴏᴠ ꜰᴀᴍǫ**!",
        description=(
            "✨ **Здравый и дружный коллектив**\n"
            "🎮 **Постоянный контент и активности**\n"
            "🎲 **Игры в кости, розыгрыши, ивенты**\n"
            "🛡️ **Семья — это навсегда**\n\n"
            "Если ты хочешь стать частью чего-то большего — жми кнопку ниже!"
        ),
        color=0xc41e3a
    )
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)

    class ApplyButton(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(label="📄 Подать заявку", style=discord.ButtonStyle.green, emoji="📝")
        async def apply(self, inter: discord.Interaction, button: discord.ui.Button):
            if is_in_family_blacklist(inter.id):
                reason = get_blacklist_reason(inter.id)
                await inter.response.send_message(
                    f"❌ Вы находитесь в чёрном списке семьи.\n**Причина:** {reason}",
                    ephemeral=True
                )
                return
            if not can_submit_application(inter.user.id):
                await inter.response.send_message(
                    "❌ Вы можете подавать заявку не чаще одного раза в день.",
                    ephemeral=True
                )
                return
            modal = ApplicationModal(target_channel=target_channel)
            await inter.response.send_modal(modal)

    await interaction.response.send_message("✅ Набор открыт! Форма отправлена в этот канал.", ephemeral=True)
    await interaction.followup.send(embed=embed, view=ApplyButton(), ephemeral=False)

# === МОДАЛЬНОЕ ОКНО ЗАЯВКИ ===
class ApplicationModal(discord.ui.Modal, title="Заявка в ᴋᴀᴅʏʀᴏᴠ ꜰᴀᴍǫ"):
    def __init__(self, target_channel: discord.TextChannel):
        super().__init__()
        self.target_channel = target_channel

        self.nick = discord.ui.TextInput(
            label="Ваш никнейм на сервере",
            placeholder="Пример: Nick Name",
            required=True,
            max_length=32
        )
        self.static_id = discord.ui.TextInput(
            label="Ваш Static ID",
            placeholder="Пример: 66666",
            required=True,
            max_length=10
        )
        self.age = discord.ui.TextInput(
            label="Сколько вам лет в IRL?",
            placeholder="Пример: 18",
            required=True,
            max_length=3
        )
        self.real_name = discord.ui.TextInput(
            label="Ваше имя в IRL",
            placeholder="Пример: Анатолий",
            required=True,
            max_length=30
        )
        self.details = discord.ui.TextInput(
            label="Время в игре + Откуда узнали?",
            placeholder="Пример: 5 часов в день\nTikTok / Друг",
            required=True,
            max_length=200,
            style=discord.TextStyle.paragraph
        )

        for item in [self.nick, self.static_id, self.age, self.real_name, self.details]:
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        if is_in_family_blacklist(interaction.user.id):
            reason = get_blacklist_reason(interaction.user.id)
            await interaction.response.send_message(
                f"❌ Вы находитесь в чёрном списке семьи.\n**Причина:** {reason}",
                ephemeral=True
            )
            return
        if not can_submit_application(interaction.user.id):
            await interaction.response.send_message(
                "❌ Вы можете подавать заявку не чаще одного раза в день.",
                ephemeral=True
            )
            return

        record_application(interaction.user.id)

        embed = discord.Embed(
            title="📄 Новая заявка на вступление",
            color=0x2b2d31,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="👤 Никнейм", value=self.nick.value, inline=True)
        embed.add_field(name="🆔 Static ID", value=self.static_id.value, inline=True)
        embed.add_field(name="🎂 Возраст (IRL)", value=self.age.value, inline=True)
        embed.add_field(name="📛 Имя (IRL)", value=self.real_name.value, inline=True)
        detail_value = self.details.value[:1020] + ("..." if len(self.details.value) > 1020 else "")
        embed.add_field(name="ℹ️ Детали", value=detail_value, inline=False)
        embed.set_footer(text=f"Заявитель: {interaction.user} | ID: {interaction.user.id}")

        view = ApplicationControlView(applicant=interaction.user)
        await self.target_channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Ваша заявка отправлена! Ожидайте обзвона.", ephemeral=True)

# === УПРАВЛЕНИЕ ЗАЯВКОЙ ===
class ApplicationControlView(discord.ui.View):
    def __init__(self, applicant: discord.Member):
        super().__init__(timeout=None)
        self.applicant = applicant

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not has_any_role(interaction.user, MANAGE_APPLICATIONS_ROLES):
            await interaction.response.send_message("❌ У вас нет прав для управления заявками.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="📞 Вызвать на обзвон", style=discord.ButtonStyle.blurple, emoji="🔊")
    async def call_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.applicant.send("🔔 **Вы вызваны на обзвон в семью `ᴋᴀᴅʏʀᴏᴠ ꜰᴀᴍǫ`!**\nЗайдите в любой открытый голосовой канал.")
            await interaction.response.send_message("✅ Уведомление отправлено.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Не удалось отправить ЛС.", ephemeral=True)

    @discord.ui.button(label="✅ Одобрено", style=discord.ButtonStyle.green, emoji="🟢")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.applicant.send("🎉 **Поздравляем!** Вы приняты в **ᴋᴀᴅʏʀᴏᴠ ꜰᴀᴍǫ**!")
            role = interaction.guild.get_role(FAMILY_ROLES["member"])
            if role and role not in self.applicant.roles:
                await self.applicant.add_roles(role)
        except discord.Forbidden:
            pass

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.title = "✅ Заявка одобрена"
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.defer()

        await log_action(
            interaction.guild,
            "Заявка одобрена",
            f"Заявитель: {self.applicant.mention}\nОдобрил: {interaction.user.mention}",
            color=0x00ff00
        )

    @discord.ui.button(label="❌ Отказано", style=discord.ButtonStyle.red, emoji="🔴")
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RejectReasonModal(self.applicant, interaction.message))

class RejectReasonModal(discord.ui.Modal, title="Причина отказа"):
    def __init__(self, applicant: discord.Member, message: discord.Message):
        super().__init__()
        self.applicant = applicant
        self.message = message
        self.reason = discord.ui.TextInput(
            label="Причина отказа",
            placeholder="Например: низкая активность",
            required=True,
            max_length=200,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.applicant.send(f"❌ Ваша заявка отклонена.\n**Причина:** {self.reason.value}")
        except discord.Forbidden:
            pass
        embed = self.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = "❌ Заявка отклонена"
        reason_value = self.reason.value[:1020] + ("..." if len(self.reason.value) > 1020 else "")
        embed.add_field(name="💬 Причина", value=reason_value, inline=False)
        await self.message.edit(embed=embed, view=None)
        await interaction.response.send_message("✅ Отказ обработан.", ephemeral=True)

        await log_action(
            interaction.guild,
            "Заявка отклонена",
            f"Заявитель: {self.applicant.mention}\nПричина: {self.reason.value}\nОтклонил: {interaction.user.mention}",
            color=0xff0000
        )

# === /статус_заявок ===
@bot.tree.command(name="статус_заявок", description="Показать статус обработки заявок")
async def application_status(interaction: discord.Interaction):
    if not has_any_role(interaction.user, MANAGE_APPLICATIONS_ROLES):
        await interaction.response.send_message("❌ У вас нет прав для просмотра статуса заявок.", ephemeral=True)
        return

    pending_count = get_pending_applications_count()
    last_time = get_last_application_time()

    embed = discord.Embed(
        title="📊 Статус заявок",
        color=0xc41e3a
    )
    embed.add_field(name="Всего нерассмотренных", value=str(pending_count), inline=True)
    embed.add_field(name="Последняя заявка", value=last_time, inline=True)
    embed.add_field(name="Обработка", value="Доступна для ролей [ʀᴇᴄʀᴜɪᴛ] и выше", inline=False)
    embed.set_footer(text="Используйте /набор для открытия нового набора")

    await interaction.response.send_message(embed=embed)

# === /состав_семьи ===
@bot.tree.command(name="состав_семьи", description="Показать состав семьи по рангам")
async def family_members(interaction: discord.Interaction):
    if not any(role.id == FAMILY_ROLES["member"] for role in interaction.user.roles):
        await interaction.response.send_message("❌ Эта команда доступна только участникам семьи.", ephemeral=True)
        return

    rank_order = [
        (FAMILY_ROLES["leader"], "[Лидер]"),
        (FAMILY_ROLES["deputy_leader"], "[Заместитель Лидера]"),
        (FAMILY_ROLES["high_staff"], "[ʜɪɢʜ sᴛᴀꜰꜰ]"),
        (FAMILY_ROLES["main_staff"], "[ᴍᴀɪɴ sᴛᴀꜰꜰ]"),
        (FAMILY_ROLES["recruit"], "[ʀᴇᴄʀᴜɪᴛ]")
    ]

    embed = discord.Embed(
        title="👨‍👩‍👧‍👦 Состав семьи **ᴋᴀᴅʏʀᴏᴠ ꜰᴀᴍǫ**",
        color=0xc41e3a,
        timestamp=discord.utils.utcnow()
    )

    status_map = {
        discord.Status.online: "🟢 Онлайн",
        discord.Status.idle: "🌙 Отошёл",
        discord.Status.dnd: "⛔ Не беспокоить",
        discord.Status.offline: "⚫ Не в сети"
    }

    for role_id, rank_name in rank_order:
        role = interaction.guild.get_role(role_id)
        if not role:
            continue
        members = [m for m in role.members if not m.bot]
        if not members:
            continue
        members.sort(key=lambda m: m.display_name.lower())
        lines = [f"{status_map.get(m.status, '⚫ Не в сети')} — {m.mention}" for m in members]
        full_text = "\n".join(lines)

        if len(full_text) <= 1024:
            embed.add_field(name=rank_name, value=full_text, inline=False)
        else:
            half = len(lines) // 2
            part1 = "\n".join(lines[:half])[:1024]
            part2 = "\n".join(lines[half:])[:1024]
            embed.add_field(name=rank_name, value=part1, inline=False)
            if part2.strip():
                embed.add_field(name=f"{rank_name} (продолжение)", value=part2, inline=False)

    if len(embed) > 6000:
        embed = discord.Embed(
            title="👨‍👩‍👧‍👦 Состав семьи **ᴋᴀᴅʏʀᴏᴠ ꜰᴀᴍǫ**",
            description="Семья слишком велика для отображения.",
            color=0xc41e3a
        )

    await interaction.response.send_message(embed=embed)

# === /состояние ===
@bot.tree.command(name="состояние", description="Показать статистику пользователя по голосовым каналам")
@app_commands.describe(user="Пользователь для проверки")
async def user_state(interaction: discord.Interaction, user: discord.User):
    allowed_roles = [FAMILY_ROLES["leader"], FAMILY_ROLES["deputy_leader"], 1460688847267565744]
    if not has_any_role(interaction.user, allowed_roles):
        await interaction.response.send_message("❌ У вас нет прав для просмотра статистики.", ephemeral=True)
        return

    member = interaction.guild.get_member(user.id)
    if not member:
        await interaction.response.send_message("❌ Пользователь не на сервере.", ephemeral=True)
        return

    sessions = get_user_sessions(user.id)
    if not sessions:
        await interaction.response.send_message(f"🔇 У {user.mention} нет записей о пребывании в голосовых.", ephemeral=True)
        return

    total_seconds = 0
    details = []
    for channel_id, start_str, end_str in sessions[:10]:
        start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        end = datetime.fromisoformat((end_str or datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00"))
        channel = interaction.guild.get_channel(channel_id)
        name = channel.name if channel else f"ID:{channel_id}"
        duration = int((end - start).total_seconds() // 60)
        total_seconds += (end - start).total_seconds()
        details.append(f"🎙️ **{name}** — {start.strftime('%d.%m %H:%M')} → {end.strftime('%H:%M')} ({duration} мин)")

    hours, minutes = divmod(int(total_seconds // 60), 60)
    embed = discord.Embed(
        title=f"📊 Голосовая активность: {user.display_name}",
        description=f"**Общее время:** {hours} ч {minutes} мин",
        color=0xc41e3a
    )
    embed.add_field(name="Последние сессии", value="\n".join(details) or "Нет данных", inline=False)
    await interaction.response.send_message(embed=embed)

# === /профиль ===
@bot.tree.command(name="профиль", description="Заполнить свой профиль семьи")
async def profile_command(interaction: discord.Interaction):
    if FAMILY_MEMBER_ROLE_ID not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("❌ Эта команда доступна только участникам семьи.", ephemeral=True)
        return

    class ProfileModal(discord.ui.Modal, title="Ваш профиль семьи"):
        def __init__(self):
            super().__init__()
            self.nick = discord.ui.TextInput(
                label="Ваш никнейм",
                placeholder="Пример: Nick Name",
                required=True,
                max_length=32
            )
            self.static_id = discord.ui.TextInput(
                label="Ваш Static ID",
                placeholder="Пример: 66666",
                required=True,
                max_length=10
            )
            self.add_item(self.nick)
            self.add_item(self.static_id)

        async def on_submit(self, inter: discord.Interaction):
            save_profile(inter.user.id, self.nick.value, self.static_id.value)
            await inter.response.send_message("✅ Ваш профиль успешно сохранён!", ephemeral=True)

    await interaction.response.send_modal(ProfileModal())

# === /посмотреть_профиль ===
@bot.tree.command(name="посмотреть_профиль", description="Просмотреть профиль участника")
@app_commands.describe(member="Участник для просмотра")
async def view_profile(interaction: discord.Interaction, member: discord.Member):
    if DEPUTY_LEADER_ROLE_ID not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("❌ Эта команда доступна только Заместителю Лидера.", ephemeral=True)
        return

    profile = get_profile(member.id)
    embed = discord.Embed(
        title=f"📄 Профиль: {member.display_name}",
        color=0xc41e3a
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="👤 Упоминание", value=member.mention, inline=True)
    embed.add_field(name="🆔 ID", value=str(member.id), inline=True)

    if profile:
        embed.add_field(name="📛 Никнейм", value=profile[0], inline=False)
        embed.add_field(name="🎮 Static ID", value=profile[1], inline=False)
    else:
        embed.description = "❌ Профиль не заполнен."

    await interaction.response.send_message(embed=embed)

# === /восстановить_состав ===
@bot.tree.command(name="восстановить_состав", description="Восстановить состав семьи из бэкапа")
@app_commands.describe(date="Дата бэкапа (формат: YYYY-MM-DD_HH-MM)")
async def restore_backup(interaction: discord.Interaction, date: str):
    if LEADER_ROLE_ID not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("❌ Только Лидер может восстанавливать состав.", ephemeral=True)
        return

    filepath = f"backups/backup_{date}.json"
    if not os.path.exists(filepath):
        files = "\n".join(f"`{f.replace('backup_', '').replace('.json', '')}`" for f in sorted(os.listdir("backups")))
        await interaction.response.send_message(
            f"❌ Бэкап не найден.\nДоступные даты:\n{files}",
            ephemeral=True
        )
        return

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    restored = 0
    for member_data in data["members"]:
        member = interaction.guild.get_member(member_data["user_id"])
        if not member:
            continue
        roles_to_add = []
        for role_id in member_data["roles"]:
            role = interaction.guild.get_role(role_id)
            if role and role not in member.roles:
                roles_to_add.append(role)
        if roles_to_add:
            await member.add_roles(*roles_to_add)
            restored += 1

    embed = discord.Embed(
        title="✅ Восстановление завершено",
        description=f"Восстановлено ролей для {restored} участников.",
        color=0x00ff00
    )
    embed.add_field(name="Файл", value=f"`{date}.json`", inline=False)
    await interaction.response.send_message(embed=embed)

# === КАЗИНО ===

# === /баланс ===
@bot.tree.command(name="баланс", description="Показать ваш баланс в казино")
async def balance_command(interaction: discord.Interaction):
    balance = get_balance(interaction.user.id)
    embed = discord.Embed(
        title="💰 Ваш баланс",
        description=f"У вас на счету: **${balance:,}**",
        color=0x2ecc71
    )
    await interaction.response.send_message(embed=embed)

# === ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: создать кнопки казино ===
def create_casino_view():
    class CasinoView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)

        @discord.ui.button(label="🎲 Кости", style=discord.ButtonStyle.blurple, emoji="🎲")
        async def dice_button(self, inter: discord.Interaction, button: discord.ui.Button):
            await inter.response.send_modal(DiceModal(min_bet=1000))

        @discord.ui.button(label="🎰 Слоты", style=discord.ButtonStyle.green, emoji="🎰")
        async def slots_button(self, inter: discord.Interaction, button: discord.ui.Button):
            await inter.response.send_modal(SlotsModal(min_bet=500))

        @discord.ui.button(label="🔮 Шанс", style=discord.ButtonStyle.red, emoji="🔮")
        async def chance_button(self, inter: discord.Interaction, button: discord.ui.Button):
            await inter.response.send_modal(ChanceModal(min_bet=100))

    return CasinoView()

# === МОДАЛЬНЫЕ ОКНА С НОВЫМИ КОЭФФИЦИЕНТАМИ ===
class DiceModal(discord.ui.Modal, title="🎲 Кости"):
    def __init__(self, min_bet=1000):
        super().__init__()
        self.min_bet = min_bet
        self.bet = discord.ui.TextInput(
            label=f"Ставка (мин. ${min_bet:,})",
            placeholder="Введите сумму",
            required=True,
            max_length=10
        )
        self.add_item(self.bet)

    async def on_submit(self, inter: discord.Interaction):
        try:
            amount = int(self.bet.value.replace(",", "").replace(" ", ""))
        except ValueError:
            await inter.response.send_message("❌ Сумма должна быть числом.", ephemeral=True)
            return

        if amount < self.min_bet:
            await inter.response.send_message(f"❌ Минимальная ставка: ${self.min_bet:,}", ephemeral=True)
            return

        balance = get_balance(inter.user.id)
        if amount > balance:
            await inter.response.send_message("❌ У вас недостаточно денег!", ephemeral=True)
            return

        set_balance(inter.user.id, balance - amount)
        player_roll = random.randint(1, 6)
        bot_roll = random.randint(1, 6)

        if player_roll > bot_roll:
            prize = amount * 2  # x2
            set_balance(inter.user.id, balance - amount + prize)
            result = f"🎉 Вы выиграли **${prize:,}**!\nВаш бросок: {player_roll} | Бот: {bot_roll}"
            color = 0x2ecc71
        elif player_roll == bot_roll:
            set_balance(inter.user.id, balance)
            result = f"🤝 Ничья! Ставка возвращена.\nВаш бросок: {player_roll} | Бот: {bot_roll}"
            color = 0xf39c12
        else:
            result = f"💀 Вы проиграли **${amount:,}**.\nВаш бросок: {player_roll} | Бот: {bot_roll}"
            color = 0xe74c3c

        new_balance = get_balance(inter.user.id)
        embed = discord.Embed(title="🎲 Кости", description=result, color=color)
        embed.set_footer(text=f"Ваш баланс: ${new_balance:,}")
        await inter.response.send_message(embed=embed, view=create_casino_view())

class SlotsModal(discord.ui.Modal, title="🎰 Слоты"):
    def __init__(self, min_bet=500):
        super().__init__()
        self.min_bet = min_bet
        self.bet = discord.ui.TextInput(
            label=f"Ставка (мин. ${min_bet:,})",
            placeholder="Введите сумму",
            required=True,
            max_length=10
        )
        self.add_item(self.bet)

    async def on_submit(self, inter: discord.Interaction):
        try:
            amount = int(self.bet.value.replace(",", "").replace(" ", ""))
        except ValueError:
            await inter.response.send_message("❌ Сумма должна быть числом.", ephemeral=True)
            return

        if amount < self.min_bet:
            await inter.response.send_message(f"❌ Минимальная ставка: ${self.min_bet:,}", ephemeral=True)
            return

        balance = get_balance(inter.user.id)
        if amount > balance:
            await inter.response.send_message("❌ У вас недостаточно денег!", ephemeral=True)
            return

        set_balance(inter.user.id, balance - amount)
        symbols = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣"]
        spin = [random.choice(symbols) for _ in range(3)]
        spin_str = " | ".join(spin)

        if spin[0] == spin[1] == spin[2]:
            prize = amount * 3  # x3
            set_balance(inter.user.id, balance - amount + prize)
            result = f"🏆 Джекпот! Вы выиграли **${prize:,}**!\n{spin_str}"
            color = 0x2ecc71
        elif spin[0] == spin[1] or spin[1] == spin[2] or spin[0] == spin[2]:
            prize = amount * 2  # x2
            set_balance(inter.user.id, balance - amount + prize)
            result = f"👍 Два одинаковых! Вы выиграли **${prize:,}**!\n{spin_str}"
            color = 0x3498db
        else:
            result = f"💔 Повезёт в следующий раз!\n{spin_str}"
            color = 0xe74c3c

        new_balance = get_balance(inter.user.id)
        embed = discord.Embed(title="🎰 Слоты", description=result, color=color)
        embed.set_footer(text=f"Ваш баланс: ${new_balance:,}")
        await inter.response.send_message(embed=embed, view=create_casino_view())

class ChanceModal(discord.ui.Modal, title="🔮 Шанс"):
    def __init__(self, min_bet=100):
        super().__init__()
        self.min_bet = min_bet
        self.bet = discord.ui.TextInput(
            label=f"Ставка (мин. ${min_bet:,})",
            placeholder="Введите сумму",
            required=True,
            max_length=10
        )
        self.add_item(self.bet)

    async def on_submit(self, inter: discord.Interaction):
        try:
            amount = int(self.bet.value.replace(",", "").replace(" ", ""))
        except ValueError:
            await inter.response.send_message("❌ Сумма должна быть числом.", ephemeral=True)
            return

        if amount < self.min_bet:
            await inter.response.send_message(f"❌ Минимальная ставка: ${self.min_bet:,}", ephemeral=True)
            return

        balance = get_balance(inter.user.id)
        if amount > balance:
            await inter.response.send_message("❌ У вас недостаточно денег!", ephemeral=True)
            return

        set_balance(inter.user.id, balance - amount)
        if random.random() < 0.5:
            prize = amount * 5  # x5
            set_balance(inter.user.id, balance - amount + prize)
            result = f"✨ Удача на вашей стороне! Вы умножили ставку на 5!\nВыигрыш: **${prize:,}**"
            color = 0x2ecc71
        else:
            result = f"🌑 Вам не повезло. Ставка потеряна."
            color = 0xe74c3c

        new_balance = get_balance(inter.user.id)
        embed = discord.Embed(title="🔮 Шанс", description=result, color=color)
        embed.set_footer(text=f"Ваш баланс: ${new_balance:,}")
        await inter.response.send_message(embed=embed, view=create_casino_view())

# === /казино ===
@bot.tree.command(name="казино", description="Играть в казино")
async def casino_command(interaction: discord.Interaction):
    balance = get_balance(interaction.user.id)
    embed = discord.Embed(
        title="🎰 Казино ᴋᴀᴅʏʀᴏᴠ ꜰᴀᴍǫ",
        description=f"Ваш баланс: **${balance:,}**\nВыберите игру и укажите ставку:",
        color=0x9b59b6
    )
    await interaction.response.send_message(embed=embed, view=create_casino_view())

# === /топ_казино ===
@bot.tree.command(name="топ_казино", description="Топ-10 богачей казино")
async def top_casino(interaction: discord.Interaction):
    top_players = get_top_casino()
    if not top_players:
        await interaction.response.send_message("Никто ещё не играл в казино.", ephemeral=True)
        return

    description = ""
    for i, (user_id, balance) in enumerate(top_players, 1):
        user = await bot.fetch_user(user_id)
        name = user.display_name if user else f"ID: {user_id}"
        description += f"{i}. **{name}** — ${balance:,}\n"

    embed = discord.Embed(
        title="🏆 Топ-10 казино",
        description=description,
        color=0xf1c40f
    )
    await interaction.response.send_message(embed=embed)

# === /work ===
@bot.tree.command(name="work", description="Работать и получить $10,000")
async def work_command(interaction: discord.Interaction):
    if not any(role.id == FAMILY_MEMBER_ROLE_ID for role in interaction.user.roles):
        await interaction.response.send_message("❌ Эта команда доступна только участникам семьи.", ephemeral=True)
        return

    if not can_work(interaction.user.id):
        await interaction.response.send_message("⏳ Вы можете работать раз в 2 часа.", ephemeral=True)
        return

    current = get_balance(interaction.user.id)
    new_balance = current + 10000
    set_balance(interaction.user.id, new_balance)
    update_work_time(interaction.user.id)

    embed = discord.Embed(
        title="💼 Работа завершена!",
        description=f"Вы заработали **$10,000**!\nВаш новый баланс: **${new_balance:,}**",
        color=0x2ecc71
    )
    await interaction.response.send_message(embed=embed)

# === /выдать_денег ===
@bot.tree.command(name="выдать_денег", description="Выдать деньги участнику")
@app_commands.describe(member="Участник", amount="Сумма в долларах")
async def give_money(interaction: discord.Interaction, member: discord.Member, amount: int):
    if DEPUTY_LEADER_ROLE_ID not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("❌ Эта команда доступна только Заместителю Лидера.", ephemeral=True)
        return

    if amount <= 0:
        await interaction.response.send_message("❌ Сумма должна быть положительной.", ephemeral=True)
        return

    current = get_balance(member.id)
    new_balance = current + amount
    set_balance(member.id, new_balance)

    embed = discord.Embed(
        title="💸 Выдача денег",
        description=f"Заместитель {interaction.user.mention} выдал **${amount:,}** участнику {member.mention}.",
        color=0x2ecc71
    )
    embed.add_field(name="Новый баланс", value=f"${new_balance:,}", inline=False)
    await interaction.response.send_message(embed=embed)

# === /обнулить_баланс ===
@bot.tree.command(name="обнулить_баланс", description="Обнулить баланс участника за нарушения")
@app_commands.describe(member="Участник")
async def reset_balance(interaction: discord.Interaction, member: discord.Member):
    if DEPUTY_LEADER_ROLE_ID not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("❌ Эта команда доступна только Заместителю Лидера.", ephemeral=True)
        return

    old_balance = get_balance(member.id)
    set_balance(member.id, 0)

    embed = discord.Embed(
        title="⚖️ Баланс обнулён",
        description=f"Заместитель {interaction.user.mention} обнулил баланс участника {member.mention} за нарушения.",
        color=0xff0000
    )
    embed.add_field(name="Предыдущий баланс", value=f"${old_balance:,}", inline=False)
    await interaction.response.send_message(embed=embed)

# === /магазин ===
@bot.tree.command(name="магазин", description="Купить роль за доллары")
async def shop_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛒 Магазин ролей ᴋᴀᴅʏʀᴏᴠ ꜰᴀᴍǫ",
        description="Выберите роль для покупки:",
        color=0x9b59b6
    )

    role_names = {
        1461403128330190982: "ЛУДИК",
        1461403410124374282: "АЛЬТУХА",
        1461403437756584126: "МЕРИКРИСТМАС",
        1461403169342099626: "ПОВЕЛИТЕЛЬ",
        1461403469175849137: "БИГ БОСС",
        1461403498053767219: "СУПЕР БОСС",
        1461403526302531686: "КОРОЛЬ ПЛАНЕТЫ",
        1461403355145572444: "ТОП 1 ФОРБС",
        1461403584360091651: "РОЛЬ С ПРАВАМИ МОДЕРАТОРА"
    }

    for role_id, price in SHOP_ROLES.items():
        role_name = role_names.get(role_id, f"Роль {role_id}")
        embed.add_field(
            name=f"{role_name}",
            value=f"Цена: **${price:,}**",
            inline=False
        )

    class ShopView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)

        @discord.ui.select(
            placeholder="Выберите роль для покупки",
            options=[
                discord.SelectOption(label=role_names[rid], value=str(rid), description=f"${SHOP_ROLES[rid]:,}")
                for rid in SHOP_ROLES.keys()
            ]
        )
        async def select_role(self, inter: discord.Interaction, select: discord.ui.Select):
            role_id = int(select.values[0])
            price = SHOP_ROLES[role_id]
            balance = get_balance(inter.user.id)

            if balance < price:
                await inter.response.send_message("❌ У вас недостаточно денег!", ephemeral=True)
                return

            role = inter.guild.get_role(role_id)
            if not role:
                await inter.response.send_message("❌ Роль не найдена на сервере.", ephemeral=True)
                return

            if role in inter.user.roles:
                await inter.response.send_message("❌ У вас уже есть эта роль.", ephemeral=True)
                return

            set_balance(inter.user.id, balance - price)
            await inter.user.add_roles(role)

            embed = discord.Embed(
                title="✅ Покупка совершена!",
                description=f"Вы приобрели роль **{role.name}** за **${price:,}**.",
                color=0x2ecc71
            )
            embed.set_footer(text=f"Ваш новый баланс: ${get_balance(inter.user.id):,}")
            await inter.response.send_message(embed=embed)

    await interaction.response.send_message(embed=embed, view=ShopView())

# === ЗАПУСК ===
if __name__ == "__main__":
    bot.run(TOKEN)
