from collections import OrderedDict
from asyncio import Lock
from pyromod import Client 

from pyrogram import filters, enums
from pyrogram.types import Message
from pyrogram.errors import PeerIdInvalid, FloodWait
import asyncio

from Modules import app, games_collection
from Assets import files

# Shared cache for both team and solo modes
# game_text_cache = OrderedDict()
# MAX_CACHE_SIZE = 30
# cache_lock = Lock()

# async def invalidate_game_cache(chat_id: int):
#     async with cache_lock:
#         if chat_id in game_text_cache:
#             del game_text_cache[chat_id]
            
async def wait_and_switch(client: Client, game_id: int):
    # await invalidate_game_cache(game_id)
    await games_collection.update_one({"game_id": game_id}, {"$set": {"joiningA": True}})
    await asyncio.sleep(30)
    game = await games_collection.find_one({"game_id": game_id})
    if game["joiningA"]:
        await games_collection.update_one({"game_id": game_id}, {"$set": {"joiningA": False, "joiningB": True}})
        await client.send_message(game_id, "⏰ Time's up for Team A! 👥 Join Team B by sending /join_teamB 📣")

    await asyncio.sleep(30)
    game = await games_collection.find_one({"game_id": game_id})
    if game["joiningB"]:
        await games_collection.update_one({"game_id": game_id}, {"$set": {"joiningB": False}})
        game_host_id = game["game_host"]
        game_host = await client.get_users(game_host_id)
        await client.send_message(game_id, f"{game_host.mention()} 👋 hey, now members are joined the teams! 🎉 Choose Team captains user /choose_cap 📝", parse_mode=enums.ParseMode.HTML)


@app.on_message(filters.command("create_team") & filters.group)
async def create_team(client: Client, message: Message):
    game_id = message.chat.id
    game = await games_collection.find_one({"game_id": game_id})
    if not game:
        await message.reply_text("No game is going on in this chat! 🏏😔")
        return
    if game["game_mode"] == "solo":
        await message.reply_text("This command cannot be used in solo mode! 🤝")
        return
    if message.from_user.id != game["game_host"]:
        await message.reply_text("Only the game host can create teams! 👮‍♂️")
        return

    await message.reply_text("🎉 Team creation is underway! Join Team A by sending /join_teamA 📣")

    await wait_and_switch(client, game_id)


@app.on_message(filters.command(["join_teamA", "join_teamB"], case_sensitive=True) & filters.group)
async def join_team(client: Client, message: Message):
    game_id = message.chat.id

    # Check if the user is already in any active game
    active_games = await games_collection.find(
        {"game_state": {"$in": ["joining", "started"]}, "players": message.from_user.id}
    ).to_list(length=100)

    if active_games:
        group_names = []
        for game in active_games:
            group_chat = await client.get_chat(game["game_id"])  # Fetch the group details
            group_names.append(group_chat.title)
        group_list = "\n".join([f"- {name}" for name in group_names])
        await message.reply(
            f"🚫 You're already in another game in the following group(s):\n{group_list}\nPlease finish those games before joining a new one."
        )
        return

    # Check if the current group has an active game
    game = await games_collection.find_one({"game_id": game_id})
    if not game:
        await message.reply_text("No game is going on in this chat! 🏏😔")
        return

    if game["game_mode"] == "solo":
        await message.reply_text("This command cannot be used in solo mode! 🤝")
        return

    if message.from_user.id == game["game_host"]:
        await message.reply_text("You are the host buddy, You can't join 🥹👑")
        return

    command = message.command[0]
    team = "A" if command == "join_teamA" else "B"
    user_id = message.from_user.id

    # Joining Team A
    if team == "A" and game["joiningA"]:
        if user_id in game["team_a"]["members"] or user_id in game["team_b"]["members"]:
            await message.reply_text("You are already in a Team! 🤝")
            return
        await games_collection.update_one({"game_id": game_id}, {"$push": {"team_a.members": user_id}})
        await message.reply_text(f"{message.from_user.mention()} joined Team A! ✈️", parse_mode=enums.ParseMode.HTML)

    # Joining Team B
    elif team == "B" and game["joiningB"]:
        if user_id in game["team_a"]["members"] or user_id in game["team_b"]["members"]:
            await message.reply_text("You are already in a Team! 🤝")
            return
        await games_collection.update_one({"game_id": game_id}, {"$push": {"team_b.members": user_id}})
        await message.reply_text(f"{message.from_user.mention()} joined Team B! 🚀", parse_mode=enums.ParseMode.HTML)

    else:
        await message.reply_text("You can't join this team right now! ⚠️")

