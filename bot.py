import os
import logging
import asyncio
import requests
import math
from pyrogram import Client, filters, errors
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from aiohttp import web
# --- THE FIX IS HERE: We import from 'editor' to get the splitting tools ---
from moviepy.editor import VideoFileClip

# --- Configuration ---
API_ID_RAW = os.environ.get("API_ID", "12345").strip()
API_ID = int(API_ID_RAW) if API_ID_RAW.isdigit() else 12345
API_HASH = os.environ.get("API_HASH", "").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
FACEBOOK_PAGE_ACCESS_TOKEN = os.environ.get("FB_TOKEN", "").strip()
FACEBOOK_PAGE_ID = os.environ.get("FB_PAGE_ID", "").strip()

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Pyrogram Bot Client ---
app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- In-Memory State Management ---
# Stores user progress: { chat_id: { 'mode': 'bulk'|'custom'|'split', 'step': 'title'|'desc'|'video', 'data': {} } }
user_states = {}

def upload_to_facebook(video_path, description, title=None):
    """Uploads a video file to Facebook Graph API"""
    url = f"https://graph-video.facebook.com/v18.0/{FACEBOOK_PAGE_ID}/videos"
    
    logger.info(f"Attempting upload to Page ID: {FACEBOOK_PAGE_ID}")

    payload = {
        'access_token': FACEBOOK_PAGE_ACCESS_TOKEN,
        'description': description or "Uploaded via Telegram Bot"
    }
    
    if title:
        payload['title'] = title

    try:
        if not os.path.exists(video_path):
             return {'error': {'message': 'File not found locally'}}

        with open(video_path, 'rb') as file:
            files = {'source': file}
            logger.info(f"Sending video data to Facebook... ({os.path.basename(video_path)})")
            response = requests.post(url, data=payload, files=files)
            
            try:
                response_data = response.json()
                logger.info(f"Facebook API Response: {response_data}")
                return response_data
            except ValueError:
                logger.error(f"Facebook returned non-JSON response: {response.text}")
                return {'error': {'message': f"Facebook API Error: {response.status_code}"}}

    except Exception as e:
        logger.error(f"Upload function error: {e}")
        return {'error': {'message': str(e)}}

def split_and_upload_sync(video_path, chat_id, original_caption):
    """Splits video into 1-minute chunks and returns upload results"""
    results = []
    
    try:
        # Load the video using the full editor (requires moviepy.editor import)
        clip = VideoFileClip(video_path)
        duration = clip.duration
        
        # Calculate number of 1-minute parts
        chunk_duration = 60 # seconds
        total_parts = math.ceil(duration / chunk_duration)
        
        logger.info(f"Video Duration: {duration}s. Splitting into {total_parts} parts.")
        
        for i in range(total_parts):
            start_time = i * chunk_duration
            end_time = min((i + 1) * chunk_duration, duration)
            
            part_filename = f"part_{i+1}_{os.path.basename(video_path)}"
            
            # Create subclip
            new_clip = clip.subclip(start_time, end_time)
            
            # Write to file (using ultrafast preset to save CPU on Render)
            new_clip.write_videofile(
                part_filename, 
                codec="libx264", 
                audio_codec="aac", 
                preset="ultrafast",
                threads=4,
                logger=None # Silence moviepy logs
            )
            
            # Upload this part
            part_title = f"Part {i+1} of {total_parts}"
            part_desc = f"{original_caption}\n\n(Part {i+1}/{total_parts})"
            
            upload_res = upload_to_facebook(part_filename, part_desc, part_title)
            results.append(upload_res)
            
            # Cleanup part file
            if os.path.exists(part_filename):
                os.remove(part_filename)
                
        clip.close()
        return results

    except Exception as e:
        logger.error(f"Splitting Error: {e}")
        return [{'error': {'message': f"Split Failed: {str(e)}"}, 'is_fatal': True}]

# --- Handlers ---

@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    """Welcome message with Mode Selection"""
    user_name = message.from_user.first_name
    
    # Set default state
    user_states[message.chat.id] = {'mode': 'bulk', 'step': 'video', 'data': {}}

    welcome_text = (
        f"👋 **Hello {user_name}!**\n\n"
        "**Choose an upload mode:**\n"
        "🚀 **Bulk:** Uploads videos exactly as they are.\n"
        "📝 **Custom:** You set the Title & Description first.\n"
        "✂️ **Split:** Turns 1 long video into 1-minute clips."
    )
    
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Bulk Upload", callback_data="mode_bulk"),
            InlineKeyboardButton("📝 Custom Title", callback_data="mode_custom")
        ],
        [
            InlineKeyboardButton("✂️ Split (1 min clips)", callback_data="mode_split")
        ]
    ])
    
    await message.reply_text(welcome_text, reply_markup=buttons)

