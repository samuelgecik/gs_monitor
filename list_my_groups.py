import asyncio
import configparser
import logging
import os

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import Dialog, Chat, Channel, User

# Configure basic logging - use ERROR to keep output clean unless issues
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.ini')

def load_config():
    """Loads configuration from config.ini."""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"Configuration file {CONFIG_FILE} not found. Please copy config.ini.template to config.ini and fill it out.")
        raise FileNotFoundError(f"Configuration file {CONFIG_FILE} not found.")

    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    
    try:
        api_id = config.getint('Telegram', 'api_id')
        api_hash = config.get('Telegram', 'api_hash')
        phone_number = config.get('Telegram', 'phone_number')
    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        logger.error(f"Missing configuration in {CONFIG_FILE}: {e}")
        raise ValueError(f"Missing configuration in {CONFIG_FILE}: {e}")
    
    session_name = phone_number.replace('+', '').replace(' ', '') + '_list_groups.session'
    return api_id, api_hash, phone_number, session_name

async def main():
    """Main function to list groups and channels the user is in."""
    try:
        api_id, api_hash, phone_number, session_name = load_config()
    except (FileNotFoundError, ValueError):
        return # Error already logged

    client = TelegramClient(session_name, api_id, api_hash)

    try:
        print("Connecting to Telegram...")
        await client.connect()

        if not await client.is_user_authorized():
            print("First-time login or session expired for this script.")
            await client.send_code_request(phone_number)
            try:
                await client.sign_in(phone_number, input('Enter the code you received: '))
            except SessionPasswordNeededError:
                await client.sign_in(password=input('Your two-factor authentication password: '))
            print("Successfully signed in.")
        else:
            print("User is already authorized.")

        print("\nFetching your chats (dialogs). This might take a moment...")
        print("-----------------------------------------------------")
        print("Groups and Channels you are a member of:")
        print("-----------------------------------------------------")
        
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            # We are interested in Chats (groups) and Channels
            if isinstance(entity, (Chat, Channel)):
                # For Channels, check if it's a megagroup or broadcast channel
                if isinstance(entity, Channel):
                    if entity.megagroup:
                        type_str = "Group (Megagroup)"
                    elif entity.broadcast:
                        type_str = "Channel (Broadcast)"
                    else:
                        type_str = "Channel (Unknown Type)" # Should not happen often
                else: # It's a Chat (legacy group)
                    type_str = "Group (Legacy)"
                
                print(f"Group/Channel: {entity.title}")
                print(f"  Usable for config.ini:")
                if hasattr(entity, 'username') and entity.username:
                    print(f"    Username: @{entity.username}")
                else:
                    print(f"    Username: Not available")
                print(f"    ID: {entity.id}")
                print(f"  Type: {type_str}")
                print("-----------------------------------------------------")

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        print(f"An error occurred: {e}")
    finally:
        if client.is_connected():
            await client.disconnect()
            print("Disconnected from Telegram.")

if __name__ == '__main__':
    asyncio.run(main())
