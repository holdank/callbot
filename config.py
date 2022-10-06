import discord
import json
import jsonschema
import logging


from discord import app_commands
from discord.ext import commands
from global_config import GUILD_ID, SPREADSHEET_ID
from typing import Optional


logger = logging.getLogger(__name__)


class ConfigWrapper:
  """
  A class which wraps the JSON config for easy access.

  By convention, it will return None for missing Discord objects to let the
  caller decide how to handle this.
  """
  def __init__(self, config_path: str, schema_path: str, guild: discord.Guild):
    self.config_path = config_path
    self.schema_path = schema_path
    self.guild = guild
    # Read once to validate.
    self.read()

  def read(self, validate: bool=True) -> dict:
    with open(self.config_path, "r") as f:
      config = json.load(f)
    with open(self.schema_path, "r") as f:
      schema = json.load(f)
    jsonschema.validate(config, schema)
    return config

  def write(self, config: dict, validate: bool=True):
    if validate:
      with open(self.schema_path, "r") as f:
        schema = json.load(f)
      jsonschema.validate(config, schema)
    with open(self.config_path, "w") as f:
      json.dump(config, f, sort_keys=True, indent=2)

  def embed(self) -> discord.Embed:
    embed = discord.Embed(title=self.config_path)
    # Don't validate here since debugging may be needed.
    config = self.read(validate=False)
    embed.description = "\n".join([
      "```json",
      json.dumps(config, sort_keys=True, indent=2),
      "```"])
    embed.description += f"\n**Spreadsheet:** https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/"
    return embed

  def raw_config(self) -> str:
    with open(self.config_path, "r") as f:
      return f.read()

  async def callers_message(self) -> Optional[discord.Message]:
    return await self._get_message("callers_message")

  async def requests_message(self) -> Optional[discord.Message]:
    return await self._get_message("requests_message")

  async def callers_role(self) -> Optional[discord.Role]:
    return self._get_role("callers_role")

  async def requests_role(self) -> Optional[discord.Role]:
    return self._get_role("requests_role")

  async def show_vc(self) -> Optional[discord.VoiceChannel]:
    return self._get_channel("show_vc")

  async def _get_message(self, key: str) -> Optional[discord.Message]:
    config = self.read()
    # The key for a message is in the form "channel_id-message_id"
    try:
      channel_id, message_id = config[key].split("-")
      channel_id = int(channel_id)
      message_id = int(message_id)
    except ValueError:
      return None

    channel = self.guild.get_channel(channel_id)
    if not channel or not isinstance(channel, discord.TextChannel):
      return None
    return await channel.fetch_message(message_id)

  def _get_role(self, key: str) -> Optional[discord.Role]:
    config = self.read()
    return self.guild.get_role(config[key])

  def _get_channel(self, key: str) -> Optional[discord.VoiceChannel]:
    config = self.read()
    channel = self.guild.get_channel(config[key])
    if isinstance(channel, discord.VoiceChannel):
      return channel
    return None


@app_commands.guilds(GUILD_ID)
class ConfigCog(commands.GroupCog, group_name="cfg"):
  """Commands to view and modify the bot's config."""
  def __init__(self, config_wrapper: ConfigWrapper):
    self.config_wrapper = config_wrapper

  async def cog_load(self):
    logger.info("ConfigCog loaded.")

  @app_commands.command()
  async def show(self, itx: discord.Interaction):
    """Shows the active config file."""
    await itx.response.send_message(embed=self.config_wrapper.embed())

  @app_commands.command()
  @app_commands.describe(
      callers_role="The role given to future callers.",
      requests_role="The role give to users requesting to be screened.",
      callers_message="A message id for the callers list in the form channel_id-message_id",
      requests_message="A message id for the requests list in the form channel_id-message_id",
      show_vc="The VC channel for the live show.")
  async def set(self, itx: discord.Interaction,
      callers_role: Optional[discord.Role],
      requests_role: Optional[discord.Role],
      callers_message: Optional[str],
      requests_message: Optional[str],
      show_vc: Optional[discord.VoiceChannel]):
    """Sets the values of fields in the bot's Discord config file."""
    if not any([callers_role, requests_role, show_vc, callers_message, requests_message]):
      await itx.response.send_message("At least one option must be provided!")
      return

    config = self.config_wrapper.read()
    if callers_role:
      config["callers_role"] = callers_role.id
    if requests_role:
      config["requests_role"] = requests_role.id
    if show_vc:
      config["show_vc"] = show_vc.id
    if callers_message:
      config["callers_message"] = callers_message
    if requests_message:
      config["requests_message"] = requests_message
    self.config_wrapper.write(config)
    await itx.response.send_message(f"Successfully updated config!", embed=self.config_wrapper.embed())
