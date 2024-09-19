import logging
import os
import asyncio
import json
import time
from io import BytesIO
from pytoniq_core import Address
import qrcode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import Bot, Dispatcher, html, types, F
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile, FSInputFile
from aiogram.types import CallbackQuery
from dotenv import load_dotenv
import pytonconnect.exceptions
from pytonconnect import TonConnect
from tc_storage import TcStorage
from messages import get_comment_message
from ai_module import call_openai



# Load environment variables from a .env file
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get the Telegram bot token and OpenAI API key from environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MANIFEST_URL = os.getenv('MANIFEST_URL')

# Check if both environment variables are loaded correctly
if not TOKEN:
    raise ValueError("Telegram bot token is not set! Check your environment variables.")

# Initialize the dispatcher for handling commands
dp = Dispatcher()
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def connector_is_here(chat_id: int) -> TonConnect:
    return TonConnect(MANIFEST_URL, storage=TcStorage(chat_id))

# Function to create the main menu buttons
def create_main_menu():
    """Generates the inline keyboard markup with buttons."""
    FSInputFile("./tarot_coin.jpeg")
    button_start = InlineKeyboardButton(text="Start Journey", callback_data="start_journey")
    button_prophet = InlineKeyboardButton(text="Get a Prophecy", callback_data="get_prophecy")
    button_invite = InlineKeyboardButton(text="Invite a Friend", callback_data="invite_friend")
    button_wish = InlineKeyboardButton(text="Wish", callback_data="wish")
    button_wallet = InlineKeyboardButton(text="Connect TON Wallet", callback_data="connect_wallet")

    # Inline keyboard with buttons arranged in rows
    return InlineKeyboardMarkup(inline_keyboard=[
        [button_start],
        [button_wish],
        [button_prophet, button_invite],
        [button_wallet]
    ])

@dp.message(CommandStart())
async def command_start_handler(message: types.Message):
    chat_id = message.chat.id
    connector_ton = connector_is_here(chat_id)
    connected = await connector_ton.restore_connection()
    photo = FSInputFile("./tarot_coin.jpeg")
    markup = create_main_menu()
    await message.answer_photo(photo=photo,
                               caption=f"Hello, {html.bold(message.from_user.full_name)}! What do you want to know today, seeker?",
                               reply_markup=markup)


@dp.message(Command('transaction'))
async def send_transaction(message: types.Message):
    connector_ton = connector_is_here(message.chat.id)
    connected = await connector_ton.restore_connection()
    if not connected:
        await message.answer('Connect wallet first!')
        return

    transaction = {
        'valid_until': int(time.time() + 3600),
        'messages': [
            get_comment_message(
                destination_address='0:0000000000000000000000000000000000000000000000000000000000000000',
                amount=int(0.01 * 10 ** 9),
                comment='hello world!'
            )
        ]
    }

    await message.answer(text='Approve transaction in your wallet app!')
    try:
        await asyncio.wait_for(connector_ton.send_transaction(
            transaction=transaction
        ), 300)
    except asyncio.TimeoutError:
        await message.answer(text='Timeout error!')
    except pytonconnect.exceptions.UserRejectsError:
        await message.answer(text='You rejected the transaction!')
    except Exception as e:
        await message.answer(text=f'Unknown error: {e}')

async def disconnect_wallet(message: types.Message):
    connector_ton = connector_is_here(message.chat.id)
    await connector_ton.restore_connection()
    await connector_ton.disconnect()
    await message.answer('You have been successfully disconnected!')

async def connect_wallet(message: types.Message, wallet_name: str):
    """Initiates the wallet connection process for the selected wallet."""
    connector_ton = connector_is_here(message.chat.id)

    wallets_list = connector_ton.get_wallets()
    wallet = None

    # Find the selected wallet
    for w in wallets_list:
        if w['name'].lower() == wallet_name.lower():
            wallet = w

    if wallet is None:
        await message.answer(f'Unknown wallet: {wallet_name}')
        return

    # Generate the connection URL for the selected wallet
    generated_url = await connector_ton.connect(wallet)

    await message.answer(f"Here is the connection URL: {generated_url}")

    mk_b = InlineKeyboardBuilder()
    mk_b.button(text='Connect', url=generated_url)

    # Generate and send the QR code
    img = qrcode.make(generated_url)
    stream = BytesIO()
    img.save(stream)
    file = BufferedInputFile(file=stream.getvalue(), filename='qrcode')

    await message.answer_photo(photo=file, caption='Connect wallet within 3 minutes', reply_markup=mk_b.as_markup())

    # Check connection status
    for i in range(1, 180):
        await asyncio.sleep(1)
        if connector_ton.connected and connector_ton.account.address:
            wallet_address = Address(connector_ton.account.address).to_str(is_bounceable=False)
            await message.answer(f'You are connected with address <code>{wallet_address}</code>')
            logger.info(f'Connected with address: {wallet_address}')
            return

    await message.answer(f'Timeout error! Connection failed.')



