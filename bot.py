import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import asyncio
import sqlite3
from datetime import datetime, timezone

# === ЗАГРУЗКА ТОКЕНА ===
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("❌ Файл .env должен содержать DISCORD_TOKEN=ваш_токен")

# === ID РОЛЕЙ (как в вашем ТЗ) ===
LEADER_ROLE_ID = 605829120974258203
DEPUTY_LEADER_ROLE_ID = 1220118511549026364
ADMIN_ROLE_ID = 1460688847267565744  # для /набор и /состояние

FAMILY_ROLES = {
    "member": 1460692962139836487,
    "main_staff": 1460692954812387472,
    "recruit": 1460692951494688967,
    "high_staff": 1460692948458143848,
    "deputy_leader": DEPUTY_LEADER_ROLE_ID,
    "leader": LEADER_ROLE_ID
}

# Роли, которые могут управлять заявками
MANAGE_APPLICATIONS_ROLES = [
    FAMILY_ROLES["recruit"],
    FAMILY_ROLES["high_staff"],
    FAMILY_ROLES["deputy_leader"]
]

# Роли, которые могут использовать /набор и /состояние
MANAGE_COMMANDS_ROLES = [LEADER_ROLE_ID, DEPUTY_LEADER_ROLE_ID, ADMIN_ROLE_ID]

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
    conn.commit()
    conn.close()

init_db()

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

# === ПРОВЕРКА РОЛЕЙ ===
def has_any_role(member: discord.Member, role_ids: list) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(role.id in role_ids for role in member.roles)

# === СОБЫТИЯ ===
@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен и готов к работе!')
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

async def change_status():
    statuses = [
        discord.Game("Играет"),
        discord.Activity(type=discord.ActivityType.watching, name="Спит"),
        discord.Activity(type=discord.ActivityType.listening, name="Есть"),
        discord.Game("Тролится")
    ]
    while True:
        for status in statuses:
            await bot.change_presence(activity=status)
            await asyncio.sleep(30)

# === КОМАНДА /набор ===
@bot.tree.command(name="набор", description="Отправить форму набора в канал по ID")
@app_commands.describe(channel_id="ID текстового канала для заявок")
async def recruitment(interaction: discord.Interaction, channel_id: str):
    if not has_any_role(interaction.user, MANAGE_COMMANDS_ROLES):
        await interaction.response.send_message("❌ У вас нет прав для использования этой команды.", ephemeral=True)
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
            modal = ApplicationModal(target_channel=target_channel)
            await inter.response.send_modal(modal)

    await target_channel.send(embed=embed, view=ApplyButton())
    await interaction.response.send_message(f"✅ Форма отправлена в канал <#{cid}>.", ephemeral=True)

class ApplicationModal(discord.ui.Modal, title="Заявка в ᴋᴀᴅʏʀᴏᴠ ꜰᴀᴍǫ"):
    def __init__(self, target_channel: discord.TextChannel):
        super().__init__()
        self.target_channel = target_channel

        fields = [
            ("nick", "Ваш никнейм на сервере", "Nick Name"),
            ("static_id", "Ваш Static ID", "66666"),
            ("age", "Сколько вам лет в IRL?", "18"),
            ("real_name", "Ваше имя в IRL", "Анатолий"),
            ("playtime", "Сколько времени уделяете игре?", "5 часов в день"),
            ("source", "Откуда узнали о семье?", "TikTok / Друг")
        ]

        self.inputs = {}
        for name, label, placeholder in fields:
            inp = discord.ui.TextInput(
                label=label,
                placeholder=placeholder,
                required=True,
                max_length=100 if name == "source" else 32
            )
            self.add_item(inp)
            self.inputs[name] = inp

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📄 Новая заявка на вступление",
            color=0x2b2d31,
            timestamp=discord.utils.utcnow()
        )
        data = {k: v.value for k, v in self.inputs.items()}
        embed.add_field(name="👤 Никнейм", value=data["nick"], inline=True)
        embed.add_field(name="🆔 Static ID", value=data["static_id"], inline=True)
        embed.add_field(name="🎂 Возраст (IRL)", value=data["age"], inline=True)
        embed.add_field(name="📛 Имя (IRL)", value=data["real_name"], inline=True)
        embed.add_field(name="⏳ Время в игре", value=data["playtime"], inline=True)
        embed.add_field(name="📢 Источник", value=data["source"], inline=True)
        embed.set_footer(text=f"Заявитель: {interaction.user} | ID: {interaction.user.id}")

        view = ApplicationControlView(applicant=interaction.user)
        msg = await self.target_channel.send(embed=embed, view=view)
        view.message = msg
        await interaction.response.send_message("✅ Ваша заявка отправлена! Ожидайте обзвона.", ephemeral=True)

class ApplicationControlView(discord.ui.View):
    def __init__(self, applicant: discord.Member):
        super().__init__(timeout=None)
        self.applicant = applicant
        self.message = None

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
        embed = self.message.embeds[0]
        embed.color = discord.Color.green()
        embed.title = "✅ Заявка одобрена"
        for child in self.children:
            child.disabled = True
        await self.message.edit(embed=embed, view=self)
        await interaction.response.defer()

    @discord.ui.button(label="❌ Отказано", style=discord.ButtonStyle.red, emoji="🔴")
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RejectReasonModal(self.applicant, self.message))

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
        embed.add_field(name="💬 Причина", value=self.reason.value, inline=False)
        await self.message.edit(embed=embed, view=None)
        await interaction.response.send_message("✅ Отказ обработан.", ephemeral=True)

# === КОМАНДА /состав_семьи ===
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
        lines = [f"{status_map.get(m.status, '⚫ Не в сети')} — {m.mention} (`{m.display_name}`)" for m in members]
        embed.add_field(name=rank_name, value="\n".join(lines), inline=False)

    await interaction.response.send_message(embed=embed)

# === КОМАНДА /состояние ===
@bot.tree.command(name="состояние", description="Показать статистику пользователя по голосовым каналам")
@app_commands.describe(user="Пользователь для проверки")
async def user_state(interaction: discord.Interaction, user: discord.User):
    if not has_any_role(interaction.user, MANAGE_COMMANDS_ROLES):
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

    total_seconds = sum(
        (datetime.fromisoformat((s[2] or datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00")) -
         datetime.fromisoformat(s[1].replace("Z", "+00:00"))).total_seconds()
        for s in sessions
    )

    details = []
    for channel_id, start_str, end_str in sessions[:10]:
        start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        end = datetime.fromisoformat((end_str or datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00"))
        channel = interaction.guild.get_channel(channel_id)
        name = channel.name if channel else f"ID:{channel_id}"
        duration = int((end - start).total_seconds() // 60)
        details.append(f"🎙️ **{name}** — {start.strftime('%d.%m %H:%M')} → {end.strftime('%H:%M')} ({duration} мин)")

    hours, minutes = divmod(int(total_seconds // 60), 60)
    embed = discord.Embed(
        title=f"📊 Голосовая активность: {user.display_name}",
        description=f"**Общее время:** {hours} ч {minutes} мин",
        color=0xc41e3a
    )
    embed.add_field(name="Последние сессии", value="\n".join(details), inline=False)
    await interaction.response.send_message(embed=embed)

# === ЗАПУСК ===
if __name__ == "__main__":
    bot.run(TOKEN)
