import asyncio
# import configparser  # Removed: no longer needed
import logging
import os
from dotenv import load_dotenv

from telethon import TelegramClient, types, functions # Added functions
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import User, Chat, Channel

import db_utils

# Load environment variables from .env file
load_dotenv()

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.ini')  # Removed: config file no longer used

def load_config():
    """Loads configuration exclusively from environment variables."""
    api_id = int(os.environ["API_ID"])
    api_hash = os.environ["API_HASH"]
    phone_number = os.environ["PHONE_NUMBER"]
    target_group_entity = os.environ["TARGET_GROUP_ENTITY"]
    db_path_config = os.environ.get("DB_PATH", None)

    # Construct session name from phone number to avoid issues with special characters
    # The session_name will be the path prefix, e.g., "data/your_phone_digits"
    # Telethon will append ".session" to this path.
    base_session_name = phone_number.replace('+', '').replace(' ', '')
    session_name = os.path.join("data", base_session_name)

    # Construct absolute path for db_path if it's relative
    if db_path_config and not os.path.isabs(db_path_config):
        db_path = os.path.join(os.path.dirname(__file__), db_path_config)
    else:
        db_path = db_path_config  # Can be None to use default from db_utils or an absolute path

    return api_id, api_hash, phone_number, target_group_entity, session_name, db_path

async def get_group_member_count(client, target_group_entity_str):
    """Fetches the member count of the specified Telegram group/channel."""
    try:
        entity_to_fetch = target_group_entity_str
        is_numeric_id = False
        numeric_id_val = 0

        # Check if it looks like a numeric ID first
        if isinstance(target_group_entity_str, str) and \
           (target_group_entity_str.isdigit() or (target_group_entity_str.startswith('-') and target_group_entity_str[1:].isdigit())):
            is_numeric_id = True
            try:
                numeric_id_val = int(target_group_entity_str)
                logging.info(f"Parsed '{target_group_entity_str}' as numeric ID: {numeric_id_val}")
            except ValueError:
                is_numeric_id = False # Should not happen due to isdigit checks
                logging.warning(f"Could not convert '{target_group_entity_str}' to int despite checks, proceeding as string.")

        if is_numeric_id:
            if numeric_id_val > 0:
                # Positive ID, likely a user ID or a bare channel/chat ID.
                # For channels/megagroups, list_my_groups.py gives the positive channel_id.
                # We should try to resolve it as PeerChannel for get_entity.
                logging.info(f"Positive numeric ID {numeric_id_val} found. Attempting to resolve as PeerChannel.")
                entity_to_fetch = types.PeerChannel(channel_id=numeric_id_val)
            else:
                # Negative ID, likely already in the form -100<channel_id> or -<chat_id>
                entity_to_fetch = numeric_id_val 
        elif target_group_entity_str.startswith('@') or target_group_entity_str.startswith('https://t.me/joinchat/') or target_group_entity_str.startswith('https://t.me/+'):
            entity_to_fetch = target_group_entity_str
            logging.info(f"Attempting to get entity for: {entity_to_fetch} (type: str)")
        else:
            logging.warning(f"Unrecognized format for target_group_entity: {target_group_entity_str}. Treating as username/invite link.")
            entity_to_fetch = target_group_entity_str # Default to treating as a string (username/invite link)

        if entity_to_fetch:
            logging.info(f"Attempting to get entity for: {entity_to_fetch} (type: {type(entity_to_fetch)})")
            # entity = await client.get_entity(entity_to_fetch) # Old way

            # New way: Use GetFullChannelRequest if it's a channel/megagroup
            if isinstance(entity_to_fetch, types.PeerChannel) or (isinstance(entity_to_fetch, str) and not entity_to_fetch.isdigit() and not entity_to_fetch.startswith(('+', '-'))):
                # If it's a PeerChannel or a string that's likely a username or public link
                try:
                    # First, get the basic entity to ensure it's a channel
                    # For usernames/links, get_entity resolves them. For PeerChannel, it confirms.
                    temp_entity = await client.get_entity(entity_to_fetch)
                    if hasattr(temp_entity, 'id'): # Check if it's a channel/chat like entity
                        full_channel = await client(functions.channels.GetFullChannelRequest(channel=temp_entity))
                        # entity = full_channel.full_chat # 'entity' here is ChatFull, e.g. ChannelFull
                        participants_count = full_channel.full_chat.participants_count
                        
                        # Find the chat title from full_channel.chats
                        chat_title = "N/A"
                        if hasattr(full_channel, 'chats') and full_channel.chats:
                            target_id = full_channel.full_chat.id
                            for chat_obj in full_channel.chats:
                                if chat_obj.id == target_id:
                                    chat_title = getattr(chat_obj, 'title', 'N/A')
                                    break
                        
                        logging.info(f"Successfully fetched full channel/chat: {chat_title}, Participants: {participants_count}")
                        return participants_count
                    else: # Might be a user or something else not supporting GetFullChannelRequest directly
                        logging.warning(f"Entity {target_group_entity_str} resolved to a type not supporting GetFullChannelRequest directly. Type: {type(temp_entity)}")
                        # Fallback or specific handling if needed, for now, we assume it won't have participants_count
                        entity = temp_entity # Use the basic entity
                except ValueError as e:
                    logging.error(f"ValueError when trying to get entity or full channel for {target_group_entity_str}: {e}")
                    return None
                except Exception as e:
                    logging.error(f"Could not get full channel/chat info for {target_group_entity_str} via GetFullChannelRequest: {e}")
                    # Fallback to trying to get entity normally if GetFullChannelRequest fails for some reason
                    entity = await client.get_entity(entity_to_fetch)

            elif isinstance(entity_to_fetch, types.PeerChat): # For basic groups
                 # For basic groups, we might need client.get_participants with limit=0 then .total
                chat = await client.get_entity(entity_to_fetch)
                if hasattr(chat, 'participants_count'):
                    participants_count = chat.participants_count
                    logging.info(f"Successfully fetched entity (PeerChat): {getattr(chat, 'title', 'N/A')}, Participants: {participants_count}")
                    return participants_count
                else: # Fallback for basic groups if direct participants_count is not available
                    try:
                        participants = await client.get_participants(chat, limit=0)
                        participants_count = participants.total
                        logging.info(f"Successfully fetched participants for basic group: {getattr(chat, 'title', 'N/A')}, Total Participants: {participants_count}")
                        return participants_count
                    except Exception as e:
                        logging.error(f"Could not get participants for basic group {target_group_entity_str}: {e}")
                        return None

            else: # Should be PeerUser or something else, or direct entity from previous logic
                entity = await client.get_entity(entity_to_fetch)


            if entity and hasattr(entity, 'participants_count') and entity.participants_count is not None:
                logging.info(f"Successfully fetched entity: {getattr(entity, 'title', 'N/A')}, Participants: {entity.participants_count}")
                return entity.participants_count
            elif entity: # Entity fetched, but no participants_count or it's None
                 # This case should ideally be handled by GetFullChannelRequest now for channels
                logging.warning(f"Fetched entity {getattr(entity, 'title', 'N/A')} but participants_count is missing or None. Type: {type(entity)}")
                # If it's a user, it won't have participants_count.
                if isinstance(entity, types.User):
                    logging.info(f"Entity {getattr(entity, 'username', entity.id)} is a user, not a group/channel.")
                    return None
                # For channels where GetFullChannelRequest might have been skipped or failed, this is a fallback log.
                return None
            else:
                logging.warning(f"Could not resolve entity for {target_group_entity_str} to a type with participant count.")
                return None
    except ValueError as e:
        # Check if the error message is about peer not found, which is common for incorrect IDs/usernames
        if "Cannot find any entity corresponding to" in str(e) or "Could not find the input entity for" in str(e):
            logging.error(f"Could not find the group/channel: '{target_group_entity_str}'. Error: {e}. Please check the username, ID, or invite link.")
        else:
            logging.error(f"ValueError while processing '{target_group_entity_str}': {e}")
    except TypeError as e:
        logging.error(f"TypeError while processing entity '{target_group_entity_str}' (parsed as {entity_to_fetch}): {e}. This might indicate an issue with the ID type.")
    except Exception as e:
        logging.error(f"Error fetching group member count for '{target_group_entity_str}': {e}", exc_info=True)
    return None