########################

from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import time

# Dictionary to track last command usage per group
group_cooldowns = {}

@app.on_message(filters.command(["members_list", "teams"]))
async def members_list(client: Client, message: Message):
    game_id = message.chat.id
    user_id = message.from_user.id

    # Fetch game data
    game = await games_collection.find_one({"game_id": game_id})
    if not game:
        await message.reply_text("No game is going on in this chat! 🏏😔")
        return
    # if game.get("game_state", None) != "started":
        # await invalidate_game_cache(game_id) 
    # Get game host ID
    game_host_id = game.get("game_host")

    # Bypass cooldown if user is the game host
    if user_id != game_host_id:
        last_used = group_cooldowns.get(game_id, 0)
        if time.time() - last_used < 120:
            await message.reply_text("⏳ Members list can only be used once every 120 seconds in this group.")
            return
        group_cooldowns[game_id] = time.time()  # Update cooldown for the group

    # Check game mode and send the appropriate list
    if game['game_mode'] == 'solo': 
        await send_solo_list(client, game_id, game)
    else:
        await send_team_list(client, game_id, game)


async def send_team_list(client: Client, chat_id: int, game: dict):
    # async with cache_lock:
    #     if chat_id in game_text_cache:
    #         cached_text = game_text_cache[chat_id]
    #         await client.send_photo(chat_id, "https://files.catbox.moe/n0vxab.png", 
    #                               caption=cached_text, 
    #                               parse_mode=enums.ParseMode.MARKDOWN)
    #         return
            
    game_host_id = game.get("game_host")
    team_a_captain = game.get("team_a_captain")
    team_b_captain = game.get("team_b_captain")
    team_a_members = []
    team_b_members = []
    try:
        host_user = await client.get_users(game_host_id)
        host_mention = f"👽Game Host: @{host_user.username}" if host_user.username else f"👽Game Host: {host_user.first_name}"
    except:
        host_mention = "👑 Unknown Host"

    # Fetch Team A members
    for user_id in game["team_a"]["members"]:
        try:
            user = await client.get_users(user_id)
            member_text = f"@{user.username}" if user.username else user.mention(style=enums.ParseMode.MARKDOWN)
            if user_id == team_a_captain:
                member_text += " [C]"  # Add Captain tag
        except:
            member_text = f"User with ID {user_id} not found ❌"
        team_a_members.append(member_text)

    # Fetch Team B members
    for user_id in game["team_b"]["members"]:
        try:
            user = await client.get_users(user_id)
            member_text = f"@{user.username}" if user.username else user.mention(style=enums.ParseMode.MARKDOWN)
            if user_id == team_b_captain:
                member_text += " [C]"  # Add Captain tag
        except:
            member_text = f"User with ID {user_id} not found ❌"
        team_b_members.append(member_text)

    # Create the reply text
    reply_text = (
        f"{host_mention}\n\n"
        f"🟦 **Team A**\n\n" +
        '\n'.join(f"{i+1}. {member}" for i, member in enumerate(team_a_members)) +
        "\n\n"
        f"🟥 **Team B**\n\n" +
        '\n'.join(f"{i+1}. {member}" for i, member in enumerate(team_b_members))
    )
    # Update cache 
    # async with cache_lock:
    #     game_text_cache[chat_id] = reply_text
    #     if len(game_text_cache) > MAX_CACHE_SIZE:
    #         game_text_cache.popitem(last=False)
    # Send the team list with a photo
    await client.send_photo(chat_id, "https://files.catbox.moe/n0vxab.png", caption=reply_text, parse_mode=enums.ParseMode.MARKDOWN)


