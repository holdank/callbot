import asyncio
import discord
import logging
import traceback

from config import ConfigWrapper
from datetime import datetime
from discord import app_commands, ui
from discord.ext import commands, tasks
from global_config import GUILD_ID
from sheets_orm import SheetsWrapper
from typing import Optional


logger = logging.getLogger(__name__)
autoremoval_loop_interval = 10  # Seconds.


class ConfirmationView(ui.View):
  """
  A view which can be used to confirm/deny an option for the user.

  Usage:
    view = ConfirmationView()
    await itx.response.send_message("Blah blah", view=view)
    await view.wait()
    if view.said_yes:
      ...
  """
  def __init__(self):
    super().__init__()
    self.said_yes = False

  async def _shutdown(self, itx, content):
    for child in self.children:
      if isinstance(child, ui.Button):
        child.disabled = True
    self.stop()
    await itx.response.edit_message(content=content, view=self)

  @ui.button(label="Yes", style=discord.ButtonStyle.success)
  async def yes(self, itx: discord.Interaction, button: ui.Button):
    self.said_yes = True
    await self._shutdown(itx, "Confirmed.")

  @ui.button(label="No", style=discord.ButtonStyle.danger)
  async def no(self, itx: discord.Interaction, button: ui.Button):
    await self._shutdown(itx, "Aborting...")

  async def on_error(self, itx: discord.Interaction, error: Exception, item: ui.Item):
    await self._shutdown(itx, f"Error: {error}")

  async def on_timeout(self, itx: discord.Interaction):
    await self._shutdown(itx, f"This interaction has timed out.")


def sheet_time():
  # TODO: Migrate this to the sheets wrapper itself.
  return datetime.today().isoformat()


def get_mentions(user_rows: list, guild: discord.Guild) -> str:
  mention_list = []
  for values in user_rows:
    # TODO: Better handle empty rows.
    if not values:
      continue
    user_id = values[0]
    name = values[1]
    date_added = values[-1]
    user = guild.get_member(user_id)
    if not user:
      logger.warning(f"Skipping missing user: {user_id}, {name}")
      continue

    try:
      relative_time = discord.utils.format_dt(datetime.fromisoformat(date_added), style="R")
    except ValueError:
      # Catch the error here in case a date was mangled.
      relative_time = f"`Invalid Date: {date_added}`"
    mention_list.append(f"{user.mention} {relative_time}")

  return "\n".join(mention_list)


async def requests_message_content(sheets_wrapper, guild):
  content = "".join([
      "**Screening Wait List**\n",
      "These are people waiting to speak to someone, NOT a list for the live show. ",
      "Read above messages to find screener availability.\n\n"
      ])

  requesters = await asyncio.to_thread(sheets_wrapper.get_all, "Requests")
  content += get_mentions(requesters, guild)
  return content


async def callers_message_content(sheets_wrapper, guild):
  content = "".join([
      "**Caller Wait List**\n",
      "These are people waiting to speak on the live show.\n\n"
      ])

  new_callers = await asyncio.to_thread(sheets_wrapper.get_all, "New Callers")
  repeat_callers = await asyncio.to_thread(sheets_wrapper.get_all, "Repeat Callers")

  content += f"**New Callers:**\n{get_mentions(new_callers, guild)}"
  content += f"\n\n**Repeat Callers:**\n{get_mentions(repeat_callers, guild)}"
  return content


async def update_requests_message(itx: discord.Interaction, config_wrapper: ConfigWrapper, sheets_wrapper, guild):
  list_message = await config_wrapper.requests_message()
  if list_message:
    content = await requests_message_content(sheets_wrapper, guild)
    await list_message.edit(content=content)
  else:
    await itx.followup.send("No requests list message was found. Use `/requests send_message` to create one.")


async def update_callers_message(itx: discord.Interaction, config_wrapper: ConfigWrapper, sheets_wrapper, guild):
  list_message = await config_wrapper.callers_message()
  if list_message:
    content = await callers_message_content(sheets_wrapper, guild)
    await list_message.edit(content=content)
  else:
    await itx.followup.send("No callers list message was found. Use `/callers send_message` to create one.")