async def main():
    """Main function to monitor Telegram group and store member count."""
    try:
        api_id, api_hash, phone_number, target_group_entity, session_name, db_path_cfg = load_config()
    except KeyError as e:
        logging.error(f"Missing required environment variable: {e}")
        return
    except ValueError as e:
        logging.error(f"Invalid value in environment variable: {e}")
        return

    # Initialize Telegram client
    # The session file will be created in the 'data/' subdirectory (e.g., data/your_phone_digits.session).
    client = TelegramClient(session_name, api_id, api_hash)
    db_conn = None

    try:
        logging.info("Connecting to Telegram...")
        await client.connect()

        if not await client.is_user_authorized():
            logging.info("First-time login or session expired. Please enter your phone number and code.")
            await client.send_code_request(phone_number)
            try:
                await client.sign_in(phone_number, input('Enter the code you received: '))
            except SessionPasswordNeededError:
                await client.sign_in(password=input('Your two-factor authentication password: '))
            logging.info("Successfully signed in.")
        else:
            logging.info("User is already authorized.")

        member_count = await get_group_member_count(client, target_group_entity)

        if member_count is not None:
            logging.info(f"Current member count for '{target_group_entity}': {member_count}")
            
            # Database operations
            db_conn = db_utils.get_db_connection(db_path=db_path_cfg) # Pass configured db_path
            db_utils.create_tables(db_conn)
            if db_utils.insert_member_count(db_conn, member_count):
                logging.info("Member count successfully saved to database.")
            else:
                logging.warning("Failed to save member count to database.")
        else:
            logging.warning(f"Could not retrieve member count for '{target_group_entity}'.")

    except ConnectionError as e: # More specific Telethon connection error
        logging.error(f"Telegram connection error: {e}. Please check your network and API credentials.")
    # except configparser.Error as e: # Removed: configparser no longer used
    #     logging.error(f"Configuration file error: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred in main_monitor: {e}", exc_info=True)
    finally:
        if db_conn:
            db_conn.close()
            logging.info("Database connection closed.")
        if client.is_connected():
            await client.disconnect()
            logging.info("Disconnected from Telegram.")

if __name__ == '__main__':
    asyncio.run(main())
