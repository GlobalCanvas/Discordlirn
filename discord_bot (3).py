import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import sys
import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional

# Music
import yt_dlp
import functools

# ═══════════════════════════════════════════════════════════════
#                        КОНФІГУРАЦІЯ
# ═══════════════════════════════════════════════════════════════

DISCORD_TOKEN = os.getenv("BOT_TOKEN", "MTQ4OTk2MDQ3MDcODYzNjgzMA.GpGGWQ.coSSTstwCsOeY9_HDRrGZHpG4iLvXdcrJDt4bQ")

DATA_DIR = "discord_data"
os.makedirs(DATA_DIR, exist_ok=True)

SETTINGS_FILE   = os.path.join(DATA_DIR, "settings.json")
WARNS_FILE      = os.path.join(DATA_DIR, "warns.json")
MUTES_FILE      = os.path.join(DATA_DIR, "mutes.json")
TICKETS_FILE    = os.path.join(DATA_DIR, "tickets.json")
GRANTS_FILE     = os.path.join(DATA_DIR, "grants.json")
MEDALS_FILE     = os.path.join(DATA_DIR, "medals.json")

# ═══════════════════════════════════════════════════════════════
#                      УТИЛИТЫ JSON
# ═══════════════════════════════════════════════════════════════

def load_json(path: str) -> dict:
    if not os.path.exists(path):
        save_json(path, {})
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ═══════════════════════════════════════════════════════════════
#              ОТРИМАННЯ НАЛАШТУВАНЬ СЕРВЕРА
# ═══════════════════════════════════════════════════════════════

def get_guild_settings(guild_id: int) -> dict:
    s = load_json(SETTINGS_FILE)
    gid = str(guild_id)
    if gid not in s:
        s[gid] = {
            "staff_roles":      [],
            "verified_roles":   [],
            "unverified_roles": [],
            "join_roles":       [],
            "grant_roles":      {},
            "antiraid":         False,
            "ticket_counter":   0,
            "verify_channel":   None,
        }
        save_json(SETTINGS_FILE, s)
    return s[gid]

def save_guild_settings(guild_id: int, data: dict):
    s = load_json(SETTINGS_FILE)
    s[str(guild_id)] = data
    save_json(SETTINGS_FILE, s)

# ═══════════════════════════════════════════════════════════════
#                  ПЕРЕВІРКА ПРАВ
# ═══════════════════════════════════════════════════════════════

def has_perm(guild_id: int, member: discord.Member, perm: str) -> bool:
    if member.guild_permissions.administrator:
        return True
    gs = get_guild_settings(guild_id)
    staff_role_ids = [int(r) for r in gs.get("staff_roles", [])]
    member_role_ids = [r.id for r in member.roles]
    if any(r in staff_role_ids for r in member_role_ids):
        return True
    grants = load_json(GRANTS_FILE)
    user_grants = grants.get(str(guild_id), {}).get(str(member.id), [])
    return perm in user_grants or "all" in user_grants

# ═══════════════════════════════════════════════════════════════
#                    ФОРМИ ВЕРИФІКАЦІЇ
# ═══════════════════════════════════════════════════════════════

FORM_UA = """🇺🇦 **Анкета для Верифікації**

**1.** Звідки ви дізналися про нас?
**2.** Скільки часу ви знайомі з пікселями?
**3.** У яких фракціях ви були і які посади займали?
**4.** Яка ваша національність?
**5.** Де ви зараз проживаєте?
**6.** Ви будете допомагати нам?

> Після заповнення надішліть відповіді одним повідомленням. Очікуйте відповіді від адміністрації."""

FORM_EN = """🇬🇧 **Verification Form**

**1.** How did you hear about us?
**2.** How long have you been familiar with pixels?
**3.** Which factions have you been in, and what positions did you hold?
**4.** What is your nationality?
**5.** Where do you currently live?
**6.** Will you help us?

> After filling out the form, send your answers in one message and wait for a response."""

# ═══════════════════════════════════════════════════════════════
#                        ІНТЕНТ & БОТ
# ═══════════════════════════════════════════════════════════════

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ═══════════════════════════════════════════════════════════════
#               VIEW: КНОПКА СТВОРИТИ ТІКЕТ
# ═══════════════════════════════════════════════════════════════

class CreateTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📩 Створити тікет верифікації",
        style=discord.ButtonStyle.primary,
        custom_id="create_ticket_btn"
    )
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = interaction.user
        gs = get_guild_settings(guild.id)

        if gs.get("antiraid", False):
            await interaction.response.send_message(
                "🛡️ Антирейд режим активний. Створення тікетів тимчасово заблоковано.",
                ephemeral=True
            )
            return

        tickets = load_json(TICKETS_FILE)
        gid = str(guild.id)
        uid = str(member.id)
        for ch_id, tdata in tickets.get(gid, {}).items():
            if tdata.get("user_id") == uid and tdata.get("open", True):
                ch = guild.get_channel(int(ch_id))
                if ch:
                    await interaction.response.send_message(
                        f"❌ У вас вже є відкритий тікет: {ch.mention}",
                        ephemeral=True
                    )
                    return

        gs["ticket_counter"] = gs.get("ticket_counter", 0) + 1
        counter = gs["ticket_counter"]
        save_guild_settings(guild.id, gs)

        staff_role_ids = [int(r) for r in gs.get("staff_roles", [])]
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member: discord.PermissionOverwrite(
                read_messages=True, send_messages=True, read_message_history=True
            ),
            guild.me: discord.PermissionOverwrite(
                read_messages=True, send_messages=True, manage_channels=True, manage_messages=True
            ),
        }
        for rid in staff_role_ids:
            role = guild.get_role(rid)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=True, read_message_history=True
                )

        channel_name = f"⟬✅⟭・verification-ticket-{counter:02d}・⟬🇺🇦⟭"
        try:
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                reason=f"Verification ticket for {member}"
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Бот не має прав для створення каналів.", ephemeral=True
            )
            return

        if gid not in tickets:
            tickets[gid] = {}
        tickets[gid][str(ticket_channel.id)] = {
            "user_id": uid,
            "open": True,
            "created_at": time.time(),
            "lang": "ua"
        }
        save_json(TICKETS_FILE, tickets)

        view = TicketView(lang="ua")
        await ticket_channel.send(
            content=f"{member.mention} | Тікет верифікації",
            embed=build_form_embed("ua"),
            view=view
        )

        await interaction.response.send_message(
            f"✅ Тікет створено: {ticket_channel.mention}", ephemeral=True
        )


# ═══════════════════════════════════════════════════════════════
#              VIEW: КНОПКИ ВСЕРЕДИНІ ТІКЕТА
# ═══════════════════════════════════════════════════════════════