async def add_role(itx: discord.Interaction, user: discord.Member, role: Optional[discord.Role]) -> bool:
  if not role:
    await itx.followup.send(f"Unable to add role to {user}: Role not found.")
    return False
  await user.add_roles(role)
  return True


async def remove_role(itx: discord.Interaction, user: discord.Member, role: Optional[discord.Role]) -> bool:
  if not role:
    await itx.followup.send(f"Unable to remove role from {user}: Role not found.")
    return False
  await user.remove_roles(role)
  return True


class UserCommandsCog(commands.Cog, description="Call-in commands for users."):
  def __init__(self, sheets_wrapper: SheetsWrapper, config_wrapper: ConfigWrapper, guild: discord.Guild):
    self.sheets_wrapper = sheets_wrapper
    self.config_wrapper = config_wrapper
    self.guild = guild

  async def cog_load(self):
    logger.info("UserCommandsCog loaded.")

  @app_commands.command()
  @app_commands.guilds(GUILD_ID)
  async def screenme(self, itx: discord.Interaction):
    """Adds you to the list of people requesting to be screened."""
    user = itx.user
    if not isinstance(user, discord.Member):
      await itx.response.send_message("You must use this command in a guild channel!", ephemeral=True)
      return
    await itx.response.defer(ephemeral=True)
    if await asyncio.to_thread(self.sheets_wrapper.get, "Requests", user.id):
      await itx.followup.send("You're already on the requests list.", ephemeral=True)
      return
    if await asyncio.to_thread(self.sheets_wrapper.get, "New Callers", user.id):
      await itx.followup.send("You're already on the callers list.", ephemeral=True)
      return
    if await asyncio.to_thread(self.sheets_wrapper.get, "Repeat Callers", user.id):
      await itx.followup.send("You're already on the callers list.", ephemeral=True)
      return
    values = [user.id, str(user), sheet_time()]
    await asyncio.to_thread(self.sheets_wrapper.append, "Requests", values)
    if not await add_role(itx, user, await self.config_wrapper.requests_role()):
      return
    await update_requests_message(itx, self.config_wrapper, self.sheets_wrapper, self.guild)
    await itx.followup.send("You've been added to the requests list!", ephemeral=True)


