import os
import logging
import secrets
import string
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# =====================================
# LOGGING
# =====================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)

# =====================================
# ENVIRONMENT
# =====================================
BOT_TOKEN = os.environ.get('BOT_TOKEN', '').strip()
ADMIN_IDS = os.environ.get('ADMIN_IDS', '').strip()
DATABASE_CHANNEL = os.environ.get('DATABASE_CHANNEL', '').strip()
PORT = int(os.environ.get('PORT', 10000))

# Logo Bot - Direct Link
BOT_LOGO = "https://i.imgur.com/N5aeIKD.png"

# Harga Langganan (dalam RM - Ringgit Malaysia)
SUBSCRIPTION_PRICES = {
    "7_hari": {"name": "7 Hari", "days": 7, "price": 5},
    "30_hari": {"name": "30 Hari", "days": 30, "price": 12},
    "60_hari": {"name": "60 Hari", "days": 60, "price": 30},
}

# Episode yang dikunci (dari episode 5 ke atas)
LOCKED_EPISODE_START = 5

# Peringatan sebelum expired (dalam hari)
WARNING_DAYS_BEFORE_EXPIRE = 3

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN tidak boleh kosong!")

# ADMIN
ADMIN_USER_IDS = set()
if ADMIN_IDS:
    for uid in ADMIN_IDS.split(','):
        try:
            ADMIN_USER_IDS.add(int(uid.strip()))
        except:
            pass

def is_admin(user_id: int) -> bool:
    if ADMIN_USER_IDS:
        return user_id in ADMIN_USER_IDS
    return False

# CHANNEL DB
DATABASE_CHANNEL_ID = None
if DATABASE_CHANNEL:
    try:
        clean = DATABASE_CHANNEL.replace(" ", '').replace('"', '').replace("'", '')
        DATABASE_CHANNEL_ID = int(clean)
    except:
        logger.warning("DATABASE_CHANNEL format salah")

# =====================================
# MEMORY DATABASE
# =====================================
drama_database = {}

# Database Langganan User: {user_id: {"expires": datetime, "type": "7_hari"}}
user_subscriptions = {}

# Database Token: {token: {"type": "7_hari", "used": False, "created_by": admin_id, "created_at": datetime}}
subscription_tokens = {}

# Track video message untuk dihapus: {user_id: {"video": message_id, "nav": message_id}}
user_video_messages = {}

# Track users yang sudah dismiss warning: {user_id: True}
dismissed_warnings = {}

# Track drama aktif untuk upload episode: {admin_id: {"drama_id": "xxx", "title": "xxx"}}
active_upload_drama = {}

# =====================================
# FLASK SERVER
# =====================================
app = Flask(__name__)

@app.route('/')
def home():
    return {
        'status': 'online',
        'dramas': len(drama_database),
        'subscribers': len([u for u, s in user_subscriptions.items() if s.get('expires', datetime.min) > datetime.now()])
    }

def run_flask():
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)


# =====================================
# SUBSCRIPTION HELPERS
# =====================================
def generate_token(length=12):
    """Generate random token"""
    chars = string.ascii_uppercase + string.digits
    return 'VVIP-' + ''.join(secrets.choice(chars) for _ in range(length))

def is_user_subscribed(user_id: int) -> bool:
    """Check if user has active subscription"""
    if user_id in user_subscriptions:
        expires = user_subscriptions[user_id].get('expires')
        if expires and expires > datetime.now():
            return True
    return False

def get_subscription_info(user_id: int) -> dict:
    """Get user subscription info"""
    if user_id in user_subscriptions:
        return user_subscriptions[user_id]
    return None

def is_expiring_soon(user_id: int) -> tuple:
    """Check if subscription is expiring within WARNING_DAYS_BEFORE_EXPIRE days"""
    if user_id in user_subscriptions:
        expires = user_subscriptions[user_id].get('expires')
        if expires and expires > datetime.now():
            remaining = expires - datetime.now()
            if remaining.days <= WARNING_DAYS_BEFORE_EXPIRE:
                return True, remaining.days, remaining.seconds // 3600
    return False, 0, 0

def is_episode_locked(ep_number) -> bool:
    """Check if episode is locked (episode 5+)"""
    try:
        ep_num = int(ep_number)
        return ep_num >= LOCKED_EPISODE_START
    except:
        return False

def activate_subscription(user_id: int, sub_type: str) -> bool:
    """Activate subscription for user"""
    if sub_type not in SUBSCRIPTION_PRICES:
        return False
    
    days = SUBSCRIPTION_PRICES[sub_type]["days"]
    
    # If user already has subscription, extend it
    if user_id in user_subscriptions and user_subscriptions[user_id].get('expires', datetime.min) > datetime.now():
        current_expires = user_subscriptions[user_id]['expires']
        new_expires = current_expires + timedelta(days=days)
    else:
        new_expires = datetime.now() + timedelta(days=days)
    
    user_subscriptions[user_id] = {
        'expires': new_expires,
        'type': sub_type,
        'activated_at': datetime.now()
    }
    
    # Reset dismissed warning when subscription is renewed
    if user_id in dismissed_warnings:
        del dismissed_warnings[user_id]
    
    return True


# =====================================
# HELPERS: SAFE EDIT / REPLY
# =====================================
async def safe_edit_or_reply(query, text, reply_markup=None, parse_mode=None):
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    except BadRequest as e:
        logger.debug(f"edit_message_text failed: {e}; will fallback to reply_text")
    except Exception as e:
        logger.debug(f"edit_message_text exception: {e}; fallback to reply_text")

    try:
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Failed to reply with fallback message: {e}")

    try:
        await query.message.delete()
    except Exception:
        pass


