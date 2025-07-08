import logging
import sqlite3
import os
import uuid
from datetime import datetime
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = "7615976931:AAEjz3Zk-LyJ13bDb2FQ7Y1kezToCZ9gaD8"
ADMIN_ID = 123456789  # You can set your admin user ID here
REFERRAL_BONUS = 10.0  # Bonus amount per referral in rupees
MIN_WITHDRAWAL = 50.0  # Minimum withdrawal amount

class DatabaseManager:
    def __init__(self, db_path="earnyha_bot.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize the database with required tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                balance REAL DEFAULT 0.0,
                total_earned REAL DEFAULT 0.0,
                total_referrals INTEGER DEFAULT 0,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        ''')
        
        # Referrals table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                bonus_amount REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referrer_id) REFERENCES users (user_id),
                FOREIGN KEY (referred_id) REFERENCES users (user_id)
            )
        ''')
        
        # Withdrawals table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                status TEXT DEFAULT 'pending',
                payment_method TEXT,
                payment_details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_user(self, user_id, username, first_name, last_name, referred_by=None):
        """Add a new user to the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        referral_code = str(uuid.uuid4())[:8].upper()
        
        try:
            cursor.execute('''
                INSERT INTO users (user_id, username, first_name, last_name, referral_code, referred_by)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name, referral_code, referred_by))
            
            # If user was referred, add referral bonus
            if referred_by:
                self.add_referral_bonus(referred_by, user_id)
            
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()
    
    def get_user(self, user_id):
        """Get user information"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return {
                'user_id': user[0],
                'username': user[1],
                'first_name': user[2],
                'last_name': user[3],
                'referral_code': user[4],
                'referred_by': user[5],
                'balance': user[6],
                'total_earned': user[7],
                'total_referrals': user[8],
                'join_date': user[9],
                'is_active': user[10]
            }
        return None
    
    def get_user_by_referral_code(self, referral_code):
        """Get user by referral code"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (referral_code,))
        result = cursor.fetchone()
        conn.close()
        
        return result[0] if result else None
    
    def add_referral_bonus(self, referrer_id, referred_id):
        """Add referral bonus to referrer"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Add bonus to referrer
            cursor.execute('''
                UPDATE users 
                SET balance = balance + ?, total_earned = total_earned + ?, total_referrals = total_referrals + 1
                WHERE user_id = ?
            ''', (REFERRAL_BONUS, REFERRAL_BONUS, referrer_id))
            
            # Record the referral
            cursor.execute('''
                INSERT INTO referrals (referrer_id, referred_id, bonus_amount)
                VALUES (?, ?, ?)
            ''', (referrer_id, referred_id, REFERRAL_BONUS))
            
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding referral bonus: {e}")
            return False
        finally:
            conn.close()
    
    def create_withdrawal_request(self, user_id, amount, payment_method, payment_details):
        """Create a withdrawal request"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO withdrawals (user_id, amount, payment_method, payment_details)
                VALUES (?, ?, ?, ?)
            ''', (user_id, amount, payment_method, payment_details))
            
            # Deduct amount from user balance
            cursor.execute('''
                UPDATE users SET balance = balance - ? WHERE user_id = ?
            ''', (amount, user_id))
            
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error creating withdrawal request: {e}")
            return False
        finally:
            conn.close()
    
    def get_all_users(self):
        """Get all users (admin function)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users ORDER BY join_date DESC')
        users = cursor.fetchall()
        conn.close()
        
        return users
    
    def get_pending_withdrawals(self):
        """Get pending withdrawal requests"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT w.*, u.username, u.first_name 
            FROM withdrawals w 
            JOIN users u ON w.user_id = u.user_id 
            WHERE w.status = 'pending' 
            ORDER BY w.created_at DESC
        ''')
        withdrawals = cursor.fetchall()
        conn.close()
        
        return withdrawals

# Initialize database
db = DatabaseManager()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    
    # Check if user exists
    existing_user = db.get_user(user.id)
    
    if existing_user:
        # Existing user
        keyboard = [
            [InlineKeyboardButton("💰 Balance", callback_data='balance')],
            [InlineKeyboardButton("👥 Referrals", callback_data='referrals')],
            [InlineKeyboardButton("💸 Withdraw", callback_data='withdraw')],
            [InlineKeyboardButton("📊 Statistics", callback_data='stats')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Welcome back, {user.first_name}! 🎉\n\n"
            f"Your current balance: ₹{existing_user['balance']:.2f}\n"
            f"Total referrals: {existing_user['total_referrals']}\n\n"
            f"What would you like to do?",
            reply_markup=reply_markup
        )
    else:
        # New user - check for referral code
        referred_by = None
        if context.args and len(context.args) > 0:
            referral_code = context.args[0]
            referred_by = db.get_user_by_referral_code(referral_code)
        
        # Add new user
        success = db.add_user(
            user.id, 
            user.username, 
            user.first_name, 
            user.last_name, 
            referred_by
        )
        
        if success:
            new_user = db.get_user(user.id)
            bonus_msg = ""
            if referred_by:
                bonus_msg = f"\n🎁 You were referred by someone and they earned ₹{REFERRAL_BONUS}!"
            
            keyboard = [
                [InlineKeyboardButton("💰 Balance", callback_data='balance')],
                [InlineKeyboardButton("👥 My Referral Link", callback_data='referrals')],
                [InlineKeyboardButton("💸 Withdraw", callback_data='withdraw')],
                [InlineKeyboardButton("📊 Statistics", callback_data='stats')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"🎉 Welcome to EarnyHa, {user.first_name}!\n\n"
                f"Your referral code: {new_user['referral_code']}\n"
                f"Current balance: ₹{new_user['balance']:.2f}{bonus_msg}\n\n"
                f"💡 **How to earn:**\n"
                f"1. Share your referral link with friends\n"
                f"2. Earn ₹{REFERRAL_BONUS} for each successful referral\n"
                f"3. Withdraw when you reach ₹{MIN_WITHDRAWAL}\n\n"
                f"What would you like to do?",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                "❌ Something went wrong. Please try again later."
            )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await query.edit_message_text("❌ User not found. Please use /start to register.")
        return
    
    if query.data == 'balance':
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"💰 **Your Balance**\n\n"
            f"Current Balance: ₹{user_data['balance']:.2f}\n"
            f"Total Earned: ₹{user_data['total_earned']:.2f}\n"
            f"Total Referrals: {user_data['total_referrals']}\n\n"
            f"Minimum withdrawal: ₹{MIN_WITHDRAWAL}",
            reply_markup=reply_markup
        )
    
    elif query.data == 'referrals':
        referral_link = f"https://t.me/Earnyha_bot?start={user_data['referral_code']}"
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"👥 **Your Referral Information**\n\n"
            f"Your referral code: {user_data['referral_code']}\n"
            f"Your referral link:\n{referral_link}\n\n"
            f"Total referrals: {user_data['total_referrals']}\n"
            f"Earned per referral: ₹{REFERRAL_BONUS}\n\n"
            f"💡 Share this link with friends to earn money!",
            reply_markup=reply_markup
        )
    
    elif query.data == 'withdraw':
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if user_data['balance'] < MIN_WITHDRAWAL:
            await query.edit_message_text(
                f"❌ **Insufficient Balance**\n\n"
                f"Current Balance: ₹{user_data['balance']:.2f}\n"
                f"Minimum withdrawal: ₹{MIN_WITHDRAWAL}\n\n"
                f"You need ₹{MIN_WITHDRAWAL - user_data['balance']:.2f} more to withdraw.",
                reply_markup=reply_markup
            )
        else:
            await query.edit_message_text(
                f"💸 **Withdrawal Request**\n\n"
                f"Available balance: ₹{user_data['balance']:.2f}\n"
                f"Minimum withdrawal: ₹{MIN_WITHDRAWAL}\n\n"
                f"To request a withdrawal, please send a message in this format:\n"
                f"/withdraw <amount> <payment_method> <payment_details>\n\n"
                f"Example:\n"
                f"/withdraw 100 UPI user@paytm\n"
                f"/withdraw 200 Bank 1234567890",
                reply_markup=reply_markup
            )
    
    elif query.data == 'stats':
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"📊 **Your Statistics**\n\n"
            f"Member since: {user_data['join_date'][:10]}\n"
            f"Total referrals: {user_data['total_referrals']}\n"
            f"Total earned: ₹{user_data['total_earned']:.2f}\n"
            f"Current balance: ₹{user_data['balance']:.2f}\n"
            f"Referral code: {user_data['referral_code']}\n\n"
            f"Keep sharing your referral link to earn more!",
            reply_markup=reply_markup
        )
    
    elif query.data == 'main_menu':
        # Show main menu
        keyboard = [
            [InlineKeyboardButton("💰 Balance", callback_data='balance')],
            [InlineKeyboardButton("👥 Referrals", callback_data='referrals')],
            [InlineKeyboardButton("💸 Withdraw", callback_data='withdraw')],
            [InlineKeyboardButton("📊 Statistics", callback_data='stats')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"Welcome back, {query.from_user.first_name}! 🎉\n\n"
            f"Your current balance: ₹{user_data['balance']:.2f}\n"
            f"Total referrals: {user_data['total_referrals']}\n\n"
            f"What would you like to do?",
            reply_markup=reply_markup
        )

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /withdraw command"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await update.message.reply_text("❌ User not found. Please use /start to register.")
        return
    
    if len(context.args) < 3:
        await update.message.reply_text(
            "❌ **Invalid format**\n\n"
            "Usage: /withdraw <amount> <payment_method> <payment_details>\n\n"
            "Examples:\n"
            "/withdraw 100 UPI user@paytm\n"
            "/withdraw 200 Bank 1234567890"
        )
        return
    
    try:
        amount = float(context.args[0])
        payment_method = context.args[1]
        payment_details = ' '.join(context.args[2:])
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please enter a valid number.")
        return
    
    if amount < MIN_WITHDRAWAL:
        await update.message.reply_text(
            f"❌ Minimum withdrawal amount is ₹{MIN_WITHDRAWAL}"
        )
        return
    
    if amount > user_data['balance']:
        await update.message.reply_text(
            f"❌ Insufficient balance. Your current balance is ₹{user_data['balance']:.2f}"
        )
        return
    
    # Create withdrawal request
    success = db.create_withdrawal_request(user_id, amount, payment_method, payment_details)
    
    if success:
        await update.message.reply_text(
            f"✅ **Withdrawal request submitted**\n\n"
            f"Amount: ₹{amount:.2f}\n"
            f"Payment method: {payment_method}\n"
            f"Payment details: {payment_details}\n\n"
            f"Your request will be processed within 24-48 hours."
        )
        
        # Notify admin if configured
        if ADMIN_ID and ADMIN_ID != 123456789:
            try:
                await context.bot.send_message(
                    ADMIN_ID,
                    f"🔔 **New Withdrawal Request**\n\n"
                    f"User: {user_data['first_name']} (@{user_data['username']})\n"
                    f"Amount: ₹{amount:.2f}\n"
                    f"Method: {payment_method}\n"
                    f"Details: {payment_details}\n\n"
                    f"User ID: {user_id}"
                )
            except Exception as e:
                logger.error(f"Error notifying admin: {e}")
    else:
        await update.message.reply_text(
            "❌ Something went wrong. Please try again later."
        )

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /balance command"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await update.message.reply_text("❌ User not found. Please use /start to register.")
        return
    
    await update.message.reply_text(
        f"💰 **Your Balance**\n\n"
        f"Current Balance: ₹{user_data['balance']:.2f}\n"
        f"Total Earned: ₹{user_data['total_earned']:.2f}\n"
        f"Total Referrals: {user_data['total_referrals']}\n\n"
        f"Minimum withdrawal: ₹{MIN_WITHDRAWAL}"
    )

async def referrals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /referrals command"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await update.message.reply_text("❌ User not found. Please use /start to register.")
        return
    
    referral_link = f"https://t.me/Earnyha_bot?start={user_data['referral_code']}"
    await update.message.reply_text(
        f"👥 **Your Referral Information**\n\n"
        f"Your referral code: {user_data['referral_code']}\n"
        f"Your referral link:\n{referral_link}\n\n"
        f"Total referrals: {user_data['total_referrals']}\n"
        f"Earned per referral: ₹{REFERRAL_BONUS}\n\n"
        f"💡 Share this link with friends to earn money!"
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /admin command"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "**Admin Commands:**\n\n"
            "/admin users - Show all users\n"
            "/admin withdrawals - Show pending withdrawals\n"
            "/admin stats - Show bot statistics"
        )
        return
    
    command = context.args[0].lower()
    
    if command == 'users':
        users = db.get_all_users()
        if not users:
            await update.message.reply_text("No users found.")
            return
        
        message = "**All Users:**\n\n"
        for user in users[:10]:  # Show first 10 users
            message += f"ID: {user[0]}\n"
            message += f"Name: {user[2]} {user[3] or ''}\n"
            message += f"Username: @{user[1] or 'N/A'}\n"
            message += f"Balance: ₹{user[6]:.2f}\n"
            message += f"Referrals: {user[8]}\n"
            message += f"Joined: {user[9][:10]}\n\n"
        
        await update.message.reply_text(message)
    
    elif command == 'withdrawals':
        withdrawals = db.get_pending_withdrawals()
        if not withdrawals:
            await update.message.reply_text("No pending withdrawals.")
            return
        
        message = "**Pending Withdrawals:**\n\n"
        for withdrawal in withdrawals:
            message += f"User: {withdrawal[9]} {withdrawal[10] or ''}\n"
            message += f"Amount: ₹{withdrawal[2]:.2f}\n"
            message += f"Method: {withdrawal[4]}\n"
            message += f"Details: {withdrawal[5]}\n"
            message += f"Date: {withdrawal[6][:10]}\n\n"
        
        await update.message.reply_text(message)
    
    elif command == 'stats':
        users = db.get_all_users()
        total_users = len(users)
        total_balance = sum(user[6] for user in users)
        total_earned = sum(user[7] for user in users)
        total_referrals = sum(user[8] for user in users)
        
        await update.message.reply_text(
            f"**Bot Statistics:**\n\n"
            f"Total Users: {total_users}\n"
            f"Total Balance: ₹{total_balance:.2f}\n"
            f"Total Earned: ₹{total_earned:.2f}\n"
            f"Total Referrals: {total_referrals}"
        )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /menu command"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await update.message.reply_text("❌ User not found. Please use /start to register.")
        return
    
    keyboard = [
        [InlineKeyboardButton("💰 Balance", callback_data='balance')],
        [InlineKeyboardButton("👥 Referrals", callback_data='referrals')],
        [InlineKeyboardButton("💸 Withdraw", callback_data='withdraw')],
        [InlineKeyboardButton("📊 Statistics", callback_data='stats')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Welcome back, {update.effective_user.first_name}! 🎉\n\n"
        f"Your current balance: ₹{user_data['balance']:.2f}\n"
        f"Total referrals: {user_data['total_referrals']}\n\n"
        f"What would you like to do?",
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    keyboard = [
        [InlineKeyboardButton("🏠 Main Menu", callback_data='main_menu')],
        [InlineKeyboardButton("💰 Balance", callback_data='balance')],
        [InlineKeyboardButton("👥 Referrals", callback_data='referrals')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "**EarnyHa Bot - Help**\n\n"
        "**Available Commands:**\n"
        "/start - Register or view main menu\n"
        "/menu - Show main menu\n"
        "/balance - Check your balance\n"
        "/referrals - Get your referral link\n"
        "/withdraw <amount> <method> <details> - Request withdrawal\n"
        "/help - Show this help message\n\n"
        "**How to earn:**\n"
        "1. Share your referral link with friends\n"
        "2. Earn ₹10 for each successful referral\n"
        "3. Withdraw when you reach ₹50\n\n"
        "**Contact:** For support, contact the bot administrator.",
        reply_markup=reply_markup
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")

def main():
    """Start the bot"""
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("referrals", referrals_command))
    application.add_handler(CommandHandler("withdraw", withdraw_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    print("🤖 EarnyHa Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()