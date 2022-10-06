import argparse
import asyncio
import discord
import logging
import sys
import traceback


from discord import app_commands
from discord.ext import commands
from global_config import GUILD_ID, SPREADSHEET_ID, SHEETS_SCOPES, DEV_ID, DISCORD_TOKEN
from google.oauth2.service_account import Credentials


from config import ConfigCog, ConfigWrapper
from sheets_orm import SheetsWrapper
from sync import SyncCog
from user_commands import RequestsCog, CallersCog, UserCommandsCog


logger = logging.getLogger(__name__)


class LoaderCog(commands.Cog):
  """
  A cog which loads all of the actual command cogs.

  LoaderCog will wait for the bot to connect to the Discord gateway so that
  the other cogs can make API calls in their `cog_load()` methods.
  """
  def __init__(self, bot: commands.Bot, sheets_wrapper: SheetsWrapper, config_path: str, schema_path: str):
    self.bot = bot
    self.sheets_wrapper = sheets_wrapper
    self.config_path = config_path
    self.schema_path = schema_path

  async def cog_load(self):
    self.setup_task = asyncio.create_task(self.initial_setup())

  async def handle_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Prints out any uncaught exceptions in commands"""
    # TODO: Stop printing the entire stacktrace in the Discord response.
    # TODO: Catch errors from the Sheets threads.
    # TODO: Add better separation between stacktraces within the logging.
    if interaction and isinstance(interaction.command, app_commands.Command):
      content = f"Error running `/{interaction.command.qualified_name}`:\n```py\n{''.join(traceback.format_exception(error))}```"
    else:
      content = f"Error:\n```py\n{''.join(traceback.format_exception(error))}```"
    logging.warning(content)

    # Obey Discord's 2000 character limit for messages, using 1900 for the mention and trunaction message.
    if len(content) > 2000:
      content = f"{content[:1900]} ...\n```**NOTE:** Stack trace truncated due to Discord's 2000 character limit."

    # Ping me if there's an error.
    guild = self.bot.get_guild(GUILD_ID)
    if guild:
      dev = guild.get_member(DEV_ID)
      if dev:
        content = f"{dev.mention}\n{content}"

    if not interaction.response.is_done():
      await interaction.response.send_message(content)
    else:
      await interaction.followup.send(content=content)

  async def initial_setup(self):
    """Waits for the bot to connect before loading the rest of the cogs."""
    try:
      logger.info("Waiting for bot to be ready...")
      await self.bot.wait_until_ready()
      logger.info("Bot ready, performing initial setup...")
      self.bot.tree.on_error = self.handle_command_error

      guild = self.bot.get_guild(GUILD_ID)
      if not guild:
        logging.error("Unable to find guild with ID {GUILD_ID}. Shutting down...")
        await self.bot.close()
        return

      await self.bot.add_cog(SyncCog(guild, self.bot.tree))
      config_wrapper = ConfigWrapper(self.config_path, self.schema_path, guild)
      await self.bot.add_cog(UserCommandsCog(self.sheets_wrapper, config_wrapper, guild))
      await self.bot.add_cog(ConfigCog(config_wrapper))
      await self.bot.add_cog(RequestsCog(self.sheets_wrapper, config_wrapper, guild))
      await self.bot.add_cog(CallersCog(self.sheets_wrapper, config_wrapper, guild))

      logging.info(f"Setup complete. Running in {guild} as {self.bot.user}!")
    except Exception as err:
      logging.error("Error in initial setup. Shutting down...", exc_info=err)
      await self.bot.close()


async def main():
  parser = argparse.ArgumentParser()
  parser.add_argument(
      "--config", default="dev_config.json", help="The path to the JSON config for the bot.")
  parser.add_argument(
      "--schema", default="config.schema", help="The path to the JSON schema for the bot config.")
  parser.add_argument(
      "--creds", default="creds.json", help="The path to the JSON service account key for Google Sheets.")
  args = parser.parse_args()

  sheets_creds = Credentials.from_service_account_file(
    args.creds, scopes=SHEETS_SCOPES)
  sheets_wrapper = SheetsWrapper(sheets_creds, SPREADSHEET_ID)

  intents = discord.Intents.default()
  intents.members = True
  intents.message_content = True
  logging.basicConfig(level=logging.INFO)
  bot = commands.Bot("!", intents=intents)

  async with bot:
    loader_cog = LoaderCog(bot, sheets_wrapper, args.config, args.schema)
    await bot.add_cog(loader_cog)
    await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
  asyncio.run(main())