async def send_solo_list(client: Client, chat_id: int, game: dict):
    # async with cache_lock:
    #     if chat_id in game_text_cache:
    #         cached_text = game_text_cache[chat_id]
    #         await client.send_photo(chat_id, "https://files.catbox.moe/n0vxab.png", 
    #                               caption=cached_text, 
    #                               parse_mode=enums.ParseMode.MARKDOWN)
    #         return
    game_host_id = game.get("game_host")
    solo_members = []
    try:
        host_user = await client.get_users(game_host_id)
        host_mention = f"👽 @{host_user.username}" if host_user.username else f"👽 {host_user.first_name}"
    except:
        host_mention = "👑 Unknown Host"
    # Fetch solo players
    for user_id in game["players"]:
        try:
            user = await client.get_users(user_id)
            member_text = f"@{user.username}" if user.username else user.mention(style=enums.ParseMode.MARKDOWN)
        except:
            member_text = f"User with ID {user_id} not found ❌"
        solo_members.append(member_text)

    # Create the reply text
    reply_text = (
        f"👤 **Solo Players**\n\n" +
        '\n'.join(f"{i+1}. {member}" for i, member in enumerate(solo_members))
    )

    # Update cache and send message
    # async with cache_lock:
    #     game_text_cache[chat_id] = reply_text
    #     if len(game_text_cache) > MAX_CACHE_SIZE:
    #         game_text_cache.popitem(last=False)
    # Send the solo list with a photo
    await client.send_photo(chat_id, "https://files.catbox.moe/n0vxab.png", caption=reply_text, parse_mode=enums.ParseMode.MARKDOWN)


from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message

@app.on_message(filters.command("choose_cap"))
async def choose_captains(client: Client, message: Message):
    game_id = message.chat.id
    user_id = message.from_user.id

    # Fetch game data
    game = await games_collection.find_one({"game_id": game_id})
    if not game:
        await message.reply_text("No game is going on in this chat! 🏏😔")
        return

    # Check if user is the game host
    if user_id != game.get("game_host"):
        await message.reply_text("Only the game host can use this command! 🚫")
        return

    # Check if captains are already selected
    if game.get("team_a_captain") and game.get("team_b_captain"):
        await message.reply_text("Both team captains have already been selected! ✅")
        return

    # Generate buttons only if captains are not yet chosen
    buttons = []
    if not game.get("team_a_captain"):
        buttons.append([InlineKeyboardButton("🏆 Choose Team A Captain", callback_data="choose_cap_a")])
    if not game.get("team_b_captain"):
        buttons.append([InlineKeyboardButton("🏆 Choose Team B Captain", callback_data="choose_cap_b")])

    keyboard = InlineKeyboardMarkup(buttons)
    await message.reply_text("Game Host, please choose captains for Team A and Team B:", reply_markup=keyboard)


@app.on_callback_query(filters.regex("^choose_cap_(a|b)$"))
async def set_captain(client: Client, query: CallbackQuery):
    game_id = query.message.chat.id
    user_id = query.from_user.id
    team = query.data.split("_")[-1]  # 'a' or 'b'

    # Fetch game data
    game = await games_collection.find_one({"game_id": game_id})
    if not game:
        await query.answer("No game found!", show_alert=True)
        return

    # Verify user belongs to the correct team
    if user_id not in game[f"team_{team}"]["members"]:
        await query.answer("You are not in this team!", show_alert=True)
        return

    # Check if captain is already chosen
    if game.get(f"team_{team}_captain"):
        await query.answer("Captain already chosen!", show_alert=True)
        return

    # Set the captain
    await games_collection.update_one({"game_id": game_id}, {"$set": {f"team_{team}_captain": user_id}})

    # Fetch user details
    user = await client.get_users(user_id)
    captain_mention = f"@{user.username}" if user.username else user.mention(style=enums.ParseMode.MARKDOWN)

    # Fetch updated game data
    updated_game = await games_collection.find_one({"game_id": game_id})

    # Generate new button layout
    buttons = []
    if not updated_game.get("team_a_captain"):
        buttons.append([InlineKeyboardButton("🏆 Choose Team A Captain", callback_data="choose_cap_a")])
    if not updated_game.get("team_b_captain"):
        buttons.append([InlineKeyboardButton("🏆 Choose Team B Captain", callback_data="choose_cap_b")])

    # Update message with new button layout or remove buttons if both captains are selected
    if buttons:
        keyboard = InlineKeyboardMarkup(buttons)
        await query.message.edit_text("Game Host, please choose captains for Team A and Team B:", reply_markup=keyboard)
    else:
        await query.message.delete()
        await members_list(client, query.message)  # Send updated list
    game_host_id = game.get("game_host")
    try:
        host_user = await client.get_users(game_host_id)
        host_mention = f"👽 @{host_user.username}" if host_user.username else f"👽 {host_user.first_name}"
    except:
        host_mention = "👑 Unknown Host"
    await query.answer("Captain selected successfully!")
    await query.message.reply_text(f"{host_mention}\n🎉 {captain_mention} is now the captain of **Team {'A' if team == 'a' else 'B'}**! 🏆")




