import discord
import logging


from discord import app_commands
from discord.ext import commands
from global_config import GUILD_ID


logger = logging.getLogger(__name__)


class SyncCog(commands.Cog):
  """A cog that adds a !sync and /sync command."""
  def __init__(self, guild: discord.Guild, tree: app_commands.CommandTree):
    self.guild = guild
    self.tree = tree

  async def cog_load(self):
    logger.info(f"SyncCog loaded.")

  @commands.hybrid_command()
  @app_commands.guilds(GUILD_ID)
  async def sync(self, ctx: commands.Context):
    """Sync the bot's commands to the guild. NOTE: Only needed on changes. This is heavily rate limited!!!"""
    await ctx.defer()
    await self.tree.sync(guild=self.guild)
    await ctx.reply(f"Successfully synced to {self.guild}!", ephemeral=True)