# =====================================
# START MENU
# =====================================
def build_start_keyboard(is_admin_user: bool, user_id: int):
    is_subscribed = is_user_subscribed(user_id)
    
    keyboard = [
        [InlineKeyboardButton("🔍 Cari Drama", callback_data='search')],
        [InlineKeyboardButton("📺 Daftar Drama", callback_data='list')],
    ]
    
    if is_subscribed:
        keyboard.append([InlineKeyboardButton("👑 Cek Langganan VVIP", callback_data='check_sub')])
    else:
        keyboard.append([InlineKeyboardButton("👑 Berlangganan VVIP", callback_data='subscribe')])
    
    keyboard.append([InlineKeyboardButton("🎟️ Redeem Token", callback_data='redeem')])
    keyboard.append([InlineKeyboardButton("📞 Hubungi Admin", url="https://t.me/admin")])
    
    if is_admin_user:
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data='admin_panel')])
    
    return InlineKeyboardMarkup(keyboard)

def build_expiry_warning_keyboard():
    """Build keyboard for expiry warning"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Perpanjang Sekarang", callback_data='subscribe')],
        [InlineKeyboardButton("❌ Nanti Saja", callback_data='dismiss_warning')]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    is_subscribed = is_user_subscribed(user_id)
    kb = build_start_keyboard(is_admin(user_id), user_id)
    
    vip_status = "👑 VVIP Member" if is_subscribed else "👤 Free Member"
    
    welcome_text = (
        "🎬 *DRAMACHIN by D3D1*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Selamat datang di nonton streaming drama China dan drama lainnya terlengkap!\n\n"
        f"📊 *Total Drama:* {len(drama_database)}\n"
        f"🎥 *Total Episode:* {sum(len(d.get('episodes', {})) for d in drama_database.values())}\n\n"
        f"🔐 *Status:* {vip_status}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ *Info:* Episode 5 ke atas membutuhkan langganan VVIP\n\n"
        "Pilih menu di bawah untuk mulai:"
    )
    
    # Check if user has expiring subscription and hasn't dismissed warning
    expiring, days_left, hours_left = is_expiring_soon(user_id)
    
    # Send logo with welcome text as caption (combined in one message)
    if BOT_LOGO:
        try:
            await update.message.reply_photo(
                photo=BOT_LOGO,
                caption=welcome_text,
                reply_markup=kb,
                parse_mode='Markdown'
            )
            logger.info("Logo with welcome message sent successfully")
        except Exception as e:
            logger.error(f"Failed to send logo: {e}")
            # Fallback to text only if logo fails
            await update.message.reply_text(
                welcome_text,
                reply_markup=kb,
                parse_mode='Markdown'
            )
    else:
        # No logo, send text only
        await update.message.reply_text(
            welcome_text,
            reply_markup=kb,
            parse_mode='Markdown'
        )
    
    # Send expiry warning if applicable and not dismissed
    if expiring and user_id not in dismissed_warnings:
        if days_left > 0:
            time_text = f"{days_left} hari {hours_left} jam"
        else:
            time_text = f"{hours_left} jam"
        
        warning_text = (
            "⚠️ *PERINGATAN LANGGANAN*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"Langganan VVIP kamu akan berakhir dalam *{time_text}* lagi!\n\n"
            "Perpanjang sekarang untuk tetap menikmati akses penuh ke semua episode.\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        
        await update.message.reply_text(
            warning_text,
            reply_markup=build_expiry_warning_keyboard(),
            parse_mode='Markdown'
        )


# =====================================
# INDEX FORWARD SYSTEM
# =====================================
async def index_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = msg.from_user.id

    if not is_admin(user_id):
        await msg.reply_text("❌ Hanya admin yang boleh index.")
        return

    origin = msg.forward_origin

    if not origin:
        await msg.reply_text("❌ Ini bukan pesan forward channel.")
        return

    origin_chat = getattr(origin, 'chat', None)
    
    if DATABASE_CHANNEL_ID and origin_chat and origin_chat.id != DATABASE_CHANNEL_ID:
        await msg.reply_text("❌ Pesan bukan dari database channel.")
        return

    result = await parse_and_index_message(msg, context, user_id)

    if result == "NO_ACTIVE_DRAMA":
        await msg.reply_text(
            "❌ *Tidak Ada Drama Aktif*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Untuk upload episode, kirim thumbnail dulu dengan format:\n\n"
            "📸 `#ID JudulDrama`\n\n"
            "Contoh:\n"
            "`#LBFD Love Between Fairy and Devil`\n\n"
            "Setelah itu baru kirim video episode (tanpa caption).",
            parse_mode='Markdown'
        )
    elif result:
        await msg.reply_text(result, parse_mode='Markdown')
    else:
        await msg.reply_text(
            "❌ *Format Salah*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*Cara Upload:*\n\n"
            "1️⃣ Kirim *Thumbnail* dengan caption:\n"
            "   `#ID JudulDrama`\n\n"
            "2️⃣ Kirim *Video Episode* tanpa caption\n"
            "   (Episode akan otomatis dinomori)\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*Contoh:*\n"
            "• Thumbnail: `#LBFD Love Between Fairy and Devil`\n"
            "• Video: _(langsung kirim tanpa caption)_",
            parse_mode='Markdown'
        )


async def parse_and_index_message(message, context, user_id):
    global drama_database, active_upload_drama

    try:
        caption = message.caption or ""

        # VIDEO (EPISODE) - Tanpa caption, ambil dari drama aktif
        if message.video:
            # Cek apakah ada drama aktif untuk admin ini
            if user_id not in active_upload_drama:
                return "NO_ACTIVE_DRAMA"
            
            active = active_upload_drama[user_id]
            drama_id = active["drama_id"]
            title = active["title"]
            
            # Hitung episode berikutnya
            if drama_id in drama_database:
                existing_eps = drama_database[drama_id].get("episodes", {})
                # Cari episode tertinggi
                max_ep = 0
                for ep_key in existing_eps.keys():
                    try:
                        ep_num = int(ep_key)
                        if ep_num > max_ep:
                            max_ep = ep_num
                    except:
                        pass
                next_ep = str(max_ep + 1)
            else:
                drama_database[drama_id] = {"title": title, "episodes": {}}
                next_ep = "1"
            
            ep = next_ep
            
            is_update = ep in drama_database[drama_id].get("episodes", {})
            
            drama_database[drama_id]["episodes"][ep] = {
                "file_id": message.video.file_id
            }

            video = message.video
            duration = f"{video.duration // 60}:{video.duration % 60:02d}" if video.duration else "N/A"
            file_size = f"{video.file_size / (1024*1024):.2f} MB" if video.file_size else "N/A"
            
            total_eps = len(drama_database[drama_id]["episodes"])
            is_locked = is_episode_locked(ep)
            
            logger.info(f"Indexed: {drama_id} - {title} EP {ep}")
            
            response = (
                f"✅ *Berhasil Diindex!*\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📹 *Tipe:* Episode Video\n"
                f"🎬 *Drama:* {title}\n"
                f"🆔 *ID:* #{drama_id}\n"
                f"📺 *Episode:* {ep}\n"
                f"⏱ *Durasi:* {duration}\n"
                f"💾 *Ukuran:* {file_size}\n"
                f"🔐 *Status:* {'🔒 Terkunci (VVIP)' if is_locked else '🔓 Gratis'}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 Total episode sekarang: *{total_eps} EP*\n\n"
                f"_Kirim video lagi untuk Episode {int(ep)+1}_"
            )
            
            return response

        # PHOTO (THUMBNAIL) - Dengan caption format: #ID JudulDrama
        if message.photo:
            if not caption.startswith("#"):
                return False

            parts = caption.split(" ", 1)
            drama_id = parts[0][1:]
            title = parts[1].strip() if len(parts) > 1 else "Unknown"

            is_new_drama = drama_id not in drama_database
            has_old_thumbnail = not is_new_drama and "thumbnail" in drama_database[drama_id]
            
            if is_new_drama:
                drama_database[drama_id] = {"title": title, "episodes": {}}

            drama_database[drama_id]["thumbnail"] = message.photo[-1].file_id
            drama_database[drama_id]["title"] = title
            
            # Set drama aktif untuk upload episode selanjutnya
            active_upload_drama[user_id] = {
                "drama_id": drama_id,
                "title": title
            }

            photo = message.photo[-1]
            resolution = f"{photo.width}x{photo.height}"
            file_size = f"{photo.file_size / 1024:.2f} KB" if photo.file_size else "N/A"
            
            total_eps = len(drama_database[drama_id].get("episodes", {}))
            
            logger.info(f"Indexed thumbnail: {drama_id} - {title}")
            
            response = (
                f"✅ *Berhasil Diindex!*\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🖼 *Tipe:* Thumbnail Drama\n"
                f"🎬 *Drama:* {title}\n"
                f"🆔 *ID:* #{drama_id}\n"
                f"📐 *Resolusi:* {resolution}\n"
                f"💾 *Ukuran:* {file_size}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
            )
            
            if is_new_drama:
                response += f"🆕 Drama baru dibuat!\n"
            elif has_old_thumbnail:
                response += f"🔄 Thumbnail diperbarui!\n"
            else:
                response += f"➕ Thumbnail ditambahkan!\n"
                
            response += f"📊 Total episode: *{total_eps} EP*\n\n"
            response += f"🎬 *Drama Aktif:* {title}\n"
            response += f"_Sekarang kirim video episode (tanpa caption)_"
            
            return response

        return False

    except Exception as e:
        logger.error(f"parse_and_index_message error: {e}")
        return False


# =====================================
# PAGINATION HELPER
# =====================================
def paginate_items(items, page, items_per_page=10):
    start = page * items_per_page
    end = start + items_per_page
    return items[start:end], len(items)


# =====================================
# CALLBACK BUTTONS
# =====================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    # ============================
    # NOOP (do nothing)
    # ============================
    if query.data == "noop":
        return

    # ============================
    # DISMISS WARNING
    # ============================
    if query.data == "dismiss_warning":
        dismissed_warnings[user_id] = True
        try:
            await query.message.delete()
        except:
            pass
        return

    # ============================
    # MENU UTAMA (BACK)
    # ============================
    if query.data == "back":
        kb = build_start_keyboard(is_admin(user_id), user_id)
        is_subscribed = is_user_subscribed(user_id)
        vip_status = "👑 VVIP Member" if is_subscribed else "👤 Free Member"
        
        welcome_text = (
            "🎬 *DRAMACHIN by D3D1*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 Total Drama: {len(drama_database)}\n"
            f"🎥 Total Episode: {sum(len(d.get('episodes', {})) for d in drama_database.values())}\n"
            f"🔐 Status: {vip_status}\n\n"
            "Pilih menu:"
        )
        
        # Delete current message first
        try:
            await query.message.delete()
        except:
            pass
        
        # Send logo with welcome text as caption (combined)
        if BOT_LOGO:
            try:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=BOT_LOGO,
                    caption=welcome_text,
                    reply_markup=kb,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.warning(f"Failed to send logo on back: {e}")
                # Fallback to text only
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=welcome_text,
                    reply_markup=kb,
                    parse_mode='Markdown'
                )
        else:
            # No logo, send text only
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=welcome_text,
                reply_markup=kb,
                parse_mode='Markdown'
            )
        return

    # ============================
    # SUBSCRIBE INFO
    # ============================
    if query.data == "subscribe":
        price_list = ""
        for key, info in SUBSCRIPTION_PRICES.items():
            price_list += f"• *{info['name']}*: RM{info['price']}\n"
        
        subscribe_text = (
            "👑 *BERLANGGANAN VVIP*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Dengan berlangganan VVIP, kamu bisa:\n"
            "✅ Akses semua film drama yang ada\n"
            "✅ Akses semua episode drama\n"
            "✅ Tonton episode 5 sampai selesai\n"
            "✅ Tanpa batasan\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💰 *DAFTAR HARGA:*\n\n"
            f"{price_list}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📝 *CARA BERLANGGANAN:*\n\n"
            "1️⃣ Hubungi admin untuk berlangganan\n"
            "2️⃣ Pilih paket langganan\n"
            "3️⃣ Transfer sesuai harga paket\n"
            "4️⃣ Kirim bukti transfer ke admin\n"
            "5️⃣ Admin akan kirim token\n"
            "6️⃣ Redeem token di menu utama\n\n"
            "⚠️ *Token hanya bisa digunakan 1x!*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📞 *Hubungi admin untuk info pembayaran dan berlangganan*"
        )
        
        keyboard = [
            [InlineKeyboardButton("📞 Hubungi Admin", url="https://t.me/admin")],
            [InlineKeyboardButton("« Kembali", callback_data="back")]
        ]
        
        await safe_edit_or_reply(query, subscribe_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # ============================
    # CHECK SUBSCRIPTION
    # ============================
    if query.data == "check_sub":
        sub_info = get_subscription_info(user_id)
        
        if sub_info and sub_info.get('expires', datetime.min) > datetime.now():
            expires = sub_info['expires']
            remaining = expires - datetime.now()
            days_left = remaining.days
            hours_left = remaining.seconds // 3600
            
            sub_type = SUBSCRIPTION_PRICES.get(sub_info.get('type', ''), {}).get('name', 'Unknown')
            
            # Check if expiring soon
            is_expiring = days_left <= WARNING_DAYS_BEFORE_EXPIRE
            
            check_text = (
                "👑 *STATUS LANGGANAN VVIP*\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "✅ *Status:* AKTIF\n\n"
                f"📦 *Paket:* {sub_type}\n"
                f"📅 *Berakhir:* {expires.strftime('%d %B %Y, %H:%M')}\n"
                f"⏳ *Sisa Waktu:* {days_left} hari {hours_left} jam\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
            )
            
            if is_expiring:
                check_text += "⚠️ *Langganan kamu akan segera berakhir!*\nPerpanjang sekarang untuk akses tanpa gangguan."
            else:
                check_text += "Nikmati akses penuh ke semua episode! 🎬"
            
            keyboard = []
            if is_expiring:
                keyboard.append([InlineKeyboardButton("✅ Perpanjang Sekarang", callback_data="subscribe")])
            keyboard.append([InlineKeyboardButton("« Kembali", callback_data="back")])
            
        else:
            check_text = (
                "👑 *STATUS LANGGANAN VVIP*\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "❌ *Status:* TIDAK AKTIF\n\n"
                "Kamu belum memiliki langganan aktif.\n"
                "Berlangganan sekarang untuk akses penuh!"
            )
            
            keyboard = [
                [InlineKeyboardButton("👑 Berlangganan", callback_data="subscribe")],
                [InlineKeyboardButton("« Kembali", callback_data="back")]
            ]
        
        await safe_edit_or_reply(query, check_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # ============================
    # REDEEM TOKEN
    # ============================
    if query.data == "redeem":
        redeem_text = (
            "🎟️ *REDEEM TOKEN VVIP*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Masukkan token langganan yang kamu terima dari admin.\n\n"
            "Format token: `VVIP-XXXXXXXXXXXX`\n\n"
            "Ketik token kamu sekarang:"
        )
        
        keyboard = [[InlineKeyboardButton("« Kembali", callback_data="back")]]
        await safe_edit_or_reply(query, redeem_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        context.user_data["waiting"] = "redeem_token"
        return

    # ============================
    # SEARCH
    # ============================
    if query.data == "search":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="back")]])
        search_text = (
            "🔍 *Pencarian Drama*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Ketik nama drama yang ingin kamu cari:\n\n"
            "Contoh: _Love Between Fairy_"
        )
        await safe_edit_or_reply(query, search_text, reply_markup=kb, parse_mode='Markdown')
        context.user_data["waiting"] = "search"
        return

    # ============================
    # ADMIN PANEL
    # ============================
    if query.data == "admin_panel":
        if not is_admin(user_id):
            await safe_edit_or_reply(query, "❌ Hanya admin yang bisa mengakses panel ini.")
            return
        
        active_subs = len([u for u, s in user_subscriptions.items() if s.get('expires', datetime.min) > datetime.now()])
        unused_tokens = len([t for t, info in subscription_tokens.items() if not info.get('used', False)])
        
        admin_text = (
            "⚙️ *Admin Panel*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Total Drama: {len(drama_database)}\n"
            f"🎥 Total Episode: {sum(len(d.get('episodes', {})) for d in drama_database.values())}\n"
            f"👑 Subscriber Aktif: {active_subs}\n"
            f"🎟️ Token Tersedia: {unused_tokens}\n\n"
            "Pilih aksi:"
        )
        keyboard = [
            [InlineKeyboardButton("➕ Upload Drama", callback_data='upload')],
            [InlineKeyboardButton("🎟️ Generate Token", callback_data='gen_token')],
            [InlineKeyboardButton("📋 Lihat Token", callback_data='list_tokens')],
            [InlineKeyboardButton("👥 Lihat Subscriber", callback_data='list_subs')],
            [InlineKeyboardButton("📊 Statistik", callback_data='stats')],
            [InlineKeyboardButton("« Kembali", callback_data="back")]
        ]
        await safe_edit_or_reply(query, admin_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # ============================
    # GENERATE TOKEN (ADMIN)
    # ============================
    if query.data == "gen_token":
        if not is_admin(user_id):
            await safe_edit_or_reply(query, "❌ Hanya admin")
            return
        
        gen_text = (
            "🎟️ *Generate Token Langganan*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Pilih durasi langganan untuk token:"
        )
        
        keyboard = []
        for key, info in SUBSCRIPTION_PRICES.items():
            keyboard.append([InlineKeyboardButton(
                f"📦 {info['name']} - RM{info['price']}", 
                callback_data=f"create_token_{key}"
            )])
        keyboard.append([InlineKeyboardButton("« Admin Panel", callback_data="admin_panel")])
        
        await safe_edit_or_reply(query, gen_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # ============================
    # RESET ACTIVE DRAMA (ADMIN)
    # ============================
    if query.data == "reset_active_drama":
        if not is_admin(user_id):
            await safe_edit_or_reply(query, "❌ Hanya admin")
            return
        
        if user_id in active_upload_drama:
            del active_upload_drama[user_id]
            await safe_edit_or_reply(
                query,
                "✅ *Drama Aktif Direset*\n\n"
                "Kirim thumbnail baru untuk memulai upload drama.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Upload Drama", callback_data="upload")]]),
                parse_mode='Markdown'
            )
        else:
            await safe_edit_or_reply(
                query,
                "ℹ️ Tidak ada drama aktif.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Upload Drama", callback_data="upload")]]),
                parse_mode='Markdown'
            )
        return

    # ============================
    # CREATE TOKEN (ADMIN)
    # ============================
    if query.data.startswith("create_token_"):
        if not is_admin(user_id):
            await safe_edit_or_reply(query, "❌ Hanya admin")
            return
        
        sub_type = query.data.replace("create_token_", "")
        
        if sub_type not in SUBSCRIPTION_PRICES:
            await safe_edit_or_reply(query, "❌ Tipe langganan tidak valid")
            return
        
        # Generate token
        token = generate_token()
        subscription_tokens[token] = {
            "type": sub_type,
            "used": False,
            "created_by": user_id,
            "created_at": datetime.now()
        }
        
        sub_info = SUBSCRIPTION_PRICES[sub_type]
        
        token_text = (
            "✅ *Token Berhasil Dibuat!*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🎟️ *Token:* `{token}`\n"
            f"📦 *Paket:* {sub_info['name']}\n"
            f"💰 *Harga:* RM{sub_info['price']}\n"
            f"📅 *Durasi:* {sub_info['days']} hari\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Kirim token ini ke user yang sudah bayar."
        )
        
        keyboard = [
            [InlineKeyboardButton("🎟️ Buat Token Lagi", callback_data="gen_token")],
            [InlineKeyboardButton("« Admin Panel", callback_data="admin_panel")]
        ]
        
        await safe_edit_or_reply(query, token_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # ============================
    # LIST TOKENS (ADMIN)
    # ============================
    if query.data == "list_tokens":
        if not is_admin(user_id):
            await safe_edit_or_reply(query, "❌ Hanya admin")
            return
        
        unused_tokens = [(t, info) for t, info in subscription_tokens.items() if not info.get('used', False)]
        
        if not unused_tokens:
            tokens_text = (
                "🎟️ *Daftar Token*\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Tidak ada token yang tersedia.\n"
                "Buat token baru di menu Generate Token."
            )
        else:
            tokens_text = (
                f"🎟️ *Daftar Token Tersedia* ({len(unused_tokens)})\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
            )
            for token, info in unused_tokens[:10]:  # Max 10
                sub_name = SUBSCRIPTION_PRICES.get(info['type'], {}).get('name', 'Unknown')
                created = info.get('created_at', datetime.now()).strftime('%d/%m/%Y')
                tokens_text += f"• `{token}`\n  📦 {sub_name} | 📅 {created}\n\n"
            
            if len(unused_tokens) > 10:
                tokens_text += f"_...dan {len(unused_tokens) - 10} token lainnya_"
        
        keyboard = [
            [InlineKeyboardButton("🎟️ Generate Token", callback_data="gen_token")],
            [InlineKeyboardButton("« Admin Panel", callback_data="admin_panel")]
        ]
        
        await safe_edit_or_reply(query, tokens_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # ============================
    # LIST SUBSCRIBERS (ADMIN)
    # ============================
    if query.data == "list_subs":
        if not is_admin(user_id):
            await safe_edit_or_reply(query, "❌ Hanya admin")
            return
        
        active_subs = [(uid, info) for uid, info in user_subscriptions.items() 
                       if info.get('expires', datetime.min) > datetime.now()]
        
        # Get used tokens with user info
        used_tokens_list = [(t, info) for t, info in subscription_tokens.items() if info.get('used', False)]
        
        if not active_subs:
            subs_text = (
                "👥 *Daftar Subscriber Aktif*\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Belum ada subscriber aktif.\n"
            )
        else:
            subs_text = (
                f"👥 *Daftar Subscriber Aktif* ({len(active_subs)})\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
            )
            for uid, info in active_subs[:10]:  # Max 10
                expires = info['expires']
                remaining = (expires - datetime.now()).days
                sub_type = SUBSCRIPTION_PRICES.get(info.get('type', ''), {}).get('name', 'Unknown')
                exp_date = expires.strftime('%d/%m/%Y')
                subs_text += f"• User `{uid}`\n  📦 {sub_type} | ⏳ {remaining} hari lagi\n  📅 Berakhir: {exp_date}\n\n"
            
            if len(active_subs) > 10:
                subs_text += f"_...dan {len(active_subs) - 10} subscriber lainnya_\n"
        
        # Add used tokens info with user
        subs_text += "\n━━━━━━━━━━━━━━━━━━━━\n"
        subs_text += "🎟️ *Riwayat Penggunaan Token:*\n\n"
        
        if not used_tokens_list:
            subs_text += "Belum ada token yang digunakan.\n"
        else:
            for token, info in used_tokens_list[:10]:  # Max 10
                used_by = info.get('used_by', 'Unknown')
                used_at = info.get('used_at', datetime.now()).strftime('%d/%m/%Y %H:%M')
                sub_name = SUBSCRIPTION_PRICES.get(info.get('type', ''), {}).get('name', 'Unknown')
                subs_text += f"• `{token}`\n  👤 User: `{used_by}`\n  📦 {sub_name} | 📅 {used_at}\n\n"
            
            if len(used_tokens_list) > 10:
                subs_text += f"_...dan {len(used_tokens_list) - 10} token lainnya_\n"
        
        keyboard = [[InlineKeyboardButton("« Admin Panel", callback_data="admin_panel")]]
        await safe_edit_or_reply(query, subs_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # ============================
    # LIST DRAMA
    # ============================
    if query.data.startswith("list"):
        page = 0
        if "_" in query.data:
            page = int(query.data.split("_")[1])
        
        if not drama_database:
            await safe_edit_or_reply(
                query, 
                "📭 *Belum Ada Drama*\n\n━━━━━━━━━━━━━━━━━━━━\nDatabase masih kosong.", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data="back")]]),
                parse_mode='Markdown'
            )
            return

        sorted_dramas = sorted(drama_database.items(), key=lambda x: x[1].get("title", ""))
        page_items, total = paginate_items(sorted_dramas, page, items_per_page=8)
        
        keyboard = []
        for did, info in page_items:
            title = info.get("title", did)
            ep_count = len(info.get("episodes", {}))
            keyboard.append([InlineKeyboardButton(
                f"🎬 {title} ({ep_count} EP)", 
                callback_data=f"d_{did}"
            )])

        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"list_{page-1}"))
        if (page + 1) * 8 < total:
            nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"list_{page+1}"))
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        keyboard.append([InlineKeyboardButton("« Kembali", callback_data="back")])
        kb = InlineKeyboardMarkup(keyboard)

        list_text = (
            f"📺 *Daftar Drama* (Halaman {page + 1})\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Menampilkan {len(page_items)} dari {total} drama\n\n"
            f"🔓 Episode 1-4: Gratis\n"
            f"🔒 Episode 5+: Khusus VVIP\n\n"
            f"Pilih drama untuk lihat episode:"
        )

        await safe_edit_or_reply(query, list_text, reply_markup=kb, parse_mode='Markdown')
        return

    # ============================
    # UPLOAD & STATS (ADMIN)
    # ============================
    if query.data == "upload":
        if not is_admin(user_id):
            await safe_edit_or_reply(query, "❌ Hanya admin")
            return
        
        # Cek drama aktif
        active_info = ""
        if user_id in active_upload_drama:
            active = active_upload_drama[user_id]
            drama_id = active["drama_id"]
            title = active["title"]
            total_eps = len(drama_database.get(drama_id, {}).get("episodes", {}))
            active_info = (
                f"🎬 *Drama Aktif:* {title}\n"
                f"📊 *Episode Tersimpan:* {total_eps}\n"
                f"📺 *Episode Berikutnya:* {total_eps + 1}\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
            )

        text = (
            "📤 *Panduan Upload Drama*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{active_info}"
            "*LANGKAH 1 - Kirim Thumbnail:*\n"
            "Forward foto thumbnail dari channel dengan caption:\n"
            "`#ID JudulDrama`\n\n"
            "*LANGKAH 2 - Kirim Video Episode:*\n"
            "Forward video dari channel *tanpa caption*\n"
            "Episode akan otomatis dinomori (1, 2, 3, ...)\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*Contoh:*\n"
            "• Thumbnail: `#LBFD Love Between Fairy and Devil`\n"
            "• Video: _(langsung forward tanpa caption)_\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💡 *Tips:* Untuk ganti drama, kirim thumbnail baru"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Reset Drama Aktif", callback_data="reset_active_drama")],
            [InlineKeyboardButton("« Admin Panel", callback_data="admin_panel")]
        ])
        await safe_edit_or_reply(query, text, parse_mode="Markdown", reply_markup=kb)
        return

    if query.data == "stats":
        if not is_admin(user_id):
            await safe_edit_or_reply(query, "❌ Hanya admin")
            return

        total_eps = sum(len(d.get('episodes', {})) for d in drama_database.values())
        dramas_with_thumb = sum(1 for d in drama_database.values() if 'thumbnail' in d)
        active_subs = len([u for u, s in user_subscriptions.items() if s.get('expires', datetime.min) > datetime.now()])
        total_tokens_used = len([t for t, info in subscription_tokens.items() if info.get('used', False)])
        
        stats_text = (
            "📋 *Statistik Database*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📺 Total Drama: {len(drama_database)}\n"
            f"🎥 Total Episode: {total_eps}\n"
            f"🖼 Drama dengan Thumbnail: {dramas_with_thumb}\n"
            f"📊 Rata-rata EP/Drama: {total_eps // len(drama_database) if drama_database else 0}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*Statistik Langganan:*\n"
            f"👑 Subscriber Aktif: {active_subs}\n"
            f"🎟️ Token Sudah Digunakan: {total_tokens_used}\n"
            f"🎟️ Token Tersedia: {len(subscription_tokens) - total_tokens_used}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*Top 5 Drama (Episode Terbanyak):*\n"
        )
        
        top_dramas = sorted(
            drama_database.items(), 
            key=lambda x: len(x[1].get('episodes', {})), 
            reverse=True
        )[:5]
        
        for i, (did, info) in enumerate(top_dramas, 1):
            stats_text += f"{i}. {info.get('title', did)} - {len(info.get('episodes', {}))} EP\n"
        
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Admin Panel", callback_data="admin_panel")]])
        await safe_edit_or_reply(query, stats_text, parse_mode='Markdown', reply_markup=kb)
        return

    # ============================
    # PILIH DRAMA
    # ============================
    if query.data.startswith("d_"):
        did = query.data[2:]
        await show_episodes(query, did, user_id)
        return

    # ============================
    # EPISODE
    # ============================
    if query.data.startswith("ep_"):
        parts = query.data.split("_")
        if len(parts) == 3:
            _, did, ep = parts
            await send_episode(query, did, ep, context, user_id)
        elif len(parts) == 4 and parts[1] == "page":
            _, _, did, page = parts
            await show_episodes(query, did, user_id, int(page))
        return


# =====================================
# SHOW EPISODES
# =====================================
async def show_episodes(query, did, user_id, page=0):
    if did not in drama_database:
        await safe_edit_or_reply(
            query, 
            "❌ Drama tidak ditemukan.", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Senarai Drama", callback_data="list")]])
        )
        return

    info = drama_database[did]
    eps = info.get("episodes", {})
    is_subscribed = is_user_subscribed(user_id)
    
    sorted_eps = sorted(eps.keys(), key=lambda x: int(x) if x.isdigit() else x)
    page_eps, total = paginate_items(sorted_eps, page, items_per_page=20)

    keyboard = []
    row = []
    
    for ep in page_eps:
        ep_num = int(ep) if ep.isdigit() else 0
        is_locked = ep_num >= LOCKED_EPISODE_START and not is_subscribed
        
        if is_locked:
            btn_text = f"🔒 {ep}"
        else:
            btn_text = f"EP {ep}"
        
        row.append(InlineKeyboardButton(btn_text, callback_data=f"ep_{did}_{ep}"))
        if len(row) == 5:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"ep_page_{did}_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"📄 {page+1}/{(total-1)//20 + 1}", callback_data="noop"))
    if (page + 1) * 20 < total:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"ep_page_{did}_{page+1}"))
    
    keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("« Daftar Drama", callback_data="list")])
    kb = InlineKeyboardMarkup(keyboard)

    vip_status = "👑 VVIP" if is_subscribed else "🔒 Free"
    free_eps = min(LOCKED_EPISODE_START - 1, len(eps))
    locked_eps = max(0, len(eps) - free_eps)

    text = (
        f"🎬 *{info.get('title', did)}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📺 Total Episode: {len(eps)}\n"
        f"🔓 Gratis: EP 1-{LOCKED_EPISODE_START-1}\n"
        f"🔒 VVIP: EP {LOCKED_EPISODE_START}+\n"
        f"👤 Status Kamu: {vip_status}\n"
        f"📄 Halaman: {page + 1}/{(total-1)//20 + 1}\n\n"
        f"Pilih episode untuk ditonton:"
    )
    
    thumb = info.get("thumbnail")

    if thumb:
        try:
            await query.message.reply_photo(
                photo=thumb, 
                caption=text, 
                reply_markup=kb, 
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"reply_photo failed: {e}")
            await safe_edit_or_reply(query, text, reply_markup=kb, parse_mode="Markdown")
        try:
            await query.message.delete()
        except Exception:
            pass
    else:
        await safe_edit_or_reply(query, text, reply_markup=kb, parse_mode="Markdown")


# =====================================
# SEND EPISODE
# =====================================
async def send_episode(query, did, ep, context, user_id):
    info = drama_database.get(did)
    if not info or "episodes" not in info or ep not in info["episodes"]:
        await safe_edit_or_reply(
            query, 
            "❌ Episode tidak ditemukan.", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Kembali", callback_data=f"d_{did}")]])
        )
        return

    # Check if episode is locked
    ep_num = int(ep) if ep.isdigit() else 0
    is_locked = ep_num >= LOCKED_EPISODE_START
    is_subscribed = is_user_subscribed(user_id)
    
    # If locked and not subscribed, show subscription prompt
    if is_locked and not is_subscribed:
        lock_text = (
            "🔒 *EPISODE TERKUNCI*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🎬 *{info.get('title', did)}*\n"
            f"📺 Episode {ep}\n\n"
            f"Episode ini memerlukan langganan VVIP.\n"
            f"Berlangganan sekarang untuk akses penuh!\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💡 *Keuntungan VVIP:*\n"
            "✅ Akses semua episode\n"
            "✅ Tanpa batasan\n"
            "✅ Tonton kapan saja"
        )
        
        keyboard = [
            [InlineKeyboardButton("👑 Berlangganan VVIP", callback_data="subscribe")],
            [InlineKeyboardButton("🎟️ Redeem Token", callback_data="redeem")],
            [InlineKeyboardButton("« Kembali", callback_data=f"d_{did}")]
        ]
        
        await safe_edit_or_reply(query, lock_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    episode = info["episodes"][ep]

    # DELETE PREVIOUS VIDEO AND NAVIGATION if exists
    if user_id in user_video_messages:
        prev_msgs = user_video_messages[user_id]
        
        # Delete previous video
        if prev_msgs.get("video"):
            try:
                await context.bot.delete_message(chat_id=query.message.chat_id, message_id=prev_msgs["video"])
                logger.info(f"Deleted previous video for user {user_id}")
            except Exception as e:
                logger.debug(f"Could not delete previous video: {e}")
        
        # Delete previous navigation
        if prev_msgs.get("nav"):
            try:
                await context.bot.delete_message(chat_id=query.message.chat_id, message_id=prev_msgs["nav"])
                logger.info(f"Deleted previous navigation for user {user_id}")
            except Exception as e:
                logger.debug(f"Could not delete previous navigation: {e}")

    caption = (
        f"🎬 *{info.get('title',did)}*\n"
        f"📺 Episode {ep}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Selamat menonton! 🍿\n\n"
        f"⚠️ Video ini dilindungi dan tidak bisa didownload atau dibagikan."
    )

    try:
        # Send video with protect_content=True to prevent download/forward
        sent_video = await query.message.reply_video(
            episode["file_id"], 
            caption=caption, 
            parse_mode="Markdown",
            protect_content=True  # Mencegah download/forward
        )
        
    except Exception as e:
        logger.error(f"reply_video failed: {e}")
        await safe_edit_or_reply(query, "❌ Gagal mengirim video.")
        return

    # Navigation buttons
    next_ep = str(int(ep) + 1) if ep.isdigit() else None
    prev_ep = str(int(ep) - 1) if ep.isdigit() and int(ep) > 1 else None
    keyboard = []
    
    nav_row = []
    if prev_ep and prev_ep in info["episodes"]:
        nav_row.append(InlineKeyboardButton(f"◀️ EP {prev_ep}", callback_data=f"ep_{did}_{prev_ep}"))
    
    if next_ep and next_ep in info["episodes"]:
        next_locked = int(next_ep) >= LOCKED_EPISODE_START and not is_subscribed
        if next_locked:
            nav_row.append(InlineKeyboardButton(f"🔒 EP {next_ep}", callback_data=f"ep_{did}_{next_ep}"))
        else:
            nav_row.append(InlineKeyboardButton(f"EP {next_ep} ▶️", callback_data=f"ep_{did}_{next_ep}"))
    
    if nav_row:
        keyboard.append(nav_row)
    
    keyboard.append([InlineKeyboardButton("📺 Daftar Episode", callback_data=f"d_{did}")])
    keyboard.append([InlineKeyboardButton("🏠 Menu Utama", callback_data="back")])
    kb = InlineKeyboardMarkup(keyboard)

    sent_nav = None
    try:
        sent_nav = await query.message.reply_text(
            "━━━━━━━━━━━━━━━━━━━━\n*Navigasi:*\n\n⚠️ _Video sebelumnya akan dihapus saat menonton episode lain_", 
            reply_markup=kb, 
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"reply_text navigation failed: {e}")
    
    # Store both video and navigation message IDs for later deletion
    user_video_messages[user_id] = {
        "video": sent_video.message_id,
        "nav": sent_nav.message_id if sent_nav else None
    }


# =====================================
# USER MESSAGE HANDLER
# =====================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    
    if not msg:
        return

    user_id = msg.from_user.id

    # FORWARD → INDEX
    if msg.forward_origin:
        await index_message(update, context)
        return

    # REDEEM TOKEN MODE
    if context.user_data.get("waiting") == "redeem_token":
        token = (msg.text or "").strip().upper()
        
        if not token:
            await msg.reply_text("❌ Masukkan token yang sah.")
            return
        
        if token not in subscription_tokens:
            await msg.reply_text(
                "❌ *Token Tidak Valid*\n\n"
                "Token yang kamu masukkan tidak ditemukan.\n"
                "Pastikan token benar atau hubungi admin.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👑 Berlangganan", callback_data="subscribe")],
                    [InlineKeyboardButton("« Menu Utama", callback_data="back")]
                ])
            )
            context.user_data["waiting"] = None
            return
        
        token_info = subscription_tokens[token]
        
        if token_info.get('used', False):
            await msg.reply_text(
                "❌ *Token Sudah Digunakan*\n\n"
                "Token ini sudah pernah digunakan.\n"
                "Hubungi admin untuk token baru.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👑 Berlangganan", callback_data="subscribe")],
                    [InlineKeyboardButton("« Menu Utama", callback_data="back")]
                ])
            )
            context.user_data["waiting"] = None
            return
        
        # Activate subscription
        sub_type = token_info['type']
        activate_subscription(user_id, sub_type)
        
        # Mark token as used
        subscription_tokens[token]['used'] = True
        subscription_tokens[token]['used_by'] = user_id
        subscription_tokens[token]['used_at'] = datetime.now()
        
        sub_info = SUBSCRIPTION_PRICES[sub_type]
        expires = user_subscriptions[user_id]['expires']
        
        await msg.reply_text(
            "✅ *LANGGANAN BERHASIL DIAKTIFKAN!*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👑 Selamat! Kamu sekarang VVIP Member!\n\n"
            f"📦 *Paket:* {sub_info['name']}\n"
            f"📅 *Berlaku sampai:* {expires.strftime('%d %B %Y, %H:%M')}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Nikmati akses penuh ke semua episode! 🎬",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📺 Tonton Drama", callback_data="list")],
                [InlineKeyboardButton("🏠 Menu Utama", callback_data="back")]
            ])
        )
        
        context.user_data["waiting"] = None
        logger.info(f"User {user_id} redeemed token {token} for {sub_type}")
        return

    # SEARCH MODE
    if context.user_data.get("waiting") == "search":
        text = (msg.text or "").strip()
        if not text:
            await msg.reply_text("❌ Masukkan nama drama.")
            return

        query_lower = text.lower()
        results = [
            (did, info["title"])
            for did, info in drama_database.items()
            if query_lower in info.get("title", "").lower()
        ]

        if not results:
            search_text = (
                "❌ *Tidak Ditemukan*\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Drama dengan kata kunci *\"{text}\"* tidak ditemukan.\n\n"
                f"Coba kata kunci lain atau lihat daftar lengkap."
            )
            await msg.reply_text(
                search_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📺 Lihat Semua Drama", callback_data="list")],
                    [InlineKeyboardButton("« Kembali", callback_data="back")]
                ]),
                parse_mode='Markdown'
            )
        else:
            keyboard = []
            for did, title in results:
                ep_count = len(drama_database[did].get("episodes", {}))
                keyboard.append([InlineKeyboardButton(
                    f"🎬 {title} ({ep_count} EP)", 
                    callback_data=f"d_{did}"
                )])
            keyboard.append([InlineKeyboardButton("« Kembali", callback_data="back")])
            
            result_text = (
                f"🔍 *Hasil Pencarian*\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Ditemukan {len(results)} drama dengan kata kunci *\"{text}\"*:\n\n"
                f"Pilih drama:"
            )
            
            await msg.reply_text(
                result_text, 
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

        context.user_data["waiting"] = None
        return


# =====================================
# SET BOT COMMANDS
# =====================================
async def post_init(application: Application):
    commands = [
        BotCommand("start", "Mulai bot dan paparkan menu utama")
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands set successfully")


# =====================================
# MAIN
# =====================================
def main():
    Thread(target=run_flask, daemon=True).start()

    app_bot = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CallbackQueryHandler(button_handler))
    app_bot.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    logger.info("Bot berjalan dengan fitur VVIP Subscription...")
    app_bot.run_polling()

if __name__ == "__main__":
    main()
