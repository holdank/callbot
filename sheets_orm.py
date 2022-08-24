import asyncio
import discord


from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from typing import Optional
from global_config import SPREADSHEET_ID, SHEETS_SCOPES


def value_list(values: list):
  """Creates a Google Sheets value list for API calls."""
  # Each value should be a string since Google Sheets does weird conversions.
  value_list = {
      "values": {
        "values": [str(v) for v in values]
        }
      }
  return value_list

def value_multi_list(values_list: list):
  """Creates a value list with multiple values."""
  # TODO: consolidate this with value_list()
  # Each value should be a string since Google Sheets does weird conversions.
  value_list = {
      "values": [
        { "values": [str(v) for v in values] } for values in values_list
        ]
      }
  return value_list


def restore_ints(value_list):
  """
  Restores int values that must be converted to str for Google Sheets due to
  the size limit on ints.
  """
  for i in range(len(value_list)):
    for j in range(len(value_list[i])):
      value = value_list[i][j]
      if isinstance(value, str) and value.isdigit():
        value_list[i][j] = int(value)


# TODO: Stop using magic strings for the sheet names.
class SheetsWrapper:
  """A class which wraps Google Sheets API calls to simplify operations."""
  def __init__(self, credentials, spreadsheet_id):
    self.spreadsheet_id = spreadsheet_id
    service = build('sheets', 'v4', credentials=credentials)
    self.sheets = service.spreadsheets()

  def _fetch_rows(self, range) -> list[list]:
    result = self.sheets.values().get(
        spreadsheetId=self.spreadsheet_id,
        range=range,
        valueRenderOption="UNFORMATTED_VALUE").execute()
    values = result.get("values")
    if values:
      restore_ints(values)
    return values

  def get_all(self, sheet: str) -> list[dict]:
    rows = self._fetch_rows(sheet)
    if not rows:
      return None
    # Skip the first row since that was a header.
    return rows[1:]

  def get(self, sheet: str, user_id: int) -> Optional[list]:
    rows = self.get_all(sheet) or []
    return discord.utils.find(lambda row: row and (row[0] == user_id), rows)

  def append(self, sheet: str, values: list):
    result = self.sheets.values().append(
        spreadsheetId=self.spreadsheet_id,
        range=sheet,
        valueInputOption="RAW",
        body=value_list(values)).execute()
    return result

  def update(self, sheet: str, values: list):
    if not values:
      raise ValueError("Must have at least one value (user_id) for an update.")

    rows = self.get_all(sheet)
    if not rows:
      return None
    # Find the row number.
    # Enumerate starting at 2 since the rows are 1-indexed and the first row
    # is the header, which get_all() doesn't return.
    numbered_rows = enumerate(rows, 2)
    print("\n".join(map(str, rows)))
    data = discord.utils.find(lambda row: row and (row[1][0] == values[0]), numbered_rows)
    if not data:
      raise KeyError(f"No row was found in {sheet} with {values[0]}.")
    i = data[0]

    result = self.sheets.values().update(
        spreadsheetId=self.spreadsheet_id,
        range=f"{sheet}!{i}:{i}",
        valueInputOption="RAW",
        body=value_list(values)).execute()
    return result

  def delete(self, sheet: str, user_id: int):
    """Deletes rows matching the user_id by overwriting them"""
    rows = self.get_all(sheet)
    new_rows = list(filter(lambda row: (not row) or (row[0] != user_id), rows))

    num_clears = len(rows) - len(new_rows)
    # Sheets doesn't like empty updates.
    if num_clears == 0:
      return None
    # Pad with empty rows so the table gets cleared out.
    for _ in range(num_clears):
      new_rows.append([""]*5)

    result = self.sheets.values().update(
        spreadsheetId=self.spreadsheet_id,
        range=f"{sheet}!2:{2+len(new_rows)}",
        valueInputOption="RAW",
        body=value_multi_list(new_rows)).execute()
    return result


async def main():
  creds = Credentials.from_service_account_file(
      "creds.json", scopes=SHEETS_SCOPES)
  wrapper = SheetsWrapper(creds, SPREADSHEET_ID)
  # Test stuff here.


if __name__ == '__main__':
  asyncio.run(main())