def build_form_embed(lang: str) -> discord.Embed:
    if lang == "ua":
        embed = discord.Embed(
            title="🇺🇦 Анкета для Верифікації",
            description=(
                "**1.** Звідки ви дізналися про нас?\n"
                "**2.** Скільки часу ви знайомі з пікселями?\n"
                "**3.** У яких фракціях ви були і які посади займали?\n"
                "**4.** Яка ваша національність?\n"
                "**5.** Де ви зараз проживаєте?\n"
                "**6.** Ви будете допомагати нам?\n\n"
                "> Після заповнення надішліть відповіді одним повідомленням. Очікуйте відповіді від адміністрації."
            ),
            color=discord.Color.blue()
        )
    else:
        embed = discord.Embed(
            title="🇬🇧 Verification Form",
            description=(
                "**1.** How did you hear about us?\n"
                "**2.** How long have you been familiar with pixels?\n"
                "**3.** Which factions have you been in, and what positions did you hold?\n"
                "**4.** What is your nationality?\n"
                "**5.** Where do you currently live?\n"
                "**6.** Will you help us?\n\n"
                "> After filling out the form, send your answers in one message and wait for a response."
            ),
            color=discord.Color.green()
        )
    return embed


lang_cooldowns: dict[int, float] = {}

class TicketView(discord.ui.View):
    def __init__(self, lang: str = "ua"):
        super().__init__(timeout=None)
        self.lang = lang

    @discord.ui.button(
        label="🌐 Змінити мову / Change language",
        style=discord.ButtonStyle.secondary,
        custom_id="ticket_lang_btn"
    )
    async def change_lang(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel_id = interaction.channel_id
        now = time.time()
        last = lang_cooldowns.get(channel_id, 0)
        if now - last < 5:
            wait = round(5 - (now - last), 1)
            await interaction.response.send_message(
                f"⏳ Зачекайте ще **{wait}с** перед зміною мови.", ephemeral=True
            )
            return
        lang_cooldowns[channel_id] = now

        tickets = load_json(TICKETS_FILE)
        gid = str(interaction.guild_id)
        cid = str(channel_id)
        current_lang = tickets.get(gid, {}).get(cid, {}).get("lang", "ua")
        new_lang = "en" if current_lang == "ua" else "ua"
        if gid in tickets and cid in tickets[gid]:
            tickets[gid][cid]["lang"] = new_lang
        save_json(TICKETS_FILE, tickets)

        new_view = TicketView(lang=new_lang)
        await interaction.message.edit(embed=build_form_embed(new_lang), view=new_view)
        await interaction.response.send_message(
            f"✅ Мова змінена на {'🇺🇦 Українська' if new_lang == 'ua' else '🇬🇧 English'}",
            ephemeral=True
        )

    @discord.ui.button(
        label="✅ Верифікувати",
        style=discord.ButtonStyle.success,
        custom_id="ticket_verify_btn"
    )
    async def verify_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member_staff = interaction.user

        if not has_perm(guild.id, member_staff, "verify"):
            await interaction.response.send_message(
                "❌ У вас немає прав для верифікації.", ephemeral=True
            )
            return

        tickets = load_json(TICKETS_FILE)
        gid = str(guild.id)
        cid = str(interaction.channel_id)
        ticket_data = tickets.get(gid, {}).get(cid)
        if not ticket_data:
            await interaction.response.send_message("❌ Тікет не знайдено.", ephemeral=True)
            return

        uid = int(ticket_data["user_id"])
        member = guild.get_member(uid)
        gs = get_guild_settings(guild.id)

        await interaction.response.defer(ephemeral=True)

        if member:
            for rid in gs.get("verified_roles", []):
                role = guild.get_role(int(rid))
                if role:
                    try:
                        await member.add_roles(role, reason="Verification passed")
                    except discord.Forbidden:
                        pass

            for rid in gs.get("unverified_roles", []):
                role = guild.get_role(int(rid))
                if role and role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Verification passed")
                    except discord.Forbidden:
                        pass

        if gid in tickets and cid in tickets[gid]:
            tickets[gid][cid]["open"] = False
        save_json(TICKETS_FILE, tickets)

        try:
            await interaction.channel.send(
                f"✅ {member.mention if member else 'Користувач'} верифікований! "
                f"Канал буде видалено через 5 секунд."
            )
        except Exception:
            pass

        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason="Verification completed")
        except Exception:
            pass

    @discord.ui.button(
        label="❌ Не верифікувати",
        style=discord.ButtonStyle.danger,
        custom_id="ticket_deny_btn"
    )
    async def deny_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if not has_perm(guild.id, interaction.user, "verify"):
            await interaction.response.send_message(
                "❌ У вас немає прав для верифікації.", ephemeral=True
            )
            return

        tickets = load_json(TICKETS_FILE)
        gid = str(guild.id)
        cid = str(interaction.channel_id)
        ticket_data = tickets.get(gid, {}).get(cid)

        if ticket_data:
            uid = int(ticket_data["user_id"])
            member = guild.get_member(uid)

            if gid in tickets and cid in tickets[gid]:
                tickets[gid][cid]["open"] = False
            save_json(TICKETS_FILE, tickets)

            await interaction.response.defer(ephemeral=True)
            try:
                await interaction.channel.send(
                    f"❌ {member.mention if member else 'Користувач'} не пройшов верифікацію. "
                    f"Канал буде видалено через 5 секунд."
                )
            except Exception:
                pass

            await asyncio.sleep(5)
            try:
                await interaction.channel.delete(reason="Verification denied")
            except Exception:
                pass
        else:
            await interaction.response.send_message("❌ Тікет не знайдено.", ephemeral=True)


# ═══════════════════════════════════════════════════════════════
#                      EVENTS
# ═══════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    print(f"✅ Discord бот запущено як {bot.user}")
    bot.add_view(CreateTicketView())
    bot.add_view(TicketView())
    try:
        synced = await tree.sync()
        print(f"✅ Синхронізовано {len(synced)} slash команд")
    except Exception as e:
        print(f"❌ Помилка синхронізації команд: {e}")


@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    gs = get_guild_settings(guild.id)

    if gs.get("antiraid", False):
        try:
            await member.send(
                "🛡️ На сервері активний антирейд режим. Повертайтеся пізніше."
            )
        except Exception:
            pass
        try:
            await member.kick(reason="Antiraid mode active")
        except Exception:
            pass
        return

    join_role_ids = gs.get("join_roles", [])
    for rid in join_role_ids:
        role = guild.get_role(int(rid))
        if role:
            try:
                await member.add_roles(role, reason="Auto join role")
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
#              SLASH КОМАНДИ: НАЛАШТУВАННЯ РОЛЕЙ
# ═══════════════════════════════════════════════════════════════

def _add_roles_to_list(gs: dict, key: str, *roles) -> list[discord.Role]:
    current = gs.get(key, [])
    added = []
    for role in roles:
        if role and str(role.id) not in current:
            current.append(str(role.id))
            added.append(role)
    gs[key] = current
    return added