@app.on_callback_query()
async def handle_callbacks(client, callback_query: CallbackQuery):
    """Handle button clicks"""
    chat_id = callback_query.message.chat.id
    data = callback_query.data
    
    if data == "mode_bulk":
        user_states[chat_id] = {'mode': 'bulk', 'step': 'video', 'data': {}}
        await callback_query.message.edit_text("🚀 **Bulk Mode**\nSend videos, I'll upload them as-is.")
    
    elif data == "mode_custom":
        user_states[chat_id] = {'mode': 'custom', 'step': 'title', 'data': {}}
        await callback_query.message.edit_text("📝 **Custom Mode**\nFirst, send me the **TITLE**.")

    elif data == "mode_split":
        user_states[chat_id] = {'mode': 'split', 'step': 'video', 'data': {}}
        await callback_query.message.edit_text(
            "✂️ **Split Mode**\n"
            "Send a long video.\n"
            "I will chop it into **1-minute parts** and upload them all."
        )

@app.on_message(filters.text & filters.private)
async def handle_text(client, message: Message):
    """Handle Title and Description inputs"""
    chat_id = message.chat.id
    state = user_states.get(chat_id)

    if not state:
        await start_command(client, message)
        return

    if state['mode'] == 'custom':
        if state['step'] == 'title':
            state['data']['title'] = message.text
            state['step'] = 'desc'
            await message.reply_text(f"✅ Title: **{message.text}**\nNow send the **DESCRIPTION**.")
        
        elif state['step'] == 'desc':
            state['data']['desc'] = message.text
            state['step'] = 'video'
            await message.reply_text(f"✅ Description set.\n🎥 **Now send the VIDEO.**")
            
    else:
        pass

@app.on_message(filters.video & filters.private)
async def handle_video(client, message: Message):
    chat_id = message.chat.id
    state = user_states.get(chat_id)
    
    if not state:
        state = {'mode': 'bulk', 'step': 'video', 'data': {}}
        user_states[chat_id] = state

    # --- Mode Logic ---
    if state['mode'] == 'custom' and state['step'] != 'video':
        await message.reply_text("⚠️ Set Title/Description first! /start")
        return

    status_msg = await message.reply_text(f"📥 Downloading video...\nMode: **{state['mode'].title()}**")
    
    file_path = None
    try:
        file_path = await message.download()
        loop = asyncio.get_event_loop()

        if state['mode'] == 'split':
            # --- SPLIT MODE ---
            await status_msg.edit_text("✂️ Processing & Splitting video...\n(This might take a moment)")
            
            caption = message.caption if message.caption else "Part of a series"
            
            # Run split and upload in background
            results = await loop.run_in_executor(None, split_and_upload_sync, file_path, chat_id, caption)
            
            # Generate Report
            success_count = sum(1 for r in results if 'id' in r)
            fail_count = len(results) - success_count
            
            report = f"🏁 **Job Done**\nUploaded: {success_count}\nFailed: {fail_count}\n\n"
            for idx, res in enumerate(results):
                if 'id' in res:
                    report += f"✅ Part {idx+1}: Success\n"
                else:
                    err = res.get('error', {}).get('message', 'Error')
                    report += f"❌ Part {idx+1}: {err}\n"
            
            await status_msg.reply_text(report)
            await status_msg.delete() # Remove the "Processing" message

        else:
            # --- BULK / CUSTOM MODE ---
            await status_msg.edit_text("📤 Uploading to Facebook...")
            
            final_title = state['data'].get('title') if state['mode'] == 'custom' else None
            final_desc = state['data'].get('desc') if state['mode'] == 'custom' else (message.caption or "")
            
            fb_response = await loop.run_in_executor(
                None, upload_to_facebook, file_path, final_desc, final_title
            )

            if 'id' in fb_response:
                success_text = f"✅ **Success!**\nPost ID: `{fb_response['id']}`"
                if state['mode'] == 'custom':
                     user_states[chat_id] = {'mode': 'bulk', 'step': 'video', 'data': {}}
                     success_text += "\n\n(Mode reset to Bulk)"
                await status_msg.edit_text(success_text)
            else:
                error_msg = fb_response.get('error', {}).get('message', 'Unknown error')
                await status_msg.edit_text(f"❌ **Failed**\nFacebook Error: {error_msg}")

    except Exception as e:
        logger.error(f"General Error: {e}")
        try:
            await status_msg.edit_text(f"❌ Error occurred: {str(e)}")
        except:
            pass
    
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

# --- Dummy Web Server ---
async def health_check(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    port = int(os.environ.get("PORT", 8080))
    app_runner = web.AppRunner(web.Application())
    await app_runner.setup()
    bind_address = "0.0.0.0"
    site = web.TCPSite(app_runner, bind_address, port)
    await site.start()

if __name__ == "__main__":
    from pyrogram import idle
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_web_server())
    app.start()
    print("Bot is running...")
    idle()
    app.stop()
