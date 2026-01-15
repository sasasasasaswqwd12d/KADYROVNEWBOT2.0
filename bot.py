import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import asyncio
import sqlite3
from datetime import datetime, timezone, timedelta

# === НАСТРОЙКИ ===
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("❌ Файл .env должен содержать DISCORD_TOKEN=ваш_токен")

# ⚠️ ЗАМЕНИТЕ НА СВОЙ ID ВЛАДЕЛЬЦА БОТА
OWNER_ID = 1425864152563585158  # ← ОБЯЗАТЕЛЬНО ИЗМЕНИТЬ!

# === ID РОЛЕЙ ===
LEADER_ROLE_ID = 605829120974258203
DEPUTY_LEADER_ROLE_ID = 1220118511549026364
ADMIN_ROLE_ID = 1460688847267565744

FAMILY_ROLES = {
    "member": 1460692962139836487,
    "main_staff": 1460692954812387472,
    "recruit": 1460692951494688967,
    "high_staff": 1460692948458143848,
    "deputy_leader": DEPUTY_LEADER_ROLE_ID,
    "leader": LEADER_ROLE_ID
}

MANAGE_APPLICATIONS_ROLES = [
    FAMILY_ROLES["recruit"],
    FAMILY_ROLES["high_staff"],
    FAMILY_ROLES["deputy_leader"],
    FAMILY_ROLES["leader"]
]

# === КАНАЛ ЛОГОВ ===
LOG_CHANNEL_ID = 1461033301170192414

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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS voice_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS family_blacklist (
            user_id INTEGER PRIMARY KEY,
            reason TEXT NOT NULL,
            added_by INTEGER NOT NULL,
            added_at TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            submitted_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# === ФУНКЦИИ ДЛЯ ГОЛОСОВЫХ СЕССИЙ ===
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

# === ФУНКЦИИ ДЛЯ ЧЁРНОГО СПИСКА ===
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

# === ФУНКЦИИ ДЛЯ ЗАЯВОК ===
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

# === ЛОГИРОВАНИЕ ===
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

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def has_any_role(member: discord.Member, role_ids: list) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(role.id in role_ids for role in member.roles)

# === СОБЫТИЯ ===
@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    print(f'💡 Отправьте "!sync" для синхронизации слэш-команд.')
    bot.loop.create_task(change_status())

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

    # Снимаем роли с нарушителя
    await after.remove_roles(*given_family_roles)

    # Находим, кто выдал роль (через audit log)
    issuer = None
    try:
        async for entry in after.guild.audit_logs(action=discord.AuditLogAction.member_role_update, limit=10):
            if entry.target.id == after.id and any(r.id in family_role_ids for r in getattr(entry.after, 'roles', [])):
                issuer = entry.user
                break
    except Exception:
        pass

    # Если нашли выдавшего — снимаем роль и с него
    issuer_roles_to_remove = []
    if issuer and issuer != bot.user and issuer != after:
        issuer_roles_to_remove = [r for r in issuer.roles if r.id in family_role_ids]
        if issuer_roles_to_remove:
            await issuer.remove_roles(*issuer_roles_to_remove)

    # Логируем
    reason = get_blacklist_reason(after.id)
    details = f"Участник: {after.mention} (ID: {after.id})\nПричина ЧС: {reason}"
    if issuer:
        details += f"\nВыдавший: {issuer.mention} (ID: {issuer.id})"
        if issuer_roles_to_remove:
            details += f"\nСняты роли с выдавшего: {', '.join(r.name for r in issuer_roles_to_remove)}"

    await log_action(after.guild, "Попытка выдать роль участнику из ЧС", details, color=0xff0000)

async def change_status():
    while True:
        pending = get_pending_applications_count()
        activity = discord.Game(f"Заявок: {pending}")
        await bot.change_presence(activity=activity)
        await asyncio.sleep(60)

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

# === МОДАЛЬНОЕ ОКНО ===
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

        view = ApplicationControlView(applicant=interaction.user, application_id=None)
        msg = await self.target_channel.send(embed=embed, view=view)
        # Обновляем статус заявки как pending
        await log_action(
            interaction.guild,
            "Новая заявка",
            f"Заявитель: {interaction.user.mention} (ID: {interaction.user.id})\nКанал: {self.target_channel.mention}",
            color=0x2b2d31
        )
        await interaction.response.send_message("✅ Ваша заявка отправлена! Ожидайте обзвона.", ephemeral=True)

# === УПРАВЛЕНИЕ ЗАЯВКОЙ ===
class ApplicationControlView(discord.ui.View):
    def __init__(self, applicant: discord.Member, application_id=None):
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
    allowed_roles = [FAMILY_ROLES["leader"], FAMILY_ROLES["deputy_leader"], ADMIN_ROLE_ID]
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

# === ЗАПУСК ===
if __name__ == "__main__":
    bot.run(TOKEN)