@app_commands.guilds(GUILD_ID)
class RequestsCog(commands.GroupCog, group_name="requests", description="Commands to manage screening requests"):
  def __init__(self, sheets_wrapper: SheetsWrapper, config_wrapper: ConfigWrapper, guild: discord.Guild,
      dev: Optional[discord.Member]):
    self.sheets_wrapper = sheets_wrapper
    self.config_wrapper = config_wrapper
    self.guild = guild
    self.dev = dev

  async def cog_load(self):
    logger.info("RequestsCog loaded.")
    self.removal_loop.start()

  async def log(self, content: str, level=logging.INFO):
    logger.log(level, content)
    # Obey 2000 character message limits.
    if len(content) >= 2000:
      content = f"{content[:1900]}\n```**Note:** Stack trace truncated due to messaging limits."
    if level == logging.ERROR and self.dev:
      try:
        await self.dev.send(content)
      except Exception as error:
        logger.log(level, f"Error DMing dev: {error}")
    terminal = self.config_wrapper.terminal()
    if terminal:
      await terminal.send(content)

  @tasks.loop(seconds=autoremoval_loop_interval)
  async def removal_loop(self):
    """A loop which removes users who haven't been confirmed by the timeout."""
    # Get all requests.
    requesters = await asyncio.to_thread(self.sheets_wrapper.get_all, "Requests")

    missing_ids = []
    delete_users = []
    max_days = self.config_wrapper.requests_timeout()
    for values in requesters:
      if not values:
        continue
      user_id = values[0]
      name = values[1]
      date_added = values[-1]
      user = self.guild.get_member(user_id)

      if not user:
        await self.log(f"Removing missing user: `{name}` `({user_id})`.")
        missing_ids.append(user_id)
        continue

      try:
        dt = datetime.fromisoformat(date_added)
      except ValueError:
        await self.log(f"Skipping invalid datetime for `{user}`: {date_added}", level=logging.WARNING)
        continue

      td = datetime.today() - dt
      if td.days >= max_days:
        await self.log(f"Removing `{user}` who's been on the list for more than {max_days} days.")
        delete_users.append(user)

    delete_ids = [u.id for u in delete_users] + missing_ids
    if delete_ids:
      await asyncio.to_thread(self.sheets_wrapper.delete, "Requests", *delete_ids)
      await update_requests_message(itx, self.config_wrapper, self.sheets_wrapper, self.guild)
    for u in delete_users:
      try:
        await u.send(f"You were automatically removed from the MrGirl Hotline caller requests list because you weren't screened within {max_days} days.\n\nIf you'd still like to be screened, run `/screenme` again in the requests channel. Be sure to read the instructions to ensure you're screened next time.")
      except Exception as error:
        logger.info(f"Unable to DM `{u}` about their autoremoval:\n	{error}")


  @removal_loop.error
  async def on_removal_loop_error(self, error):
    content = f"**Requests removal loop failed.**\n\nIf the error has been resolved, you can start the loop again using `/requests start_loop`.\n```py{''.join(traceback.format_exception(error))}```"
    await self.log(content, level=logging.ERROR)

  @app_commands.command()
  async def send_message(self, itx: discord.Interaction, channel: discord.TextChannel):
    """Sends the call list message. Only needed on first setup."""
    # TODO: Handle existing message.
    await itx.response.defer()
    content = await requests_message_content(self.sheets_wrapper, self.guild)
    message = await channel.send(content, allowed_mentions=discord.AllowedMentions.none())

    # Store this new message in the config.
    config = self.config_wrapper.read()
    config["requests_message"] = f"{channel.id}-{message.id}"
    self.config_wrapper.write(config)

    await itx.followup.send(f"Successfully sent and stored the new requests message in {channel.mention}")

  @app_commands.command()
  async def refresh(self, itx:discord.Interaction):
    """Refreshes the requests list message. (Only needed for manual edits)."""
    await itx.response.defer()
    await update_requests_message(itx, self.config_wrapper, self.sheets_wrapper, self.guild)
    await itx.followup.send("Refreshed the message!")

  @app_commands.command()
  async def add(self, itx: discord.Interaction, user: discord.Member):
    """Adds a user to the requests list."""
    await itx.response.defer()
    if await asyncio.to_thread(self.sheets_wrapper.get, "Requests", user.id):
      await itx.followup.send(f"`{user}` is already on the requests list..")
      return
    if await asyncio.to_thread(self.sheets_wrapper.get, "New Callers", user.id):
      await itx.followup.send(f"`{user}` is already on the new callers list.")
      return
    if await asyncio.to_thread(self.sheets_wrapper.get, "Repeat Callers", user.id):
      await itx.followup.send(f"`{user}` is already on the repeat callers list.")
      return
    values = [user.id, str(user), sheet_time()]
    await asyncio.to_thread(self.sheets_wrapper.append, "Requests", values)
    if not await add_role(itx, user, await self.config_wrapper.requests_role()):
      return
    await update_requests_message(itx, self.config_wrapper, self.sheets_wrapper, self.guild)
    await itx.followup.send(f"Added {user} to the requests list!")

  @app_commands.command()
  async def approve(self, itx: discord.Interaction, user: discord.Member, european: bool=False):
    """Approves a user after screening, moving them to the callers lists."""
    await itx.response.defer()
    if not await asyncio.to_thread(self.sheets_wrapper.get, "Requests", user.id):
      view = ConfirmationView()
      await itx.followup.send(f"`{user}` isn't on the requests list, approve them anyway?", view=view)
      await view.wait()
      if not view.said_yes:
        return

    values = [user.id, str(user), european, sheet_time()]
    if await asyncio.to_thread(self.sheets_wrapper.get, "Caller History", user.id):
      await asyncio.to_thread(self.sheets_wrapper.append, "Repeat Callers", values)
    else:
      await asyncio.to_thread(self.sheets_wrapper.append, "New Callers", values)
    await asyncio.to_thread(self.sheets_wrapper.delete, "Requests", user.id)
    await update_requests_message(itx, self.config_wrapper, self.sheets_wrapper, self.guild)
    await update_callers_message(itx, self.config_wrapper, self.sheets_wrapper, self.guild)
    if not await remove_role(itx, user, await self.config_wrapper.requests_role()):
      return
    if not await add_role(itx, user, await self.config_wrapper.callers_role()):
      return
    await itx.followup.send(f"{user} has been approved!")

  @app_commands.command()
  async def deny(self, itx: discord.Interaction, user: discord.Member, reason: str):
    """Denies a user after screening, recording the reason they were rejected."""
    await itx.response.defer()
    if not await asyncio.to_thread(self.sheets_wrapper.get, "Requests", user.id):
      await itx.followup.send(f"`{user}` isn't on the requests list.")
      return
    values = [user.id, str(user), reason, sheet_time()]
    await asyncio.to_thread(self.sheets_wrapper.append, "Denied Requests", values)
    await asyncio.to_thread(self.sheets_wrapper.delete, "Requests", user.id)
    await update_requests_message(itx, self.config_wrapper, self.sheets_wrapper, self.guild)
    if not await remove_role(itx, user, await self.config_wrapper.requests_role()):
      return
    await itx.followup.send(f"`{user}` was denied: {reason}")

  @app_commands.command()
  async def remove(self, itx: discord.Interaction, user: discord.Member):
    """Removes a user from the requests list."""
    await itx.response.defer()
    if not await asyncio.to_thread(self.sheets_wrapper.get, "Requests", user.id):
      await itx.followup.send(f"`{user}` isn't on the requests list.")
      return
    await asyncio.to_thread(self.sheets_wrapper.delete, "Requests", user.id)
    await update_requests_message(itx, self.config_wrapper, self.sheets_wrapper, self.guild)
    if not await remove_role(itx, user, await self.config_wrapper.requests_role()):
      return
    await itx.followup.send(f"`{user}` was removed from requests.")

  @app_commands.command()
  async def start_loop(self, itx: discord.Interaction):
    """Starts the requests autoremoval loop. The loop is already started when the bot starts."""
    if self.removal_loop.is_running():
      await itx.response.send_message("The autoremoval loop is already running.")
      return
    self.removal_loop.start()
    await itx.response.send_message("Started the autoremoval loop.")

  @app_commands.command()
  async def stop_loop(self, itx: discord.Interaction):
    """Stops the requests autoremoval loop."""
    if not self.removal_loop.is_running():
      await itx.response.send_message("The autoremoval loop is stopped.")
      return
    self.removal_loop.cancel()
    await itx.response.send_message("Stopped the autoremoval loop.")