from pyrogram import Client, filters, enums
from pyrogram.types import Message
import re

@app.on_message(filters.command("cap_change"))
async def change_captain(client: Client, message: Message):
    game_id = message.chat.id
    user_id = message.from_user.id

    # Fetch game data
    game = await games_collection.find_one({"game_id": game_id})
    if not game:
        await message.reply_text("No game is going on in this chat! 🏏😔")
        return

    # Check if the user is the game host
    if user_id != game.get("game_host"):
        await message.reply_text("Only the game host can change captains! 🚫")
        return

    # Parse the command using regex
    match = re.match(r"/cap_change\s+([AB])\s*[|,\-]?\s*(\d+)", message.text, re.IGNORECASE)
    if not match:
        await message.reply_text("Invalid format! Use: `/cap_change A | 1`", parse_mode=enums.ParseMode.MARKDOWN)
        return

    team = match.group(1).upper()  # Convert to uppercase (A or B)
    player_index = int(match.group(2)) - 1  # Convert player position to zero-based index

    # Convert to lowercase for database keys
    team_key = f"team_{team.lower()}"
    team_members = game.get(team_key, {}).get("members", [])

    # Ensure the index is within range
    if player_index < 0 or player_index >= len(team_members):
        await message.reply_text("Invalid player selection! 🚫")
        return

    player_id = team_members[player_index]  # Get the actual player ID

    # Update the captain in the database
    await games_collection.update_one({"game_id": game_id}, {"$set": {f"{team_key}_captain": player_id}})

    # Fetch updated user details
    user = await client.get_users(player_id)
    captain_mention = f"@{user.username}" if user.username else user.mention(style=enums.ParseMode.MARKDOWN)

    await message.reply_text(f"🎉 {captain_mention} is now the captain of **Team {team}**! 🏆")



###########


@app.on_message(filters.command(["remove_A", "remove_B"], case_sensitive=True) & filters.group)
async def remove_member(client: Client, message: Message):
    game_id = message.chat.id
    game = await games_collection.find_one({"game_id": game_id})
    if not game:
        await message.reply_text("No game is going on in this chat! 🏏😔")
        return
    if game["game_mode"] == "solo":
        await message.reply_text("This command cannot be used in solo mode! 🤝")
        return
    if message.from_user.id != game["game_host"]:
        await message.reply_text("Only the game host can remove members! 🤝")
        return
    
    command = message.command[0]
    team = "A" if command == "remove_A" else "B"
    member_index = int(message.command[1]) - 1

    if team == "A":
        if member_index < len(game["team_a"]["members"]):
            await games_collection.update_one({"game_id": game_id}, {"$pull": {"team_a.members": game["team_a"]["members"][member_index]}})
            await message.reply_text(f"Member {member_index + 1} removed from Team A! ✈️")
            # await invalidate_game_cache(game_id)
        else:
            await message.reply_text("Invalid member index! ⚠️")
    elif team == "B":
        if member_index < len(game["team_b"]["members"]):
            await games_collection.update_one({"game_id": game_id}, {"$pull": {"team_b.members": game["team_b"]["members"][member_index]}})
            await message.reply_text(f"Member {member_index + 1} removed from Team B! 🚀")
            # await invalidate_game_cache(game_id)
        else:
            await message.reply_text("Invalid member index! ⚠️")


