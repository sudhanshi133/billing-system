import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sqlite3
import hashlib
from datetime import datetime, date, timedelta
import json
import os
from PIL import Image, ImageTk, ImageDraw, ImageFont
import tempfile
import csv
import queue
import threading
import time
import re
import os
import traceback

# Pillow compatibility - handle different versions
try:
    from PIL import ImageWin
except ImportError:
    ImageWin = None

# Handle different Pillow versions for resampling
try:
    RESAMPLE_FILTER = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_FILTER = Image.LANCZOS

# Windows printer support
try:
    import win32print
    PRINTER_AVAILABLE = True
except ImportError:
    PRINTER_AVAILABLE = False
    print("WARNING: win32print module not found. Printer functionality will be disabled.")
    print("To enable printing, install: pip install pywin32")


# ==================== WINDOWS PRINTER MANAGER ====================
# ==================== WINDOWS PRINTER MANAGER (WORKING VERSION) ====================
class WindowsPrinterManager:
    def __init__(self, db_path="pos_printers.db"):
        self.db_path = db_path
        self.init_database()

    # --------------------------------------------------
    # DATABASE
    # --------------------------------------------------
    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
       CREATE TABLE IF NOT EXISTS printer_settings (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           printer_name TEXT,
           printer_type TEXT,
           paper_width INTEGER,
           is_default INTEGER DEFAULT 0
       )
       """)

        conn.commit()
        conn.close()

        self.ensure_default_printer()

    def ensure_default_printer(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM printer_settings")
        count = cursor.fetchone()[0]

        if count == 0:
            try:
                default_printer = win32print.GetDefaultPrinter()
            except:
                default_printer = None

            cursor.execute("""
           INSERT INTO printer_settings
           (printer_name, printer_type, paper_width, is_default)
           VALUES (?, 'receipt', 32, 1)
           """, (default_printer,))

            conn.commit()

        conn.close()

    def get_printer(self, printer_type="receipt"):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
       SELECT printer_name, paper_width
       FROM printer_settings
       WHERE printer_type=?
       LIMIT 1
       """, (printer_type,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                "name": row[0],
                "width": row[1]
            }

        return None

    def set_printer(self, printer_type, printer_name, paper_width=32):
        """Set printer for a specific type"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Delete existing for this type
        cursor.execute("DELETE FROM printer_settings WHERE printer_type=?", (printer_type,))

        # Insert new
        cursor.execute("""
       INSERT INTO printer_settings
       (printer_name, printer_type, paper_width, is_default)
       VALUES (?, ?, ?, 1)
       """, (printer_name, printer_type, paper_width))

        conn.commit()
        conn.close()

    # --------------------------------------------------
    # PRINTER LIST
    # --------------------------------------------------
    def list_windows_printers(self):
        if not PRINTER_AVAILABLE:
            print("Printer module not available")
            return []
        try:
            printers = win32print.EnumPrinters(2)
            return [p[2] for p in printers]
        except Exception as e:
            print(f"Error listing printers: {e}")
            return []

    # --------------------------------------------------
    # TEXT FORMATTER
    # --------------------------------------------------
    def format_receipt(self, text, width=32):
        lines = text.split("\n")
        formatted = []

        for line in lines:
            if len(line) <= width:
                formatted.append(line)
            else:
                while len(line) > width:
                    formatted.append(line[:width])
                    line = line[width:]
                formatted.append(line)

        return "\n".join(formatted) + "\n\n\n"

    # --------------------------------------------------
    # CORE PRINT FUNCTION
    # --------------------------------------------------
    def print_text(self, text, printer_type="receipt"):
        if not PRINTER_AVAILABLE:
            print(f"❌ Printer module not available. Cannot print {printer_type}.")
            print("Install pywin32: pip install pywin32")
            return False

        printer_info = self.get_printer(printer_type)

        if not printer_info:
            print(f"No printer configured for type: {printer_type}")
            return False

        printer_name = printer_info["name"]
        width = printer_info["width"]

        formatted = self.format_receipt(text, width)

        try:
            # fallback if db printer fails
            if not printer_name:
                printer_name = win32print.GetDefaultPrinter()

            try:
                hprinter = win32print.OpenPrinter(printer_name)
            except:
                print("DB printer failed, using default printer")
                printer_name = win32print.GetDefaultPrinter()
                hprinter = win32print.OpenPrinter(printer_name)

            job = win32print.StartDocPrinter(hprinter, 1, ("POS Receipt", None, "RAW"))
            win32print.StartPagePrinter(hprinter)

            win32print.WritePrinter(
                hprinter,
                formatted.encode("cp437", "ignore")
            )

            win32print.EndPagePrinter(hprinter)
            win32print.EndDocPrinter(hprinter)
            win32print.ClosePrinter(hprinter)

            print(f"✅ Printed successfully on {printer_name}")
            return True

        except Exception as e:
            print(f"❌ Print error: {e}")
            traceback.print_exc()
            return False

    # --------------------------------------------------
    # RECEIPT PRINTING (BILL)
    # --------------------------------------------------
    def print_bill(self, order_data):
        """Print final bill/receipt"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        settings = order_data.get('settings', {})

        receipt = []
        receipt.append(f"{settings.get('hotel_name', 'RESTAURANT'):^32}")
        receipt.append("-" * 32)
        receipt.append(f"Bill No: {order_data['bill_number']}")
        receipt.append(f"Order : {order_data['order_number']}")
        receipt.append(f"Date  : {now}")
        receipt.append(f"Table : {order_data.get('table', 'N/A')}")
        receipt.append("-" * 32)
        receipt.append(f"{'Item':<20} {'Qty':>3} {'Amt':>7}")
        receipt.append("-" * 32)

        total = 0
        for item in order_data["items"]:
            name = item["name"][:20]
            qty = item["qty"]
            price = item["price"]
            line_total = qty * price
            total += line_total
            receipt.append(f"{name:<20} {qty:>3} ₹{line_total:>6.2f}")

        receipt.append("-" * 32)
        receipt.append(f"{'Subtotal:':<25} ₹{total:>6.2f}")

        tax = order_data.get('tax', 0)
        if tax > 0:
            receipt.append(f"{'Tax:':<25} ₹{tax:>6.2f}")
            total += tax

        receipt.append("=" * 32)
        receipt.append(f"{'TOTAL:':<25} ₹{total:>6.2f}")
        receipt.append("=" * 32)
        receipt.append(f"{'Thank You!':^32}")
        receipt.append(f"{'Visit Again!':^32}")
        receipt.append("=" * 32)

        text = "\n".join(receipt)
        return self.print_text(text, "bill")

    # --------------------------------------------------
    # KITCHEN PRINT
    # --------------------------------------------------
    def print_kitchen(self, order_data):
        """Print kitchen order slip"""
        kitchen = []
        kitchen.append("=" * 32)
        kitchen.append(f"{'KITCHEN ORDER':^32}")
        kitchen.append("=" * 32)
        kitchen.append(f"Order: {order_data['order_number']}")
        kitchen.append(f"Table: {order_data.get('table', 'N/A')}")
        kitchen.append(f"Time : {datetime.now().strftime('%H:%M:%S')}")
        kitchen.append("-" * 32)

        for item in order_data["items"]:
            kitchen.append(f"{item['qty']} x {item['name']}")

        kitchen.append("-" * 32)
        kitchen.append("=" * 32)

        text = "\n".join(kitchen)
        return self.print_text(text, "kitchen")

    # --------------------------------------------------
    # DESK PRINT
    # --------------------------------------------------
    def print_desk(self, order_data):
        """Print desk order slip"""
        now = datetime.now().strftime("%H:%M:%S")

        desk = []
        desk.append("=" * 40)
        desk.append(f"{'DESK ORDER':^40}")
        desk.append("=" * 40)
        desk.append(f"Order: {order_data['order_number']}")
        desk.append(f"Table: {order_data.get('table', 'N/A')}")
        desk.append(f"Time : {now}")
        desk.append("-" * 40)
        desk.append(f"{'Item':<25} {'Qty':>5} {'Price':>8}")
        desk.append("-" * 40)

        total = 0
        for item in order_data["items"]:
            name = item["name"][:25]
            qty = item["qty"]
            price = item["price"]
            line_total = qty * price
            total += line_total
            desk.append(f"{name:<25} {qty:>5}  ₹{line_total:>8.2f}")

        desk.append("-" * 40)
        desk.append(f"{'TOTAL:':<35} ₹{total:>8.2f}")
        desk.append("=" * 40)

        text = "\n".join(desk)
        return self.print_text(text, "desk")

    # --------------------------------------------------
    # TEST PRINTER
    # --------------------------------------------------
    def test_printer(self, printer_type):
        """Test printer connection with actual printing"""
        if not PRINTER_AVAILABLE:
            print(f"❌ Printer module not available. Cannot test {printer_type} printer.")
            print("Install pywin32: pip install pywin32")
            return False

        test_content = f"""
    {'=' * 40}
    {'PRINTER TEST':^40}
    {'=' * 40}
    Printer Type: {printer_type}
    Time: {datetime.now().strftime('%H:%M:%S')}
    Date: {datetime.now().strftime('%Y-%m-%d')}
    {'=' * 40}
    If you can read this,
    the printer is working!
    {'=' * 40}

    """
        # Format the test content
        printer_info = self.get_printer(printer_type)
        if not printer_info:
            print(f"No printer configured for {printer_type}")
            return False

        printer_name = printer_info["name"]
        width = printer_info["width"]

        formatted = self.format_receipt(test_content, width)

        try:
            # Try to open and print
            hprinter = win32print.OpenPrinter(printer_name)
            job_id = win32print.StartDocPrinter(hprinter, 1, ("Printer Test", None, "RAW"))
            win32print.StartPagePrinter(hprinter)

            win32print.WritePrinter(
                hprinter,
                formatted.encode('cp437', 'ignore')
            )

            win32print.EndPagePrinter(hprinter)
            win32print.EndDocPrinter(hprinter)
            win32print.ClosePrinter(hprinter)

            print(f"✅ Test page printed successfully on {printer_name}")
            return True

        except Exception as e:
            print(f"❌ Printer test failed: {e}")
            traceback.print_exc()
            return False


# ==================== DATABASE SETUP ====================
class IntegratedDatabase:
    def __init__(self, db_name='integrated_billing.db'):
        self.db_name = db_name
        self.connection_pool = queue.Queue(maxsize=10)
        self.init_connection_pool()
        self.init_database()

    def init_connection_pool(self):
        """Initialize connection pool with 5 connections."""
        for _ in range(5):
            conn = sqlite3.connect(self.db_name, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            self.connection_pool.put(conn)

    def get_connection(self):
        """Get a connection from the pool."""
        try:
            return self.connection_pool.get(timeout=10)
        except queue.Empty:
            conn = sqlite3.connect(self.db_name, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            return conn

    def return_connection(self, conn):
        """Return connection to the pool."""
        if conn:
            try:
                self.connection_pool.put(conn, timeout=5)
            except queue.Full:
                conn.close()

    def execute_query(self, query, params=(), fetch_one=False, fetch_all=False, commit=False):
        """Execute a query with proper connection handling."""
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(query, params)

            result = None
            if fetch_one:
                result = cursor.fetchone()
            elif fetch_all:
                result = cursor.fetchall()

            if commit:
                conn.commit()

            return result
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn:
                self.return_connection(conn)

    def init_database(self):
        """Initialize database tables with integration support."""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Add pending bills table
        cursor.execute('''
           CREATE TABLE IF NOT EXISTS pending_bills (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               bill_id INTEGER NOT NULL,
               customer_name TEXT NOT NULL,
               customer_phone TEXT,
               reference_name TEXT NOT NULL,
               reference_phone TEXT NOT NULL,
               reference_notes TEXT,
               pending_amount REAL NOT NULL,
               original_total REAL NOT NULL,
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
               status TEXT DEFAULT 'pending',
               converted_to_paid_at TIMESTAMP,
               converted_by INTEGER,
               FOREIGN KEY (bill_id) REFERENCES bills (id),
               FOREIGN KEY (converted_by) REFERENCES users (id)
           )
       ''')

        # Users table
        cursor.execute('''
           CREATE TABLE IF NOT EXISTS users (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               username TEXT UNIQUE NOT NULL,
               password_hash TEXT NOT NULL,
               role TEXT NOT NULL,
               email TEXT,
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
           )
       ''')

        # Hotel settings table
        cursor.execute('''
           CREATE TABLE IF NOT EXISTS hotel_settings (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               hotel_name TEXT DEFAULT 'THE EVAANI HOTEL',
               address TEXT DEFAULT 'Talwandi Road, Mansa',
               phone TEXT DEFAULT '9530752236, 9915297440',
               gstin TEXT DEFAULT '03AATFJ9071F1Z3',
               updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
           )
       ''')

        # Day management table
        cursor.execute('''
           CREATE TABLE IF NOT EXISTS day_management (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               day_date DATE UNIQUE NOT NULL,
               is_open BOOLEAN DEFAULT 0,
               opened_at TIMESTAMP,
               closed_at TIMESTAMP,
               opened_by INTEGER,
               closed_by INTEGER,
               opening_cash REAL DEFAULT 0.0,
               closing_cash REAL DEFAULT 0.0,
               total_sales REAL DEFAULT 0.0,
               restaurant_sales REAL DEFAULT 0.0,
               room_service_sales REAL DEFAULT 0.0,
               complimentary_sales REAL DEFAULT 0.0,
               cash_sales REAL DEFAULT 0.0,
               card_sales REAL DEFAULT 0.0,
               upi_sales REAL DEFAULT 0.0,
               status TEXT DEFAULT 'closed',
               FOREIGN KEY (opened_by) REFERENCES users (id),
               FOREIGN KEY (closed_by) REFERENCES users (id)
           )
       ''')

        # Restaurants table
        cursor.execute('''
           CREATE TABLE IF NOT EXISTS restaurants (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               restaurant_code TEXT UNIQUE NOT NULL,
               restaurant_name TEXT NOT NULL,
               table_count INTEGER DEFAULT 0,
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
           )
       ''')

        # Tables table
        cursor.execute('''
           CREATE TABLE IF NOT EXISTS restaurant_tables (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               restaurant_id INTEGER NOT NULL,
               table_number TEXT NOT NULL,
               status TEXT DEFAULT 'available',
               current_order_id INTEGER,
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
               FOREIGN KEY (restaurant_id) REFERENCES restaurants (id),
               UNIQUE(restaurant_id, table_number)
           )
       ''')

        # Menu categories table
        cursor.execute('''
           CREATE TABLE IF NOT EXISTS menu_categories (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               category_name TEXT UNIQUE NOT NULL,
               tax_exempt BOOLEAN DEFAULT 0,
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
           )
       ''')

        # Menu items table
        cursor.execute('''
           CREATE TABLE IF NOT EXISTS menu_items (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               item_name TEXT NOT NULL,
               category_id INTEGER NOT NULL,
               price REAL NOT NULL,
               tax_percentage REAL DEFAULT 5.0,
               inventory_item_name TEXT,
               description TEXT,
               is_available BOOLEAN DEFAULT 1,
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
               updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
               FOREIGN KEY (category_id) REFERENCES menu_categories (id)
           )
       ''')

        # Orders table
        cursor.execute('''
           CREATE TABLE IF NOT EXISTS orders (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               order_number TEXT UNIQUE NOT NULL,
               customer_name TEXT NOT NULL,
               customer_phone TEXT,
               restaurant_id INTEGER NOT NULL,
               table_id INTEGER,
               table_number TEXT,
               room_id INTEGER,
               room_number TEXT,
               order_type TEXT DEFAULT 'restaurant',
               order_date DATE NOT NULL,
               order_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
               status TEXT DEFAULT 'active',
               total_amount REAL DEFAULT 0.0,
               tax_amount REAL DEFAULT 0.0,
               payment_status TEXT DEFAULT 'pending',
               payment_method TEXT,
               is_complimentary BOOLEAN DEFAULT 0,
               created_by INTEGER,
               completed_at TIMESTAMP,
               FOREIGN KEY (restaurant_id) REFERENCES restaurants (id),
               FOREIGN KEY (table_id) REFERENCES restaurant_tables (id),
               FOREIGN KEY (created_by) REFERENCES users (id)
           )
       ''')

        # Order items table
        cursor.execute('''
           CREATE TABLE IF NOT EXISTS order_items (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               order_id INTEGER NOT NULL,
               menu_item_id INTEGER NOT NULL,
               item_name TEXT NOT NULL,
               quantity INTEGER NOT NULL,
               unit_price REAL NOT NULL,
               tax_percentage REAL NOT NULL,
               total_price REAL NOT NULL,
               printed_to_kitchen BOOLEAN DEFAULT 0,
               printed_to_desk BOOLEAN DEFAULT 0,
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
               FOREIGN KEY (order_id) REFERENCES orders (id),
               FOREIGN KEY (menu_item_id) REFERENCES menu_items (id)
           )
       ''')

        # Bills table
        cursor.execute('''
           CREATE TABLE IF NOT EXISTS bills (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               bill_number TEXT UNIQUE NOT NULL,
               order_id INTEGER NOT NULL,
               customer_name TEXT NOT NULL,
               customer_phone TEXT,
               restaurant_name TEXT,
               table_number TEXT,
               room_number TEXT,
               order_type TEXT,
               bill_date DATE NOT NULL,
               bill_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
               subtotal REAL NOT NULL,
               tax_amount REAL NOT NULL,
               total_amount REAL NOT NULL,
               payment_method TEXT,
               payment_status TEXT DEFAULT 'pending',
               is_complimentary BOOLEAN DEFAULT 0,
               discount_percentage REAL DEFAULT 0.0,
               discount_amount REAL DEFAULT 0.0,
               cash_received REAL DEFAULT 0.0,
               change_returned REAL DEFAULT 0.0,
               created_by INTEGER,
               day_id INTEGER,
               FOREIGN KEY (order_id) REFERENCES orders (id),
               FOREIGN KEY (created_by) REFERENCES users (id),
               FOREIGN KEY (day_id) REFERENCES day_management (id)
           )
       ''')

        # Integration with hotel database
        cursor.execute('''
           CREATE TABLE IF NOT EXISTS hotel_integration (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               hotel_db_path TEXT DEFAULT 'hotel_billing.db',
               inventory_db_path TEXT DEFAULT 'inventory.db',
               last_sync TIMESTAMP,
               sync_status TEXT
           )
       ''')

        # Inventory deductions tracking
        cursor.execute('''
           CREATE TABLE IF NOT EXISTS inventory_deductions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               order_id INTEGER NOT NULL,
               item_name TEXT NOT NULL,
               quantity INTEGER NOT NULL,
               inventory_item_name TEXT,
               deduction_status TEXT DEFAULT 'pending',
               reason TEXT DEFAULT 'Hotel Restaurant Billing',
               deducted_at TIMESTAMP,
               FOREIGN KEY (order_id) REFERENCES orders (id)
           )
       ''')

        # Printer settings table - with all columns properly defined (ONCE)
        cursor.execute('''
           CREATE TABLE IF NOT EXISTS printer_settings (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               printer_name TEXT NOT NULL,
               printer_type TEXT NOT NULL,  -- 'kitchen', 'desk', 'bill', 'report'
               printer_port TEXT,  -- USB, LPT1, COM1, etc.
               printer_ip TEXT,  -- Network printer IP
               is_default BOOLEAN DEFAULT 0,
               paper_width INTEGER DEFAULT 40,  -- Character width for thermal printer
               enabled BOOLEAN DEFAULT 1,
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
           )
       ''')

        # Print jobs tracking
        cursor.execute('''
           CREATE TABLE IF NOT EXISTS print_jobs (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               job_type TEXT NOT NULL,  -- 'kitchen', 'desk', 'bill', 'report'
               document_type TEXT,  -- 'order', 'bill', 'report'
               reference_id INTEGER,  -- order_id or bill_id
               content TEXT,
               status TEXT DEFAULT 'pending',  -- 'pending', 'printed', 'failed'
               printed_at TIMESTAMP,
               printer_name TEXT,
               retry_count INTEGER DEFAULT 0,
               error_message TEXT,
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
           )
       ''')

        # Add bill edit history table
        cursor.execute('''
           CREATE TABLE IF NOT EXISTS bill_edit_history (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               bill_id INTEGER NOT NULL,
               edited_by INTEGER NOT NULL,
               edited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
               field_name TEXT NOT NULL,
               old_value TEXT,
               new_value TEXT,
               reason TEXT,
               FOREIGN KEY (bill_id) REFERENCES bills (id),
               FOREIGN KEY (edited_by) REFERENCES users (id)
           )
       ''')

        cursor.execute('''
           INSERT OR IGNORE INTO printer_settings (printer_name, printer_type, paper_width, is_default)
           VALUES
               ('EPSON TM-T20 (Kitchen)', 'kitchen', 32, 1),
               ('EPSON TM-T20 (Desk)', 'desk', 40, 1),
               ('EPSON TM-T20 (Bill)', 'bill', 40, 1)
       ''')

        # Add default categories
        categories = [
            ('Starters', 0),
            ('Main Course', 0),
            ('Beverages', 1),  # Tax exempt
            ('Desserts', 0),
            ('Soups', 0),
            ('Rice & Biryani', 0),
            ('Breads', 0),
            ('Chinese', 0),
            ('Continental', 0)
        ]

        for cat_name, tax_exempt in categories:
            cursor.execute('''
               INSERT OR IGNORE INTO menu_categories (category_name, tax_exempt)
               VALUES (?, ?)
           ''', (cat_name, tax_exempt))

        # Add default restaurants R1-R5
        restaurants = [
            ('R1', 'Main Restaurant', 9),
            ('R2', 'Fine Dining', 10),
            ('R3', 'Terrace Garden', 8),
            ('R4', 'Pool Side', 6),
            ('R5', 'VIP Lounge', 5)
        ]

        for code, name, table_count in restaurants:
            cursor.execute('''
               INSERT OR IGNORE INTO restaurants (restaurant_code, restaurant_name, table_count)
               VALUES (?, ?, ?)
           ''', (code, name, table_count))

        # Add tables for each restaurant
        cursor.execute('SELECT id, restaurant_code, table_count FROM restaurants')
        restaurants_data = cursor.fetchall()

        for rest in restaurants_data:
            rest_id = rest['id']
            code = rest['restaurant_code']
            count = rest['table_count']

            for i in range(1, count + 1):
                table_num = f"t{i}"
                cursor.execute('''
                   INSERT OR IGNORE INTO restaurant_tables (restaurant_id, table_number, status)
                   VALUES (?, ?, ?)
               ''', (rest_id, table_num, 'available'))

        # Add default hotel settings
        cursor.execute('''
           INSERT OR IGNORE INTO hotel_settings (hotel_name, address, phone, gstin)
           VALUES ('THE EVAANI HOTEL', 'Talwandi Road, Mansa', '9530752236, 9915297440', '03AATFJ9071F1Z3')
       ''')

        # Add default admin user if not exists
        admin_hash = self.hash_password('admin123')
        cursor.execute('''
           INSERT OR IGNORE INTO users (username, password_hash, role, email)
           VALUES (?, ?, ?, ?)
       ''', ('admin', admin_hash, 'admin', 'admin@evaani.com'))

        # Add default user if not exists
        user_hash = self.hash_password('user123')
        cursor.execute('''
           INSERT OR IGNORE INTO users (username, password_hash, role, email)
           VALUES (?, ?, ?, ?)
       ''', ('user', user_hash, 'user', 'user@evaani.com'))

        # Initialize integration tracking
        cursor.execute('''
           INSERT OR IGNORE INTO hotel_integration (hotel_db_path, inventory_db_path, last_sync, sync_status)
           VALUES ('hotel_billing.db', 'inventory.db', CURRENT_TIMESTAMP, 'initialized')
       ''')

        conn.commit()
        self.return_connection(conn)
        self.migrate_database()

    def migrate_database(self):
        """Add missing columns to existing tables."""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # Check if columns exist in day_management table
            cursor.execute("PRAGMA table_info(day_management)")
            columns = [col[1] for col in cursor.fetchall()]

            # Add restaurant_sales column if it doesn't exist
            if 'restaurant_sales' not in columns:
                print("Adding restaurant_sales column to day_management table...")
                cursor.execute('ALTER TABLE day_management ADD COLUMN restaurant_sales REAL DEFAULT 0.0')

            # Add room_service_sales column if it doesn't exist
            if 'room_service_sales' not in columns:
                print("Adding room_service_sales column to day_management table...")
                cursor.execute('ALTER TABLE day_management ADD COLUMN room_service_sales REAL DEFAULT 0.0')

            # Check if bills table has discount columns
            cursor.execute("PRAGMA table_info(bills)")
            bill_columns = [col[1] for col in cursor.fetchall()]

            if 'discount_percentage' not in bill_columns:
                print("Adding discount_percentage column to bills table...")
                cursor.execute('ALTER TABLE bills ADD COLUMN discount_percentage REAL DEFAULT 0.0')

            if 'discount_amount' not in bill_columns:
                print("Adding discount_amount column to bills table...")
                cursor.execute('ALTER TABLE bills ADD COLUMN discount_amount REAL DEFAULT 0.0')

            # Add settlement columns if they don't exist
            if 'settled_at' not in bill_columns:
                print("Adding settled_at column to bills table...")
                cursor.execute('ALTER TABLE bills ADD COLUMN settled_at TIMESTAMP')

            if 'settlement_notes' not in bill_columns:
                print("Adding settlement_notes column to bills table...")
                cursor.execute('ALTER TABLE bills ADD COLUMN settlement_notes TEXT')

            # Check orders table for missing columns
            cursor.execute("PRAGMA table_info(orders)")
            order_columns = [col[1] for col in cursor.fetchall()]

            # Add discount columns to orders table if they don't exist
            if 'discount_percentage' not in order_columns:
                print("Adding discount_percentage column to orders table...")
                try:
                    cursor.execute('ALTER TABLE orders ADD COLUMN discount_percentage REAL DEFAULT 0.0')
                except sqlite3.OperationalError as e:
                    print(f"Note: {e}")

            if 'discount_amount' not in order_columns:
                print("Adding discount_amount column to orders table...")
                try:
                    cursor.execute('ALTER TABLE orders ADD COLUMN discount_amount REAL DEFAULT 0.0')
                except sqlite3.OperationalError as e:
                    print(f"Note: {e}")

            # Check printer_settings table
            cursor.execute("PRAGMA table_info(printer_settings)")
            printer_columns = [col[1] for col in cursor.fetchall()]

            # If printer_settings table exists, check for missing columns
            if printer_columns:
                if 'paper_width' not in printer_columns:
                    print("Adding paper_width column to printer_settings table...")
                    try:
                        cursor.execute('ALTER TABLE printer_settings ADD COLUMN paper_width INTEGER DEFAULT 40')
                    except sqlite3.OperationalError as e:
                        print(f"Note: {e}")

                if 'printer_port' not in printer_columns:
                    print("Adding printer_port column to printer_settings table...")
                    try:
                        cursor.execute('ALTER TABLE printer_settings ADD COLUMN printer_port TEXT')
                    except sqlite3.OperationalError as e:
                        print(f"Note: {e}")

                if 'printer_ip' not in printer_columns:
                    print("Adding printer_ip column to printer_settings table...")
                    try:
                        cursor.execute('ALTER TABLE printer_settings ADD COLUMN printer_ip TEXT')
                    except sqlite3.OperationalError as e:
                        print(f"Note: {e}")

                if 'enabled' not in printer_columns:
                    print("Adding enabled column to printer_settings table...")
                    try:
                        cursor.execute('ALTER TABLE printer_settings ADD COLUMN enabled BOOLEAN DEFAULT 1')
                    except sqlite3.OperationalError as e:
                        print(f"Note: {e}")

                if 'is_default' not in printer_columns:
                    print("Adding is_default column to printer_settings table...")
                    try:
                        cursor.execute('ALTER TABLE printer_settings ADD COLUMN is_default BOOLEAN DEFAULT 0')
                    except sqlite3.OperationalError as e:
                        print(f"Note: {e}")

            # Check print_jobs table
            cursor.execute("PRAGMA table_info(print_jobs)")
            job_columns = [col[1] for col in cursor.fetchall()]

            if job_columns:
                if 'retry_count' not in job_columns:
                    print("Adding retry_count column to print_jobs table...")
                    try:
                        cursor.execute('ALTER TABLE print_jobs ADD COLUMN retry_count INTEGER DEFAULT 0')
                    except sqlite3.OperationalError as e:
                        print(f"Note: {e}")

                if 'error_message' not in job_columns:
                    print("Adding error_message column to print_jobs table...")
                    try:
                        cursor.execute('ALTER TABLE print_jobs ADD COLUMN error_message TEXT')
                    except sqlite3.OperationalError as e:
                        print(f"Note: {e}")

            conn.commit()
            print("Database migration completed successfully.")

        except Exception as e:
            print(f"Error during migration: {e}")
            conn.rollback()
        finally:
            self.return_connection(conn)

    @staticmethod
    def hash_password(password):
        return hashlib.sha256(password.encode()).hexdigest()

    def verify_user(self, username, password):
        password_hash = self.hash_password(password)
        result = self.execute_query(
            'SELECT id, username, role FROM users WHERE username = ? AND password_hash = ?',
            (username, password_hash),
            fetch_one=True
        )
        if result:
            return {'id': result[0], 'username': result[1], 'role': result[2]}
        return None

    def get_hotel_settings(self):
        """Get hotel settings."""
        result = self.execute_query(
            'SELECT * FROM hotel_settings ORDER BY id DESC LIMIT 1',
            fetch_one=True
        )
        return dict(result) if result else {
            'hotel_name': 'THE EVAANI HOTEL',
            'address': 'Talwandi Road, Mansa',
            'phone': '9530752236, 9915297440',
            'gstin': '03AATFJ9071F1Z3'
        }

    def update_hotel_settings(self, settings_data):
        """Update hotel settings."""
        self.execute_query('''
           UPDATE hotel_settings
           SET hotel_name = ?, address = ?, phone = ?, gstin = ?, updated_at = CURRENT_TIMESTAMP
           WHERE id = (SELECT id FROM hotel_settings ORDER BY id DESC LIMIT 1)
       ''', (
            settings_data['hotel_name'],
            settings_data['address'],
            settings_data['phone'],
            settings_data['gstin']
        ), commit=True)


# ==================== AUTHENTICATION ====================
class Authentication:
    def __init__(self, db: IntegratedDatabase):
        self.db = db
        self.current_user = None

    def login(self, username, password):
        if not username or not password:
            raise ValueError("Username and password are required")

        user = self.db.verify_user(username, password)
        if user:
            self.current_user = user
            return user
        return None

    def logout(self):
        self.current_user = None

    def is_admin(self):
        return self.current_user and self.current_user['role'] == 'admin'

    def is_authenticated(self):
        return self.current_user is not None


# ==================== DAY MANAGEMENT ====================
class DayManager:
    def __init__(self, db: IntegratedDatabase, auth: Authentication):
        self.db = db
        self.auth = auth
        self.current_day = None

    def check_today_status(self):
        """Check if today is open."""
        today = date.today().isoformat()
        result = self.db.execute_query(
            'SELECT * FROM day_management WHERE day_date = ?',
            (today,),
            fetch_one=True
        )
        if result:
            self.current_day = dict(result)
            return self.current_day.get('is_open', False)
        return False

    def start_day(self, opening_cash=0.0):
        """Start a new day."""
        today = date.today().isoformat()
        now = datetime.now().isoformat()

        # Check if day already exists
        existing = self.db.execute_query(
            'SELECT id FROM day_management WHERE day_date = ?',
            (today,),
            fetch_one=True
        )

        if existing:
            # Update existing
            self.db.execute_query('''
               UPDATE day_management
               SET is_open = 1, opened_at = ?, opened_by = ?, opening_cash = ?, status = 'open'
               WHERE day_date = ?
           ''', (now, self.auth.current_user['id'], opening_cash, today), commit=True)
        else:
            # Create new
            self.db.execute_query('''
               INSERT INTO day_management
               (day_date, is_open, opened_at, opened_by, opening_cash, status)
               VALUES (?, 1, ?, ?, ?, 'open')
           ''', (today, now, self.auth.current_user['id'], opening_cash), commit=True)

        self.check_today_status()
        return True

    def close_day(self, closing_cash):
        """Close the current day."""
        today = date.today().isoformat()
        now = datetime.now().isoformat()

        # Get day's sales totals - SEPARATE restaurant and room service
        sales = self.db.execute_query('''
           SELECT
               COALESCE(SUM(CASE WHEN payment_method = 'cash' AND is_complimentary = 0 AND order_type = 'restaurant' THEN total_amount ELSE 0 END), 0) as restaurant_cash_sales,
               COALESCE(SUM(CASE WHEN payment_method = 'card' AND is_complimentary = 0 AND order_type = 'restaurant' THEN total_amount ELSE 0 END), 0) as restaurant_card_sales,
               COALESCE(SUM(CASE WHEN payment_method = 'upi' AND is_complimentary = 0 AND order_type = 'restaurant' THEN total_amount ELSE 0 END), 0) as restaurant_upi_sales,
               COALESCE(SUM(CASE WHEN payment_method = 'cash' AND is_complimentary = 0 AND order_type = 'room_service' THEN total_amount ELSE 0 END), 0) as room_cash_sales,
               COALESCE(SUM(CASE WHEN payment_method = 'card' AND is_complimentary = 0 AND order_type = 'room_service' THEN total_amount ELSE 0 END), 0) as room_card_sales,
               COALESCE(SUM(CASE WHEN payment_method = 'upi' AND is_complimentary = 0 AND order_type = 'room_service' THEN total_amount ELSE 0 END), 0) as room_upi_sales,
               COALESCE(SUM(CASE WHEN is_complimentary = 1 THEN total_amount ELSE 0 END), 0) as complimentary_sales,
               COALESCE(SUM(total_amount), 0) as total_sales
           FROM bills
           WHERE DATE(bill_date) = ?
       ''', (today,), fetch_one=True)

        sales_dict = dict(sales) if sales else {
            'restaurant_cash_sales': 0, 'restaurant_card_sales': 0, 'restaurant_upi_sales': 0,
            'room_cash_sales': 0, 'room_card_sales': 0, 'room_upi_sales': 0,
            'complimentary_sales': 0, 'total_sales': 0
        }

        restaurant_sales = (sales_dict.get('restaurant_cash_sales', 0) +
                            sales_dict.get('restaurant_card_sales', 0) +
                            sales_dict.get('restaurant_upi_sales', 0))

        room_service_sales = (sales_dict.get('room_cash_sales', 0) +
                              sales_dict.get('room_card_sales', 0) +
                              sales_dict.get('room_upi_sales', 0))

        self.db.execute_query('''
           UPDATE day_management
           SET is_open = 0, closed_at = ?, closed_by = ?, closing_cash = ?,
               total_sales = ?, restaurant_sales = ?, room_service_sales = ?,
               complimentary_sales = ?,
               cash_sales = ?,
               card_sales = ?,
               upi_sales = ?,
               status = 'closed'
           WHERE day_date = ?
       ''', (
            now, self.auth.current_user['id'], closing_cash,
            sales_dict['total_sales'], restaurant_sales, room_service_sales,
            sales_dict['complimentary_sales'],
            sales_dict.get('restaurant_cash_sales', 0) + sales_dict.get('room_cash_sales', 0),
            sales_dict.get('restaurant_card_sales', 0) + sales_dict.get('room_card_sales', 0),
            sales_dict.get('restaurant_upi_sales', 0) + sales_dict.get('room_upi_sales', 0),
            today
        ), commit=True)

        self.current_day = None
        return True

    def get_day_summary(self, day_date=None):
        """Get summary for a specific day."""
        if not day_date:
            day_date = date.today().isoformat()

        result = self.db.execute_query(
            'SELECT * FROM day_management WHERE day_date = ?',
            (day_date,),
            fetch_one=True
        )
        return dict(result) if result else None

    def get_open_days(self):
        """Get all open days."""
        results = self.db.execute_query(
            'SELECT * FROM day_management WHERE is_open = 1 ORDER BY day_date DESC',
            fetch_all=True
        )
        return [dict(r) for r in results] if results else []


# ==================== HOTEL & INVENTORY INTEGRATION ====================
class HotelIntegration:
    def __init__(self):
        self.hotel_conn = None
        self.inventory_conn = None
        self.connect_to_databases()

    def connect_to_databases(self):
        """Connect to hotel and inventory databases."""
        try:
            self.hotel_conn = sqlite3.connect('hotel_billing.db')
            self.hotel_conn.row_factory = sqlite3.Row
        except Exception as e:
            self.hotel_conn = None
            print(f"Hotel database not found: {e}")

        try:
            self.inventory_conn = sqlite3.connect('inventory.db')
            self.inventory_conn.row_factory = sqlite3.Row
        except Exception as e:
            self.inventory_conn = None
            print(f"Inventory database not found: {e}")

    def get_active_room_bookings(self):
        """Get active room bookings from hotel database."""
        if not self.hotel_conn:
            return []

        try:
            cursor = self.hotel_conn.cursor()
            cursor.execute('''
               SELECT b.id, b.room_id, r.room_number, b.guest_name, b.guest_phone, b.check_in_time
               FROM bookings b
               JOIN rooms r ON b.room_id = r.id
               WHERE b.status = 'active'
               ORDER BY b.check_in_time DESC
           ''')
            results = cursor.fetchall()
            return [dict(r) for r in results] if results else []
        except Exception as e:
            print(f"Error fetching room bookings: {e}")
            return []

    def add_room_service_to_hotel_bill(self, booking_id, room_id, room_number, items, total_amount, tax_amount):
        """Add room service items to hotel billing system's food orders."""
        if not self.hotel_conn:
            print("Hotel database not connected")
            return False

        try:
            cursor = self.hotel_conn.cursor()

            # First, check if the booking exists and is active
            cursor.execute('''
               SELECT id, status FROM bookings WHERE id = ? AND status = 'active'
           ''', (booking_id,))

            booking = cursor.fetchone()
            if not booking:
                print(f"Booking {booking_id} not found or not active")
                return False

            # Add each item as a food order in hotel billing
            for item in items:
                order_number = f"RS-{datetime.now().strftime('%Y%m%d%H%M%S')}-{item['id']}"

                cursor.execute('''
                   INSERT INTO food_orders
                   (booking_id, room_id, order_number, item_name, quantity,
                    unit_price, total_price, gst_percentage, status, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ''', (
                    booking_id,
                    room_id,
                    order_number,
                    item['item_name'],
                    item['quantity'],
                    item['unit_price'],
                    item['total_price'],
                    item['tax_percentage'],
                    'completed',
                    f"Room service order - {room_number}"
                ))

            self.hotel_conn.commit()
            print(f"Successfully added {len(items)} items to hotel bill for room {room_number}")
            return True

        except Exception as e:
            print(f"Error adding room service to hotel bill: {e}")
            if self.hotel_conn:
                self.hotel_conn.rollback()
            return False

    def deduct_inventory(self, item_name, quantity, order_id, reason="Hotel Restaurant Billing"):
        """Deduct quantity from inventory."""
        if not self.inventory_conn:
            print("Inventory database not connected")
            return False

        try:
            cursor = self.inventory_conn.cursor()

            # Find the item in inventory (case-insensitive search)
            cursor.execute('''
               SELECT id, quantity, name FROM inventory
               WHERE LOWER(name) = LOWER(?) OR LOWER(name) LIKE LOWER(?)
           ''', (item_name, f'%{item_name}%'))

            inventory_item = cursor.fetchone()

            if not inventory_item:
                print(f"Item '{item_name}' not found in inventory")
                return False

            current_qty = inventory_item['quantity']
            new_qty = max(0, current_qty - quantity)

            # Update inventory quantity
            cursor.execute('''
               UPDATE inventory SET quantity = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?
           ''', (new_qty, inventory_item['id']))

            # Log the deduction in inventory_history
            cursor.execute('''
               INSERT INTO inventory_history
               (item_id, user_id, action, old_quantity, new_quantity, reason)
               VALUES (?, ?, ?, ?, ?, ?)
           ''', (
                inventory_item['id'],
                1,  # System user ID
                'RESTAURANT_USAGE',
                current_qty,
                new_qty,
                reason
            ))

            # Also log in product_usage for easy viewing in the Product Usage tab
            cursor.execute('''
               INSERT INTO product_usage
               (item_id, user_id, quantity_taken, reason)
               VALUES (?, ?, ?, ?)
           ''', (
                inventory_item['id'],
                1,  # System user ID
                quantity,
                reason
            ))

            self.inventory_conn.commit()
            print(f"Deducted {quantity} of '{item_name}' from inventory for {reason}")
            return True

        except Exception as e:
            print(f"Error deducting inventory: {e}")
            if self.inventory_conn:
                self.inventory_conn.rollback()
            return False

    def get_booking_id_from_room(self, room_number):
        """Get active booking ID from room number."""
        if not self.hotel_conn:
            return None

        try:
            cursor = self.hotel_conn.cursor()
            cursor.execute('''
               SELECT b.id FROM bookings b
               JOIN rooms r ON b.room_id = r.id
               WHERE r.room_number = ? AND b.status = 'active'
               ORDER BY b.check_in_time DESC LIMIT 1
           ''', (room_number,))

            result = cursor.fetchone()
            return result['id'] if result else None
        except Exception as e:
            print(f"Error getting booking ID: {e}")
            return None


# ==================== RESTAURANT BILLING MANAGER ====================
class RestaurantBillingManager:
    def __init__(self, db: IntegratedDatabase, auth: Authentication, day_manager: DayManager):
        self.db = db
        self.auth = auth
        self.day_manager = day_manager
        self.hotel_integration = HotelIntegration()
        self.printer_queue = queue.Queue()

        # Initialize printer manager with separate database
        self.printer_manager = WindowsPrinterManager("printer_config.db")

        # Set default printers if not configured
        self.initialize_printers()

        self.start_printer_thread()
        self.gui = None  # Will be set by GUI

    def initialize_printers(self):
        """Initialize default printers for all types"""
        try:
            # Get available printers
            available = self.printer_manager.list_windows_printers()
            default = available[0] if available else "Microsoft XPS Document Writer"

            # Set default for each type if not already configured
            for printer_type, width in [('kitchen', 32), ('desk', 40), ('bill', 40)]:
                if not self.printer_manager.get_printer(printer_type):
                    self.printer_manager.set_printer(printer_type, default, width)
        except Exception as e:
            print(f"Error initializing printers: {e}")

    def start_printer_thread(self):
        """Start thread for handling printer jobs."""

        def printer_worker():
            while True:
                try:
                    job = self.printer_queue.get(timeout=1)
                    self._send_to_printer(job)
                except queue.Empty:
                    continue
                except Exception as e:
                    print(f"Printer error: {e}")

        thread = threading.Thread(target=printer_worker, daemon=True)
        thread.start()

    # ==================== USER MANAGEMENT ====================
    def get_all_users(self):
        """Get all users."""
        results = self.db.execute_query(
            'SELECT id, username, role, email, created_at FROM users ORDER BY username',
            fetch_all=True
        )
        return [dict(u) for u in results] if results else []

    def add_user(self, user_data):
        """Add a new user."""
        password_hash = self.db.hash_password(user_data['password'])
        self.db.execute_query('''
           INSERT INTO users (username, password_hash, role, email)
           VALUES (?, ?, ?, ?)
       ''', (
            user_data['username'],
            password_hash,
            user_data['role'],
            user_data.get('email', '')
        ), commit=True)
        return True

    def delete_user(self, user_id):
        """Delete a user."""
        if self.auth.current_user and user_id == self.auth.current_user['id']:
            raise ValueError("You cannot delete your own account")

        result = self.db.execute_query(
            'SELECT COUNT(*) as admin_count FROM users WHERE role = "admin"',
            fetch_one=True
        )
        admin_count = result['admin_count'] if result else 0

        if admin_count <= 1:
            user = self.db.execute_query(
                'SELECT role FROM users WHERE id = ?',
                (user_id,),
                fetch_one=True
            )
            if user and user['role'] == 'admin':
                raise ValueError("Cannot delete the last admin user")

        self.db.execute_query('DELETE FROM users WHERE id = ?', (user_id,), commit=True)
        return True

    # ==================== RESTAURANT MANAGEMENT ====================
    def get_all_restaurants(self):
        """Get all restaurants."""
        results = self.db.execute_query(
            'SELECT * FROM restaurants ORDER BY restaurant_code',
            fetch_all=True
        )
        return [dict(r) for r in results] if results else []

    def get_restaurant_by_id(self, rest_id):
        """Get restaurant by ID."""
        result = self.db.execute_query(
            'SELECT * FROM restaurants WHERE id = ?',
            (rest_id,),
            fetch_one=True
        )
        return dict(result) if result else None

    def get_restaurant_by_code(self, code):
        """Get restaurant by code."""
        result = self.db.execute_query(
            'SELECT * FROM restaurants WHERE restaurant_code = ?',
            (code,),
            fetch_one=True
        )
        return dict(result) if result else None

    def add_restaurant(self, data):
        """Add a new restaurant."""
        self.db.execute_query('''
           INSERT INTO restaurants (restaurant_code, restaurant_name, table_count)
           VALUES (?, ?, ?)
       ''', (data['code'], data['name'], data['table_count']), commit=True)

        result = self.db.execute_query(
            'SELECT id FROM restaurants WHERE restaurant_code = ?',
            (data['code'],),
            fetch_one=True
        )
        rest_id = result['id'] if result else None

        if rest_id:
            for i in range(1, data['table_count'] + 1):
                self.db.execute_query('''
                   INSERT INTO restaurant_tables (restaurant_id, table_number, status)
                   VALUES (?, ?, ?)
               ''', (rest_id, f"t{i}", 'available'), commit=True)

        return True

    def update_restaurant(self, rest_id, data):
        """Update restaurant."""
        self.db.execute_query('''
           UPDATE restaurants
           SET restaurant_name = ?, table_count = ?
           WHERE id = ?
       ''', (data['name'], data['table_count'], rest_id), commit=True)

        current_tables = self.db.execute_query(
            'SELECT COUNT(*) as count FROM restaurant_tables WHERE restaurant_id = ?',
            (rest_id,),
            fetch_one=True
        )
        current_count = current_tables['count'] if current_tables else 0

        if current_count < data['table_count']:
            for i in range(current_count + 1, data['table_count'] + 1):
                self.db.execute_query('''
                   INSERT INTO restaurant_tables (restaurant_id, table_number, status)
                   VALUES (?, ?, ?)
               ''', (rest_id, f"t{i}", 'available'), commit=True)

        return True

    def delete_restaurant(self, rest_id):
        """Delete restaurant."""
        active = self.db.execute_query('''
           SELECT COUNT(*) as count FROM orders
           WHERE restaurant_id = ? AND status = 'active'
       ''', (rest_id,), fetch_one=True)

        if active and active['count'] > 0:
            raise ValueError("Cannot delete restaurant with active orders")

        self.db.execute_query('DELETE FROM restaurant_tables WHERE restaurant_id = ?', (rest_id,), commit=True)
        self.db.execute_query('DELETE FROM restaurants WHERE id = ?', (rest_id,), commit=True)
        return True

    def get_tables_for_restaurant(self, rest_id):
        """Get all tables for a restaurant."""
        results = self.db.execute_query('''
           SELECT * FROM restaurant_tables
           WHERE restaurant_id = ?
           ORDER BY table_number
       ''', (rest_id,), fetch_all=True)
        return [dict(t) for t in results] if results else []

    def get_available_tables(self, rest_id):
        """Get available tables for a restaurant."""
        results = self.db.execute_query('''
           SELECT * FROM restaurant_tables
           WHERE restaurant_id = ? AND status = 'available'
           ORDER BY table_number
       ''', (rest_id,), fetch_all=True)
        return [dict(t) for t in results] if results else []

    def update_table_status(self, table_id, status, order_id=None):
        """Update table status."""
        if order_id:
            self.db.execute_query('''
               UPDATE restaurant_tables
               SET status = ?, current_order_id = ?
               WHERE id = ?
           ''', (status, order_id, table_id), commit=True)
        else:
            self.db.execute_query('''
               UPDATE restaurant_tables
               SET status = ?, current_order_id = NULL
               WHERE id = ?
           ''', (status, table_id), commit=True)

    # ==================== MENU MANAGEMENT ====================
    def get_all_categories(self):
        """Get all menu categories."""
        results = self.db.execute_query(
            'SELECT * FROM menu_categories ORDER BY category_name',
            fetch_all=True
        )
        return [dict(c) for c in results] if results else []

    def add_category(self, name, tax_exempt=False):
        """Add a new category."""
        self.db.execute_query('''
           INSERT INTO menu_categories (category_name, tax_exempt)
           VALUES (?, ?)
       ''', (name, 1 if tax_exempt else 0), commit=True)
        return True

    def get_all_menu_items(self, category_id=None):
        """Get all menu items."""
        if category_id:
            results = self.db.execute_query('''
               SELECT m.*, c.category_name, c.tax_exempt
               FROM menu_items m
               JOIN menu_categories c ON m.category_id = c.id
               WHERE m.category_id = ?
               ORDER BY m.item_name
           ''', (category_id,), fetch_all=True)
        else:
            results = self.db.execute_query('''
               SELECT m.*, c.category_name, c.tax_exempt
               FROM menu_items m
               JOIN menu_categories c ON m.category_id = c.id
               ORDER BY c.category_name, m.item_name
           ''', fetch_all=True)

        return [dict(m) for m in results] if results else []

    def get_menu_item_by_id(self, item_id):
        """Get menu item by ID."""
        result = self.db.execute_query('''
           SELECT m.*, c.category_name, c.tax_exempt
           FROM menu_items m
           JOIN menu_categories c ON m.category_id = c.id
           WHERE m.id = ?
       ''', (item_id,), fetch_one=True)
        return dict(result) if result else None

    def add_menu_item(self, data):
        """Add a new menu item."""
        self.db.execute_query('''
           INSERT INTO menu_items
           (item_name, category_id, price, tax_percentage, inventory_item_name, description, is_available)
           VALUES (?, ?, ?, ?, ?, ?, ?)
       ''', (
            data['item_name'],
            data['category_id'],
            data['price'],
            data['tax_percentage'],
            data.get('inventory_item_name', ''),
            data.get('description', ''),
            1
        ), commit=True)
        return True

    def update_menu_item(self, item_id, data):
        """Update menu item."""
        self.db.execute_query('''
           UPDATE menu_items
           SET item_name = ?, category_id = ?, price = ?,
               tax_percentage = ?, inventory_item_name = ?,
               description = ?, is_available = ?, updated_at = CURRENT_TIMESTAMP
           WHERE id = ?
       ''', (
            data['item_name'],
            data['category_id'],
            data['price'],
            data['tax_percentage'],
            data.get('inventory_item_name', ''),
            data.get('description', ''),
            1 if data.get('is_available', True) else 0,
            item_id
        ), commit=True)
        return True

    def delete_menu_item(self, item_id):
        """Delete menu item."""
        self.db.execute_query('DELETE FROM menu_items WHERE id = ?', (item_id,), commit=True)
        return True

    # ==================== ORDER MANAGEMENT ====================
    def generate_order_number(self):
        """Generate a unique order number."""
        today = date.today().strftime('%Y%m%d')
        result = self.db.execute_query('''
           SELECT COUNT(*) as count FROM orders WHERE order_number LIKE ?
       ''', (f"ORD-{today}%",), fetch_one=True)

        count = result['count'] if result else 0
        return f"ORD-{today}-{count + 1:04d}"

    def create_order(self, order_data):
        """Create a new order."""
        if not self.day_manager.check_today_status():
            raise ValueError("Please start the day first before taking orders")

        today = date.today().isoformat()
        order_number = self.generate_order_number()

        restaurant = self.get_restaurant_by_id(order_data['restaurant_id'])

        table_id = None
        table_number = None
        if order_data.get('table_id'):
            table_id = order_data['table_id']
            table_info = self.db.execute_query(
                'SELECT table_number FROM restaurant_tables WHERE id = ?',
                (table_id,),
                fetch_one=True
            )
            table_number = table_info['table_number'] if table_info else None

        # Use provided customer name or default to table/room number
        customer_name = order_data.get('customer_name', '')
        if not customer_name:
            if order_data.get('order_type') == 'restaurant' and table_number:
                customer_name = f"Table {table_number}"
            elif order_data.get('order_type') == 'room_service' and order_data.get('room_number'):
                customer_name = f"Room {order_data['room_number']}"
            else:
                customer_name = "Guest"

        self.db.execute_query('''
           INSERT INTO orders
           (order_number, customer_name, customer_phone, restaurant_id,
            table_id, table_number, room_id, room_number, order_type,
            order_date, created_by, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
       ''', (
            order_number,
            customer_name,
            order_data.get('customer_phone', ''),
            order_data['restaurant_id'],
            table_id,
            table_number,
            order_data.get('room_id'),
            order_data.get('room_number'),
            order_data.get('order_type', 'restaurant'),
            today,
            self.auth.current_user['id']
        ), commit=True)

        result = self.db.execute_query(
            'SELECT id FROM orders WHERE order_number = ?',
            (order_number,),
            fetch_one=True
        )
        order_id = result['id'] if result else None

        if table_id and order_data.get('order_type') == 'restaurant':
            self.update_table_status(table_id, 'occupied', order_id)

        return order_id, order_number

    def add_order_item(self, order_id, menu_item_id, quantity):
        """Add an item to an order."""
        menu_item = self.get_menu_item_by_id(menu_item_id)
        if not menu_item:
            raise ValueError("Menu item not found")

        total_price = menu_item['price'] * quantity

        self.db.execute_query('''
           INSERT INTO order_items
           (order_id, menu_item_id, item_name, quantity, unit_price,
            tax_percentage, total_price)
           VALUES (?, ?, ?, ?, ?, ?, ?)
       ''', (
            order_id,
            menu_item_id,
            menu_item['item_name'],
            quantity,
            menu_item['price'],
            menu_item['tax_percentage'],
            total_price
        ), commit=True)

        self.update_order_totals(order_id)
        self.queue_order_item_for_printing(order_id, menu_item['item_name'], quantity, menu_item['price'])

        return True

    def update_order_totals(self, order_id):
        """Update order totals and refresh display."""
        totals = self.db.execute_query('''
            SELECT 
                COALESCE(SUM(total_price), 0) as subtotal,
                COALESCE(SUM(total_price * tax_percentage / 100), 0) as tax
            FROM order_items 
            WHERE order_id = ?
        ''', (order_id,), fetch_one=True)

        subtotal = totals['subtotal'] if totals else 0
        tax = totals['tax'] if totals else 0
        total = subtotal + tax

        self.db.execute_query('''
            UPDATE orders 
            SET total_amount = ?, tax_amount = ?
            WHERE id = ?
        ''', (total, tax, order_id), commit=True)

        # Refresh the display in the order popup if it exists
        if hasattr(self, 'gui') and self.gui:
            try:
                # Try to refresh the order items display
                if hasattr(self.gui, 'load_order_items_popup'):
                    self.gui.load_order_items_popup(order_id)

                # Also try to refresh the totals in the order popup
                if hasattr(self.gui, 'current_popup') and self.gui.current_popup:
                    # Look for the totals frame and update it
                    for widget in self.gui.current_popup.winfo_children():
                        if isinstance(widget, tk.Frame):
                            for child in widget.winfo_children():
                                if isinstance(child, tk.Frame) and hasattr(child, 'winfo_children'):
                                    for label in child.winfo_children():
                                        if isinstance(label, tk.Label) and 'Subtotal:' in str(label.cget('text')):
                                            # This is a bit hacky but works - the actual update happens via load_order_items_popup
                                            pass
            except Exception as e:
                print(f"Error refreshing GUI: {e}")

        return total, tax

    def queue_order_item_for_printing(self, order_id, item_name, quantity, price):
        """Queue ONLY the newly added order item for printing to kitchen and desk."""
        order = self.get_order_by_id(order_id)

        # Kitchen slip - ONLY this item
        kitchen_content = f"""
   {'-' * 32}
   {'KITCHEN ORDER':^32}
   {'-' * 32}
   Order: {order['order_number']}
   Tbl/Rm: {order.get('table_number') or order.get('room_number', 'N/A')}
   Time: {datetime.now().strftime('%H:%M:%S')}
   {'-' * 32}
   NEW ITEM ADDED:
   {'-' * 32}
   Item: {item_name[:20]}
   Qty:  {quantity}
   {'-' * 32}
   """

        # Desk slip - ONLY this item
        desk_content = f"""
   {'-' * 32}
   {'DESK ORDER':^32}
   {'-' * 32}
   Order: {order['order_number']}
   Cust: {order['customer_name'][:15]}
   Tbl/Rm: {order.get('table_number') or order.get('room_number', 'N/A')}
   Time: {datetime.now().strftime('%H:%M:%S')}
   {'-' * 32}
   NEW ITEM ADDED:
   {'-' * 32}
   Item: {item_name[:20]}
   Qty:  {quantity}
   Price: ${price * quantity:.2f}
   {'-' * 32}
   """

        # Put in queue for background printing
        self.printer_queue.put({
            'printer': 'kitchen',
            'content': kitchen_content
        })
        self.printer_queue.put({
            'printer': 'desk',
            'content': desk_content
        })

        # Update printed status
        self.db.execute_query('''
           UPDATE order_items
           SET printed_to_kitchen = 1, printed_to_desk = 1
           WHERE order_id = ? AND item_name = ? AND created_at = (
               SELECT MAX(created_at) FROM order_items WHERE order_id = ? AND item_name = ?
           )
       ''', (order_id, item_name, order_id, item_name), commit=True)

    def get_order_by_id(self, order_id):
        """Get order by ID."""
        result = self.db.execute_query('''
           SELECT o.*, r.restaurant_name
           FROM orders o
           LEFT JOIN restaurants r ON o.restaurant_id = r.id
           WHERE o.id = ?
       ''', (order_id,), fetch_one=True)
        return dict(result) if result else None

    def get_order_items(self, order_id):
        """Get items for an order."""
        results = self.db.execute_query('''
           SELECT * FROM order_items
           WHERE order_id = ?
           ORDER BY created_at
       ''', (order_id,), fetch_all=True)
        return [dict(i) for i in results] if results else []

    def get_active_orders(self, restaurant_id=None):
        """Get all active orders."""
        if restaurant_id:
            results = self.db.execute_query('''
               SELECT o.*, r.restaurant_name
               FROM orders o
               LEFT JOIN restaurants r ON o.restaurant_id = r.id
               WHERE o.status = 'active' AND o.restaurant_id = ?
               ORDER BY o.order_time DESC
           ''', (restaurant_id,), fetch_all=True)
        else:
            results = self.db.execute_query('''
               SELECT o.*, r.restaurant_name
               FROM orders o
               LEFT JOIN restaurants r ON o.restaurant_id = r.id
               WHERE o.status = 'active'
               ORDER BY o.order_time DESC
           ''', fetch_all=True)

        return [dict(o) for o in results] if results else []

    def update_order_item(self, item_id, quantity):
        """Update order item quantity."""
        item = self.db.execute_query(
            'SELECT * FROM order_items WHERE id = ?',
            (item_id,),
            fetch_one=True
        )
        if not item:
            raise ValueError("Order item not found")

        item = dict(item)
        new_total = item['unit_price'] * quantity

        self.db.execute_query('''
           UPDATE order_items
           SET quantity = ?, total_price = ?
           WHERE id = ?
       ''', (quantity, new_total, item_id), commit=True)

        self.update_order_totals(item['order_id'])
        return True

    def delete_order_item(self, item_id):
        """Delete order item."""
        item = self.db.execute_query(
            'SELECT order_id FROM order_items WHERE id = ?',
            (item_id,),
            fetch_one=True
        )
        if item:
            order_id = item['order_id']
            self.db.execute_query('DELETE FROM order_items WHERE id = ?', (item_id,), commit=True)
            self.update_order_totals(order_id)
        return True

    def cancel_order(self, order_id):
        """Cancel an order."""
        order = self.get_order_by_id(order_id)
        if not order:
            raise ValueError("Order not found")

        if order['table_id'] and order['order_type'] == 'restaurant':
            self.update_table_status(order['table_id'], 'available')

        self.db.execute_query('''
           UPDATE orders SET status = 'cancelled' WHERE id = ?
       ''', (order_id,), commit=True)

        return True

    # ==================== ACTIVE BOOKINGS (ROOM SERVICE) ====================
    def get_active_room_bookings(self):
        """Get active room bookings from hotel database."""
        return self.hotel_integration.get_active_room_bookings()

    # ==================== BILL GENERATION WITH INTEGRATION ====================
    def generate_bill(self, order_id, payment_data):
        """Generate bill for an order with full integration - supports pending/paid"""
        order = self.get_order_by_id(order_id)
        if not order:
            raise ValueError("Order not found")

        items = self.get_order_items(order_id)

        today = date.today().isoformat()
        day = self.db.execute_query(
            'SELECT id FROM day_management WHERE day_date = ?',
            (today,),
            fetch_one=True
        )
        day_id = day['id'] if day else None

        bill_number = f"BILL-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        is_complimentary = payment_data.get('is_complimentary', False)
        payment_method = payment_data.get('payment_method', 'cash')
        discount_percentage = payment_data.get('discount_percentage', 0.0)
        payment_status = payment_data.get('payment_status', 'paid')  # 'paid' or 'pending'

        # Get phone number from payment data or order
        customer_phone = payment_data.get('customer_phone', '') or order.get('customer_phone', '')

        subtotal = order['total_amount'] - order['tax_amount']
        original_total = order['total_amount']

        # Calculate discount
        discount_amount = 0
        if discount_percentage > 0 and not is_complimentary:
            discount_amount = original_total * (discount_percentage / 100)

        final_total = original_total - discount_amount if not is_complimentary else 0

        # Insert bill
        self.db.execute_query('''
           INSERT INTO bills
           (bill_number, order_id, customer_name, customer_phone, restaurant_name,
            table_number, room_number, order_type, bill_date, bill_time,
            subtotal, tax_amount, total_amount, payment_method, payment_status,
            is_complimentary, discount_percentage, discount_amount,
            cash_received, change_returned, created_by, day_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
       ''', (
            bill_number,
            order_id,
            order['customer_name'],
            customer_phone,
            order.get('restaurant_name', ''),
            order.get('table_number'),
            order.get('room_number'),
            order['order_type'],
            today,
            subtotal,
            order['tax_amount'],
            final_total,
            payment_method,
            payment_status,  # Store payment status
            1 if is_complimentary else 0,
            discount_percentage,
            discount_amount,
            payment_data.get('cash_received', 0),
            payment_data.get('change_returned', 0),
            self.auth.current_user['id'],
            day_id
        ), commit=True)

        # Update order with phone number if it was provided in bill
        if customer_phone and not order.get('customer_phone'):
            self.db.execute_query('''
               UPDATE orders
               SET customer_phone = ?
               WHERE id = ?
           ''', (customer_phone, order_id), commit=True)

        # Update order status
        self.db.execute_query('''
           UPDATE orders
           SET status = 'completed', payment_status = ?,
               is_complimentary = ?, payment_method = ?, completed_at = CURRENT_TIMESTAMP
           WHERE id = ?
       ''', (payment_status, 1 if is_complimentary else 0, payment_method, order_id), commit=True)

        if order['table_id'] and order['order_type'] == 'restaurant':
            self.update_table_status(order['table_id'], 'available')

        # If payment is pending, create pending bill record
        if payment_status == 'pending':
            pending_data = payment_data.get('pending_data', {})
            self.db.execute_query('''
               INSERT INTO pending_bills
               (bill_id, customer_name, customer_phone, reference_name,
                reference_phone, reference_notes, pending_amount, original_total, status)
               VALUES ((SELECT id FROM bills WHERE bill_number = ?), ?, ?, ?, ?, ?, ?, ?, 'pending')
           ''', (
                bill_number,
                pending_data.get('customer_name', order['customer_name']),
                pending_data.get('customer_phone', ''),
                pending_data.get('reference_name', ''),
                pending_data.get('reference_phone', ''),
                pending_data.get('reference_notes', ''),
                final_total,
                original_total
            ), commit=True)

        # Deduct from inventory
        for item in items:
            reason = f"Restaurant - Order #{order['order_number']}"
            self.hotel_integration.deduct_inventory(
                item['item_name'],
                item['quantity'],
                order_id,
                reason
            )

        # Add room service to hotel bill
        if order['order_type'] == 'room_service' and order.get('room_number'):
            booking_id = self.hotel_integration.get_booking_id_from_room(order['room_number'])

            if booking_id:
                success = self.hotel_integration.add_room_service_to_hotel_bill(
                    booking_id,
                    booking_id,
                    order['room_number'],
                    items,
                    original_total,
                    order['tax_amount']
                )

                if success:
                    print(f"Room service added to hotel bill for room {order['room_number']}")
                else:
                    print(f"Failed to add room service to hotel bill for room {order['room_number']}")

        # Print COMPLETE bill with ALL items
        self.print_complete_bill(order, items, bill_number, is_complimentary, payment_method, final_total,
                                 discount_percentage, discount_amount, payment_status)

        return bill_number

    def get_unprinted_items(self, order_id):
        """Get items that haven't been printed to kitchen/desk."""
        results = self.db.execute_query('''
           SELECT * FROM order_items
           WHERE order_id = ? AND (printed_to_kitchen = 0 OR printed_to_desk = 0)
           ORDER BY created_at
       ''', (order_id,), fetch_all=True)

        return [dict(i) for i in results] if results else []

    def settle_bill(self, bill_id, settlement_data):
        """Settle a bill with adjusted amount - record difference as discount."""
        try:
            # Get the bill
            bill = self.db.execute_query(
                'SELECT * FROM bills WHERE id = ?',
                (bill_id,),
                fetch_one=True
            )

            if not bill:
                raise ValueError("Bill not found")

            bill = dict(bill)

            # Get settlement details
            settled_amount = settlement_data.get('settled_amount', 0)
            payment_method = settlement_data.get('payment_method', 'cash')
            notes = settlement_data.get('notes', '')

            # Get customer info from settlement data (optional)
            customer_name = settlement_data.get('customer_name', bill['customer_name'])
            customer_phone = settlement_data.get('customer_phone', bill.get('customer_phone', ''))

            original_total = bill['total_amount']

            # Calculate discount if settled amount is less than original
            discount_amount = 0
            discount_percentage = 0

            if settled_amount < original_total:
                discount_amount = original_total - settled_amount
                discount_percentage = (discount_amount / original_total) * 100

            # Update the bill with customer info from settlement
            self.db.execute_query('''
               UPDATE bills
               SET total_amount = ?,
                   discount_percentage = ?,
                   discount_amount = ?,
                   payment_method = ?,
                   payment_status = 'settled',
                   cash_received = ?,
                   change_returned = 0,
                   settlement_notes = ?,
                   settled_at = CURRENT_TIMESTAMP,
                   customer_name = ?,
                   customer_phone = ?
               WHERE id = ?
           ''', (
                settled_amount,
                discount_percentage,
                discount_amount,
                payment_method,
                settled_amount,
                notes,
                customer_name,
                customer_phone,
                bill_id
            ), commit=True)

            # Update the associated order if needed - SAFELY check if columns exist first
            if bill['order_id']:
                try:
                    # First check if the columns exist in orders table
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("PRAGMA table_info(orders)")
                    order_columns = [col[1] for col in cursor.fetchall()]
                    self.db.return_connection(conn)

                    # Build update query dynamically based on existing columns
                    update_fields = []
                    params = []

                    update_fields.append("total_amount = ?")
                    params.append(settled_amount)

                    update_fields.append("payment_status = 'settled'")
                    update_fields.append("payment_method = ?")
                    params.append(payment_method)

                    # Update customer name/phone in order if provided
                    if customer_name and customer_name != bill['customer_name']:
                        update_fields.append("customer_name = ?")
                        params.append(customer_name)

                    if customer_phone:
                        update_fields.append("customer_phone = ?")
                        params.append(customer_phone)

                    # Only add discount fields if they exist
                    if 'discount_amount' in order_columns:
                        update_fields.append("discount_amount = ?")
                        params.append(discount_amount)

                    if 'discount_percentage' in order_columns:
                        update_fields.append("discount_percentage = ?")
                        params.append(discount_percentage)

                    params.append(bill['order_id'])

                    update_query = f'''
                       UPDATE orders
                       SET {', '.join(update_fields)}
                       WHERE id = ?
                   '''

                    self.db.execute_query(update_query, params, commit=True)

                except Exception as e:
                    print(f"Warning: Could not update order with settlement info: {e}")
                    # Continue even if order update fails - bill is already updated

            # Log the settlement
            print(
                f"Bill #{bill['bill_number']} settled: Original ₹{original_total:.2f} → Settled ₹{settled_amount:.2f}")

            return True

        except Exception as e:
            print(f"Error settling bill: {e}")
            raise e

    # Add this new method to the RestaurantBillingManager class
    def add_order_item(self, order_id, menu_item_id, quantity):
        """Add an item to an order and track if it's newly added."""
        menu_item = self.get_menu_item_by_id(menu_item_id)
        if not menu_item:
            raise ValueError("Menu item not found")

        total_price = menu_item['price'] * quantity

        # Insert the item and get its ID
        cursor = self.db.execute_query('''
            INSERT INTO order_items 
            (order_id, menu_item_id, item_name, quantity, unit_price, 
             tax_percentage, total_price, printed_to_kitchen, printed_to_desk)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)
        ''', (
            order_id,
            menu_item_id,
            menu_item['item_name'],
            quantity,
            menu_item['price'],
            menu_item['tax_percentage'],
            total_price
        ), commit=True)

        # Get the last inserted ID (this item)
        result = self.db.execute_query('SELECT last_insert_rowid() as id', fetch_one=True)
        new_item_id = result['id'] if result else None

        self.update_order_totals(order_id)

        # DO NOT auto-print when adding items from Menu Items tab
        # User will manually click "Print New Items" button in Order Items tab
        # if new_item_id:
        #     self.print_new_order_item(order_id, new_item_id)

        return True

    def get_desk_content(self, order_id):
        """Get formatted desk content for printing."""
        order = self.get_order_by_id(order_id)
        items = self.get_order_items(order_id)

        if not order or not items:
            return None

        settings = self.db.get_hotel_settings()
        line_width = 40

        content = f"""
   {'=' * line_width}
   {settings['hotel_name'][:line_width]:^{line_width}}
   {'DESK ORDER':^40}
   {'=' * line_width}
   Order: {order['order_number']}
   Customer: {order['customer_name'][:20]}
   Table: {order.get('table_number') or order.get('room_number', 'N/A')}
   Time: {datetime.now().strftime('%H:%M:%S')}
   {'-' * line_width}
   ITEM                QTY     AMOUNT
   {'-' * line_width}"""

        subtotal = 0
        for item in items:
            name = item['item_name'][:20]
            qty = item['quantity']
            amt = item['total_price']
            content += f"\n{name:<20} {qty:>3}   ₹{amt:>7.2f}"
            subtotal += amt

        tax = sum(i['unit_price'] * i['quantity'] * i['tax_percentage'] / 100 for i in items)
        total = subtotal + tax

        content += f"""
   {'-' * line_width}
   Subtotal:               ₹{subtotal:>9.2f}
   Tax:                    ₹{tax:>9.2f}
   TOTAL:                  ₹{total:>9.2f}
   {'=' * line_width}
   """

        return content

    def print_new_order_item(self, order_id, item_id):
        """Print ONLY the newly added order item to kitchen and desk"""
        order = self.get_order_by_id(order_id)
        item = self.db.execute_query('SELECT * FROM order_items WHERE id = ?', (item_id,), fetch_one=True)

        if not order or not item:
            return

        item = dict(item)

        # Create order data for kitchen
        kitchen_data = {
            'order_number': order['order_number'],
            'table': order.get('table_number') or order.get('room_number', 'N/A'),
            'items': [{
                'name': item['item_name'],
                'qty': item['quantity'],
                'price': item['unit_price']
            }]
        }

        # Create order data for desk
        desk_data = {
            'order_number': order['order_number'],
            'table': order.get('table_number') or order.get('room_number', 'N/A'),
            'items': [{
                'name': item['item_name'],
                'qty': item['quantity'],
                'price': item['unit_price']
            }]
        }

        # Put in queue for background printing
        self.printer_queue.put({
            'printer': 'kitchen',
            'content': '',
            'order_number': order['order_number'],
            'table': order.get('table_number') or order.get('room_number', 'N/A'),
            'items': kitchen_data['items']
        })

        self.printer_queue.put({
            'printer': 'desk',
            'content': '',
            'order_number': order['order_number'],
            'table': order.get('table_number') or order.get('room_number', 'N/A'),
            'items': desk_data['items']
        })

        # Update printed status
        self.db.execute_query('''
           UPDATE order_items
           SET printed_to_kitchen = 1, printed_to_desk = 1
           WHERE id = ?
       ''', (item_id,), commit=True)

    def get_new_order_items(self, order_id, last_printed_time=None):
        """Get only newly added items since last print."""
        if last_printed_time:
            results = self.db.execute_query('''
               SELECT * FROM order_items
               WHERE order_id = ? AND created_at > ?
               ORDER BY created_at
           ''', (order_id, last_printed_time), fetch_all=True)
        else:
            # If no last printed time, get items that haven't been printed
            results = self.db.execute_query('''
               SELECT * FROM order_items
               WHERE order_id = ? AND printed_to_kitchen = 0
               ORDER BY created_at
           ''', (order_id,), fetch_all=True)

        return [dict(i) for i in results] if results else []

    def print_order_by_type(self, order_id, print_type='all'):
        """Print order items based on type: 'all' or 'unprinted'"""
        order = self.get_order_by_id(order_id)

        if print_type == 'all':
            items = self.get_order_items(order_id)
            title = "FULL ORDER"
        else:  # 'unprinted'
            items = [i for i in self.get_order_items(order_id) if not i.get('printed_to_kitchen', 0)]
            title = "UNPRINTED ITEMS"

        if not items:
            if hasattr(self, 'gui') and self.gui:
                self.gui.show_warning("No items to print")
            return

        # Create items list for printer
        print_items = []
        for item in items:
            print_items.append({
                'name': item['item_name'],
                'qty': item['quantity'],
                'price': item['unit_price']
            })

        # Kitchen order
        kitchen_data = {
            'order_number': order['order_number'],
            'table': order.get('table_number') or order.get('room_number', 'N/A'),
            'items': print_items
        }

        # Desk order
        desk_data = {
            'order_number': order['order_number'],
            'table': order.get('table_number') or order.get('room_number', 'N/A'),
            'items': print_items
        }

        # Send to printer queue
        self.printer_queue.put({
            'printer': 'kitchen',
            'content': '',
            'order_number': order['order_number'],
            'table': order.get('table_number') or order.get('room_number', 'N/A'),
            'items': print_items
        })

        self.printer_queue.put({
            'printer': 'desk',
            'content': '',
            'order_number': order['order_number'],
            'table': order.get('table_number') or order.get('room_number', 'N/A'),
            'items': print_items
        })

        # Mark items as printed
        for item in items:
            self.db.execute_query('''
               UPDATE order_items
               SET printed_to_kitchen = 1, printed_to_desk = 1
               WHERE id = ?
           ''', (item['id'],), commit=True)

    def print_complete_bill(self, order, items, bill_number, is_complimentary, payment_method, total,
                            discount_percentage=0, discount_amount=0, payment_status='paid'):
        """Print COMPLETE bill with ALL items"""

        # Create items list for printer
        bill_items = []
        for item in items:
            bill_items.append({
                'name': item['item_name'],
                'qty': item['quantity'],
                'price': item['unit_price']
            })

        # Get hotel settings
        settings = self.db.get_hotel_settings()

        # Create bill data
        bill_data = {
            'bill_number': bill_number,
            'order_number': order['order_number'],
            'table': order.get('table_number') or order.get('room_number', 'N/A'),
            'items': bill_items,
            'tax': order['tax_amount'],
            'settings': settings
        }

        # Send to printer queue
        self.printer_queue.put({
            'printer': 'bill',
            'content': '',
            'order_number': order['order_number'],
            'table': order.get('table_number') or order.get('room_number', 'N/A'),
            'items': bill_items,
            'bill_number': bill_number,
            'tax': order['tax_amount'],
            'settings': settings
        })

    def get_pending_bills(self, status='pending'):
        """Get all pending bills"""
        results = self.db.execute_query('''
           SELECT pb.*, b.bill_number, b.customer_name as bill_customer,
                  b.total_amount, b.payment_method, b.created_by,
                  u.username as created_by_name
           FROM pending_bills pb
           JOIN bills b ON pb.bill_id = b.id
           LEFT JOIN users u ON b.created_by = u.id
           WHERE pb.status = ?
           ORDER BY pb.created_at DESC
       ''', (status,), fetch_all=True)

        return [dict(pb) for pb in results] if results else []

    def mark_pending_as_paid(self, pending_id, payment_data):
        """Mark a pending bill as paid and settle it"""
        try:
            # Get pending bill
            pending = self.db.execute_query('''
               SELECT pb.*, b.bill_number, b.order_id
               FROM pending_bills pb
               JOIN bills b ON pb.bill_id = b.id
               WHERE pb.id = ?
           ''', (pending_id,), fetch_one=True)

            if not pending:
                raise ValueError("Pending bill not found")

            pending = dict(pending)

            # Update pending bill status
            self.db.execute_query('''
               UPDATE pending_bills
               SET status = 'paid',
                   converted_to_paid_at = CURRENT_TIMESTAMP,
                   converted_by = ?
               WHERE id = ?
           ''', (self.auth.current_user['id'], pending_id), commit=True)

            # Update bill payment status
            self.db.execute_query('''
               UPDATE bills
               SET payment_status = 'paid',
                   payment_method = ?,
                   cash_received = ?,
                   change_returned = 0
               WHERE id = ?
           ''', (
                payment_data.get('payment_method', 'cash'),
                payment_data.get('amount_paid', pending['pending_amount']),
                pending['bill_id']
            ), commit=True)

            # Now settle the bill with the paid amount
            self.settle_bill(pending['bill_id'], {
                'settled_amount': payment_data.get('amount_paid', pending['pending_amount']),
                'payment_method': payment_data.get('payment_method', 'cash'),
                'notes': f"Converted from pending bill - {payment_data.get('notes', '')}"
            })

            return True

        except Exception as e:
            print(f"Error marking pending as paid: {e}")
            raise e

    def get_pending_bill_details(self, pending_id):
        """Get detailed information about a pending bill"""
        result = self.db.execute_query('''
           SELECT pb.*, b.bill_number, b.order_id, b.customer_name,
                  b.table_number, b.room_number, b.order_type,
                  b.bill_date, b.subtotal, b.tax_amount, b.total_amount,
                  b.payment_method as original_payment_method,
                  o.order_number, o.order_time as order_created_at,
                  u.username as created_by_name
           FROM pending_bills pb
           JOIN bills b ON pb.bill_id = b.id
           JOIN orders o ON b.order_id = o.id
           LEFT JOIN users u ON b.created_by = u.id
           WHERE pb.id = ?
       ''', (pending_id,), fetch_one=True)

        return dict(result) if result else None

    def get_bills(self, day_date=None, complimentary_only=False):
        """Get bills for a specific day - includes payment status"""
        if not day_date:
            day_date = date.today().isoformat()

        if complimentary_only:
            results = self.db.execute_query('''
               SELECT b.*, u.username as created_by_name
               FROM bills b
               LEFT JOIN users u ON b.created_by = u.id
               WHERE DATE(b.bill_date) = ? AND b.is_complimentary = 1
               ORDER BY b.bill_time DESC
           ''', (day_date,), fetch_all=True)
        else:
            results = self.db.execute_query('''
               SELECT b.*, u.username as created_by_name
               FROM bills b
               LEFT JOIN users u ON b.created_by = u.id
               WHERE DATE(b.bill_date) = ?
               ORDER BY b.bill_time DESC
           ''', (day_date,), fetch_all=True)

        return [dict(b) for b in results] if results else []

    def get_bills(self, day_date=None, complimentary_only=False):
        """Get bills for a specific day - includes payment status"""
        if not day_date:
            day_date = date.today().isoformat()

        if complimentary_only:
            results = self.db.execute_query('''
               SELECT b.*, u.username as created_by_name
               FROM bills b
               LEFT JOIN users u ON b.created_by = u.id
               WHERE DATE(b.bill_date) = ? AND b.is_complimentary = 1
               ORDER BY b.bill_time DESC
           ''', (day_date,), fetch_all=True)
        else:
            results = self.db.execute_query('''
               SELECT b.*, u.username as created_by_name
               FROM bills b
               LEFT JOIN users u ON b.created_by = u.id
               WHERE DATE(b.bill_date) = ?
               ORDER BY b.bill_time DESC
           ''', (day_date,), fetch_all=True)

        return [dict(b) for b in results] if results else []

    def get_all_bills(self, start_date=None, end_date=None, bill_number=None):
        """Get all bills within date range or by bill number - includes pending status"""
        if bill_number:
            results = self.db.execute_query('''
               SELECT b.*, u.username as created_by_name
               FROM bills b
               LEFT JOIN users u ON b.created_by = u.id
               WHERE b.bill_number = ?
               ORDER BY b.bill_time DESC
           ''', (bill_number,), fetch_all=True)
        elif start_date and end_date:
            results = self.db.execute_query('''
               SELECT b.*, u.username as created_by_name
               FROM bills b
               LEFT JOIN users u ON b.created_by = u.id
               WHERE DATE(b.bill_date) BETWEEN ? AND ?
               ORDER BY b.bill_time DESC
           ''', (start_date, end_date), fetch_all=True)
        else:
            if not start_date:
                start_date = (date.today() - timedelta(days=30)).isoformat()
            if not end_date:
                end_date = date.today().isoformat()
            results = self.db.execute_query('''
               SELECT b.*, u.username as created_by_name
               FROM bills b
               LEFT JOIN users u ON b.created_by = u.id
               WHERE DATE(b.bill_date) BETWEEN ? AND ?
               ORDER BY b.bill_time DESC
           ''', (start_date, end_date), fetch_all=True)

        return [dict(b) for b in results] if results else []

    def get_bills_by_type(self, order_type, start_date=None, end_date=None):
        """Get bills by order type."""
        if not start_date:
            start_date = (date.today() - timedelta(days=30)).isoformat()
        if not end_date:
            end_date = date.today().isoformat()

        results = self.db.execute_query('''
           SELECT b.*, u.username as created_by_name
           FROM bills b
           LEFT JOIN users u ON b.created_by = u.id
           WHERE DATE(b.bill_date) BETWEEN ? AND ? AND b.order_type = ?
           ORDER BY b.bill_time DESC
       ''', (start_date, end_date, order_type), fetch_all=True)

        return [dict(b) for b in results] if results else []

    # ==================== REPORTS ====================
    def get_daily_sales_report(self, day_date=None):
        """Get daily sales report with settled amounts only."""
        try:
            if not day_date:
                day_date = date.today().isoformat()

            day_summary = self.day_manager.get_day_summary(day_date)

            # Get bills with full customer data
            bills = self.get_bills(day_date)

            # Get payment breakdown using settled amounts (actual amount received)
            payment_result = self.db.execute_query('''
               SELECT
                   COALESCE(SUM(CASE WHEN payment_method = 'cash' AND is_complimentary = 0 AND order_type = 'restaurant' THEN total_amount ELSE 0 END), 0) as restaurant_cash,
                   COALESCE(SUM(CASE WHEN payment_method = 'card' AND is_complimentary = 0 AND order_type = 'restaurant' THEN total_amount ELSE 0 END), 0) as restaurant_card,
                   COALESCE(SUM(CASE WHEN payment_method = 'upi' AND is_complimentary = 0 AND order_type = 'restaurant' THEN total_amount ELSE 0 END), 0) as restaurant_upi,
                   COALESCE(SUM(CASE WHEN payment_method = 'cash' AND is_complimentary = 0 AND order_type = 'room_service' THEN total_amount ELSE 0 END), 0) as room_cash,
                   COALESCE(SUM(CASE WHEN payment_method = 'card' AND is_complimentary = 0 AND order_type = 'room_service' THEN total_amount ELSE 0 END), 0) as room_card,
                   COALESCE(SUM(CASE WHEN payment_method = 'upi' AND is_complimentary = 0 AND order_type = 'room_service' THEN total_amount ELSE 0 END), 0) as room_upi,
                   COALESCE(SUM(CASE WHEN is_complimentary = 1 THEN total_amount ELSE 0 END), 0) as complimentary_total,
                   COUNT(CASE WHEN is_complimentary = 0 AND (settled_at IS NOT NULL OR payment_status = 'paid') THEN 1 END) as paid_bills,
                   COUNT(CASE WHEN is_complimentary = 1 THEN 1 END) as comp_bills,
                   COUNT(CASE WHEN order_type = 'restaurant' AND is_complimentary = 0 AND (settled_at IS NOT NULL OR payment_status = 'paid') THEN 1 END) as restaurant_bills,
                   COUNT(CASE WHEN order_type = 'room_service' AND is_complimentary = 0 AND (settled_at IS NOT NULL OR payment_status = 'paid') THEN 1 END) as room_bills,
                   COALESCE(SUM(CASE WHEN settled_at IS NOT NULL THEN discount_amount ELSE 0 END), 0) as total_discounts_given
               FROM bills
               WHERE DATE(bill_date) = ?
           ''', (day_date,), fetch_one=True)

            # Convert to dictionary with safe defaults
            pd = {}
            if payment_result:
                pd = dict(payment_result)
            else:
                pd = {
                    'restaurant_cash': 0, 'restaurant_card': 0, 'restaurant_upi': 0,
                    'room_cash': 0, 'room_card': 0, 'room_upi': 0,
                    'complimentary_total': 0, 'paid_bills': 0, 'comp_bills': 0,
                    'restaurant_bills': 0, 'room_bills': 0, 'total_discounts_given': 0
                }

            restaurant_total = float(pd.get('restaurant_cash', 0)) + float(pd.get('restaurant_card', 0)) + float(
                pd.get('restaurant_upi', 0))
            room_total = float(pd.get('room_cash', 0)) + float(pd.get('room_card', 0)) + float(pd.get('room_upi', 0))

            # Get settlement summary
            settlement_summary = self.db.execute_query('''
               SELECT
                   COUNT(*) as total_settled_bills,
                   COALESCE(SUM(total_amount), 0) as total_settled_amount,
                   COALESCE(SUM(discount_amount), 0) as total_discount_from_settlements,
                   COALESCE(AVG(discount_percentage), 0) as avg_discount_percentage
               FROM bills
               WHERE DATE(bill_date) = ? AND settled_at IS NOT NULL
           ''', (day_date,), fetch_one=True)

            settlement_dict = dict(settlement_summary) if settlement_summary else {
                'total_settled_bills': 0,
                'total_settled_amount': 0,
                'total_discount_from_settlements': 0,
                'avg_discount_percentage': 0
            }

            report = {
                'date': day_date,
                'day_summary': day_summary,
                'total_bills': len(bills) if bills else 0,
                'restaurant_bills': int(pd.get('restaurant_bills', 0)),
                'room_bills': int(pd.get('room_bills', 0)),
                'restaurant_cash': float(pd.get('restaurant_cash', 0)),
                'restaurant_card': float(pd.get('restaurant_card', 0)),
                'restaurant_upi': float(pd.get('restaurant_upi', 0)),
                'room_cash': float(pd.get('room_cash', 0)),
                'room_card': float(pd.get('room_card', 0)),
                'room_upi': float(pd.get('room_upi', 0)),
                'restaurant_total': restaurant_total,
                'room_total': room_total,
                'complimentary_total': float(pd.get('complimentary_total', 0)),
                'paid_bills': int(pd.get('paid_bills', 0)),
                'comp_bills': int(pd.get('comp_bills', 0)),
                'grand_total': restaurant_total + room_total,
                'total_discounts_given': float(pd.get('total_discounts_given', 0)),
                'settlement_summary': settlement_dict,
                'bills': bills if bills else []  # Bills now include full customer data
            }

            return report

        except Exception as e:
            print(f"Error generating report: {e}")
            import traceback
            traceback.print_exc()
            return {
                'date': day_date if day_date else date.today().isoformat(),
                'day_summary': None,
                'total_bills': 0,
                'restaurant_bills': 0,
                'room_bills': 0,
                'restaurant_cash': 0,
                'restaurant_card': 0,
                'restaurant_upi': 0,
                'room_cash': 0,
                'room_card': 0,
                'room_upi': 0,
                'restaurant_total': 0,
                'room_total': 0,
                'complimentary_total': 0,
                'paid_bills': 0,
                'comp_bills': 0,
                'grand_total': 0,
                'total_discounts_given': 0,
                'settlement_summary': {
                    'total_settled_bills': 0,
                    'total_settled_amount': 0,
                    'total_discount_from_settlements': 0,
                    'avg_discount_percentage': 0
                },
                'bills': []
            }

    def get_sales_summary(self, start_date=None, end_date=None):
        """Get comprehensive sales summary with settlement details."""
        try:
            if not start_date:
                start_date = (date.today() - timedelta(days=30)).isoformat()
            if not end_date:
                end_date = date.today().isoformat()

            # Overall sales summary
            summary = self.db.execute_query('''
               SELECT
                   COUNT(*) as total_bills,
                   COALESCE(SUM(CASE WHEN is_complimentary = 0 THEN total_amount ELSE 0 END), 0) as total_sales,
                   COALESCE(SUM(CASE WHEN is_complimentary = 1 THEN total_amount ELSE 0 END), 0) as total_complimentary,
                   COALESCE(SUM(discount_amount), 0) as total_discounts,
                   COALESCE(AVG(CASE WHEN discount_amount > 0 THEN discount_percentage ELSE NULL END), 0) as avg_discount_percentage,
                   COUNT(CASE WHEN settled_at IS NOT NULL THEN 1 END) as settled_bills_count,
                   COALESCE(SUM(CASE WHEN settled_at IS NOT NULL THEN total_amount ELSE 0 END), 0) as settled_amount_total,
                   COALESCE(SUM(CASE WHEN settled_at IS NOT NULL THEN discount_amount ELSE 0 END), 0) as settlement_discounts
               FROM bills
               WHERE DATE(bill_date) BETWEEN ? AND ?
           ''', (start_date, end_date), fetch_one=True)

            # Payment method breakdown
            payment_breakdown = self.db.execute_query('''
               SELECT
                   payment_method,
                   COUNT(*) as bill_count,
                   COALESCE(SUM(total_amount), 0) as total_amount,
                   COALESCE(SUM(discount_amount), 0) as discounts
               FROM bills
               WHERE DATE(bill_date) BETWEEN ? AND ? AND is_complimentary = 0
               GROUP BY payment_method
               ORDER BY total_amount DESC
           ''', (start_date, end_date), fetch_all=True)

            # Daily breakdown
            daily_breakdown = self.db.execute_query('''
               SELECT
                   DATE(bill_date) as sale_date,
                   COUNT(*) as bills_count,
                   COALESCE(SUM(CASE WHEN is_complimentary = 0 THEN total_amount ELSE 0 END), 0) as total_sales,
                   COALESCE(SUM(CASE WHEN is_complimentary = 1 THEN total_amount ELSE 0 END), 0) as complimentary,
                   COALESCE(SUM(discount_amount), 0) as discounts,
                   COUNT(CASE WHEN settled_at IS NOT NULL THEN 1 END) as settled_count,
                   COALESCE(SUM(CASE WHEN settled_at IS NOT NULL THEN total_amount ELSE 0 END), 0) as settled_amount
               FROM bills
               WHERE DATE(bill_date) BETWEEN ? AND ?
               GROUP BY DATE(bill_date)
               ORDER BY sale_date DESC
           ''', (start_date, end_date), fetch_all=True)

            # Settlement trends
            settlement_trends = self.db.execute_query('''
               SELECT
                   DATE(settled_at) as settlement_date,
                   COUNT(*) as settlements_count,
                   COALESCE(SUM(total_amount), 0) as settled_amount,
                   COALESCE(SUM(discount_amount), 0) as discounts_given
               FROM bills
               WHERE settled_at IS NOT NULL AND DATE(settled_at) BETWEEN ? AND ?
               GROUP BY DATE(settled_at)
               ORDER BY settlement_date DESC
           ''', (start_date, end_date), fetch_all=True)

            summary_dict = dict(summary) if summary else {
                'total_bills': 0,
                'total_sales': 0,
                'total_complimentary': 0,
                'total_discounts': 0,
                'avg_discount_percentage': 0,
                'settled_bills_count': 0,
                'settled_amount_total': 0,
                'settlement_discounts': 0
            }

            return {
                'period': {'start': start_date, 'end': end_date},
                'summary': summary_dict,
                'payment_breakdown': [dict(p) for p in payment_breakdown] if payment_breakdown else [],
                'daily_breakdown': [dict(d) for d in daily_breakdown] if daily_breakdown else [],
                'settlement_trends': [dict(s) for s in settlement_trends] if settlement_trends else []
            }

        except Exception as e:
            print(f"Error getting sales summary: {e}")
            return {
                'period': {'start': start_date, 'end': end_date},
                'summary': {
                    'total_bills': 0,
                    'total_sales': 0,
                    'total_complimentary': 0,
                    'total_discounts': 0,
                    'avg_discount_percentage': 0,
                    'settled_bills_count': 0,
                    'settled_amount_total': 0,
                    'settlement_discounts': 0
                },
                'payment_breakdown': [],
                'daily_breakdown': [],
                'settlement_trends': []
            }

    def verify_cash_balance(self, day_date=None, actual_cash=None):
        """Verify cash balance (restaurant cash only)."""
        report = self.get_daily_sales_report(day_date)
        day_summary = report['day_summary']

        if not day_summary:
            return {'match': False, 'message': 'Day not found'}

        # Only include restaurant cash sales in expected cash
        expected_cash = report['restaurant_cash'] + (day_summary.get('opening_cash', 0) if day_summary else 0)

        if actual_cash is not None:
            match = abs(actual_cash - expected_cash) < 0.01
            return {
                'match': match,
                'expected': expected_cash,
                'actual': actual_cash,
                'difference': actual_cash - expected_cash,
                'message': 'Balanced' if match else f"Difference: ₹{actual_cash - expected_cash:.2f}"
            }

        return {
            'match': True,
            'expected': expected_cash,
            'actual': None,
            'difference': 0,
            'message': f"Expected cash: ₹{expected_cash:.2f}"
        }

    # ==================== PRINTER MANAGEMENT ====================
    def get_printer_settings(self, printer_type=None):
        """Get printer settings."""
        if printer_type:
            results = self.db.execute_query('''
               SELECT * FROM printer_settings
               WHERE printer_type = ? AND enabled = 1
               ORDER BY is_default DESC, printer_name
           ''', (printer_type,), fetch_all=True)
        else:
            results = self.db.execute_query('''
               SELECT * FROM printer_settings
               WHERE enabled = 1
               ORDER BY printer_type, is_default DESC, printer_name
           ''', fetch_all=True)

        return [dict(p) for p in results] if results else []

    def get_default_printer(self, printer_type):
        """Get default printer for a type."""
        result = self.db.execute_query('''
           SELECT * FROM printer_settings
           WHERE printer_type = ? AND enabled = 1 AND is_default = 1
           LIMIT 1
       ''', (printer_type,), fetch_one=True)

        if result:
            return dict(result)

        # If no default, get first enabled
        result = self.db.execute_query('''
           SELECT * FROM printer_settings
           WHERE printer_type = ? AND enabled = 1
           LIMIT 1
       ''', (printer_type,), fetch_one=True)

        return dict(result) if result else None

    def add_printer(self, printer_data):
        """Add a new printer."""
        # If this is set as default, remove default from others of same type
        if printer_data.get('is_default'):
            self.db.execute_query('''
               UPDATE printer_settings
               SET is_default = 0
               WHERE printer_type = ?
           ''', (printer_data['printer_type'],), commit=True)

        self.db.execute_query('''
           INSERT INTO printer_settings
           (printer_name, printer_type, printer_port, printer_ip, is_default, paper_width)
           VALUES (?, ?, ?, ?, ?, ?)
       ''', (
            printer_data['printer_name'],
            printer_data['printer_type'],
            printer_data.get('printer_port', ''),
            printer_data.get('printer_ip', ''),
            1 if printer_data.get('is_default') else 0,
            printer_data.get('paper_width', 40)
        ), commit=True)
        return True

    def update_printer(self, printer_id, printer_data):
        """Update printer settings."""
        # If this is set as default, remove default from others of same type
        if printer_data.get('is_default'):
            self.db.execute_query('''
               UPDATE printer_settings
               SET is_default = 0
               WHERE printer_type = ? AND id != ?
           ''', (printer_data['printer_type'], printer_id), commit=True)

        self.db.execute_query('''
           UPDATE printer_settings
           SET printer_name = ?, printer_type = ?, printer_port = ?,
               printer_ip = ?, is_default = ?, paper_width = ?, enabled = ?
           WHERE id = ?
       ''', (
            printer_data['printer_name'],
            printer_data['printer_type'],
            printer_data.get('printer_port', ''),
            printer_data.get('printer_ip', ''),
            1 if printer_data.get('is_default') else 0,
            printer_data.get('paper_width', 40),
            1 if printer_data.get('enabled', True) else 0,
            printer_id
        ), commit=True)
        return True

    def delete_printer(self, printer_id):
        """Delete a printer."""
        self.db.execute_query('DELETE FROM printer_settings WHERE id = ?', (printer_id,), commit=True)
        return True

    def test_printer_connection(self, printer_data):
        """Test printer connection."""
        try:
            printer_type = printer_data.get('printer_type')
            printer_port = printer_data.get('printer_port')
            printer_ip = printer_data.get('printer_ip')

            # Simulate printer test - in real implementation, you'd actually connect to printer
            test_content = f"""
   {'=' * 40}
   {'PRINTER TEST':^40}
   {'=' * 40}
   Printer: {printer_data['printer_name']}
   Type: {printer_type}
   Time: {datetime.now().strftime('%H:%M:%S')}
   {'=' * 40}
   If you can read this, the printer is working!
   {'=' * 40}
           """

            # Try to print test page
            success = self.direct_print(printer_data, test_content)

            if success:
                # Log test job
                self.db.execute_query('''
                   INSERT INTO print_jobs
                   (job_type, document_type, content, status, printer_name)
                   VALUES (?, 'test', ?, 'printed', ?)
               ''', (printer_type, test_content, printer_data['printer_name']), commit=True)

            return success

        except Exception as e:
            print(f"Printer test failed: {e}")
            return False

    def direct_print(self, printer, content, reference_id=None, doc_type=None):
        """Directly print to specified printer."""
        try:
            # In a real implementation, you would:
            # 1. For USB/LPT printers: Use os.startfile(port) or win32print
            # 2. For network printers: Use socket connection or IPP
            # 3. For thermal printers: Send ESC/POS commands

            printer_type = printer.get('printer_type')
            printer_port = printer.get('printer_port')
            printer_ip = printer.get('printer_ip')
            paper_width = printer.get('paper_width', 40)

            # Format content for thermal printer (if needed)
            formatted_content = self.format_for_thermal(content, paper_width)

            # Simulate printing (replace with actual printer communication)
            print(f"\n{'=' * paper_width}")
            print(f"PRINTING TO {printer['printer_name'].upper()}")
            print(f"{'=' * paper_width}")
            print(formatted_content)
            print(f"{'=' * paper_width}\n")

            # Log print job
            self.db.execute_query('''
               INSERT INTO print_jobs
               (job_type, document_type, reference_id, content, status, printer_name)
               VALUES (?, ?, ?, ?, 'printed', ?)
           ''', (printer_type, doc_type, reference_id, content[:500], printer['printer_name']), commit=True)

            return True

        except Exception as e:
            error_msg = str(e)
            print(f"Print error: {error_msg}")

            # Log failed job
            if reference_id:
                self.db.execute_query('''
                   INSERT INTO print_jobs
                   (job_type, document_type, reference_id, content, status, printer_name, error_message)
                   VALUES (?, ?, ?, ?, 'failed', ?, ?)
               ''', (printer.get('printer_type'), doc_type, reference_id, content[:500],
                     printer.get('printer_name'), error_msg), commit=True)

            return False

    def format_for_thermal(self, content, width=40):
        """Format content for thermal printer."""
        lines = content.split('\n')
        formatted_lines = []

        for line in lines:
            # Remove extra indentation
            stripped = line.strip()
            if stripped:
                # Truncate to width
                if len(stripped) > width:
                    formatted_lines.append(stripped[:width])
                else:
                    formatted_lines.append(stripped)
            else:
                formatted_lines.append('')

        return '\n'.join(formatted_lines)

    def print_document(self, doc_type, reference_id, printer_type=None):
        """Print a document directly."""
        try:
            # Get printer
            if printer_type:
                printer = self.get_default_printer(printer_type)
            else:
                # Use bill printer as default for documents
                printer = self.get_default_printer('bill')

            if not printer:
                if self.gui:
                    self.gui.show_error(f"No printer configured for {printer_type or 'bill'}")
                return False

            # Get document content based on type
            if doc_type == 'bill':
                content = self.get_bill_content(reference_id)
            elif doc_type == 'kitchen':
                content = self.get_kitchen_content(reference_id)
            elif doc_type == 'order' or doc_type == 'desk':
                content = self.get_desk_content(reference_id)
            elif doc_type == 'report':
                content = self.get_report_content(reference_id)
            else:
                raise ValueError(f"Unknown document type: {doc_type}")

            if not content:
                raise ValueError(f"Could not generate content for {doc_type} #{reference_id}")

            # Print directly
            success = self.direct_print(printer, content, reference_id, doc_type)

            if success and self.gui:
                self.gui.show_info(f"✅ Document sent to {printer['printer_name']}")

            return success

        except Exception as e:
            print(f"Error printing document: {e}")
            if self.gui:
                self.gui.show_error(f"Print error: {str(e)}")
            return False

    def get_bill_content(self, bill_id):
        """Get formatted bill content for printing."""
        bill = self.db.execute_query('''
           SELECT b.*, o.order_number, o.customer_name, o.table_number, o.room_number
           FROM bills b
           JOIN orders o ON b.order_id = o.id
           WHERE b.id = ?
       ''', (bill_id,), fetch_one=True)

        if not bill:
            return None

        bill = dict(bill)
        items = self.get_order_items(bill['order_id'])

        settings = self.db.get_hotel_settings()

        # Format bill content
        line_width = 40
        content = f"""
   {'=' * line_width}
   {settings['hotel_name'][:line_width]:^{line_width}}
   {'=' * line_width}
   Bill: {bill['bill_number']}
   Date: {datetime.now().strftime('%d/%m/%y %H:%M')}
   Cust: {bill['customer_name'][:20]}
   {'=' * line_width}
   ITEM                QTY     AMOUNT
   {'-' * line_width}"""

        for item in items:
            name = item['item_name'][:20]
            qty = item['quantity']
            amt = item['total_price']
            content += f"\n{name:<20} {qty:>3}   ₹{amt:>7.2f}"

        content += f"""
   {'-' * line_width}
   Subtotal:               ₹{bill['subtotal']:>9.2f}
   Tax:                    ₹{bill['tax_amount']:>9.2f}
   TOTAL:                  ₹{bill['total_amount']:>9.2f}
   {'=' * line_width}
   Thank you!
   {'=' * line_width}"""

        return content

    def get_kitchen_content(self, order_id):
        """Get formatted kitchen content for printing."""
        order = self.get_order_by_id(order_id)
        items = self.get_order_items(order_id)

        if not order or not items:
            return None

        line_width = 32
        content = f"""
   {'=' * line_width}
   {'KITCHEN ORDER':^32}
   {'=' * line_width}
   Order: {order['order_number']}
   Table: {order.get('table_number') or order.get('room_number', 'N/A')}
   Time: {datetime.now().strftime('%H:%M')}
   {'-' * line_width}"""

        for item in items:
            content += f"\n{item['item_name'][:20]:<20} x{item['quantity']}"

        content += f"\n{'-' * line_width}"
        content += f"\nTotal Items: {len(items)}"
        content += f"\n{'=' * line_width}"

        return content

    # ==================== ADMIN BILL EDITING ====================
    def get_bill_for_editing(self, bill_id):
        """Get complete bill details for editing including all items."""
        try:
            # Get bill details with full data
            bill = self.db.execute_query('''
               SELECT b.*, o.order_number, o.order_type, o.table_number, o.room_number,
                      o.customer_name as order_customer_name, o.customer_phone as order_customer_phone
               FROM bills b
               LEFT JOIN orders o ON b.order_id = o.id
               WHERE b.id = ?
           ''', (bill_id,), fetch_one=True)

            if not bill:
                raise ValueError("Bill not found")

            bill = dict(bill)

            # Get all items for this bill
            items = self.db.execute_query('''
               SELECT oi.*
               FROM order_items oi
               WHERE oi.order_id = ?
               ORDER BY oi.created_at
           ''', (bill['order_id'],), fetch_all=True)

            bill['items'] = [dict(item) for item in items] if items else []

            return bill

        except Exception as e:
            print(f"Error getting bill for editing: {e}")
            raise e

    def get_all_menu_items_for_edit(self):
        """Get all menu items for item replacement in editing."""
        return self.get_all_menu_items()

    def update_bill_after_edit(self, bill_id, edit_data, user_id, reason=""):
        """Update bill after admin edits with full audit trail."""
        conn = None
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()

            # Start transaction
            cursor.execute("BEGIN TRANSACTION")

            # Get current bill data for comparison
            cursor.execute('SELECT * FROM bills WHERE id = ?', (bill_id,))
            current_bill = dict(cursor.fetchone())

            # Update bill table
            update_fields = []
            params = []

            # Track changes for history
            changes = []

            # Customer information
            if 'customer_name' in edit_data and edit_data['customer_name'] != current_bill['customer_name']:
                update_fields.append("customer_name = ?")
                params.append(edit_data['customer_name'])
                changes.append({
                    'field': 'customer_name',
                    'old': current_bill['customer_name'],
                    'new': edit_data['customer_name']
                })

            if 'customer_phone' in edit_data and edit_data['customer_phone'] != current_bill.get('customer_phone', ''):
                update_fields.append("customer_phone = ?")
                params.append(edit_data['customer_phone'])
                changes.append({
                    'field': 'customer_phone',
                    'old': current_bill.get('customer_phone', ''),
                    'new': edit_data['customer_phone']
                })

            # Table/Room information
            if 'table_number' in edit_data and edit_data['table_number'] != current_bill.get('table_number', ''):
                update_fields.append("table_number = ?")
                params.append(edit_data['table_number'])
                changes.append({
                    'field': 'table_number',
                    'old': current_bill.get('table_number', ''),
                    'new': edit_data['table_number']
                })

            if 'room_number' in edit_data and edit_data['room_number'] != current_bill.get('room_number', ''):
                update_fields.append("room_number = ?")
                params.append(edit_data['room_number'])
                changes.append({
                    'field': 'room_number',
                    'old': current_bill.get('room_number', ''),
                    'new': edit_data['room_number']
                })

            # Financial information
            if 'subtotal' in edit_data and edit_data['subtotal'] != current_bill['subtotal']:
                update_fields.append("subtotal = ?")
                params.append(edit_data['subtotal'])
                changes.append({
                    'field': 'subtotal',
                    'old': current_bill['subtotal'],
                    'new': edit_data['subtotal']
                })

            if 'tax_amount' in edit_data and edit_data['tax_amount'] != current_bill['tax_amount']:
                update_fields.append("tax_amount = ?")
                params.append(edit_data['tax_amount'])
                changes.append({
                    'field': 'tax_amount',
                    'old': current_bill['tax_amount'],
                    'new': edit_data['tax_amount']
                })

            if 'total_amount' in edit_data and edit_data['total_amount'] != current_bill['total_amount']:
                update_fields.append("total_amount = ?")
                params.append(edit_data['total_amount'])
                changes.append({
                    'field': 'total_amount',
                    'old': current_bill['total_amount'],
                    'new': edit_data['total_amount']
                })

            # Discount information
            if 'discount_percentage' in edit_data and edit_data['discount_percentage'] != current_bill.get(
                    'discount_percentage', 0):
                update_fields.append("discount_percentage = ?")
                params.append(edit_data['discount_percentage'])
                changes.append({
                    'field': 'discount_percentage',
                    'old': current_bill.get('discount_percentage', 0),
                    'new': edit_data['discount_percentage']
                })

            if 'discount_amount' in edit_data and edit_data['discount_amount'] != current_bill.get('discount_amount',
                                                                                                   0):
                update_fields.append("discount_amount = ?")
                params.append(edit_data['discount_amount'])
                changes.append({
                    'field': 'discount_amount',
                    'old': current_bill.get('discount_amount', 0),
                    'new': edit_data['discount_amount']
                })

            # Payment information
            if 'payment_method' in edit_data and edit_data['payment_method'] != current_bill['payment_method']:
                update_fields.append("payment_method = ?")
                params.append(edit_data['payment_method'])
                changes.append({
                    'field': 'payment_method',
                    'old': current_bill['payment_method'],
                    'new': edit_data['payment_method']
                })

            if 'payment_status' in edit_data and edit_data['payment_status'] != current_bill['payment_status']:
                update_fields.append("payment_status = ?")
                params.append(edit_data['payment_status'])
                changes.append({
                    'field': 'payment_status',
                    'old': current_bill['payment_status'],
                    'new': edit_data['payment_status']
                })

            # Apply updates to bills table
            if update_fields:
                params.append(bill_id)
                cursor.execute(f'''
                   UPDATE bills
                   SET {', '.join(update_fields)}
                   WHERE id = ?
               ''', params)

            # Update order items if provided
            if 'items' in edit_data and edit_data['items']:
                # First, delete existing items
                cursor.execute('DELETE FROM order_items WHERE order_id = ?', (current_bill['order_id'],))

                # Insert updated items
                for item in edit_data['items']:
                    cursor.execute('''
                       INSERT INTO order_items
                       (order_id, menu_item_id, item_name, quantity, unit_price,
                        tax_percentage, total_price, printed_to_kitchen, printed_to_desk)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1)
                   ''', (
                        current_bill['order_id'],
                        item.get('menu_item_id', 0),
                        item['item_name'],
                        item['quantity'],
                        item['unit_price'],
                        item.get('tax_percentage', 5.0),
                        item['total_price']
                    ))

                changes.append({
                    'field': 'items',
                    'old': 'Original items',
                    'new': f'Updated to {len(edit_data["items"])} items'
                })

            # Update orders table
            order_update_fields = []
            order_params = []

            if 'customer_name' in edit_data:
                order_update_fields.append("customer_name = ?")
                order_params.append(edit_data['customer_name'])

            if 'customer_phone' in edit_data:
                order_update_fields.append("customer_phone = ?")
                order_params.append(edit_data['customer_phone'])

            if 'table_number' in edit_data:
                order_update_fields.append("table_number = ?")
                order_params.append(edit_data['table_number'])

            if 'room_number' in edit_data:
                order_update_fields.append("room_number = ?")
                order_params.append(edit_data['room_number'])

            if 'total_amount' in edit_data:
                order_update_fields.append("total_amount = ?")
                order_params.append(edit_data['total_amount'])

            if 'tax_amount' in edit_data:
                order_update_fields.append("tax_amount = ?")
                order_params.append(edit_data['tax_amount'])

            if order_update_fields:
                order_params.append(current_bill['order_id'])
                cursor.execute(f'''
                   UPDATE orders
                   SET {', '.join(order_update_fields)}
                   WHERE id = ?
               ''', order_params)

            # Save edit history
            for change in changes:
                cursor.execute('''
                   INSERT INTO bill_edit_history
                   (bill_id, edited_by, field_name, old_value, new_value, reason)
                   VALUES (?, ?, ?, ?, ?, ?)
               ''', (
                    bill_id,
                    user_id,
                    change['field'],
                    str(change['old']),
                    str(change['new']),
                    reason
                ))

            # Commit transaction
            conn.commit()

            return True

        except Exception as e:
            if conn:
                conn.rollback()
            print(f"Error updating bill: {e}")
            raise e
        finally:
            if conn:
                self.db.return_connection(conn)

    def get_bill_edit_history(self, bill_id):
        """Get edit history for a bill."""
        results = self.db.execute_query('''
           SELECT eh.*, u.username as editor_name
           FROM bill_edit_history eh
           LEFT JOIN users u ON eh.edited_by = u.id
           WHERE eh.bill_id = ?
           ORDER BY eh.edited_at DESC
       ''', (bill_id,), fetch_all=True)

        return [dict(r) for r in results] if results else []

    def _send_to_printer(self, job):
        """Send job to printer with preview then auto-print"""
        try:
            printer_type = job['printer']  # 'kitchen', 'desk', or 'bill'

            # Get printer info
            printer_info = self.printer_manager.get_printer(printer_type)
            if not printer_info:
                print(f"No printer configured for {printer_type}")
                return

            printer_name = printer_info["name"]
            if not printer_name:
                if PRINTER_AVAILABLE:
                    printer_name = win32print.GetDefaultPrinter()
                else:
                    printer_name = "No Printer"

            # Format content based on printer type
            if printer_type == 'kitchen':
                content = self._format_kitchen_slip(job)
            elif printer_type == 'desk':
                content = self._format_desk_slip(job)
            elif printer_type == 'bill':
                content = self._format_bill(job)
            else:
                content = job.get('content', '')

            # Format for thermal printer width
            width = printer_info.get('width', 40)
            formatted = self.printer_manager.format_receipt(content, width)

            # Show preview in a dialog
            self._show_print_preview_and_print(formatted, printer_type, printer_name)

        except Exception as e:
            print(f"Printer error: {e}")
            traceback.print_exc()

    def _show_print_preview_and_print(self, content, printer_type, printer_name):
        """Show preview dialog and automatically print after 2 seconds"""
        preview_dialog = tk.Toplevel(self.gui.root if self.gui else None)
        preview_dialog.title(f"{printer_type.upper()} Print Preview")
        preview_dialog.geometry("500x600")
        preview_dialog.configure(bg='white')

        # Title
        title_label = tk.Label(preview_dialog,
                              text=f"📄 {printer_type.upper()} PREVIEW",
                              font=('Segoe UI', 14, 'bold'),
                              bg='#2e86c1', fg='white', pady=10)
        title_label.pack(fill=tk.X)

        # Printer info
        info_label = tk.Label(preview_dialog,
                             text=f"Printer: {printer_name}",
                             font=('Segoe UI', 10),
                             bg='white', fg='#555')
        info_label.pack(pady=5)

        # Preview text area
        text_frame = tk.Frame(preview_dialog, bg='white')
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        text_widget = tk.Text(text_frame, font=('Courier New', 9),
                             bg='#f5f5f5', fg='black',
                             relief=tk.SOLID, borderwidth=1)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(text_frame, command=text_widget.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.config(yscrollcommand=scrollbar.set)

        # Insert content
        text_widget.insert('1.0', content)
        text_widget.config(state=tk.DISABLED)

        # Status label
        status_label = tk.Label(preview_dialog,
                               text="⏳ Printing in 2 seconds...",
                               font=('Segoe UI', 11, 'bold'),
                               bg='white', fg='#e67e22')
        status_label.pack(pady=10)

        # Auto-print after 2 seconds
        def auto_print():
            try:
                status_label.config(text="🖨️ Sending to printer...", fg='#2e86c1')
                preview_dialog.update()

                if PRINTER_AVAILABLE:
                    # Send to printer
                    hprinter = win32print.OpenPrinter(printer_name)
                    job_id = win32print.StartDocPrinter(hprinter, 1, ("POS Receipt", None, "RAW"))
                    win32print.StartPagePrinter(hprinter)

                    win32print.WritePrinter(
                        hprinter,
                        content.encode('cp437', 'ignore')
                    )

                    win32print.EndPagePrinter(hprinter)
                    win32print.EndDocPrinter(hprinter)
                    win32print.ClosePrinter(hprinter)

                    status_label.config(text="✅ Printed successfully! (Closing in 3s)", fg='#27ae60')
                    print(f"✅ Printed successfully to {printer_type} on {printer_name}")

                    # Close dialog after 3 seconds
                    preview_dialog.after(3000, preview_dialog.destroy)
                else:
                    status_label.config(text="ℹ️ PREVIEW ONLY - No printer attached (Click Close to exit)", fg='#e67e22')
                    print(f"ℹ️ Preview shown for {printer_type} - Printer module not available")
                    # Don't auto-close when no printer - let user review and close manually

            except Exception as e:
                status_label.config(text=f"❌ Print failed: {str(e)[:40]}", fg='#c0392b')
                print(f"❌ Printer error: {e}")
                # Don't auto-close on error - let user see the error

        # Schedule auto-print
        preview_dialog.after(2000, auto_print)

        # Close button
        close_btn = tk.Button(preview_dialog, text="✕ CLOSE",
                             font=('Segoe UI', 10, 'bold'),
                             bg='#95a5a6', fg='white',
                             command=preview_dialog.destroy,
                             padx=20, pady=8)
        close_btn.pack(pady=10)

    def _format_kitchen_slip(self, job):
        """Format kitchen slip"""
        lines = []
        lines.append("=" * 32)
        lines.append("KITCHEN ORDER".center(32))
        lines.append("=" * 32)
        lines.append(f"Order: {job.get('order_number', 'N/A')}")
        lines.append(f"Table: {job.get('table', 'N/A')}")
        lines.append(f"Time: {datetime.now().strftime('%H:%M:%S')}")
        lines.append("-" * 32)

        for item in job.get('items', []):
            lines.append(f"{item['name'][:20]:<20} x{item['qty']:>2}")

        lines.append("-" * 32)
        lines.append("=" * 32)
        return "\n".join(lines)

    def _format_desk_slip(self, job):
        """Format desk slip"""
        lines = []
        lines.append("=" * 40)
        lines.append("DESK ORDER".center(40))
        lines.append("=" * 40)
        lines.append(f"Order: {job.get('order_number', 'N/A')}")
        lines.append(f"Table: {job.get('table', 'N/A')}")
        lines.append(f"Time: {datetime.now().strftime('%H:%M:%S')}")
        lines.append("-" * 40)
        lines.append(f"{'Item':<25} {'Qty':>5} {'Price':>8}")
        lines.append("-" * 40)

        total = 0
        for item in job.get('items', []):
            line_total = item['qty'] * item['price']
            lines.append(f"{item['name'][:25]:<25} {item['qty']:>5}  ₹{line_total:>8.2f}")
            total += line_total

        lines.append("-" * 40)
        lines.append(f"{'TOTAL:':<35} ₹{total:>8.2f}")
        lines.append("=" * 40)
        return "\n".join(lines)

    def _format_bill(self, job):
        """Format complete bill"""
        settings = job.get('settings', {})
        lines = []
        lines.append("=" * 40)
        lines.append(f"{settings.get('hotel_name', 'RESTAURANT'):^40}")
        lines.append("=" * 40)
        lines.append(f"Bill No: {job.get('bill_number', 'N/A')}")
        lines.append(f"Order: {job.get('order_number', 'N/A')}")
        lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"Table: {job.get('table', 'N/A')}")
        lines.append("-" * 40)
        lines.append(f"{'Item':<20} {'Qty':>3} {'Amt':>7}")
        lines.append("-" * 40)

        total = 0
        for item in job.get('items', []):
            name = item['name'][:20]
            qty = item['qty']
            price = item['price']
            line_total = qty * price
            total += line_total
            lines.append(f"{name:<20} {qty:>3} ₹{line_total:>6.2f}")

        lines.append("-" * 40)
        lines.append(f"{'Subtotal:':<25} ₹{total:>6.2f}")

        tax = job.get('tax', 0)
        if tax > 0:
            lines.append(f"{'Tax:':<25} ₹{tax:>6.2f}")
            total += tax

        lines.append("=" * 40)
        lines.append(f"{'TOTAL:':<25} ₹{total:>6.2f}")
        lines.append("=" * 40)
        lines.append("Thank You!".center(40))
        lines.append("Visit Again!".center(40))
        lines.append("=" * 40)

        return "\n".join(lines)


# ==================== GUI APPLICATION WITH UPDATED UI ====================
class IntegratedRestaurantAppGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("The Evaani Hotel - Integrated Restaurant Billing System")

        # Start in full screen mode
        self.root.state('zoomed')

        # Get screen dimensions and set geometry
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_width}x{screen_height}")

        self.db = IntegratedDatabase()
        self.auth = Authentication(self.db)
        self.day_manager = DayManager(self.db, self.auth)
        self.restaurant = RestaurantBillingManager(self.db, self.auth, self.day_manager)
        self.restaurant.gui = self  # Set GUI reference

        self.setup_styles()

        self.login_frame = None
        self.main_frame = None
        self.current_popup = None  # Track active popup
        self.active_popups = {}  # Store active popup windows

        self.create_login_frame()

        # Bind Enter key globally for forms
        self.root.bind('<Return>', self.handle_enter_key)

    def setup_styles(self):
        """Setup modern styles for the application."""
        style = ttk.Style()
        style.theme_use('clam')

        # Modern color scheme for luxury hotel
        primary_color = '#6a4334'  # Dark brown
        secondary_color = '#2e86c1'  # Light blue
        accent_color = '#c0392b'  # Red
        success_color = '#27ae60'  # Green
        warning_color = '#f39c12'  # Orange
        light_bg = '#f8f9fa'
        dark_bg = '#6a4334'
        grey_color = '#6c757d'  # Medium grey
        dark_grey = '#5a6268'  # Dark grey for hover

        # Configure styles
        style.configure('TFrame', background=light_bg)
        style.configure('TLabel', background=light_bg, font=('Segoe UI', 10))  # Reduced from 11 to 10
        style.configure('Header.TLabel', background=primary_color, foreground='white',
                        font=('Segoe UI', 16, 'bold'), padding=12)  # Reduced from 18 to 16
        style.configure('Title.TLabel', font=('Segoe UI', 14, 'bold'),
                        foreground=primary_color)  # Reduced from 16 to 14
        style.configure('Subtitle.TLabel', font=('Segoe UI', 12, 'bold'),
                        foreground=secondary_color)  # Reduced from 14 to 12

        # Configure buttons with grey color scheme and black text
        style.configure('TButton', font=('Segoe UI', 10, 'bold'), padding=8)  # Reduced padding
        style.configure('Primary.TButton', background=grey_color, foreground='black')
        style.map('Primary.TButton', background=[('active', dark_grey)], foreground=[('active', 'black')])
        style.configure('Success.TButton', background=grey_color, foreground='black')
        style.map('Success.TButton', background=[('active', dark_grey)], foreground=[('active', 'black')])
        style.configure('Danger.TButton', background=grey_color, foreground='black')
        style.map('Danger.TButton', background=[('active', dark_grey)], foreground=[('active', 'black')])
        style.configure('Warning.TButton', background=grey_color, foreground='black')
        style.map('Warning.TButton', background=[('active', dark_grey)], foreground=[('active', 'black')])
        style.configure('Info.TButton', background=grey_color, foreground='black')
        style.map('Info.TButton', background=[('active', dark_grey)], foreground=[('active', 'black')])

        # Configure treeview
        style.configure('Treeview', font=('Segoe UI', 10), rowheight=28)  # Reduced from 11 to 10, from 30 to 28
        style.configure('Treeview.Heading', font=('Segoe UI', 11, 'bold'), background=light_bg)  # Reduced from 12 to 11

        self.root.configure(bg=light_bg)

    def center_window(self, width, height):
        """Center the main window."""
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def center_dialog(self, dialog, width, height):
        """Center a dialog window on screen."""
        screen_width = dialog.winfo_screenwidth()
        screen_height = dialog.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        dialog.geometry(f'{width}x{height}+{x}+{y}')

    def handle_enter_key(self, event):
        """Handle Enter key press globally."""
        # Get the focused widget
        widget = self.root.focus_get()

        # If it's an Entry widget, find and click the default button
        if isinstance(widget, tk.Entry):
            # Find the parent dialog or frame
            parent = widget.winfo_toplevel()

            # Look for a default button (usually the primary action button)
            for child in parent.winfo_children():
                if isinstance(child, tk.Button) and child.cget('text') in ['LOGIN', 'ADD', 'UPDATE', 'SEARCH', 'SAVE',
                                                                           'CREATE ORDER', 'GENERATE BILL']:
                    child.invoke()
                    return "break"

        return None

    def show_error(self, message):
        messagebox.showerror("Error", message)

    def show_info(self, message):
        messagebox.showinfo("Information", message)

    def show_warning(self, message):
        messagebox.showwarning("Warning", message)

    def ask_confirmation(self, message):
        return messagebox.askyesno("Confirmation", message)

    def create_login_frame(self):
        """Create the login screen with hotel branding."""
        if self.main_frame:
            self.main_frame.destroy()

        # Create gradient background
        self.login_frame = tk.Frame(self.root, bg='white')
        self.login_frame.pack(fill=tk.BOTH, expand=True)

        # Left side with hotel branding
        left_frame = tk.Frame(self.login_frame, bg='#6a4334', width=500)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left_frame.pack_propagate(False)

        # Hotel branding
        brand_frame = tk.Frame(left_frame, bg='#6a4334')
        brand_frame.pack(expand=True, pady=100)

        tk.Label(brand_frame, text="THE", font=('Georgia', 24, 'bold'),
                 bg='#6a4334', fg='white').pack()
        tk.Label(brand_frame, text="EVAANI", font=('Georgia', 48, 'bold'),
                 bg='#6a4334', fg='white').pack()
        tk.Label(brand_frame, text="HOTEL", font=('Georgia', 28, 'bold'),
                 bg='#6a4334', fg='white').pack(pady=(0, 20))

        tk.Label(brand_frame, text="Integrated Restaurant Billing System", font=('Segoe UI', 16),
                 bg='#6a4334', fg='#d5d8dc').pack()
        tk.Label(brand_frame, text="Hotel + Restaurant + Inventory", font=('Segoe UI', 14),
                 bg='#6a4334', fg='#d5d8dc').pack(pady=(30, 0))

        # Right side with login form
        right_frame = tk.Frame(self.login_frame, bg='white', width=700)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        right_frame.pack_propagate(False)

        # Login form container
        form_container = tk.Frame(right_frame, bg='white')
        form_container.pack(expand=True, padx=100)

        # Form title
        tk.Label(form_container, text="Welcome Back", font=('Segoe UI', 24, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 40))

        # Username field
        tk.Label(form_container, text="Username", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').pack(anchor='w', pady=(10, 5))
        username_frame = tk.Frame(form_container, bg='white', height=50)
        username_frame.pack(fill=tk.X, pady=(0, 20))
        self.username_entry = tk.Entry(username_frame, font=('Segoe UI', 14),
                                       bd=0, highlightthickness=1, highlightcolor='#2e86c1',
                                       highlightbackground='#ddd', width=30)
        self.username_entry.pack(fill=tk.X, ipady=10)
        self.username_entry.focus()

        # Password field
        tk.Label(form_container, text="Password", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').pack(anchor='w', pady=(10, 5))
        password_frame = tk.Frame(form_container, bg='white', height=50)
        password_frame.pack(fill=tk.X, pady=(0, 30))
        self.password_entry = tk.Entry(password_frame, font=('Segoe UI', 14),
                                       show="*", bd=0, highlightthickness=1,
                                       highlightcolor='#2e86c1', highlightbackground='#ddd', width=30)
        self.password_entry.pack(fill=tk.X, ipady=10)

        # Login button
        login_btn = tk.Button(form_container, text="LOGIN", font=('Segoe UI', 14, 'bold'),
                              bg='#2e86c1', fg='black', activebackground='#6a4334',
                              activeforeground='white', relief='flat', cursor='hand2',
                              command=self.login, height=2, width=20)
        login_btn.pack(pady=20)

        # Bind Enter key to login
        self.password_entry.bind('<Return>', lambda e: self.login())

        # Footer
        footer_frame = tk.Frame(right_frame, bg='white')
        footer_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=20)
        tk.Label(footer_frame, text="© 2024 The Evaani Hotel. All rights reserved.",
                 font=('Segoe UI', 10), bg='white', fg='#7f8c8d').pack()

    def create_all_bills_in_popup(self, parent):
        """Create all bills screen in popup with settlement button."""
        # Filter frame
        filter_frame = tk.LabelFrame(parent, text="Filter Bills",
                                     font=('Segoe UI', 11, 'bold'),
                                     bg='white', fg='#6a4334', padx=15, pady=10)
        filter_frame.pack(fill=tk.X, pady=(0, 20))

        # Bill Number filter
        row_frame = tk.Frame(filter_frame, bg='white')
        row_frame.pack(fill=tk.X, pady=5)

        tk.Label(row_frame, text="Bill Number:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.all_bill_number_filter = tk.Entry(row_frame, font=('Segoe UI', 11), width=20)
        self.all_bill_number_filter.pack(side=tk.LEFT, padx=5)
        self.all_bill_number_filter.bind('<Return>', lambda e: self.filter_all_bills_popup())

        search_btn = tk.Button(row_frame, text="🔍 SEARCH",
                               font=('Segoe UI', 10, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.filter_all_bills_popup, padx=15, pady=2)
        search_btn.pack(side=tk.LEFT, padx=5)

        clear_btn = tk.Button(row_frame, text="🔄 CLEAR",
                              font=('Segoe UI', 10, 'bold'),
                              bg='#95a5a6', fg='black', relief='flat',
                              command=self.clear_all_bills_filter_popup, padx=15, pady=2)
        clear_btn.pack(side=tk.LEFT, padx=5)

        # Date range filters
        date_frame = tk.Frame(filter_frame, bg='white')
        date_frame.pack(fill=tk.X, pady=5)

        tk.Label(date_frame, text="From:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.all_from_date = tk.Entry(date_frame, font=('Segoe UI', 11), width=12)
        self.all_from_date.pack(side=tk.LEFT, padx=5)
        self.all_from_date.insert(0, (date.today() - timedelta(days=30)).isoformat())
        self.all_from_date.bind('<Return>', lambda e: self.all_to_date.focus())

        tk.Label(date_frame, text="To:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.all_to_date = tk.Entry(date_frame, font=('Segoe UI', 11), width=12)
        self.all_to_date.pack(side=tk.LEFT, padx=5)
        self.all_to_date.insert(0, date.today().isoformat())
        self.all_to_date.bind('<Return>', lambda e: self.load_all_bills_data_popup())

        filter_btn = tk.Button(date_frame, text="🔍 FILTER BY DATE",
                               font=('Segoe UI', 10, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.load_all_bills_data_popup, padx=15, pady=2)
        filter_btn.pack(side=tk.LEFT, padx=10)

        # Action buttons
        action_frame = tk.Frame(parent, bg='white')
        action_frame.pack(fill=tk.X, pady=(0, 10))

        view_btn = tk.Button(action_frame, text="👁️ VIEW BILL",
                             font=('Segoe UI', 11, 'bold'),
                             bg='#3498db', fg='black', relief='flat', cursor='hand2',
                             command=self.view_selected_all_bill_popup, padx=15, pady=5)
        view_btn.pack(side=tk.LEFT, padx=5)

        print_btn = tk.Button(action_frame, text="🖨️ PRINT BILL",
                              font=('Segoe UI', 11, 'bold'),
                              bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                              command=self.print_selected_all_bill_popup, padx=15, pady=5)
        print_btn.pack(side=tk.LEFT, padx=5)

        # NEW: Settlement Button
        settle_btn = tk.Button(action_frame, text="💰 SETTLE BILL",
                               font=('Segoe UI', 11, 'bold'),
                               bg='#f39c12', fg='black', relief='flat', cursor='hand2',
                               command=self.settle_selected_bill_popup, padx=15, pady=5)
        settle_btn.pack(side=tk.LEFT, padx=5)

        refresh_btn = tk.Button(action_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_all_bills_data_popup, padx=15, pady=5)
        refresh_btn.pack(side=tk.RIGHT, padx=5)

        # Treeview
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        columns = ('Bill #', 'Order #', 'Customer', 'Table/Room', 'Date', 'Total', 'Payment', 'Type', 'Status',
                   'Created By')
        self.all_bills_tree = ttk.Treeview(tree_container, columns=columns,
                                           yscrollcommand=v_scrollbar.set,
                                           xscrollcommand=h_scrollbar.set,
                                           height=15)

        v_scrollbar.config(command=self.all_bills_tree.yview)
        h_scrollbar.config(command=self.all_bills_tree.xview)

        for col in columns:
            self.all_bills_tree.heading(col, text=col, anchor=tk.W)
            self.all_bills_tree.column(col, width=120)

        self.all_bills_tree.column('Bill #', width=180)
        self.all_bills_tree.column('Order #', width=150)
        self.all_bills_tree.column('Customer', width=150)
        self.all_bills_tree.column('Status', width=100)

        self.all_bills_tree.bind('<Double-Button-1>', lambda e: self.view_selected_all_bill_popup())

        self.all_bills_tree.pack(fill=tk.BOTH, expand=True)

        self.load_all_bills_data_popup()

    def create_printer_settings_popup(self, parent):
        """Create printer settings screen."""
        # Get printers
        printers = self.restaurant.get_printer_settings()

        # Button frame
        button_frame = tk.Frame(parent, bg='white')
        button_frame.pack(fill=tk.X, pady=(0, 20))

        add_btn = tk.Button(button_frame, text="➕ ADD PRINTER",
                            font=('Segoe UI', 11, 'bold'),
                            bg='#27ae60', fg='black', relief='flat',
                            command=self.add_printer_dialog, padx=15, pady=5)
        add_btn.pack(side=tk.LEFT, padx=5)

        edit_btn = tk.Button(button_frame, text="✏️ EDIT",
                             font=('Segoe UI', 11, 'bold'),
                             bg='#f39c12', fg='black', relief='flat',
                             command=self.edit_printer_dialog, padx=15, pady=5)
        edit_btn.pack(side=tk.LEFT, padx=5)

        delete_btn = tk.Button(button_frame, text="🗑️ DELETE",
                               font=('Segoe UI', 11, 'bold'),
                               bg='#c0392b', fg='black', relief='flat',
                               command=self.delete_printer, padx=15, pady=5)
        delete_btn.pack(side=tk.LEFT, padx=5)

        test_btn = tk.Button(button_frame, text="🖨️ TEST PRINTER",
                             font=('Segoe UI', 11, 'bold'),
                             bg='#2e86c1', fg='black', relief='flat',
                             command=self.test_selected_printer, padx=15, pady=5)
        test_btn.pack(side=tk.LEFT, padx=5)

        refresh_btn = tk.Button(button_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat',
                                command=self.load_printers, padx=15, pady=5)
        refresh_btn.pack(side=tk.RIGHT, padx=5)

        # Treeview
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scroll = ttk.Scrollbar(tree_container)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ('ID', 'Printer Name', 'Type', 'Port/IP', 'Paper Width', 'Default', 'Status')
        self.printer_tree = ttk.Treeview(tree_container, columns=columns,
                                         yscrollcommand=v_scroll.set, height=10)
        v_scroll.config(command=self.printer_tree.yview)

        for col in columns:
            self.printer_tree.heading(col, text=col, anchor=tk.W)
            self.printer_tree.column(col, width=100)

        self.printer_tree.column('ID', width=50)
        self.printer_tree.column('Printer Name', width=150)

        self.printer_tree.pack(fill=tk.BOTH, expand=True)

        self.load_printers()

    def load_printers(self):
        """Load printers into treeview."""
        if not hasattr(self, 'printer_tree'):
            return

        for item in self.printer_tree.get_children():
            self.printer_tree.delete(item)

        printers = self.restaurant.get_printer_settings()

        for printer in printers:
            values = (
                printer['id'],
                printer['printer_name'],
                printer['printer_type'].upper(),
                printer.get('printer_port') or printer.get('printer_ip', 'N/A'),
                printer['paper_width'],
                '✅' if printer['is_default'] else '❌',
                '🟢 Enabled' if printer['enabled'] else '🔴 Disabled'
            )
            self.printer_tree.insert('', tk.END, values=values)

    def add_printer_dialog(self):
        """Dialog to add printer."""
        dialog = tk.Toplevel(self.current_popup if self.current_popup else self.root)
        dialog.title("Add Printer")
        dialog.geometry("500x450")
        dialog.transient(self.current_popup if self.current_popup else self.root)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 500, 450)

        dialog.bind('<Escape>', lambda e: dialog.destroy())

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="ADD PRINTER", font=('Segoe UI', 16, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        form_frame = tk.Frame(main_frame, bg='white')
        form_frame.pack(fill=tk.BOTH, expand=True)

        row = 0
        tk.Label(form_frame, text="Printer Name *", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        name_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        name_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        name_entry.bind('<Return>', lambda e: type_combo.focus())
        row += 1

        tk.Label(form_frame, text="Printer Type *", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        type_var = tk.StringVar(value='bill')
        type_combo = ttk.Combobox(form_frame, textvariable=type_var,
                                  values=['kitchen', 'desk', 'bill', 'report'],
                                  state='readonly', width=28, font=('Segoe UI', 11))
        type_combo.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        type_combo.bind('<<ComboboxSelected>>', lambda e: port_entry.focus())
        row += 1

        tk.Label(form_frame, text="Port (USB/LPT/COM)", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        port_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        port_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        port_entry.insert(0, 'USB001')
        port_entry.bind('<Return>', lambda e: ip_entry.focus())
        row += 1

        tk.Label(form_frame, text="IP Address (Network)", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        ip_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        ip_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        ip_entry.insert(0, '')
        ip_entry.bind('<Return>', lambda e: width_entry.focus())
        row += 1

        tk.Label(form_frame, text="Paper Width (chars)", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        width_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        width_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        width_entry.insert(0, '40')
        width_entry.bind('<Return>', lambda e: default_check.focus())
        row += 1

        default_var = tk.BooleanVar(value=True)
        default_check = ttk.Checkbutton(form_frame, text="Set as default printer",
                                        variable=default_var)
        default_check.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        row += 1

        def add_action():
            try:
                name = name_entry.get().strip()
                if not name:
                    raise ValueError("Printer name is required")

                printer_data = {
                    'printer_name': name,
                    'printer_type': type_var.get(),
                    'printer_port': port_entry.get().strip(),
                    'printer_ip': ip_entry.get().strip(),
                    'paper_width': int(width_entry.get()),
                    'is_default': default_var.get()
                }

                self.restaurant.add_printer(printer_data)
                self.show_info("Printer added successfully!")
                self.load_printers()
                dialog.destroy()

            except Exception as e:
                self.show_error(str(e))

        button_frame = tk.Frame(form_frame, bg='white')
        button_frame.grid(row=row, column=0, columnspan=2, pady=15)

        add_btn = tk.Button(button_frame, text="ADD PRINTER", font=('Segoe UI', 12, 'bold'),
                            bg='#27ae60', fg='black', relief='flat',
                            command=add_action, padx=30, pady=8)
        add_btn.pack(side=tk.LEFT, padx=10)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat',
                               command=dialog.destroy, padx=30, pady=8)
        cancel_btn.pack(side=tk.LEFT, padx=10)

        add_btn.bind('<Return>', lambda e: add_action())

    def edit_printer_dialog(self):
        """Dialog to edit printer."""
        selection = self.printer_tree.selection()
        if not selection:
            self.show_warning("Please select a printer")
            return

        printer_id = self.printer_tree.item(selection[0])['values'][0]
        printers = self.restaurant.get_printer_settings()
        printer = next((p for p in printers if p['id'] == printer_id), None)

        if not printer:
            self.show_error("Printer not found")
            return

        dialog = tk.Toplevel(self.current_popup if self.current_popup else self.root)
        dialog.title("Edit Printer")
        dialog.geometry("500x500")
        dialog.transient(self.current_popup if self.current_popup else self.root)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 500, 500)

        dialog.bind('<Escape>', lambda e: dialog.destroy())

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="EDIT PRINTER", font=('Segoe UI', 16, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        form_frame = tk.Frame(main_frame, bg='white')
        form_frame.pack(fill=tk.BOTH, expand=True)

        row = 0
        tk.Label(form_frame, text="Printer Name *", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        name_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        name_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        name_entry.insert(0, printer['printer_name'])
        row += 1

        tk.Label(form_frame, text="Printer Type *", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        type_var = tk.StringVar(value=printer['printer_type'])
        type_combo = ttk.Combobox(form_frame, textvariable=type_var,
                                  values=['kitchen', 'desk', 'bill', 'report'],
                                  state='readonly', width=28, font=('Segoe UI', 11))
        type_combo.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        row += 1

        tk.Label(form_frame, text="Port (USB/LPT/COM)", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        port_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        port_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        port_entry.insert(0, printer.get('printer_port', ''))
        row += 1

        tk.Label(form_frame, text="IP Address (Network)", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        ip_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        ip_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        ip_entry.insert(0, printer.get('printer_ip', ''))
        row += 1

        tk.Label(form_frame, text="Paper Width (chars)", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        width_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        width_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        width_entry.insert(0, str(printer['paper_width']))
        row += 1

        default_var = tk.BooleanVar(value=printer['is_default'])
        default_check = ttk.Checkbutton(form_frame, text="Set as default printer",
                                        variable=default_var)
        default_check.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        row += 1

        enabled_var = tk.BooleanVar(value=printer['enabled'])
        enabled_check = ttk.Checkbutton(form_frame, text="Printer enabled",
                                        variable=enabled_var)
        enabled_check.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        row += 1

        def update_action():
            try:
                name = name_entry.get().strip()
                if not name:
                    raise ValueError("Printer name is required")

                printer_data = {
                    'printer_name': name,
                    'printer_type': type_var.get(),
                    'printer_port': port_entry.get().strip(),
                    'printer_ip': ip_entry.get().strip(),
                    'paper_width': int(width_entry.get()),
                    'is_default': default_var.get(),
                    'enabled': enabled_var.get()
                }

                self.restaurant.update_printer(printer_id, printer_data)
                self.show_info("Printer updated successfully!")
                self.load_printers()
                dialog.destroy()

            except Exception as e:
                self.show_error(str(e))

        button_frame = tk.Frame(form_frame, bg='white')
        button_frame.grid(row=row, column=0, columnspan=2, pady=15)

        update_btn = tk.Button(button_frame, text="UPDATE PRINTER", font=('Segoe UI', 12, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=update_action, padx=30, pady=8)
        update_btn.pack(side=tk.LEFT, padx=10)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat',
                               command=dialog.destroy, padx=30, pady=8)
        cancel_btn.pack(side=tk.LEFT, padx=10)

        update_btn.bind('<Return>', lambda e: update_action())

    def delete_printer(self):
        """Delete selected printer."""
        selection = self.printer_tree.selection()
        if not selection:
            self.show_warning("Please select a printer")
            return

        printer_name = self.printer_tree.item(selection[0])['values'][1]

        if self.ask_confirmation(f"Delete printer '{printer_name}'?"):
            printer_id = self.printer_tree.item(selection[0])['values'][0]
            self.restaurant.delete_printer(printer_id)
            self.show_info("Printer deleted")
            self.load_printers()

    def test_selected_printer(self):
        """Test selected printer."""
        selection = self.printer_tree.selection()
        if not selection:
            self.show_warning("Please select a printer")
            return

        printer_id = self.printer_tree.item(selection[0])['values'][0]
        printers = self.restaurant.get_printer_settings()
        printer = next((p for p in printers if p['id'] == printer_id), None)

        if not printer:
            self.show_error("Printer not found")
            return

        if self.restaurant.test_printer_connection(printer):
            self.show_info(f"✅ Printer test successful!\n\n{printer['printer_name']} is working.")
        else:
            self.show_error(f"❌ Printer test failed!\n\nPlease check printer connection.")

    def settle_selected_bill_popup(self):
        """Open settlement dialog for selected bill."""
        selection = self.all_bills_tree.selection()
        if not selection:
            self.show_warning("Please select a bill to settle")
            return

        # Get bill details
        bill_values = self.all_bills_tree.item(selection[0])['values']
        bill_number = bill_values[0]
        original_total = float(bill_values[5].replace('₹', ''))

        # Get bill ID from database
        bills = self.restaurant.get_all_bills(bill_number=bill_number)
        if not bills:
            self.show_error("Bill not found")
            return

        bill = bills[0]
        bill_id = bill['id']

        # Create settlement dialog
        dialog = tk.Toplevel(self.current_popup if self.current_popup else self.root)
        dialog.title(f"Settle Bill - {bill_number}")
        dialog.geometry("500x400")
        dialog.transient(self.current_popup if self.current_popup else self.root)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 500, 400)

        # Bind Escape to close
        dialog.bind('<Escape>', lambda e: dialog.destroy())

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="SETTLE BILL", font=('Segoe UI', 18, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        # Bill info
        info_frame = tk.LabelFrame(main_frame, text="Bill Information",
                                   font=('Segoe UI', 11, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        info_frame.pack(fill=tk.X, pady=(0, 20))

        tk.Label(info_frame, text=f"Bill Number: {bill_number}", font=('Segoe UI', 11),
                 bg='white', fg='#2e86c1').pack(anchor='w', pady=2)
        tk.Label(info_frame, text=f"Customer: {bill['customer_name']}", font=('Segoe UI', 11),
                 bg='white', fg='#2e86c1').pack(anchor='w', pady=2)
        tk.Label(info_frame, text=f"Original Amount: ₹{original_total:.2f}", font=('Segoe UI', 11, 'bold'),
                 bg='white', fg='#c0392b').pack(anchor='w', pady=2)

        # Settlement form
        form_frame = tk.LabelFrame(main_frame, text="Settlement Details",
                                   font=('Segoe UI', 11, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        form_frame.pack(fill=tk.X, pady=(0, 20))

        row = 0
        tk.Label(form_frame, text="Amount Received (₹):", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.settle_amount_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=20)
        self.settle_amount_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.settle_amount_entry.insert(0, str(original_total))
        row += 1

        tk.Label(form_frame, text="Payment Method:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.settle_method_var = tk.StringVar(value='cash')
        method_combo = ttk.Combobox(form_frame, textvariable=self.settle_method_var,
                                    values=['cash', 'card', 'upi'], state='readonly',
                                    width=18, font=('Segoe UI', 11))
        method_combo.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        row += 1

        tk.Label(form_frame, text="Notes:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='ne')
        self.settle_notes = tk.Text(form_frame, font=('Segoe UI', 11), width=30, height=3)
        self.settle_notes.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.settle_notes.insert('1.0', f"Customer paid ₹{original_total:.2f} but gave less - settled amount")
        row += 1

        # Discount preview
        self.discount_preview_label = tk.Label(form_frame, text="", font=('Segoe UI', 11, 'bold'),
                                               bg='white', fg='#27ae60')
        self.discount_preview_label.grid(row=row, column=0, columnspan=2, pady=10)

        # Bind amount entry to calculate discount
        self.settle_amount_entry.bind('<KeyRelease>', lambda e: self.update_settlement_discount(original_total))

        def settle_action():
            try:
                settled_amount = float(self.settle_amount_entry.get())
                if settled_amount <= 0:
                    raise ValueError("Amount must be positive")
                if settled_amount > original_total:
                    raise ValueError(f"Settled amount cannot exceed original amount ₹{original_total:.2f}")

                settlement_data = {
                    'settled_amount': settled_amount,
                    'payment_method': self.settle_method_var.get(),
                    'notes': self.settle_notes.get('1.0', tk.END).strip()
                }

                self.restaurant.settle_bill(bill_id, settlement_data)

                # Show summary
                discount = original_total - settled_amount
                if discount > 0:
                    self.show_info(f"✅ Bill settled successfully!\n\n"
                                   f"Original Amount: ₹{original_total:.2f}\n"
                                   f"Amount Paid: ₹{settled_amount:.2f}\n"
                                   f"Discount Given: ₹{discount:.2f}\n"
                                   f"Discount %: {(discount / original_total * 100):.1f}%\n\n"
                                   f"This discount will be reflected in today's sales summary.")
                else:
                    self.show_info(f"✅ Bill settled successfully!\n\nAmount Paid: ₹{settled_amount:.2f}")

                dialog.destroy()
                self.load_all_bills_data_popup()

            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(f"Error settling bill: {str(e)}")

        # Button frame
        button_frame = tk.Frame(main_frame, bg='white')
        button_frame.pack(pady=20)

        settle_btn = tk.Button(button_frame, text="💰 SETTLE BILL", font=('Segoe UI', 12, 'bold'),
                               bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                               command=settle_action, padx=30, pady=10)
        settle_btn.pack(side=tk.LEFT, padx=10)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                               command=dialog.destroy, padx=30, pady=10)
        cancel_btn.pack(side=tk.LEFT, padx=10)

        # Bind Enter key
        settle_btn.bind('<Return>', lambda e: settle_action())

    def update_settlement_discount(self, original_total, event=None):
        """Update discount preview when settlement amount changes."""
        try:
            settled_amount = float(self.settle_amount_entry.get())
            if 0 < settled_amount < original_total:
                discount = original_total - settled_amount
                discount_percent = (discount / original_total) * 100
                self.discount_preview_label.config(
                    text=f"Discount: ₹{discount:.2f} ({discount_percent:.1f}%)",
                    fg='#c0392b'
                )
            elif settled_amount == original_total:
                self.discount_preview_label.config(text="No discount", fg='#27ae60')
            else:
                self.discount_preview_label.config(text="Invalid amount", fg='#c0392b')
        except:
            self.discount_preview_label.config(text="", fg='black')

    def load_all_bills_data_popup(self):
        """Load all bills data in popup with settlement status."""
        if not hasattr(self, 'all_bills_tree'):
            return

        for item in self.all_bills_tree.get_children():
            self.all_bills_tree.delete(item)

        try:
            from_date = self.all_from_date.get()
            to_date = self.all_to_date.get()

            bills = self.restaurant.get_all_bills(from_date, to_date)

            for bill in bills:
                # Determine status
                if bill.get('settled_at'):
                    status = 'SETTLED'
                    status_color = '#f39c12'  # Orange
                elif bill['is_complimentary']:
                    status = 'COMP'
                    status_color = '#ffffcc'
                else:
                    status = 'PAID'
                    status_color = 'white'

                values = (
                    bill['bill_number'],
                    bill['order_id'],
                    bill['customer_name'],
                    bill.get('table_number') or bill.get('room_number', ''),
                    bill['bill_date'],
                    f"₹{bill['total_amount']:.2f}",
                    bill['payment_method'].upper(),
                    'COMP' if bill['is_complimentary'] else 'PAID',
                    status,
                    bill.get('created_by_name', '')
                )

                tags = ('settled',) if bill.get('settled_at') else ('comp',) if bill['is_complimentary'] else ()
                self.all_bills_tree.insert('', tk.END, values=values, tags=tags)

            # Configure tags
            self.all_bills_tree.tag_configure('comp', background='#ffffcc')
            self.all_bills_tree.tag_configure('settled', background='#fdebd0')  # Light orange

        except Exception as e:
            self.show_error(f"Error loading bills: {str(e)}")

    def login(self):
        """Handle login."""
        username = self.username_entry.get()
        password = self.password_entry.get()

        try:
            user = self.auth.login(username, password)
            if user:
                self.current_user = user
                self.login_frame.destroy()
                self.check_day_start()
            else:
                self.show_error("Invalid username or password!")
        except Exception as e:
            self.show_error(str(e))

    def check_day_start(self):
        """Check if day needs to be started."""
        is_open = self.day_manager.check_today_status()

        if not is_open:
            if messagebox.askyesno("Start Day", "Do you want to start the day?"):
                self.show_start_day_dialog()
            else:
                self.create_main_menu()
        else:
            self.create_main_menu()

    def show_start_day_dialog(self):
        """Show dialog to start the day."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Start Day")
        dialog.geometry("400x250")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 400, 300)

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="START NEW DAY", font=('Segoe UI', 16, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        tk.Label(main_frame, text=f"Date: {date.today().strftime('%d %B, %Y')}",
                 font=('Segoe UI', 12), bg='white', fg='#2e86c1').pack(pady=5)

        tk.Label(main_frame, text="Opening Cash (₹):", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(anchor='w', pady=(10, 5))
        opening_cash_entry = tk.Entry(main_frame, font=('Segoe UI', 12), width=20)
        opening_cash_entry.pack(fill=tk.X, pady=(0, 10))
        opening_cash_entry.insert(0, '100.00')
        opening_cash_entry.focus()
        opening_cash_entry.bind('<Return>', lambda e: start_action())

        def start_action():
            try:
                opening_cash = float(opening_cash_entry.get() or 0)
                self.day_manager.start_day(opening_cash)
                self.show_info("Day started successfully!")
                dialog.destroy()
                self.create_main_menu()
            except ValueError:
                self.show_error("Please enter a valid amount")
            except Exception as e:
                self.show_error(str(e))

        button_frame = tk.Frame(main_frame, bg='white')
        button_frame.pack(pady=20)

        start_btn = tk.Button(button_frame, text="START DAY", font=('Segoe UI', 12, 'bold'),
                              bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                              command=start_action, padx=30, pady=10)
        start_btn.pack(side=tk.LEFT, padx=10)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                               command=lambda: [dialog.destroy(), self.create_main_menu()],
                               padx=30, pady=10)
        cancel_btn.pack(side=tk.LEFT, padx=10)

    def create_main_menu(self):
        """Create the main menu screen - absolutely NO white backgrounds, only image visible."""
        # Clear existing main frame if it exists
        if hasattr(self, 'main_frame') and self.main_frame:
            self.main_frame.destroy()

        self.main_frame = tk.Frame(self.root, bg='#f8f9fa')
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # Create header
        self.create_header()

        # Create main container
        main_container = tk.Frame(self.main_frame, bg='#f8f9fa')
        main_container.pack(fill=tk.BOTH, expand=True)

        # BACKGROUND IMAGE - FULL SCREEN (THIS IS THE ONLY BACKGROUND)
        try:
            # Use the correct image path - check for Windows or macOS
            if os.name == 'nt':  # Windows
                image_path = r"C:\Users\sanan\Downloads\resort.jpeg"
            else:  # macOS/Linux - skip background image
                raise FileNotFoundError("Background image not configured for macOS")

            # Check if file exists
            import os
            if not os.path.exists(image_path):
                print(f"⚠️ Image not found at: {image_path}")
                raise FileNotFoundError(f"Image not found: {image_path}")

            print(f"✅ Loading background image from: {image_path}")

            # Get current screen dimensions
            screen_width = self.root.winfo_width()
            screen_height = self.root.winfo_height()

            # If dimensions are 1x1 (not yet realized), use a default size
            if screen_width <= 1 or screen_height <= 1:
                screen_width = 1600
                screen_height = 900

            # Load and resize image to fit screen
            img = Image.open(image_path)
            img = img.resize((screen_width, screen_height), RESAMPLE_FILTER)
            self.bg_photo = ImageTk.PhotoImage(img)

            # Create label with image that fills the entire container
            bg_label = tk.Label(main_container, image=self.bg_photo, bg='#f8f9fa')
            bg_label.place(x=0, y=0, relwidth=1, relheight=1)

            # Bind resize event to update image when window is resized
            def resize_background(event):
                if event.width > 1 and event.height > 1:  # Avoid invalid dimensions
                    try:
                        new_img = Image.open(image_path)
                        new_img = new_img.resize((event.width, event.height), RESAMPLE_FILTER)
                        new_photo = ImageTk.PhotoImage(new_img)
                        bg_label.config(image=new_photo)
                        bg_label.image = new_photo  # Keep a reference
                        self.bg_photo = new_photo  # Update the stored reference
                    except Exception as e:
                        print(f"Error resizing background: {e}")

            main_container.bind('<Configure>', resize_background)

        except Exception as e:
            # Fallback if image loading fails
            print(f"⚠️ Could not load background image: {e}")
            print("Using fallback solid color background")

            # Create a solid color background
            bg_label = tk.Label(main_container, bg='#f0f0f0')
            bg_label.place(x=0, y=0, relwidth=1, relheight=1)

            # Add some decorative elements for visual appeal
            # Top gradient bar
            gradient_frame = tk.Frame(main_container, bg='#6a4334', height=80)
            gradient_frame.place(x=0, y=0, relwidth=1)

            # Hotel name on the gradient bar
            tk.Label(gradient_frame, text="THE EVAANI HOTEL",
                     font=('Georgia', 18, 'bold'),
                     bg='#6a4334', fg='white').place(relx=0.5, rely=0.5, anchor=tk.CENTER)

            # Bottom gradient bar
            bottom_gradient = tk.Frame(main_container, bg='#6a4334', height=30)
            bottom_gradient.place(x=0, rely=1.0, relwidth=1, anchor=tk.SW)

        # ALL CONTENT IS PLACED DIRECTLY ON THE IMAGE - NO BACKGROUND FRAMES
        # Title - NO BACKGROUND, directly on image
        title_label = tk.Label(main_container,
                               text="RESTAURANT BILLING SYSTEM",
                               font=('Segoe UI', 24, 'bold'),
                               bg='#f8f9fa',  # This becomes transparent on the image
                               fg='black',
                               bd=0)
        title_label.place(relx=0.5, rely=0.10, anchor=tk.CENTER)  # Moved up slightly

        # Day status indicator - ONLY THIS HAS COLOR BACKGROUND
        is_open = self.day_manager.check_today_status()
        day_status = "🟢 DAY OPEN" if is_open else "🔴 DAY CLOSED"
        day_color = "#27ae60" if is_open else "#c0392b"

        day_label = tk.Label(main_container,
                             text=day_status,
                             font=('Segoe UI', 14, 'bold'),
                             bg=day_color,
                             fg='black',
                             padx=20,
                             pady=8,
                             bd=0)
        day_label.place(relx=0.5, rely=0.16, anchor=tk.CENTER)  # Moved up slightly

        # Subtitle - NO BACKGROUND
        if self.auth.is_admin():
            subtitle_text = f"Welcome, {self.auth.current_user['username'].upper()} (ADMINISTRATOR)"
        else:
            subtitle_text = f"Welcome, {self.auth.current_user['username'].upper()} (USER)"

        subtitle = tk.Label(main_container,
                            text=subtitle_text,
                            font=('Segoe UI', 16),
                            bg='#f8f9fa',  # Transparent
                            fg='black',
                            bd=0)
        subtitle.place(relx=0.5, rely=0.22, anchor=tk.CENTER)  # Moved up slightly

        # Create two columns for buttons - directly on image
        # Left column buttons
        left_buttons = [
            ('F1', '📊 DASHBOARD', 'dashboard'),
            ('F2', '🍽️ NEW ORDER', 'new_order'),
            ('F3', '📋 ACTIVE ORDERS', 'active_orders'),
            ('F4', '🧾 GENERATE BILL', 'generate_bill'),
            ('F5', '💰 SETTLEMENT', 'settlement'),
            ('F6', '📈 SALES SUMMARY', 'sales_summary'),
            ('F7', '📊 REPORTS', 'reports'),
            ('F8', '🏪 RESTAURANTS', 'restaurants'),
            ('F9', '📋 MENU', 'menu')
        ]

        # Right column buttons (for admin)
        if self.auth.is_admin():
            right_buttons = [
                ('F10', '📄 ALL BILLS', 'all_bills'),
                ('F11', '⏳ PENDING BILLS', 'pending_bills'),
                ('F12', '🎁 COMP BILLS', 'comp_bills'),
                ('Ctrl+U', '🛎️ ROOM SERVICE BILLS', 'room_service_bills'),
                ('Ctrl+J', '🍽️ RESTAURANT BILLS', 'restaurant_bills'),
                ('Ctrl+R', '👥 USER MANAGEMENT', 'users'),
                ('Ctrl+P', '🖨️ TEST PRINTERS', 'test_printers'),
                ('Ctrl+K', '🖨️ PRINTER SETTINGS', 'printer_settings'),
                ('Ctrl+L', '⚙️ SETTINGS', 'settings'),
                ('Ctrl+M', '🔒 CLOSE DAY', 'close_day'),
                ('Ctrl+N', '🚪 LOGOUT', 'logout')
            ]
        else:
            right_buttons = [
                ('F10', '📄 ALL BILLS', 'all_bills'),
                ('F11', '⏳ PENDING BILLS', 'pending_bills'),
                ('F12', '🎁 COMP BILLS', 'comp_bills'),
                ('Ctrl+R', '🖨️ PRINTER SETTINGS', 'printer_settings'),
                ('Ctrl+P', '🖨️ TEST PRINTERS', 'test_printers'),
                ('Ctrl+U', '⚙️ SETTINGS', 'settings'),
                ('Ctrl+J', '🔒 CLOSE DAY', 'close_day'),
                ('Ctrl+K', '🚪 LOGOUT', 'logout')
            ]

        grey_color = 'white'  # Fixed: Use actual grey color
        dark_grey = '#5a6268'  # Fixed: Use actual dark grey

        # Calculate center positions for two columns
        # Left column anchor at 0.38 (38% from left)
        # Right column anchor at 0.62 (62% from left)

        # Place left column buttons - INCREASED SIZE
        for i, (shortcut, text, command_id) in enumerate(left_buttons):
            y_pos = 0.28 + (i * 0.050)  # Adjusted spacing for larger buttons

            # Shortcut badge - INCREASED SIZE
            badge = tk.Label(main_container,
                             text=shortcut,
                             font=('Segoe UI', 10, 'bold'),  # Increased font size
                             bg='#6a4334',
                             fg='white',
                             width=6,  # Increased from 5 to 6
                             height=2,  # Increased from 1 to 2
                             relief=tk.FLAT,
                             bd=0)
            badge.place(relx=0.32, rely=y_pos, anchor=tk.E)  # Adjusted position

            # Main button - INCREASED SIZE
            btn = tk.Button(main_container,
                            text=text,
                            font=('Segoe UI', 12, 'bold'),  # Increased from 11 to 12
                            bg=grey_color,
                            fg='black',
                            activebackground=dark_grey,
                            activeforeground='black',
                            relief=tk.RAISED,
                            bd=2,  # Increased from 1 to 2
                            cursor='hand2',
                            width=25,  # Increased from 22 to 25
                            height=1,  # Increased from 1 to 2
                            command=lambda c=command_id: self.handle_menu_command(c))
            btn.place(relx=0.33, rely=y_pos, anchor=tk.W)  # Adjusted position

        # Place right column buttons - INCREASED SIZE
        for i, (shortcut, text, command_id) in enumerate(right_buttons):
            y_pos = 0.28 + (i * 0.046)  # Adjusted spacing for larger buttons

            # Shortcut badge - INCREASED SIZE
            badge = tk.Label(main_container,
                             text=shortcut,
                             font=('Segoe UI', 10, 'bold'),  # Increased font size
                             bg='#6a4334',
                             fg='white',
                             width=6,  # Increased from 5 to 6
                             height=2,  # Increased from 1 to 2
                             relief=tk.FLAT,
                             bd=0)
            badge.place(relx=0.58, rely=y_pos, anchor=tk.E)  # Adjusted position

            # Main button - INCREASED SIZE
            btn = tk.Button(main_container,
                            text=text,
                            font=('Segoe UI', 12, 'bold'),  # Increased from 11 to 12
                            bg=grey_color,
                            fg='black',
                            activebackground=dark_grey,
                            activeforeground='black',
                            relief=tk.RAISED,
                            bd=2,  # Increased from 1 to 2
                            cursor='hand2',
                            width=25,  # Increased from 22 to 25
                            height=1,  # Increased from 1 to 2
                            command=lambda c=command_id: self.handle_menu_command(c))
            btn.place(relx=0.59, rely=y_pos, anchor=tk.W)  # Adjusted position

        # Status bar - at the very bottom of the window (this is the ONLY non-transparent bar)
        status_bar = tk.Frame(self.main_frame, bg='#6a4334', height=25)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        status_bar.pack_propagate(False)

        status_text = f"Logged in as: {self.auth.current_user['username']} | Role: {self.auth.current_user['role']} | Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        tk.Label(status_bar, text=status_text, font=('Segoe UI', 9),
                 bg='#6a4334', fg='white').pack(side=tk.LEFT, padx=20, pady=3)

        # Keyboard shortcuts
        self.setup_shortcuts()

        # Force an initial resize to set the background properly
        self.root.update_idletasks()
        main_container.event_generate('<Configure>')

    def create_header(self):
        """Create header for main menu - smaller."""
        header_frame = tk.Frame(self.main_frame, bg='#6a4334', height=70)  # Reduced from 80 to 70
        header_frame.pack(fill=tk.X, padx=0, pady=0)
        header_frame.pack_propagate(False)

        # Left side: Hotel logo and name
        logo_frame = tk.Frame(header_frame, bg='#6a4334')
        logo_frame.pack(side=tk.LEFT, padx=20, pady=12)  # Reduced pady from 10 to 12? Actually made consistent

        hotel_label = tk.Label(logo_frame, text="🏨 THE EVAANI HOTEL",
                               font=('Georgia', 18, 'bold'), bg='#6a4334', fg='white')  # Reduced from 20 to 18
        hotel_label.pack(side=tk.LEFT, padx=(0, 15))  # Reduced padx from 20 to 15

        system_label = tk.Label(logo_frame, text="Integrated Restaurant Billing System",
                                font=('Segoe UI', 11), bg='#6a4334', fg='#d5d8dc')  # Reduced from 12 to 11
        system_label.pack(side=tk.LEFT)

        # Right side: User info and day status
        user_frame = tk.Frame(header_frame, bg='#6a4334')
        user_frame.pack(side=tk.RIGHT, padx=20, pady=12)  # Reduced pady from 10 to 12? Made consistent

        # Day status indicator
        is_open = self.day_manager.check_today_status()
        day_status = "🟢 DAY OPEN" if is_open else "🔴 DAY CLOSED"
        day_color = "#27ae60" if is_open else "#c0392b"

        day_label = tk.Label(user_frame, text=day_status, font=('Segoe UI', 9, 'bold'),  # Reduced from 10 to 9
                             bg=day_color, fg='black', padx=8, pady=3)  # Reduced padding
        day_label.pack(side=tk.LEFT, padx=(0, 15))  # Reduced padx from 20 to 15

        welcome_label = tk.Label(user_frame,
                                 text=f"Welcome, {self.auth.current_user['username'].upper()}",
                                 font=('Segoe UI', 11, 'bold'),  # Reduced from 12 to 11
                                 bg='#6a4334', fg='white')
        welcome_label.pack(side=tk.LEFT, padx=(0, 15))  # Reduced padx from 20 to 15

        role_badge = tk.Label(user_frame, text=self.auth.current_user['role'].upper(),
                              font=('Segoe UI', 9, 'bold'), bg='#2e86c1', fg='black',  # Reduced from 10 to 9
                              padx=8, pady=3, relief=tk.FLAT)  # Reduced padding
        role_badge.pack(side=tk.LEFT, padx=(0, 15))  # Reduced padx from 20 to 15

        logout_btn = tk.Button(user_frame, text="LOGOUT", font=('Segoe UI', 10, 'bold'),  # Reduced from 11 to 10
                               bg='#c0392b', fg='black', activebackground='#a93226',
                               activeforeground='white', relief='flat', cursor='hand2',
                               command=self.logout, padx=12, pady=3)  # Reduced padding
        logout_btn.pack(side=tk.LEFT)

    def setup_shortcuts(self):
        """Setup keyboard shortcuts for menu items."""
        # Unbind any existing shortcuts
        for i in range(1, 13):
            self.root.unbind(f'<F{i}>')

        # Unbind Ctrl shortcuts
        self.root.unbind('<Control-u>')
        self.root.unbind('<Control-U>')
        self.root.unbind('<Control-j>')
        self.root.unbind('<Control-J>')
        self.root.unbind('<Control-r>')
        self.root.unbind('<Control-R>')
        self.root.unbind('<Control-k>')
        self.root.unbind('<Control-K>')
        self.root.unbind('<Control-l>')
        self.root.unbind('<Control-L>')
        self.root.unbind('<Control-m>')
        self.root.unbind('<Control-M>')
        self.root.unbind('<Control-n>')
        self.root.unbind('<Control-N>')

        # Bind shortcuts based on user role
        if self.auth.is_admin():
            self.root.bind('<F1>', lambda e: self.handle_menu_command('dashboard'))
            self.root.bind('<F2>', lambda e: self.handle_menu_command('new_order'))
            self.root.bind('<F3>', lambda e: self.handle_menu_command('active_orders'))
            self.root.bind('<F4>', lambda e: self.handle_menu_command('generate_bill'))
            self.root.bind('<F5>', lambda e: self.handle_menu_command('settlement'))
            self.root.bind('<F6>', lambda e: self.handle_menu_command('sales_summary'))
            self.root.bind('<F7>', lambda e: self.handle_menu_command('reports'))
            self.root.bind('<F8>', lambda e: self.handle_menu_command('restaurants'))
            self.root.bind('<F9>', lambda e: self.handle_menu_command('menu'))
            self.root.bind('<F10>', lambda e: self.handle_menu_command('all_bills'))
            self.root.bind('<F11>', lambda e: self.handle_menu_command('pending_bills'))
            self.root.bind('<F12>', lambda e: self.handle_menu_command('comp_bills'))
        else:
            self.root.bind('<F1>', lambda e: self.handle_menu_command('dashboard'))
            self.root.bind('<F2>', lambda e: self.handle_menu_command('new_order'))
            self.root.bind('<F3>', lambda e: self.handle_menu_command('active_orders'))
            self.root.bind('<F4>', lambda e: self.handle_menu_command('generate_bill'))
            self.root.bind('<F5>', lambda e: self.handle_menu_command('settlement'))
            self.root.bind('<F6>', lambda e: self.handle_menu_command('sales_summary'))
            self.root.bind('<F7>', lambda e: self.handle_menu_command('reports'))
            self.root.bind('<F8>', lambda e: self.handle_menu_command('all_bills'))
            self.root.bind('<F9>', lambda e: self.handle_menu_command('pending_bills'))
            self.root.bind('<F10>', lambda e: self.handle_menu_command('comp_bills'))
            self.root.bind('<F11>', lambda e: self.handle_menu_command('room_service_bills'))
            self.root.bind('<F12>', lambda e: self.handle_menu_command('restaurant_bills'))

        # Common Ctrl shortcuts
        self.root.bind('<Control-u>', lambda e: self.handle_menu_command('room_service_bills'))
        self.root.bind('<Control-U>', lambda e: self.handle_menu_command('room_service_bills'))
        self.root.bind('<Control-j>', lambda e: self.handle_menu_command('restaurant_bills'))
        self.root.bind('<Control-J>', lambda e: self.handle_menu_command('restaurant_bills'))
        self.root.bind('<Control-r>', lambda e: self.handle_menu_command('users'))
        self.root.bind('<Control-R>', lambda e: self.handle_menu_command('users'))
        self.root.bind('<Control-k>', lambda e: self.handle_menu_command('printers'))
        self.root.bind('<Control-K>', lambda e: self.handle_menu_command('printers'))
        self.root.bind('<Control-l>', lambda e: self.handle_menu_command('settings'))
        self.root.bind('<Control-L>', lambda e: self.handle_menu_command('settings'))
        self.root.bind('<Control-m>', lambda e: self.handle_menu_command('close_day'))
        self.root.bind('<Control-M>', lambda e: self.handle_menu_command('close_day'))
        self.root.bind('<Control-n>', lambda e: self.handle_menu_command('logout'))
        self.root.bind('<Control-N>', lambda e: self.handle_menu_command('logout'))

    def handle_menu_command(self, command_id):
        """Handle menu commands - open in popup if applicable, otherwise direct."""
        if command_id == 'dashboard':
            self.open_popup('dashboard')
        elif command_id == 'new_order':
            self.open_popup('new_order')
        elif command_id == 'active_orders':
            self.open_popup('active_orders')
        elif command_id == 'generate_bill':
            self.open_popup('generate_bill')
        elif command_id == 'settlement':
            self.open_popup('settlement')
        elif command_id == 'sales_summary':
            self.open_popup('sales_summary')
        elif command_id == 'reports':
            self.open_popup('reports')
        elif command_id == 'restaurants':
            self.open_popup('restaurants')
        elif command_id == 'menu':
            self.open_popup('menu')
        elif command_id == 'all_bills':
            self.open_popup('all_bills')
        elif command_id == 'pending_bills':
            self.open_popup('pending_bills')
        elif command_id == 'comp_bills':
            self.open_popup('comp_bills')
        elif command_id == 'room_service_bills':
            self.open_popup('room_service_bills')
        elif command_id == 'restaurant_bills':
            self.open_popup('restaurant_bills')
        elif command_id == 'users' and self.auth.is_admin():
            self.open_popup('users')
        elif command_id == 'test_printers':
            self.test_all_printers()
        elif command_id == 'printer_settings':
            self.configure_printers_dialog()
        elif command_id == 'printers':
            self.open_popup('printers')
        elif command_id == 'settings':
            self.open_popup('settings')
        elif command_id == 'close_day':
            self.close_day()
        elif command_id == 'logout':
            self.logout()

    def open_popup(self, tab_id):
        """Open a popup window for the selected function."""
        # Close existing popup if any
        if self.current_popup and self.current_popup.winfo_exists():
            self.current_popup.destroy()

        # Create new popup
        popup = tk.Toplevel(self.root)
        popup.title(f"The Evaani Hotel - {self.get_tab_title(tab_id)}")
        popup.geometry("1000x700")
        popup.transient(self.root)
        popup.grab_set()
        popup.configure(bg='white')

        # Center popup
        self.center_dialog(popup, 1000, 700)

        # Make popup modal
        popup.focus_set()

        # Store reference
        self.current_popup = popup

        # Create content based on tab_id
        self.create_popup_content(popup, tab_id)

        # Bind Escape key to close popup
        popup.bind('<Escape>', lambda e: popup.destroy())

        # Add close button
        close_btn = tk.Button(popup, text="✕ CLOSE", font=('Segoe UI', 12, 'bold'),
                              bg='#c0392b', fg='black', activebackground='#a93226',
                              activeforeground='white', relief='flat', cursor='hand2',
                              command=popup.destroy, padx=20, pady=5)
        close_btn.place(relx=1.0, x=-20, y=20, anchor=tk.NE)

    def get_tab_title(self, tab_id):
        """Get display title for tab."""
        titles = {
            'dashboard': 'Dashboard',
            'new_order': 'New Order',
            'active_orders': 'Active Orders',
            'generate_bill': 'Generate Bill',
            'settlement': 'Bill Settlement',
            'sales_summary': 'Sales Summary',
            'reports': 'Reports',
            'restaurants': 'Restaurant Management',
            'menu': 'Menu Management',
            'all_bills': 'All Bills',
            'pending_bills': 'Pending Bills',
            'comp_bills': 'Complimentary Bills',
            'room_service_bills': 'Room Service Bills',
            'restaurant_bills': 'Restaurant Bills',
            'printers': 'Printer Settings',
            'users': 'User Management',
            'settings': 'Settings'
        }
        return titles.get(tab_id, tab_id.replace('_', ' ').title())

    def create_popup_content(self, parent, tab_id):
        """Create content for popup window."""
        # Clear parent except close button
        for widget in parent.winfo_children():
            if widget != parent.winfo_children()[-1]:  # Keep close button
                widget.destroy()

        # Main container
        main_container = tk.Frame(parent, bg='white', padx=20, pady=20)
        main_container.pack(fill=tk.BOTH, expand=True)

        # Title
        title_label = tk.Label(main_container, text=self.get_tab_title(tab_id).upper(),
                               font=('Segoe UI', 20, 'bold'),
                               bg='white', fg='#6a4334')
        title_label.pack(pady=(0, 20), anchor=tk.W)

        # Create content based on tab_id
        if tab_id == 'dashboard':
            self.create_dashboard_popup(main_container)
        elif tab_id == 'new_order':
            self.create_new_order_popup(main_container)
        elif tab_id == 'active_orders':
            self.create_active_orders_popup(main_container)
        elif tab_id == 'generate_bill':
            self.create_generate_bill_popup(main_container)
        elif tab_id == 'settlement':
            self.create_settlement_popup(main_container)
        elif tab_id == 'sales_summary':
            self.create_sales_summary_popup(main_container)
        elif tab_id == 'reports':
            self.create_reports_popup(main_container)
        elif tab_id == 'restaurants':
            self.create_restaurant_management_popup(main_container)
        elif tab_id == 'menu':
            self.create_menu_management_popup(main_container)
        elif tab_id == 'all_bills':
            self.create_all_bills_popup(main_container)
        elif tab_id == 'pending_bills':
            self.create_pending_bills_popup(main_container)
        elif tab_id == 'comp_bills':
            self.create_comp_bills_popup(main_container)
        elif tab_id == 'room_service_bills':
            self.create_room_service_bills_popup(main_container)
        elif tab_id == 'restaurant_bills':
            self.create_restaurant_bills_popup(main_container)
        elif tab_id == 'users' and self.auth.is_admin():
            self.create_users_popup(main_container)
        elif tab_id == 'printers':
            self.create_printer_settings_popup(main_container)
        elif tab_id == 'settings':
            self.create_settings_popup(main_container)

    def create_settlement_popup(self, parent):
        """Create settlement screen in popup."""
        # Filter frame
        filter_frame = tk.LabelFrame(parent, text="Filter Bills for Settlement",
                                     font=('Segoe UI', 11, 'bold'),
                                     bg='white', fg='#6a4334', padx=15, pady=10)
        filter_frame.pack(fill=tk.X, pady=(0, 20))

        # Bill Number filter
        row_frame = tk.Frame(filter_frame, bg='white')
        row_frame.pack(fill=tk.X, pady=5)

        tk.Label(row_frame, text="Bill Number:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.settlement_bill_filter = tk.Entry(row_frame, font=('Segoe UI', 11), width=20)
        self.settlement_bill_filter.pack(side=tk.LEFT, padx=5)
        self.settlement_bill_filter.bind('<Return>', lambda e: self.filter_settlement_bills())

        search_btn = tk.Button(row_frame, text="🔍 SEARCH",
                               font=('Segoe UI', 10, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.filter_settlement_bills, padx=15, pady=2)
        search_btn.pack(side=tk.LEFT, padx=5)

        clear_btn = tk.Button(row_frame, text="🔄 CLEAR",
                              font=('Segoe UI', 10, 'bold'),
                              bg='#95a5a6', fg='black', relief='flat',
                              command=self.clear_settlement_filter, padx=15, pady=2)
        clear_btn.pack(side=tk.LEFT, padx=5)

        # Date range filters
        date_frame = tk.Frame(filter_frame, bg='white')
        date_frame.pack(fill=tk.X, pady=5)

        tk.Label(date_frame, text="From:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.settlement_from_date = tk.Entry(date_frame, font=('Segoe UI', 11), width=12)
        self.settlement_from_date.pack(side=tk.LEFT, padx=5)
        self.settlement_from_date.insert(0, (date.today() - timedelta(days=30)).isoformat())
        self.settlement_from_date.bind('<Return>', lambda e: self.settlement_to_date.focus())

        tk.Label(date_frame, text="To:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.settlement_to_date = tk.Entry(date_frame, font=('Segoe UI', 11), width=12)
        self.settlement_to_date.pack(side=tk.LEFT, padx=5)
        self.settlement_to_date.insert(0, date.today().isoformat())
        self.settlement_to_date.bind('<Return>', lambda e: self.load_settlement_bills())

        filter_btn = tk.Button(date_frame, text="🔍 FILTER",
                               font=('Segoe UI', 10, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.load_settlement_bills, padx=15, pady=2)
        filter_btn.pack(side=tk.LEFT, padx=10)

        # Show unpaid/active bills only checkbox
        self.show_unpaid_only = tk.BooleanVar(value=True)
        unpaid_check = ttk.Checkbutton(filter_frame, text="Show only unpaid bills",
                                       variable=self.show_unpaid_only,
                                       command=self.load_settlement_bills)
        unpaid_check.pack(anchor='w', pady=5)

        # Instructions
        tk.Label(filter_frame,
                 text="💰 Select a bill and click SETTLE to adjust payment amount. Difference will be recorded as discount.",
                 font=('Segoe UI', 10), bg='white', fg='#2e86c1', wraplength=800).pack(pady=5)

        # Treeview frame
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        columns = ('ID', 'Bill #', 'Date', 'Customer', 'Table/Room', 'Original Amount', 'Status', 'Payment')
        self.settlement_tree = ttk.Treeview(tree_container, columns=columns,
                                            yscrollcommand=v_scrollbar.set,
                                            xscrollcommand=h_scrollbar.set,
                                            height=15)

        v_scrollbar.config(command=self.settlement_tree.yview)
        h_scrollbar.config(command=self.settlement_tree.xview)

        for col in columns:
            self.settlement_tree.heading(col, text=col, anchor=tk.W)
            self.settlement_tree.column(col, width=120)

        self.settlement_tree.column('ID', width=50)
        self.settlement_tree.column('Bill #', width=180)
        self.settlement_tree.column('Customer', width=150)
        self.settlement_tree.column('Original Amount', width=120)

        self.settlement_tree.pack(fill=tk.BOTH, expand=True)

        self.settlement_tree.bind('<Double-Button-1>', lambda e: self.open_settlement_dialog())

        # Button frame
        button_frame = tk.Frame(parent, bg='white')
        button_frame.pack(fill=tk.X, pady=10)

        settle_btn = tk.Button(button_frame, text="💰 SETTLE SELECTED BILL",
                               font=('Segoe UI', 12, 'bold'),
                               bg='#f39c12', fg='black', relief='flat', cursor='hand2',
                               command=self.open_settlement_dialog, padx=20, pady=8)
        settle_btn.pack(side=tk.LEFT, padx=5)

        refresh_btn = tk.Button(button_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 12, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_settlement_bills, padx=20, pady=8)
        refresh_btn.pack(side=tk.LEFT, padx=5)

        # Load bills
        self.load_settlement_bills()

    def create_pending_bills_popup(self, parent):
        """Create pending bills screen in popup"""
        # Filter frame
        filter_frame = tk.LabelFrame(parent, text="Filter Pending Bills",
                                     font=('Segoe UI', 11, 'bold'),
                                     bg='white', fg='#6a4334', padx=15, pady=10)
        filter_frame.pack(fill=tk.X, pady=(0, 20))

        # Bill Number filter
        row_frame = tk.Frame(filter_frame, bg='white')
        row_frame.pack(fill=tk.X, pady=5)

        tk.Label(row_frame, text="Bill Number:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.pending_bill_filter = tk.Entry(row_frame, font=('Segoe UI', 11), width=20)
        self.pending_bill_filter.pack(side=tk.LEFT, padx=5)
        self.pending_bill_filter.bind('<Return>', lambda e: self.filter_pending_bills())

        search_btn = tk.Button(row_frame, text="🔍 SEARCH",
                               font=('Segoe UI', 10, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.filter_pending_bills, padx=15, pady=2)
        search_btn.pack(side=tk.LEFT, padx=5)

        clear_btn = tk.Button(row_frame, text="🔄 CLEAR",
                              font=('Segoe UI', 10, 'bold'),
                              bg='#95a5a6', fg='black', relief='flat',
                              command=self.clear_pending_filter, padx=15, pady=2)
        clear_btn.pack(side=tk.LEFT, padx=5)

        refresh_btn = tk.Button(row_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 10, 'bold'),
                                bg='#27ae60', fg='black', relief='flat',
                                command=self.load_pending_bills, padx=15, pady=2)
        refresh_btn.pack(side=tk.RIGHT, padx=5)

        # Instructions
        tk.Label(filter_frame,
                 text="⏳ These bills are pending payment. Select a bill and click MARK AS PAID to convert to paid.",
                 font=('Segoe UI', 10), bg='white', fg='#2e86c1', wraplength=800).pack(pady=5)

        # Action buttons
        action_frame = tk.Frame(parent, bg='white')
        action_frame.pack(fill=tk.X, pady=(0, 10))

        view_btn = tk.Button(action_frame, text="👁️ VIEW BILL",
                             font=('Segoe UI', 11, 'bold'),
                             bg='#3498db', fg='black', relief='flat', cursor='hand2',
                             command=self.view_selected_pending_bill, padx=15, pady=5)
        view_btn.pack(side=tk.LEFT, padx=5)

        mark_paid_btn = tk.Button(action_frame, text="💰 MARK AS PAID",
                                  font=('Segoe UI', 11, 'bold'),
                                  bg='#f39c12', fg='black', relief='flat', cursor='hand2',
                                  command=self.mark_pending_as_paid_dialog, padx=15, pady=5)
        mark_paid_btn.pack(side=tk.LEFT, padx=5)

        # Treeview
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        columns = ('ID', 'Bill #', 'Date', 'Customer', 'Amount', 'Reference Name', 'Reference Phone', 'Status')
        self.pending_tree = ttk.Treeview(tree_container, columns=columns,
                                         yscrollcommand=v_scrollbar.set,
                                         xscrollcommand=h_scrollbar.set,
                                         height=15)

        v_scrollbar.config(command=self.pending_tree.yview)
        h_scrollbar.config(command=self.pending_tree.xview)

        for col in columns:
            self.pending_tree.heading(col, text=col, anchor=tk.W)
            self.pending_tree.column(col, width=120)

        self.pending_tree.column('ID', width=50)
        self.pending_tree.column('Bill #', width=180)
        self.pending_tree.column('Customer', width=150)
        self.pending_tree.column('Reference Name', width=150)
        self.pending_tree.column('Amount', width=100)

        self.pending_tree.bind('<Double-Button-1>', lambda e: self.view_selected_pending_bill())

        self.pending_tree.pack(fill=tk.BOTH, expand=True)

        self.load_pending_bills()

    def load_pending_bills(self):
        """Load pending bills into tree"""
        if not hasattr(self, 'pending_tree'):
            return

        for item in self.pending_tree.get_children():
            self.pending_tree.delete(item)

        try:
            pending_bills = self.restaurant.get_pending_bills('pending')

            for pb in pending_bills:
                values = (
                    pb['id'],
                    pb['bill_number'],
                    pb['created_at'][:10] if pb['created_at'] else '',
                    pb['customer_name'],
                    f"₹{pb['pending_amount']:.2f}",
                    pb['reference_name'],
                    pb['reference_phone'],
                    pb['status'].upper()
                )
                self.pending_tree.insert('', tk.END, values=values)

        except Exception as e:
            self.show_error(f"Error loading pending bills: {str(e)}")

    def filter_pending_bills(self):
        """Filter pending bills by bill number"""
        bill_number = self.pending_bill_filter.get().strip()
        if not bill_number:
            self.load_pending_bills()
            return

        try:
            for item in self.pending_tree.get_children():
                self.pending_tree.delete(item)

            # Get pending bills
            pending_bills = self.restaurant.get_pending_bills('pending')

            # Filter by bill number
            filtered = [pb for pb in pending_bills if bill_number.lower() in pb['bill_number'].lower()]

            for pb in filtered:
                values = (
                    pb['id'],
                    pb['bill_number'],
                    pb['created_at'][:10] if pb['created_at'] else '',
                    pb['customer_name'],
                    f"₹{pb['pending_amount']:.2f}",
                    pb['reference_name'],
                    pb['reference_phone'],
                    pb['status'].upper()
                )
                self.pending_tree.insert('', tk.END, values=values)

        except Exception as e:
            self.show_error(f"Error filtering pending bills: {str(e)}")

    def clear_pending_filter(self):
        """Clear pending bills filter"""
        self.pending_bill_filter.delete(0, tk.END)
        self.load_pending_bills()

    def view_selected_pending_bill(self):
        """View selected pending bill details"""
        selection = self.pending_tree.selection()
        if not selection:
            self.show_warning("Please select a pending bill to view")
            return

        pending_id = self.pending_tree.item(selection[0])['values'][0]
        pending = self.restaurant.get_pending_bill_details(pending_id)

        if not pending:
            self.show_error("Pending bill not found")
            return

        # Show details dialog
        dialog = tk.Toplevel(self.current_popup)
        dialog.title(f"Pending Bill Details - {pending['bill_number']}")
        dialog.geometry("600x500")
        dialog.transient(self.current_popup)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 600, 500)

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="PENDING BILL DETAILS", font=('Segoe UI', 16, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        # Bill Information
        info_frame = tk.LabelFrame(main_frame, text="Bill Information",
                                   font=('Segoe UI', 12, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        info_frame.pack(fill=tk.X, pady=10)

        info_text = f"""
   Bill Number: {pending['bill_number']}
   Order Number: {pending['order_number']}
   Date: {pending['bill_date']}
   Customer: {pending['customer_name']}
   Table/Room: {pending.get('table_number') or pending.get('room_number', 'N/A')}
   Total Amount: ₹{pending['total_amount']:.2f}
   Pending Amount: ₹{pending['pending_amount']:.2f}
       """

        tk.Label(info_frame, text=info_text, font=('Segoe UI', 11),
                 bg='white', fg='#2e86c1', justify=tk.LEFT).pack(anchor='w')

        # Reference Information
        ref_frame = tk.LabelFrame(main_frame, text="Reference Information",
                                  font=('Segoe UI', 12, 'bold'),
                                  bg='white', fg='#6a4334', padx=15, pady=10)
        ref_frame.pack(fill=tk.X, pady=10)

        ref_text = f"""
   Reference Name: {pending['reference_name']}
   Reference Phone: {pending['reference_phone']}
   Reference Notes: {pending.get('reference_notes', 'N/A')}
   Created At: {pending['created_at'][:16] if pending['created_at'] else 'N/A'}
       """

        tk.Label(ref_frame, text=ref_text, font=('Segoe UI', 11),
                 bg='white', fg='#e67e22', justify=tk.LEFT).pack(anchor='w')

        # Button frame
        button_frame = tk.Frame(main_frame, bg='white')
        button_frame.pack(pady=20)

        close_btn = tk.Button(button_frame, text="CLOSE", font=('Segoe UI', 12, 'bold'),
                              bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                              command=dialog.destroy, padx=30, pady=8)
        close_btn.pack()

    def mark_pending_as_paid_dialog(self):
        """Open dialog to mark pending bill as paid"""
        selection = self.pending_tree.selection()
        if not selection:
            self.show_warning("Please select a pending bill to mark as paid")
            return

        pending_id = self.pending_tree.item(selection[0])['values'][0]
        pending = self.restaurant.get_pending_bill_details(pending_id)

        if not pending:
            self.show_error("Pending bill not found")
            return

        dialog = tk.Toplevel(self.current_popup)
        dialog.title(f"Mark as Paid - {pending['bill_number']}")
        dialog.geometry("500x450")
        dialog.transient(self.current_popup)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 500, 450)

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="MARK AS PAID", font=('Segoe UI', 16, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        # Bill info
        info_frame = tk.Frame(main_frame, bg='white')
        info_frame.pack(fill=tk.X, pady=10)

        tk.Label(info_frame, text=f"Bill: {pending['bill_number']}", font=('Segoe UI', 12, 'bold'),
                 bg='white', fg='#2e86c1').pack(anchor='w')
        tk.Label(info_frame, text=f"Pending Amount: ₹{pending['pending_amount']:.2f}", font=('Segoe UI', 11),
                 bg='white', fg='#c0392b').pack(anchor='w', pady=2)
        tk.Label(info_frame, text=f"Reference: {pending['reference_name']} ({pending['reference_phone']})",
                 font=('Segoe UI', 10), bg='white', fg='#7f8c8d').pack(anchor='w', pady=2)

        # Payment form
        form_frame = tk.LabelFrame(main_frame, text="Payment Details",
                                   font=('Segoe UI', 12, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        form_frame.pack(fill=tk.X, pady=10)

        row = 0
        tk.Label(form_frame, text="Amount Paid (₹):", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        amount_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=20)
        amount_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        amount_entry.insert(0, str(pending['pending_amount']))
        row += 1

        tk.Label(form_frame, text="Payment Method:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        method_var = tk.StringVar(value='cash')
        method_combo = ttk.Combobox(form_frame, textvariable=method_var,
                                    values=['cash', 'card', 'upi'], state='readonly',
                                    width=18, font=('Segoe UI', 11))
        method_combo.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        row += 1

        tk.Label(form_frame, text="Notes:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='ne')
        notes_text = tk.Text(form_frame, font=('Segoe UI', 11), width=30, height=3)
        notes_text.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        notes_text.insert('1.0', f"Payment received for pending bill. Reference: {pending['reference_name']}")
        row += 1

        # Discount preview
        discount_preview = tk.Label(form_frame, text="", font=('Segoe UI', 11, 'bold'),
                                    bg='white', fg='#27ae60')
        discount_preview.grid(row=row, column=0, columnspan=2, pady=10)

        def update_preview(event=None):
            try:
                paid = float(amount_entry.get())
                if paid < pending['pending_amount']:
                    discount = pending['pending_amount'] - paid
                    discount_percent = (discount / pending['pending_amount']) * 100
                    discount_preview.config(
                        text=f"Discount: ₹{discount:.2f} ({discount_percent:.1f}%)",
                        fg='#c0392b'
                    )
                elif paid == pending['pending_amount']:
                    discount_preview.config(text="Full payment - no discount", fg='#27ae60')
                elif paid > pending['pending_amount']:
                    discount_preview.config(text="Amount cannot exceed pending amount", fg='#c0392b')
                else:
                    discount_preview.config(text="", fg='black')
            except:
                discount_preview.config(text="", fg='black')

        amount_entry.bind('<KeyRelease>', update_preview)

        def mark_paid_action():
            try:
                paid_amount = float(amount_entry.get())
                if paid_amount <= 0:
                    raise ValueError("Amount must be positive")
                if paid_amount > pending['pending_amount']:
                    raise ValueError(f"Amount cannot exceed pending amount ₹{pending['pending_amount']:.2f}")

                payment_data = {
                    'amount_paid': paid_amount,
                    'payment_method': method_var.get(),
                    'notes': notes_text.get('1.0', tk.END).strip()
                }

                self.restaurant.mark_pending_as_paid(pending_id, payment_data)

                discount = pending['pending_amount'] - paid_amount
                if discount > 0:
                    self.show_info(f"✅ Pending bill marked as paid!\n\n"
                                   f"Original Pending: ₹{pending['pending_amount']:.2f}\n"
                                   f"Amount Paid: ₹{paid_amount:.2f}\n"
                                   f"Discount Given: ₹{discount:.2f}")
                else:
                    self.show_info(f"✅ Pending bill marked as paid!\n\nAmount Paid: ₹{paid_amount:.2f}")

                dialog.destroy()
                self.load_pending_bills()

            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(f"Error: {str(e)}")

        button_frame = tk.Frame(main_frame, bg='white')
        button_frame.pack(pady=20)

        mark_btn = tk.Button(button_frame, text="💰 MARK AS PAID", font=('Segoe UI', 12, 'bold'),
                             bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                             command=mark_paid_action, padx=30, pady=8)
        mark_btn.pack(side=tk.LEFT, padx=10)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                               command=dialog.destroy, padx=30, pady=8)
        cancel_btn.pack(side=tk.LEFT, padx=10)

    def load_settlement_bills(self):
        """Load bills for settlement."""
        if not hasattr(self, 'settlement_tree'):
            return

        for item in self.settlement_tree.get_children():
            self.settlement_tree.delete(item)

        try:
            from_date = self.settlement_from_date.get()
            to_date = self.settlement_to_date.get()

            # Get all bills
            bills = self.restaurant.get_all_bills(from_date, to_date)

            for bill in bills:
                # Skip if showing only unpaid and bill is already settled
                if self.show_unpaid_only.get() and bill.get('settled_at'):
                    continue

                # Skip complimentary bills as they're already at zero
                if bill['is_complimentary']:
                    continue

                values = (
                    bill['id'],
                    bill['bill_number'],
                    bill['bill_date'],
                    bill['customer_name'],
                    bill.get('table_number') or bill.get('room_number', ''),
                    f"₹{bill['total_amount']:.2f}",
                    'SETTLED' if bill.get('settled_at') else 'PENDING',
                    bill['payment_method'].upper()
                )

                tags = ('settled',) if bill.get('settled_at') else ('pending',)
                self.settlement_tree.insert('', tk.END, values=values, tags=tags)

            # Configure tags
            self.settlement_tree.tag_configure('settled', background='#d5f5e3')  # Light green
            self.settlement_tree.tag_configure('pending', background='#fdebd0')  # Light orange

        except Exception as e:
            self.show_error(f"Error loading bills: {str(e)}")

    def filter_settlement_bills(self):
        """Filter settlement bills by bill number."""
        bill_number = self.settlement_bill_filter.get().strip()
        if bill_number:
            try:
                for item in self.settlement_tree.get_children():
                    self.settlement_tree.delete(item)

                bills = self.restaurant.get_all_bills(bill_number=bill_number)

                for bill in bills:
                    if self.show_unpaid_only.get() and bill.get('settled_at'):
                        continue
                    if bill['is_complimentary']:
                        continue

                    values = (
                        bill['id'],
                        bill['bill_number'],
                        bill['bill_date'],
                        bill['customer_name'],
                        bill.get('table_number') or bill.get('room_number', ''),
                        f"₹{bill['total_amount']:.2f}",
                        'SETTLED' if bill.get('settled_at') else 'PENDING',
                        bill['payment_method'].upper()
                    )

                    tags = ('settled',) if bill.get('settled_at') else ('pending',)
                    self.settlement_tree.insert('', tk.END, values=values, tags=tags)

            except Exception as e:
                self.show_error(f"Error searching bills: {str(e)}")

    def clear_settlement_filter(self):
        """Clear settlement filter."""
        self.settlement_bill_filter.delete(0, tk.END)
        self.load_settlement_bills()

    def open_settlement_dialog(self):
        """Open settlement dialog for selected bill."""
        selection = self.settlement_tree.selection()
        if not selection:
            self.show_warning("Please select a bill to settle")
            return

        # Get bill details
        bill_values = self.settlement_tree.item(selection[0])['values']
        bill_id = bill_values[0]
        bill_number = bill_values[1]
        original_total = float(bill_values[5].replace('₹', ''))

        # Check if already settled
        if bill_values[6] == 'SETTLED':
            if not self.ask_confirmation(f"Bill #{bill_number} is already settled. Do you want to re-settle it?"):
                return

        # Create settlement dialog
        dialog = tk.Toplevel(self.current_popup if self.current_popup else self.root)
        dialog.title(f"Settle Bill - {bill_number}")
        dialog.geometry("700x550")
        dialog.transient(self.current_popup if self.current_popup else self.root)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 700, 550)

        # Bind Escape to close
        dialog.bind('<Escape>', lambda e: dialog.destroy())

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="SETTLE BILL", font=('Segoe UI', 18, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        # Bill info
        info_frame = tk.LabelFrame(main_frame, text="Bill Information",
                                   font=('Segoe UI', 11, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        info_frame.pack(fill=tk.X, pady=(0, 20))

        tk.Label(info_frame, text=f"Bill Number: {bill_number}", font=('Segoe UI', 11),
                 bg='white', fg='#2e86c1').pack(anchor='w', pady=2)
        tk.Label(info_frame, text=f"Customer: {bill_values[3]}", font=('Segoe UI', 11),
                 bg='white', fg='#2e86c1').pack(anchor='w', pady=2)
        tk.Label(info_frame, text=f"Original Amount: ₹{original_total:.2f}", font=('Segoe UI', 11, 'bold'),
                 bg='white', fg='#c0392b').pack(anchor='w', pady=2)

        # Settlement form
        form_frame = tk.LabelFrame(main_frame, text="Settlement Details",
                                   font=('Segoe UI', 11, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        form_frame.pack(fill=tk.X, pady=(0, 20))

        row = 0
        tk.Label(form_frame, text="Amount Received (₹):", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        settle_amount_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=20)
        settle_amount_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        settle_amount_entry.insert(0, str(original_total))
        row += 1

        tk.Label(form_frame, text="Payment Method:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        settle_method_var = tk.StringVar(value='cash')
        method_combo = ttk.Combobox(form_frame, textvariable=settle_method_var,
                                    values=['cash', 'card', 'upi'], state='readonly',
                                    width=18, font=('Segoe UI', 11))
        method_combo.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        row += 1

        tk.Label(form_frame, text="Notes:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='ne')
        settle_notes = tk.Text(form_frame, font=('Segoe UI', 11), width=30, height=3)
        settle_notes.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        settle_notes.insert('1.0', f"Customer paid ₹{original_total:.2f} - settled amount")
        row += 1

        # Discount preview
        discount_preview = tk.Label(form_frame, text="", font=('Segoe UI', 11, 'bold'),
                                    bg='white', fg='#27ae60')
        discount_preview.grid(row=row, column=0, columnspan=2, pady=10)

        def update_discount_preview(event=None):
            try:
                settled = float(settle_amount_entry.get())
                if 0 < settled < original_total:
                    discount = original_total - settled
                    discount_percent = (discount / original_total) * 100
                    discount_preview.config(
                        text=f"Discount: ₹{discount:.2f} ({discount_percent:.1f}%)",
                        fg='#c0392b'
                    )
                elif settled == original_total:
                    discount_preview.config(text="No discount", fg='#27ae60')
                elif settled > original_total:
                    discount_preview.config(text="Amount cannot exceed original", fg='#c0392b')
                else:
                    discount_preview.config(text="Invalid amount", fg='#c0392b')
            except:
                discount_preview.config(text="", fg='black')

        settle_amount_entry.bind('<KeyRelease>', update_discount_preview)

        def settle_action():
            try:
                settled_amount = float(settle_amount_entry.get())
                if settled_amount <= 0:
                    raise ValueError("Amount must be positive")
                if settled_amount > original_total:
                    raise ValueError(f"Settled amount cannot exceed original amount ₹{original_total:.2f}")

                settlement_data = {
                    'settled_amount': settled_amount,
                    'payment_method': settle_method_var.get(),
                    'notes': settle_notes.get('1.0', tk.END).strip()
                }

                self.restaurant.settle_bill(bill_id, settlement_data)

                # Show summary
                discount = original_total - settled_amount
                if discount > 0:
                    self.show_info(f"✅ Bill settled successfully!\n\n"
                                   f"Original Amount: ₹{original_total:.2f}\n"
                                   f"Amount Paid: ₹{settled_amount:.2f}\n"
                                   f"Discount Given: ₹{discount:.2f}\n"
                                   f"Discount %: {(discount / original_total * 100):.1f}%\n\n"
                                   f"This discount will be reflected in today's sales summary.")
                else:
                    self.show_info(f"✅ Bill settled successfully!\n\nAmount Paid: ₹{settled_amount:.2f}")

                dialog.destroy()
                self.load_settlement_bills()
                self.load_settlement_bills()  # Refresh twice to ensure update

            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(f"Error settling bill: {str(e)}")

        # Button frame
        button_frame = tk.Frame(main_frame, bg='white')
        button_frame.pack(pady=20)

        settle_btn = tk.Button(button_frame, text="💰 SETTLE BILL", font=('Segoe UI', 12, 'bold'),
                               bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                               command=settle_action, padx=30, pady=10)
        settle_btn.pack(side=tk.LEFT, padx=10)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                               command=dialog.destroy, padx=30, pady=10)
        cancel_btn.pack(side=tk.LEFT, padx=10)

        # Bind Enter key
        settle_btn.bind('<Return>', lambda e: settle_action())

    # ==================== POPUP CONTENT METHODS ====================
    # These methods will call the existing screen methods but adapted for popup

    def create_dashboard_popup(self, parent):
        """Create dashboard in popup."""
        # Call existing dashboard logic but adapted for popup
        self.create_dashboard_in_popup(parent)

    def create_new_order_popup(self, parent):
        """Create new order in popup."""
        self.create_new_order_in_popup(parent)

    def create_active_orders_popup(self, parent):
        """Create active orders in popup."""
        self.create_active_orders_in_popup(parent)

    def create_generate_bill_popup(self, parent):
        """Create generate bill in popup."""
        self.create_generate_bill_in_popup(parent)

    def create_reports_popup(self, parent):
        """Create reports in popup."""
        self.create_reports_in_popup(parent)

    def create_restaurant_management_popup(self, parent):
        """Create restaurant management in popup."""
        self.create_restaurant_management_in_popup(parent)

    def create_menu_management_popup(self, parent):
        """Create menu management in popup."""
        self.create_menu_management_in_popup(parent)

    def create_all_bills_popup(self, parent):
        """Create all bills in popup."""
        self.create_all_bills_in_popup(parent)

    def create_comp_bills_popup(self, parent):
        """Create complimentary bills in popup."""
        self.create_comp_bills_in_popup(parent)

    def create_room_service_bills_popup(self, parent):
        """Create room service bills in popup."""
        self.create_room_service_bills_in_popup(parent)

    def create_restaurant_bills_popup(self, parent):
        """Create restaurant bills in popup."""
        self.create_restaurant_bills_in_popup(parent)

    def create_users_popup(self, parent):
        """Create user management in popup."""
        self.create_users_in_popup(parent)

    def create_settings_popup(self, parent):
        """Create settings in popup."""
        self.create_settings_in_popup(parent)

    # ==================== ADAPTED EXISTING METHODS FOR POPUPS ====================

    def create_dashboard_in_popup(self, parent):
        """Create dashboard content adapted for popup."""
        # Get report data
        report = self.restaurant.get_daily_sales_report()

        # Stats cards
        stats_frame = tk.Frame(parent, bg='white')
        stats_frame.pack(fill=tk.X, pady=20)

        stats = [
            ("Today's Bills", report['total_bills'], "#2e86c1"),
            ("Restaurant Bills", report['restaurant_bills'], "#27ae60"),
            ("Room Service Bills", report['room_bills'], "#16a085"),
            ("Restaurant Total", f"₹{report['restaurant_total']:.2f}", "#f39c12"),
            ("Room Service Total", f"₹{report['room_total']:.2f}", "#e67e22"),
            ("Comp Amount", f"₹{report['complimentary_total']:.2f}", "#c0392b")
        ]

        row = 0
        col = 0
        for i, (title, value, color) in enumerate(stats):
            card = tk.Frame(stats_frame, bg=color, relief=tk.RAISED, bd=1)
            card.grid(row=row, column=col, padx=5, pady=5, ipadx=10, ipady=10, sticky='nsew')

            tk.Label(card, text=title, font=('Segoe UI', 10),
                     bg=color, fg='black').pack()
            tk.Label(card, text=str(value), font=('Segoe UI', 14, 'bold'),
                     bg=color, fg='black').pack()

            col += 1
            if col >= 3:
                col = 0
                row += 1

        for i in range(3):
            stats_frame.grid_columnconfigure(i, weight=1)

        # Active orders
        orders_frame = tk.LabelFrame(parent, text="Active Orders",
                                     font=('Segoe UI', 14, 'bold'),
                                     bg='white', fg='#6a4334', padx=20, pady=15)
        orders_frame.pack(fill=tk.BOTH, expand=True, pady=20)

        active_orders = self.restaurant.get_active_orders()

        if active_orders:
            tree_frame = tk.Frame(orders_frame, bg='white')
            tree_frame.pack(fill=tk.BOTH, expand=True)

            tree_container = tk.Frame(tree_frame, bg='white')
            tree_container.pack(fill=tk.BOTH, expand=True)

            v_scrollbar = ttk.Scrollbar(tree_container)
            v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            columns = ('Order #', 'Customer', 'Restaurant', 'Table/Room', 'Items', 'Total', 'Time', 'Type')
            tree = ttk.Treeview(tree_container, columns=columns, yscrollcommand=v_scrollbar.set, height=8)
            v_scrollbar.config(command=tree.yview)

            for col in columns:
                tree.heading(col, text=col, anchor=tk.W)
                tree.column(col, width=100)

            tree.column('Order #', width=150)
            tree.column('Customer', width=150)
            tree.column('Total', width=100)

            tree.pack(fill=tk.BOTH, expand=True)

            for order in active_orders:
                items = self.restaurant.get_order_items(order['id'])
                item_count = len(items)
                values = (
                    order['order_number'],
                    order['customer_name'],
                    order.get('restaurant_name', ''),
                    order.get('table_number') or order.get('room_number', ''),
                    item_count,
                    f"₹{order['total_amount']:.2f}",
                    order['order_time'][11:16] if order['order_time'] else '',
                    order['order_type'].upper()
                )
                tree.insert('', tk.END, values=values)
        else:
            tk.Label(orders_frame, text="No active orders", font=('Segoe UI', 12),
                     bg='white', fg='#7f8c8d').pack(pady=50)

    def create_new_order_in_popup(self, parent):
        """Create new order form adapted for popup."""
        if not self.day_manager.check_today_status():
            tk.Label(parent, text="⚠️ Day is not started. Please start the day first.",
                     font=('Segoe UI', 14, 'bold'), bg='white', fg='#c0392b').pack(pady=50)
            return

        # Notebook for tabs
        notebook = ttk.Notebook(parent)
        notebook.pack(fill=tk.BOTH, expand=True)

        # Restaurant tab
        restaurant_frame = ttk.Frame(notebook)
        notebook.add(restaurant_frame, text="🍽️ Restaurant Order")
        self.create_restaurant_order_form_popup(restaurant_frame)

        # Room service tab
        room_frame = ttk.Frame(notebook)
        notebook.add(room_frame, text="🛎️ Room Service")
        self.create_room_service_form_popup(room_frame)

    def create_restaurant_order_form_popup(self, parent):
        """Create restaurant order form for popup - customer fields optional."""
        form_frame = tk.Frame(parent, bg='white', padx=20, pady=20)
        form_frame.pack(fill=tk.BOTH, expand=True)

        # Restaurant Selection (Required)
        tk.Label(form_frame, text="Select Restaurant *", font=('Segoe UI', 14, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 15), anchor='w')

        restaurants = self.restaurant.get_all_restaurants()
        self.order_restaurant_var = tk.StringVar()
        restaurant_combo = ttk.Combobox(form_frame, textvariable=self.order_restaurant_var,
                                        values=[f"{r['restaurant_code']} - {r['restaurant_name']}" for r in
                                                restaurants],
                                        state='readonly', font=('Segoe UI', 12))
        restaurant_combo.pack(fill=tk.X, pady=(0, 10))
        restaurant_combo.bind('<<ComboboxSelected>>', self.load_tables_for_restaurant_popup)

        # Table Selection (Required)
        tk.Label(form_frame, text="Select Table *", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(anchor='w', pady=(5, 2))
        self.order_table_var = tk.StringVar()
        self.table_combo = ttk.Combobox(form_frame, textvariable=self.order_table_var,
                                        values=[], state='readonly', font=('Segoe UI', 12))
        self.table_combo.pack(fill=tk.X, pady=(0, 20))

        # Customer Name (Optional)
        tk.Label(form_frame, text="Customer Name (Optional)", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(anchor='w', pady=(5, 2))
        self.order_customer_name = tk.Entry(form_frame, font=('Segoe UI', 12))
        self.order_customer_name.pack(fill=tk.X, pady=(0, 10))
        self.order_customer_name.insert(0, "Guest")  # Default value
        self.order_customer_name.bind('<Return>', lambda e: self.order_customer_phone.focus())

        # Phone Number (Optional)
        tk.Label(form_frame, text="Phone Number (Optional)", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(anchor='w', pady=(5, 2))
        self.order_customer_phone = tk.Entry(form_frame, font=('Segoe UI', 12))
        self.order_customer_phone.pack(fill=tk.X, pady=(0, 10))
        self.order_customer_phone.insert(0, "")  # Empty by default
        self.order_customer_phone.bind('<Return>', lambda e: create_btn.focus())

        create_btn = tk.Button(form_frame, text="CREATE ORDER", font=('Segoe UI', 14, 'bold'),
                               bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                               command=self.create_restaurant_order_popup, padx=30, pady=15)
        create_btn.pack(pady=20)

        # Bind Enter key to create button
        create_btn.bind('<Return>', lambda e: self.create_restaurant_order_popup())

    def create_room_service_form_popup(self, parent):
        """Create room service form for popup."""
        form_frame = tk.Frame(parent, bg='white', padx=20, pady=20)
        form_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(form_frame, text="Room Service", font=('Segoe UI', 14, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 15), anchor='w')

        # Guest Name (will be populated from selection)
        tk.Label(form_frame, text="Guest Name", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(anchor='w', pady=(5, 2))
        self.room_guest_name = tk.Entry(form_frame, font=('Segoe UI', 12), state='readonly')
        self.room_guest_name.pack(fill=tk.X, pady=(0, 10))

        # Phone (will be populated from selection)
        tk.Label(form_frame, text="Phone", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(anchor='w', pady=(5, 2))
        self.room_guest_phone = tk.Entry(form_frame, font=('Segoe UI', 12), state='readonly')
        self.room_guest_phone.pack(fill=tk.X, pady=(0, 10))

        tk.Label(form_frame, text="Select Active Room *", font=('Segoe UI', 14, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(15, 15), anchor='w')

        # Listbox with scrollbar
        listbox_frame = tk.Frame(form_frame)
        listbox_frame.pack(fill=tk.X, pady=(0, 10))

        scrollbar = ttk.Scrollbar(listbox_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.room_selection_listbox = tk.Listbox(listbox_frame, font=('Segoe UI', 11), height=8,
                                                 yscrollcommand=scrollbar.set)
        self.room_selection_listbox.pack(fill=tk.X, expand=True)
        scrollbar.config(command=self.room_selection_listbox.yview)

        self.room_selection_listbox.bind('<<ListboxSelect>>', self.load_room_details)

        refresh_btn = tk.Button(form_frame, text="🔄 LOAD ACTIVE ROOMS", font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_active_rooms_popup)
        refresh_btn.pack(pady=5)

        create_btn = tk.Button(form_frame, text="CREATE ROOM SERVICE ORDER", font=('Segoe UI', 14, 'bold'),
                               bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                               command=self.create_room_service_order_popup, padx=30, pady=15)
        create_btn.pack(pady=20)

        # Bind Enter key to create button
        create_btn.bind('<Return>', lambda e: self.create_room_service_order_popup())

        self.load_active_rooms_popup()

    def load_tables_for_restaurant_popup(self, event=None):
        """Load available tables for selected restaurant in popup."""
        selection = self.order_restaurant_var.get()
        if not selection:
            return

        rest_code = selection.split(' - ')[0]
        restaurant = self.restaurant.get_restaurant_by_code(rest_code)

        if restaurant:
            tables = self.restaurant.get_available_tables(restaurant['id'])
            self.table_combo['values'] = [t['table_number'] for t in tables]

    def load_active_rooms_popup(self):
        """Load active room bookings in popup."""
        self.room_selection_listbox.delete(0, tk.END)

        rooms = self.restaurant.get_active_room_bookings()

        if rooms:
            for room in rooms:
                display = f"Room {room['room_number']} - {room['guest_name']} (Check-in: {room['check_in_time'][:10]})"
                self.room_selection_listbox.insert(tk.END, display)
        else:
            self.room_selection_listbox.insert(tk.END, "No active room bookings found")

    def load_room_details(self, event=None):
        """Load room details when selected."""
        selection = self.room_selection_listbox.curselection()
        if not selection:
            return

        room_text = self.room_selection_listbox.get(selection[0])
        if "No active room bookings" in room_text:
            return

        parts = room_text.split(' - ')
        if len(parts) >= 2:
            room_number = parts[0].replace('Room ', '')
            guest_name = parts[1].split(' (')[0]

            self.room_guest_name.config(state='normal')
            self.room_guest_name.delete(0, tk.END)
            self.room_guest_name.insert(0, guest_name)
            self.room_guest_name.config(state='readonly')

            self.room_guest_phone.config(state='normal')
            self.room_guest_phone.delete(0, tk.END)
            self.room_guest_phone.insert(0, "Contact at front desk")
            self.room_guest_phone.config(state='readonly')

            self.selected_room_number = room_number

    def create_restaurant_order_popup(self):
        """Create a new restaurant order from popup - with optional customer fields."""
        try:
            restaurant_selection = self.order_restaurant_var.get()
            if not restaurant_selection:
                raise ValueError("Please select a restaurant")

            rest_code = restaurant_selection.split(' - ')[0]
            restaurant = self.restaurant.get_restaurant_by_code(rest_code)

            table_number = self.order_table_var.get()
            if not table_number:
                raise ValueError("Please select a table")

            tables = self.restaurant.get_tables_for_restaurant(restaurant['id'])
            table_id = None
            for t in tables:
                if t['table_number'] == table_number:
                    table_id = t['id']
                    break

            # Get customer name (use default if empty)
            customer_name = self.order_customer_name.get().strip()
            if not customer_name:
                # Use table number as default customer name
                customer_name = f"Table {table_number}"

            # Phone number is optional
            customer_phone = self.order_customer_phone.get().strip()

            order_data = {
                'customer_name': customer_name,
                'customer_phone': customer_phone,
                'restaurant_id': restaurant['id'],
                'table_id': table_id,
                'order_type': 'restaurant'
            }

            order_id, order_number = self.restaurant.create_order(order_data)

            self.show_info(f"✅ Order created successfully!\n\nOrder #: {order_number}")

            # Clear form
            self.order_customer_name.delete(0, tk.END)
            self.order_customer_name.insert(0, "Guest")  # Reset to default
            self.order_customer_phone.delete(0, tk.END)
            self.order_restaurant_var.set('')
            self.table_combo.set('')
            self.table_combo['values'] = []

            # Open order for items in new popup
            self.open_order_for_items_popup(order_id)

        except Exception as e:
            self.show_error(str(e))

    def create_room_service_order_popup(self):
        """Create a new room service order from popup."""
        try:
            selection = self.room_selection_listbox.curselection()
            if not selection:
                raise ValueError("Please select a room")

            room_text = self.room_selection_listbox.get(selection[0])
            if "No active room bookings" in room_text:
                raise ValueError("No valid room selected")

            parts = room_text.split(' - ')
            if len(parts) < 2:
                raise ValueError("Invalid room selection")

            room_number = parts[0].replace('Room ', '')
            guest_name = parts[1].split(' (')[0]

            restaurants = self.restaurant.get_all_restaurants()
            if not restaurants:
                raise ValueError("No restaurants configured")

            order_data = {
                'customer_name': guest_name,  # Guest name from room booking
                'customer_phone': '',  # Phone number optional
                'restaurant_id': restaurants[0]['id'],
                'room_number': room_number,
                'order_type': 'room_service'
            }

            order_id, order_number = self.restaurant.create_order(order_data)

            self.show_info(f"✅ Room service order created successfully!\n\nOrder #: {order_number}")

            # Clear selection
            self.room_selection_listbox.selection_clear(0, tk.END)
            self.room_guest_name.config(state='normal')
            self.room_guest_name.delete(0, tk.END)
            self.room_guest_name.config(state='readonly')
            self.room_guest_phone.config(state='normal')
            self.room_guest_phone.delete(0, tk.END)
            self.room_guest_phone.config(state='readonly')

            # Open order for items in new popup
            self.open_order_for_items_popup(order_id)

        except Exception as e:
            self.show_error(str(e))

    def open_order_for_items_popup(self, order_id):
        """Open order details popup for adding items with improved item selection."""
        order = self.restaurant.get_order_by_id(order_id)
        if not order:
            self.show_error("Order not found")
            return

        dialog = tk.Toplevel(self.current_popup if self.current_popup else self.root)
        dialog.title(f"Order: {order['order_number']}")
        dialog.geometry("1400x800")
        dialog.transient(self.current_popup if self.current_popup else self.root)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 1400, 800)

        # Bind Escape to close
        dialog.bind('<Escape>', lambda e: dialog.destroy())

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header
        header_frame = tk.Frame(main_frame, bg='white')
        header_frame.pack(fill=tk.X, pady=(0, 20))

        tk.Label(header_frame, text=f"ORDER: {order['order_number']}",
                 font=('Segoe UI', 18, 'bold'), bg='white', fg='#6a4334').pack(side=tk.LEFT)

        tk.Label(header_frame,
                 text=f"Customer: {order['customer_name']} | {order.get('table_number') or order.get('room_number', '')}",
                 font=('Segoe UI', 12), bg='white', fg='#2e86c1').pack(side=tk.RIGHT)

        # Create notebook for menu organization
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        # Menu tab
        menu_tab = ttk.Frame(notebook)
        notebook.add(menu_tab, text="🍽️ MENU ITEMS")

        # Order items tab
        order_tab = ttk.Frame(notebook)
        notebook.add(order_tab, text="📋 ORDER ITEMS")

        # ========== MENU TAB ==========
        # Quick add frame with improved design
        quick_frame = tk.LabelFrame(menu_tab, text="Quick Add Item", font=('Segoe UI', 12, 'bold'),
                                    bg='white', fg='#6a4334', padx=15, pady=10)
        quick_frame.pack(fill=tk.X, pady=5)

        # Create columns for item entry
        columns_frame = tk.Frame(quick_frame, bg='white')
        columns_frame.pack(fill=tk.X, pady=5)

        # Headers
        tk.Label(columns_frame, text="Item No.", font=('Segoe UI', 10, 'bold'),
                 bg='white', fg='#6a4334', width=8).grid(row=0, column=0, padx=2)
        tk.Label(columns_frame, text="Item Name/ID", font=('Segoe UI', 10, 'bold'),
                 bg='white', fg='#6a4334', width=30).grid(row=0, column=1, padx=2)
        tk.Label(columns_frame, text="Quantity", font=('Segoe UI', 10, 'bold'),
                 bg='white', fg='#6a4334', width=10).grid(row=0, column=2, padx=2)
        tk.Label(columns_frame, text="Price", font=('Segoe UI', 10, 'bold'),
                 bg='white', fg='#6a4334', width=10).grid(row=0, column=3, padx=2)
        tk.Label(columns_frame, text="Total", font=('Segoe UI', 10, 'bold'),
                 bg='white', fg='#6a4334', width=12).grid(row=0, column=4, padx=2)
        tk.Label(columns_frame, text="", width=10).grid(row=0, column=5, padx=2)  # For Add button

        # Create entry row
        entry_frame = tk.Frame(quick_frame, bg='white')
        entry_frame.pack(fill=tk.X, pady=5)

        # Auto-incrementing item number
        self.current_item_no = tk.StringVar(value="1")
        tk.Label(entry_frame, textvariable=self.current_item_no, font=('Segoe UI', 11, 'bold'),
                 bg='white', fg='#27ae60', width=8).grid(row=0, column=0, padx=2)

        # Item name/ID entry with search functionality
        self.quick_item_name = tk.Entry(entry_frame, font=('Segoe UI', 11), width=30)
        self.quick_item_name.grid(row=0, column=1, padx=2)
        self.quick_item_name.bind('<KeyRelease>', lambda e: self.search_items_on_type(order_id))
        self.quick_item_name.bind('<Return>', lambda e: self.quick_quantity.focus())

        # Quantity entry
        self.quick_quantity = tk.Entry(entry_frame, font=('Segoe UI', 11), width=10)
        self.quick_quantity.grid(row=0, column=2, padx=2)
        self.quick_quantity.insert(0, '1')
        self.quick_quantity.bind('<Return>', lambda e: self.quick_add_by_search(order_id))

        # Price (auto-filled when item selected)
        self.quick_price_var = tk.StringVar(value="₹0.00")
        tk.Label(entry_frame, textvariable=self.quick_price_var, font=('Segoe UI', 11),
                 bg='white', fg='#2e86c1', width=10).grid(row=0, column=3, padx=2)

        # Total (auto-calculated)
        self.quick_total_var = tk.StringVar(value="₹0.00")
        tk.Label(entry_frame, textvariable=self.quick_total_var, font=('Segoe UI', 11, 'bold'),
                 bg='white', fg='#27ae60', width=12).grid(row=0, column=4, padx=2)

        # Add button
        quick_add_btn = tk.Button(entry_frame, text="➕ ADD", font=('Segoe UI', 11, 'bold'),
                                  bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                                  command=lambda: self.quick_add_by_search(order_id), padx=15, pady=2)
        quick_add_btn.grid(row=0, column=5, padx=5)

        # Bind quantity change to update total
        self.quick_quantity.bind('<KeyRelease>', lambda e: self.update_quick_total())

        # Item search results listbox
        search_frame = tk.Frame(quick_frame, bg='white')
        search_frame.pack(fill=tk.X, pady=5)

        self.search_listbox = tk.Listbox(search_frame, font=('Segoe UI', 10), height=5)
        self.search_listbox.pack(fill=tk.X)
        self.search_listbox.bind('<<ListboxSelect>>', self.on_item_select_from_search)
        self.search_listbox.bind('<Double-Button-1>', lambda e: self.quick_quantity.focus())

        # Category filter
        filter_frame = tk.Frame(menu_tab, bg='white')
        filter_frame.pack(fill=tk.X, pady=5)

        tk.Label(filter_frame, text="Filter by Category:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)

        self.menu_category_var = tk.StringVar(value='ALL')
        categories = self.restaurant.get_all_categories()
        cat_values = ['ALL'] + [c['category_name'] for c in categories]

        category_combo = ttk.Combobox(filter_frame, textvariable=self.menu_category_var,
                                      values=cat_values, state='readonly', width=20)
        category_combo.pack(side=tk.LEFT, padx=5)
        category_combo.bind('<<ComboboxSelected>>', lambda e: self.load_menu_items_popup(order_id))

        # Search by name
        tk.Label(filter_frame, text="Search:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=20)
        self.menu_search_var = tk.StringVar()
        search_entry = tk.Entry(filter_frame, textvariable=self.menu_search_var, font=('Segoe UI', 11), width=15)
        search_entry.pack(side=tk.LEFT, padx=5)
        search_entry.bind('<KeyRelease>', lambda e: self.load_menu_items_popup(order_id))

        # Add selected item frame
        add_selected_frame = tk.Frame(menu_tab, bg='white')
        add_selected_frame.pack(fill=tk.X, pady=10)

        tk.Label(add_selected_frame, text="Quantity:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)

        self.item_quantity = tk.Entry(add_selected_frame, font=('Segoe UI', 12), width=5)
        self.item_quantity.pack(side=tk.LEFT, padx=5)
        self.item_quantity.insert(0, '1')

        add_selected_btn = tk.Button(add_selected_frame, text="➕ ADD SELECTED", font=('Segoe UI', 11, 'bold'),
                                     bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                                     command=lambda: self.add_item_to_order_popup(order_id), padx=15, pady=5)
        add_selected_btn.pack(side=tk.LEFT, padx=10)

        # Menu items tree
        menu_frame = tk.Frame(menu_tab, bg='white')
        menu_frame.pack(fill=tk.BOTH, expand=True)

        menu_container = tk.Frame(menu_frame, bg='white')
        menu_container.pack(fill=tk.BOTH, expand=True)

        v_scroll = ttk.Scrollbar(menu_container)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        h_scroll = ttk.Scrollbar(menu_container, orient=tk.HORIZONTAL)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)

        columns = ('ID', 'Item', 'Category', 'Price', 'Tax %')
        self.menu_tree = ttk.Treeview(menu_container, columns=columns,
                                      yscrollcommand=v_scroll.set,
                                      xscrollcommand=h_scroll.set, height=8)
        v_scroll.config(command=self.menu_tree.yview)
        h_scroll.config(command=self.menu_tree.xview)

        for col in columns:
            self.menu_tree.heading(col, text=col, anchor=tk.W)
            self.menu_tree.column(col, width=100)

        self.menu_tree.column('ID', width=50)
        self.menu_tree.column('Item', width=250)
        self.menu_tree.column('Category', width=150)
        self.menu_tree.column('Price', width=100)
        self.menu_tree.column('Tax %', width=80)

        self.menu_tree.pack(fill=tk.BOTH, expand=True)

        self.menu_tree.bind('<Double-Button-1>', lambda e: self.add_item_to_order_popup(order_id))
        self.menu_tree.bind('<<TreeviewSelect>>', self.on_menu_tree_select)

        # ========== ORDER TAB ==========
        # Order items tree with printed status
        items_frame = tk.Frame(order_tab, bg='white')
        items_frame.pack(fill=tk.BOTH, expand=True)

        items_container = tk.Frame(items_frame, bg='white')
        items_container.pack(fill=tk.BOTH, expand=True)

        v_scroll2 = ttk.Scrollbar(items_container)
        v_scroll2.pack(side=tk.RIGHT, fill=tk.Y)

        h_scroll2 = ttk.Scrollbar(items_container, orient=tk.HORIZONTAL)
        h_scroll2.pack(side=tk.BOTTOM, fill=tk.X)

        # FIXED: Include ID as visible column with reasonable width
        item_columns = ('ID', 'S.No', 'Item', 'Qty', 'Unit Price', 'Total', 'Tax %', 'Printed')
        self.order_items_tree = ttk.Treeview(items_container, columns=item_columns,
                                             yscrollcommand=v_scroll2.set,
                                             xscrollcommand=h_scroll2.set,
                                             height=10)
        v_scroll2.config(command=self.order_items_tree.yview)
        h_scroll2.config(command=self.order_items_tree.xview)

        for col in item_columns:
            self.order_items_tree.heading(col, text=col, anchor=tk.W)
            self.order_items_tree.column(col, width=120)

        self.order_items_tree.column('ID', width=50)  # Make ID column visible
        self.order_items_tree.column('S.No', width=50)
        self.order_items_tree.column('Item', width=200)
        self.order_items_tree.column('Qty', width=60)
        self.order_items_tree.column('Unit Price', width=100)
        self.order_items_tree.column('Total', width=120)
        self.order_items_tree.column('Tax %', width=80)
        self.order_items_tree.column('Printed', width=80)

        self.order_items_tree.pack(fill=tk.BOTH, expand=True)

        # Action buttons
        action_frame = tk.Frame(order_tab, bg='white')
        action_frame.pack(fill=tk.X, pady=10)

        update_btn = tk.Button(action_frame, text="✏️ UPDATE", font=('Segoe UI', 11, 'bold'),
                               bg='#f39c12', fg='black', relief='flat', cursor='hand2',
                               command=lambda: self.update_order_item_popup(order_id), padx=15, pady=5)
        update_btn.pack(side=tk.LEFT, padx=5)

        delete_btn = tk.Button(action_frame, text="🗑️ DELETE", font=('Segoe UI', 11, 'bold'),
                               bg='#c0392b', fg='black', relief='flat', cursor='hand2',
                               command=lambda: self.delete_order_item_popup(order_id), padx=15, pady=5)
        delete_btn.pack(side=tk.LEFT, padx=5)

        # NEW BUTTON: Print New Items Only
        print_new_btn = tk.Button(action_frame, text="🆕 PRINT NEW ITEMS", font=('Segoe UI', 11, 'bold'),
                                  bg='#e67e22', fg='black', relief='flat', cursor='hand2',
                                  command=lambda: self.print_new_items_only(order_id),
                                  padx=15, pady=5)
        print_new_btn.pack(side=tk.LEFT, padx=5)

        # Print all button
        print_all_btn = tk.Button(action_frame, text="🖨️ PRINT ALL", font=('Segoe UI', 11, 'bold'),
                                  bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                  command=lambda: self.restaurant.print_order_by_type(order_id, 'all'),
                                  padx=15, pady=5)
        print_all_btn.pack(side=tk.LEFT, padx=5)

        done_btn = tk.Button(action_frame, text="✅ DONE", font=('Segoe UI', 11, 'bold'),
                             bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                             command=lambda: self.finish_order_popup(order_id, dialog), padx=15, pady=5)
        done_btn.pack(side=tk.RIGHT, padx=5)

        # Totals
        totals_frame = tk.Frame(order_tab, bg='white')
        totals_frame.pack(fill=tk.X, pady=10)

        order_items = self.restaurant.get_order_items(order_id)
        subtotal = sum(i['unit_price'] * i['quantity'] for i in order_items)
        tax = sum(i['unit_price'] * i['quantity'] * i['tax_percentage'] / 100 for i in order_items)
        total = subtotal + tax

        tk.Label(totals_frame, text=f"Subtotal: ₹{subtotal:.2f}", font=('Segoe UI', 12, 'bold'),
                 bg='white', fg='#6a4334').pack(anchor='e')
        tk.Label(totals_frame, text=f"Tax: ₹{tax:.2f}", font=('Segoe UI', 12, 'bold'),
                 bg='white', fg='#2e86c1').pack(anchor='e')
        tk.Label(totals_frame, text=f"TOTAL: ₹{total:.2f}", font=('Segoe UI', 14, 'bold'),
                 bg='white', fg='#27ae60').pack(anchor='e', pady=5)

        # Bind keyboard shortcuts
        dialog.bind('<Control-p>', lambda e: self.restaurant.print_order_by_type(order_id, 'all'))
        dialog.bind('<Control-P>', lambda e: self.restaurant.print_order_by_type(order_id, 'all'))
        dialog.bind('<Control-n>', lambda e: self.print_new_items_only(order_id))
        dialog.bind('<Control-N>', lambda e: self.print_new_items_only(order_id))

        # Load data
        self.load_menu_items_popup(order_id)
        self.load_order_items_popup(order_id)

    def search_items_on_type(self, order_id):
        """Search items as user types in the quick add field."""
        search_text = self.quick_item_name.get().strip()

        # Clear the search listbox
        self.search_listbox.delete(0, tk.END)

        if len(search_text) < 2:
            return

        # Get all menu items
        items = self.restaurant.get_all_menu_items()

        # Try to interpret as ID first
        if search_text.isdigit():
            # Search by ID
            for item in items:
                if str(item['id']) == search_text:
                    self.search_listbox.insert(tk.END, f"ID:{item['id']} - {item['item_name']} - ₹{item['price']:.2f}")
                    self.search_listbox.selection_set(0)
                    self.on_item_select_from_search()
                    return

            # If no exact ID match, show items where ID starts with the number
            for item in items:
                if str(item['id']).startswith(search_text):
                    self.search_listbox.insert(tk.END, f"ID:{item['id']} - {item['item_name']} - ₹{item['price']:.2f}")
        else:
            # Search by name
            for item in items:
                if search_text.lower() in item['item_name'].lower():
                    self.search_listbox.insert(tk.END, f"ID:{item['id']} - {item['item_name']} - ₹{item['price']:.2f}")

        # If only one result, select it automatically
        if self.search_listbox.size() == 1:
            self.search_listbox.selection_set(0)
            self.on_item_select_from_search()

    def on_item_select_from_search(self, event=None):
        """Handle item selection from search listbox."""
        selection = self.search_listbox.curselection()
        if not selection:
            return

        selected_text = self.search_listbox.get(selection[0])
        # Parse the selection to get item ID
        try:
            parts = selected_text.split(' - ')
            if len(parts) >= 1:
                id_part = parts[0].replace('ID:', '')
                item_id = int(id_part)

                # Get item details
                item = self.restaurant.get_menu_item_by_id(item_id)
                if item:
                    self.selected_item_id = item_id
                    self.quick_price_var.set(f"₹{item['price']:.2f}")
                    self.update_quick_total()

                    # Update the item name field with the selected item name for better UX
                    self.quick_item_name.delete(0, tk.END)
                    self.quick_item_name.insert(0, item['item_name'])

                    # Focus on quantity field
                    self.quick_quantity.focus()
        except Exception as e:
            print(f"Error selecting item: {e}")

    def update_quick_total(self):
        """Update total price based on quantity and selected item."""
        try:
            price_text = self.quick_price_var.get().replace('₹', '')
            if price_text:
                price = float(price_text)
                quantity = int(self.quick_quantity.get() or 1)
                total = price * quantity
                self.quick_total_var.set(f"₹{total:.2f}")
        except:
            pass

    def on_menu_tree_select(self, event=None):
        """Handle menu tree selection."""
        selection = self.menu_tree.selection()
        if selection:
            item_id = self.menu_tree.item(selection[0])['values'][0]
            item = self.restaurant.get_menu_item_by_id(item_id)
            if item:
                self.selected_item_id = item_id
                self.quick_price_var.set(f"₹{item['price']:.2f}")
                self.quick_item_name.delete(0, tk.END)
                self.quick_item_name.insert(0, item['item_name'])
                self.update_quick_total()

    def quick_add_by_search(self, order_id):
        """Add item by search selection."""
        if not hasattr(self, 'selected_item_id'):
            self.show_warning("Please select an item first")
            return

        try:
            quantity = int(self.quick_quantity.get())
            if quantity <= 0:
                raise ValueError("Quantity must be positive")

            self.restaurant.add_order_item(order_id, self.selected_item_id, quantity)
            self.load_order_items_popup(order_id)

            # Update item number and clear selection
            current_no = int(self.current_item_no.get())
            self.current_item_no.set(str(current_no + 1))

            self.quick_item_name.delete(0, tk.END)
            self.quick_price_var.set("₹0.00")
            self.quick_total_var.set("₹0.00")
            self.quick_quantity.delete(0, tk.END)
            self.quick_quantity.insert(0, '1')
            self.search_listbox.delete(0, tk.END)

            self.show_info("Item added successfully")
            self.quick_item_name.focus()

        except ValueError as e:
            self.show_error(str(e))
        except Exception as e:
            self.show_error(f"Error adding item: {str(e)}")

    def load_order_items_popup(self, order_id):
        """Load order items into tree with auto-incrementing serial numbers."""
        if not hasattr(self, 'order_items_tree'):
            return

        for item in self.order_items_tree.get_children():
            self.order_items_tree.delete(item)

        items = self.restaurant.get_order_items(order_id)

        for idx, item in enumerate(items, start=1):
            values = (
                idx,  # Auto-incrementing serial number
                item['item_name'],
                item['quantity'],
                f"₹{item['unit_price']:.2f}",
                f"₹{item['total_price']:.2f}",
                f"{item['tax_percentage']}%"
            )
            self.order_items_tree.insert('', tk.END, values=values)

        # Update the next item number
        self.current_item_no.set(str(len(items) + 1))

    def load_menu_items_popup(self, order_id=None):
        """Load menu items into tree for popup."""
        if not hasattr(self, 'menu_tree'):
            return

        for item in self.menu_tree.get_children():
            self.menu_tree.delete(item)

        category_filter = self.menu_category_var.get() if hasattr(self, 'menu_category_var') else 'ALL'
        search_term = self.menu_search_var.get().strip().lower() if hasattr(self, 'menu_search_var') else ''

        if category_filter != 'ALL':
            categories = self.restaurant.get_all_categories()
            cat_id = None
            for c in categories:
                if c['category_name'] == category_filter:
                    cat_id = c['id']
                    break
            items = self.restaurant.get_all_menu_items(cat_id)
        else:
            items = self.restaurant.get_all_menu_items()

        # Apply search filter
        if search_term:
            items = [item for item in items if search_term in item['item_name'].lower()]

        for item in items:
            values = (
                item['id'],
                item['item_name'],
                item['category_name'],
                f"₹{item['price']:.2f}",
                f"{item['tax_percentage']}%"
            )
            self.menu_tree.insert('', tk.END, values=values)

    def load_order_items_popup(self, order_id):
        """Load order items into tree with printed status and update totals."""
        if not hasattr(self, 'order_items_tree'):
            return

        for item in self.order_items_tree.get_children():
            self.order_items_tree.delete(item)

        items = self.restaurant.get_order_items(order_id)

        # Calculate totals
        subtotal = 0
        tax = 0

        for idx, item in enumerate(items, start=1):
            # Determine printed status
            if item.get('printed_to_kitchen') and item.get('printed_to_desk'):
                printed_status = "✅"
            elif item.get('printed_to_kitchen') or item.get('printed_to_desk'):
                printed_status = "⚠️"
            else:
                printed_status = "❌"

            values = (
                item['id'],  # ID as first column (visible now)
                idx,  # Auto-incrementing serial number
                item['item_name'],
                item['quantity'],
                f"₹{item['unit_price']:.2f}",
                f"₹{item['total_price']:.2f}",
                f"{item['tax_percentage']}%",
                printed_status
            )
            self.order_items_tree.insert('', tk.END, values=values)

            # Calculate totals
            subtotal += item['total_price']
            tax += item['unit_price'] * item['quantity'] * item['tax_percentage'] / 100

        # Update the next item number
        self.current_item_no.set(str(len(items) + 1))

        # Update totals display in the order popup
        total = subtotal + tax

        # Find and update the totals labels in the order popup
        try:
            # Look for the parent frame that contains the totals
            parent = self.order_items_tree.master.master.master.master
            for widget in parent.winfo_children():
                if isinstance(widget, tk.Frame):
                    for child in widget.winfo_children():
                        if isinstance(child, tk.Frame) and child.winfo_children():
                            for label in child.winfo_children():
                                if isinstance(label, tk.Label):
                                    if 'Subtotal:' in str(label.cget('text')):
                                        label.config(text=f"Subtotal: ₹{subtotal:.2f}")
                                    elif 'Tax:' in str(label.cget('text')):
                                        label.config(text=f"Tax: ₹{tax:.2f}")
                                    elif 'TOTAL:' in str(label.cget('text')):
                                        label.config(text=f"TOTAL: ₹{total:.2f}")
        except Exception as e:
            print(f"Error updating totals display: {e}")

    def quick_add_by_id_popup(self, order_id):
        """Quick add item by ID in popup."""
        try:
            item_id = self.quick_item_id.get().strip()
            if not item_id:
                self.show_warning("Please enter an item ID")
                return

            quantity = int(self.quick_quantity.get())
            if quantity <= 0:
                raise ValueError("Quantity must be positive")

            self.restaurant.add_order_item(order_id, int(item_id), quantity)
            self.load_order_items_popup(order_id)
            self.show_info("Item added successfully")
            self.quick_item_id.delete(0, tk.END)
            self.quick_item_id.focus()
        except ValueError as e:
            self.show_error(str(e))
        except Exception as e:
            self.show_error(f"Error adding item: {str(e)}")

    def quick_add_by_name_popup(self, order_id):
        """Quick add item by name search in popup."""
        try:
            item_name = self.quick_item_name.get().strip()
            if not item_name:
                self.show_warning("Please enter an item name")
                return

            # Search for items matching the name
            items = self.restaurant.get_all_menu_items()
            matching_items = [item for item in items if item_name.lower() in item['item_name'].lower()]

            if not matching_items:
                self.show_error(f"No items found matching '{item_name}'")
                return

            if len(matching_items) == 1:
                # Single match - add directly
                quantity = int(self.quick_quantity.get())
                if quantity <= 0:
                    raise ValueError("Quantity must be positive")

                self.restaurant.add_order_item(order_id, matching_items[0]['id'], quantity)
                self.load_order_items_popup(order_id)
                self.show_info(f"Added {matching_items[0]['item_name']}")

                # Find and select the item in the menu tree
                for child in self.menu_tree.get_children():
                    if self.menu_tree.item(child)['values'][1] == matching_items[0]['item_name']:
                        self.menu_tree.selection_set(child)
                        self.menu_tree.see(child)
                        break

                self.quick_item_name.delete(0, tk.END)
            else:
                # Multiple matches - show selection dialog
                self.show_item_selection_dialog_popup(order_id, matching_items)

        except ValueError as e:
            self.show_error(str(e))
        except Exception as e:
            self.show_error(f"Error adding item: {str(e)}")

    def show_item_selection_dialog_popup(self, order_id, items):
        """Show dialog to select from multiple matching items in popup."""
        dialog = tk.Toplevel(self.current_popup if self.current_popup else self.root)
        dialog.title("Select Item")
        dialog.geometry("500x400")
        dialog.transient(self.current_popup if self.current_popup else self.root)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 500, 400)

        # Bind Escape to close
        dialog.bind('<Escape>', lambda e: dialog.destroy())

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="Multiple items found", font=('Segoe UI', 14, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 10))

        # Treeview for items
        tree_frame = tk.Frame(main_frame, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scroll = ttk.Scrollbar(tree_container)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ('ID', 'Item Name', 'Category', 'Price')
        tree = ttk.Treeview(tree_container, columns=columns, yscrollcommand=v_scroll.set, height=10)
        v_scroll.config(command=tree.yview)

        for col in columns:
            tree.heading(col, text=col, anchor=tk.W)
            tree.column(col, width=100)

        tree.column('ID', width=50)
        tree.column('Item Name', width=200)

        tree.pack(fill=tk.BOTH, expand=True)

        for item in items:
            tree.insert('', tk.END,
                        values=(item['id'], item['item_name'], item['category_name'], f"₹{item['price']:.2f}"))

        qty_frame = tk.Frame(main_frame, bg='white')
        qty_frame.pack(fill=tk.X, pady=10)

        tk.Label(qty_frame, text="Quantity:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)

        qty_entry = tk.Entry(qty_frame, font=('Segoe UI', 11), width=10)
        qty_entry.pack(side=tk.LEFT, padx=5)
        qty_entry.insert(0, '1')
        qty_entry.bind('<Return>', lambda e: add_selected())

        def add_selected():
            selection = tree.selection()
            if not selection:
                self.show_warning("Please select an item")
                return

            item_id = tree.item(selection[0])['values'][0]
            quantity = int(qty_entry.get())

            try:
                self.restaurant.add_order_item(order_id, item_id, quantity)
                self.load_order_items_popup(order_id)
                self.show_info("Item added successfully")
                dialog.destroy()
                self.quick_item_name.delete(0, tk.END)
            except Exception as e:
                self.show_error(str(e))

        button_frame = tk.Frame(main_frame, bg='white')
        button_frame.pack(pady=10)

        add_btn = tk.Button(button_frame, text="ADD SELECTED", font=('Segoe UI', 11, 'bold'),
                            bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                            command=add_selected, padx=20, pady=8)
        add_btn.pack(side=tk.LEFT, padx=5)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 11, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                               command=dialog.destroy, padx=20, pady=8)
        cancel_btn.pack(side=tk.LEFT, padx=5)

    def add_item_to_order_popup(self, order_id):
        """Add selected menu item to order in popup."""
        selection = self.menu_tree.selection()
        if not selection:
            self.show_warning("Please select a menu item")
            return

        try:
            item_id = self.menu_tree.item(selection[0])['values'][0]
            quantity = int(self.item_quantity.get())

            if quantity <= 0:
                raise ValueError("Quantity must be positive")

            self.restaurant.add_order_item(order_id, item_id, quantity)
            self.load_order_items_popup(order_id)
            self.show_info("Item added to order")

        except ValueError as e:
            self.show_error(str(e))
        except Exception as e:
            self.show_error(f"Error adding item: {str(e)}")

    def update_order_item_popup(self, order_id):
        """Update selected order item in popup."""
        selection = self.order_items_tree.selection()
        if not selection:
            self.show_warning("Please select an item to update")
            return

        # Get values from the selected item - ID is now first column
        values = self.order_items_tree.item(selection[0])['values']
        if not values or len(values) < 5:
            self.show_error("Invalid item selection")
            return

        item_id = values[0]  # ID is first column
        current_qty = values[3]  # Quantity is now at index 3

        new_qty = simpledialog.askinteger("Update Quantity",
                                          f"Enter new quantity (current: {current_qty}):",
                                          parent=self.current_popup, minvalue=1, maxvalue=100)

        if new_qty:
            try:
                self.restaurant.update_order_item(item_id, new_qty)
                self.load_order_items_popup(order_id)
                self.show_info("Item updated")
            except Exception as e:
                self.show_error(str(e))

    def delete_order_item_popup(self, order_id):
        """Delete selected order item in popup."""
        selection = self.order_items_tree.selection()
        if not selection:
            self.show_warning("Please select an item to delete")
            return

        # Get values from the selected item - ID is first column
        values = self.order_items_tree.item(selection[0])['values']
        if not values or len(values) < 3:
            self.show_error("Invalid item selection")
            return

        item_id = values[0]  # ID is first column
        item_name = values[2]  # Item name is now at index 2

        if self.ask_confirmation(f"Delete '{item_name}' from order?"):
            try:
                self.restaurant.delete_order_item(item_id)
                self.load_order_items_popup(order_id)
                self.show_info("Item deleted")
            except Exception as e:
                self.show_error(str(e))

    def finish_order_popup(self, order_id, dialog):
        """Finish order and close dialog."""
        order = self.restaurant.get_order_by_id(order_id)
        if order['total_amount'] > 0:
            if self.ask_confirmation("Order has items. Do you want to proceed to billing?"):
                dialog.destroy()
                self.open_popup('generate_bill')
        else:
            dialog.destroy()

    def create_active_orders_in_popup(self, parent):
        """Create active orders list in popup with restaurant and table filters."""
        # Filter frame
        filter_frame = tk.LabelFrame(parent, text="Filter Orders",
                                     font=('Segoe UI', 11, 'bold'),
                                     bg='white', fg='#6a4334', padx=15, pady=10)
        filter_frame.pack(fill=tk.X, pady=(0, 20))

        # Restaurant filter
        rest_frame = tk.Frame(filter_frame, bg='white')
        rest_frame.pack(fill=tk.X, pady=5)

        tk.Label(rest_frame, text="Restaurant:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)

        # Get all restaurants for filter
        restaurants = self.restaurant.get_all_restaurants()
        rest_values = ['ALL'] + [f"{r['restaurant_code']} - {r['restaurant_name']}" for r in restaurants]

        self.active_orders_rest_filter = tk.StringVar(value='ALL')
        rest_combo = ttk.Combobox(rest_frame, textvariable=self.active_orders_rest_filter,
                                  values=rest_values, state='readonly', width=30,
                                  font=('Segoe UI', 11))
        rest_combo.pack(side=tk.LEFT, padx=5)
        rest_combo.bind('<<ComboboxSelected>>', lambda e: self.load_filtered_active_orders_popup())

        # Table filter
        table_frame = tk.Frame(filter_frame, bg='white')
        table_frame.pack(fill=tk.X, pady=5)

        tk.Label(table_frame, text="Table Number:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)

        self.active_orders_table_filter = tk.Entry(table_frame, font=('Segoe UI', 11), width=20)
        self.active_orders_table_filter.pack(side=tk.LEFT, padx=5)
        self.active_orders_table_filter.bind('<Return>', lambda e: self.load_filtered_active_orders_popup())

        # Show active tables only checkbox
        self.show_active_tables_only = tk.BooleanVar(value=True)
        active_tables_check = ttk.Checkbutton(table_frame, text="Show only active tables",
                                              variable=self.show_active_tables_only,
                                              command=self.load_filtered_active_orders_popup)
        active_tables_check.pack(side=tk.LEFT, padx=20)

        # Button frame
        button_frame = tk.Frame(filter_frame, bg='white')
        button_frame.pack(fill=tk.X, pady=5)

        filter_btn = tk.Button(button_frame, text="🔍 APPLY FILTERS",
                               font=('Segoe UI', 10, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.load_filtered_active_orders_popup, padx=15, pady=2)
        filter_btn.pack(side=tk.LEFT, padx=5)

        clear_btn = tk.Button(button_frame, text="🔄 CLEAR FILTERS",
                              font=('Segoe UI', 10, 'bold'),
                              bg='#95a5a6', fg='black', relief='flat',
                              command=self.clear_active_orders_filters, padx=15, pady=2)
        clear_btn.pack(side=tk.LEFT, padx=5)

        refresh_btn = tk.Button(button_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 10, 'bold'),
                                bg='#27ae60', fg='black', relief='flat',
                                command=self.load_filtered_active_orders_popup, padx=15, pady=2)
        refresh_btn.pack(side=tk.RIGHT, padx=5)

        # Active tables status frame
        status_frame = tk.Frame(filter_frame, bg='white')
        status_frame.pack(fill=tk.X, pady=5)

        self.active_tables_label = tk.Label(status_frame, text="", font=('Segoe UI', 10),
                                            bg='white', fg='#2e86c1')
        self.active_tables_label.pack(anchor='w', padx=5)

        # Treeview frame
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        columns = ('ID', 'Order #', 'Customer', 'Restaurant', 'Table/Room', 'Items', 'Total', 'Time', 'Type',
                   'Table Status')
        self.orders_tree = ttk.Treeview(tree_container, columns=columns,
                                        yscrollcommand=v_scrollbar.set,
                                        xscrollcommand=h_scrollbar.set,
                                        height=12)

        v_scrollbar.config(command=self.orders_tree.yview)
        h_scrollbar.config(command=self.orders_tree.xview)

        # Configure columns
        column_widths = {
            'ID': 50,
            'Order #': 150,
            'Customer': 150,
            'Restaurant': 120,
            'Table/Room': 100,
            'Items': 60,
            'Total': 100,
            'Time': 80,
            'Type': 100,
            'Table Status': 100
        }

        for col in columns:
            self.orders_tree.heading(col, text=col, anchor=tk.W)
            self.orders_tree.column(col, width=column_widths.get(col, 100))

        self.orders_tree.pack(fill=tk.BOTH, expand=True)

        self.orders_tree.bind('<Double-Button-1>', lambda e: self.open_selected_order_popup())

        # Load initial data
        self.load_filtered_active_orders_popup()

    def load_filtered_active_orders_popup(self):
        """Load active orders with filters applied."""
        if not hasattr(self, 'orders_tree'):
            return

        for item in self.orders_tree.get_children():
            self.orders_tree.delete(item)

        # Get filter values
        rest_filter = self.active_orders_rest_filter.get()
        table_filter = self.active_orders_table_filter.get().strip().lower()
        show_active_tables = self.show_active_tables_only.get()

        # Get restaurant ID if filter is not ALL
        restaurant_id = None
        if rest_filter != 'ALL':
            rest_code = rest_filter.split(' - ')[0]
            restaurant = self.restaurant.get_restaurant_by_code(rest_code)
            if restaurant:
                restaurant_id = restaurant['id']

        # Get all active orders
        active_orders = self.restaurant.get_active_orders(restaurant_id)

        # Apply table filter
        filtered_orders = []
        active_tables_count = 0

        for order in active_orders:
            table_room = order.get('table_number') or order.get('room_number', '').lower()

            # Apply table filter if provided
            if table_filter and table_filter not in table_room:
                continue

            filtered_orders.append(order)

            # Count active tables (for restaurant orders)
            if order.get('order_type') == 'restaurant' and order.get('table_number'):
                active_tables_count += 1

        # Sort orders by time (newest first)
        filtered_orders.sort(key=lambda x: x.get('order_time', ''), reverse=True)

        # Get all active tables for display
        if show_active_tables:
            active_tables_info = self.get_active_tables_info()
            self.active_tables_label.config(text=active_tables_info)

        # Populate tree
        for order in filtered_orders:
            items = self.restaurant.get_order_items(order['id'])
            item_count = len(items)

            # Determine table status
            table_status = ""
            if order.get('order_type') == 'restaurant' and order.get('table_number'):
                table_status = f"Table {order['table_number']} (Occupied)"

            values = (
                order['id'],
                order['order_number'],
                order['customer_name'][:20] + ('...' if len(order['customer_name']) > 20 else ''),
                order.get('restaurant_name', '')[:15],
                order.get('table_number') or order.get('room_number', ''),
                item_count,
                f"₹{order['total_amount']:.2f}",
                order['order_time'][11:16] if order['order_time'] else '',
                order['order_type'].upper(),
                table_status
            )

            # Add tags for different types
            tags = ()
            if order.get('order_type') == 'restaurant':
                tags = ('restaurant',)
            else:
                tags = ('room_service',)

            self.orders_tree.insert('', tk.END, values=values, tags=tags)

        # Configure tags
        self.orders_tree.tag_configure('restaurant', background='#e8f8f5')  # Light green
        self.orders_tree.tag_configure('room_service', background='#fdebd0')  # Light orange

        # Update filter status
        total_orders = len(filtered_orders)
        status_text = f"Showing {total_orders} active order(s)"
        if table_filter:
            status_text += f" | Filtered by table: '{table_filter}'"
        if show_active_tables:
            status_text += f" | Active tables: {active_tables_count}"

        # Add status label at bottom
        if hasattr(self, 'orders_status_label'):
            self.orders_status_label.destroy()

        self.orders_status_label = tk.Label(self.orders_tree.master.master.master,
                                            text=status_text, font=('Segoe UI', 10, 'italic'),
                                            bg='white', fg='#6a4334')
        self.orders_status_label.pack(fill=tk.X, pady=5)

    def get_active_tables_info(self):
        """Get information about active tables across restaurants."""
        try:
            restaurants = self.restaurant.get_all_restaurants()
            active_tables_info = []

            for rest in restaurants:
                tables = self.restaurant.get_tables_for_restaurant(rest['id'])
                occupied_tables = [t for t in tables if t['status'] == 'occupied']
                if occupied_tables:
                    table_numbers = [t['table_number'] for t in occupied_tables]
                    active_tables_info.append(f"{rest['restaurant_code']}: {', '.join(table_numbers)}")

            if active_tables_info:
                return "Active tables: " + " | ".join(active_tables_info)
            else:
                return "No active tables currently"

        except Exception as e:
            print(f"Error getting active tables info: {e}")
            return ""

    def clear_active_orders_filters(self):
        """Clear all filters in active orders."""
        self.active_orders_rest_filter.set('ALL')
        self.active_orders_table_filter.delete(0, tk.END)
        self.load_filtered_active_orders_popup()

    def load_active_orders_list_popup(self):
        """Load active orders into treeview in popup."""
        if not hasattr(self, 'orders_tree'):
            return

        for item in self.orders_tree.get_children():
            self.orders_tree.delete(item)

        filter_text = self.active_orders_filter.get()
        restaurant_id = None

        if filter_text != 'ALL':
            rest_code = filter_text.split(' - ')[0]
            restaurant = self.restaurant.get_restaurant_by_code(rest_code)
            if restaurant:
                restaurant_id = restaurant['id']

        active_orders = self.restaurant.get_active_orders(restaurant_id)

        for order in active_orders:
            items = self.restaurant.get_order_items(order['id'])
            item_count = len(items)

            values = (
                order['id'],
                order['order_number'],
                order['customer_name'],
                order.get('restaurant_name', ''),
                order.get('table_number') or order.get('room_number', ''),
                item_count,
                f"₹{order['total_amount']:.2f}",
                order['order_time'][11:16] if order['order_time'] else '',
                order['order_type'].upper()
            )
            self.orders_tree.insert('', tk.END, values=values)

    def open_selected_order_popup(self):
        """Open selected order for item management in popup."""
        selection = self.orders_tree.selection()
        if not selection:
            self.show_warning("Please select an order")
            return

        order_id = self.orders_tree.item(selection[0])['values'][0]
        self.open_order_for_items_popup(order_id)

    def create_generate_bill_in_popup(self, parent):
        """Create generate bill screen in popup."""
        # Filter frame
        filter_frame = tk.Frame(parent, bg='white')
        filter_frame.pack(fill=tk.X, pady=(0, 20))

        tk.Label(filter_frame, text="Select Order:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)

        refresh_btn = tk.Button(filter_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_billable_orders_popup, padx=15, pady=5)
        refresh_btn.pack(side=tk.RIGHT, padx=5)

        # Treeview frame
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ('ID', 'Order #', 'Customer', 'Table/Room', 'Items', 'Total', 'Type', 'Time')
        self.bill_orders_tree = ttk.Treeview(tree_container, columns=columns,
                                             yscrollcommand=v_scrollbar.set,
                                             height=10)
        v_scrollbar.config(command=self.bill_orders_tree.yview)

        for col in columns:
            self.bill_orders_tree.heading(col, text=col, anchor=tk.W)
            self.bill_orders_tree.column(col, width=120)

        self.bill_orders_tree.column('ID', width=50)
        self.bill_orders_tree.column('Order #', width=150)

        self.bill_orders_tree.pack(fill=tk.BOTH, expand=True)

        self.bill_orders_tree.bind('<Double-Button-1>', lambda e: self.open_bill_dialog_popup())

        self.load_billable_orders_popup()

    def load_billable_orders_popup(self):
        """Load orders ready for billing in popup."""
        if not hasattr(self, 'bill_orders_tree'):
            return

        for item in self.bill_orders_tree.get_children():
            self.bill_orders_tree.delete(item)

        active_orders = self.restaurant.get_active_orders()

        for order in active_orders:
            if order['total_amount'] > 0:
                items = self.restaurant.get_order_items(order['id'])
                item_count = len(items)

                values = (
                    order['id'],
                    order['order_number'],
                    order['customer_name'],
                    order.get('table_number') or order.get('room_number', ''),
                    item_count,
                    f"₹{order['total_amount']:.2f}",
                    order['order_type'].upper(),
                    order['order_time'][11:16] if order['order_time'] else ''
                )
                self.bill_orders_tree.insert('', tk.END, values=values)

    def open_bill_dialog_popup(self, event=None):
        """Open bill generation dialog for selected order in popup."""
        if not hasattr(self, 'bill_orders_tree'):
            return

        selection = self.bill_orders_tree.selection()
        if not selection:
            self.show_warning("Please select an order")
            return

        order_id = self.bill_orders_tree.item(selection[0])['values'][0]
        order = self.restaurant.get_order_by_id(order_id)

        if not order:
            self.show_error("Order not found")
            return

        items = self.restaurant.get_order_items(order_id)

        # Create dialog
        dialog = tk.Toplevel(self.current_popup)
        dialog.title(f"Generate Bill - Order: {order['order_number']}")
        dialog.geometry("700x800")
        dialog.transient(self.current_popup)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 700, 800)

        # Bind Escape to close
        dialog.bind('<Escape>', lambda e: dialog.destroy())

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Create canvas with scrollbar
        canvas = tk.Canvas(main_frame, bg='white', highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='white')

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        tk.Label(scrollable_frame, text=f"GENERATE BILL", font=('Segoe UI', 18, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        # Order Summary
        summary_frame = tk.LabelFrame(scrollable_frame, text="Order Summary",
                                      font=('Segoe UI', 12, 'bold'),
                                      bg='white', fg='#6a4334', padx=20, pady=15)
        summary_frame.pack(fill=tk.X, pady=(0, 20))

        info_text = f"""
   Order #: {order['order_number']}
   Customer: {order['customer_name']}
   Table/Room: {order.get('table_number') or order.get('room_number', 'N/A')}
   Items: {len(items)}
       """

        tk.Label(summary_frame, text=info_text, font=('Segoe UI', 11),
                 bg='white', fg='#2e86c1', justify=tk.LEFT).pack(anchor='w')

        # Customer Phone Number (if not provided)
        if not order.get('customer_phone'):
            phone_frame = tk.LabelFrame(scrollable_frame, text="Customer Contact (Optional)",
                                        font=('Segoe UI', 12, 'bold'),
                                        bg='white', fg='#6a4334', padx=20, pady=15)
            phone_frame.pack(fill=tk.X, pady=(0, 20))

            tk.Label(phone_frame, text="Mobile Number:", font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').pack(anchor='w', pady=(5, 2))

            self.bill_phone_entry = tk.Entry(phone_frame, font=('Segoe UI', 12), width=30)
            self.bill_phone_entry.pack(fill=tk.X, pady=(0, 10))
            self.bill_phone_entry.insert(0, "")  # Empty by default

            tk.Label(phone_frame, text="(Optional - for SMS bill delivery)",
                     font=('Segoe UI', 9), bg='white', fg='#7f8c8d').pack(anchor='w')

        # Items
        items_frame = tk.LabelFrame(scrollable_frame, text="Items",
                                    font=('Segoe UI', 12, 'bold'),
                                    bg='white', fg='#6a4334', padx=20, pady=15)
        items_frame.pack(fill=tk.X, pady=(0, 20))

        for item in items:
            item_text = f"{item['item_name']} x{item['quantity']} @ ₹{item['unit_price']:.2f} = ₹{item['total_price']:.2f}"
            tk.Label(items_frame, text=item_text, font=('Segoe UI', 10),
                     bg='white', fg='#333333').pack(anchor='w', pady=2)

        subtotal = sum(i['unit_price'] * i['quantity'] for i in items)
        tax = sum(i['unit_price'] * i['quantity'] * i['tax_percentage'] / 100 for i in items)
        total = subtotal + tax

        # Totals
        total_frame = tk.Frame(scrollable_frame, bg='white')
        total_frame.pack(fill=tk.X, pady=(0, 20))

        tk.Label(total_frame, text=f"Subtotal: ₹{subtotal:.2f}", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').pack(anchor='e')
        tk.Label(total_frame, text=f"Tax: ₹{tax:.2f}", font=('Segoe UI', 12),
                 bg='white', fg='#2e86c1').pack(anchor='e')
        tk.Label(total_frame, text=f"TOTAL: ₹{total:.2f}", font=('Segoe UI', 16, 'bold'),
                 bg='white', fg='#27ae60').pack(anchor='e', pady=5)

        # Payment Details
        payment_frame = tk.LabelFrame(scrollable_frame, text="Payment Details",
                                      font=('Segoe UI', 12, 'bold'),
                                      bg='white', fg='#6a4334', padx=20, pady=15)
        payment_frame.pack(fill=tk.X, pady=(0, 20))

        row = 0
        tk.Label(payment_frame, text="Payment Method:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.payment_method_var = tk.StringVar(value='cash')
        method_combo = ttk.Combobox(payment_frame, textvariable=self.payment_method_var,
                                    values=['cash', 'card', 'upi', 'complimentary', 'pending'],
                                    state='readonly', width=20, font=('Segoe UI', 11))
        method_combo.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        method_combo.bind('<<ComboboxSelected>>', self.toggle_payment_fields_popup)
        row += 1

        # Discount field
        tk.Label(payment_frame, text="Discount %:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.discount_entry = tk.Entry(payment_frame, font=('Segoe UI', 11), width=10)
        self.discount_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.discount_entry.insert(0, '0')
        self.discount_entry.bind('<KeyRelease>', self.calculate_discount_popup)
        row += 1

        tk.Label(payment_frame, text="Cash Received:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.cash_received_entry = tk.Entry(payment_frame, font=('Segoe UI', 11), width=20)
        self.cash_received_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.cash_received_entry.insert(0, str(total))
        row += 1

        self.change_label = tk.Label(payment_frame, text="Change: ₹0.00", font=('Segoe UI', 11),
                                     bg='white', fg='#27ae60')
        self.change_label.grid(row=row, column=1, padx=5, pady=5, sticky='w')

        self.cash_received_entry.bind('<KeyRelease>', self.calculate_change_popup)

        # Pending bill details frame (initially hidden)
        self.pending_frame = tk.LabelFrame(payment_frame, text="Pending Bill Details",
                                           font=('Segoe UI', 11, 'bold'),
                                           bg='white', fg='#6a4334', padx=15, pady=10)
        self.pending_frame.grid(row=row, column=0, columnspan=2, pady=10, sticky='ew')
        row += 1

        # Pending form fields
        pending_row = 0
        tk.Label(self.pending_frame, text="Customer Name:", font=('Segoe UI', 10),
                 bg='white', fg='#6a4334').grid(row=pending_row, column=0, padx=5, pady=5, sticky='e')
        self.pending_customer_name = tk.Entry(self.pending_frame, font=('Segoe UI', 10), width=25)
        self.pending_customer_name.grid(row=pending_row, column=1, padx=5, pady=5, sticky='w')
        self.pending_customer_name.insert(0, order['customer_name'])
        pending_row += 1

        tk.Label(self.pending_frame, text="Customer Phone:", font=('Segoe UI', 10),
                 bg='white', fg='#6a4334').grid(row=pending_row, column=0, padx=5, pady=5, sticky='e')
        self.pending_customer_phone = tk.Entry(self.pending_frame, font=('Segoe UI', 10), width=25)
        self.pending_customer_phone.grid(row=pending_row, column=1, padx=5, pady=5, sticky='w')
        pending_row += 1

        tk.Label(self.pending_frame, text="Reference Name:", font=('Segoe UI', 10),
                 bg='white', fg='#6a4334').grid(row=pending_row, column=0, padx=5, pady=5, sticky='e')
        self.pending_ref_name = tk.Entry(self.pending_frame, font=('Segoe UI', 10), width=25)
        self.pending_ref_name.grid(row=pending_row, column=1, padx=5, pady=5, sticky='w')
        pending_row += 1

        tk.Label(self.pending_frame, text="Reference Phone:", font=('Segoe UI', 10),
                 bg='white', fg='#6a4334').grid(row=pending_row, column=0, padx=5, pady=5, sticky='e')
        self.pending_ref_phone = tk.Entry(self.pending_frame, font=('Segoe UI', 10), width=25)
        self.pending_ref_phone.grid(row=pending_row, column=1, padx=5, pady=5, sticky='w')
        pending_row += 1

        tk.Label(self.pending_frame, text="Notes:", font=('Segoe UI', 10),
                 bg='white', fg='#6a4334').grid(row=pending_row, column=0, padx=5, pady=5, sticky='ne')
        self.pending_notes = tk.Text(self.pending_frame, font=('Segoe UI', 10), width=25, height=3)
        self.pending_notes.grid(row=pending_row, column=1, padx=5, pady=5, sticky='w')
        self.pending_notes.insert('1.0', "Bill pending payment")
        pending_row += 1

        # Hide pending frame initially
        self.pending_frame.grid_remove()

        # Note for room service
        if order['order_type'] == 'room_service':
            note_frame = tk.Frame(payment_frame, bg='#fff3cd', bd=1, relief=tk.SOLID)
            note_frame.grid(row=row + 1, column=0, columnspan=2, pady=10, sticky='ew')
            tk.Label(note_frame,
                     text="ℹ️ Room Service: Discount applies to this bill only. Full amount will be added to hotel bill.",
                     font=('Segoe UI', 9), bg='#fff3cd', fg='#856404', padx=10, pady=5).pack()

        # Adjusted total
        self.adjusted_total_label = tk.Label(payment_frame, text=f"Final Total: ₹{total:.2f}",
                                             font=('Segoe UI', 12, 'bold'),
                                             bg='white', fg='#c0392b')
        self.adjusted_total_label.grid(row=row + 2, column=0, columnspan=2, pady=10)

        # Store bill_id for later use (will be set after generation)
        self.current_bill_id = None

        def generate_bill_action():
            try:
                payment_method = self.payment_method_var.get()
                is_complimentary = (payment_method == 'complimentary')
                is_pending = (payment_method == 'pending')

                # If pending, use 'pending' as payment method for storage
                actual_payment_method = 'pending' if is_pending else payment_method

                # Get phone number if provided
                customer_phone = ""
                if hasattr(self, 'bill_phone_entry'):
                    customer_phone = self.bill_phone_entry.get().strip()

                # Calculate discount
                discount_percent = float(self.discount_entry.get() or 0)

                # Calculate with discount
                discount_amount = 0
                final_total = total
                if discount_percent > 0 and not is_complimentary:
                    discount_amount = total * (discount_percent / 100)
                    final_total = total - discount_amount

                cash_received = 0
                change_returned = 0

                if payment_method == 'cash' and not is_complimentary and not is_pending:
                    cash_received = float(self.cash_received_entry.get() or 0)
                    if cash_received < final_total:
                        raise ValueError(f"Insufficient cash. Need ₹{final_total:.2f}")
                    change_returned = cash_received - final_total

                # Prepare payment data
                payment_data = {
                    'payment_method': actual_payment_method,
                    'is_complimentary': is_complimentary,
                    'discount_percentage': discount_percent,
                    'cash_received': cash_received,
                    'change_returned': change_returned,
                    'customer_phone': customer_phone,
                    'payment_status': 'pending' if is_pending else 'paid'
                }

                # Add pending data if applicable
                if is_pending:
                    pending_data = {
                        'customer_name': self.pending_customer_name.get().strip(),
                        'customer_phone': self.pending_customer_phone.get().strip(),
                        'reference_name': self.pending_ref_name.get().strip(),
                        'reference_phone': self.pending_ref_phone.get().strip(),
                        'reference_notes': self.pending_notes.get('1.0', tk.END).strip()
                    }

                    # Validate pending data
                    if not pending_data['reference_name']:
                        raise ValueError("Reference name is required for pending bills")
                    if not pending_data['reference_phone']:
                        raise ValueError("Reference phone number is required for pending bills")

                    payment_data['pending_data'] = pending_data

                bill_number = self.restaurant.generate_bill(order_id, payment_data)

                # Get the bill_id for printing
                bills = self.restaurant.get_all_bills(bill_number=bill_number)
                if bills:
                    self.current_bill_id = bills[0]['id']

                # Show success message
                if is_pending:
                    self.show_info(
                        f"✅ Pending bill created successfully!\n\nBill #: {bill_number}\n\nThis bill has been recorded as pending and will appear in the Pending Bills section.")
                elif customer_phone:
                    self.show_info(
                        f"✅ Bill generated successfully!\n\nBill #: {bill_number}\n\nSMS bill will be sent to {customer_phone}")
                else:
                    self.show_info(f"✅ Bill generated successfully!\n\nBill #: {bill_number}")

                # Ask if user wants to print the bill
                if self.ask_confirmation("Do you want to print the bill now?"):
                    if self.current_bill_id:
                        self.restaurant.print_document('bill', self.current_bill_id, 'bill')
                    else:
                        self.show_error("Bill ID not found for printing")

                dialog.destroy()
                self.load_billable_orders_popup()

            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(f"Error generating bill: {str(e)}")

        # Buttons frame
        button_frame = tk.Frame(scrollable_frame, bg='white')
        button_frame.pack(pady=20)

        generate_btn = tk.Button(button_frame, text="🧾 GENERATE BILL",
                                 font=('Segoe UI', 14, 'bold'),
                                 bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                                 command=generate_bill_action, padx=30, pady=10)
        generate_btn.pack(side=tk.LEFT, padx=10)

        cancel_btn = tk.Button(button_frame, text="CANCEL",
                               font=('Segoe UI', 14, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                               command=dialog.destroy, padx=30, pady=10)
        cancel_btn.pack(side=tk.LEFT, padx=10)

        # Bind Enter key to generate button
        generate_btn.bind('<Return>', lambda e: generate_bill_action())

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def toggle_payment_fields_popup(self, event=None):
        """Toggle payment fields based on method in popup."""
        method = self.payment_method_var.get()

        if method == 'complimentary':
            self.cash_received_entry.config(state='disabled')
            self.change_label.config(text="Change: ₹0.00")
            self.discount_entry.config(state='disabled')
            self.pending_frame.grid_remove()
        elif method == 'pending':
            self.cash_received_entry.config(state='disabled')
            self.change_label.config(text="")
            self.discount_entry.config(state='normal')
            self.pending_frame.grid()
        elif method == 'cash':
            self.cash_received_entry.config(state='normal')
            self.discount_entry.config(state='normal')
            self.pending_frame.grid_remove()
            self.calculate_change_popup()
        else:
            self.cash_received_entry.config(state='disabled')
            self.discount_entry.config(state='normal')
            self.pending_frame.grid_remove()
            self.change_label.config(text="")

    def calculate_discount_popup(self, event=None):
        """Calculate discount and update display in popup."""
        try:
            # Get the total from the adjusted total label
            total_text = self.adjusted_total_label.cget('text')
            if 'Final Total:' in total_text:
                original_total = float(total_text.replace('Final Total: ₹', ''))
            else:
                return

            discount_percent = float(self.discount_entry.get() or 0)
            discount_amount = original_total * (discount_percent / 100)
            final_total = original_total - discount_amount

            self.adjusted_total_label.config(text=f"Final Total: ₹{final_total:.2f}")

            # Update cash change calculation
            self.calculate_change_popup()
        except:
            pass

    def calculate_change_popup(self, event=None):
        """Calculate change for cash payment in popup."""
        try:
            total_text = self.adjusted_total_label.cget('text')
            total = float(total_text.replace('Final Total: ₹', ''))

            cash_received = float(self.cash_received_entry.get() or 0)
            change = cash_received - total

            if change >= 0:
                self.change_label.config(text=f"Change: ₹{change:.2f}", fg='#27ae60')
            else:
                self.change_label.config(text=f"Short: ₹{abs(change):.2f}", fg='#c0392b')
        except:
            pass

    def create_reports_in_popup(self, parent):
        """Create reports screen in popup."""
        # Date frame
        date_frame = tk.Frame(parent, bg='white')
        date_frame.pack(fill=tk.X, pady=(0, 20))

        tk.Label(date_frame, text="Report Date:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)

        self.report_date = tk.Entry(date_frame, font=('Segoe UI', 11), width=12)
        self.report_date.pack(side=tk.LEFT, padx=5)
        self.report_date.insert(0, date.today().isoformat())
        self.report_date.bind('<Return>', lambda e: self.generate_report_popup())

        generate_btn = tk.Button(date_frame, text="📊 GENERATE",
                                 font=('Segoe UI', 11, 'bold'),
                                 bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                                 command=self.generate_report_popup, padx=15, pady=5)
        generate_btn.pack(side=tk.LEFT, padx=10)

        print_btn = tk.Button(date_frame, text="🖨️ PRINT REPORT",
                              font=('Segoe UI', 11, 'bold'),
                              bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                              command=self.print_report_popup, padx=15, pady=5)
        print_btn.pack(side=tk.LEFT, padx=5)

        # Report text
        self.report_text = tk.Text(parent, font=('Courier', 11), height=25)
        self.report_text.pack(fill=tk.BOTH, expand=True)

        self.generate_report_popup()

    def generate_report_popup(self):
        """Generate and display report in popup."""
        try:
            day_date = self.report_date.get()
            report = self.restaurant.get_daily_sales_report(day_date)

            # Get the day summary which contains opening and closing cash
            day_summary = report['day_summary']

            # Calculate expected cash (opening + restaurant cash sales)
            opening_cash = day_summary.get('opening_cash', 0) if day_summary else 0
            closing_cash = day_summary.get('closing_cash', 0) if day_summary else 0
            expected_cash = report['restaurant_cash'] + opening_cash

            # Calculate variance
            if closing_cash > 0:
                variance = closing_cash - expected_cash
                variance_status = "OVER" if variance > 0 else "SHORT" if variance < 0 else "BALANCED"
            else:
                variance = 0
                variance_status = "DAY NOT CLOSED"

            report_content = f"""
   {'=' * 70}
   {' ' * 25}THE EVAANI HOTEL
   {' ' * 23}RESTAURANT DAILY REPORT
   {'=' * 70}

   Date: {day_date}

   {'=' * 70}
   DAY SUMMARY
   {'-' * 70}
   """

            if day_summary:
                opened_at = day_summary.get('opened_at', 'N/A')[:16] if day_summary.get('opened_at') else 'N/A'
                closed_at = day_summary.get('closed_at', 'N/A')[:16] if day_summary.get('closed_at') else 'N/A'
                day_status = 'OPEN' if day_summary.get('is_open') else 'CLOSED'

                report_content += f"""
   Day Status: {day_status}
   Opened At: {opened_at}
   Closed At: {closed_at}
   {'=' * 70}
   CASH BALANCE SUMMARY
   {'-' * 70}
   Opening Cash: {' ' * 39} ₹{opening_cash:>10.2f}
   Restaurant Cash Sales: {' ' * 33} ₹{report['restaurant_cash']:>10.2f}
   {'-' * 70}
   Expected Cash Balance: {' ' * 34} ₹{expected_cash:>10.2f}
   Actual Closing Cash: {' ' * 35} ₹{closing_cash:>10.2f}
   {'-' * 70}
   Variance: {' ' * 44} ₹{variance:>10.2f} ({variance_status})
   {'=' * 70}
   """
            else:
                report_content += "\nNo day record found\n"
                report_content += f"""
   {'=' * 70}
   CASH BALANCE SUMMARY
   {'-' * 70}
   Opening Cash: {' ' * 39} ₹    0.00
   Restaurant Cash Sales: {' ' * 33} ₹{report['restaurant_cash']:>10.2f}
   {'-' * 70}
   Expected Cash Balance: {' ' * 34} ₹{report['restaurant_cash']:>10.2f}
   Actual Closing Cash: {' ' * 35} ₹    0.00
   {'-' * 70}
   Variance: {' ' * 44} ₹{-report['restaurant_cash']:>10.2f} (DAY NOT CLOSED)
   {'=' * 70}
   """

            report_content += f"""
   SALES BREAKDOWN
   {'-' * 70}

   Total Bills: {report['total_bills']}
     ├─ Restaurant Bills: {report['restaurant_bills']}
     └─ Room Service Bills: {report['room_bills']}

   Paid Bills: {report['paid_bills']}
   Complimentary Bills: {report['comp_bills']}

   {'=' * 70}
   RESTAURANT SALES (for day closing)
   {'-' * 70}

   Cash Sales:      ₹{report['restaurant_cash']:>10.2f}
   Card Sales:      ₹{report['restaurant_card']:>10.2f}
   UPI Sales:       ₹{report['restaurant_upi']:>10.2f}
   {'-' * 70}
   RESTAURANT TOTAL: ₹{report['restaurant_total']:>10.2f}
   {'=' * 70}

   ROOM SERVICE SALES (to be added to hotel bill)
   {'-' * 70}

   Cash Sales:      ₹{report['room_cash']:>10.2f}
   Card Sales:      ₹{report['room_card']:>10.2f}
   UPI Sales:       ₹{report['room_upi']:>10.2f}
   {'-' * 70}
   ROOM SERVICE TOTAL: ₹{report['room_total']:>10.2f}
   {'=' * 70}

   COMPLIMENTARY SALES
   {'-' * 70}

   Complimentary Total: ₹{report['complimentary_total']:>10.2f}
   {'=' * 70}

   GRAND TOTAL (All Sales): ₹{report['grand_total']:>10.2f}
   {'=' * 70}

   Room Service Cash (To be deposited separately): ₹{report['room_cash']:>10.2f}

   {'=' * 70}
   """

            self.report_text.delete('1.0', tk.END)
            self.report_text.insert('1.0', report_content)

        except Exception as e:
            self.show_error(f"Error generating report: {str(e)}")

    def print_report_popup(self):
        """Print the current report in popup."""
        report_content = self.report_text.get('1.0', tk.END)
        if report_content.strip():
            self.show_print_preview("Daily Sales Report", report_content, "report")

    def create_restaurant_management_in_popup(self, parent):
        """Create restaurant management screen in popup."""
        # Button frame
        button_frame = tk.Frame(parent, bg='white')
        button_frame.pack(fill=tk.X, pady=(0, 20))

        if self.auth.is_admin():
            add_btn = tk.Button(button_frame, text="➕ ADD RESTAURANT",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                                command=self.add_restaurant_dialog_popup, padx=15, pady=5)
            add_btn.pack(side=tk.LEFT, padx=5)

            edit_btn = tk.Button(button_frame, text="✏️ EDIT",
                                 font=('Segoe UI', 11, 'bold'),
                                 bg='#f39c12', fg='black', relief='flat', cursor='hand2',
                                 command=self.edit_restaurant_popup, padx=15, pady=5)
            edit_btn.pack(side=tk.LEFT, padx=5)

            delete_btn = tk.Button(button_frame, text="🗑️ DELETE",
                                   font=('Segoe UI', 11, 'bold'),
                                   bg='#c0392b', fg='black', relief='flat', cursor='hand2',
                                   command=self.delete_restaurant_popup, padx=15, pady=5)
            delete_btn.pack(side=tk.LEFT, padx=5)

        refresh_btn = tk.Button(button_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_restaurants_data_popup, padx=15, pady=5)
        refresh_btn.pack(side=tk.RIGHT, padx=5)

        # Treeview frame
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ('ID', 'Code', 'Name', 'Table Count', 'Created')
        self.restaurants_tree = ttk.Treeview(tree_container, columns=columns,
                                             yscrollcommand=v_scrollbar.set,
                                             height=15)

        v_scrollbar.config(command=self.restaurants_tree.yview)

        for col in columns:
            self.restaurants_tree.heading(col, text=col, anchor=tk.W)
            self.restaurants_tree.column(col, width=120)

        self.restaurants_tree.pack(fill=tk.BOTH, expand=True)

        self.load_restaurants_data_popup()

    def load_restaurants_data_popup(self):
        """Load restaurants into treeview in popup."""
        if not hasattr(self, 'restaurants_tree'):
            return

        for item in self.restaurants_tree.get_children():
            self.restaurants_tree.delete(item)

        restaurants = self.restaurant.get_all_restaurants()

        for rest in restaurants:
            values = (
                rest['id'],
                rest['restaurant_code'],
                rest['restaurant_name'],
                rest['table_count'],
                rest['created_at'][:10] if rest['created_at'] else ''
            )
            self.restaurants_tree.insert('', tk.END, values=values)

    def add_restaurant_dialog_popup(self):
        """Dialog to add restaurant in popup."""
        dialog = tk.Toplevel(self.current_popup)
        dialog.title("Add Restaurant")
        dialog.geometry("400x300")
        dialog.transient(self.current_popup)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 400, 300)

        # Bind Escape to close
        dialog.bind('<Escape>', lambda e: dialog.destroy())

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="ADD RESTAURANT", font=('Segoe UI', 16, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        tk.Label(main_frame, text="Restaurant Code (R1-R5):", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(anchor='w', pady=(5, 2))
        code_entry = tk.Entry(main_frame, font=('Segoe UI', 12))
        code_entry.pack(fill=tk.X, pady=(0, 10))
        code_entry.bind('<Return>', lambda e: name_entry.focus())

        tk.Label(main_frame, text="Restaurant Name:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(anchor='w', pady=(5, 2))
        name_entry = tk.Entry(main_frame, font=('Segoe UI', 12))
        name_entry.pack(fill=tk.X, pady=(0, 10))
        name_entry.bind('<Return>', lambda e: count_entry.focus())

        tk.Label(main_frame, text="Number of Tables:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(anchor='w', pady=(5, 2))
        count_entry = tk.Entry(main_frame, font=('Segoe UI', 12))
        count_entry.pack(fill=tk.X, pady=(0, 20))
        count_entry.insert(0, '10')
        count_entry.bind('<Return>', lambda e: add_action())

        def add_action():
            try:
                data = {
                    'code': code_entry.get().strip().upper(),
                    'name': name_entry.get().strip(),
                    'table_count': int(count_entry.get())
                }

                if not data['code'] or not data['name']:
                    raise ValueError("Code and name are required")

                self.restaurant.add_restaurant(data)
                self.show_info("Restaurant added successfully!")
                self.load_restaurants_data_popup()
                dialog.destroy()

            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(str(e))

        button_frame = tk.Frame(main_frame, bg='white')
        button_frame.pack(pady=10)

        add_btn = tk.Button(button_frame, text="ADD", font=('Segoe UI', 12, 'bold'),
                            bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                            command=add_action, padx=30, pady=8)
        add_btn.pack(side=tk.LEFT, padx=10)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                               command=dialog.destroy, padx=30, pady=8)
        cancel_btn.pack(side=tk.LEFT, padx=10)

        # Bind Enter key to add button
        add_btn.bind('<Return>', lambda e: add_action())

    def edit_restaurant_popup(self):
        """Edit selected restaurant in popup."""
        selection = self.restaurants_tree.selection()
        if not selection:
            self.show_warning("Please select a restaurant")
            return

        rest_id = self.restaurants_tree.item(selection[0])['values'][0]
        rest = self.restaurant.get_restaurant_by_id(rest_id)

        if not rest:
            self.show_error("Restaurant not found")
            return

        dialog = tk.Toplevel(self.current_popup)
        dialog.title("Edit Restaurant")
        dialog.geometry("400x250")
        dialog.transient(self.current_popup)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 400, 250)

        # Bind Escape to close
        dialog.bind('<Escape>', lambda e: dialog.destroy())

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="EDIT RESTAURANT", font=('Segoe UI', 16, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        tk.Label(main_frame, text="Restaurant Name:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(anchor='w', pady=(5, 2))
        name_entry = tk.Entry(main_frame, font=('Segoe UI', 12))
        name_entry.pack(fill=tk.X, pady=(0, 10))
        name_entry.insert(0, rest['restaurant_name'])
        name_entry.bind('<Return>', lambda e: count_entry.focus())

        tk.Label(main_frame, text="Number of Tables:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(anchor='w', pady=(5, 2))
        count_entry = tk.Entry(main_frame, font=('Segoe UI', 12))
        count_entry.pack(fill=tk.X, pady=(0, 20))
        count_entry.insert(0, str(rest['table_count']))
        count_entry.bind('<Return>', lambda e: update_action())

        def update_action():
            try:
                data = {
                    'name': name_entry.get().strip(),
                    'table_count': int(count_entry.get())
                }

                if not data['name']:
                    raise ValueError("Name is required")

                self.restaurant.update_restaurant(rest_id, data)
                self.show_info("Restaurant updated successfully!")
                self.load_restaurants_data_popup()
                dialog.destroy()

            except ValueError as e:
                self.show_error(str(e))

        button_frame = tk.Frame(main_frame, bg='white')
        button_frame.pack(pady=10)

        update_btn = tk.Button(button_frame, text="UPDATE", font=('Segoe UI', 12, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                               command=update_action, padx=30, pady=8)
        update_btn.pack(side=tk.LEFT, padx=10)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                               command=dialog.destroy, padx=30, pady=8)
        cancel_btn.pack(side=tk.LEFT, padx=10)

        # Bind Enter key to update button
        update_btn.bind('<Return>', lambda e: update_action())

    def delete_restaurant_popup(self):
        """Delete selected restaurant in popup."""
        selection = self.restaurants_tree.selection()
        if not selection:
            self.show_warning("Please select a restaurant")
            return

        rest_id = self.restaurants_tree.item(selection[0])['values'][0]
        rest_name = self.restaurants_tree.item(selection[0])['values'][2]

        if self.ask_confirmation(f"Delete restaurant '{rest_name}'? This will also delete all tables."):
            try:
                self.restaurant.delete_restaurant(rest_id)
                self.show_info("Restaurant deleted")
                self.load_restaurants_data_popup()
            except Exception as e:
                self.show_error(str(e))

    def create_menu_management_in_popup(self, parent):
        """Create menu management screen in popup."""
        # Category info frame
        cat_frame = tk.LabelFrame(parent, text="Categories",
                                  font=('Segoe UI', 12, 'bold'),
                                  bg='white', fg='#6a4334', padx=20, pady=15)
        cat_frame.pack(fill=tk.X, pady=(0, 20))

        categories = self.restaurant.get_all_categories()
        cat_list = ', '.join([c['category_name'] for c in categories])

        tk.Label(cat_frame, text=f"Categories: {cat_list}", font=('Segoe UI', 11),
                 bg='white', fg='#2e86c1').pack(anchor='w', pady=5)

        if self.auth.is_admin():
            add_cat_btn = tk.Button(cat_frame, text="➕ ADD CATEGORY",
                                    font=('Segoe UI', 11, 'bold'),
                                    bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                                    command=self.add_category_dialog_popup, padx=15, pady=5)
            add_cat_btn.pack(pady=5)

        # Button frame
        button_frame = tk.Frame(parent, bg='white')
        button_frame.pack(fill=tk.X, pady=(0, 20))

        if self.auth.is_admin():
            add_btn = tk.Button(button_frame, text="➕ ADD MENU ITEM",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                                command=self.add_menu_item_dialog_popup, padx=15, pady=5)
            add_btn.pack(side=tk.LEFT, padx=5)

            edit_btn = tk.Button(button_frame, text="✏️ EDIT",
                                 font=('Segoe UI', 11, 'bold'),
                                 bg='#f39c12', fg='black', relief='flat', cursor='hand2',
                                 command=self.edit_menu_item_popup, padx=15, pady=5)
            edit_btn.pack(side=tk.LEFT, padx=5)

            delete_btn = tk.Button(button_frame, text="🗑️ DELETE",
                                   font=('Segoe UI', 11, 'bold'),
                                   bg='#c0392b', fg='black', relief='flat', cursor='hand2',
                                   command=self.delete_menu_item_popup, padx=15, pady=5)
            delete_btn.pack(side=tk.LEFT, padx=5)

        refresh_btn = tk.Button(button_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_menu_data_popup, padx=15, pady=5)
        refresh_btn.pack(side=tk.RIGHT, padx=5)

        # Treeview frame
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        columns = ('ID', 'Item Name', 'Category', 'Price', 'Tax %', 'Inventory Item', 'Description')
        self.menu_tree = ttk.Treeview(tree_container, columns=columns,
                                      yscrollcommand=v_scrollbar.set,
                                      xscrollcommand=h_scrollbar.set,
                                      height=15)

        v_scrollbar.config(command=self.menu_tree.yview)
        h_scrollbar.config(command=self.menu_tree.xview)

        for col in columns:
            self.menu_tree.heading(col, text=col, anchor=tk.W)
            self.menu_tree.column(col, width=100)

        self.menu_tree.column('ID', width=50)
        self.menu_tree.column('Item Name', width=150)
        self.menu_tree.column('Description', width=200)

        self.menu_tree.pack(fill=tk.BOTH, expand=True)

        self.load_menu_data_popup()

    def load_menu_data_popup(self):
        """Load menu items into treeview in popup."""
        if not hasattr(self, 'menu_tree'):
            return

        for item in self.menu_tree.get_children():
            self.menu_tree.delete(item)

        items = self.restaurant.get_all_menu_items()

        for item in items:
            values = (
                item['id'],
                item['item_name'],
                item['category_name'],
                f"₹{item['price']:.2f}",
                f"{item['tax_percentage']}%",
                item.get('inventory_item_name', ''),
                item.get('description', '')[:30] + '...' if len(item.get('description', '')) > 30 else item.get(
                    'description', '')
            )
            self.menu_tree.insert('', tk.END, values=values)

    def add_category_dialog_popup(self):
        """Dialog to add category in popup."""
        dialog = tk.Toplevel(self.current_popup)
        dialog.title("Add Category")
        dialog.geometry("400x250")
        dialog.transient(self.current_popup)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 400, 250)

        # Bind Escape to close
        dialog.bind('<Escape>', lambda e: dialog.destroy())

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="ADD CATEGORY", font=('Segoe UI', 16, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        tk.Label(main_frame, text="Category Name:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(anchor='w', pady=(5, 2))
        name_entry = tk.Entry(main_frame, font=('Segoe UI', 12))
        name_entry.pack(fill=tk.X, pady=(0, 10))
        name_entry.bind('<Return>', lambda e: tax_checkbox.focus())

        tax_exempt_var = tk.BooleanVar(value=False)
        tax_checkbox = ttk.Checkbutton(main_frame, text="Tax Exempt (Beverages)",
                                       variable=tax_exempt_var)
        tax_checkbox.pack(anchor='w', pady=10)
        tax_checkbox.bind('<Return>', lambda e: add_action())

        def add_action():
            try:
                name = name_entry.get().strip()
                if not name:
                    raise ValueError("Category name is required")

                self.restaurant.add_category(name, tax_exempt_var.get())
                self.show_info("Category added successfully!")
                dialog.destroy()
                # Refresh menu management
                self.create_menu_management_in_popup(self.current_popup)

            except Exception as e:
                self.show_error(str(e))

        button_frame = tk.Frame(main_frame, bg='white')
        button_frame.pack(pady=10)

        add_btn = tk.Button(button_frame, text="ADD", font=('Segoe UI', 12, 'bold'),
                            bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                            command=add_action, padx=30, pady=8)
        add_btn.pack(side=tk.LEFT, padx=10)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                               command=dialog.destroy, padx=30, pady=8)
        cancel_btn.pack(side=tk.LEFT, padx=10)

        # Bind Enter key to add button
        add_btn.bind('<Return>', lambda e: add_action())

    def add_menu_item_dialog_popup(self):
        """Dialog to add menu item in popup."""
        dialog = tk.Toplevel(self.current_popup)
        dialog.title("Add Menu Item")
        dialog.geometry("500x650")
        dialog.transient(self.current_popup)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 500, 650)

        # Bind Escape to close
        dialog.bind('<Escape>', lambda e: dialog.destroy())

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="ADD MENU ITEM", font=('Segoe UI', 16, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        form_frame = tk.Frame(main_frame, bg='white')
        form_frame.pack(fill=tk.BOTH, expand=True)

        row = 0
        tk.Label(form_frame, text="Item Name *", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        name_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        name_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        name_entry.bind('<Return>', lambda e: cat_combo.focus())
        row += 1

        tk.Label(form_frame, text="Category *", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        categories = self.restaurant.get_all_categories()
        cat_var = tk.StringVar()
        cat_combo = ttk.Combobox(form_frame, textvariable=cat_var,
                                 values=[c['category_name'] for c in categories],
                                 state='readonly', width=28, font=('Segoe UI', 11))
        cat_combo.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        cat_combo.bind('<<ComboboxSelected>>', lambda e: price_entry.focus())
        row += 1

        tk.Label(form_frame, text="Price (₹) *", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        price_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        price_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        price_entry.insert(0, '0.00')
        price_entry.bind('<Return>', lambda e: tax_entry.focus())
        row += 1

        tk.Label(form_frame, text="Tax % *", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        tax_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        tax_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        tax_entry.insert(0, '5.0')
        tax_entry.bind('<Return>', lambda e: inv_entry.focus())
        row += 1

        tk.Label(form_frame, text="Inventory Item", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        inv_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        inv_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        inv_entry.bind('<Return>', lambda e: desc_text.focus())
        row += 1

        tk.Label(form_frame, text="Description", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='ne')
        desc_text = tk.Text(form_frame, font=('Segoe UI', 11), width=30, height=4)
        desc_text.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        desc_text.bind('<Return>', lambda e: add_action())
        row += 1

        def add_action():
            try:
                name = name_entry.get().strip()
                category_name = cat_var.get()
                price = float(price_entry.get())
                tax_percentage = float(tax_entry.get())

                if not name:
                    raise ValueError("Item name is required")
                if not category_name:
                    raise ValueError("Please select a category")
                if tax_percentage < 0 or tax_percentage > 100:
                    raise ValueError("Tax percentage must be between 0 and 100")

                cat_id = None
                for c in categories:
                    if c['category_name'] == category_name:
                        cat_id = c['id']
                        break

                data = {
                    'item_name': name,
                    'category_id': cat_id,
                    'price': price,
                    'tax_percentage': tax_percentage,
                    'inventory_item_name': inv_entry.get().strip(),
                    'description': desc_text.get('1.0', tk.END).strip()
                }

                self.restaurant.add_menu_item(data)
                self.show_info("Menu item added successfully!")
                self.load_menu_data_popup()
                dialog.destroy()

            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(str(e))

        button_frame = tk.Frame(form_frame, bg='white')
        button_frame.grid(row=row, column=0, columnspan=2, pady=15)

        add_btn = tk.Button(button_frame, text="ADD ITEM", font=('Segoe UI', 12, 'bold'),
                            bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                            command=add_action, padx=30, pady=8)
        add_btn.pack(side=tk.LEFT, padx=10)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                               command=dialog.destroy, padx=30, pady=8)
        cancel_btn.pack(side=tk.LEFT, padx=10)

        # Bind Enter key to add button
        add_btn.bind('<Return>', lambda e: add_action())

    def edit_menu_item_popup(self):
        """Edit selected menu item in popup."""
        selection = self.menu_tree.selection()
        if not selection:
            self.show_warning("Please select a menu item")
            return

        item_id = self.menu_tree.item(selection[0])['values'][0]
        item = self.restaurant.get_menu_item_by_id(item_id)

        if not item:
            self.show_error("Item not found")
            return

        dialog = tk.Toplevel(self.current_popup)
        dialog.title("Edit Menu Item")
        dialog.geometry("500x650")
        dialog.transient(self.current_popup)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 500, 650)

        # Bind Escape to close
        dialog.bind('<Escape>', lambda e: dialog.destroy())

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="EDIT MENU ITEM", font=('Segoe UI', 16, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        form_frame = tk.Frame(main_frame, bg='white')
        form_frame.pack(fill=tk.BOTH, expand=True)

        row = 0
        tk.Label(form_frame, text="Item Name", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        name_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        name_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        name_entry.insert(0, item['item_name'])
        name_entry.bind('<Return>', lambda e: cat_combo.focus())
        row += 1

        tk.Label(form_frame, text="Category", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        categories = self.restaurant.get_all_categories()
        cat_var = tk.StringVar(value=item['category_name'])
        cat_combo = ttk.Combobox(form_frame, textvariable=cat_var,
                                 values=[c['category_name'] for c in categories],
                                 state='readonly', width=28, font=('Segoe UI', 11))
        cat_combo.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        cat_combo.bind('<<ComboboxSelected>>', lambda e: price_entry.focus())
        row += 1

        tk.Label(form_frame, text="Price (₹)", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        price_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        price_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        price_entry.insert(0, str(item['price']))
        price_entry.bind('<Return>', lambda e: tax_entry.focus())
        row += 1

        tk.Label(form_frame, text="Tax %", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        tax_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        tax_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        tax_entry.insert(0, str(item['tax_percentage']))
        tax_entry.bind('<Return>', lambda e: inv_entry.focus())
        row += 1

        tk.Label(form_frame, text="Inventory Item", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        inv_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        inv_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        inv_entry.insert(0, item.get('inventory_item_name', ''))
        inv_entry.bind('<Return>', lambda e: desc_text.focus())
        row += 1

        tk.Label(form_frame, text="Description", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='ne')
        desc_text = tk.Text(form_frame, font=('Segoe UI', 11), width=30, height=4)
        desc_text.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        desc_text.insert('1.0', item.get('description', ''))
        desc_text.bind('<Return>', lambda e: update_action())
        row += 1

        def update_action():
            try:
                category_name = cat_var.get()
                cat_id = None
                for c in categories:
                    if c['category_name'] == category_name:
                        cat_id = c['id']
                        break

                data = {
                    'item_name': name_entry.get().strip(),
                    'category_id': cat_id,
                    'price': float(price_entry.get()),
                    'tax_percentage': float(tax_entry.get()),
                    'inventory_item_name': inv_entry.get().strip(),
                    'description': desc_text.get('1.0', tk.END).strip(),
                    'is_available': True
                }

                self.restaurant.update_menu_item(item_id, data)
                self.show_info("Menu item updated successfully!")
                self.load_menu_data_popup()
                dialog.destroy()

            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(str(e))

        button_frame = tk.Frame(form_frame, bg='white')
        button_frame.grid(row=row, column=0, columnspan=2, pady=15)

        update_btn = tk.Button(button_frame, text="UPDATE", font=('Segoe UI', 12, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                               command=update_action, padx=30, pady=8)
        update_btn.pack(side=tk.LEFT, padx=10)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                               command=dialog.destroy, padx=30, pady=8)
        cancel_btn.pack(side=tk.LEFT, padx=10)

        # Bind Enter key to update button
        update_btn.bind('<Return>', lambda e: update_action())

    def delete_menu_item_popup(self):
        """Delete selected menu item in popup."""
        selection = self.menu_tree.selection()
        if not selection:
            self.show_warning("Please select a menu item")
            return

        item_id = self.menu_tree.item(selection[0])['values'][0]
        item_name = self.menu_tree.item(selection[0])['values'][1]

        if self.ask_confirmation(f"Delete '{item_name}'?"):
            try:
                self.restaurant.delete_menu_item(item_id)
                self.show_info("Item deleted")
                self.load_menu_data_popup()
            except Exception as e:
                self.show_error(str(e))

    def create_all_bills_in_popup(self, parent):
        """Create all bills screen in popup."""
        # Filter frame
        filter_frame = tk.LabelFrame(parent, text="Filter Bills",
                                     font=('Segoe UI', 11, 'bold'),
                                     bg='white', fg='#6a4334', padx=15, pady=10)
        filter_frame.pack(fill=tk.X, pady=(0, 20))

        # Bill Number filter
        row_frame = tk.Frame(filter_frame, bg='white')
        row_frame.pack(fill=tk.X, pady=5)

        tk.Label(row_frame, text="Bill Number:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.all_bill_number_filter = tk.Entry(row_frame, font=('Segoe UI', 11), width=20)
        self.all_bill_number_filter.pack(side=tk.LEFT, padx=5)
        self.all_bill_number_filter.bind('<Return>', lambda e: self.filter_all_bills_popup())

        search_btn = tk.Button(row_frame, text="🔍 SEARCH",
                               font=('Segoe UI', 10, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.filter_all_bills_popup, padx=15, pady=2)
        search_btn.pack(side=tk.LEFT, padx=5)

        clear_btn = tk.Button(row_frame, text="🔄 CLEAR",
                              font=('Segoe UI', 10, 'bold'),
                              bg='#95a5a6', fg='black', relief='flat',
                              command=self.clear_all_bills_filter_popup, padx=15, pady=2)
        clear_btn.pack(side=tk.LEFT, padx=5)

        # Date range filters
        date_frame = tk.Frame(filter_frame, bg='white')
        date_frame.pack(fill=tk.X, pady=5)

        tk.Label(date_frame, text="From:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.all_from_date = tk.Entry(date_frame, font=('Segoe UI', 11), width=12)
        self.all_from_date.pack(side=tk.LEFT, padx=5)
        self.all_from_date.insert(0, (date.today() - timedelta(days=30)).isoformat())
        self.all_from_date.bind('<Return>', lambda e: self.all_to_date.focus())

        tk.Label(date_frame, text="To:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.all_to_date = tk.Entry(date_frame, font=('Segoe UI', 11), width=12)
        self.all_to_date.pack(side=tk.LEFT, padx=5)
        self.all_to_date.insert(0, date.today().isoformat())
        self.all_to_date.bind('<Return>', lambda e: self.load_all_bills_data_popup())

        filter_btn = tk.Button(date_frame, text="🔍 FILTER BY DATE",
                               font=('Segoe UI', 10, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.load_all_bills_data_popup, padx=15, pady=2)
        filter_btn.pack(side=tk.LEFT, padx=10)

        # Action buttons
        action_frame = tk.Frame(parent, bg='white')
        action_frame.pack(fill=tk.X, pady=(0, 10))

        view_btn = tk.Button(action_frame, text="👁️ VIEW BILL",
                             font=('Segoe UI', 11, 'bold'),
                             bg='#3498db', fg='black', relief='flat', cursor='hand2',
                             command=self.view_selected_all_bill_popup, padx=15, pady=5)
        view_btn.pack(side=tk.LEFT, padx=5)

        print_btn = tk.Button(action_frame, text="🖨️ PRINT BILL",
                              font=('Segoe UI', 11, 'bold'),
                              bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                              command=self.print_selected_all_bill_popup, padx=15, pady=5)
        print_btn.pack(side=tk.LEFT, padx=5)

        refresh_btn = tk.Button(action_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_all_bills_data_popup, padx=15, pady=5)
        refresh_btn.pack(side=tk.RIGHT, padx=5)

        # Treeview
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        columns = ('Bill #', 'Order #', 'Customer', 'Table/Room', 'Date', 'Total', 'Payment', 'Type', 'Created By')
        self.all_bills_tree = ttk.Treeview(tree_container, columns=columns,
                                           yscrollcommand=v_scrollbar.set,
                                           xscrollcommand=h_scrollbar.set,
                                           height=15)

        v_scrollbar.config(command=self.all_bills_tree.yview)
        h_scrollbar.config(command=self.all_bills_tree.xview)

        for col in columns:
            self.all_bills_tree.heading(col, text=col, anchor=tk.W)
            self.all_bills_tree.column(col, width=120)

        self.all_bills_tree.column('Bill #', width=180)
        self.all_bills_tree.column('Order #', width=150)
        self.all_bills_tree.column('Customer', width=150)

        self.all_bills_tree.bind('<Double-Button-1>', lambda e: self.view_selected_all_bill_popup())

        self.all_bills_tree.pack(fill=tk.BOTH, expand=True)

        self.load_all_bills_data_popup()
        # Add Admin Edit button (only visible to admin)
        if self.auth.is_admin():
            admin_edit_btn = tk.Button(action_frame, text="⚙️ ADMIN EDIT",
                                       font=('Segoe UI', 11, 'bold'),
                                       bg='#e67e22', fg='black', relief='flat', cursor='hand2',
                                       command=self.admin_edit_selected_bill_popup, padx=15, pady=5)
            admin_edit_btn.pack(side=tk.LEFT, padx=5)

    def filter_all_bills_popup(self):
        """Filter all bills by bill number in popup."""
        bill_number = self.all_bill_number_filter.get().strip()
        if bill_number:
            try:
                for item in self.all_bills_tree.get_children():
                    self.all_bills_tree.delete(item)

                bills = self.restaurant.get_all_bills(bill_number=bill_number)

                for bill in bills:
                    values = (
                        bill['bill_number'],
                        bill['order_id'],
                        bill['customer_name'],
                        bill.get('table_number') or bill.get('room_number', ''),
                        bill['bill_date'],
                        f"₹{bill['total_amount']:.2f}",
                        bill['payment_method'].upper(),
                        'COMP' if bill['is_complimentary'] else 'PAID',
                        bill.get('created_by_name', '')
                    )

                    tags = ('comp',) if bill['is_complimentary'] else ()
                    self.all_bills_tree.insert('', tk.END, values=values, tags=tags)

                self.all_bills_tree.tag_configure('comp', background='#ffffcc')

            except Exception as e:
                self.show_error(f"Error searching bills: {str(e)}")

    def clear_all_bills_filter_popup(self):
        """Clear all bills filter in popup."""
        self.all_bill_number_filter.delete(0, tk.END)
        self.load_all_bills_data_popup()

    def load_all_bills_data_popup(self):
        """Load all bills data in popup."""
        if not hasattr(self, 'all_bills_tree'):
            return

        for item in self.all_bills_tree.get_children():
            self.all_bills_tree.delete(item)

        try:
            from_date = self.all_from_date.get()
            to_date = self.all_to_date.get()

            bills = self.restaurant.get_all_bills(from_date, to_date)

            for bill in bills:
                values = (
                    bill['bill_number'],
                    bill['order_id'],
                    bill['customer_name'],
                    bill.get('table_number') or bill.get('room_number', ''),
                    bill['bill_date'],
                    f"₹{bill['total_amount']:.2f}",
                    bill['payment_method'].upper(),
                    'COMP' if bill['is_complimentary'] else 'PAID',
                    bill.get('created_by_name', '')
                )

                tags = ('comp',) if bill['is_complimentary'] else ()
                self.all_bills_tree.insert('', tk.END, values=values, tags=tags)

            self.all_bills_tree.tag_configure('comp', background='#ffffcc')

        except Exception as e:
            self.show_error(f"Error loading bills: {str(e)}")

    def view_selected_all_bill_popup(self):
        """View selected bill from all bills in popup."""
        selection = self.all_bills_tree.selection()
        if not selection:
            self.show_warning("Please select a bill to view")
            return

        bill_number = self.all_bills_tree.item(selection[0])['values'][0]
        self.show_bill_preview_popup(bill_number)

    def print_selected_all_bill_popup(self):
        """Print selected bill from all bills in popup."""
        selection = self.all_bills_tree.selection()
        if not selection:
            self.show_warning("Please select a bill to print")
            return

        bill_number = self.all_bills_tree.item(selection[0])['values'][0]
        self.show_bill_preview_popup(bill_number)

    def create_comp_bills_in_popup(self, parent):
        """Create complimentary bills screen in popup."""
        # Filter frame
        filter_frame = tk.LabelFrame(parent, text="Filter",
                                     font=('Segoe UI', 11, 'bold'),
                                     bg='white', fg='#6a4334', padx=15, pady=10)
        filter_frame.pack(fill=tk.X, pady=(0, 20))

        row_frame = tk.Frame(filter_frame, bg='white')
        row_frame.pack(fill=tk.X, pady=5)

        tk.Label(row_frame, text="Bill Number:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.comp_bill_number_filter = tk.Entry(row_frame, font=('Segoe UI', 11), width=20)
        self.comp_bill_number_filter.pack(side=tk.LEFT, padx=5)
        self.comp_bill_number_filter.bind('<Return>', lambda e: self.filter_comp_bills_popup())

        search_btn = tk.Button(row_frame, text="🔍 SEARCH",
                               font=('Segoe UI', 10, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.filter_comp_bills_popup, padx=15, pady=2)
        search_btn.pack(side=tk.LEFT, padx=5)

        clear_btn = tk.Button(row_frame, text="🔄 CLEAR",
                              font=('Segoe UI', 10, 'bold'),
                              bg='#95a5a6', fg='black', relief='flat',
                              command=self.clear_comp_bills_filter_popup, padx=15, pady=2)
        clear_btn.pack(side=tk.LEFT, padx=5)

        tk.Label(row_frame, text="Date:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=20)
        self.comp_date = tk.Entry(row_frame, font=('Segoe UI', 11), width=12)
        self.comp_date.pack(side=tk.LEFT, padx=5)
        self.comp_date.insert(0, date.today().isoformat())
        self.comp_date.bind('<Return>', lambda e: self.load_comp_bills_data_popup())

        load_btn = tk.Button(row_frame, text="🔍 LOAD",
                             font=('Segoe UI', 10, 'bold'),
                             bg='#2e86c1', fg='black', relief='flat',
                             command=self.load_comp_bills_data_popup, padx=15, pady=2)
        load_btn.pack(side=tk.LEFT, padx=10)

        # Action buttons
        action_frame = tk.Frame(parent, bg='white')
        action_frame.pack(fill=tk.X, pady=(0, 10))

        view_btn = tk.Button(action_frame, text="👁️ VIEW BILL",
                             font=('Segoe UI', 11, 'bold'),
                             bg='#3498db', fg='black', relief='flat', cursor='hand2',
                             command=self.view_selected_comp_bill_popup, padx=15, pady=5)
        view_btn.pack(side=tk.LEFT, padx=5)

        print_btn = tk.Button(action_frame, text="🖨️ PRINT BILL",
                              font=('Segoe UI', 11, 'bold'),
                              bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                              command=self.print_selected_comp_bill_popup, padx=15, pady=5)
        print_btn.pack(side=tk.LEFT, padx=5)

        refresh_btn = tk.Button(action_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_comp_bills_data_popup, padx=15, pady=5)
        refresh_btn.pack(side=tk.RIGHT, padx=5)

        # Treeview
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ('Bill #', 'Order #', 'Customer', 'Table/Room', 'Time', 'Total', 'Created By')
        self.comp_bills_tree = ttk.Treeview(tree_container, columns=columns,
                                            yscrollcommand=v_scrollbar.set,
                                            height=15)

        v_scrollbar.config(command=self.comp_bills_tree.yview)

        for col in columns:
            self.comp_bills_tree.heading(col, text=col, anchor=tk.W)
            self.comp_bills_tree.column(col, width=120)

        self.comp_bills_tree.column('Bill #', width=180)
        self.comp_bills_tree.column('Order #', width=150)

        self.comp_bills_tree.bind('<Double-Button-1>', lambda e: self.view_selected_comp_bill_popup())

        self.comp_bills_tree.pack(fill=tk.BOTH, expand=True)

        self.load_comp_bills_data_popup()

    def filter_comp_bills_popup(self):
        """Filter complimentary bills by bill number in popup."""
        bill_number = self.comp_bill_number_filter.get().strip()
        if bill_number:
            try:
                for item in self.comp_bills_tree.get_children():
                    self.comp_bills_tree.delete(item)

                bills = self.restaurant.get_all_bills(bill_number=bill_number)

                for bill in bills:
                    if bill['is_complimentary']:
                        values = (
                            bill['bill_number'],
                            bill['order_id'],
                            bill['customer_name'],
                            bill.get('table_number') or bill.get('room_number', ''),
                            bill['bill_time'][11:16] if bill['bill_time'] else '',
                            f"₹{bill['total_amount']:.2f}",
                            bill.get('created_by_name', '')
                        )
                        self.comp_bills_tree.insert('', tk.END, values=values)

            except Exception as e:
                self.show_error(f"Error searching bills: {str(e)}")

    def clear_comp_bills_filter_popup(self):
        """Clear complimentary bills filter in popup."""
        self.comp_bill_number_filter.delete(0, tk.END)
        self.load_comp_bills_data_popup()

    def load_comp_bills_data_popup(self):
        """Load complimentary bills in popup."""
        if not hasattr(self, 'comp_bills_tree'):
            return

        for item in self.comp_bills_tree.get_children():
            self.comp_bills_tree.delete(item)

        try:
            day_date = self.comp_date.get()
            bills = self.restaurant.get_bills(day_date, complimentary_only=True)

            total_comp = 0

            for bill in bills:
                values = (
                    bill['bill_number'],
                    bill['order_id'],
                    bill['customer_name'],
                    bill.get('table_number') or bill.get('room_number', ''),
                    bill['bill_time'][11:16] if bill['bill_time'] else '',
                    f"₹{bill['total_amount']:.2f}",
                    bill.get('created_by_name', '')
                )
                self.comp_bills_tree.insert('', tk.END, values=values)
                total_comp += bill['total_amount']

            # Add total label - need to find the parent frame
            # Since we're in a popup, we need to get the parent of the tree
            parent_frame = self.comp_bills_tree.master.master.master
            total_frame = tk.Frame(parent_frame, bg='white')
            total_frame.pack(fill=tk.X, pady=10)
            tk.Label(total_frame, text=f"Total Complimentary: ₹{total_comp:.2f}",
                     font=('Segoe UI', 14, 'bold'), bg='white', fg='#c0392b').pack()

        except Exception as e:
            self.show_error(f"Error loading comp bills: {str(e)}")

    def view_selected_comp_bill_popup(self):
        """View selected complimentary bill in popup."""
        selection = self.comp_bills_tree.selection()
        if not selection:
            self.show_warning("Please select a bill to view")
            return

        bill_number = self.comp_bills_tree.item(selection[0])['values'][0]
        self.show_bill_preview_popup(bill_number)

    def print_selected_comp_bill_popup(self):
        """Print selected complimentary bill in popup."""
        selection = self.comp_bills_tree.selection()
        if not selection:
            self.show_warning("Please select a bill to print")
            return

        bill_number = self.comp_bills_tree.item(selection[0])['values'][0]
        self.show_bill_preview_popup(bill_number)

    def create_room_service_bills_in_popup(self, parent):
        """Create room service bills screen in popup."""
        # Filter frame
        filter_frame = tk.LabelFrame(parent, text="Filter",
                                     font=('Segoe UI', 11, 'bold'),
                                     bg='white', fg='#6a4334', padx=15, pady=10)
        filter_frame.pack(fill=tk.X, pady=(0, 20))

        row_frame = tk.Frame(filter_frame, bg='white')
        row_frame.pack(fill=tk.X, pady=5)

        tk.Label(row_frame, text="Bill Number:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.rs_bill_number_filter = tk.Entry(row_frame, font=('Segoe UI', 11), width=20)
        self.rs_bill_number_filter.pack(side=tk.LEFT, padx=5)
        self.rs_bill_number_filter.bind('<Return>', lambda e: self.filter_room_service_bills_popup())

        search_btn = tk.Button(row_frame, text="🔍 SEARCH",
                               font=('Segoe UI', 10, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.filter_room_service_bills_popup, padx=15, pady=2)
        search_btn.pack(side=tk.LEFT, padx=5)

        clear_btn = tk.Button(row_frame, text="🔄 CLEAR",
                              font=('Segoe UI', 10, 'bold'),
                              bg='#95a5a6', fg='black', relief='flat',
                              command=self.clear_room_service_filter_popup, padx=15, pady=2)
        clear_btn.pack(side=tk.LEFT, padx=5)

        tk.Label(row_frame, text="From:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=20)
        self.rs_from_date = tk.Entry(row_frame, font=('Segoe UI', 11), width=12)
        self.rs_from_date.pack(side=tk.LEFT, padx=5)
        self.rs_from_date.insert(0, (date.today() - timedelta(days=30)).isoformat())
        self.rs_from_date.bind('<Return>', lambda e: self.rs_to_date.focus())

        tk.Label(row_frame, text="To:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.rs_to_date = tk.Entry(row_frame, font=('Segoe UI', 11), width=12)
        self.rs_to_date.pack(side=tk.LEFT, padx=5)
        self.rs_to_date.insert(0, date.today().isoformat())
        self.rs_to_date.bind('<Return>', lambda e: self.load_room_service_bills_popup())

        filter_btn = tk.Button(row_frame, text="🔍 FILTER",
                               font=('Segoe UI', 10, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.load_room_service_bills_popup, padx=15, pady=2)
        filter_btn.pack(side=tk.LEFT, padx=10)

        # Action buttons
        action_frame = tk.Frame(parent, bg='white')
        action_frame.pack(fill=tk.X, pady=(0, 10))

        view_btn = tk.Button(action_frame, text="👁️ VIEW BILL",
                             font=('Segoe UI', 11, 'bold'),
                             bg='#3498db', fg='black', relief='flat', cursor='hand2',
                             command=self.view_selected_rs_bill_popup, padx=15, pady=5)
        view_btn.pack(side=tk.LEFT, padx=5)

        print_btn = tk.Button(action_frame, text="🖨️ PRINT BILL",
                              font=('Segoe UI', 11, 'bold'),
                              bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                              command=self.print_selected_rs_bill_popup, padx=15, pady=5)
        print_btn.pack(side=tk.LEFT, padx=5)

        refresh_btn = tk.Button(action_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_room_service_bills_popup, padx=15, pady=5)
        refresh_btn.pack(side=tk.RIGHT, padx=5)

        # Treeview
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        columns = ('Bill #', 'Order #', 'Customer', 'Room No', 'Date', 'Total', 'Payment', 'Created By')
        self.rs_bills_tree = ttk.Treeview(tree_container, columns=columns,
                                          yscrollcommand=v_scrollbar.set,
                                          xscrollcommand=h_scrollbar.set,
                                          height=15)

        v_scrollbar.config(command=self.rs_bills_tree.yview)
        h_scrollbar.config(command=self.rs_bills_tree.xview)

        for col in columns:
            self.rs_bills_tree.heading(col, text=col, anchor=tk.W)
            self.rs_bills_tree.column(col, width=120)

        self.rs_bills_tree.column('Bill #', width=180)
        self.rs_bills_tree.column('Order #', width=150)

        self.rs_bills_tree.bind('<Double-Button-1>', lambda e: self.view_selected_rs_bill_popup())

        self.rs_bills_tree.pack(fill=tk.BOTH, expand=True)

        self.load_room_service_bills_popup()

    def filter_room_service_bills_popup(self):
        """Filter room service bills by bill number in popup."""
        bill_number = self.rs_bill_number_filter.get().strip()
        if bill_number:
            try:
                for item in self.rs_bills_tree.get_children():
                    self.rs_bills_tree.delete(item)

                bills = self.restaurant.get_all_bills(bill_number=bill_number)

                for bill in bills:
                    if bill.get('order_type') == 'room_service':
                        values = (
                            bill['bill_number'],
                            bill['order_id'],
                            bill['customer_name'],
                            bill.get('room_number', ''),
                            bill['bill_date'],
                            f"₹{bill['total_amount']:.2f}",
                            bill['payment_method'].upper(),
                            bill.get('created_by_name', '')
                        )
                        self.rs_bills_tree.insert('', tk.END, values=values)

            except Exception as e:
                self.show_error(f"Error searching bills: {str(e)}")

    def clear_room_service_filter_popup(self):
        """Clear room service bills filter in popup."""
        self.rs_bill_number_filter.delete(0, tk.END)
        self.load_room_service_bills_popup()

    def load_room_service_bills_popup(self):
        """Load room service bills in popup."""
        if not hasattr(self, 'rs_bills_tree'):
            return

        for item in self.rs_bills_tree.get_children():
            self.rs_bills_tree.delete(item)

        try:
            from_date = self.rs_from_date.get()
            to_date = self.rs_to_date.get()

            bills = self.restaurant.get_bills_by_type('room_service', from_date, to_date)

            for bill in bills:
                values = (
                    bill['bill_number'],
                    bill['order_id'],
                    bill['customer_name'],
                    bill.get('room_number', ''),
                    bill['bill_date'],
                    f"₹{bill['total_amount']:.2f}",
                    bill['payment_method'].upper(),
                    bill.get('created_by_name', '')
                )
                self.rs_bills_tree.insert('', tk.END, values=values)

        except Exception as e:
            self.show_error(f"Error loading room service bills: {str(e)}")

    def view_selected_rs_bill_popup(self):
        """View selected room service bill in popup."""
        selection = self.rs_bills_tree.selection()
        if not selection:
            self.show_warning("Please select a bill to view")
            return

        bill_number = self.rs_bills_tree.item(selection[0])['values'][0]
        self.show_bill_preview_popup(bill_number)

    def print_selected_rs_bill_popup(self):
        """Print selected room service bill in popup."""
        selection = self.rs_bills_tree.selection()
        if not selection:
            self.show_warning("Please select a bill to print")
            return

        bill_number = self.rs_bills_tree.item(selection[0])['values'][0]
        self.show_bill_preview_popup(bill_number)

    def create_restaurant_bills_in_popup(self, parent):
        """Create restaurant bills screen in popup."""
        # Filter frame
        filter_frame = tk.LabelFrame(parent, text="Filter",
                                     font=('Segoe UI', 11, 'bold'),
                                     bg='white', fg='#6a4334', padx=15, pady=10)
        filter_frame.pack(fill=tk.X, pady=(0, 20))

        row_frame = tk.Frame(filter_frame, bg='white')
        row_frame.pack(fill=tk.X, pady=5)

        tk.Label(row_frame, text="Bill Number:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.rest_bill_number_filter = tk.Entry(row_frame, font=('Segoe UI', 11), width=20)
        self.rest_bill_number_filter.pack(side=tk.LEFT, padx=5)
        self.rest_bill_number_filter.bind('<Return>', lambda e: self.filter_restaurant_bills_popup())

        search_btn = tk.Button(row_frame, text="🔍 SEARCH",
                               font=('Segoe UI', 10, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.filter_restaurant_bills_popup, padx=15, pady=2)
        search_btn.pack(side=tk.LEFT, padx=5)

        clear_btn = tk.Button(row_frame, text="🔄 CLEAR",
                              font=('Segoe UI', 10, 'bold'),
                              bg='#95a5a6', fg='black', relief='flat',
                              command=self.clear_restaurant_filter_popup, padx=15, pady=2)
        clear_btn.pack(side=tk.LEFT, padx=5)

        tk.Label(row_frame, text="From:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=20)
        self.rest_from_date = tk.Entry(row_frame, font=('Segoe UI', 11), width=12)
        self.rest_from_date.pack(side=tk.LEFT, padx=5)
        self.rest_from_date.insert(0, (date.today() - timedelta(days=30)).isoformat())
        self.rest_from_date.bind('<Return>', lambda e: self.rest_to_date.focus())

        tk.Label(row_frame, text="To:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.rest_to_date = tk.Entry(row_frame, font=('Segoe UI', 11), width=12)
        self.rest_to_date.pack(side=tk.LEFT, padx=5)
        self.rest_to_date.insert(0, date.today().isoformat())
        self.rest_to_date.bind('<Return>', lambda e: self.load_restaurant_bills_popup())

        filter_btn = tk.Button(row_frame, text="🔍 FILTER",
                               font=('Segoe UI', 10, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.load_restaurant_bills_popup, padx=15, pady=2)
        filter_btn.pack(side=tk.LEFT, padx=10)

        # Action buttons
        action_frame = tk.Frame(parent, bg='white')
        action_frame.pack(fill=tk.X, pady=(0, 10))

        view_btn = tk.Button(action_frame, text="👁️ VIEW BILL",
                             font=('Segoe UI', 11, 'bold'),
                             bg='#3498db', fg='black', relief='flat', cursor='hand2',
                             command=self.view_selected_rest_bill_popup, padx=15, pady=5)
        view_btn.pack(side=tk.LEFT, padx=5)

        print_btn = tk.Button(action_frame, text="🖨️ PRINT BILL",
                              font=('Segoe UI', 11, 'bold'),
                              bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                              command=self.print_selected_rest_bill_popup, padx=15, pady=5)
        print_btn.pack(side=tk.LEFT, padx=5)

        refresh_btn = tk.Button(action_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_restaurant_bills_popup, padx=15, pady=5)
        refresh_btn.pack(side=tk.RIGHT, padx=5)

        # Treeview
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        columns = ('Bill #', 'Order #', 'Customer', 'Table', 'Date', 'Total', 'Payment', 'Created By')
        self.rest_bills_tree = ttk.Treeview(tree_container, columns=columns,
                                            yscrollcommand=v_scrollbar.set,
                                            xscrollcommand=h_scrollbar.set,
                                            height=15)

        v_scrollbar.config(command=self.rest_bills_tree.yview)
        h_scrollbar.config(command=self.rest_bills_tree.xview)

        for col in columns:
            self.rest_bills_tree.heading(col, text=col, anchor=tk.W)
            self.rest_bills_tree.column(col, width=120)

        self.rest_bills_tree.column('Bill #', width=180)
        self.rest_bills_tree.column('Order #', width=150)

        self.rest_bills_tree.bind('<Double-Button-1>', lambda e: self.view_selected_rest_bill_popup())

        self.rest_bills_tree.pack(fill=tk.BOTH, expand=True)

        self.load_restaurant_bills_popup()

    def filter_restaurant_bills_popup(self):
        """Filter restaurant bills by bill number in popup."""
        bill_number = self.rest_bill_number_filter.get().strip()
        if bill_number:
            try:
                for item in self.rest_bills_tree.get_children():
                    self.rest_bills_tree.delete(item)

                bills = self.restaurant.get_all_bills(bill_number=bill_number)

                for bill in bills:
                    if bill.get('order_type') != 'room_service':
                        values = (
                            bill['bill_number'],
                            bill['order_id'],
                            bill['customer_name'],
                            bill.get('table_number', ''),
                            bill['bill_date'],
                            f"₹{bill['total_amount']:.2f}",
                            bill['payment_method'].upper(),
                            bill.get('created_by_name', '')
                        )
                        self.rest_bills_tree.insert('', tk.END, values=values)

            except Exception as e:
                self.show_error(f"Error searching bills: {str(e)}")

    def clear_restaurant_filter_popup(self):
        """Clear restaurant bills filter in popup."""
        self.rest_bill_number_filter.delete(0, tk.END)
        self.load_restaurant_bills_popup()

    def load_restaurant_bills_popup(self):
        """Load restaurant bills in popup."""
        if not hasattr(self, 'rest_bills_tree'):
            return

        for item in self.rest_bills_tree.get_children():
            self.rest_bills_tree.delete(item)

        try:
            from_date = self.rest_from_date.get()
            to_date = self.rest_to_date.get()

            bills = self.restaurant.get_bills_by_type('restaurant', from_date, to_date)

            for bill in bills:
                values = (
                    bill['bill_number'],
                    bill['order_id'],
                    bill['customer_name'],
                    bill.get('table_number', ''),
                    bill['bill_date'],
                    f"₹{bill['total_amount']:.2f}",
                    bill['payment_method'].upper(),
                    bill.get('created_by_name', '')
                )
                self.rest_bills_tree.insert('', tk.END, values=values)

        except Exception as e:
            self.show_error(f"Error loading restaurant bills: {str(e)}")

    def view_selected_rest_bill_popup(self):
        """View selected restaurant bill in popup."""
        selection = self.rest_bills_tree.selection()
        if not selection:
            self.show_warning("Please select a bill to view")
            return

        bill_number = self.rest_bills_tree.item(selection[0])['values'][0]
        self.show_bill_preview_popup(bill_number)

    def print_selected_rest_bill_popup(self):
        """Print selected restaurant bill in popup."""
        selection = self.rest_bills_tree.selection()
        if not selection:
            self.show_warning("Please select a bill to print")
            return

        bill_number = self.rest_bills_tree.item(selection[0])['values'][0]
        self.show_bill_preview_popup(bill_number)

    def create_users_in_popup(self, parent):
        """Create user management screen in popup."""
        if not self.auth.is_admin():
            tk.Label(parent, text="Access Denied", font=('Segoe UI', 14, 'bold'),
                     bg='white', fg='#c0392b').pack(pady=50)
            return

        # Button frame
        button_frame = tk.Frame(parent, bg='white')
        button_frame.pack(fill=tk.X, pady=(0, 20))

        add_btn = tk.Button(button_frame, text="➕ ADD USER",
                            font=('Segoe UI', 11, 'bold'),
                            bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                            command=self.add_user_dialog_popup, padx=15, pady=5)
        add_btn.pack(side=tk.LEFT, padx=5)

        delete_btn = tk.Button(button_frame, text="🗑️ DELETE",
                               font=('Segoe UI', 11, 'bold'),
                               bg='#c0392b', fg='black', relief='flat', cursor='hand2',
                               command=self.delete_user_popup, padx=15, pady=5)
        delete_btn.pack(side=tk.LEFT, padx=5)

        refresh_btn = tk.Button(button_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_users_data_popup, padx=15, pady=5)
        refresh_btn.pack(side=tk.RIGHT, padx=5)

        # Treeview frame
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ('ID', 'Username', 'Role', 'Email', 'Created')
        self.users_tree = ttk.Treeview(tree_container, columns=columns,
                                       yscrollcommand=v_scrollbar.set,
                                       height=15)

        v_scrollbar.config(command=self.users_tree.yview)

        for col in columns:
            self.users_tree.heading(col, text=col, anchor=tk.W)
            self.users_tree.column(col, width=120)

        self.users_tree.pack(fill=tk.BOTH, expand=True)

        self.load_users_data_popup()

    def load_users_data_popup(self):
        """Load users into treeview in popup."""
        if not hasattr(self, 'users_tree'):
            return

        for item in self.users_tree.get_children():
            self.users_tree.delete(item)

        users = self.restaurant.get_all_users()

        for user in users:
            values = (
                user['id'],
                user['username'],
                user['role'],
                user.get('email', ''),
                user['created_at'][:10] if user['created_at'] else ''
            )
            self.users_tree.insert('', tk.END, values=values)

    def add_user_dialog_popup(self):
        """Dialog to add user in popup."""
        dialog = tk.Toplevel(self.current_popup)
        dialog.title("Add User")
        dialog.geometry("500x400")
        dialog.transient(self.current_popup)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 500, 400)

        # Bind Escape to close
        dialog.bind('<Escape>', lambda e: dialog.destroy())

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="ADD USER", font=('Segoe UI', 16, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        form_frame = tk.Frame(main_frame, bg='white')
        form_frame.pack(fill=tk.BOTH, expand=True)

        row = 0
        tk.Label(form_frame, text="Username *", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        username_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        username_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        username_entry.bind('<Return>', lambda e: password_entry.focus())
        row += 1

        tk.Label(form_frame, text="Password *", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        password_entry = tk.Entry(form_frame, font=('Segoe UI', 12), show="*", width=30)
        password_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        password_entry.bind('<Return>', lambda e: confirm_entry.focus())
        row += 1

        tk.Label(form_frame, text="Confirm Password *", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        confirm_entry = tk.Entry(form_frame, font=('Segoe UI', 12), show="*", width=30)
        confirm_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        confirm_entry.bind('<Return>', lambda e: role_combo.focus())
        row += 1

        tk.Label(form_frame, text="Role *", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        role_var = tk.StringVar(value='user')
        role_combo = ttk.Combobox(form_frame, textvariable=role_var,
                                  values=['admin', 'user'], state='readonly', width=28,
                                  font=('Segoe UI', 11))
        role_combo.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        role_combo.bind('<<ComboboxSelected>>', lambda e: email_entry.focus())
        row += 1

        tk.Label(form_frame, text="Email", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        email_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        email_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        email_entry.bind('<Return>', lambda e: add_action())
        row += 1

        def add_action():
            try:
                username = username_entry.get().strip()
                password = password_entry.get()
                confirm = confirm_entry.get()
                role = role_var.get()
                email = email_entry.get().strip()

                if not username:
                    raise ValueError("Username is required")
                if not password:
                    raise ValueError("Password is required")
                if password != confirm:
                    raise ValueError("Passwords do not match")
                if len(password) < 4:
                    raise ValueError("Password must be at least 4 characters")

                user_data = {
                    'username': username,
                    'password': password,
                    'role': role,
                    'email': email
                }

                self.restaurant.add_user(user_data)
                self.show_info("User added successfully!")
                self.load_users_data_popup()
                dialog.destroy()

            except Exception as e:
                self.show_error(str(e))

        button_frame = tk.Frame(form_frame, bg='white')
        button_frame.grid(row=row, column=0, columnspan=2, pady=15)

        add_btn = tk.Button(button_frame, text="ADD", font=('Segoe UI', 12, 'bold'),
                            bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                            command=add_action, padx=30, pady=8)
        add_btn.pack(side=tk.LEFT, padx=10)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                               command=dialog.destroy, padx=30, pady=8)
        cancel_btn.pack(side=tk.LEFT, padx=10)

        # Bind Enter key to add button
        add_btn.bind('<Return>', lambda e: add_action())

    def delete_user_popup(self):
        """Delete selected user in popup."""
        selection = self.users_tree.selection()
        if not selection:
            self.show_warning("Please select a user")
            return

        user_id = self.users_tree.item(selection[0])['values'][0]
        username = self.users_tree.item(selection[0])['values'][1]

        if self.ask_confirmation(f"Delete user '{username}'?"):
            try:
                self.restaurant.delete_user(user_id)
                self.show_info("User deleted")
                self.load_users_data_popup()
            except Exception as e:
                self.show_error(str(e))

    def create_settings_in_popup(self, parent):
        """Create settings screen in popup."""
        settings = self.db.get_hotel_settings()

        form_frame = tk.LabelFrame(parent, text="Hotel Information",
                                   font=('Segoe UI', 14, 'bold'),
                                   bg='white', fg='#6a4334', padx=30, pady=30)
        form_frame.pack(fill=tk.BOTH, expand=True, padx=50, pady=20)

        row = 0
        tk.Label(form_frame, text="Hotel Name:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=15, sticky='e')
        self.hotel_name_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=40)
        self.hotel_name_entry.grid(row=row, column=1, padx=10, pady=15, sticky='w')
        self.hotel_name_entry.insert(0, settings.get('hotel_name', 'THE EVAANI HOTEL'))
        self.hotel_name_entry.bind('<Return>', lambda e: self.address_entry.focus())

        row += 1
        tk.Label(form_frame, text="Address:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=15, sticky='ne')
        self.address_entry = tk.Text(form_frame, font=('Segoe UI', 12), width=40, height=3)
        self.address_entry.grid(row=row, column=1, padx=10, pady=15, sticky='w')
        self.address_entry.insert('1.0', settings.get('address', 'Talwandi Road, Mansa'))
        self.address_entry.bind('<Return>', lambda e: self.phone_entry.focus())

        row += 1
        tk.Label(form_frame, text="Phone:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=15, sticky='e')
        self.phone_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=40)
        self.phone_entry.grid(row=row, column=1, padx=10, pady=15, sticky='w')
        self.phone_entry.insert(0, settings.get('phone', '9530752236, 9915297440'))
        self.phone_entry.bind('<Return>', lambda e: self.gstin_entry.focus())

        row += 1
        tk.Label(form_frame, text="GSTIN:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=15, sticky='e')
        self.gstin_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=40)
        self.gstin_entry.grid(row=row, column=1, padx=10, pady=15, sticky='w')
        self.gstin_entry.insert(0, settings.get('gstin', '03AATFJ9071F1Z3'))
        self.gstin_entry.bind('<Return>', lambda e: save_action())

        row += 1
        button_frame = tk.Frame(form_frame, bg='white')
        button_frame.grid(row=row, column=0, columnspan=2, pady=30)

        def save_action():
            try:
                settings_data = {
                    'hotel_name': self.hotel_name_entry.get().strip(),
                    'address': self.address_entry.get('1.0', tk.END).strip(),
                    'phone': self.phone_entry.get().strip(),
                    'gstin': self.gstin_entry.get().strip()
                }

                self.db.update_hotel_settings(settings_data)
                self.show_info("Settings updated successfully!")

            except Exception as e:
                self.show_error(str(e))

        save_btn = tk.Button(button_frame, text="💾 SAVE SETTINGS",
                             font=('Segoe UI', 14, 'bold'),
                             bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                             command=save_action, padx=30, pady=15)
        save_btn.pack()

        # Bind Enter key to save button
        save_btn.bind('<Return>', lambda e: save_action())

    def show_bill_preview_popup(self, bill_number):
        """Show bill preview for selected bill number in popup."""
        try:
            # Get bill details from database
            bills = self.restaurant.get_all_bills(bill_number=bill_number)
            if not bills:
                self.show_error("Bill not found")
                return

            bill = bills[0]  # Get the first matching bill

            # Get order details
            order = self.restaurant.get_order_by_id(bill['order_id'])
            items = self.restaurant.get_order_items(bill['order_id']) if order else []

            # Format bill content for preview
            is_complimentary = bill['is_complimentary']
            payment_method = bill['payment_method']
            discount_percentage = bill.get('discount_percentage', 0)
            discount_amount = bill.get('discount_amount', 0)

            bill_content = f"""
   {'=' * 60}
   {' ' * 20}THE EVAANI HOTEL
   {' ' * 18}RESTAURANT BILL
   {'=' * 60}

   Bill No: {bill['bill_number']}
   Date: {bill['bill_date']} {bill['bill_time'][11:16] if bill['bill_time'] else ''}
   Order No: {bill['order_id']}
   Customer: {bill['customer_name']}
   Table/Room: {bill.get('table_number') or bill.get('room_number', 'N/A')}

   {'=' * 60}
   {'Item':<25} {'Qty':<5} {'Price':<8} {'Total':<8}
   {'-' * 60}
   """

            for item in items:
                bill_content += f"{item['item_name'][:25]:<25} {item['quantity']:<5} ₹{item['unit_price']:<7.2f} ₹{item['total_price']:<7.2f}\n"

            bill_content += f"""
   {'-' * 60}
   Subtotal: {' ' * 45} ₹{bill['subtotal']:.2f}
   Tax: {' ' * 48} ₹{bill['tax_amount']:.2f}
   """

            if discount_percentage > 0:
                bill_content += f"Discount ({discount_percentage}%): {' ' * 40} -₹{discount_amount:.2f}\n"

            bill_content += f"""
   {'=' * 60}
   TOTAL: {' ' * 47} ₹{bill['total_amount']:.2f}
   {'=' * 60}

   Payment Method: {payment_method.upper() if payment_method else 'N/A'}
   Status: {'COMPLIMENTARY' if is_complimentary else 'PAID'}
   GST Included in total amount

   {' ' * 20}Thank you for dining with us!
   {' ' * 18}Visit again!

   {'=' * 60}
   """

            # Show print preview
            self.show_print_preview(f"Bill {bill_number}", bill_content, "bill")

        except Exception as e:
            self.show_error(f"Error showing bill preview: {str(e)}")

    def show_kitchen_preview(self, title, content):
        """Show kitchen print preview with Save & Open for Printing functionality."""
        dialog = tk.Toplevel(self.current_popup if self.current_popup else self.root)
        dialog.title(f"Kitchen Preview - {title}")
        dialog.geometry("500x650")
        dialog.transient(self.current_popup if self.current_popup else self.root)
        dialog.grab_set()
        dialog.configure(bg='white')

        # Bind Ctrl+P to print
        def on_ctrl_p(event):
            self.save_and_open_for_printing(content, 'kitchen', 32)
            return "break"

        dialog.bind('<Control-p>', on_ctrl_p)
        dialog.bind('<Control-P>', on_ctrl_p)

        # Bind Escape to close
        dialog.bind('<Escape>', lambda e: dialog.destroy())

        self.center_dialog(dialog, 500, 650)

        main_frame = tk.Frame(dialog, bg='white', padx=5, pady=5)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header with instructions
        header_frame = tk.Frame(main_frame, bg='white')
        header_frame.pack(fill=tk.X, pady=(0, 5))

        tk.Label(header_frame, text="🧾 KITCHEN PRINT PREVIEW",
                 font=('Segoe UI', 11, 'bold'),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT)

        tk.Label(header_frame, text="(Ctrl+P to save & open)",
                 font=('Segoe UI', 8), bg='white', fg='#2e86c1').pack(side=tk.RIGHT)

        # Preview text widget with fixed-width font
        preview_frame = tk.Frame(main_frame, bg='white')
        preview_frame.pack(fill=tk.BOTH, expand=True)

        text_widget = tk.Text(preview_frame, font=('Courier New', 10),
                              wrap=tk.NONE, bg='#f8f9fa', fg='black',
                              height=25, width=40)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        v_scroll = ttk.Scrollbar(preview_frame, orient=tk.VERTICAL, command=text_widget.yview)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.config(yscrollcommand=v_scroll.set)

        h_scroll = ttk.Scrollbar(main_frame, orient=tk.HORIZONTAL, command=text_widget.xview)
        h_scroll.pack(fill=tk.X)
        text_widget.config(xscrollcommand=h_scroll.set)

        # Process content for kitchen (simpler format)
        processed_lines = []
        for line in content.split('\n'):
            stripped = line.strip()
            if stripped:
                processed_lines.append(stripped)
            else:
                processed_lines.append('')

        processed_content = '\n'.join(processed_lines)

        text_widget.insert('1.0', processed_content)
        text_widget.config(state=tk.DISABLED)

        # Button frame
        button_frame = tk.Frame(main_frame, bg='white')
        button_frame.pack(fill=tk.X, pady=(5, 0))

        def save_and_open_action():
            self.save_and_open_for_printing(content, 'kitchen', 32)
            dialog.destroy()

        save_btn = tk.Button(button_frame, text="💾 SAVE & OPEN FOR PRINTING (Ctrl+P)",
                             font=('Segoe UI', 10, 'bold'),
                             bg='#27ae60', fg='black', relief='flat',
                             cursor='hand2', command=save_and_open_action,
                             padx=15, pady=5)
        save_btn.pack(side=tk.LEFT, padx=5)

        close_btn = tk.Button(button_frame, text="✕ CLOSE",
                              font=('Segoe UI', 10, 'bold'),
                              bg='#c0392b', fg='black', relief='flat',
                              cursor='hand2', command=dialog.destroy,
                              padx=15, pady=5)
        close_btn.pack(side=tk.RIGHT, padx=5)

    def show_print_preview(self, title, content, printer_type, printer_width=40):
        """Show print preview dialog with Save & Open for Printing functionality."""
        # Check if dialog already exists
        for widget in self.root.winfo_children():
            if isinstance(widget,
                          tk.Toplevel) and widget.title() == f"Print Preview - {printer_type.upper()} - {title}":
                widget.lift()
                widget.focus()
                return

        dialog = tk.Toplevel(self.current_popup if self.current_popup else self.root)
        dialog.title(f"Print Preview - {printer_type.upper()} - {title}")
        dialog.geometry("600x700")
        dialog.transient(self.current_popup if self.current_popup else self.root)
        dialog.grab_set()
        dialog.configure(bg='white')

        # Bind Ctrl+P to print
        def on_ctrl_p(event):
            self.save_and_open_for_printing(content, printer_type, printer_width)
            return "break"

        dialog.bind('<Control-p>', on_ctrl_p)
        dialog.bind('<Control-P>', on_ctrl_p)

        # Bind Escape to close
        dialog.bind('<Escape>', lambda e: dialog.destroy())

        self.center_dialog(dialog, 600, 700)

        main_frame = tk.Frame(dialog, bg='white', padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header with instructions
        header_frame = tk.Frame(main_frame, bg='white')
        header_frame.pack(fill=tk.X, pady=(0, 5))

        tk.Label(header_frame, text=f"🧾 {printer_type.upper()} PRINT PREVIEW - {title}",
                 font=('Segoe UI', 12, 'bold'),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT)

        tk.Label(header_frame, text="(Ctrl+P to save & open)",
                 font=('Segoe UI', 9), bg='white', fg='#2e86c1').pack(side=tk.RIGHT)

        # Preview text widget with monospace font
        preview_frame = tk.Frame(main_frame, bg='white')
        preview_frame.pack(fill=tk.BOTH, expand=True)

        text_widget = tk.Text(preview_frame, font=('Courier New', 11),
                              wrap=tk.NONE, bg='#f8f9fa', fg='black',
                              height=25, width=60)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        v_scroll = ttk.Scrollbar(preview_frame, orient=tk.VERTICAL, command=text_widget.yview)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.config(yscrollcommand=v_scroll.set)

        h_scroll = ttk.Scrollbar(main_frame, orient=tk.HORIZONTAL, command=text_widget.xview)
        h_scroll.pack(fill=tk.X)
        text_widget.config(xscrollcommand=h_scroll.set)

        # Insert content
        text_widget.insert('1.0', content)
        text_widget.config(state=tk.DISABLED)

        # Button frame
        button_frame = tk.Frame(main_frame, bg='white')
        button_frame.pack(fill=tk.X, pady=(10, 0))

        def save_and_open_action():
            self.save_and_open_for_printing(content, printer_type, printer_width)
            dialog.destroy()

        save_btn = tk.Button(button_frame, text="💾 SAVE & OPEN FOR PRINTING (Ctrl+P)",
                             font=('Segoe UI', 11, 'bold'),
                             bg='#27ae60', fg='black', relief='flat',
                             cursor='hand2', command=save_and_open_action,
                             padx=15, pady=8)
        save_btn.pack(side=tk.LEFT, padx=5)

        close_btn = tk.Button(button_frame, text="✕ CLOSE",
                              font=('Segoe UI', 11, 'bold'),
                              bg='#c0392b', fg='black', relief='flat',
                              cursor='hand2', command=dialog.destroy,
                              padx=15, pady=8)
        close_btn.pack(side=tk.RIGHT, padx=5)

    def show_print_image_preview(self, title, content, printer_type):
        """Show print preview as an image that can be printed directly."""
        # Create a temporary image of the content
        img = self.create_print_image(content, printer_type)

        # Create a new window to display the image
        preview_window = tk.Toplevel(self.current_popup if self.current_popup else self.root)
        preview_window.title(f"Print Preview - {title}")
        preview_window.geometry("600x800")
        preview_window.transient(self.current_popup if self.current_popup else self.root)
        preview_window.grab_set()
        preview_window.configure(bg='white')

        # Bind Escape to close
        preview_window.bind('<Escape>', lambda e: preview_window.destroy())

        # Center the window
        self.center_dialog(preview_window, 600, 800)

        # Main frame
        main_frame = tk.Frame(preview_window, bg='white', padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header
        header_frame = tk.Frame(main_frame, bg='white')
        header_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(header_frame, text=f"🧾 {printer_type.upper()} PRINT PREVIEW - {title}",
                 font=('Segoe UI', 12, 'bold'), bg='white', fg='#6a4334').pack(side=tk.LEFT)

        # Image frame with scrollbars
        canvas_frame = tk.Frame(main_frame, bg='white')
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        # Create canvas with scrollbars
        canvas = tk.Canvas(canvas_frame, bg='white', highlightthickness=0)
        v_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
        h_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=canvas.xview)

        canvas.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        # Pack scrollbars and canvas
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Convert PIL Image to PhotoImage
        photo = ImageTk.PhotoImage(img)

        # Create a frame inside canvas to hold the image
        image_frame = tk.Frame(canvas, bg='white')
        canvas.create_window((0, 0), window=image_frame, anchor='nw')

        # Display image
        image_label = tk.Label(image_frame, image=photo, bg='white')
        image_label.image = photo  # Keep a reference
        image_label.pack()

        # Update scroll region
        image_frame.update_idletasks()
        canvas.config(scrollregion=canvas.bbox('all'))

        # Button frame
        button_frame = tk.Frame(main_frame, bg='white')
        button_frame.pack(fill=tk.X, pady=(10, 0))

        def save_and_print():
            # Save to temporary file and open with default image viewer for printing
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            img.save(temp_file.name, dpi=(300, 300), quality=95)
            temp_file.close()

            # Open with default image viewer
            import subprocess
            import platform

            if platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', temp_file.name])
            elif platform.system() == 'Windows':
                os.startfile(temp_file.name)
            else:  # Linux
                subprocess.run(['xdg-open', temp_file.name])

            self.show_info(f"✅ Image saved to {temp_file.name}\nPlease use your image viewer to print.")

        def print_direct():
            # Simulate direct printing
            self.simulate_print_to_printer(printer_type, content, 40)
            self.show_info(f"✅ Print job sent to {printer_type} printer!")
            preview_window.destroy()

        save_btn = tk.Button(button_frame, text="💾 SAVE & OPEN FOR PRINTING",
                             font=('Segoe UI', 11, 'bold'),
                             bg='#27ae60', fg='black', relief='flat',
                             cursor='hand2', command=save_and_print,
                             padx=15, pady=8)
        save_btn.pack(side=tk.LEFT, padx=5)

        print_direct_btn = tk.Button(button_frame, text="🖨️ PRINT DIRECT",
                                     font=('Segoe UI', 11, 'bold'),
                                     bg='#2e86c1', fg='black', relief='flat',
                                     cursor='hand2', command=print_direct,
                                     padx=15, pady=8)
        print_direct_btn.pack(side=tk.LEFT, padx=5)

        close_btn = tk.Button(button_frame, text="✕ CLOSE",
                              font=('Segoe UI', 11, 'bold'),
                              bg='#c0392b', fg='black', relief='flat',
                              cursor='hand2', command=preview_window.destroy,
                              padx=15, pady=8)
        close_btn.pack(side=tk.RIGHT, padx=5)

    def create_print_image(self, content, printer_type, width=500):
        """Create a PIL Image from text content for printing."""
        # Split content into lines
        lines = content.strip().split('\n')

        # Calculate image dimensions
        line_height = 20  # Height per line
        char_width = 10  # Approximate width per character

        img_width = width
        img_height = max(400, len(lines) * line_height + 100)

        # Create image
        img = Image.new('RGB', (img_width, img_height), color='white')
        draw = ImageDraw.Draw(img)

        # Try to load a monospace font for proper alignment
        try:
            # Try different font paths based on OS
            font_paths = [
                'C:/Windows/Fonts/consola.ttf',  # Windows Console font
                'C:/Windows/Fonts/cour.ttf',  # Windows Courier
                '/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf',  # Linux
                '/System/Library/Fonts/Menlo.ttc',  # Mac
                '/System/Library/Fonts/Courier.dfont',  # Mac alternative
            ]

            font = None
            for path in font_paths:
                if os.path.exists(path):
                    font = ImageFont.truetype(path, 14)
                    break

            if font is None:
                font = ImageFont.load_default()
        except:
            font = ImageFont.load_default()

        # Draw each line
        y_position = 30
        for line in lines:
            # Clean the line
            clean_line = line.rstrip()
            if clean_line:
                draw.text((30, y_position), clean_line, fill='black', font=font)
            y_position += line_height

        # Add footer
        footer_text = f"Printed: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        draw.text((30, img_height - 30), footer_text, fill='gray', font=font)

        return img

    def simulate_print_to_printer(self, printer_type, content, printer_width=40):
        """Simulate printing to printer with proper formatting."""
        print(f"\n{'=' * printer_width}")
        print(f"PRINTING TO {printer_type.upper()} PRINTER")
        print(f"{'=' * printer_width}")

        # Clean up the content for printing
        lines = content.split('\n')
        for line in lines:
            # Remove extra indentation
            cleaned_line = line.strip()
            if cleaned_line:
                print(cleaned_line[:printer_width])
            else:
                print()

        print(f"{'=' * printer_width}\n")

    def save_and_open_for_printing(self, content, printer_type, printer_width=40):
        """Save content as image and open for printing."""
        try:
            # Create image from content
            img = self.create_print_image(content, printer_type, width=600)

            # Save to temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False,
                                                    suffix=f'_{printer_type}.png',
                                                    prefix='print_')
            img.save(temp_file.name, dpi=(300, 300), quality=95)
            temp_file.close()

            # Open with default image viewer
            import subprocess
            import platform

            if platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', temp_file.name])
            elif platform.system() == 'Windows':
                os.startfile(temp_file.name)
            else:  # Linux
                subprocess.run(['xdg-open', temp_file.name])

            self.show_info(f"✅ Image saved to:\n{temp_file.name}\n\nPlease use your image viewer to print.")

        except Exception as e:
            self.show_error(f"Error creating print image: {str(e)}")

    def clear_content_area(self):
        """Clear the content area."""
        for widget in self.content_area.winfo_children():
            widget.destroy()

    def logout(self):
        """Logout user."""
        if self.ask_confirmation("Are you sure you want to logout?"):
            self.auth.logout()
            self.main_frame.destroy()
            self.create_login_frame()

    def close_day(self):
        """Close the current day."""
        try:
            if not self.day_manager.check_today_status():
                self.show_warning("Day is already closed")
                return

            report = self.restaurant.get_daily_sales_report()

            if not report:
                self.show_error("Failed to generate sales report. Please try again.")
                return

            day_summary = report.get('day_summary')

            opening_cash = day_summary.get('opening_cash', 0) if day_summary else 0
            expected_cash = report.get('restaurant_cash', 0) + opening_cash
        except Exception as e:
            self.show_error(f"Error preparing close day report:\n{str(e)}")
            print(f"Close day error: {e}")
            import traceback
            traceback.print_exc()
            return

        try:
            summary = f"""
   {'=' * 50}
   TODAY'S CLOSING SUMMARY
   {'=' * 50}
   Date: {date.today().strftime('%d %B, %Y')}

   CASH BALANCE:
   Opening Cash: {' ' * 20} ₹{opening_cash:>10.2f}
   Restaurant Cash Sales: {' ' * 14} ₹{report.get('restaurant_cash', 0):>10.2f}
   {'-' * 50}
   Expected Cash in Drawer: {' ' * 13} ₹{expected_cash:>10.2f}

   SALES SUMMARY:
   Total Bills: {report.get('total_bills', 0)}
   ├─ Restaurant Bills: {report.get('restaurant_bills', 0)}
   └─ Room Service Bills: {report.get('room_bills', 0)}

   RESTAURANT BREAKDOWN:
   Cash: ₹{report.get('restaurant_cash', 0):>10.2f}
   Card: ₹{report.get('restaurant_card', 0):>10.2f}
   UPI:  ₹{report.get('restaurant_upi', 0):>10.2f}
   {'-' * 50}
   RESTAURANT TOTAL: ₹{report.get('restaurant_total', 0):>10.2f}

   ROOM SERVICE TOTAL: ₹{report.get('room_total', 0):>10.2f}
   (to be added to hotel bill)

   COMPLIMENTARY TOTAL: ₹{report.get('complimentary_total', 0):>10.2f}

   {'=' * 50}
   Do you want to close the day?
   """

            if not self.ask_confirmation(summary):
                return

            actual_cash = simpledialog.askfloat("Close Day",
                                                f"""Enter actual cash count:

   Expected Cash: ₹{expected_cash:.2f}
   Room Service Cash (separate): ₹{report.get('room_cash', 0):.2f}

   Actual cash in drawer:""",
                                                parent=self.root, minvalue=0)
        except Exception as e:
            self.show_error(f"Error displaying close day summary:\n{str(e)}")
            print(f"Summary display error: {e}")
            import traceback
            traceback.print_exc()
            return

        if actual_cash is not None:
            try:
                self.day_manager.close_day(actual_cash)

                variance = actual_cash - expected_cash
                variance_status = "OVER" if variance > 0 else "SHORT" if variance < 0 else "BALANCED"

                restaurant_cash = report.get('restaurant_cash', 0)
                room_cash = report.get('room_cash', 0)

                if abs(variance) < 0.01:
                    self.show_info(
                        f"""✅ Day closed successfully!

   Opening Cash: ₹{opening_cash:.2f}
   Restaurant Cash Sales: ₹{restaurant_cash:.2f}
   Expected: ₹{expected_cash:.2f}
   Actual: ₹{actual_cash:.2f}
   Variance: ₹0.00 (BALANCED)

   Room Service Cash to deposit: ₹{room_cash:.2f}""")
                else:
                    self.show_warning(
                        f"""⚠️ Day closed with variance!

   Opening Cash: ₹{opening_cash:.2f}
   Restaurant Cash Sales: ₹{restaurant_cash:.2f}
   Expected: ₹{expected_cash:.2f}
   Actual: ₹{actual_cash:.2f}
   Variance: ₹{variance:.2f} ({variance_status})

   Please record this discrepancy.
   Room Service Cash to deposit: ₹{room_cash:.2f}""")

                self.create_main_menu()

            except Exception as e:
                self.show_error(f"Error closing day:\n{str(e)}")
                print(f"Close day final error: {e}")
                import traceback
                traceback.print_exc()

    def print_new_items_only(self, order_id):
        """Print only items that haven't been printed to kitchen/desk yet - properly aligned."""
        try:
            # Get items that haven't been printed to kitchen
            unprinted_items = self.restaurant.get_unprinted_items(order_id)

            if not unprinted_items:
                self.show_info("No new items to print.")
                return

            order = self.restaurant.get_order_by_id(order_id)

            line_width = 32  # Kitchen width
            desk_width = 40  # Desk width

            # Kitchen slip - ONLY new/unprinted items - properly aligned
            kitchen_content = []
            kitchen_content.append('=' * line_width)
            kitchen_content.append(f"{'KITCHEN ORDER - NEW ITEMS':^{line_width}}")
            kitchen_content.append('=' * line_width)
            kitchen_content.append(f"Order: {order['order_number']}")
            kitchen_content.append(f"Tbl/Rm: {order.get('table_number') or order.get('room_number', 'N/A')}")
            kitchen_content.append(f"Time: {datetime.now().strftime('%H:%M:%S')}")
            kitchen_content.append('-' * line_width)
            kitchen_content.append(f"{'NEW ITEMS ADDED':^{line_width}}")
            kitchen_content.append('-' * line_width)

            for item in unprinted_items:
                name = item['item_name'][:20]
                kitchen_content.append(f"{name:<20} x{item['quantity']:>2}")

            kitchen_content.append('-' * line_width)
            if len(unprinted_items) > 5:
                kitchen_content.append(f"{'Total New Items:':<20} {len(unprinted_items):>3}")
            kitchen_content.append('=' * line_width)

            kitchen_formatted = '\n'.join(kitchen_content)

            # Desk slip - Detailed format with prices - properly aligned
            desk_content = []
            desk_content.append('=' * desk_width)
            desk_content.append(f"{'DESK ORDER - NEW ITEMS':^{desk_width}}")
            desk_content.append('=' * desk_width)
            desk_content.append(f"Order: {order['order_number']}")
            desk_content.append(f"Cust: {order['customer_name'][:20]}")
            desk_content.append(f"Tbl/Rm: {order.get('table_number') or order.get('room_number', 'N/A')}")
            desk_content.append(f"Time: {datetime.now().strftime('%H:%M:%S')}")
            desk_content.append('-' * desk_width)
            desk_content.append(f"{'ITEM':<20} {'QTY':>5} {'AMOUNT':>8}")
            desk_content.append('-' * desk_width)

            subtotal = 0
            for item in unprinted_items:
                name = item['item_name'][:20]
                qty = item['quantity']
                amt = item['total_price']
                desk_content.append(f"{name:<20} {qty:>5}  ₹{amt:>8.2f}")
                subtotal += amt

            tax = sum(i['unit_price'] * i['quantity'] * i['tax_percentage'] / 100 for i in unprinted_items)
            total = subtotal + tax

            desk_content.append('-' * desk_width)
            desk_content.append(f"{'New Items Subtotal:':<30} ₹{subtotal:>8.2f}")
            desk_content.append(f"{'Tax:':<30} ₹{tax:>8.2f}")
            desk_content.append('-' * desk_width)
            desk_content.append(f"{'NEW ITEMS TOTAL:':<30} ₹{total:>8.2f}")
            desk_content.append('=' * desk_width)

            desk_formatted = '\n'.join(desk_content)

            # Send to printer queue - WITH PREVIEW then AUTO-PRINT
            self.restaurant.printer_queue.put({
                'printer': 'kitchen',
                'content': kitchen_formatted
            })
            self.restaurant.printer_queue.put({
                'printer': 'desk',
                'content': desk_formatted
            })

            # Mark items as printed
            for item in unprinted_items:
                self.restaurant.db.execute_query('''
                   UPDATE order_items
                   SET printed_to_kitchen = 1, printed_to_desk = 1
                   WHERE id = ?
               ''', (item['id'],), commit=True)

            # Refresh the order items display to show updated printed status
            self.load_order_items_popup(order_id)

        except Exception as e:
            self.show_error(f"Error printing new items: {str(e)}")

    def create_sales_summary_popup(self, parent):
        """Create comprehensive sales summary popup with detailed bills."""
        # Date range frame
        date_frame = tk.LabelFrame(parent, text="Select Period",
                                   font=('Segoe UI', 11, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        date_frame.pack(fill=tk.X, pady=(0, 20))

        row_frame = tk.Frame(date_frame, bg='white')
        row_frame.pack(fill=tk.X, pady=5)

        tk.Label(row_frame, text="From:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.summary_from_date = tk.Entry(row_frame, font=('Segoe UI', 11), width=12)
        self.summary_from_date.pack(side=tk.LEFT, padx=5)
        self.summary_from_date.insert(0, (date.today() - timedelta(days=30)).isoformat())
        self.summary_from_date.bind('<Return>', lambda e: self.summary_to_date.focus())

        tk.Label(row_frame, text="To:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.summary_to_date = tk.Entry(row_frame, font=('Segoe UI', 11), width=12)
        self.summary_to_date.pack(side=tk.LEFT, padx=5)
        self.summary_to_date.insert(0, date.today().isoformat())
        self.summary_to_date.bind('<Return>', lambda e: self.load_sales_summary())

        generate_btn = tk.Button(row_frame, text="📊 GENERATE SUMMARY",
                                 font=('Segoe UI', 11, 'bold'),
                                 bg='#27ae60', fg='black', relief='flat',
                                 command=self.load_sales_summary, padx=15, pady=2)
        generate_btn.pack(side=tk.LEFT, padx=10)

        export_btn = tk.Button(row_frame, text="📥 EXPORT ALL",
                               font=('Segoe UI', 11, 'bold'),
                               bg='#3498db', fg='black', relief='flat',
                               command=self.export_all_sales_data, padx=15, pady=2)
        export_btn.pack(side=tk.LEFT, padx=5)

        # Create notebook for different views
        notebook = ttk.Notebook(parent)
        notebook.pack(fill=tk.BOTH, expand=True)

        # Overview tab
        overview_frame = ttk.Frame(notebook)
        notebook.add(overview_frame, text="📊 Overview")

        # Payment Methods tab
        payment_frame = ttk.Frame(notebook)
        notebook.add(payment_frame, text="💳 Payment Methods")

        # Daily Breakdown tab
        daily_frame = ttk.Frame(notebook)
        notebook.add(daily_frame, text="📅 Daily Breakdown")

        # Settlement Analysis tab
        settlement_frame = ttk.Frame(notebook)
        notebook.add(settlement_frame, text="💰 Settlement Analysis")

        # Detailed Bills tab - NEW
        bills_frame = ttk.Frame(notebook)
        notebook.add(bills_frame, text="🧾 Detailed Bills")

        # Store frames for later use
        self.summary_overview_frame = overview_frame
        self.summary_payment_frame = payment_frame
        self.summary_daily_frame = daily_frame
        self.summary_settlement_frame = settlement_frame
        self.summary_bills_frame = bills_frame

        # Load initial summary
        self.load_sales_summary()

    def load_sales_summary(self):
        """Load and display sales summary data with detailed bills."""
        try:
            from_date = self.summary_from_date.get()
            to_date = self.summary_to_date.get()

            # Validate dates
            try:
                datetime.strptime(from_date, '%Y-%m-%d')
                datetime.strptime(to_date, '%Y-%m-%d')
            except:
                self.show_error("Invalid date format. Use YYYY-MM-DD")
                return

            # Get all bills for the date range
            all_bills = self.restaurant.get_all_bills(from_date, to_date)

            if not all_bills:
                self.show_info("No bills found for the selected period")
                return

            # Get summary data from existing method
            summary_data = self.restaurant.get_sales_summary(from_date, to_date)

            # Clear all frames
            for frame in [self.summary_overview_frame, self.summary_payment_frame,
                          self.summary_daily_frame, self.summary_settlement_frame,
                          self.summary_bills_frame]:
                for widget in frame.winfo_children():
                    widget.destroy()

            # ========== OVERVIEW TAB ==========
            overview = self.summary_overview_frame

            # Summary cards
            cards_frame = tk.Frame(overview, bg='white')
            cards_frame.pack(fill=tk.X, pady=10)

            summary = summary_data['summary']

            # Create metric cards
            metrics = [
                ("Total Bills", summary['total_bills'], "#3498db"),
                ("Total Sales", f"₹{summary['total_sales']:.2f}", "#27ae60"),
                ("Total Discounts", f"₹{summary['total_discounts']:.2f}", "#e67e22"),
                ("Avg Discount", f"{summary['avg_discount_percentage']:.1f}%", "#f39c12"),
                ("Complimentary", f"₹{summary['total_complimentary']:.2f}", "#c0392b"),
                ("Settled Bills", summary['settled_bills_count'], "#16a085"),
                ("Settled Amount", f"₹{summary['settled_amount_total']:.2f}", "#2e86c1"),
                ("Settlement Discounts", f"₹{summary['settlement_discounts']:.2f}", "#d35400")
            ]

            row, col = 0, 0
            for i, (title, value, color) in enumerate(metrics):
                card = tk.Frame(cards_frame, bg=color, relief=tk.RAISED, bd=1)
                card.grid(row=row, column=col, padx=5, pady=5, ipadx=15, ipady=10, sticky='nsew')

                tk.Label(card, text=title, font=('Segoe UI', 10),
                         bg=color, fg='black').pack()
                tk.Label(card, text=str(value), font=('Segoe UI', 14, 'bold'),
                         bg=color, fg='black').pack()

                col += 1
                if col >= 4:
                    col = 0
                    row += 1

            for i in range(4):
                cards_frame.grid_columnconfigure(i, weight=1)

            # Period info
            period_label = tk.Label(overview,
                                    text=f"Period: {summary_data['period']['start']} to {summary_data['period']['end']}",
                                    font=('Segoe UI', 12, 'bold'),
                                    bg='white', fg='#6a4334')
            period_label.pack(pady=10)

            # Key insights
            insights_frame = tk.LabelFrame(overview, text="Key Insights",
                                           font=('Segoe UI', 12, 'bold'),
                                           bg='white', fg='#6a4334', padx=15, pady=10)
            insights_frame.pack(fill=tk.BOTH, expand=True, pady=10)

            # Calculate insights
            total_sales = summary['total_sales']
            total_discounts = summary['total_discounts']
            settlement_discounts = summary['settlement_discounts']
            settled_amount = summary['settled_amount_total']

            if total_sales > 0:
                discount_rate = (total_discounts / total_sales) * 100
                settlement_rate = (settlement_discounts / total_sales) * 100 if total_sales > 0 else 0
            else:
                discount_rate = 0
                settlement_rate = 0

            insights_text = f"""
       • Total Revenue: ₹{total_sales:.2f}
       • Total Discounts Given: ₹{total_discounts:.2f} ({discount_rate:.1f}% of sales)
       • Discounts from Settlements: ₹{settlement_discounts:.2f} ({settlement_rate:.1f}% of sales)
       • Settlements Account for: {summary['settled_bills_count']} bills (₹{settled_amount:.2f})
       • Average Discount per Settled Bill: ₹{settlement_discounts / max(1, summary['settled_bills_count']):.2f}
           """

            tk.Label(insights_frame, text=insights_text, font=('Segoe UI', 11),
                     bg='white', fg='#2e86c1', justify=tk.LEFT).pack(anchor='w')

            # ========== PAYMENT METHODS TAB ==========
            payment = self.summary_payment_frame

            # Treeview for payment breakdown
            tree_frame = tk.Frame(payment, bg='white')
            tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            tree_container = tk.Frame(tree_frame, bg='white')
            tree_container.pack(fill=tk.BOTH, expand=True)

            v_scroll = ttk.Scrollbar(tree_container)
            v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

            columns = ('Payment Method', 'Bills Count', 'Total Amount', 'Discounts', 'Avg per Bill')
            payment_tree = ttk.Treeview(tree_container, columns=columns,
                                        yscrollcommand=v_scroll.set, height=8)
            v_scroll.config(command=payment_tree.yview)

            for col in columns:
                payment_tree.heading(col, text=col, anchor=tk.W)
                payment_tree.column(col, width=120)

            payment_tree.pack(fill=tk.BOTH, expand=True)

            for method in summary_data['payment_breakdown']:
                method_name = method['payment_method'].upper() if method['payment_method'] else 'UNKNOWN'
                count = method['bill_count']
                amount = method['total_amount']
                discounts = method['discounts']
                avg = amount / count if count > 0 else 0

                payment_tree.insert('', tk.END, values=(
                    method_name, count, f"₹{amount:.2f}", f"₹{discounts:.2f}", f"₹{avg:.2f}"
                ))

            # Summary stats
            stats_frame = tk.Frame(payment, bg='white')
            stats_frame.pack(fill=tk.X, pady=10)

            total_bills = summary['total_bills']
            total_sales = summary['total_sales']

            tk.Label(stats_frame, text=f"Total Bills: {total_bills}", font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=10)
            tk.Label(stats_frame, text=f"Total Sales: ₹{total_sales:.2f}", font=('Segoe UI', 11, 'bold'),
                     bg='white', fg='#27ae60').pack(side=tk.LEFT, padx=10)

            # ========== DAILY BREAKDOWN TAB ==========
            daily = self.summary_daily_frame

            # Treeview for daily breakdown
            daily_tree_frame = tk.Frame(daily, bg='white')
            daily_tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            daily_container = tk.Frame(daily_tree_frame, bg='white')
            daily_container.pack(fill=tk.BOTH, expand=True)

            v_scroll2 = ttk.Scrollbar(daily_container)
            v_scroll2.pack(side=tk.RIGHT, fill=tk.Y)

            h_scroll2 = ttk.Scrollbar(daily_container, orient=tk.HORIZONTAL)
            h_scroll2.pack(side=tk.BOTTOM, fill=tk.X)

            daily_columns = ('Date', 'Bills', 'Sales', 'Complimentary', 'Discounts', 'Settled', 'Settled Amount')
            daily_tree = ttk.Treeview(daily_container, columns=daily_columns,
                                      yscrollcommand=v_scroll2.set,
                                      xscrollcommand=h_scroll2.set,
                                      height=12)
            v_scroll2.config(command=daily_tree.yview)
            h_scroll2.config(command=daily_tree.xview)

            for col in daily_columns:
                daily_tree.heading(col, text=col, anchor=tk.W)
                daily_tree.column(col, width=100)

            daily_tree.column('Date', width=120)
            daily_tree.column('Sales', width=120)
            daily_tree.column('Settled Amount', width=120)

            daily_tree.pack(fill=tk.BOTH, expand=True)

            for day in summary_data['daily_breakdown']:
                daily_tree.insert('', tk.END, values=(
                    day['sale_date'],
                    day['bills_count'],
                    f"₹{day['total_sales']:.2f}",
                    f"₹{day['complimentary']:.2f}",
                    f"₹{day['discounts']:.2f}",
                    day['settled_count'],
                    f"₹{day['settled_amount']:.2f}"
                ))

            # ========== SETTLEMENT ANALYSIS TAB ==========
            settlement = self.summary_settlement_frame

            # Summary stats for settlements
            settle_stats = tk.LabelFrame(settlement, text="Settlement Summary",
                                         font=('Segoe UI', 12, 'bold'),
                                         bg='white', fg='#6a4334', padx=15, pady=10)
            settle_stats.pack(fill=tk.X, pady=10)

            total_settled = summary['settled_bills_count']
            total_settled_amount = summary['settled_amount_total']
            total_settlement_discounts = summary['settlement_discounts']

            if total_settled > 0:
                avg_settlement = total_settled_amount / total_settled
                avg_discount = total_settlement_discounts / total_settled
            else:
                avg_settlement = 0
                avg_discount = 0

            stats_text = f"""
       Total Settled Bills: {total_settled}
       Total Settled Amount: ₹{total_settled_amount:.2f}
       Total Discounts from Settlements: ₹{total_settlement_discounts:.2f}
       Average Settlement Amount: ₹{avg_settlement:.2f}
       Average Discount per Settlement: ₹{avg_discount:.2f}
           """

            tk.Label(settle_stats, text=stats_text, font=('Segoe UI', 11),
                     bg='white', fg='#2e86c1', justify=tk.LEFT).pack(anchor='w')

            # Treeview for settlement trends
            trend_frame = tk.LabelFrame(settlement, text="Settlement Trends",
                                        font=('Segoe UI', 12, 'bold'),
                                        bg='white', fg='#6a4334', padx=15, pady=10)
            trend_frame.pack(fill=tk.BOTH, expand=True, pady=10)

            trend_container = tk.Frame(trend_frame, bg='white')
            trend_container.pack(fill=tk.BOTH, expand=True)

            v_scroll3 = ttk.Scrollbar(trend_container)
            v_scroll3.pack(side=tk.RIGHT, fill=tk.Y)

            trend_columns = ('Date', 'Settlements', 'Amount Settled', 'Discounts Given')
            trend_tree = ttk.Treeview(trend_container, columns=trend_columns,
                                      yscrollcommand=v_scroll3.set, height=8)
            v_scroll3.config(command=trend_tree.yview)

            for col in trend_columns:
                trend_tree.heading(col, text=col, anchor=tk.W)
                trend_tree.column(col, width=120)

            trend_tree.column('Date', width=120)
            trend_tree.column('Amount Settled', width=150)

            trend_tree.pack(fill=tk.BOTH, expand=True)

            for trend in summary_data['settlement_trends']:
                trend_tree.insert('', tk.END, values=(
                    trend['settlement_date'],
                    trend['settlements_count'],
                    f"₹{trend['settled_amount']:.2f}",
                    f"₹{trend['discounts_given']:.2f}"
                ))

            # ========== DETAILED BILLS TAB ==========
            bills_tab = self.summary_bills_frame

            # Filter frame for bills tab
            bills_filter_frame = tk.Frame(bills_tab, bg='white')
            bills_filter_frame.pack(fill=tk.X, pady=(0, 10))

            tk.Label(bills_filter_frame, text="Filter by Bill Number:", font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)

            self.bills_filter_entry = tk.Entry(bills_filter_frame, font=('Segoe UI', 11), width=20)
            self.bills_filter_entry.pack(side=tk.LEFT, padx=5)
            self.bills_filter_entry.bind('<Return>', lambda e: self.filter_bills_in_summary(all_bills))

            filter_btn = tk.Button(bills_filter_frame, text="🔍 FILTER",
                                   font=('Segoe UI', 10, 'bold'),
                                   bg='#2e86c1', fg='black', relief='flat',
                                   command=lambda: self.filter_bills_in_summary(all_bills), padx=15, pady=2)
            filter_btn.pack(side=tk.LEFT, padx=5)

            clear_btn = tk.Button(bills_filter_frame, text="🔄 CLEAR",
                                  font=('Segoe UI', 10, 'bold'),
                                  bg='#95a5a6', fg='black', relief='flat',
                                  command=lambda: self.load_all_bills_in_summary(all_bills), padx=15, pady=2)
            clear_btn.pack(side=tk.LEFT, padx=5)

            # Treeview for detailed bills
            bills_tree_frame = tk.Frame(bills_tab, bg='white')
            bills_tree_frame.pack(fill=tk.BOTH, expand=True)

            bills_container = tk.Frame(bills_tree_frame, bg='white')
            bills_container.pack(fill=tk.BOTH, expand=True)

            v_scroll4 = ttk.Scrollbar(bills_container)
            v_scroll4.pack(side=tk.RIGHT, fill=tk.Y)

            h_scroll4 = ttk.Scrollbar(bills_container, orient=tk.HORIZONTAL)
            h_scroll4.pack(side=tk.BOTTOM, fill=tk.X)

            bill_columns = ('Bill #', 'Date', 'Customer', 'Table/Room', 'Type', 'Subtotal', 'Tax', 'Discount', 'Total',
                            'Method', 'Status')
            self.bills_summary_tree = ttk.Treeview(bills_container, columns=bill_columns,
                                                   yscrollcommand=v_scroll4.set,
                                                   xscrollcommand=h_scroll4.set,
                                                   height=15)

            v_scroll4.config(command=self.bills_summary_tree.yview)
            h_scroll4.config(command=self.bills_summary_tree.xview)

            for col in bill_columns:
                self.bills_summary_tree.heading(col, text=col, anchor=tk.W)
                self.bills_summary_tree.column(col, width=100)

            self.bills_summary_tree.column('Bill #', width=180)
            self.bills_summary_tree.column('Customer', width=150)
            self.bills_summary_tree.column('Date', width=120)
            self.bills_summary_tree.column('Total', width=100)

            self.bills_summary_tree.pack(fill=tk.BOTH, expand=True)

            # Bind double-click to view bill
            self.bills_summary_tree.bind('<Double-Button-1>', lambda e: self.view_bill_from_summary())

            # Action buttons for bills tab
            bills_action_frame = tk.Frame(bills_tab, bg='white')
            bills_action_frame.pack(fill=tk.X, pady=10)

            view_bill_btn = tk.Button(bills_action_frame, text="👁️ VIEW SELECTED BILL",
                                      font=('Segoe UI', 11, 'bold'),
                                      bg='#3498db', fg='black', relief='flat',
                                      command=self.view_bill_from_summary, padx=15, pady=5)
            view_bill_btn.pack(side=tk.LEFT, padx=5)

            print_bill_btn = tk.Button(bills_action_frame, text="🖨️ PRINT SELECTED BILL",
                                       font=('Segoe UI', 11, 'bold'),
                                       bg='#27ae60', fg='black', relief='flat',
                                       command=self.print_bill_from_summary, padx=15, pady=5)
            print_bill_btn.pack(side=tk.LEFT, padx=5)

            export_csv_btn = tk.Button(bills_action_frame, text="📥 EXPORT TO CSV",
                                       font=('Segoe UI', 11, 'bold'),
                                       bg='#f39c12', fg='black', relief='flat',
                                       command=lambda: self.export_bills_to_csv(all_bills), padx=15, pady=5)
            export_csv_btn.pack(side=tk.LEFT, padx=5)

            # Load all bills
            self.load_all_bills_in_summary(all_bills)

            # Grand total label at bottom
            grand_total_frame = tk.Frame(bills_tab, bg='white')
            grand_total_frame.pack(fill=tk.X, pady=5)

            grand_total = sum(bill['total_amount'] for bill in all_bills)
            tk.Label(grand_total_frame, text=f"GRAND TOTAL: ₹{grand_total:.2f}",
                     font=('Segoe UI', 14, 'bold'), bg='white', fg='#c0392b').pack(side=tk.RIGHT)

        except Exception as e:
            self.show_error(f"Error loading sales summary: {str(e)}")
            import traceback
            traceback.print_exc()

    def load_all_bills_in_summary(self, bills):
        """Load all bills into the summary tree."""
        if not hasattr(self, 'bills_summary_tree'):
            return

        # Clear existing
        for item in self.bills_summary_tree.get_children():
            self.bills_summary_tree.delete(item)

        # Sort bills by date (newest first)
        sorted_bills = sorted(bills, key=lambda x: x.get('bill_date', ''), reverse=True)

        for bill in sorted_bills:
            # Format date
            bill_date = bill['bill_date']
            if len(bill_date) > 10:
                bill_date = bill_date[:10]

            # Determine status
            if bill.get('settled_at'):
                status = 'SETTLED'
                tags = ('settled',)
            elif bill['is_complimentary']:
                status = 'COMP'
                tags = ('comp',)
            else:
                status = 'PAID'
                tags = ('paid',)

            # Format customer name with phone if available
            customer_display = bill['customer_name']
            if bill.get('customer_phone'):
                customer_display += f" ({bill['customer_phone']})"

            # Truncate if too long
            if len(customer_display) > 25:
                customer_display = customer_display[:22] + '...'

            values = (
                bill['bill_number'],
                bill_date,
                customer_display,
                bill.get('table_number') or bill.get('room_number', ''),
                'COMP' if bill['is_complimentary'] else 'PAID',
                f"₹{bill['subtotal']:.2f}",
                f"₹{bill['tax_amount']:.2f}",
                f"₹{bill.get('discount_amount', 0):.2f}",
                f"₹{bill['total_amount']:.2f}",
                bill['payment_method'].upper(),
                status
            )
            self.bills_summary_tree.insert('', tk.END, values=values, tags=tags)

        # Configure tags
        self.bills_summary_tree.tag_configure('settled', background='#d5f5e3')
        self.bills_summary_tree.tag_configure('comp', background='#fcf3cf')
        self.bills_summary_tree.tag_configure('paid', background='#ffffff')

    def filter_bills_in_summary(self, all_bills):
        """Filter bills by bill number in summary."""
        filter_text = self.bills_filter_entry.get().strip().lower()
        if not filter_text:
            self.load_all_bills_in_summary(all_bills)
            return

        filtered_bills = [bill for bill in all_bills
                          if filter_text in bill['bill_number'].lower()
                          or filter_text in bill['customer_name'].lower()]

        self.load_all_bills_in_summary(filtered_bills)

    def view_bill_from_summary(self):
        """View selected bill from summary."""
        selection = self.bills_summary_tree.selection()
        if not selection:
            self.show_warning("Please select a bill to view")
            return

        bill_number = self.bills_summary_tree.item(selection[0])['values'][0]
        self.show_bill_preview_popup(bill_number)

    def print_bill_from_summary(self):
        """Print selected bill from summary."""
        selection = self.bills_summary_tree.selection()
        if not selection:
            self.show_warning("Please select a bill to print")
            return

        bill_number = self.bills_summary_tree.item(selection[0])['values'][0]
        self.show_bill_preview_popup(bill_number)

    def export_bills_to_csv(self, bills):
        """Export all bills in summary to CSV file."""
        if not bills:
            self.show_warning("No bills to export")
            return

        try:
            from_date = self.summary_from_date.get()
            to_date = self.summary_to_date.get()
            filename = f"sales_bills_{from_date}_to_{to_date}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['Bill Number', 'Date', 'Customer Name', 'Customer Phone', 'Table/Room', 'Type',
                              'Subtotal (₹)', 'Tax (₹)', 'Discount (₹)', 'Total (₹)',
                              'Payment Method', 'Status', 'Settled At']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                total_amount = 0

                for bill in bills:
                    # Format date
                    bill_date = bill['bill_date']
                    if len(bill_date) > 10:
                        bill_date = bill_date[:10]

                    # Determine status
                    if bill.get('settled_at'):
                        status = 'SETTLED'
                        settled_at = bill['settled_at'][:10] if bill['settled_at'] else ''
                    elif bill['is_complimentary']:
                        status = 'COMPLIMENTARY'
                        settled_at = ''
                    else:
                        status = 'PAID'
                        settled_at = ''

                    writer.writerow({
                        'Bill Number': bill['bill_number'],
                        'Date': bill_date,
                        'Customer Name': bill['customer_name'],
                        'Customer Phone': bill.get('customer_phone', ''),
                        'Table/Room': bill.get('table_number') or bill.get('room_number', ''),
                        'Type': 'COMP' if bill['is_complimentary'] else 'PAID',
                        'Subtotal (₹)': f"{bill['subtotal']:.2f}",
                        'Tax (₹)': f"{bill['tax_amount']:.2f}",
                        'Discount (₹)': f"{bill.get('discount_amount', 0):.2f}",
                        'Total (₹)': f"{bill['total_amount']:.2f}",
                        'Payment Method': bill['payment_method'].upper() if bill['payment_method'] else '',
                        'Status': status,
                        'Settled At': settled_at
                    })
                    total_amount += bill['total_amount']

                # Add summary row
                writer.writerow({})
                writer.writerow({
                    'Bill Number': 'TOTAL',
                    'Total (₹)': f"{total_amount:.2f}"
                })

            self.show_info(f"✅ Bills exported to:\n{filename}")

        except Exception as e:
            self.show_error(f"Error exporting bills: {str(e)}")

    def export_all_sales_data(self):
        """Export all sales data including summary and bills."""
        try:
            from_date = self.summary_from_date.get()
            to_date = self.summary_to_date.get()

            # Get all data
            all_bills = self.restaurant.get_all_bills(from_date, to_date)
            summary_data = self.restaurant.get_sales_summary(from_date, to_date)

            if not all_bills:
                self.show_warning("No data to export")
                return

            filename = f"complete_sales_report_{from_date}_to_{to_date}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)

                # Header
                writer.writerow(['THE EVAANI HOTEL - COMPLETE SALES REPORT'])
                writer.writerow([f"Period: {from_date} to {to_date}"])
                writer.writerow([f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"])
                writer.writerow([])

                # Summary Section
                writer.writerow(['=' * 50])
                writer.writerow(['SALES SUMMARY'])
                writer.writerow(['=' * 50])

                summary = summary_data['summary']
                writer.writerow(['Total Bills:', summary['total_bills']])
                writer.writerow(['Total Sales (₹):', f"{summary['total_sales']:.2f}"])
                writer.writerow(['Total Discounts (₹):', f"{summary['total_discounts']:.2f}"])
                writer.writerow(['Total Complimentary (₹):', f"{summary['total_complimentary']:.2f}"])
                writer.writerow(['Avg Discount %:', f"{summary['avg_discount_percentage']:.1f}%"])
                writer.writerow(['Settled Bills:', summary['settled_bills_count']])
                writer.writerow(['Settled Amount (₹):', f"{summary['settled_amount_total']:.2f}"])
                writer.writerow(['Settlement Discounts (₹):', f"{summary['settlement_discounts']:.2f}"])
                writer.writerow([])

                # Payment Breakdown
                writer.writerow(['PAYMENT BREAKDOWN'])
                writer.writerow(['Payment Method', 'Bills', 'Amount (₹)', 'Discounts (₹)'])
                for method in summary_data['payment_breakdown']:
                    writer.writerow([
                        method['payment_method'].upper() if method['payment_method'] else 'UNKNOWN',
                        method['bill_count'],
                        f"{method['total_amount']:.2f}",
                        f"{method['discounts']:.2f}"
                    ])
                writer.writerow([])

                # Daily Breakdown
                writer.writerow(['DAILY BREAKDOWN'])
                writer.writerow(['Date', 'Bills', 'Sales (₹)', 'Complimentary (₹)', 'Discounts (₹)', 'Settled',
                                 'Settled Amount (₹)'])
                for day in summary_data['daily_breakdown']:
                    writer.writerow([
                        day['sale_date'],
                        day['bills_count'],
                        f"{day['total_sales']:.2f}",
                        f"{day['complimentary']:.2f}",
                        f"{day['discounts']:.2f}",
                        day['settled_count'],
                        f"{day['settled_amount']:.2f}"
                    ])
                writer.writerow([])

                # Detailed Bills
                writer.writerow(['DETAILED BILLS'])
                writer.writerow(['Bill #', 'Date', 'Customer', 'Table/Room', 'Type',
                                 'Subtotal', 'Tax', 'Discount', 'Total', 'Method', 'Status'])

                total_amount = 0
                for bill in all_bills:
                    bill_date = bill['bill_date']
                    if len(bill_date) > 10:
                        bill_date = bill_date[:10]

                    if bill.get('settled_at'):
                        status = 'SETTLED'
                    elif bill['is_complimentary']:
                        status = 'COMP'
                    else:
                        status = 'PAID'

                    writer.writerow([
                        bill['bill_number'],
                        bill_date,
                        bill['customer_name'],
                        bill.get('table_number') or bill.get('room_number', ''),
                        'COMP' if bill['is_complimentary'] else 'PAID',
                        f"{bill['subtotal']:.2f}",
                        f"{bill['tax_amount']:.2f}",
                        f"{bill.get('discount_amount', 0):.2f}",
                        f"{bill['total_amount']:.2f}",
                        bill['payment_method'].upper() if bill['payment_method'] else '',
                        status
                    ])
                    total_amount += bill['total_amount']

                writer.writerow([])
                writer.writerow(['GRAND TOTAL:', f"{total_amount:.2f}"])

            self.show_info(f"✅ Complete sales report exported to:\n{filename}")

        except Exception as e:
            self.show_error(f"Error exporting sales data: {str(e)}")

    def create_sales_summary_popup(self, parent):
        """Create comprehensive sales summary popup with detailed bills."""
        # Date range frame
        date_frame = tk.LabelFrame(parent, text="Select Period",
                                   font=('Segoe UI', 11, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        date_frame.pack(fill=tk.X, pady=(0, 20))

        row_frame = tk.Frame(date_frame, bg='white')
        row_frame.pack(fill=tk.X, pady=5)

        tk.Label(row_frame, text="From:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.summary_from_date = tk.Entry(row_frame, font=('Segoe UI', 11), width=12)
        self.summary_from_date.pack(side=tk.LEFT, padx=5)
        self.summary_from_date.insert(0, (date.today() - timedelta(days=30)).isoformat())
        self.summary_from_date.bind('<Return>', lambda e: self.summary_to_date.focus())

        tk.Label(row_frame, text="To:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.summary_to_date = tk.Entry(row_frame, font=('Segoe UI', 11), width=12)
        self.summary_to_date.pack(side=tk.LEFT, padx=5)
        self.summary_to_date.insert(0, date.today().isoformat())
        self.summary_to_date.bind('<Return>', lambda e: self.load_sales_summary())

        generate_btn = tk.Button(row_frame, text="📊 GENERATE SUMMARY",
                                 font=('Segoe UI', 11, 'bold'),
                                 bg='#27ae60', fg='black', relief='flat',
                                 command=self.load_sales_summary, padx=15, pady=2)
        generate_btn.pack(side=tk.LEFT, padx=10)

        export_btn = tk.Button(row_frame, text="📥 EXPORT ALL",
                               font=('Segoe UI', 11, 'bold'),
                               bg='#3498db', fg='black', relief='flat',
                               command=self.export_all_sales_data, padx=15, pady=2)
        export_btn.pack(side=tk.LEFT, padx=5)

        # Create notebook for different views
        notebook = ttk.Notebook(parent)
        notebook.pack(fill=tk.BOTH, expand=True)

        # Overview tab
        overview_frame = ttk.Frame(notebook)
        notebook.add(overview_frame, text="📊 Overview")

        # Payment Methods tab
        payment_frame = ttk.Frame(notebook)
        notebook.add(payment_frame, text="💳 Payment Methods")

        # Daily Breakdown tab
        daily_frame = ttk.Frame(notebook)
        notebook.add(daily_frame, text="📅 Daily Breakdown")

        # Settlement Analysis tab
        settlement_frame = ttk.Frame(notebook)
        notebook.add(settlement_frame, text="💰 Settlement Analysis")

        # Detailed Bills tab - NEW
        bills_frame = ttk.Frame(notebook)
        notebook.add(bills_frame, text="🧾 Detailed Bills")

        # Store frames for later use
        self.summary_overview_frame = overview_frame
        self.summary_payment_frame = payment_frame
        self.summary_daily_frame = daily_frame
        self.summary_settlement_frame = settlement_frame
        self.summary_bills_frame = bills_frame

        # Load initial summary
        self.load_sales_summary()

    def load_sales_summary(self):
        """Load and display sales summary data with detailed bills."""
        try:
            from_date = self.summary_from_date.get()
            to_date = self.summary_to_date.get()

            # Validate dates
            try:
                datetime.strptime(from_date, '%Y-%m-%d')
                datetime.strptime(to_date, '%Y-%m-%d')
            except:
                self.show_error("Invalid date format. Use YYYY-MM-DD")
                return

            # Get all bills for the date range
            all_bills = self.restaurant.get_all_bills(from_date, to_date)

            if not all_bills:
                self.show_info("No bills found for the selected period")
                return

            # Get summary data from existing method
            summary_data = self.restaurant.get_sales_summary(from_date, to_date)

            # Clear all frames
            for frame in [self.summary_overview_frame, self.summary_payment_frame,
                          self.summary_daily_frame, self.summary_settlement_frame,
                          self.summary_bills_frame]:
                for widget in frame.winfo_children():
                    widget.destroy()

            # ========== OVERVIEW TAB ==========
            overview = self.summary_overview_frame

            # Summary cards
            cards_frame = tk.Frame(overview, bg='white')
            cards_frame.pack(fill=tk.X, pady=10)

            summary = summary_data['summary']

            # Create metric cards
            metrics = [
                ("Total Bills", summary['total_bills'], "#3498db"),
                ("Total Sales", f"₹{summary['total_sales']:.2f}", "#27ae60"),
                ("Total Discounts", f"₹{summary['total_discounts']:.2f}", "#e67e22"),
                ("Avg Discount", f"{summary['avg_discount_percentage']:.1f}%", "#f39c12"),
                ("Complimentary", f"₹{summary['total_complimentary']:.2f}", "#c0392b"),
                ("Settled Bills", summary['settled_bills_count'], "#16a085"),
                ("Settled Amount", f"₹{summary['settled_amount_total']:.2f}", "#2e86c1"),
                ("Settlement Discounts", f"₹{summary['settlement_discounts']:.2f}", "#d35400")
            ]

            row, col = 0, 0
            for i, (title, value, color) in enumerate(metrics):
                card = tk.Frame(cards_frame, bg=color, relief=tk.RAISED, bd=1)
                card.grid(row=row, column=col, padx=5, pady=5, ipadx=15, ipady=10, sticky='nsew')

                tk.Label(card, text=title, font=('Segoe UI', 10),
                         bg=color, fg='black').pack()
                tk.Label(card, text=str(value), font=('Segoe UI', 14, 'bold'),
                         bg=color, fg='black').pack()

                col += 1
                if col >= 4:
                    col = 0
                    row += 1

            for i in range(4):
                cards_frame.grid_columnconfigure(i, weight=1)

            # Period info
            period_label = tk.Label(overview,
                                    text=f"Period: {summary_data['period']['start']} to {summary_data['period']['end']}",
                                    font=('Segoe UI', 12, 'bold'),
                                    bg='white', fg='#6a4334')
            period_label.pack(pady=10)

            # Key insights
            insights_frame = tk.LabelFrame(overview, text="Key Insights",
                                           font=('Segoe UI', 12, 'bold'),
                                           bg='white', fg='#6a4334', padx=15, pady=10)
            insights_frame.pack(fill=tk.BOTH, expand=True, pady=10)

            # Calculate insights
            total_sales = summary['total_sales']
            total_discounts = summary['total_discounts']
            settlement_discounts = summary['settlement_discounts']
            settled_amount = summary['settled_amount_total']

            if total_sales > 0:
                discount_rate = (total_discounts / total_sales) * 100
                settlement_rate = (settlement_discounts / total_sales) * 100 if total_sales > 0 else 0
            else:
                discount_rate = 0
                settlement_rate = 0

            insights_text = f"""
       • Total Revenue: ₹{total_sales:.2f}
       • Total Discounts Given: ₹{total_discounts:.2f} ({discount_rate:.1f}% of sales)
       • Discounts from Settlements: ₹{settlement_discounts:.2f} ({settlement_rate:.1f}% of sales)
       • Settlements Account for: {summary['settled_bills_count']} bills (₹{settled_amount:.2f})
       • Average Discount per Settled Bill: ₹{settlement_discounts / max(1, summary['settled_bills_count']):.2f}
           """

            tk.Label(insights_frame, text=insights_text, font=('Segoe UI', 11),
                     bg='white', fg='#2e86c1', justify=tk.LEFT).pack(anchor='w')

            # ========== PAYMENT METHODS TAB ==========
            payment = self.summary_payment_frame

            # Treeview for payment breakdown
            tree_frame = tk.Frame(payment, bg='white')
            tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            tree_container = tk.Frame(tree_frame, bg='white')
            tree_container.pack(fill=tk.BOTH, expand=True)

            v_scroll = ttk.Scrollbar(tree_container)
            v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

            columns = ('Payment Method', 'Bills Count', 'Total Amount', 'Discounts', 'Avg per Bill')
            payment_tree = ttk.Treeview(tree_container, columns=columns,
                                        yscrollcommand=v_scroll.set, height=8)
            v_scroll.config(command=payment_tree.yview)

            for col in columns:
                payment_tree.heading(col, text=col, anchor=tk.W)
                payment_tree.column(col, width=120)

            payment_tree.pack(fill=tk.BOTH, expand=True)

            for method in summary_data['payment_breakdown']:
                method_name = method['payment_method'].upper() if method['payment_method'] else 'UNKNOWN'
                count = method['bill_count']
                amount = method['total_amount']
                discounts = method['discounts']
                avg = amount / count if count > 0 else 0

                payment_tree.insert('', tk.END, values=(
                    method_name, count, f"₹{amount:.2f}", f"₹{discounts:.2f}", f"₹{avg:.2f}"
                ))

            # Summary stats
            stats_frame = tk.Frame(payment, bg='white')
            stats_frame.pack(fill=tk.X, pady=10)

            total_bills = summary['total_bills']
            total_sales = summary['total_sales']

            tk.Label(stats_frame, text=f"Total Bills: {total_bills}", font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=10)
            tk.Label(stats_frame, text=f"Total Sales: ₹{total_sales:.2f}", font=('Segoe UI', 11, 'bold'),
                     bg='white', fg='#27ae60').pack(side=tk.LEFT, padx=10)

            # ========== DAILY BREAKDOWN TAB ==========
            daily = self.summary_daily_frame

            # Treeview for daily breakdown
            daily_tree_frame = tk.Frame(daily, bg='white')
            daily_tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            daily_container = tk.Frame(daily_tree_frame, bg='white')
            daily_container.pack(fill=tk.BOTH, expand=True)

            v_scroll2 = ttk.Scrollbar(daily_container)
            v_scroll2.pack(side=tk.RIGHT, fill=tk.Y)

            h_scroll2 = ttk.Scrollbar(daily_container, orient=tk.HORIZONTAL)
            h_scroll2.pack(side=tk.BOTTOM, fill=tk.X)

            daily_columns = ('Date', 'Bills', 'Sales', 'Complimentary', 'Discounts', 'Settled', 'Settled Amount')
            daily_tree = ttk.Treeview(daily_container, columns=daily_columns,
                                      yscrollcommand=v_scroll2.set,
                                      xscrollcommand=h_scroll2.set,
                                      height=12)
            v_scroll2.config(command=daily_tree.yview)
            h_scroll2.config(command=daily_tree.xview)

            for col in daily_columns:
                daily_tree.heading(col, text=col, anchor=tk.W)
                daily_tree.column(col, width=100)

            daily_tree.column('Date', width=120)
            daily_tree.column('Sales', width=120)
            daily_tree.column('Settled Amount', width=120)

            daily_tree.pack(fill=tk.BOTH, expand=True)

            for day in summary_data['daily_breakdown']:
                daily_tree.insert('', tk.END, values=(
                    day['sale_date'],
                    day['bills_count'],
                    f"₹{day['total_sales']:.2f}",
                    f"₹{day['complimentary']:.2f}",
                    f"₹{day['discounts']:.2f}",
                    day['settled_count'],
                    f"₹{day['settled_amount']:.2f}"
                ))

            # ========== SETTLEMENT ANALYSIS TAB ==========
            settlement = self.summary_settlement_frame

            # Summary stats for settlements
            settle_stats = tk.LabelFrame(settlement, text="Settlement Summary",
                                         font=('Segoe UI', 12, 'bold'),
                                         bg='white', fg='#6a4334', padx=15, pady=10)
            settle_stats.pack(fill=tk.X, pady=10)

            total_settled = summary['settled_bills_count']
            total_settled_amount = summary['settled_amount_total']
            total_settlement_discounts = summary['settlement_discounts']

            if total_settled > 0:
                avg_settlement = total_settled_amount / total_settled
                avg_discount = total_settlement_discounts / total_settled
            else:
                avg_settlement = 0
                avg_discount = 0

            stats_text = f"""
       Total Settled Bills: {total_settled}
       Total Settled Amount: ₹{total_settled_amount:.2f}
       Total Discounts from Settlements: ₹{total_settlement_discounts:.2f}
       Average Settlement Amount: ₹{avg_settlement:.2f}
       Average Discount per Settlement: ₹{avg_discount:.2f}
           """

            tk.Label(settle_stats, text=stats_text, font=('Segoe UI', 11),
                     bg='white', fg='#2e86c1', justify=tk.LEFT).pack(anchor='w')

            # Treeview for settlement trends
            trend_frame = tk.LabelFrame(settlement, text="Settlement Trends",
                                        font=('Segoe UI', 12, 'bold'),
                                        bg='white', fg='#6a4334', padx=15, pady=10)
            trend_frame.pack(fill=tk.BOTH, expand=True, pady=10)

            trend_container = tk.Frame(trend_frame, bg='white')
            trend_container.pack(fill=tk.BOTH, expand=True)

            v_scroll3 = ttk.Scrollbar(trend_container)
            v_scroll3.pack(side=tk.RIGHT, fill=tk.Y)

            trend_columns = ('Date', 'Settlements', 'Amount Settled', 'Discounts Given')
            trend_tree = ttk.Treeview(trend_container, columns=trend_columns,
                                      yscrollcommand=v_scroll3.set, height=8)
            v_scroll3.config(command=trend_tree.yview)

            for col in trend_columns:
                trend_tree.heading(col, text=col, anchor=tk.W)
                trend_tree.column(col, width=120)

            trend_tree.column('Date', width=120)
            trend_tree.column('Amount Settled', width=150)

            trend_tree.pack(fill=tk.BOTH, expand=True)

            for trend in summary_data['settlement_trends']:
                trend_tree.insert('', tk.END, values=(
                    trend['settlement_date'],
                    trend['settlements_count'],
                    f"₹{trend['settled_amount']:.2f}",
                    f"₹{trend['discounts_given']:.2f}"
                ))

            # ========== DETAILED BILLS TAB ==========
            bills_tab = self.summary_bills_frame

            # Filter frame for bills tab
            bills_filter_frame = tk.Frame(bills_tab, bg='white')
            bills_filter_frame.pack(fill=tk.X, pady=(0, 10))

            tk.Label(bills_filter_frame, text="Filter by Bill Number:", font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)

            self.bills_filter_entry = tk.Entry(bills_filter_frame, font=('Segoe UI', 11), width=20)
            self.bills_filter_entry.pack(side=tk.LEFT, padx=5)
            self.bills_filter_entry.bind('<Return>', lambda e: self.filter_bills_in_summary(all_bills))

            filter_btn = tk.Button(bills_filter_frame, text="🔍 FILTER",
                                   font=('Segoe UI', 10, 'bold'),
                                   bg='#2e86c1', fg='black', relief='flat',
                                   command=lambda: self.filter_bills_in_summary(all_bills), padx=15, pady=2)
            filter_btn.pack(side=tk.LEFT, padx=5)

            clear_btn = tk.Button(bills_filter_frame, text="🔄 CLEAR",
                                  font=('Segoe UI', 10, 'bold'),
                                  bg='#95a5a6', fg='black', relief='flat',
                                  command=lambda: self.load_all_bills_in_summary(all_bills), padx=15, pady=2)
            clear_btn.pack(side=tk.LEFT, padx=5)

            # Treeview for detailed bills
            bills_tree_frame = tk.Frame(bills_tab, bg='white')
            bills_tree_frame.pack(fill=tk.BOTH, expand=True)

            bills_container = tk.Frame(bills_tree_frame, bg='white')
            bills_container.pack(fill=tk.BOTH, expand=True)

            v_scroll4 = ttk.Scrollbar(bills_container)
            v_scroll4.pack(side=tk.RIGHT, fill=tk.Y)

            h_scroll4 = ttk.Scrollbar(bills_container, orient=tk.HORIZONTAL)
            h_scroll4.pack(side=tk.BOTTOM, fill=tk.X)

            bill_columns = ('Bill #', 'Date', 'Customer', 'Table/Room', 'Type', 'Subtotal', 'Tax', 'Discount', 'Total',
                            'Method', 'Status')
            self.bills_summary_tree = ttk.Treeview(bills_container, columns=bill_columns,
                                                   yscrollcommand=v_scroll4.set,
                                                   xscrollcommand=h_scroll4.set,
                                                   height=15)

            v_scroll4.config(command=self.bills_summary_tree.yview)
            h_scroll4.config(command=self.bills_summary_tree.xview)

            for col in bill_columns:
                self.bills_summary_tree.heading(col, text=col, anchor=tk.W)
                self.bills_summary_tree.column(col, width=100)

            self.bills_summary_tree.column('Bill #', width=180)
            self.bills_summary_tree.column('Customer', width=150)
            self.bills_summary_tree.column('Date', width=120)
            self.bills_summary_tree.column('Total', width=100)

            self.bills_summary_tree.pack(fill=tk.BOTH, expand=True)

            # Bind double-click to view bill
            self.bills_summary_tree.bind('<Double-Button-1>', lambda e: self.view_bill_from_summary())

            # Action buttons for bills tab
            bills_action_frame = tk.Frame(bills_tab, bg='white')
            bills_action_frame.pack(fill=tk.X, pady=10)

            view_bill_btn = tk.Button(bills_action_frame, text="👁️ VIEW SELECTED BILL",
                                      font=('Segoe UI', 11, 'bold'),
                                      bg='#3498db', fg='black', relief='flat',
                                      command=self.view_bill_from_summary, padx=15, pady=5)
            view_bill_btn.pack(side=tk.LEFT, padx=5)

            print_bill_btn = tk.Button(bills_action_frame, text="🖨️ PRINT SELECTED BILL",
                                       font=('Segoe UI', 11, 'bold'),
                                       bg='#27ae60', fg='black', relief='flat',
                                       command=self.print_bill_from_summary, padx=15, pady=5)
            print_bill_btn.pack(side=tk.LEFT, padx=5)

            export_csv_btn = tk.Button(bills_action_frame, text="📥 EXPORT TO CSV",
                                       font=('Segoe UI', 11, 'bold'),
                                       bg='#f39c12', fg='black', relief='flat',
                                       command=lambda: self.export_bills_to_csv(all_bills), padx=15, pady=5)
            export_csv_btn.pack(side=tk.LEFT, padx=5)

            # Load all bills
            self.load_all_bills_in_summary(all_bills)

            # Grand total label at bottom
            grand_total_frame = tk.Frame(bills_tab, bg='white')
            grand_total_frame.pack(fill=tk.X, pady=5)

            grand_total = sum(bill['total_amount'] for bill in all_bills)
            tk.Label(grand_total_frame, text=f"GRAND TOTAL: ₹{grand_total:.2f}",
                     font=('Segoe UI', 14, 'bold'), bg='white', fg='#c0392b').pack(side=tk.RIGHT)

        except Exception as e:
            self.show_error(f"Error loading sales summary: {str(e)}")
            import traceback
            traceback.print_exc()

    def load_all_bills_in_summary(self, bills):
        """Load all bills into the summary tree."""
        if not hasattr(self, 'bills_summary_tree'):
            return

        # Clear existing
        for item in self.bills_summary_tree.get_children():
            self.bills_summary_tree.delete(item)

        # Sort bills by date (newest first)
        sorted_bills = sorted(bills, key=lambda x: x.get('bill_date', ''), reverse=True)

        for bill in sorted_bills:
            # Format date
            bill_date = bill['bill_date']
            if len(bill_date) > 10:
                bill_date = bill_date[:10]

            # Determine status
            if bill.get('settled_at'):
                status = 'SETTLED'
                tags = ('settled',)
            elif bill['is_complimentary']:
                status = 'COMP'
                tags = ('comp',)
            else:
                status = 'PAID'
                tags = ('paid',)

            # Get phone number
            phone = bill.get('customer_phone', '')
            # Combine customer name with phone if phone exists
            customer_display = bill['customer_name']
            if phone:
                customer_display = f"{bill['customer_name']} ({phone})"

            # Truncate if too long
            if len(customer_display) > 25:
                customer_display = customer_display[:22] + '...'

            values = (
                bill['bill_number'],
                bill_date,
                customer_display,  # Now includes phone number
                bill.get('table_number') or bill.get('room_number', ''),
                'COMP' if bill['is_complimentary'] else 'PAID',
                f"₹{bill['subtotal']:.2f}",
                f"₹{bill['tax_amount']:.2f}",
                f"₹{bill.get('discount_amount', 0):.2f}",
                f"₹{bill['total_amount']:.2f}",
                bill['payment_method'].upper(),
                status
            )
            self.bills_summary_tree.insert('', tk.END, values=values, tags=tags)

        # Configure tags
        self.bills_summary_tree.tag_configure('settled', background='#d5f5e3')
        self.bills_summary_tree.tag_configure('comp', background='#fcf3cf')
        self.bills_summary_tree.tag_configure('paid', background='#ffffff')

    def filter_bills_in_summary(self, all_bills):
        """Filter bills by bill number in summary."""
        filter_text = self.bills_filter_entry.get().strip().lower()
        if not filter_text:
            self.load_all_bills_in_summary(all_bills)
            return

        filtered_bills = [bill for bill in all_bills
                          if filter_text in bill['bill_number'].lower()
                          or filter_text in bill['customer_name'].lower()]

        self.load_all_bills_in_summary(filtered_bills)

    def view_bill_from_summary(self):
        """View selected bill from summary."""
        selection = self.bills_summary_tree.selection()
        if not selection:
            self.show_warning("Please select a bill to view")
            return

        bill_number = self.bills_summary_tree.item(selection[0])['values'][0]
        self.show_bill_preview_popup(bill_number)

    def print_bill_from_summary(self):
        """Print selected bill from summary."""
        selection = self.bills_summary_tree.selection()
        if not selection:
            self.show_warning("Please select a bill to print")
            return

        bill_number = self.bills_summary_tree.item(selection[0])['values'][0]
        self.show_bill_preview_popup(bill_number)

    def export_bills_to_csv(self, bills):
        """Export all bills in summary to CSV file."""
        if not bills:
            self.show_warning("No bills to export")
            return

        try:
            from_date = self.summary_from_date.get()
            to_date = self.summary_to_date.get()
            filename = f"sales_bills_{from_date}_to_{to_date}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['Bill Number', 'Date', 'Customer', 'Table/Room', 'Type',
                              'Subtotal (₹)', 'Tax (₹)', 'Discount (₹)', 'Total (₹)',
                              'Payment Method', 'Status', 'Settled At']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                total_amount = 0

                for bill in bills:
                    # Format date
                    bill_date = bill['bill_date']
                    if len(bill_date) > 10:
                        bill_date = bill_date[:10]

                    # Determine status
                    if bill.get('settled_at'):
                        status = 'SETTLED'
                        settled_at = bill['settled_at'][:10] if bill['settled_at'] else ''
                    elif bill['is_complimentary']:
                        status = 'COMPLIMENTARY'
                        settled_at = ''
                    else:
                        status = 'PAID'
                        settled_at = ''

                    writer.writerow({
                        'Bill Number': bill['bill_number'],
                        'Date': bill_date,
                        'Customer': bill['customer_name'],
                        'Table/Room': bill.get('table_number') or bill.get('room_number', ''),
                        'Type': 'COMP' if bill['is_complimentary'] else 'PAID',
                        'Subtotal (₹)': f"{bill['subtotal']:.2f}",
                        'Tax (₹)': f"{bill['tax_amount']:.2f}",
                        'Discount (₹)': f"{bill.get('discount_amount', 0):.2f}",
                        'Total (₹)': f"{bill['total_amount']:.2f}",
                        'Payment Method': bill['payment_method'].upper() if bill['payment_method'] else '',
                        'Status': status,
                        'Settled At': settled_at
                    })
                    total_amount += bill['total_amount']

                # Add summary row
                writer.writerow({})
                writer.writerow({
                    'Bill Number': 'TOTAL',
                    'Total (₹)': f"{total_amount:.2f}"
                })

            self.show_info(f"✅ Bills exported to:\n{filename}")

        except Exception as e:
            self.show_error(f"Error exporting bills: {str(e)}")

    def export_all_sales_data(self):
        """Export all sales data including summary and bills."""
        try:
            from_date = self.summary_from_date.get()
            to_date = self.summary_to_date.get()

            # Get all data
            all_bills = self.restaurant.get_all_bills(from_date, to_date)
            summary_data = self.restaurant.get_sales_summary(from_date, to_date)

            if not all_bills:
                self.show_warning("No data to export")
                return

            filename = f"complete_sales_report_{from_date}_to_{to_date}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)

                # Header
                writer.writerow(['THE EVAANI HOTEL - COMPLETE SALES REPORT'])
                writer.writerow([f"Period: {from_date} to {to_date}"])
                writer.writerow([f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"])
                writer.writerow([])

                # Summary Section
                writer.writerow(['=' * 50])
                writer.writerow(['SALES SUMMARY'])
                writer.writerow(['=' * 50])

                summary = summary_data['summary']
                writer.writerow(['Total Bills:', summary['total_bills']])
                writer.writerow(['Total Sales (₹):', f"{summary['total_sales']:.2f}"])
                writer.writerow(['Total Discounts (₹):', f"{summary['total_discounts']:.2f}"])
                writer.writerow(['Total Complimentary (₹):', f"{summary['total_complimentary']:.2f}"])
                writer.writerow(['Avg Discount %:', f"{summary['avg_discount_percentage']:.1f}%"])
                writer.writerow(['Settled Bills:', summary['settled_bills_count']])
                writer.writerow(['Settled Amount (₹):', f"{summary['settled_amount_total']:.2f}"])
                writer.writerow(['Settlement Discounts (₹):', f"{summary['settlement_discounts']:.2f}"])
                writer.writerow([])

                # Payment Breakdown
                writer.writerow(['PAYMENT BREAKDOWN'])
                writer.writerow(['Payment Method', 'Bills', 'Amount (₹)', 'Discounts (₹)'])
                for method in summary_data['payment_breakdown']:
                    writer.writerow([
                        method['payment_method'].upper() if method['payment_method'] else 'UNKNOWN',
                        method['bill_count'],
                        f"{method['total_amount']:.2f}",
                        f"{method['discounts']:.2f}"
                    ])
                writer.writerow([])

                # Daily Breakdown
                writer.writerow(['DAILY BREAKDOWN'])
                writer.writerow(['Date', 'Bills', 'Sales (₹)', 'Complimentary (₹)', 'Discounts (₹)', 'Settled',
                                 'Settled Amount (₹)'])
                for day in summary_data['daily_breakdown']:
                    writer.writerow([
                        day['sale_date'],
                        day['bills_count'],
                        f"{day['total_sales']:.2f}",
                        f"{day['complimentary']:.2f}",
                        f"{day['discounts']:.2f}",
                        day['settled_count'],
                        f"{day['settled_amount']:.2f}"
                    ])
                writer.writerow([])

                # Detailed Bills
                writer.writerow(['DETAILED BILLS'])
                writer.writerow(['Bill #', 'Date', 'Customer', 'Table/Room', 'Type',
                                 'Subtotal', 'Tax', 'Discount', 'Total', 'Method', 'Status'])

                total_amount = 0
                for bill in all_bills:
                    bill_date = bill['bill_date']
                    if len(bill_date) > 10:
                        bill_date = bill_date[:10]

                    if bill.get('settled_at'):
                        status = 'SETTLED'
                    elif bill['is_complimentary']:
                        status = 'COMP'
                    else:
                        status = 'PAID'

                    writer.writerow([
                        bill['bill_number'],
                        bill_date,
                        bill['customer_name'],
                        bill.get('table_number') or bill.get('room_number', ''),
                        'COMP' if bill['is_complimentary'] else 'PAID',
                        f"{bill['subtotal']:.2f}",
                        f"{bill['tax_amount']:.2f}",
                        f"{bill.get('discount_amount', 0):.2f}",
                        f"{bill['total_amount']:.2f}",
                        bill['payment_method'].upper() if bill['payment_method'] else '',
                        status
                    ])
                    total_amount += bill['total_amount']

                writer.writerow([])
                writer.writerow(['GRAND TOTAL:', f"{total_amount:.2f}"])

            self.show_info(f"✅ Complete sales report exported to:\n{filename}")

        except Exception as e:
            self.show_error(f"Error exporting sales data: {str(e)}")

    def open_settlement_dialog(self, event=None):
        """Open settlement dialog for selected bill."""
        selection = self.settlement_tree.selection()
        if not selection:
            self.show_warning("Please select a bill to settle")
            return

        # Get bill details
        bill_values = self.settlement_tree.item(selection[0])['values']
        bill_id = bill_values[0]
        bill_number = bill_values[1]
        original_total = float(bill_values[5].replace('₹', ''))
        current_customer = bill_values[3]
        current_phone = bill_values[4] if len(bill_values) > 4 and bill_values[4] else ""

        # Check if already settled
        if bill_values[6] == 'SETTLED':
            if not self.ask_confirmation(f"Bill #{bill_number} is already settled. Do you want to re-settle it?"):
                return

        # Get full bill details for phone number
        bills = self.restaurant.get_all_bills(bill_number=bill_number)
        if bills:
            bill = bills[0]
            current_phone = bill.get('customer_phone', '')

        # Create settlement dialog
        dialog = tk.Toplevel(self.current_popup if self.current_popup else self.root)
        dialog.title(f"Settle Bill - {bill_number}")
        dialog.geometry("700x650")
        dialog.transient(self.current_popup if self.current_popup else self.root)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 700, 650)

        # Bind Escape to close
        dialog.bind('<Escape>', lambda e: dialog.destroy())

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Create canvas with scrollbar
        canvas = tk.Canvas(main_frame, bg='white', highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='white')

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        tk.Label(scrollable_frame, text="SETTLE BILL", font=('Segoe UI', 18, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        # Bill info
        info_frame = tk.LabelFrame(scrollable_frame, text="Bill Information",
                                   font=('Segoe UI', 11, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        info_frame.pack(fill=tk.X, pady=(0, 20))

        tk.Label(info_frame, text=f"Bill Number: {bill_number}", font=('Segoe UI', 11),
                 bg='white', fg='#2e86c1').pack(anchor='w', pady=2)
        tk.Label(info_frame, text=f"Current Customer: {current_customer}", font=('Segoe UI', 11),
                 bg='white', fg='#2e86c1').pack(anchor='w', pady=2)
        tk.Label(info_frame, text=f"Current Phone: {current_phone if current_phone else 'Not provided'}",
                 font=('Segoe UI', 11), bg='white', fg='#2e86c1').pack(anchor='w', pady=2)
        tk.Label(info_frame, text=f"Original Amount: ₹{original_total:.2f}", font=('Segoe UI', 11, 'bold'),
                 bg='white', fg='#c0392b').pack(anchor='w', pady=2)

        # Customer Information (optional) - NEW SECTION
        customer_frame = tk.LabelFrame(scrollable_frame, text="Customer Information (Optional)",
                                       font=('Segoe UI', 11, 'bold'),
                                       bg='white', fg='#6a4334', padx=15, pady=10)
        customer_frame.pack(fill=tk.X, pady=(0, 20))

        row = 0
        tk.Label(customer_frame, text="Customer Name:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        settle_customer_name = tk.Entry(customer_frame, font=('Segoe UI', 12), width=30)
        settle_customer_name.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        settle_customer_name.insert(0, current_customer)
        row += 1

        tk.Label(customer_frame, text="Phone Number:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        settle_customer_phone = tk.Entry(customer_frame, font=('Segoe UI', 12), width=30)
        settle_customer_phone.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        settle_customer_phone.insert(0, current_phone)
        row += 1

        tk.Label(customer_frame, text="(Optional - will update bill with this information)",
                 font=('Segoe UI', 9), bg='white', fg='#7f8c8d').grid(row=row, column=0, columnspan=2, pady=2)

        # Settlement form
        settlement_form_frame = tk.LabelFrame(scrollable_frame, text="Settlement Details",
                                              font=('Segoe UI', 11, 'bold'),
                                              bg='white', fg='#6a4334', padx=15, pady=10)
        settlement_form_frame.pack(fill=tk.X, pady=(0, 20))

        row = 0
        tk.Label(settlement_form_frame, text="Amount Received (₹):", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        settle_amount_entry = tk.Entry(settlement_form_frame, font=('Segoe UI', 12), width=20)
        settle_amount_entry.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        settle_amount_entry.insert(0, str(original_total))
        row += 1

        tk.Label(settlement_form_frame, text="Payment Method:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        settle_method_var = tk.StringVar(value='cash')
        method_combo = ttk.Combobox(settlement_form_frame, textvariable=settle_method_var,
                                    values=['cash', 'card', 'upi'], state='readonly',
                                    width=18, font=('Segoe UI', 11))
        method_combo.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        row += 1

        tk.Label(settlement_form_frame, text="Notes:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='ne')
        settle_notes = tk.Text(settlement_form_frame, font=('Segoe UI', 11), width=30, height=3)
        settle_notes.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        settle_notes.insert('1.0', f"Customer paid ₹{original_total:.2f} - settled amount")
        row += 1

        # Discount preview
        discount_preview = tk.Label(settlement_form_frame, text="", font=('Segoe UI', 11, 'bold'),
                                    bg='white', fg='#27ae60')
        discount_preview.grid(row=row, column=0, columnspan=2, pady=10)

        def update_discount_preview(event=None):
            try:
                settled = float(settle_amount_entry.get())
                if 0 < settled < original_total:
                    discount = original_total - settled
                    discount_percent = (discount / original_total) * 100
                    discount_preview.config(
                        text=f"Discount: ₹{discount:.2f} ({discount_percent:.1f}%)",
                        fg='#c0392b'
                    )
                elif settled == original_total:
                    discount_preview.config(text="No discount", fg='#27ae60')
                elif settled > original_total:
                    discount_preview.config(text="Amount cannot exceed original", fg='#c0392b')
                else:
                    discount_preview.config(text="Invalid amount", fg='#c0392b')
            except:
                discount_preview.config(text="", fg='black')

        settle_amount_entry.bind('<KeyRelease>', update_discount_preview)

        def settle_action():
            try:
                settled_amount = float(settle_amount_entry.get())
                if settled_amount <= 0:
                    raise ValueError("Amount must be positive")
                if settled_amount > original_total:
                    raise ValueError(f"Settled amount cannot exceed original amount ₹{original_total:.2f}")

                settlement_data = {
                    'settled_amount': settled_amount,
                    'payment_method': settle_method_var.get(),
                    'notes': settle_notes.get('1.0', tk.END).strip(),
                    'customer_name': settle_customer_name.get().strip() or current_customer,
                    'customer_phone': settle_customer_phone.get().strip()
                }

                self.restaurant.settle_bill(bill_id, settlement_data)

                # Show summary
                discount = original_total - settled_amount
                customer_info = f"\nCustomer: {settlement_data['customer_name']}"
                if settlement_data['customer_phone']:
                    customer_info += f"\nPhone: {settlement_data['customer_phone']}"

                if discount > 0:
                    self.show_info(f"✅ Bill settled successfully!\n\n"
                                   f"Original Amount: ₹{original_total:.2f}\n"
                                   f"Amount Paid: ₹{settled_amount:.2f}\n"
                                   f"Discount Given: ₹{discount:.2f}\n"
                                   f"Discount %: {(discount / original_total * 100):.1f}%{customer_info}\n\n"
                                   f"This discount will be reflected in today's sales summary.")
                else:
                    self.show_info(f"✅ Bill settled successfully!\n\nAmount Paid: ₹{settled_amount:.2f}{customer_info}")

                dialog.destroy()
                self.load_settlement_bills()
                self.load_settlement_bills()  # Refresh twice to ensure update

            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(f"Error settling bill: {str(e)}")

        # Button frame
        button_frame = tk.Frame(scrollable_frame, bg='white')
        button_frame.pack(pady=20)

        settle_btn = tk.Button(button_frame, text="💰 SETTLE BILL", font=('Segoe UI', 12, 'bold'),
                               bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                               command=settle_action, padx=30, pady=10)
        settle_btn.pack(side=tk.LEFT, padx=10)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                               command=dialog.destroy, padx=30, pady=10)
        cancel_btn.pack(side=tk.LEFT, padx=10)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Bind Enter key
        settle_btn.bind('<Return>', lambda e: settle_action())

    def open_admin_bill_edit_dialog(self, bill_id, bill_number):
        """Open admin bill edit dialog (only for admin users)."""
        if not self.auth.is_admin():
            self.show_error("This feature is only available for administrators")
            return

        try:
            # Get full bill data for editing
            bill_data = self.restaurant.get_bill_for_editing(bill_id)
            menu_items = self.restaurant.get_all_menu_items_for_edit()

            # Create dialog
            dialog = tk.Toplevel(self.current_popup if self.current_popup else self.root)
            dialog.title(f"Admin Bill Edit - {bill_number}")
            dialog.geometry("1200x800")
            dialog.transient(self.current_popup if self.current_popup else self.root)
            dialog.grab_set()
            dialog.configure(bg='white')

            self.center_dialog(dialog, 1200, 800)

            # Bind Escape to close
            dialog.bind('<Escape>', lambda e: dialog.destroy())

            # Create main frame with scrollbar
            main_frame = tk.Frame(dialog, bg='white')
            main_frame.pack(fill=tk.BOTH, expand=True)

            # Create canvas for scrolling
            canvas = tk.Canvas(main_frame, bg='white', highlightthickness=0)
            scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
            scrollable_frame = tk.Frame(canvas, bg='white')

            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )

            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)

            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            # Warning banner
            warning_frame = tk.Frame(scrollable_frame, bg='#fff3cd', bd=2, relief=tk.SOLID)
            warning_frame.pack(fill=tk.X, pady=(0, 20))

            tk.Label(warning_frame,
                     text="⚠️ ADMIN EDIT MODE - Changes will be applied to all records and tracked in audit log",
                     font=('Segoe UI', 12, 'bold'),
                     bg='#fff3cd', fg='#856404', padx=20, pady=10).pack()

            # Bill Information Section
            info_frame = tk.LabelFrame(scrollable_frame, text="Bill Information (Editable)",
                                       font=('Segoe UI', 14, 'bold'),
                                       bg='white', fg='#6a4334', padx=20, pady=15)
            info_frame.pack(fill=tk.X, pady=(0, 20))

            row = 0
            # Customer Information
            tk.Label(info_frame, text="Customer Name:", font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=8, sticky='e')
            self.edit_customer_name = tk.Entry(info_frame, font=('Segoe UI', 12), width=30)
            self.edit_customer_name.grid(row=row, column=1, padx=10, pady=8, sticky='w')
            self.edit_customer_name.insert(0, str(bill_data['customer_name']))  # Fixed: convert to string
            row += 1

            tk.Label(info_frame, text="Phone Number:", font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=8, sticky='e')
            self.edit_customer_phone = tk.Entry(info_frame, font=('Segoe UI', 12), width=30)
            self.edit_customer_phone.grid(row=row, column=1, padx=10, pady=8, sticky='w')
            self.edit_customer_phone.insert(0, str(bill_data.get('customer_phone', '')))  # Fixed: convert to string
            row += 1

            # Table/Room Information
            tk.Label(info_frame, text="Table Number:", font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=8, sticky='e')
            self.edit_table_number = tk.Entry(info_frame, font=('Segoe UI', 12), width=15)
            self.edit_table_number.grid(row=row, column=1, padx=10, pady=8, sticky='w')
            self.edit_table_number.insert(0, str(bill_data.get('table_number', '')))  # Fixed: convert to string
            row += 1

            tk.Label(info_frame, text="Room Number:", font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=8, sticky='e')
            self.edit_room_number = tk.Entry(info_frame, font=('Segoe UI', 12), width=15)
            self.edit_room_number.grid(row=row, column=1, padx=10, pady=8, sticky='w')
            self.edit_room_number.insert(0, str(bill_data.get('room_number', '')))  # Fixed: convert to string
            row += 1

            # Separator
            separator = ttk.Separator(info_frame, orient='horizontal')
            separator.grid(row=row, column=0, columnspan=2, sticky='ew', pady=15)
            row += 1

            # Financial Information
            tk.Label(info_frame, text="Subtotal (₹):", font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=8, sticky='e')
            self.edit_subtotal = tk.Entry(info_frame, font=('Segoe UI', 12), width=15)
            self.edit_subtotal.grid(row=row, column=1, padx=10, pady=8, sticky='w')
            self.edit_subtotal.insert(0, f"{float(bill_data['subtotal']):.2f}")  # Fixed: format as float
            row += 1

            tk.Label(info_frame, text="Tax Amount (₹):", font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=8, sticky='e')
            self.edit_tax = tk.Entry(info_frame, font=('Segoe UI', 12), width=15)
            self.edit_tax.grid(row=row, column=1, padx=10, pady=8, sticky='w')
            self.edit_tax.insert(0, f"{float(bill_data['tax_amount']):.2f}")  # Fixed: format as float
            row += 1

            tk.Label(info_frame, text="Discount (%):", font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=8, sticky='e')
            self.edit_discount_percent = tk.Entry(info_frame, font=('Segoe UI', 12), width=10)
            self.edit_discount_percent.grid(row=row, column=1, padx=10, pady=8, sticky='w')
            self.edit_discount_percent.insert(0,
                                              f"{float(bill_data.get('discount_percentage', 0)):.1f}")  # Fixed: format as float
            self.edit_discount_percent.bind('<KeyRelease>', self.update_total_from_discount)
            row += 1

            tk.Label(info_frame, text="Discount Amount (₹):", font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=8, sticky='e')
            self.edit_discount_amount = tk.Entry(info_frame, font=('Segoe UI', 12), width=15)
            self.edit_discount_amount.grid(row=row, column=1, padx=10, pady=8, sticky='w')
            self.edit_discount_amount.insert(0,
                                             f"{float(bill_data.get('discount_amount', 0)):.2f}")  # Fixed: format as float
            self.edit_discount_amount.bind('<KeyRelease>', self.update_total_from_discount_amount)
            row += 1

            tk.Label(info_frame, text="Total Amount (₹):", font=('Segoe UI', 12, 'bold'),
                     bg='white', fg='#c0392b').grid(row=row, column=0, padx=10, pady=8, sticky='e')
            self.edit_total = tk.Entry(info_frame, font=('Segoe UI', 12, 'bold'), width=15, fg='#c0392b')
            self.edit_total.grid(row=row, column=1, padx=10, pady=8, sticky='w')
            self.edit_total.insert(0, f"{float(bill_data['total_amount']):.2f}")  # Fixed: format as float
            row += 1

            # Separator
            separator2 = ttk.Separator(info_frame, orient='horizontal')
            separator2.grid(row=row, column=0, columnspan=2, sticky='ew', pady=15)
            row += 1

            # Payment Information
            tk.Label(info_frame, text="Payment Method:", font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=8, sticky='e')
            self.edit_payment_method = ttk.Combobox(info_frame,
                                                    values=['cash', 'card', 'upi', 'pending'],
                                                    state='readonly', width=18, font=('Segoe UI', 11))
            self.edit_payment_method.grid(row=row, column=1, padx=10, pady=8, sticky='w')
            self.edit_payment_method.set(bill_data['payment_method'])
            row += 1

            tk.Label(info_frame, text="Payment Status:", font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=8, sticky='e')
            self.edit_payment_status = ttk.Combobox(info_frame,
                                                    values=['pending', 'paid', 'settled'],
                                                    state='readonly', width=18, font=('Segoe UI', 11))
            self.edit_payment_status.grid(row=row, column=1, padx=10, pady=8, sticky='w')
            self.edit_payment_status.set(bill_data['payment_status'])
            row += 1

            # Reason for edit
            tk.Label(info_frame, text="Reason for Edit:", font=('Segoe UI', 11, 'bold'),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=8, sticky='ne')
            self.edit_reason = tk.Text(info_frame, font=('Segoe UI', 11), width=40, height=3)
            self.edit_reason.grid(row=row, column=1, padx=10, pady=8, sticky='w')
            self.edit_reason.insert('1.0', "Admin correction - ")
            row += 1

            # Items Section
            items_frame = tk.LabelFrame(scrollable_frame, text="Order Items (Editable)",
                                        font=('Segoe UI', 14, 'bold'),
                                        bg='white', fg='#6a4334', padx=20, pady=15)
            items_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 20))

            # Item management buttons
            item_btn_frame = tk.Frame(items_frame, bg='white')
            item_btn_frame.pack(fill=tk.X, pady=(0, 10))

            add_item_btn = tk.Button(item_btn_frame, text="➕ ADD ITEM",
                                     font=('Segoe UI', 10, 'bold'),
                                     bg='#27ae60', fg='black', relief='flat',
                                     command=lambda: self.add_item_to_edit(bill_data['order_id'], menu_items,
                                                                           items_tree),
                                     padx=10, pady=2)
            add_item_btn.pack(side=tk.LEFT, padx=5)

            remove_item_btn = tk.Button(item_btn_frame, text="🗑️ REMOVE SELECTED",
                                        font=('Segoe UI', 10, 'bold'),
                                        bg='#c0392b', fg='black', relief='flat',
                                        command=lambda: self.remove_selected_edit_item(items_tree,
                                                                                       bill_data['order_id']),
                                        padx=10, pady=2)
            remove_item_btn.pack(side=tk.LEFT, padx=5)

            # Items tree
            tree_frame = tk.Frame(items_frame, bg='white')
            tree_frame.pack(fill=tk.BOTH, expand=True)

            tree_container = tk.Frame(tree_frame, bg='white')
            tree_container.pack(fill=tk.BOTH, expand=True)

            v_scroll = ttk.Scrollbar(tree_container)
            v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

            h_scroll = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
            h_scroll.pack(side=tk.BOTTOM, fill=tk.X)

            columns = ('S.No', 'Item Name', 'Quantity', 'Unit Price', 'Tax %', 'Total')
            items_tree = ttk.Treeview(tree_container, columns=columns,
                                      yscrollcommand=v_scroll.set,
                                      xscrollcommand=h_scroll.set,
                                      height=8)

            v_scroll.config(command=items_tree.yview)
            h_scroll.config(command=items_tree.xview)

            for col in columns:
                items_tree.heading(col, text=col, anchor=tk.W)
                items_tree.column(col, width=100)

            items_tree.column('S.No', width=50)
            items_tree.column('Item Name', width=200)
            items_tree.column('Quantity', width=80)
            items_tree.column('Unit Price', width=100)
            items_tree.column('Tax %', width=80)
            items_tree.column('Total', width=100)

            items_tree.pack(fill=tk.BOTH, expand=True)

            items_tree.bind('<Double-Button-1>',
                            lambda e: self.edit_selected_item(items_tree, menu_items, bill_data['order_id']))

            # Load existing items
            self.edit_items_data = []
            for item in bill_data.get('items', []):
                self.edit_items_data.append({
                    'menu_item_id': item.get('menu_item_id', 0),
                    'item_name': item['item_name'],
                    'quantity': item['quantity'],
                    'unit_price': item['unit_price'],
                    'tax_percentage': item.get('tax_percentage', 5.0),
                    'total_price': item['total_price']
                })
                items_tree.insert('', tk.END, values=(
                    len(self.edit_items_data),
                    item['item_name'],
                    item['quantity'],
                    f"₹{float(item['unit_price']):.2f}",
                    f"{float(item.get('tax_percentage', 5.0)):.1f}%",
                    f"₹{float(item['total_price']):.2f}"
                ))

            # Edit History Section
            history_frame = tk.LabelFrame(scrollable_frame, text="Edit History",
                                          font=('Segoe UI', 14, 'bold'),
                                          bg='white', fg='#6a4334', padx=20, pady=15)
            history_frame.pack(fill=tk.X, pady=(0, 20))

            # Get edit history
            edit_history = self.restaurant.get_bill_edit_history(bill_id)

            if edit_history:
                history_text = ""
                for h in edit_history:
                    history_text += f"[{h['edited_at'][:16]}] {h['editor_name']}: {h['field_name']} - '{h['old_value']}' → '{h['new_value']}'\n"
                    if h.get('reason'):
                        history_text += f"     Reason: {h['reason']}\n"

                tk.Label(history_frame, text=history_text, font=('Segoe UI', 10),
                         bg='white', fg='#2e86c1', justify=tk.LEFT).pack(anchor='w')
            else:
                tk.Label(history_frame, text="No edit history available", font=('Segoe UI', 10),
                         bg='white', fg='#7f8c8d').pack(anchor='w')

            # Button frame
            button_frame = tk.Frame(scrollable_frame, bg='white')
            button_frame.pack(pady=20)

            def save_edits():
                try:
                    # Validate inputs
                    if not self.edit_customer_name.get().strip():
                        raise ValueError("Customer name cannot be empty")

                    subtotal = float(self.edit_subtotal.get() or 0)
                    tax = float(self.edit_tax.get() or 0)
                    discount_percent = float(self.edit_discount_percent.get() or 0)
                    discount_amount = float(self.edit_discount_amount.get() or 0)
                    total = float(self.edit_total.get() or 0)

                    reason_text = self.edit_reason.get('1.0', tk.END).strip()
                    if not reason_text or reason_text == "Admin correction - ":
                        raise ValueError("Please provide a reason for the edit")

                    # Prepare edit data
                    edit_data = {
                        'customer_name': self.edit_customer_name.get().strip(),
                        'customer_phone': self.edit_customer_phone.get().strip(),
                        'table_number': self.edit_table_number.get().strip(),
                        'room_number': self.edit_room_number.get().strip(),
                        'subtotal': subtotal,
                        'tax_amount': tax,
                        'discount_percentage': discount_percent,
                        'discount_amount': discount_amount,
                        'total_amount': total,
                        'payment_method': self.edit_payment_method.get(),
                        'payment_status': self.edit_payment_status.get(),
                        'items': self.edit_items_data
                    }

                    # Update bill
                    self.restaurant.update_bill_after_edit(bill_id, edit_data, self.auth.current_user['id'],
                                                           reason_text)

                    self.show_info(
                        "✅ Bill updated successfully!\n\nChanges have been saved to all records and audit log.")

                    dialog.destroy()

                    # Refresh the current view if needed
                    if hasattr(self, 'load_all_bills_data_popup'):
                        self.load_all_bills_data_popup()

                except ValueError as e:
                    self.show_error(str(e))
                except Exception as e:
                    self.show_error(f"Error saving edits: {str(e)}")

            save_btn = tk.Button(button_frame, text="💾 SAVE CHANGES", font=('Segoe UI', 14, 'bold'),
                                 bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                                 command=save_edits, padx=30, pady=10)
            save_btn.pack(side=tk.LEFT, padx=10)

            cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 14, 'bold'),
                                   bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                                   command=dialog.destroy, padx=30, pady=10)
            cancel_btn.pack(side=tk.LEFT, padx=10)

            # Bind Enter key to save button
            save_btn.bind('<Return>', lambda e: save_edits())

        except Exception as e:
            self.show_error(f"Error opening edit dialog: {str(e)}")
            import traceback
            traceback.print_exc()

    def add_item_to_edit(self, order_id, menu_items, tree):
        """Add a new item to the bill being edited."""
        # Create selection dialog
        dialog = tk.Toplevel(self.current_popup if self.current_popup else self.root)
        dialog.title("Add Item to Bill")
        dialog.geometry("500x400")
        dialog.transient(self.current_popup if self.current_popup else self.root)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 500, 400)

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="SELECT ITEM TO ADD", font=('Segoe UI', 14, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        # Search frame
        search_frame = tk.Frame(main_frame, bg='white')
        search_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(search_frame, text="Search:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)

        search_entry = tk.Entry(search_frame, font=('Segoe UI', 11), width=20)
        search_entry.pack(side=tk.LEFT, padx=5)

        # Items list
        list_frame = tk.Frame(main_frame, bg='white')
        list_frame.pack(fill=tk.BOTH, expand=True)

        listbox = tk.Listbox(list_frame, font=('Segoe UI', 10), height=10)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.config(yscrollcommand=scrollbar.set)

        # Load items
        items_by_id = {}
        for item in menu_items:
            display = f"{item['id']}: {item['item_name']} - ₹{item['price']:.2f} ({item['category_name']})"
            listbox.insert(tk.END, display)
            items_by_id[display] = item

        def search_items():
            search_text = search_entry.get().lower()
            listbox.delete(0, tk.END)
            for item in menu_items:
                if search_text in item['item_name'].lower() or search_text in str(item['id']):
                    display = f"{item['id']}: {item['item_name']} - ₹{item['price']:.2f} ({item['category_name']})"
                    listbox.insert(tk.END, display)
                    items_by_id[display] = item

        search_entry.bind('<KeyRelease>', lambda e: search_items())

        # Quantity
        qty_frame = tk.Frame(main_frame, bg='white')
        qty_frame.pack(fill=tk.X, pady=10)

        tk.Label(qty_frame, text="Quantity:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)

        qty_entry = tk.Entry(qty_frame, font=('Segoe UI', 11), width=5)
        qty_entry.pack(side=tk.LEFT, padx=5)
        qty_entry.insert(0, '1')

        def add_selected():
            selection = listbox.curselection()
            if not selection:
                self.show_warning("Please select an item")
                return

            selected_text = listbox.get(selection[0])
            if selected_text in items_by_id:
                item = items_by_id[selected_text]
                quantity = int(qty_entry.get())

                # Add to edit items data
                new_item = {
                    'menu_item_id': item['id'],
                    'item_name': item['item_name'],
                    'quantity': quantity,
                    'unit_price': item['price'],
                    'tax_percentage': item['tax_percentage'],
                    'total_price': item['price'] * quantity
                }

                self.edit_items_data.append(new_item)

                # Add to tree
                tree.insert('', tk.END, values=(
                    len(self.edit_items_data),
                    item['item_name'],
                    quantity,
                    f"₹{item['price']:.2f}",
                    f"{item['tax_percentage']}%",
                    f"₹{item['price'] * quantity:.2f}"
                ))

                # Recalculate totals
                self.recalculate_edit_totals()

                dialog.destroy()

        button_frame = tk.Frame(main_frame, bg='white')
        button_frame.pack(pady=10)

        add_btn = tk.Button(button_frame, text="ADD ITEM", font=('Segoe UI', 11, 'bold'),
                            bg='#27ae60', fg='black', relief='flat',
                            command=add_selected, padx=20, pady=5)
        add_btn.pack(side=tk.LEFT, padx=5)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 11, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat',
                               command=dialog.destroy, padx=20, pady=5)
        cancel_btn.pack(side=tk.LEFT, padx=5)

    def remove_selected_edit_item(self, tree, order_id):
        """Remove selected item from edit bill."""
        selection = tree.selection()
        if not selection:
            self.show_warning("Please select an item to remove")
            return

        # Get the index from tree
        item_id = int(tree.item(selection[0])['values'][0])

        if 1 <= item_id <= len(self.edit_items_data):
            # Remove from data
            removed = self.edit_items_data.pop(item_id - 1)

            # Remove from tree
            tree.delete(selection[0])

            # Reindex remaining items
            for i, child in enumerate(tree.get_children(), 1):
                values = list(tree.item(child)['values'])
                values[0] = i
                tree.item(child, values=values)

            self.show_info(f"Removed: {removed['item_name']}")

            # Recalculate totals
            self.recalculate_edit_totals()

    def edit_selected_item(self, tree, menu_items, order_id):
        """Edit selected item in edit bill."""
        selection = tree.selection()
        if not selection:
            return

        item_index = int(tree.item(selection[0])['values'][0]) - 1
        item = self.edit_items_data[item_index]

        # Create edit dialog
        dialog = tk.Toplevel(self.current_popup if self.current_popup else self.root)
        dialog.title("Edit Item")
        dialog.geometry("400x250")
        dialog.transient(self.current_popup if self.current_popup else self.root)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 400, 250)

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text=f"Edit: {item['item_name']}", font=('Segoe UI', 14, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        form_frame = tk.Frame(main_frame, bg='white')
        form_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(form_frame, text="Quantity:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=0, column=0, padx=5, pady=8, sticky='e')

        qty_entry = tk.Entry(form_frame, font=('Segoe UI', 11), width=10)
        qty_entry.grid(row=0, column=1, padx=5, pady=8, sticky='w')
        qty_entry.insert(0, str(item['quantity']))

        tk.Label(form_frame, text="Unit Price (₹):", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=1, column=0, padx=5, pady=8, sticky='e')

        price_entry = tk.Entry(form_frame, font=('Segoe UI', 11), width=10)
        price_entry.grid(row=1, column=1, padx=5, pady=8, sticky='w')
        price_entry.insert(0, f"{item['unit_price']:.2f}")

        def update_item():
            try:
                new_qty = int(qty_entry.get())
                new_price = float(price_entry.get())

                if new_qty <= 0:
                    raise ValueError("Quantity must be positive")
                if new_price <= 0:
                    raise ValueError("Price must be positive")

                # Update item
                self.edit_items_data[item_index]['quantity'] = new_qty
                self.edit_items_data[item_index]['unit_price'] = new_price
                self.edit_items_data[item_index]['total_price'] = new_price * new_qty

                # Update tree
                tree.item(selection[0], values=(
                    item_index + 1,
                    item['item_name'],
                    new_qty,
                    f"₹{new_price:.2f}",
                    f"{item['tax_percentage']}%",
                    f"₹{new_price * new_qty:.2f}"
                ))

                # Recalculate totals
                self.recalculate_edit_totals()

                dialog.destroy()

            except ValueError as e:
                self.show_error(str(e))

        button_frame = tk.Frame(form_frame, bg='white')
        button_frame.grid(row=2, column=0, columnspan=2, pady=15)

        update_btn = tk.Button(button_frame, text="UPDATE", font=('Segoe UI', 11, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=update_item, padx=20, pady=5)
        update_btn.pack(side=tk.LEFT, padx=5)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 11, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat',
                               command=dialog.destroy, padx=20, pady=5)
        cancel_btn.pack(side=tk.LEFT, padx=5)

    def recalculate_edit_totals(self):
        """Recalculate totals based on current items."""
        try:
            subtotal = sum(item['total_price'] for item in self.edit_items_data)
            tax = sum(item['unit_price'] * item['quantity'] * item['tax_percentage'] / 100
                      for item in self.edit_items_data)

            self.edit_subtotal.delete(0, tk.END)
            self.edit_subtotal.insert(0, f"{subtotal:.2f}")

            self.edit_tax.delete(0, tk.END)
            self.edit_tax.insert(0, f"{tax:.2f}")

            # Recalculate total with discount
            self.update_total_from_discount()

        except Exception as e:
            print(f"Error recalculating totals: {e}")

    def update_total_from_discount(self, event=None):
        """Update total based on discount percentage."""
        try:
            subtotal = float(self.edit_subtotal.get())
            tax = float(self.edit_tax.get())
            discount_percent = float(self.edit_discount_percent.get() or 0)

            base_total = subtotal + tax
            discount_amount = base_total * (discount_percent / 100)
            final_total = base_total - discount_amount

            self.edit_discount_amount.delete(0, tk.END)
            self.edit_discount_amount.insert(0, f"{discount_amount:.2f}")

            self.edit_total.delete(0, tk.END)
            self.edit_total.insert(0, f"{final_total:.2f}")

        except:
            pass

    def update_total_from_discount_amount(self, event=None):
        """Update total based on discount amount."""
        try:
            subtotal = float(self.edit_subtotal.get())
            tax = float(self.edit_tax.get())
            discount_amount = float(self.edit_discount_amount.get() or 0)

            base_total = subtotal + tax
            final_total = base_total - discount_amount

            if base_total > 0:
                discount_percent = (discount_amount / base_total) * 100
                self.edit_discount_percent.delete(0, tk.END)
                self.edit_discount_percent.insert(0, f"{discount_percent:.1f}")

            self.edit_total.delete(0, tk.END)
            self.edit_total.insert(0, f"{final_total:.2f}")

        except:
            pass

    def admin_edit_selected_bill_popup(self):
        """Open admin edit dialog for selected bill."""
        selection = self.all_bills_tree.selection()
        if not selection:
            self.show_warning("Please select a bill to edit")
            return

        bill_number = self.all_bills_tree.item(selection[0])['values'][0]

        # Get bill ID from database
        bills = self.restaurant.get_all_bills(bill_number=bill_number)
        if not bills:
            self.show_error("Bill not found")
            return

        bill = bills[0]
        self.open_admin_bill_edit_dialog(bill['id'], bill_number)

    def test_all_printers(self):
        """Test all configured printers"""
        if not hasattr(self.restaurant, 'printer_manager'):
            self.show_error("Printer manager not initialized")
            return

        results = []
        for printer_type in ['kitchen', 'desk', 'bill']:
            printer_info = self.restaurant.printer_manager.get_printer(printer_type)
            printer_name = printer_info['name'] if printer_info else 'Not configured'

            # Show test dialog
            success = self.restaurant.printer_manager.test_printer(printer_type)
            status = "✅ Working" if success else "❌ Failed"
            results.append(f"{printer_type.upper()}: {printer_name} - {status}")

        self.show_info("Printer Test Results:\n\n" + "\n".join(results))

    def configure_printers_dialog(self):
        """Dialog to configure actual Windows printer names"""
        if not hasattr(self.restaurant, 'printer_manager'):
            self.show_error("Printer manager not initialized")
            return

        # Get available printers from Windows
        available_printers = self.restaurant.printer_manager.list_windows_printers()

        if not available_printers:
            self.show_error("No printers found in Windows")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Configure Printers")
        dialog.geometry("600x550")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 600, 550)

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="Printer Configuration",
                 font=('Segoe UI', 16, 'bold'), bg='white', fg='#6a4334').pack(pady=(0, 20))

        tk.Label(main_frame, text="Select the actual Windows printer names for each printer type:",
                 font=('Segoe UI', 11), bg='white', fg='#2e86c1').pack(pady=(0, 20))

        # Kitchen printer
        kitchen_frame = tk.LabelFrame(main_frame, text="Kitchen Printer (32 chars width)",
                                      font=('Segoe UI', 11, 'bold'),
                                      bg='white', fg='#6a4334', padx=15, pady=10)
        kitchen_frame.pack(fill=tk.X, pady=5)

        kitchen_info = self.restaurant.printer_manager.get_printer('kitchen') or {}
        kitchen_var = tk.StringVar(value=kitchen_info.get('name', ''))
        kitchen_combo = ttk.Combobox(kitchen_frame, textvariable=kitchen_var,
                                     values=available_printers, state='readonly', width=50,
                                     font=('Segoe UI', 11))
        kitchen_combo.pack(fill=tk.X, pady=5)

        # Desk printer
        desk_frame = tk.LabelFrame(main_frame, text="Desk Printer (40 chars width)",
                                   font=('Segoe UI', 11, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        desk_frame.pack(fill=tk.X, pady=5)

        desk_info = self.restaurant.printer_manager.get_printer('desk') or {}
        desk_var = tk.StringVar(value=desk_info.get('name', ''))
        desk_combo = ttk.Combobox(desk_frame, textvariable=desk_var,
                                  values=available_printers, state='readonly', width=50,
                                  font=('Segoe UI', 11))
        desk_combo.pack(fill=tk.X, pady=5)

        # Bill printer
        bill_frame = tk.LabelFrame(main_frame, text="Bill Printer (40 chars width)",
                                   font=('Segoe UI', 11, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        bill_frame.pack(fill=tk.X, pady=5)

        bill_info = self.restaurant.printer_manager.get_printer('bill') or {}
        bill_var = tk.StringVar(value=bill_info.get('name', ''))
        bill_combo = ttk.Combobox(bill_frame, textvariable=bill_var,
                                  values=available_printers, state='readonly', width=50,
                                  font=('Segoe UI', 11))
        bill_combo.pack(fill=tk.X, pady=5)

        # Test buttons for each printer
        test_frame = tk.Frame(main_frame, bg='white')
        test_frame.pack(fill=tk.X, pady=10)

        def test_kitchen():
            if kitchen_var.get():
                self.restaurant.printer_manager.set_printer('kitchen', kitchen_var.get(), 32)
                if self.restaurant.printer_manager.test_printer('kitchen'):
                    self.show_info("Kitchen printer test successful!")
                else:
                    self.show_error("Kitchen printer test failed!")

        def test_desk():
            if desk_var.get():
                self.restaurant.printer_manager.set_printer('desk', desk_var.get(), 40)
                if self.restaurant.printer_manager.test_printer('desk'):
                    self.show_info("Desk printer test successful!")
                else:
                    self.show_error("Desk printer test failed!")

        def test_bill():
            if bill_var.get():
                self.restaurant.printer_manager.set_printer('bill', bill_var.get(), 40)
                if self.restaurant.printer_manager.test_printer('bill'):
                    self.show_info("Bill printer test successful!")
                else:
                    self.show_error("Bill printer test failed!")

        tk.Button(test_frame, text="TEST KITCHEN", font=('Segoe UI', 10, 'bold'),
                  bg='#2e86c1', fg='black', command=test_kitchen, padx=10, pady=5).pack(side=tk.LEFT, padx=5)
        tk.Button(test_frame, text="TEST DESK", font=('Segoe UI', 10, 'bold'),
                  bg='#2e86c1', fg='black', command=test_desk, padx=10, pady=5).pack(side=tk.LEFT, padx=5)
        tk.Button(test_frame, text="TEST BILL", font=('Segoe UI', 10, 'bold'),
                  bg='#2e86c1', fg='black', command=test_bill, padx=10, pady=5).pack(side=tk.LEFT, padx=5)

        def save_config():
            # Save all printer configurations
            if kitchen_var.get():
                self.restaurant.printer_manager.set_printer('kitchen', kitchen_var.get(), 32)
            if desk_var.get():
                self.restaurant.printer_manager.set_printer('desk', desk_var.get(), 40)
            if bill_var.get():
                self.restaurant.printer_manager.set_printer('bill', bill_var.get(), 40)

            self.show_info("Printer configuration saved successfully!")
            dialog.destroy()

        button_frame = tk.Frame(main_frame, bg='white')
        button_frame.pack(pady=20)

        save_btn = tk.Button(button_frame, text="💾 SAVE CONFIGURATION", font=('Segoe UI', 12, 'bold'),
                             bg='#27ae60', fg='black', command=save_config, padx=30, pady=10)
        save_btn.pack(side=tk.LEFT, padx=10)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', command=dialog.destroy, padx=30, pady=10)
        cancel_btn.pack(side=tk.LEFT, padx=10)

    def configure_printers_dialog(self):
        """Dialog to configure actual Windows printer names"""
        if not hasattr(self.restaurant, 'win_printer'):
            self.show_error("Printer manager not initialized")
            return

        # Get available printers from Windows
        available_printers = self.restaurant.win_printer.get_available_windows_printers()

        if not available_printers:
            self.show_error("No printers found in Windows")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Configure Printers")
        dialog.geometry("600x500")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg='white')

        self.center_dialog(dialog, 600, 500)

        main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="Printer Configuration",
                 font=('Segoe UI', 16, 'bold'), bg='white', fg='#6a4334').pack(pady=(0, 20))

        tk.Label(main_frame, text="Select the actual Windows printer names for each printer type:",
                 font=('Segoe UI', 11), bg='white', fg='#2e86c1').pack(pady=(0, 20))

        # Kitchen printer
        kitchen_frame = tk.LabelFrame(main_frame, text="Kitchen Printer",
                                      font=('Segoe UI', 11, 'bold'),
                                      bg='white', fg='#6a4334', padx=15, pady=10)
        kitchen_frame.pack(fill=tk.X, pady=5)

        kitchen_var = tk.StringVar(value=self.restaurant.win_printer.printers.get('kitchen', {}).get('name', ''))
        kitchen_combo = ttk.Combobox(kitchen_frame, textvariable=kitchen_var,
                                     values=available_printers, state='readonly', width=50,
                                     font=('Segoe UI', 11))
        kitchen_combo.pack(fill=tk.X, pady=5)

        # Desk printer
        desk_frame = tk.LabelFrame(main_frame, text="Desk Printer",
                                   font=('Segoe UI', 11, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        desk_frame.pack(fill=tk.X, pady=5)

        desk_var = tk.StringVar(value=self.restaurant.win_printer.printers.get('desk', {}).get('name', ''))
        desk_combo = ttk.Combobox(desk_frame, textvariable=desk_var,
                                  values=available_printers, state='readonly', width=50,
                                  font=('Segoe UI', 11))
        desk_combo.pack(fill=tk.X, pady=5)

        # Bill printer
        bill_frame = tk.LabelFrame(main_frame, text="Bill Printer",
                                   font=('Segoe UI', 11, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        bill_frame.pack(fill=tk.X, pady=5)

        bill_var = tk.StringVar(value=self.restaurant.win_printer.printers.get('bill', {}).get('name', ''))
        bill_combo = ttk.Combobox(bill_frame, textvariable=bill_var,
                                  values=available_printers, state='readonly', width=50,
                                  font=('Segoe UI', 11))
        bill_combo.pack(fill=tk.X, pady=5)

        # Test buttons for each printer
        test_frame = tk.Frame(main_frame, bg='white')
        test_frame.pack(fill=tk.X, pady=10)

        def test_kitchen():
            if kitchen_var.get():
                self.restaurant.win_printer.printers['kitchen']['name'] = kitchen_var.get()
                if self.restaurant.win_printer.test_printer('kitchen'):
                    self.show_info("Kitchen printer test successful!")
                else:
                    self.show_error("Kitchen printer test failed!")

        def test_desk():
            if desk_var.get():
                self.restaurant.win_printer.printers['desk']['name'] = desk_var.get()
                if self.restaurant.win_printer.test_printer('desk'):
                    self.show_info("Desk printer test successful!")
                else:
                    self.show_error("Desk printer test failed!")

        def test_bill():
            if bill_var.get():
                self.restaurant.win_printer.printers['bill']['name'] = bill_var.get()
                if self.restaurant.win_printer.test_printer('bill'):
                    self.show_info("Bill printer test successful!")
                else:
                    self.show_error("Bill printer test failed!")

        tk.Button(test_frame, text="TEST KITCHEN", font=('Segoe UI', 10, 'bold'),
                  bg='#2e86c1', fg='black', command=test_kitchen, padx=10, pady=5).pack(side=tk.LEFT, padx=5)
        tk.Button(test_frame, text="TEST DESK", font=('Segoe UI', 10, 'bold'),
                  bg='#2e86c1', fg='black', command=test_desk, padx=10, pady=5).pack(side=tk.LEFT, padx=5)
        tk.Button(test_frame, text="TEST BILL", font=('Segoe UI', 10, 'bold'),
                  bg='#2e86c1', fg='black', command=test_bill, padx=10, pady=5).pack(side=tk.LEFT, padx=5)

        def save_config():
            # Update printer names
            self.restaurant.win_printer.printers['kitchen']['name'] = kitchen_var.get()
            self.restaurant.win_printer.printers['desk']['name'] = desk_var.get()
            self.restaurant.win_printer.printers['bill']['name'] = bill_var.get()

            # Update database
            for printer_type, printer_info in self.restaurant.win_printer.printers.items():
                self.restaurant.db.execute_query('''
                   UPDATE printer_settings
                   SET printer_name = ?
                   WHERE printer_type = ? AND enabled = 1
               ''', (printer_info['name'], printer_type), commit=True)

            self.show_info("Printer configuration saved successfully!")
            dialog.destroy()

        button_frame = tk.Frame(main_frame, bg='white')
        button_frame.pack(pady=20)

        save_btn = tk.Button(button_frame, text="💾 SAVE CONFIGURATION", font=('Segoe UI', 12, 'bold'),
                             bg='#27ae60', fg='black', command=save_config, padx=30, pady=10)
        save_btn.pack(side=tk.LEFT, padx=10)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', command=dialog.destroy, padx=30, pady=10)
        cancel_btn.pack(side=tk.LEFT, padx=10)

    def run(self):
        """Run the application."""
        self.root.mainloop()


# ==================== MAIN ENTRY POINT ====================
if __name__ == "__main__":
    try:
        app = IntegratedRestaurantAppGUI()
        app.run()
    except Exception as e:
        print(f"Error starting application: {e}")
        import traceback

        traceback.print_exc()
        input("Press Enter to exit...")


