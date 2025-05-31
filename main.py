import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import gspread
from oauth2client.service_account import ServiceAccountCredentials

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree

# Google Sheets Setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/spreadsheets",
         "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("google_credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open("GD Creator Contest Submissions").sheet1

contest_data = {
    "active": False,
    "title": None,
    "theme": None,
    "deadline": None,
    "judging": None,
    "channel_announcement": None,
    "channel_review": None,
    "channel_podium": None,
    "entries": [],
    "judges": []
}

class ContestEntry:
    def __init__(self, user, level_id, level_name, description, yt_link):
        self.user = user
        self.level_id = level_id
        self.level_name = level_name
        self.description = description
        self.yt_link = yt_link
        self.scores = []

    def average_score(self):
        if not self.scores:
            return 0
        return round(sum(self.scores) / len(self.scores), 2)

@tree.command(name="contest_create")
@app_commands.checks.has_permissions(administrator=True)
async def contest_create(interaction: discord.Interaction, title: str, theme: str, deadline: str, judging: str):
    contest_data["active"] = True
    contest_data["title"] = title
    contest_data["theme"] = theme
    contest_data["deadline"] = deadline
    contest_data["judging"] = judging
    contest_data["entries"] = []
    await interaction.response.send_message(f"✅ Contest '{title}' has been created.", ephemeral=True)

@tree.command(name="contest_announce")
@app_commands.checks.has_permissions(administrator=True)
async def contest_announce(interaction: discord.Interaction, channel: discord.TextChannel):
    if not contest_data["active"]:
        await interaction.response.send_message("❌ No active contest.", ephemeral=True)
        return

    contest_data["channel_announcement"] = channel.id

    embed = discord.Embed(title=f"🎉 New Contest: {contest_data['title']}", color=0x00ff00)
    embed.add_field(name="🧠 Theme", value=contest_data['theme'], inline=False)
    embed.add_field(name="📆 Deadline", value=contest_data['deadline'], inline=False)
    embed.add_field(name="🧑‍⚖️ Judged by", value=contest_data['judging'], inline=False)
    embed.set_footer(text="Click the button below to submit your entry!")

    view = SubmitButtonView()
    await channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ Announcement posted.", ephemeral=True)

class SubmitButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Submit Entry", style=discord.ButtonStyle.green)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SubmitModal())

class SubmitModal(discord.ui.Modal, title="Submit Your Level"):
    level_id = discord.ui.TextInput(label="Level ID", required=True)
    level_name = discord.ui.TextInput(label="Level Name", required=True)
    description = discord.ui.TextInput(label="Description (optional)", style=discord.TextStyle.paragraph, required=False)
    yt_link = discord.ui.TextInput(label="YouTube Link (optional)", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        entry = ContestEntry(user=interaction.user, level_id=self.level_id.value, level_name=self.level_name.value,
                             description=self.description.value or "None", yt_link=self.yt_link.value or "None")
        contest_data["entries"].append(entry)

        # Google Sheet logging
        sheet.append_row([str(interaction.user), self.level_name.value, self.level_id.value,
                          self.description.value or "None", self.yt_link.value or "None"])

        # Post to review channel if set
        if contest_data["channel_review"]:
            review_channel = bot.get_channel(contest_data["channel_review"])
            if review_channel:
                embed = discord.Embed(title="🧱 New Contest Entry", color=0xff9900)
                embed.add_field(name="👤 By", value=interaction.user.mention)
                embed.add_field(name="🏷️ Level", value=f"{self.level_name.value} (ID: {self.level_id.value})", inline=False)
                if self.description.value:
                    embed.add_field(name="📝 Description", value=self.description.value, inline=False)
                if self.yt_link.value:
                    embed.add_field(name="📺 Video", value=self.yt_link.value, inline=False)
                await review_channel.send(embed=embed)

        await interaction.response.send_message("✅ Entry submitted!", ephemeral=True)

@tree.command(name="contest_set_review")
@app_commands.checks.has_permissions(administrator=True)
async def set_review(interaction: discord.Interaction, channel: discord.TextChannel):
    contest_data["channel_review"] = channel.id
    await interaction.response.send_message("✅ Review channel set.", ephemeral=True)

@tree.command(name="contest_set_podium")
@app_commands.checks.has_permissions(administrator=True)
async def set_podium(interaction: discord.Interaction, channel: discord.TextChannel):
    contest_data["channel_podium"] = channel.id
    await interaction.response.send_message("✅ Podium channel set.", ephemeral=True)

@tree.command(name="score")
@app_commands.checks.has_permissions(manage_messages=True)
async def score(interaction: discord.Interaction, user: discord.User, score: float):
    for entry in contest_data["entries"]:
        if entry.user == user:
            entry.scores.append(score)
            await interaction.response.send_message(f"✅ Score added to {user.display_name}. Current Avg: {entry.average_score()}", ephemeral=True)
            return
    await interaction.response.send_message("❌ Entry not found.", ephemeral=True)

@tree.command(name="podium_show")
@app_commands.checks.has_permissions(administrator=True)
async def podium_show(interaction: discord.Interaction):
    if not contest_data["entries"]:
        await interaction.response.send_message("❌ No entries to rank.", ephemeral=True)
        return

    sorted_entries = sorted(contest_data["entries"], key=lambda x: x.average_score(), reverse=True)[:3]
    podium_channel = bot.get_channel(contest_data["channel_podium"])
    if not podium_channel:
        await interaction.response.send_message("❌ Podium channel not set.", ephemeral=True)
        return

    podium_text = ""
    medals = ["🥇", "🥈", "🥉"]
    for i, entry in enumerate(sorted_entries):
        podium_text += f"{medals[i]} {i+1}st – “{entry.level_name}” by {entry.user.mention} – {entry.average_score()} pts\n"

    await podium_channel.send(f"🏆 **Contest Winners: {contest_data['title']}**\n\n{podium_text}")
    await interaction.response.send_message("✅ Podium posted.", ephemeral=True)

@bot.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {bot.user}")

bot.run("MTM3ODM1OTc4OTg4ODczNzI4MA.GeWHD_.NABY58lAgXEjP-4SRvrYw4ppoSatsuGzAuXAgM")