from pyrogram import Client, filters
from pyrogram.errors import PeerIdInvalid, FloodWait
from pyrogram.types import Message
import logging

@app.on_message(filters.command(["add_A", "add_B"], case_sensitive=True) & filters.group)
async def add_member(client: Client, message: Message):
    game_id = message.chat.id
    game = await games_collection.find_one({"game_id": game_id})

    # Check if game exists
    if not game:
        await message.reply_text("No game is going on in this chat! 🏏😔")
        return

    # Check game mode
    if game["game_mode"] == "solo":
        await message.reply_text("This command cannot be used in solo mode! 🤝")
        return

    # Check if user is host
    if message.from_user.id != game["game_host"]:
        await message.reply_text("Only the game host can add members! 🤝👥")
        return

    # Determine which team to add to
    try:
        command = message.command[0]
        team = "A" if command == "add_A" else "B"
        if message.reply_to_message_id:
            user_input = message.reply_to_message.from_user.id
        else:
            user_input = message.command[1]
    except:
        await message.reply_text("Please enter a valid id/username or reply to a user!")
        return

    # Resolve user_id
    try:
        user_id = int(user_input)
    except ValueError:
        try:
            user = await client.get_users(user_input)
            user_id = user.id
        except PeerIdInvalid:
            await message.reply_text("Invalid username! Please try again. 🤔")
            return
        except FloodWait as e:
            await message.reply_text(f"Flood wait error! Please try again after {e.x} seconds. ⏰")
            return
        except Exception as e:
            await message.reply_text(f"An error occurred! {e} 🤯")
            return

    # Prevent host from adding themselves
    if user_id == game["game_host"]:
        await message.reply_text("You are host buddy, You can't join🥹👑")
        return

    # Check if user is already in a team in this game
    if user_id in game["team_a"]["members"] or user_id in game["team_b"]["members"]:
        await message.reply_text("User is already in a Team! 🤝")
        return

    # Check if user is already in other active games (solo or team)
    solo_games = []
    team_games = []

    active_games = await games_collection.find({
        "game_state": {"$in": ["joining", "started"]},
    }).to_list(length=100)

    for g in active_games:
        if g["game_id"] == game_id:
            continue
        title = "Unknown Group (ID: {})".format(g["game_id"])
        try:
            group_chat = await client.get_chat(g["game_id"])
            title = group_chat.title
        except Exception as e:
            logging.error(f"Error fetching chat title for game_id {g['game_id']}: {e}")

        if g["game_mode"] == "solo" and user_id in g.get("players", []):
            solo_games.append(title)
        elif g["game_mode"] == "team" and (
            user_id in g.get("team_a", {}).get("members", []) or
            user_id in g.get("team_b", {}).get("members", []) or
            user_id == g.get("game_host")
        ):
            team_games.append(title)

    if solo_games or team_games:
        try:
            user_profile = await client.get_users(user_id)
            user_name = user_profile.first_name
        except:
            user_name = "This user"

        text = f"🚫 {user_name}, you're already in another game in the following group(s):\n"
        if solo_games:
            text += "\n**Solo Games:**\n" + "\n".join([f"- {g}" for g in solo_games])
        if team_games:
            text += "\n\n**Team Games:**\n" + "\n".join([f"- {g}" for g in team_games])
        text += "\nPlease finish those games before joining a new one."
        await message.reply_text(text)
        return

    # Add to team
    if team == "A":
        await games_collection.update_one({"game_id": game_id}, {"$push": {"team_a.members": user_id}})
        await message.reply_text("Member added to Team A! ✈️👍")
    elif team == "B":
        await games_collection.update_one({"game_id": game_id}, {"$push": {"team_b.members": user_id}})
        await message.reply_text("Member added to Team B! 🚀👊")