@dp.callback_query(F.data == "connect_wallet")
async def connect_ton_wallet(call: CallbackQuery):
    connector_ton = connector_is_here(call.message.chat.id)
    wallets_list = connector_ton.get_wallets()
    tonkeeper_wallets = [wallet for wallet in wallets_list if wallet['name'].lower() == "tonkeeper"]

    if not tonkeeper_wallets:
        await call.message.answer("Tonkeeper wallet not available.")
        return

    mk_b = InlineKeyboardBuilder()
    for wallet in tonkeeper_wallets:
        mk_b.button(text=wallet['name'], callback_data=f'connect:{wallet["name"]}')
    mk_b.button(text="Back to Main Menu", callback_data="main_menu")

    await call.message.answer("Choose a wallet to connect:", reply_markup=mk_b.as_markup())


@dp.callback_query(lambda call: call.data.startswith('connect:'))
async def wallet_callback_handler(call: CallbackQuery):
    """Handles the wallet selection callback."""
    await call.answer()  # Answer the callback to remove the loading animation
    data = call.data.split(':')
    wallet_name = data[1] if len(data) > 1 else None

    if wallet_name:
        await connect_wallet(call.message, wallet_name)  # Call the connect_wallet function
    else:
        await call.message.answer("Invalid wallet selection.")

@dp.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback_query: CallbackQuery):
    """Handles the 'Back to Main Menu' button press."""
    markup = create_main_menu()  # Recreate the main menu buttons
    await callback_query.message.edit_text("Back to the main menu!", reply_markup=markup)


@dp.callback_query(lambda call: call.data in ["start_journey", "wish", "get_prophecy", "invite_friend"])
async def main_menu_callback_handler(callback_query: CallbackQuery):
    if callback_query.data == "start_journey":
        await process_callback(callback_query)
    elif callback_query.data == "wish":
        await process_callback(callback_query)
    elif callback_query.data == "get_prophecy":
        await handle_get_prophecy(callback_query)
    elif callback_query.data == "invite_friend":
        await handle_invite_friend(callback_query)

@dp.callback_query(F.data == "start_journey")
async def process_callback(callback_query: CallbackQuery):
    await callback_query.message.answer(f"You've started your journey, {html.bold(callback_query.from_user.full_name)}!")

@dp.callback_query(F.data == "wish")
async def process_callback(callback_query: CallbackQuery):
    await callback_query.message.answer("Your wish will be fulfilled! You deserve it!")

@dp.callback_query(F.data == "get_prophecy")
async def handle_get_prophecy(callback_query: CallbackQuery):
    """Handles the 'Get a Prophecy' button press."""
    await callback_query.message.answer("The prophecy is on its way!")

@dp.callback_query(F.data == "invite_friend")
async def handle_invite_friend(callback_query: CallbackQuery):
    """Handles the 'Invite a Friend' button press."""
    await callback_query.message.answer("https://t.me/MyTarotProphecyBot Your friend will be a part of your fate!")

async def handle_command(message: types.Message, user_input: str):
    """Handles commands by calling OpenAI and replying with the result."""
    bot_response = await call_openai(user_input)
    await message.reply(bot_response)

@dp.message(Command("prophet"))
async def handle_prophet(message: types.Message):
    """Handles the /prophet command."""
    user_input = "Give me a short prophecy in 5 words which inspires me"
    await handle_command(message, user_input)

@dp.message(Command("moto"))
async def handle_moto(message: types.Message):
    """Handles the /moto command."""
    user_input = "Give me a moto for today. Inspire me"
    await handle_command(message, user_input)

@dp.message(Command("wish"))
async def handle_wish(message: types.Message):
    """Handles the /moto command."""
    await message.answer("Your wish will be fulfilled! You deserve it!")

async def main():
    """Starts the bot and begins polling."""
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