@app_commands.guilds(GUILD_ID)
class CallersCog(commands.GroupCog, group_name="callers", description="Commands to manage callers."):
  """A set of commands related to screened callers."""
  def __init__(self, sheets_wrapper: SheetsWrapper, config_wrapper: ConfigWrapper, guild: discord.Guild):
    self.sheets_wrapper = sheets_wrapper
    self.config_wrapper = config_wrapper
    self.guild = guild

  async def cog_load(self):
    logger.info("CallersCog loaded.")

  @app_commands.command()
  async def send_message(self, itx: discord.Interaction, channel: discord.TextChannel):
    """Sends the call list message. Only needed on first setup."""
    # TODO: Handle existing message.
    await itx.response.defer()
    content = await callers_message_content(self.sheets_wrapper, self.guild)
    message = await channel.send(content, allowed_mentions=discord.AllowedMentions.none())

    # Store this new message in the config.
    config = self.config_wrapper.read()
    config["callers_message"] = f"{channel.id}-{message.id}"
    self.config_wrapper.write(config)

    await itx.followup.send(f"Successfully sent and stored the new callers message in {channel.mention}")

  @app_commands.command()
  async def refresh(self, itx:discord.Interaction):
    """Refreshes the caller list message. (Only needed for manual edits)."""
    await itx.response.defer()
    await update_callers_message(itx, self.config_wrapper, self.sheets_wrapper, self.guild)
    await itx.followup.send("Refreshed the message!")

  @app_commands.command()
  async def add(self, itx: discord.Interaction, user: discord.Member, european: bool=False):
    """Adds a user to the callers list, bypassing the screening process."""
    await itx.response.defer()
    # Sanity check the lists.
    if await asyncio.to_thread(self.sheets_wrapper.get, "Requests", user.id):
      await itx.followup.send(f"`{user}` is already on the requests list. Use /requests approve.")
      return
    if await asyncio.to_thread(self.sheets_wrapper.get, "New Callers", user.id):
      await itx.followup.send(f"`{user}` is already on the new callers list.")
      return
    if await asyncio.to_thread(self.sheets_wrapper.get, "Repeat Callers", user.id):
      await itx.followup.send(f"`{user}` is already on the repeat callers list.")
      return

    # Add the user to the appropriate call list.
    values = [user.id, str(user), european, sheet_time()]
    if await asyncio.to_thread(self.sheets_wrapper.get, "Caller History", user.id):
      await asyncio.to_thread(self.sheets_wrapper.append, "Repeat Callers", values)
      await itx.followup.send(f"Added {user} to the new callers list!")
    else:
      await asyncio.to_thread(self.sheets_wrapper.append, "New Callers", values)
      await itx.followup.send(f"Added {user} to the new callers list!")
    if not await add_role(itx, user, await self.config_wrapper.callers_role()):
      return
    await update_callers_message(itx, self.config_wrapper, self.sheets_wrapper, self.guild)

  @app_commands.command()
  async def remove(self, itx: discord.Interaction, user: discord.Member):
    """Removes a user from the callers list."""
    await itx.response.defer()
    if await asyncio.to_thread(self.sheets_wrapper.get, "New Callers", user.id):
      await asyncio.to_thread(self.sheets_wrapper.delete, "New Callers", user.id)
      await update_callers_message(itx, self.config_wrapper, self.sheets_wrapper, self.guild)
      if not await remove_role(itx, user, await self.config_wrapper.callers_role()):
        return
      await itx.followup.send(f"Removed {user} from the new callers list.")
    elif await asyncio.to_thread(self.sheets_wrapper.get, "Repeat Callers", user.id):
      await asyncio.to_thread(self.sheets_wrapper.delete, "Repeat Callers", user.id)
      await update_callers_message(itx, self.config_wrapper, self.sheets_wrapper, self.guild)
      if not await remove_role(itx, user, await self.config_wrapper.callers_role()):
        return
      await itx.followup.send(f"Removed {user} from the repeat callers list.")
    else:
      await itx.followup.send(f"`{user}` isn't on either callers list.")

  @app_commands.command()
  async def connect(self, itx: discord.Interaction, user: discord.Member):
    """Connects a user to the live show voice channel."""
    await itx.response.defer()
    if not user.voice:
      await itx.followup.send(f"{user} is not in a voice channel")
      return
    show_vc = await self.config_wrapper.show_vc()
    if not show_vc:
      await itx.followup.send(f"Unable to find show VC. Check bot permissions, then try `/cfg set show_vc`.")
      return
    await user.move_to(show_vc)
    view = ConfirmationView()
    await itx.followup.send(f"Did {user} successfully connect? (Pressing no will kick them from VC.)", view=view)
    await view.wait()
    if view.said_yes:
      values = [user.id, str(user), sheet_time()]
      await asyncio.to_thread(self.sheets_wrapper.append, "Caller History", values)
      await asyncio.to_thread(self.sheets_wrapper.delete, "New Callers", user.id)
      await asyncio.to_thread(self.sheets_wrapper.delete, "Repeat Callers", user.id)
      await update_callers_message(itx, self.config_wrapper, self.sheets_wrapper, self.guild)
      if not await remove_role(itx, user, await self.config_wrapper.callers_role()):
        return
    else:
      if user.voice:
        # Kicks the user from vc.
        await user.move_to(None)

  @app_commands.command()
  async def chronicle(self, itx: discord.Interaction, user: discord.Member):
    """Adds a user to the past callers history list."""
    await itx.response.defer()
    # Sanity check the lists.
    if await asyncio.to_thread(self.sheets_wrapper.get, "Caller History", user.id):
      await itx.followup.send(f"`{user}` is already in the caller history.")
      return

    values = [user.id, str(user), sheet_time()]
    await asyncio.to_thread(self.sheets_wrapper.append, "Caller History", values)
    await update_callers_message(itx, self.config_wrapper, self.sheets_wrapper, self.guild)
    await itx.followup.send(f"Added {user} to the caller history.")