def _remove_roles_from_list(gs: dict, key: str, *roles) -> list[discord.Role]:
    current = gs.get(key, [])
    removed = []
    for role in roles:
        if role and str(role.id) in current:
            current.remove(str(role.id))
            removed.append(role)
    gs[key] = current
    return removed

def _format_role_list(gs: dict, key: str, guild: discord.Guild) -> str:
    ids = gs.get(key, [])
    if not ids:
        return "*(немає)*"
    mentions = []
    for rid in ids:
        role = guild.get_role(int(rid))
        mentions.append(role.mention if role else f"`{rid}`")
    return ", ".join(mentions)


@tree.command(name="setroles-staff-add", description="➕ Додати Staff роль (до 5 за раз)")
@app_commands.describe(
    role1="Staff роль #1", role2="Staff роль #2", role3="Staff роль #3",
    role4="Staff роль #4", role5="Staff роль #5"
)
async def cmd_setroles_staff_add(
    interaction: discord.Interaction,
    role1: discord.Role,
    role2: Optional[discord.Role] = None,
    role3: Optional[discord.Role] = None,
    role4: Optional[discord.Role] = None,
    role5: Optional[discord.Role] = None,
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Тільки адміністратори.", ephemeral=True)
        return
    gs = get_guild_settings(interaction.guild_id)
    added = _add_roles_to_list(gs, "staff_roles", role1, role2, role3, role4, role5)
    save_guild_settings(interaction.guild_id, gs)
    all_now = _format_role_list(gs, "staff_roles", interaction.guild)
    added_txt = ", ".join(r.mention for r in added) if added else "*(вже були додані)*"
    await interaction.response.send_message(
        f"👮 **Staff ролі оновлено**\n➕ Додано: {added_txt}\n📋 Всі Staff ролі: {all_now}",
        ephemeral=True
    )


@tree.command(name="setroles-staff-remove", description="➖ Видалити Staff роль (до 5 за раз)")
@app_commands.describe(
    role1="Staff роль #1", role2="Staff роль #2", role3="Staff роль #3",
    role4="Staff роль #4", role5="Staff роль #5"
)
async def cmd_setroles_staff_remove(
    interaction: discord.Interaction,
    role1: discord.Role,
    role2: Optional[discord.Role] = None,
    role3: Optional[discord.Role] = None,
    role4: Optional[discord.Role] = None,
    role5: Optional[discord.Role] = None,
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Тільки адміністратори.", ephemeral=True)
        return
    gs = get_guild_settings(interaction.guild_id)
    removed = _remove_roles_from_list(gs, "staff_roles", role1, role2, role3, role4, role5)
    save_guild_settings(interaction.guild_id, gs)
    all_now = _format_role_list(gs, "staff_roles", interaction.guild)
    removed_txt = ", ".join(r.mention for r in removed) if removed else "*(не знайдено в списку)*"
    await interaction.response.send_message(
        f"👮 **Staff ролі оновлено**\n➖ Видалено: {removed_txt}\n📋 Залишились: {all_now}",
        ephemeral=True
    )


@tree.command(name="setroles-verified", description="✅ Додати/видалити роль верифікованого (до 5 за раз)")
@app_commands.describe(
    action="add або remove",
    role1="Роль #1", role2="Роль #2", role3="Роль #3",
    role4="Роль #4", role5="Роль #5"
)
@app_commands.choices(action=[
    app_commands.Choice(name="add — додати",    value="add"),
    app_commands.Choice(name="remove — видалити", value="remove"),
])
async def cmd_setroles_verified(
    interaction: discord.Interaction,
    action: str,
    role1: discord.Role,
    role2: Optional[discord.Role] = None,
    role3: Optional[discord.Role] = None,
    role4: Optional[discord.Role] = None,
    role5: Optional[discord.Role] = None,
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Тільки адміністратори.", ephemeral=True)
        return
    gs = get_guild_settings(interaction.guild_id)
    if action == "add":
        changed = _add_roles_to_list(gs, "verified_roles", role1, role2, role3, role4, role5)
        verb = "➕ Додано"
    else:
        changed = _remove_roles_from_list(gs, "verified_roles", role1, role2, role3, role4, role5)
        verb = "➖ Видалено"
    save_guild_settings(interaction.guild_id, gs)
    all_now = _format_role_list(gs, "verified_roles", interaction.guild)
    changed_txt = ", ".join(r.mention for r in changed) if changed else "*(нічого не змінилось)*"
    await interaction.response.send_message(
        f"✅ **Ролі верифікованого оновлено**\n{verb}: {changed_txt}\n📋 Всі ролі верифікованого: {all_now}",
        ephemeral=True
    )


@tree.command(name="setroles-unverified", description="❓ Додати/видалити роль неверифікованого (до 5 за раз)")
@app_commands.describe(
    action="add або remove",
    role1="Роль #1", role2="Роль #2", role3="Роль #3",
    role4="Роль #4", role5="Роль #5"
)
@app_commands.choices(action=[
    app_commands.Choice(name="add — додати",    value="add"),
    app_commands.Choice(name="remove — видалити", value="remove"),
])
async def cmd_setroles_unverified(
    interaction: discord.Interaction,
    action: str,
    role1: discord.Role,
    role2: Optional[discord.Role] = None,
    role3: Optional[discord.Role] = None,
    role4: Optional[discord.Role] = None,
    role5: Optional[discord.Role] = None,
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Тільки адміністратори.", ephemeral=True)
        return
    gs = get_guild_settings(interaction.guild_id)
    if action == "add":
        changed = _add_roles_to_list(gs, "unverified_roles", role1, role2, role3, role4, role5)
        verb = "➕ Додано"
    else:
        changed = _remove_roles_from_list(gs, "unverified_roles", role1, role2, role3, role4, role5)
        verb = "➖ Видалено"
    save_guild_settings(interaction.guild_id, gs)
    all_now = _format_role_list(gs, "unverified_roles", interaction.guild)
    changed_txt = ", ".join(r.mention for r in changed) if changed else "*(нічого не змінилось)*"
    await interaction.response.send_message(
        f"❓ **Ролі неверифікованого оновлено**\n{verb}: {changed_txt}\n📋 Всі ролі неверифікованого: {all_now}",
        ephemeral=True
    )


@tree.command(name="setroles-join", description="🚪 Додати/видалити роль при вході (до 5 за раз)")
@app_commands.describe(
    action="add або remove",
    role1="Роль #1", role2="Роль #2", role3="Роль #3",
    role4="Роль #4", role5="Роль #5"
)
@app_commands.choices(action=[
    app_commands.Choice(name="add — додати",    value="add"),
    app_commands.Choice(name="remove — видалити", value="remove"),
])
async def cmd_setroles_join(
    interaction: discord.Interaction,
    action: str,
    role1: discord.Role,
    role2: Optional[discord.Role] = None,
    role3: Optional[discord.Role] = None,
    role4: Optional[discord.Role] = None,
    role5: Optional[discord.Role] = None,
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Тільки адміністратори.", ephemeral=True)
        return
    gs = get_guild_settings(interaction.guild_id)
    if action == "add":
        changed = _add_roles_to_list(gs, "join_roles", role1, role2, role3, role4, role5)
        verb = "➕ Додано"
    else:
        changed = _remove_roles_from_list(gs, "join_roles", role1, role2, role3, role4, role5)
        verb = "➖ Видалено"
    save_guild_settings(interaction.guild_id, gs)
    all_now = _format_role_list(gs, "join_roles", interaction.guild)
    changed_txt = ", ".join(r.mention for r in changed) if changed else "*(нічого не змінилось)*"
    await interaction.response.send_message(
        f"🚪 **Ролі при вході оновлено**\n{verb}: {changed_txt}\n📋 Всі join ролі: {all_now}",
        ephemeral=True
    )


@tree.command(name="setroles-list", description="📋 Показати всі поточні ролі")
async def cmd_setroles_list(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Тільки адміністратори.", ephemeral=True)
        return
    gs = get_guild_settings(interaction.guild_id)
    guild = interaction.guild
    embed = discord.Embed(title="📋 Поточні ролі сервера", color=discord.Color.blurple())
    embed.add_field(name="👮 Staff ролі",             value=_format_role_list(gs, "staff_roles",      guild), inline=False)
    embed.add_field(name="✅ Ролі верифікованого",     value=_format_role_list(gs, "verified_roles",   guild), inline=False)
    embed.add_field(name="❓ Ролі неверифікованого",   value=_format_role_list(gs, "unverified_roles", guild), inline=False)
    embed.add_field(name="🚪 Join ролі",               value=_format_role_list(gs, "join_roles",       guild), inline=False)
    embed.add_field(name="🛡️ Антирейд",                value="✅ Увімкнено" if gs.get("antiraid") else "❌ Вимкнено", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ═══════════════════════════════════════════════════════════════
#          SLASH КОМАНДА: ВІДПРАВИТИ КНОПКУ ТІКЕТА
# ═══════════════════════════════════════════════════════════════

@tree.command(name="verifysent", description="Надіслати кнопку створення тікету верифікації")
async def cmd_verifysent(interaction: discord.Interaction):
    if not has_perm(interaction.guild_id, interaction.user, "verify"):
        await interaction.response.send_message("❌ Недостатньо прав.", ephemeral=True)
        return

    embed = discord.Embed(
        title="🔐 Верифікація",
        description=(
            "Для верифікації на сервері натисніть кнопку нижче.\n"
            "Буде створено особистий канал з анкетою.\n\n"
            "For verification on the server, click the button below.\n"
            "A private channel with a form will be created."
        ),
        color=discord.Color.gold()
    )
    await interaction.channel.send(embed=embed, view=CreateTicketView())
    await interaction.response.send_message("✅ Кнопку відправлено!", ephemeral=True)


# ═══════════════════════════════════════════════════════════════
#              SLASH КОМАНДИ: МОДЕРАЦІЯ
# ═══════════════════════════════════════════════════════════════

@tree.command(name="ban", description="Забанити учасника")
@app_commands.describe(member="Учасник", reason="Причина")
async def cmd_ban(interaction: discord.Interaction, member: discord.Member, reason: str = "Не вказана"):
    if not has_perm(interaction.guild_id, interaction.user, "ban"):
        await interaction.response.send_message("❌ Немає прав на бан.", ephemeral=True)
        return
    try:
        await member.send(f"🔨 Вас забанено на сервері **{interaction.guild.name}**. Причина: {reason}")
    except Exception:
        pass
    await member.ban(reason=reason)
    await interaction.response.send_message(f"🔨 **{member}** забанено. Причина: {reason}")


@tree.command(name="unban", description="Розбанити учасника по ID")
@app_commands.describe(user_id="ID учасника")
async def cmd_unban(interaction: discord.Interaction, user_id: str):
    if not has_perm(interaction.guild_id, interaction.user, "ban"):
        await interaction.response.send_message("❌ Немає прав.", ephemeral=True)
        return
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        await interaction.response.send_message(f"✅ Розбанено: **{user}**")
    except Exception as e:
        await interaction.response.send_message(f"❌ Помилка: {e}", ephemeral=True)


@tree.command(name="kick", description="Кікнути учасника")
@app_commands.describe(member="Учасник", reason="Причина")
async def cmd_kick(interaction: discord.Interaction, member: discord.Member, reason: str = "Не вказана"):
    if not has_perm(interaction.guild_id, interaction.user, "kick"):
        await interaction.response.send_message("❌ Немає прав на кік.", ephemeral=True)
        return
    try:
        await member.send(f"👟 Вас кікнули з **{interaction.guild.name}**. Причина: {reason}")
    except Exception:
        pass
    await member.kick(reason=reason)
    await interaction.response.send_message(f"👟 **{member}** кікнутий. Причина: {reason}")


@tree.command(name="mute", description="Замутити учасника")
@app_commands.describe(member="Учасник", minutes="Час у хвилинах", reason="Причина")
async def cmd_mute(
    interaction: discord.Interaction,
    member: discord.Member,
    minutes: int,
    reason: str = "Не вказана"
):
    if not has_perm(interaction.guild_id, interaction.user, "mute"):
        await interaction.response.send_message("❌ Немає прав на мут.", ephemeral=True)
        return
    until = discord.utils.utcnow() + timedelta(minutes=minutes)
    try:
        await member.timeout(until, reason=reason)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Недостатньо прав бота.", ephemeral=True)
        return
    mutes = load_json(MUTES_FILE)
    gid = str(interaction.guild_id)
    if gid not in mutes:
        mutes[gid] = {}
    mutes[gid][str(member.id)] = {"until": until.isoformat(), "reason": reason}
    save_json(MUTES_FILE, mutes)
    await interaction.response.send_message(
        f"🔇 **{member}** замучений на **{minutes} хв**. Причина: {reason}"
    )


@tree.command(name="unmute", description="Зняти мут з учасника")
@app_commands.describe(member="Учасник")
async def cmd_unmute(interaction: discord.Interaction, member: discord.Member):
    if not has_perm(interaction.guild_id, interaction.user, "mute"):
        await interaction.response.send_message("❌ Немає прав.", ephemeral=True)
        return
    try:
        await member.timeout(None)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Недостатньо прав бота.", ephemeral=True)
        return
    mutes = load_json(MUTES_FILE)
    gid = str(interaction.guild_id)
    if gid in mutes and str(member.id) in mutes[gid]:
        del mutes[gid][str(member.id)]
    save_json(MUTES_FILE, mutes)
    await interaction.response.send_message(f"🔊 Мут знятий з **{member}**")


# ═══════════════════════════════════════════════════════════════
#              SLASH КОМАНДИ: ВАРНИ
# ═══════════════════════════════════════════════════════════════

@tree.command(name="warn", description="Видати попередження учаснику")
@app_commands.describe(member="Учасник", reason="Причина")
async def cmd_warn(interaction: discord.Interaction, member: discord.Member, reason: str = "Не вказана"):
    if not has_perm(interaction.guild_id, interaction.user, "warn"):
        await interaction.response.send_message("❌ Немає прав на варн.", ephemeral=True)
        return

    warns = load_json(WARNS_FILE)
    gid = str(interaction.guild_id)
    uid = str(member.id)
    if gid not in warns:
        warns[gid] = {}
    if uid not in warns[gid]:
        warns[gid][uid] = []

    warns[gid][uid].append({
        "reason": reason,
        "by": str(interaction.user.id),
        "at": datetime.utcnow().isoformat()
    })
    save_json(WARNS_FILE, warns)

    count = len(warns[gid][uid])
    try:
        await member.send(
            f"⚠️ Ви отримали попередження на **{interaction.guild.name}**.\n"
            f"Причина: {reason}\nВарнів: **{count}/3**"
        )
    except Exception:
        pass

    msg = f"⚠️ **{member}** отримав попередження ({count}/3). Причина: {reason}"

    if count >= 3:
        gs = get_guild_settings(interaction.guild_id)
        for rid in gs.get("verified_roles", []):
            role = interaction.guild.get_role(int(rid))
            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason="3 warns reached")
                except Exception:
                    pass
        try:
            await member.send(f"👟 Ви кікнуті з **{interaction.guild.name}** за 3 попередження!")
        except Exception:
            pass
        try:
            await member.kick(reason="3 warns reached")
        except Exception:
            pass
        warns[gid][uid] = []
        save_json(WARNS_FILE, warns)
        msg += "\n🚨 **Досягнуто 3 варни — учасника кікнуто та знято роль верифікованого!**"

    await interaction.response.send_message(msg)


@tree.command(name="unwarn", description="Зняти останнє попередження учасника")
@app_commands.describe(member="Учасник")
async def cmd_unwarn(interaction: discord.Interaction, member: discord.Member):
    if not has_perm(interaction.guild_id, interaction.user, "warn"):
        await interaction.response.send_message("❌ Немає прав.", ephemeral=True)
        return

    warns = load_json(WARNS_FILE)
    gid = str(interaction.guild_id)
    uid = str(member.id)
    user_warns = warns.get(gid, {}).get(uid, [])

    if not user_warns:
        await interaction.response.send_message(f"ℹ️ У **{member}** немає варнів.", ephemeral=True)
        return

    warns[gid][uid].pop()
    save_json(WARNS_FILE, warns)
    count = len(warns[gid][uid])
    await interaction.response.send_message(
        f"✅ Знято варн з **{member}**. Залишилось: **{count}/3**"
    )


# ═══════════════════════════════════════════════════════════════
#           SLASH КОМАНДИ: АНТИРЕЙД
# ═══════════════════════════════════════════════════════════════

@tree.command(name="antiraid", description="Увімкнути/вимкнути антирейд режим")
@app_commands.describe(mode="on або off")
@app_commands.choices(mode=[
    app_commands.Choice(name="on",  value="on"),
    app_commands.Choice(name="off", value="off"),
])
async def cmd_antiraid(interaction: discord.Interaction, mode: str):
    if not has_perm(interaction.guild_id, interaction.user, "antiraid"):
        await interaction.response.send_message("❌ Немає прав.", ephemeral=True)
        return

    gs = get_guild_settings(interaction.guild_id)
    gs["antiraid"] = (mode == "on")
    save_guild_settings(interaction.guild_id, gs)

    status = "🛡️ **УВІМКНЕНО**" if gs["antiraid"] else "✅ **ВИМКНЕНО**"
    await interaction.response.send_message(f"Антирейд режим: {status}")


# ═══════════════════════════════════════════════════════════════
#           SLASH КОМАНДИ: GRANT ПРАВ
# ═══════════════════════════════════════════════════════════════

VALID_PERMS = ["ban", "warn", "kick", "mute", "verify", "antiraid", "announcement"]

@tree.command(name="grant", description="Видати права учаснику")
@app_commands.describe(
    member="Учасник",
    permission="Право: ban, warn, kick, mute, verify, antiraid, announcement"
)
async def cmd_grant(interaction: discord.Interaction, member: discord.Member, permission: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Тільки адміністратори.", ephemeral=True)
        return

    perm = permission.lower().strip()
    if perm not in VALID_PERMS and perm != "all":
        await interaction.response.send_message(
            f"❌ Невідоме право. Доступні: {', '.join(VALID_PERMS)}", ephemeral=True
        )
        return

    grants = load_json(GRANTS_FILE)
    gid = str(interaction.guild_id)
    uid = str(member.id)
    if gid not in grants:
        grants[gid] = {}
    if uid not in grants[gid]:
        grants[gid][uid] = []
    if perm not in grants[gid][uid]:
        grants[gid][uid].append(perm)
    save_json(GRANTS_FILE, grants)

    await interaction.response.send_message(f"✅ **{member}** отримав право: `{perm}`")


# ═══════════════════════════════════════════════════════════════
#           SLASH КОМАНДИ: ANNOUNCEMENT
# ═══════════════════════════════════════════════════════════════

@tree.command(name="announcement", description="Надіслати оголошення в ЛС всім учасникам сервера")
@app_commands.describe(message="Текст оголошення")
async def cmd_announcement(interaction: discord.Interaction, message: str):
    if not has_perm(interaction.guild_id, interaction.user, "announcement"):
        await interaction.response.send_message("❌ Немає прав.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    success = 0
    failed = 0

    embed = discord.Embed(
        title=f"📢 Оголошення від {guild.name}",
        description=message,
        color=discord.Color.gold(),
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text=f"Від: {interaction.user}")

    for member in guild.members:
        if member.bot:
            continue
        try:
            await member.send(embed=embed)
            success += 1
            await asyncio.sleep(0.1)
        except Exception:
            failed += 1

    await interaction.followup.send(
        f"📢 Оголошення надіслано!\n✅ Успішно: **{success}**\n❌ Не вдалося: **{failed}**",
        ephemeral=True
    )


# ═══════════════════════════════════════════════════════════════
#           SLASH КОМАНДИ: ІНФОРМАЦІЯ
# ═══════════════════════════════════════════════════════════════

@tree.command(name="warnlist", description="Показати всі варни учасника")
@app_commands.describe(member="Учасник")
async def cmd_warnlist(interaction: discord.Interaction, member: discord.Member):
    if not has_perm(interaction.guild_id, interaction.user, "warn"):
        await interaction.response.send_message("❌ Немає прав.", ephemeral=True)
        return
    warns = load_json(WARNS_FILE)
    gid = str(interaction.guild_id)
    uid = str(member.id)
    user_warns = warns.get(gid, {}).get(uid, [])
    if not user_warns:
        await interaction.response.send_message(f"ℹ️ У **{member}** немає варнів.")
        return
    embed = discord.Embed(title=f"⚠️ Варни: {member}", color=discord.Color.orange())
    for i, w in enumerate(user_warns, 1):
        embed.add_field(
            name=f"Варн #{i}",
            value=f"Причина: {w['reason']}\nДата: {w['at'][:10]}",
            inline=False
        )
    embed.set_footer(text=f"Всього: {len(user_warns)}/3")
    await interaction.response.send_message(embed=embed)


# ═══════════════════════════════════════════════════════════════
#                    СИСТЕМА МЕДАЛЕЙ
# ═══════════════════════════════════════════════════════════════

MEDAL_ICONS = {
    0:  "🎗️", 1:  "🏅", 2:  "🥉", 3:  "🥈", 4:  "🥇",
    5:  "⭐",  6:  "🌟", 7:  "💫", 8:  "🔰", 9:  "🛡️",
    10: "⚔️",  11: "👑", 12: "🎖️",
}

def get_medal_icon(importance: int) -> str:
    return MEDAL_ICONS.get(importance, "🎖️")


@tree.command(name="mplus", description="Видати медаль учаснику")
@app_commands.describe(member="Учасник", importance="Важність медалі (0–12)", name="Назва медалі")
async def cmd_mplus(interaction: discord.Interaction, member: discord.Member, importance: int, name: str):
    if not has_perm(interaction.guild_id, interaction.user, "warn"):
        await interaction.response.send_message("❌ Немає прав на видачу медалей.", ephemeral=True)
        return
    if not (0 <= importance <= 12):
        await interaction.response.send_message("❌ Важність медалі має бути від 0 до 12.", ephemeral=True)
        return

    medals = load_json(MEDALS_FILE)
    gid = str(interaction.guild_id)
    uid = str(member.id)
    if gid not in medals:
        medals[gid] = {}
    if uid not in medals[gid]:
        medals[gid][uid] = []

    medal_id = int(time.time() * 1000)
    date_str = datetime.utcnow().strftime("%d.%m.%Y")
    medals[gid][uid].append({
        "id": medal_id, "name": name, "importance": importance,
        "date": date_str, "by": str(interaction.user.id),
    })
    save_json(MEDALS_FILE, medals)

    icon = get_medal_icon(importance)
    embed = discord.Embed(title="🏆 Медаль видана!", color=discord.Color.gold())
    embed.add_field(name="Учасник", value=member.mention, inline=True)
    embed.add_field(name="Медаль", value=f"{name} {icon}", inline=True)
    embed.add_field(name="Важність", value=f"{importance}/12", inline=True)
    embed.add_field(name="Дата", value=date_str, inline=True)
    embed.add_field(name="ID медалі", value=str(medal_id), inline=True)
    embed.set_footer(text=f"Видав: {interaction.user}")
    await interaction.response.send_message(embed=embed)

    try:
        await member.send(
            f"🏆 Ви отримали медаль **{name}** {icon} (важність {importance}/12) "
            f"на сервері **{interaction.guild.name}**!"
        )
    except Exception:
        pass


@tree.command(name="mminus", description="Забрати медаль у учасника за ID")
@app_commands.describe(member="Учасник", medal_id="ID медалі")
async def cmd_mminus(interaction: discord.Interaction, member: discord.Member, medal_id: str):
    if not has_perm(interaction.guild_id, interaction.user, "warn"):
        await interaction.response.send_message("❌ Немає прав на видалення медалей.", ephemeral=True)
        return

    medals = load_json(MEDALS_FILE)
    gid = str(interaction.guild_id)
    uid = str(member.id)
    user_medals = medals.get(gid, {}).get(uid, [])
    new_medals = [m for m in user_medals if str(m["id"]) != str(medal_id)]

    if len(new_medals) == len(user_medals):
        await interaction.response.send_message(
            f"❌ Медаль з ID `{medal_id}` не знайдена у {member.mention}.", ephemeral=True
        )
        return

    medals[gid][uid] = new_medals
    save_json(MEDALS_FILE, medals)
    await interaction.response.send_message(f"✅ Медаль `{medal_id}` забрана у {member.mention}.")


@tree.command(name="medals", description="Показати медалі учасника")
@app_commands.describe(member="Учасник")
async def cmd_medals(interaction: discord.Interaction, member: discord.Member):
    medals = load_json(MEDALS_FILE)
    gid = str(interaction.guild_id)
    uid = str(member.id)
    user_medals = medals.get(gid, {}).get(uid, [])

    embed = discord.Embed(title=f"🏆 Медалі: {member.display_name}", color=discord.Color.gold())

    if not user_medals:
        embed.description = "У цього учасника ще немає медалей."
    else:
        sorted_medals = sorted(user_medals, key=lambda x: x["importance"], reverse=True)
        lines = []
        for i, m in enumerate(sorted_medals, 1):
            icon = get_medal_icon(m["importance"])
            lines.append(
                f"**{i}. {m['name']}** | {m['importance']}/12 {icon} | видана {m['date']} | ID: `{m['id']}`"
            )
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Всього медалей: {len(user_medals)}")

    embed.set_thumbnail(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


# ═══════════════════════════════════════════════════════════════
#                    МУЗИЧНИЙ ПЛЕЄР
# ═══════════════════════════════════════════════════════════════

# Стан музики для кожного сервера
music_states: dict[int, dict] = {}

YTDL_COOKIES_FILE = os.path.join(os.path.dirname(__file__), "cookies.txt")

# Шлях до ffmpeg
if sys.platform == "win32":
    FFMPEG_PATH = os.path.join(os.path.dirname(__file__), "ffmpeg", "ffmpeg.exe")
else:
    FFMPEG_PATH = os.path.join(os.path.dirname(__file__), "ffmpeg", "ffmpeg")


def get_music_state(guild_id: int) -> dict:
    if guild_id not in music_states:
        music_states[guild_id] = {
            "volume": 0.5,
            "current": None,
            "queue": [],
            "paused": False,
            "search_results": [],
            "player_message": None,
            "repeat": False,          # ← НОВИЙ СТАН: повтор вкл/вимк
        }
    return music_states[guild_id]


async def search_youtube(query: str) -> list[dict]:
    """Шукає 5 результатів на YouTube."""
    loop = asyncio.get_event_loop()

    def _search():
        opts = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "default_search": "ytsearch5",
            "source_address": "0.0.0.0",
            "extract_flat": True,
        }
        if os.path.isfile(YTDL_COOKIES_FILE):
            opts["cookiefile"] = YTDL_COOKIES_FILE

        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.extract_info(f"ytsearch5:{query}", download=False)
            entries = result.get("entries", []) if result else []
            tracks = []
            for e in entries[:5]:
                duration = e.get("duration") or 0
                mins, secs = divmod(int(duration), 60)
                tracks.append({
                    "title": e.get("title", "Невідомо"),
                    "url": e.get("url") or e.get("webpage_url", ""),
                    "duration": f"{mins}:{secs:02d}",
                    "webpage_url": e.get("webpage_url") or f"https://www.youtube.com/watch?v={e.get('id','')}",
                })
            return tracks

    return await loop.run_in_executor(None, _search)


async def download_audio_file(webpage_url: str) -> tuple[str, str, str]:
    """
    Завжди скачує аудіо як локальний MP3 файл.
    Повертає (local_path, title, duration).
    Після відтворення файл потрібно видалити вручну.
    """
    loop = asyncio.get_event_loop()
    has_cookies = os.path.isfile(YTDL_COOKIES_FILE)

    def _do_download():
        import tempfile
        import glob

        tmp_dir = tempfile.mkdtemp(prefix="discord_music_")
        out_template = os.path.join(tmp_dir, "audio.%(ext)s")

        opts = {
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "quiet": True,
            "noplaylist": True,
            "cookiefile": "cookies.txt",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "ffmpeg_location": os.path.dirname(FFMPEG_PATH),
        }
        if has_cookies:
            opts["cookiefile"] = YTDL_COOKIES_FILE

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(webpage_url, download=True)
            title    = info.get("title", "Невідомо") if info else "Невідомо"
            duration = info.get("duration", 0) or 0
            mins, secs = divmod(int(duration), 60)
            dur_str  = f"{mins}:{secs:02d}"

        # Знаходимо скачаний файл
        files = glob.glob(os.path.join(tmp_dir, "*.mp3"))
        if not files:
            files = glob.glob(os.path.join(tmp_dir, "*.*"))
        if not files:
            raise Exception("Аудіо файл не знайдено після завантаження")

        return files[0], title, dur_str

    return await loop.run_in_executor(None, _do_download)


def _cleanup_audio_file(local_path: str):
    """Видаляє аудіо файл та його тимчасову директорію."""
    try:
        if os.path.isfile(local_path):
            os.remove(local_path)
        parent = os.path.dirname(local_path)
        if os.path.isdir(parent) and not os.listdir(parent):
            os.rmdir(parent)
    except Exception:
        pass


async def _play_downloaded_track(state: dict, vc: discord.VoiceClient, track: dict):
    """
    Скачує трек і відтворює його. Після завершення — видаляє файл.
    Якщо увімкнений повтор — скачує і грає знову.
    """
    try:
        local_path, title, duration = await download_audio_file(track["webpage_url"])
    except Exception as e:
        print(f"[Music] Помилка завантаження: {e}")
        return

    # Оновлюємо інформацію про трек
    track["title"] = title
    track["duration"] = duration
    state["current"] = track
    state["paused"] = False

    if not vc.is_connected():
        _cleanup_audio_file(local_path)
        return

    # Зупиняємо поточне відтворення
    if vc.is_playing():
        vc.stop()

    source = discord.FFmpegPCMAudio(local_path, executable=FFMPEG_PATH)
    source = discord.PCMVolumeTransformer(source, volume=state.get("volume", 0.5))

    def _after_playback(err):
        # 1. Видаляємо файл після відтворення
        _cleanup_audio_file(local_path)

        if err:
            print(f"[Music] Помилка відтворення: {err}")

        # 2. Якщо повтор увімкнено і трек ще актуальний — грати знову
        if state.get("repeat") and state.get("current") and vc.is_connected():
            current_track = state["current"]
            asyncio.run_coroutine_threadsafe(
                _play_downloaded_track(state, vc, dict(current_track)),
                bot.loop
            )

    vc.play(source, after=_after_playback)


def build_player_embed(state: dict) -> discord.Embed:
    current = state.get("current")
    repeat_status = "🔁 Вкл" if state.get("repeat") else "➡️ Вимк"

    if not current:
        embed = discord.Embed(
            title="🎵 Музичний плеєр",
            description="Нічого не грає.",
            color=discord.Color.blurple()
        )
        embed.add_field(name="🔁 Повтор", value=repeat_status, inline=True)
        return embed

    paused = state.get("paused", False)
    status = "⏸️ Пауза" if paused else "▶️ Грає"
    vol = int(state.get("volume", 0.5) * 100)

    embed = discord.Embed(
        title=f"🎵 {status}",
        description=f"**[{current['title']}]({current['webpage_url']})**",
        color=discord.Color.green() if not paused else discord.Color.orange(),
    )
    embed.add_field(name="⏱️ Тривалість", value=current["duration"], inline=True)
    embed.add_field(name="🔊 Гучність",   value=f"{vol}%",           inline=True)
    embed.add_field(name="🔁 Повтор",     value=repeat_status,       inline=True)
    return embed


class SearchResultsView(discord.ui.View):
    """Відображає результати пошуку (1–5) для вибору треку."""

    def __init__(self, results: list[dict], state: dict, voice_client):
        super().__init__(timeout=60)
        self.results = results
        self.state = state
        self.voice_client = voice_client

        for i, track in enumerate(results, 1):
            label = f"{i}. {track['title'][:40]} [{track['duration']}]"
            btn = discord.ui.Button(
                label=label[:80],
                style=discord.ButtonStyle.secondary,
                row=(i - 1) // 2,
                custom_id=f"search_pick_{i}"
            )
            btn.callback = functools.partial(self._pick_callback, index=i - 1)
            self.add_item(btn)

    async def _pick_callback(self, interaction: discord.Interaction, index: int):
        await interaction.response.defer()
        track = dict(self.results[index])
        state = self.state
        vc = self.voice_client

        if not vc or not vc.is_connected():
            await interaction.followup.send("❌ Бот не в голосовому каналі.", ephemeral=True)
            return

        # Показуємо повідомлення завантаження
        loading_embed = discord.Embed(
            title="⬇️ Завантаження...",
            description=f"Скачую: **{track['title']}**\nЗачекайте...",
            color=discord.Color.yellow()
        )
        player_view = MusicPlayerView(state, vc)

        if state.get("player_message"):
            try:
                await state["player_message"].edit(embed=loading_embed, view=player_view)
                await interaction.message.delete()
            except Exception:
                state["player_message"] = await interaction.followup.send(embed=loading_embed, view=player_view)
        else:
            state["player_message"] = await interaction.followup.send(embed=loading_embed, view=player_view)

        # Скачуємо і відтворюємо
        await _play_downloaded_track(state, vc, track)

        # Оновлюємо embed після початку відтворення
        if state.get("player_message"):
            try:
                await state["player_message"].edit(
                    embed=build_player_embed(state),
                    view=MusicPlayerView(state, vc)
                )
            except Exception:
                pass


class MusicPlayerView(discord.ui.View):
    """Кнопки керування плеєром з кнопкою Повтор."""

    def __init__(self, state: dict, voice_client):
        super().__init__(timeout=None)
        self.state = state
        self.vc = voice_client

        # Динамічно оновлюємо кнопку Повтор
        for item in self.children:
            if hasattr(item, "custom_id") and item.custom_id == "music_repeat":
                if state.get("repeat"):
                    item.label = "🔁 Повтор: Вкл"
                    item.style = discord.ButtonStyle.success
                else:
                    item.label = "🔁 Повтор: Вимк"
                    item.style = discord.ButtonStyle.secondary
                break

    @discord.ui.button(label="▶️ / ⏸️", style=discord.ButtonStyle.primary, row=0)
    async def toggle_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.vc
        if not vc or not vc.is_connected():
            await interaction.response.send_message("❌ Бот не в голосовому каналі.", ephemeral=True)
            return
        if vc.is_paused():
            vc.resume()
            self.state["paused"] = False
        elif vc.is_playing():
            vc.pause()
            self.state["paused"] = True
        await interaction.response.edit_message(embed=build_player_embed(self.state), view=self)

    @discord.ui.button(label="⏹️ Стоп", style=discord.ButtonStyle.danger, row=0)
    async def stop_music(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.vc
        # Вимикаємо повтор щоб _after не перезапустив трек
        self.state["repeat"] = False
        if vc and vc.is_playing():
            vc.stop()
        self.state["current"] = None
        self.state["paused"] = False
        embed = discord.Embed(
            title="⏹️ Зупинено",
            description="Відтворення зупинено.",
            color=discord.Color.red()
        )
        embed.add_field(name="🔁 Повтор", value="➡️ Вимк", inline=True)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🔉 -10%", style=discord.ButtonStyle.secondary, row=1)
    async def vol_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.state
        new_vol = max(0.0, state.get("volume", 0.5) - 0.1)
        state["volume"] = round(new_vol, 2)
        vc = self.vc
        if vc and vc.source:
            vc.source.volume = new_vol
        await interaction.response.edit_message(embed=build_player_embed(state), view=self)

    @discord.ui.button(label="🔊 +10%", style=discord.ButtonStyle.secondary, row=1)
    async def vol_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.state
        new_vol = min(2.0, state.get("volume", 0.5) + 0.1)
        state["volume"] = round(new_vol, 2)
        vc = self.vc
        if vc and vc.source:
            vc.source.volume = new_vol
        await interaction.response.edit_message(embed=build_player_embed(state), view=self)

    @discord.ui.button(
        label="🔁 Повтор: Вимк",
        style=discord.ButtonStyle.secondary,
        row=1,
        custom_id="music_repeat"
    )
    async def toggle_repeat(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Перемикає повтор треку. Файл після завершення видаляється, а при повторі скачується знову."""
        self.state["repeat"] = not self.state["repeat"]
        if self.state["repeat"]:
            button.label = "🔁 Повтор: Вкл"
            button.style = discord.ButtonStyle.success
        else:
            button.label = "🔁 Повтор: Вимк"
            button.style = discord.ButtonStyle.secondary
        await interaction.response.edit_message(embed=build_player_embed(self.state), view=self)

    @discord.ui.button(label="🔀 Змінити музику", style=discord.ButtonStyle.primary, row=2)
    async def change_music(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "🔍 Введіть `/play <назва>` щоб знайти нову музику.", ephemeral=True
        )

    @discord.ui.button(label="🚪 Вийти з каналу", style=discord.ButtonStyle.danger, row=2)
    async def leave_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.vc
        # Вимикаємо повтор перед виходом
        self.state["repeat"] = False
        if vc and vc.is_connected():
            if vc.is_playing():
                vc.stop()
            await vc.disconnect()
        self.state["current"] = None
        self.state["paused"] = False
        guild_id = interaction.guild_id
        if guild_id in music_states:
            del music_states[guild_id]
        embed = discord.Embed(
            title="👋 Вийшов з каналу",
            description="Бот покинув голосовий канал.",
            color=discord.Color.greyple()
        )
        await interaction.response.edit_message(embed=embed, view=None)


@tree.command(name="play", description="Відтворити музику в голосовому каналі")
@app_commands.describe(query="Назва пісні або URL")
async def cmd_play(interaction: discord.Interaction, query: str):
    member = interaction.user
    if not member.voice or not member.voice.channel:
        await interaction.response.send_message(
            "❌ Спочатку зайдіть у голосовий канал!", ephemeral=True
        )
        return

    await interaction.response.defer()

    voice_channel = member.voice.channel
    guild = interaction.guild
    vc = guild.voice_client

    if vc is None:
        try:
            vc = await voice_channel.connect()
        except Exception as e:
            await interaction.followup.send(f"❌ Не вдалося підключитись: {e}", ephemeral=True)
            return
    elif vc.channel != voice_channel:
        await vc.move_to(voice_channel)

    state = get_music_state(guild.id)

    try:
        results = await search_youtube(query)
    except Exception as e:
        await interaction.followup.send(f"❌ Помилка пошуку: {e}", ephemeral=True)
        return

    if not results:
        await interaction.followup.send("❌ Нічого не знайдено.", ephemeral=True)
        return

    state["search_results"] = results

    embed = discord.Embed(
        title=f"🔍 Результати пошуку: `{query}`",
        color=discord.Color.blurple(),
    )
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"**{i}.** {r['title']} ⏱️ `{r['duration']}`")
    embed.description = "\n".join(lines)
    embed.set_footer(text="Оберіть трек — він буде скачаний і відтворений:")

    view = SearchResultsView(results, state, vc)
    await interaction.followup.send(embed=embed, view=view)


@tree.command(name="leave", description="Вийти з голосового каналу")
async def cmd_leave(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_connected():
        guild_id = interaction.guild_id
        state = music_states.get(guild_id, {})
        state["repeat"] = False  # Вимикаємо повтор
        if vc.is_playing():
            vc.stop()
        await vc.disconnect()
        if guild_id in music_states:
            del music_states[guild_id]
        await interaction.response.send_message("👋 Бот покинув голосовий канал.")
    else:
        await interaction.response.send_message("❌ Бот не в голосовому каналі.", ephemeral=True)


async def start_discord_bot():
    """Запуск Discord бота — вызывается из bot.py"""
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(start_discord_bot())
