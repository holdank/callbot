# callbot
A Discord bot for managing a call-in show.

The bot maintains lists of users on the Discord server, backed by a Google Sheets spreadsheet for easy manual editing.

## Commands
### `/sync` or `!sync`
Syncs the bot's commands to the server. This is only needed on initial setup and changes to commands.

### `/screenme`
Adds the user of the command to the requests list.

### `/cfg`
| Subcommand | Description                              |
| ---------- |----------------------------------------- |
| `set`      | Sets any specified fields in the config. |
| `show`     | Shows the config.                        |

### `/requests`
| Subcommand               | Description                                                     |
| ------------------------ |---------------------------------------------------------------- |
| `add @user`              | Adds a user to the requests list.                               |
| `approve @user`          | Approves a user, moving them to a callers list.                 |
| `deny @user reason`      | Denies a user for the specified reason.                         |
| `send_message #channel`  | Sends the list of requesters to the specified channel.          |
| `refresh`                | Refreshes the request list. (Only needed if manually modified). |

### `/callers`
| Subcommand               | Description                                                         |
| ------------------------ |-------------------------------------------------------------------- |
| `add @user`              | Adds a user to a callers list, bypassing the approval process.      |
| `remove @user`           | Removes a user from any callers list.                               |
| `connect @user`          | Connects a user to the call-in channel.                             |
| `send_message #channel`  | Sends the lists of new and repeat callers to the specified channel. |
| `refresh`                | Refreshes the callers lists. (Only needed if manually modified).    |
| `chronicle`              | Adds a user to the caller history list.                             |
