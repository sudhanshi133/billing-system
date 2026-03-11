import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sqlite3
import hashlib
from datetime import datetime, timedelta, date
import csv
import json
import os
from PIL import Image, ImageTk, ImageDraw, ImageFont
import tempfile
import threading
from queue import Queue
import time
import re
import urllib.request
from io import BytesIO

# Database setup with connection pooling
class HotelDatabase:
    def __init__(self, db_name='hotel_billing.db'):
        self.db_name = db_name
        self.connection_pool = Queue(maxsize=10)
        self.init_connection_pool()
        self.init_database()

    def init_connection_pool(self):
        """Initialize connection pool with 5 connections."""
        for _ in range(5):
            conn = sqlite3.connect(self.db_name, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self.connection_pool.put(conn)

    def get_connection(self):
        """Get a connection from the pool."""
        try:
            return self.connection_pool.get(timeout=5)
        except:
            # Create new connection if pool is empty
            conn = sqlite3.connect(self.db_name, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            return conn

    def return_connection(self, conn):
        """Return connection to the pool."""
        try:
            self.connection_pool.put(conn, timeout=5)
        except:
            conn.close()

    def init_database(self):
        conn = self.get_connection()
        cursor = conn.cursor()

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
                hotel_name TEXT DEFAULT 'THE EVAANI',
                unit TEXT DEFAULT 'Unit of BY JS HOTELS & FOODS',
                address TEXT DEFAULT 'Talwandi Road, Mansa',
                phone TEXT DEFAULT '9530752236, 9915297440',
                gstin TEXT DEFAULT '03AATFJ9071F1Z3',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Rooms table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_number TEXT UNIQUE NOT NULL,
                room_type TEXT NOT NULL,
                price_per_hour REAL NOT NULL,
                price_per_day REAL NOT NULL,
                status TEXT DEFAULT 'available',
                description TEXT,
                amenities TEXT,
                max_occupancy INTEGER DEFAULT 2,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Room status history
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS room_status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                changed_by INTEGER,
                changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reason TEXT,
                FOREIGN KEY (room_id) REFERENCES rooms (id),
                FOREIGN KEY (changed_by) REFERENCES users (id)
            )
        ''')

        # Bookings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                guest_name TEXT NOT NULL,
                guest_phone TEXT,
                guest_email TEXT,
                guest_id_card TEXT,
                guest_address TEXT,
                check_in_date DATE,
                check_out_date DATE,
                check_in_time TIMESTAMP,
                check_out_time TIMESTAMP,
                total_hours INTEGER DEFAULT 0,
                total_amount REAL DEFAULT 0.0,
                payment_status TEXT DEFAULT 'pending',
                status TEXT DEFAULT 'active',
                reservation_type TEXT DEFAULT 'checkin',
                no_of_persons INTEGER DEFAULT 1,
                company_name TEXT,
                company_address TEXT,
                party_gstin TEXT,
                registration_no TEXT,
                folio_no TEXT,
                advance_payment REAL DEFAULT 0.0,
                advance_payment_method TEXT,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (room_id) REFERENCES rooms (id),
                FOREIGN KEY (created_by) REFERENCES users (id)
            )
        ''')

        # Advance payments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS advance_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                payment_method TEXT NOT NULL,
                payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                received_by INTEGER,
                notes TEXT,
                FOREIGN KEY (booking_id) REFERENCES bookings (id),
                FOREIGN KEY (received_by) REFERENCES users (id)
            )
        ''')

        # Food orders table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS food_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id INTEGER NOT NULL,
                room_id INTEGER NOT NULL,
                order_number TEXT UNIQUE,
                item_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                total_price REAL NOT NULL,
                gst_percentage REAL DEFAULT 5.0,
                order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                order_time TIME,
                status TEXT DEFAULT 'pending',
                created_by INTEGER,
                notes TEXT,
                FOREIGN KEY (booking_id) REFERENCES bookings (id),
                FOREIGN KEY (room_id) REFERENCES rooms (id),
                FOREIGN KEY (created_by) REFERENCES users (id)
            )
        ''')

        # Bills table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id INTEGER NOT NULL,
                room_id INTEGER NOT NULL,
                bill_number TEXT UNIQUE NOT NULL,
                folio_no TEXT,
                registration_no TEXT,
                bill_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                check_in_time TIMESTAMP NOT NULL,
                check_out_time TIMESTAMP NOT NULL,
                total_hours INTEGER NOT NULL,
                hourly_rate REAL NOT NULL,
                daily_rate REAL NOT NULL,
                room_charges REAL NOT NULL,
                sub_total REAL NOT NULL,
                tax_percentage REAL DEFAULT 5.0,
                tax_amount REAL DEFAULT 0.0,
                cgst_percentage REAL DEFAULT 2.5,
                cgst_amount REAL DEFAULT 0.0,
                sgst_percentage REAL DEFAULT 2.5,
                sgst_amount REAL DEFAULT 0.0,
                discount_percentage REAL DEFAULT 0.0,
                discount_amount REAL DEFAULT 0.0,
                food_total REAL DEFAULT 0.0,
                food_gst_total REAL DEFAULT 0.0,
                total_amount REAL NOT NULL,
                advance_paid REAL DEFAULT 0.0,
                balance_due REAL DEFAULT 0.0,
                payment_method TEXT,
                payment_status TEXT DEFAULT 'pending',
                payment_date DATE,
                notes TEXT,
                verified_by TEXT,
                created_by INTEGER,
                FOREIGN KEY (booking_id) REFERENCES bookings (id),
                FOREIGN KEY (room_id) REFERENCES rooms (id),
                FOREIGN KEY (created_by) REFERENCES users (id)
            )
        ''')

        # Bill adjustments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bill_adjustments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_id INTEGER NOT NULL,
                adjustment_type TEXT NOT NULL,
                amount REAL NOT NULL,
                reason TEXT NOT NULL,
                adjusted_by INTEGER NOT NULL,
                adjusted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (bill_id) REFERENCES bills (id),
                FOREIGN KEY (adjusted_by) REFERENCES users (id)
            )
        ''')

        # Settlements table (corrected schema)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settlements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_id INTEGER NOT NULL,
                settlement_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_amount REAL DEFAULT 0.0,
                paid_amount REAL DEFAULT 0.0,
                discount_amount REAL DEFAULT 0.0,
                balance_amount REAL DEFAULT 0.0,
                payment_method TEXT NOT NULL,
                payment_status TEXT DEFAULT 'settled',
                settled_by INTEGER,
                notes TEXT,
                FOREIGN KEY (bill_id) REFERENCES bills (id),
                FOREIGN KEY (settled_by) REFERENCES users (id)
            )
        ''')

        # Sales summary table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sales_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                total_bookings INTEGER DEFAULT 0,
                total_amount REAL DEFAULT 0.0,
                collected_amount REAL DEFAULT 0.0,
                pending_amount REAL DEFAULT 0.0,
                settlement_amount REAL DEFAULT 0.0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Daily sales breakdown table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_sales_breakdown (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_id INTEGER NOT NULL,
                booking_id INTEGER NOT NULL,
                date DATE NOT NULL,
                day_number INTEGER NOT NULL,
                room_charge REAL DEFAULT 0.0,
                cgst_amount REAL DEFAULT 0.0,
                sgst_amount REAL DEFAULT 0.0,
                food_amount REAL DEFAULT 0.0,
                food_gst REAL DEFAULT 0.0,
                total_amount REAL DEFAULT 0.0,
                FOREIGN KEY (bill_id) REFERENCES bills (id),
                FOREIGN KEY (booking_id) REFERENCES bookings (id)
            )
        ''')

        # Add default admin user if not exists
        admin_hash = self.hash_password('admin123')
        cursor.execute('''
            INSERT OR IGNORE INTO users (username, password_hash, role, email)
            VALUES (?, ?, ?, ?)
        ''', ('admin', admin_hash, 'admin', 'admin@evaanihotel.com'))

        # Add default user if not exists
        user_hash = self.hash_password('user123')
        cursor.execute('''
            INSERT OR IGNORE INTO users (username, password_hash, role, email)
            VALUES (?, ?, ?, ?)
        ''', ('user', user_hash, 'user', 'user@evaanihotel.com'))

        # Add default hotel settings
        cursor.execute('''
            INSERT OR IGNORE INTO hotel_settings (hotel_name, unit, address, phone, gstin)
            VALUES ('THE EVAANI', 'Unit of BY JS HOTELS & FOODS', 'Talwandi Road, Mansa', '9530752236, 9915297440', '03AATFJ9071F1Z3')
        ''')

        conn.commit()
        self.return_connection(conn)

        # Add migration for existing database
        self.migrate_database()

    # Fix the migrate_database method in HotelDatabase class
    def migrate_database(self):
        """Add missing columns to existing tables if needed."""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # Check settlements table schema
            cursor.execute("PRAGMA table_info(settlements)")
            columns = [col[1] for col in cursor.fetchall()]

            # If bill_number exists in settlements, we need to recreate the table
            if 'bill_number' in columns:
                print("Fixing settlements table schema...")

                # Create temporary table with correct schema
                cursor.execute('''
                    CREATE TABLE settlements_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        bill_id INTEGER NOT NULL,
                        settlement_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        total_amount REAL DEFAULT 0.0,
                        paid_amount REAL DEFAULT 0.0,
                        discount_amount REAL DEFAULT 0.0,
                        balance_amount REAL DEFAULT 0.0,
                        payment_method TEXT NOT NULL,
                        payment_status TEXT DEFAULT 'settled',
                        settled_by INTEGER,
                        notes TEXT,
                        FOREIGN KEY (bill_id) REFERENCES bills (id),
                        FOREIGN KEY (settled_by) REFERENCES users (id)
                    )
                ''')

                # Copy data if any exists (without bill_number)
                cursor.execute('''
                    INSERT INTO settlements_new 
                    (id, bill_id, settlement_date, total_amount, paid_amount, 
                     discount_amount, balance_amount, payment_method, 
                     payment_status, settled_by, notes)
                    SELECT id, bill_id, settlement_date, total_amount, paid_amount,
                           discount_amount, balance_amount, payment_method,
                           payment_status, settled_by, notes
                    FROM settlements
                ''')

                # Drop old table and rename new one
                cursor.execute('DROP TABLE settlements')
                cursor.execute('ALTER TABLE settlements_new RENAME TO settlements')

                print("Settlements table schema fixed successfully.")

            # Check and add missing columns to bookings table
            cursor.execute("PRAGMA table_info(bookings)")
            columns = [col[1] for col in cursor.fetchall()]

            if 'guest_id_card' not in columns:
                print("Adding guest_id_card column to bookings table...")
                cursor.execute('ALTER TABLE bookings ADD COLUMN guest_id_card TEXT')

            if 'guest_address' not in columns:
                print("Adding guest_address column to bookings table...")
                cursor.execute('ALTER TABLE bookings ADD COLUMN guest_address TEXT')

            if 'advance_payment' not in columns:
                print("Adding advance_payment column to bookings table...")
                cursor.execute('ALTER TABLE bookings ADD COLUMN advance_payment REAL DEFAULT 0.0')

            if 'advance_payment_method' not in columns:
                print("Adding advance_payment_method column to bookings table...")
                cursor.execute('ALTER TABLE bookings ADD COLUMN advance_payment_method TEXT')

            # Check and add columns to bills table
            cursor.execute("PRAGMA table_info(bills)")
            bill_columns = [col[1] for col in cursor.fetchall()]

            if 'advance_paid' not in bill_columns:
                print("Adding advance_paid column to bills table...")
                cursor.execute('ALTER TABLE bills ADD COLUMN advance_paid REAL DEFAULT 0.0')

            if 'balance_due' not in bill_columns:
                print("Adding balance_due column to bills table...")
                cursor.execute('ALTER TABLE bills ADD COLUMN balance_due REAL DEFAULT 0.0')

            # Check sales_summary table for settlement_amount column
            cursor.execute("PRAGMA table_info(sales_summary)")
            sales_columns = [col[1] for col in cursor.fetchall()]

            if 'settlement_amount' not in sales_columns:
                print("Adding settlement_amount column to sales_summary table...")
                cursor.execute('ALTER TABLE sales_summary ADD COLUMN settlement_amount REAL DEFAULT 0.0')

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
        conn = self.get_connection()
        cursor = conn.cursor()
        password_hash = self.hash_password(password)

        cursor.execute('''
            SELECT id, username, role FROM users
            WHERE username = ? AND password_hash = ?
        ''', (username, password_hash))

        user = cursor.fetchone()
        self.return_connection(conn)

        if user:
            return {'id': user[0], 'username': user[1], 'role': user[2]}
        return None

    def get_hotel_settings(self):
        """Get hotel settings for billing."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM hotel_settings ORDER BY id DESC LIMIT 1')
        settings = cursor.fetchone()
        self.return_connection(conn)
        return dict(settings) if settings else {
            'hotel_name': 'THE EVAANI',
            'unit': 'Unit of BY JS HOTELS & FOODS',
            'address': 'Talwandi Road, Mansa',
            'phone': '9530752236, 9915297440',
            'gstin': '03AATFJ9071F1Z3'
        }

    def update_hotel_settings(self, settings_data):
        """Update hotel settings."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE hotel_settings
            SET hotel_name = ?, unit = ?, address = ?, phone = ?, gstin = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = (SELECT id FROM hotel_settings ORDER BY id DESC LIMIT 1)
        ''', (settings_data['hotel_name'], settings_data['unit'], settings_data['address'],
              settings_data['phone'], settings_data['gstin']))
        conn.commit()
        self.return_connection(conn)

    # User management methods
    def get_all_users(self):
        """Get all users."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, username, role, email, created_at FROM users ORDER BY username')
        users = cursor.fetchall()
        self.return_connection(conn)
        return [dict(user) for user in users]

    def add_user(self, user_data):
        """Add a new user."""
        conn = self.get_connection()
        cursor = conn.cursor()
        password_hash = self.hash_password(user_data['password'])

        cursor.execute('''
            INSERT INTO users (username, password_hash, role, email)
            VALUES (?, ?, ?, ?)
        ''', (user_data['username'], password_hash, user_data['role'], user_data.get('email', '')))

        user_id = cursor.lastrowid
        conn.commit()
        self.return_connection(conn)
        return user_id

    def delete_user(self, user_id):
        """Delete a user."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
        self.return_connection(conn)


# Authentication system
class Authentication:
    def __init__(self, db: HotelDatabase):
        self.db = db
        self.current_user = None

    def login(self, username, password):
        try:
            if not username or not password:
                raise ValueError("Username and password are required")

            user = self.db.verify_user(username, password)
            if user:
                self.current_user = user
                return user
            return None
        except ValueError as e:
            raise

    def logout(self):
        self.current_user = None

    def is_admin(self):
        return self.current_user and self.current_user['role'] == 'admin'

    def is_authenticated(self):
        return self.current_user is not None


# Hotel Billing Management with proper error handling
class HotelBillingManager:
    def __init__(self, db: HotelDatabase, auth: Authentication):
        self.db = db
        self.auth = auth

    # Hotel settings methods
    def get_hotel_settings(self):
        return self.db.get_hotel_settings()

    def update_hotel_settings(self, settings_data):
        self.db.update_hotel_settings(settings_data)

    # Add this to the HotelBillingManager class (around line 1400-1500)

    def admin_edit_bill(self, bill_id: int, edit_data: dict, reason: str):
        """Admin-only function to completely edit a bill with full override.
        Updates bill, booking, and adjusts settlements if needed."""

        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # Start transaction
            cursor.execute("BEGIN TRANSACTION")

            # Get current bill and related data
            cursor.execute('''
                SELECT b.*, bk.room_id as original_room_id, bk.id as booking_id,
                       bk.guest_name, bk.guest_phone, bk.guest_email, bk.guest_id_card,
                       bk.guest_address, bk.company_name, bk.company_address, bk.party_gstin,
                       bk.check_in_time, bk.check_out_time, bk.no_of_persons,
                       bk.registration_no, bk.folio_no, bk.advance_payment,
                       r.room_number, r.price_per_day, r.price_per_hour
                FROM bills b
                JOIN bookings bk ON b.booking_id = bk.id
                JOIN rooms r ON b.room_id = r.id
                WHERE b.id = ?
            ''', (bill_id,))

            current_bill = cursor.fetchone()
            if not current_bill:
                raise ValueError("Bill not found")

            current_bill = dict(current_bill)

            # Parse times
            old_check_in = datetime.fromisoformat(current_bill['check_in_time'])
            old_check_out = datetime.fromisoformat(current_bill['check_out_time'])

            new_check_in = datetime.fromisoformat(
                edit_data['check_in_time']) if 'check_in_time' in edit_data else old_check_in
            new_check_out = datetime.fromisoformat(
                edit_data['check_out_time']) if 'check_out_time' in edit_data else old_check_out

            # Calculate new days based on 12:00 PM policy
            cutoff_time = 12

            if new_check_out.date() == new_check_in.date():
                days = 1
            else:
                check_in_before_12 = new_check_in.hour < cutoff_time or (
                            new_check_in.hour == cutoff_time and new_check_in.minute == 0)

                if check_in_before_12:
                    days = 1
                    current_date = new_check_in.date() + timedelta(days=1)
                else:
                    days = 0
                    current_date = new_check_in.date() + timedelta(days=1)

                while current_date < new_check_out.date():
                    days += 1
                    current_date += timedelta(days=1)

                if new_check_out.hour >= cutoff_time:
                    days += 1

            if days < 1:
                days = 1

            # Get room price - if room changed
            new_room_id = edit_data.get('room_id', current_bill['room_id'])
            if new_room_id != current_bill['room_id']:
                cursor.execute('SELECT price_per_day, price_per_hour, room_number FROM rooms WHERE id = ?',
                               (new_room_id,))
                new_room = cursor.fetchone()
                if not new_room:
                    raise ValueError("New room not found")
                price_per_day = new_room['price_per_day']
                price_per_hour = new_room['price_per_hour']
                new_room_number = new_room['room_number']
            else:
                price_per_day = current_bill['daily_rate']
                price_per_hour = current_bill['hourly_rate']
                new_room_number = current_bill['room_number']

            # Calculate new room charges
            new_room_charges = days * price_per_day

            # Calculate taxes
            cgst_percentage = edit_data.get('cgst_percentage', current_bill['cgst_percentage'])
            sgst_percentage = edit_data.get('sgst_percentage', current_bill['sgst_percentage'])

            new_cgst = new_room_charges * (cgst_percentage / 100)
            new_sgst = new_room_charges * (sgst_percentage / 100)

            # Get food totals (unchanged or edited)
            food_total = edit_data.get('food_total', current_bill['food_total'])
            food_gst_total = edit_data.get('food_gst_total', current_bill['food_gst_total'])

            # Calculate new total
            new_sub_total = new_room_charges
            new_total_before_discount = new_room_charges + new_cgst + new_sgst + food_total + food_gst_total

            discount_percentage = edit_data.get('discount_percentage', current_bill['discount_percentage'])
            discount_amount = new_total_before_discount * (discount_percentage / 100)
            new_total_amount = new_total_before_discount - discount_amount

            # Get advance payment (from booking or edited)
            advance_paid = edit_data.get('advance_paid', current_bill['advance_paid'])

            # Get existing settlements for this bill
            cursor.execute('''
                SELECT SUM(paid_amount) as total_paid, SUM(discount_amount) as total_discount
                FROM settlements
                WHERE bill_id = ?
            ''', (bill_id,))
            settlement_data = cursor.fetchone()

            already_paid = settlement_data['total_paid'] if settlement_data['total_paid'] else 0.0
            already_discounted = settlement_data['total_discount'] if settlement_data['total_discount'] else 0.0

            # Calculate new balance due
            new_balance_due = new_total_amount - advance_paid - already_paid - already_discounted

            # Ensure balance is not negative
            if new_balance_due < 0:
                new_balance_due = 0

            # Determine new payment status
            if new_balance_due <= 0.01:
                new_payment_status = 'paid'
            elif new_balance_due < new_total_amount:
                new_payment_status = 'partial'
            else:
                new_payment_status = 'pending'

            # UPDATE BOOKING TABLE if any booking details changed
            booking_update_fields = []
            booking_update_params = []

            booking_updates = {
                'guest_name': edit_data.get('guest_name'),
                'guest_phone': edit_data.get('guest_phone'),
                'guest_email': edit_data.get('guest_email'),
                'guest_id_card': edit_data.get('guest_id_card'),
                'guest_address': edit_data.get('guest_address'),
                'company_name': edit_data.get('company_name'),
                'company_address': edit_data.get('company_address'),
                'party_gstin': edit_data.get('party_gstin'),
                'no_of_persons': edit_data.get('no_of_persons'),
                'registration_no': edit_data.get('registration_no'),
                'folio_no': edit_data.get('folio_no'),
                'advance_payment': edit_data.get('advance_paid'),  # Update advance payment in booking
            }

            for field, value in booking_updates.items():
                if value is not None:
                    booking_update_fields.append(f"{field} = ?")
                    booking_update_params.append(value)

            # Always update check-in/out times if changed
            if 'check_in_time' in edit_data:
                booking_update_fields.append("check_in_time = ?")
                booking_update_params.append(edit_data['check_in_time'])

            if 'check_out_time' in edit_data:
                booking_update_fields.append("check_out_time = ?")
                booking_update_params.append(edit_data['check_out_time'])

            # Update room if changed
            if new_room_id != current_bill['room_id']:
                booking_update_fields.append("room_id = ?")
                booking_update_params.append(new_room_id)

            if booking_update_fields:
                booking_update_params.append(current_bill['booking_id'])
                cursor.execute(f'''
                    UPDATE bookings
                    SET {', '.join(booking_update_fields)}
                    WHERE id = ?
                ''', booking_update_params)

            # UPDATE BILL TABLE with all new values
            bill_update_data = {
                'room_id': new_room_id,
                'bill_number': edit_data.get('bill_number', current_bill['bill_number']),
                'folio_no': edit_data.get('folio_no', current_bill['folio_no']),
                'registration_no': edit_data.get('registration_no', current_bill['registration_no']),
                'check_in_time': edit_data.get('check_in_time', current_bill['check_in_time']),
                'check_out_time': edit_data.get('check_out_time', current_bill['check_out_time']),
                'total_hours': days * 24,
                'hourly_rate': price_per_hour,
                'daily_rate': price_per_day,
                'room_charges': new_room_charges,
                'sub_total': new_sub_total,
                'tax_percentage': cgst_percentage + sgst_percentage,
                'tax_amount': new_cgst + new_sgst,
                'cgst_percentage': cgst_percentage,
                'cgst_amount': new_cgst,
                'sgst_percentage': sgst_percentage,
                'sgst_amount': new_sgst,
                'discount_percentage': discount_percentage,
                'discount_amount': discount_amount,
                'food_total': food_total,
                'food_gst_total': food_gst_total,
                'total_amount': new_total_amount,
                'advance_paid': advance_paid,
                'balance_due': new_balance_due,
                'payment_method': edit_data.get('payment_method', current_bill['payment_method']),
                'payment_status': new_payment_status,
                'payment_date': edit_data.get('payment_date', current_bill['payment_date']),
                'notes': edit_data.get('notes', current_bill['notes']),
                'verified_by': edit_data.get('verified_by',
                                             self.auth.current_user['username'] if self.auth.current_user else
                                             current_bill['verified_by'])
            }

            set_clause = []
            params = []
            for key, value in bill_update_data.items():
                set_clause.append(f"{key} = ?")
                params.append(value)

            params.append(bill_id)

            cursor.execute(f'''
                UPDATE bills
                SET {', '.join(set_clause)}
                WHERE id = ?
            ''', params)

            # Log the edit in bill_adjustments table
            cursor.execute('''
                INSERT INTO bill_adjustments
                (bill_id, adjustment_type, amount, reason, adjusted_by)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                bill_id,
                'admin_edit',
                new_total_amount - current_bill['total_amount'],
                f"ADMIN EDIT: {reason}",
                self.auth.current_user['id'] if self.auth.current_user else None
            ))

            # Update or recreate daily_sales_breakdown
            cursor.execute('DELETE FROM daily_sales_breakdown WHERE bill_id = ?', (bill_id,))

            # Create new day breakdowns
            current_date = new_check_in.date()
            day_number = 1

            daily_room_charge = price_per_day
            daily_cgst = daily_room_charge * (cgst_percentage / 100)
            daily_sgst = daily_room_charge * (sgst_percentage / 100)

            while day_number <= days:
                cursor.execute('''
                    INSERT INTO daily_sales_breakdown
                    (bill_id, booking_id, date, day_number, room_charge,
                     cgst_amount, sgst_amount, total_amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    bill_id,
                    current_bill['booking_id'],
                    current_date.strftime('%Y-%m-%d'),
                    day_number,
                    daily_room_charge,
                    daily_cgst,
                    daily_sgst,
                    daily_room_charge + daily_cgst + daily_sgst
                ))

                current_date += timedelta(days=1)
                day_number += 1

            # Update room status if room changed
            if new_room_id != current_bill['room_id']:
                # Old room becomes available/housekeeping
                cursor.execute('UPDATE rooms SET status = "housekeeping" WHERE id = ?', (current_bill['room_id'],))
                # New room becomes occupied if still active? (but bill is already generated, so likely checkout done)
                # For now, leave as is - admin can manually update room status if needed

            # Update sales summary - we need to adjust for the date change
            old_date = datetime.fromisoformat(current_bill['bill_date']).date().isoformat()
            new_date = datetime.now().date().isoformat()  # Use current date for edit

            # Adjust old date summary (reduce)
            cursor.execute('SELECT * FROM sales_summary WHERE date = ?', (old_date,))
            old_summary = cursor.fetchone()
            if old_summary:
                cursor.execute('''
                    UPDATE sales_summary
                    SET total_amount = total_amount - ?,
                        collected_amount = collected_amount - ?,
                        pending_amount = pending_amount - ?
                    WHERE date = ?
                ''', (
                    current_bill['total_amount'],
                    current_bill['advance_paid'] + already_paid,
                    current_bill['balance_due'],
                    old_date
                ))

            # Add to new date summary
            cursor.execute('SELECT * FROM sales_summary WHERE date = ?', (new_date,))
            new_summary = cursor.fetchone()

            if new_summary:
                cursor.execute('''
                    UPDATE sales_summary
                    SET total_amount = total_amount + ?,
                        collected_amount = collected_amount + ?,
                        pending_amount = pending_amount + ?
                    WHERE date = ?
                ''', (
                    new_total_amount,
                    advance_paid + already_paid,
                    new_balance_due,
                    new_date
                ))
            else:
                cursor.execute('''
                    INSERT INTO sales_summary
                    (date, total_bookings, total_amount, collected_amount, pending_amount, settlement_amount)
                    VALUES (?, 1, ?, ?, ?, 0)
                ''', (
                    new_date,
                    new_total_amount,
                    advance_paid + already_paid,
                    new_balance_due
                ))

            # Commit all changes
            conn.commit()

            return {
                'bill_id': bill_id,
                'bill_number': bill_update_data['bill_number'],
                'old_total': current_bill['total_amount'],
                'new_total': new_total_amount,
                'old_balance': current_bill['balance_due'],
                'new_balance': new_balance_due,
                'room_changed': new_room_id != current_bill['room_id'],
                'new_room_number': new_room_number
            }

        except Exception as e:
            conn.rollback()
            raise ValueError(f"Error editing bill: {str(e)}")
        finally:
            self.db.return_connection(conn)

    # Add this method to get all rooms for selection in edit dialog
    def get_all_rooms_simple(self):
        """Get simple list of all rooms for dropdown."""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, room_number, room_type FROM rooms ORDER BY room_number')
        rooms = cursor.fetchall()
        self.db.return_connection(conn)
        return [dict(room) for room in rooms]

    # Room management methods
    def add_room(self, room_data: dict):
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO rooms
                (room_number, room_type, price_per_hour, price_per_day, status,
                 description, amenities, max_occupancy)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                room_data['room_number'],
                room_data['room_type'],
                room_data['price_per_hour'],
                room_data['price_per_day'],
                room_data.get('status', 'available'),
                room_data.get('description', ''),
                room_data.get('amenities', ''),
                room_data.get('max_occupancy', 2)
            ))

            room_id = cursor.lastrowid
            conn.commit()
            return room_id
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e) and "room_number" in str(e):
                raise ValueError("Room number already exists")
            raise ValueError("Database error: " + str(e))
        except Exception as e:
            raise ValueError("Error adding room: " + str(e))
        finally:
            self.db.return_connection(conn)

    def update_room_status(self, room_id: int, status: str, reason: str = ""):
        """Update room status and log the change."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('UPDATE rooms SET status = ? WHERE id = ?', (status, room_id))

            # Log status change
            cursor.execute('''
                INSERT INTO room_status_history (room_id, status, changed_by, reason)
                VALUES (?, ?, ?, ?)
            ''', (room_id, status, self.auth.current_user['id'] if self.auth.current_user else None, reason))

            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise ValueError(f"Error updating room status: {str(e)}")
        finally:
            self.db.return_connection(conn)

    def update_room(self, room_id: int, update_data: dict):
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # Build update query
            set_clause = []
            params = []

            for key, value in update_data.items():
                if key in ['room_number', 'room_type', 'status', 'description', 'amenities']:
                    set_clause.append(f"{key} = ?")
                    params.append(str(value).strip())
                elif key in ['price_per_hour', 'price_per_day']:
                    set_clause.append(f"{key} = ?")
                    params.append(float(value))
                elif key == 'max_occupancy':
                    set_clause.append(f"{key} = ?")
                    params.append(int(value))

            params.append(room_id)

            if set_clause:
                cursor.execute(f'''
                    UPDATE rooms
                    SET {', '.join(set_clause)}
                    WHERE id = ?
                ''', params)

                conn.commit()
                return True
            return False
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e) and "room_number" in str(e):
                raise ValueError("Room number already exists")
            raise ValueError("Database error: " + str(e))
        except Exception as e:
            raise ValueError("Error updating room: " + str(e))
        finally:
            self.db.return_connection(conn)

    def delete_room(self, room_id: int):
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # Check if room has active bookings or reservations
            cursor.execute('''
                SELECT COUNT(*) FROM bookings
                WHERE room_id = ? AND status IN ("active", "reserved")
            ''', (room_id,))
            active_bookings = cursor.fetchone()[0]

            if active_bookings > 0:
                raise ValueError("Cannot delete room with active bookings or reservations")

            cursor.execute('DELETE FROM rooms WHERE id = ?', (room_id,))
            conn.commit()
            return True
        except Exception as e:
            raise ValueError("Error deleting room: " + str(e))
        finally:
            self.db.return_connection(conn)

    def get_all_rooms(self):
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # First get all rooms
        cursor.execute('SELECT * FROM rooms ORDER BY room_number')
        rooms = cursor.fetchall()

        # Check reservation status for each room
        room_list = []
        today = datetime.now().date().isoformat()

        for room in rooms:
            room_dict = dict(room)

            # Check if room has any future reservations
            cursor.execute('''
                SELECT COUNT(*) as reservation_count
                FROM bookings
                WHERE room_id = ?
                AND status = 'reserved'
                AND check_in_date > ?
            ''', (room_dict['id'], today))

            result = cursor.fetchone()
            if result and result['reservation_count'] > 0:
                room_dict['status'] = 'reserved_future'

            # Check if room has reservations today
            cursor.execute('''
                SELECT COUNT(*) as today_reservation
                FROM bookings
                WHERE room_id = ?
                AND status = 'reserved'
                AND check_in_date <= ?
                AND check_out_date > ?
            ''', (room_dict['id'], today, today))

            result_today = cursor.fetchone()
            if result_today and result_today['today_reservation'] > 0:
                room_dict['status'] = 'reserved_today'

            room_list.append(room_dict)

        self.db.return_connection(conn)
        return room_list

    def get_room_status_counts(self):
        """Get counts of rooms by status."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT
                SUM(CASE WHEN status = 'available' THEN 1 ELSE 0 END) as available,
                SUM(CASE WHEN status = 'occupied' THEN 1 ELSE 0 END) as occupied,
                SUM(CASE WHEN status = 'reserved' THEN 1 ELSE 0 END) as reserved,
                SUM(CASE WHEN status = 'housekeeping' THEN 1 ELSE 0 END) as housekeeping,
                SUM(CASE WHEN status = 'underprocess' THEN 1 ELSE 0 END) as underprocess
            FROM rooms
        ''')

        counts = cursor.fetchone()
        self.db.return_connection(conn)
        return dict(counts) if counts else {
            'available': 0, 'occupied': 0, 'reserved': 0,
            'housekeeping': 0, 'underprocess': 0
        }

    def get_available_rooms(self, check_in_date=None, check_out_date=None):
        """Get rooms available for a specific date range (for reservations)"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            if check_in_date and check_out_date:
                # Check for room availability for specific dates
                cursor.execute('''
                    SELECT r.* FROM rooms r
                    WHERE r.status IN ('available', 'reserved', 'housekeeping', 'underprocess')
                    AND r.id NOT IN (
                        SELECT b.room_id FROM bookings b
                        WHERE b.status IN ('active', 'reserved')
                        AND (
                            (DATE(b.check_in_date) <= ? AND DATE(b.check_out_date) > ?) OR
                            (DATE(b.check_in_date) < ? AND DATE(b.check_out_date) >= ?) OR
                            (DATE(b.check_in_date) >= ? AND DATE(b.check_out_date) <= ?)
                        )
                    )
                    ORDER BY r.room_number
                ''', (check_in_date, check_in_date, check_out_date, check_out_date,
                      check_in_date, check_out_date))
            else:
                # Get all rooms that are not currently occupied
                cursor.execute('''
                    SELECT r.* FROM rooms r
                    WHERE r.status IN ('available', 'housekeeping', 'underprocess')
                    AND r.id NOT IN (
                        SELECT room_id FROM bookings
                        WHERE status = 'active'
                    )
                    ORDER BY r.room_number
                ''')

            rooms = cursor.fetchall()
            return [dict(room) for room in rooms]
        finally:
            self.db.return_connection(conn)

    def get_room_by_id(self, room_id: int):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM rooms WHERE id = ?', (room_id,))
        room = cursor.fetchone()
        self.db.return_connection(conn)
        return dict(room) if room else None

    def get_room_by_number(self, room_number: str):
        """Get room by room number"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM rooms WHERE room_number = ?', (room_number,))
        room = cursor.fetchone()
        self.db.return_connection(conn)
        return dict(room) if room else None

    # Get guest by ID card
    def get_guest_by_id_card(self, id_card):
        """Get guest information by ID card number."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT guest_name, guest_phone, guest_email, guest_address, company_name,
                   company_address, party_gstin
            FROM bookings
            WHERE guest_id_card = ?
            ORDER BY created_at DESC
            LIMIT 1
        ''', (id_card,))

        guest = cursor.fetchone()
        self.db.return_connection(conn)
        return dict(guest) if guest else None

    # Booking management methods with reservation support
    def create_booking(self, booking_data: dict):
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # Always set check_in_time for all bookings
            check_in_time = booking_data.get('check_in_time', datetime.now().isoformat())

            # Generate folio and registration numbers
            folio_no = booking_data.get('folio_no', f"F{datetime.now().strftime('%Y%m%d%H%M%S')}")
            registration_no = booking_data.get('registration_no', f"R{datetime.now().strftime('%Y%m%d%H%M%S')}")

            # For reservations
            if booking_data.get('reservation_type') == 'reservation':
                check_in_date = booking_data['check_in_date']
                check_out_date = booking_data['check_out_date']

                # Check if room is available for these dates
                cursor.execute('''
                    SELECT COUNT(*) FROM bookings
                    WHERE room_id = ?
                    AND status IN ('active', 'reserved')
                    AND NOT (
                        DATE(check_out_date) <= ? OR
                        DATE(check_in_date) >= ?
                    )
                ''', (booking_data['room_id'], check_in_date, check_out_date))

                conflicting_bookings = cursor.fetchone()[0]

                if conflicting_bookings > 0:
                    raise ValueError("Room is not available for the selected dates")

                # Create reservation
                cursor.execute('''
                    INSERT INTO bookings
                    (room_id, guest_name, guest_phone, guest_email, guest_id_card, guest_address,
                     check_in_date, check_out_date, check_in_time,
                     reservation_type, created_by, status, no_of_persons,
                     company_name, company_address, party_gstin, registration_no, folio_no,
                     advance_payment, advance_payment_method)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    booking_data['room_id'],
                    booking_data['guest_name'],
                    booking_data.get('guest_phone', ''),
                    booking_data.get('guest_email', ''),
                    booking_data.get('guest_id_card', ''),
                    booking_data.get('guest_address', ''),
                    check_in_date,
                    check_out_date,
                    check_in_time,
                    'reservation',
                    self.auth.current_user['id'],
                    'reserved',
                    booking_data.get('no_of_persons', 1),
                    booking_data.get('company_name', ''),
                    booking_data.get('company_address', ''),
                    booking_data.get('party_gstin', ''),
                    registration_no,
                    folio_no,
                    booking_data.get('advance_payment', 0.0),
                    booking_data.get('advance_payment_method', '')
                ))
            else:
                # Regular check-in (immediate occupancy)
                # Check if room is available
                cursor.execute('SELECT status FROM rooms WHERE id = ?', (booking_data['room_id'],))
                room = cursor.fetchone()

                if not room:
                    raise ValueError("Room not found")

                # Check if room has reservation for today or within next 5 days
                today = datetime.now().date().isoformat()
                five_days_later = (datetime.now().date() + timedelta(days=5)).isoformat()

                cursor.execute('''
                    SELECT b.*, r.room_number
                    FROM bookings b
                    JOIN rooms r ON b.room_id = r.id
                    WHERE b.room_id = ?
                    AND b.status = 'reserved'
                    AND DATE(b.check_in_date) BETWEEN ? AND ?
                ''', (booking_data['room_id'], today, five_days_later))

                upcoming_reservations = cursor.fetchall()

                if upcoming_reservations:
                    res = dict(upcoming_reservations[0])
                    days_until = (
                                datetime.strptime(res['check_in_date'], '%Y-%m-%d').date() - datetime.now().date()).days

                    warning_message = f"⚠️ WARNING: This room is RESERVED!\n\n"
                    warning_message += f"Guest: {res['guest_name']}\n"
                    warning_message += f"Reservation Date: {res['check_in_date']}\n"

                    if days_until == 0:
                        warning_message += f"\n❌ RESERVATION IS FOR TODAY!\nPlease contact guest before allocating."
                    elif days_until <= 5:
                        warning_message += f"\n⚠️ Reservation is in {days_until} days!\nOnly {days_until} days remaining before guest arrives."

                    if not self.ask_confirmation_callback(
                            warning_message + "\n\nDo you still want to allocate this room?"):
                        raise ValueError("Room allocation cancelled due to upcoming reservation")

                if room['status'] not in ['available', 'housekeeping', 'underprocess']:
                    raise ValueError("Room is not available")

                # Create booking with check-in time
                cursor.execute('''
                    INSERT INTO bookings
                    (room_id, guest_name, guest_phone, guest_email, guest_id_card, guest_address,
                     check_in_time, check_in_date, check_out_date, created_by, status, reservation_type,
                     no_of_persons, company_name, company_address, party_gstin, registration_no, folio_no,
                     advance_payment, advance_payment_method)
                    VALUES (?, ?, ?, ?, ?, ?, ?, DATE(?), DATE(?), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    booking_data['room_id'],
                    booking_data['guest_name'],
                    booking_data.get('guest_phone', ''),
                    booking_data.get('guest_email', ''),
                    booking_data.get('guest_id_card', ''),
                    booking_data.get('guest_address', ''),
                    check_in_time,
                    check_in_time[:10],  # Get date part
                    check_in_time[:10],  # Will be updated on check-out
                    self.auth.current_user['id'],
                    'active',
                    'checkin',
                    booking_data.get('no_of_persons', 1),
                    booking_data.get('company_name', ''),
                    booking_data.get('company_address', ''),
                    booking_data.get('party_gstin', ''),
                    registration_no,
                    folio_no,
                    booking_data.get('advance_payment', 0.0),
                    booking_data.get('advance_payment_method', '')
                ))

                # Update room status to occupied
                cursor.execute('UPDATE rooms SET status = "occupied" WHERE id = ?', (booking_data['room_id'],))

                # Record advance payment if any
                advance_amount = booking_data.get('advance_payment', 0.0)
                if advance_amount > 0:
                    cursor.execute('''
                        INSERT INTO advance_payments
                        (booking_id, amount, payment_method, received_by, notes)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (
                        cursor.lastrowid,
                        advance_amount,
                        booking_data.get('advance_payment_method', 'cash'),
                        self.auth.current_user['id'],
                        'Advance payment at check-in'
                    ))

            booking_id = cursor.lastrowid
            conn.commit()
            return booking_id
        except Exception as e:
            conn.rollback()
            raise ValueError("Error creating booking: " + str(e))
        finally:
            self.db.return_connection(conn)

    def ask_confirmation_callback(self, message):
        """Callback for confirmation dialog - will be overridden in GUI"""
        return True

    def update_booking(self, booking_id: int, update_data: dict):
        """Update booking details (check-in/out times, guest info, etc.)"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            set_clause = []
            params = []

            for key, value in update_data.items():
                if key in ['guest_name', 'guest_phone', 'guest_email', 'guest_id_card', 'guest_address',
                           'company_name', 'company_address', 'party_gstin', 'registration_no', 'folio_no']:
                    set_clause.append(f"{key} = ?")
                    params.append(str(value).strip())
                elif key in ['check_in_time', 'check_out_time']:
                    set_clause.append(f"{key} = ?")
                    params.append(value)
                elif key == 'no_of_persons':
                    set_clause.append(f"{key} = ?")
                    params.append(int(value))

            params.append(booking_id)

            if set_clause:
                cursor.execute(f'''
                    UPDATE bookings
                    SET {', '.join(set_clause)}
                    WHERE id = ?
                ''', params)

                conn.commit()
                return True
            return False
        except Exception as e:
            conn.rollback()
            raise ValueError(f"Error updating booking: {str(e)}")
        finally:
            self.db.return_connection(conn)

    # Checkout method with 12:00 to 12:00 cycle
    def checkout_booking(self, booking_id: int, check_out_time: str):
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # Get booking details
            cursor.execute('''
                SELECT b.*, r.price_per_hour, r.price_per_day, r.id as room_id
                FROM bookings b
                JOIN rooms r ON b.room_id = r.id
                WHERE b.id = ?
            ''', (booking_id,))
            booking = cursor.fetchone()

            if not booking:
                raise ValueError("Booking not found")

            booking = dict(booking)

            # Parse times
            check_in_time = datetime.fromisoformat(booking['check_in_time'])
            check_out_time_dt = datetime.fromisoformat(check_out_time)

            # Calculate days based on 12:00 PM to 12:00 PM billing cycle
            cutoff_time = 12  # 12:00 PM

            # Get check-in date and time
            check_in_date = check_in_time.date()
            check_in_hour = check_in_time.hour
            check_in_minute = check_in_time.minute

            # Calculate number of days
            days = 0

            # Case 1: Same day checkout
            if check_out_time_dt.date() == check_in_date:
                # Same day checkout - charge 1 day (full day rate)
                days = 1
            else:
                # Different day checkout
                # Determine if check-in was before or after 12 PM
                check_in_before_12 = check_in_hour < cutoff_time or (
                            check_in_hour == cutoff_time and check_in_minute == 0)

                if check_in_before_12:
                    # Checked in before/at 12 PM - count from today
                    days = 1
                    current_date = check_in_date + timedelta(days=1)
                else:
                    # Checked in after 12 PM - first day starts tomorrow
                    days = 0
                    current_date = check_in_date + timedelta(days=1)

                # Count full days between current_date and check-out date
                while current_date < check_out_time_dt.date():
                    days += 1
                    current_date += timedelta(days=1)

                # Check if checkout time is after 12 PM on the last day
                if check_out_time_dt.hour >= cutoff_time:
                    days += 1

            # Ensure at least 1 day
            if days < 1:
                days = 1

            # Calculate total amount (full days only - no hourly rates)
            total_amount = days * booking['price_per_day']

            # Update booking
            cursor.execute('''
                UPDATE bookings
                SET check_out_time = ?, total_hours = ?, total_amount = ?, status = "completed"
                WHERE id = ?
            ''', (check_out_time, days * 24, total_amount, booking_id))

            # Update room status to housekeeping
            cursor.execute('UPDATE rooms SET status = "housekeeping" WHERE id = ?', (booking['room_id'],))

            conn.commit()
            return days, total_amount, check_in_time, check_out_time_dt
        except Exception as e:
            conn.rollback()
            raise ValueError("Error during checkout: " + str(e))
        finally:
            self.db.return_connection(conn)

    # Generate bill with day-wise breakdown
    def generate_bill(self, booking_id: int, bill_data: dict):
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # Get booking details
            cursor.execute('''
                SELECT b.*, r.price_per_hour, r.price_per_day, r.room_number, r.id as room_id
                FROM bookings b
                JOIN rooms r ON b.room_id = r.id
                WHERE b.id = ?
            ''', (booking_id,))
            booking = cursor.fetchone()

            if not booking:
                raise ValueError("Booking not found")

            booking = dict(booking)

            # Get advance payment
            advance_paid = booking.get('advance_payment', 0.0)

            # Parse times
            check_in_time = datetime.fromisoformat(booking['check_in_time'])
            check_out_time = datetime.fromisoformat(bill_data['check_out_time'])

            # Calculate days based on 12:00 PM to 12:00 PM billing cycle
            cutoff_time = 12

            check_in_date = check_in_time.date()
            check_in_hour = check_in_time.hour
            check_in_minute = check_in_time.minute

            # Calculate number of days
            days = 0

            if check_out_time.date() == check_in_date:
                days = 1
            else:
                check_in_before_12 = check_in_hour < cutoff_time or (
                        check_in_hour == cutoff_time and check_in_minute == 0)

                if check_in_before_12:
                    days = 1
                    current_date = check_in_date + timedelta(days=1)
                else:
                    days = 0
                    current_date = check_in_date + timedelta(days=1)

                while current_date < check_out_time.date():
                    days += 1
                    current_date += timedelta(days=1)

                if check_out_time.hour >= cutoff_time:
                    days += 1

            if days < 1:
                days = 1

            room_charges = days * booking['price_per_day']

            # Calculate per-day breakdown - FIXED: Proper calculation
            day_breakdowns = []
            current_date = check_in_date
            day_number = 1

            # Daily room charge
            daily_room_charge = booking['price_per_day']

            # Daily CGST and SGST
            daily_cgst = daily_room_charge * (bill_data.get('cgst_percentage', 2.5) / 100)
            daily_sgst = daily_room_charge * (bill_data.get('sgst_percentage', 2.5) / 100)

            # For each day, add the same amounts (since it's per day rate)
            while day_number <= days:
                day_breakdowns.append({
                    'date': current_date.strftime('%Y-%m-%d'),
                    'day_number': day_number,
                    'room_charge': daily_room_charge,
                    'cgst_amount': daily_cgst,
                    'sgst_amount': daily_sgst,
                    'total': daily_room_charge + daily_cgst + daily_sgst
                })

                current_date += timedelta(days=1)
                day_number += 1

            # Get food orders for this booking
            cursor.execute('''
                SELECT SUM(total_price) as food_total,
                       SUM(total_price * gst_percentage / 100) as food_gst_total
                FROM food_orders
                WHERE booking_id = ?
            ''', (booking_id,))

            food_totals = cursor.fetchone()
            food_total = food_totals['food_total'] or 0.0
            food_gst_total = food_totals['food_gst_total'] or 0.0

            # Calculate taxes
            cgst_percentage = bill_data.get('cgst_percentage', 2.5)
            sgst_percentage = bill_data.get('sgst_percentage', 2.5)

            room_cgst = room_charges * (cgst_percentage / 100)
            room_sgst = room_charges * (sgst_percentage / 100)

            sub_total = room_charges
            total_amount = room_charges + room_cgst + room_sgst + food_total + food_gst_total

            # Apply discount
            discount_percentage = bill_data.get('discount_percentage', 0.0)
            discount_amount = total_amount * (discount_percentage / 100)
            total_amount -= discount_amount

            # Calculate balance due after advance
            balance_due = total_amount - advance_paid

            # Generate bill number
            bill_number = f"MB{datetime.now().strftime('%Y%m%d%H%M%S')}"

            # Insert bill record
            cursor.execute('''
                INSERT INTO bills
                (booking_id, room_id, bill_number, folio_no, registration_no, bill_date,
                 check_in_time, check_out_time, total_hours, hourly_rate, daily_rate,
                 room_charges, sub_total, tax_percentage, tax_amount,
                 cgst_percentage, cgst_amount, sgst_percentage, sgst_amount,
                 discount_percentage, discount_amount, food_total, food_gst_total,
                 total_amount, advance_paid, balance_due, payment_method, payment_status, payment_date,
                 notes, verified_by, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                booking_id,
                booking['room_id'],
                bill_number,
                booking.get('folio_no', ''),
                booking.get('registration_no', ''),
                datetime.now().isoformat(),
                booking['check_in_time'],
                bill_data['check_out_time'],
                days * 24,
                booking['price_per_hour'],
                booking['price_per_day'],
                room_charges,
                sub_total,
                cgst_percentage + sgst_percentage,
                room_cgst + room_sgst,
                cgst_percentage,
                room_cgst,
                sgst_percentage,
                room_sgst,
                discount_percentage,
                discount_amount,
                food_total,
                food_gst_total,
                total_amount,
                advance_paid,
                balance_due,
                bill_data.get('payment_method', 'cash'),
                'pending' if balance_due > 0 else 'paid',
                datetime.now().date().isoformat(),
                bill_data.get('notes', ''),
                bill_data.get('verified_by', ''),
                self.auth.current_user['id']
            ))

            bill_id = cursor.lastrowid

            # Insert day breakdowns
            for day in day_breakdowns:
                cursor.execute('''
                    INSERT INTO daily_sales_breakdown
                    (bill_id, booking_id, date, day_number, room_charge,
                     cgst_amount, sgst_amount, total_amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    bill_id,
                    booking_id,
                    day['date'],
                    day['day_number'],
                    day['room_charge'],
                    day['cgst_amount'],
                    day['sgst_amount'],
                    day['total']
                ))

            # Update booking payment status
            cursor.execute('''
                UPDATE bookings
                SET payment_status = ?, total_amount = ?, status = 'completed',
                    check_out_time = ?
                WHERE id = ?
            ''', ('paid' if balance_due <= 0 else 'pending', total_amount,
                  bill_data['check_out_time'], booking_id))

            # Update room status
            cursor.execute('UPDATE rooms SET status = "housekeeping" WHERE id = ?', (booking['room_id'],))

            # Update sales summary on checkout date
            self.update_sales_summary(cursor, check_out_time.date().isoformat(),
                                      total_amount, 'pending' if balance_due > 0 else 'paid')

            conn.commit()
            return bill_id, bill_number, total_amount, advance_paid, balance_due, day_breakdowns

        except Exception as e:
            conn.rollback()
            raise ValueError("Error generating bill: " + str(e))
        finally:
            self.db.return_connection(conn)

    # Settlement method
    def settle_bill(self, bill_id: int, settlement_data: dict):
        """Process bill settlement with partial payment/discount."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # Get current bill
            cursor.execute('SELECT * FROM bills WHERE id = ?', (bill_id,))
            bill = cursor.fetchone()

            if not bill:
                raise ValueError("Bill not found")

            bill = dict(bill)

            paid_amount = settlement_data.get('paid_amount', bill['total_amount'])
            discount_amount = settlement_data.get('discount_amount', 0.0)

            # Calculate balance after settlement
            balance_amount = bill['balance_due'] - paid_amount - discount_amount

            if balance_amount < -0.01:  # Allow small rounding errors
                raise ValueError(
                    f"Paid amount + discount ({paid_amount + discount_amount:.2f}) cannot exceed balance due ({bill['balance_due']:.2f})")

            # Ensure balance_amount is not negative
            if balance_amount < 0:
                balance_amount = 0

            # Insert settlement record - FIXED: Using correct columns
            cursor.execute('''
                INSERT INTO settlements
                (bill_id, total_amount, paid_amount, discount_amount, balance_amount,
                 payment_method, payment_status, settled_by, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                bill_id,
                bill['total_amount'],
                paid_amount,
                discount_amount,
                balance_amount,
                settlement_data.get('payment_method', 'cash'),
                'settled' if balance_amount == 0 else 'partial',
                self.auth.current_user['id'],
                settlement_data.get('notes', '')
            ))

            settlement_id = cursor.lastrowid

            # Update bill
            new_balance = balance_amount
            new_payment_status = 'settled' if new_balance == 0 else 'partial'

            cursor.execute('''
                UPDATE bills
                SET payment_status = ?,
                    balance_due = ?,
                    payment_method = ?
                WHERE id = ?
            ''', (
                new_payment_status,
                new_balance,
                settlement_data.get('payment_method', 'cash'),
                bill_id
            ))

            # Update sales summary - add the collected amount
            self.update_sales_summary_settlement(cursor,
                                                 datetime.now().date().isoformat(),
                                                 paid_amount)

            conn.commit()
            return {
                'settlement_id': settlement_id,
                'total_amount': bill['total_amount'],
                'paid_amount': paid_amount,
                'discount_amount': discount_amount,
                'balance_amount': balance_amount
            }

        except Exception as e:
            conn.rollback()
            raise ValueError(f"Error settling bill: {str(e)}")
        finally:
            self.db.return_connection(conn)

    def update_sales_summary_settlement(self, cursor, date_str: str, amount: float):
        """Update sales summary with settlement amount."""
        cursor.execute('SELECT * FROM sales_summary WHERE date = ?', (date_str,))
        summary = cursor.fetchone()

        if summary:
            cursor.execute('''
                UPDATE sales_summary
                SET collected_amount = collected_amount + ?,
                    settlement_amount = settlement_amount + ?,
                    pending_amount = pending_amount - ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE date = ?
            ''', (amount, amount, amount, date_str))
        else:
            cursor.execute('''
                INSERT INTO sales_summary
                (date, total_bookings, total_amount, collected_amount, pending_amount, settlement_amount)
                VALUES (?, 0, 0, ?, 0, ?)
            ''', (date_str, amount, amount))

    def update_sales_summary(self, cursor, date_str: str, amount: float, payment_status: str):
        """Update sales summary - called during bill generation"""
        cursor.execute('SELECT * FROM sales_summary WHERE date = ?', (date_str,))
        summary = cursor.fetchone()

        if summary:
            cursor.execute('''
                UPDATE sales_summary
                SET total_bookings = total_bookings + 1,
                    total_amount = total_amount + ?,
                    collected_amount = collected_amount + CASE WHEN ? = "paid" THEN ? ELSE 0 END,
                    pending_amount = pending_amount + CASE WHEN ? = "pending" THEN ? ELSE 0 END,
                    settlement_amount = settlement_amount + 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE date = ?
            ''', (amount, payment_status, amount, payment_status, amount, date_str))
        else:
            cursor.execute('''
                INSERT INTO sales_summary
                (date, total_bookings, total_amount, collected_amount, pending_amount, settlement_amount)
                VALUES (?, 1, ?, ?, ?, 0)
            ''', (date_str, amount, amount if payment_status == 'paid' else 0,
                  amount if payment_status == 'pending' else 0))

    def get_daily_breakdown(self, bill_id: int):
        """Get daily breakdown for a bill."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM daily_sales_breakdown
            WHERE bill_id = ?
            ORDER BY day_number
        ''', (bill_id,))

        breakdown = cursor.fetchall()
        self.db.return_connection(conn)
        return [dict(day) for day in breakdown]

    def get_pending_settlements(self):
        """Get bills pending settlement (where balance_due > 0)."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT b.*, r.room_number, bk.guest_name, bk.guest_phone
            FROM bills b
            JOIN rooms r ON b.room_id = r.id
            JOIN bookings bk ON b.booking_id = bk.id
            WHERE b.balance_due > 0 AND b.balance_due IS NOT NULL
            ORDER BY b.bill_date DESC
        ''')

        bills = cursor.fetchall()
        self.db.return_connection(conn)
        return [dict(bill) for bill in bills]

    # Food order methods
    def add_food_order(self, order_data: dict):
        """Add a food order for a booking."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # Generate order number
            order_number = f"FOOD-{datetime.now().strftime('%Y%m%d%H%M%S')}"

            total_price = order_data['quantity'] * order_data['unit_price']

            cursor.execute('''
                INSERT INTO food_orders
                (booking_id, room_id, order_number, item_name, quantity, unit_price,
                 total_price, gst_percentage, order_time, created_by, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                order_data['booking_id'],
                order_data['room_id'],
                order_number,
                order_data['item_name'],
                order_data['quantity'],
                order_data['unit_price'],
                total_price,
                order_data.get('gst_percentage', 5.0),
                datetime.now().strftime('%H:%M:%S'),
                self.auth.current_user['id'],
                order_data.get('notes', '')
            ))

            order_id = cursor.lastrowid
            conn.commit()
            return order_id, order_number
        except Exception as e:
            conn.rollback()
            raise ValueError(f"Error adding food order: {str(e)}")
        finally:
            self.db.return_connection(conn)

    def get_food_orders_for_booking(self, booking_id: int):
        """Get all food orders for a booking."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT fo.*, u.username as created_by_name
            FROM food_orders fo
            LEFT JOIN users u ON fo.created_by = u.id
            WHERE fo.booking_id = ?
            ORDER BY fo.order_date DESC
        ''', (booking_id,))

        orders = cursor.fetchall()
        self.db.return_connection(conn)
        return [dict(order) for order in orders]

    def delete_food_order(self, order_id: int):
        """Delete a food order."""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM food_orders WHERE id = ?', (order_id,))
        conn.commit()
        self.db.return_connection(conn)

    def get_active_bookings(self):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT b.*, r.room_number, r.room_type
            FROM bookings b
            JOIN rooms r ON b.room_id = r.id
            WHERE b.status = "active"
            ORDER BY b.check_in_time DESC
        ''')
        bookings = cursor.fetchall()
        self.db.return_connection(conn)
        return [dict(booking) for booking in bookings]

    def get_all_bookings_for_billing(self):
        """Get all bookings that can be billed (active and completed)"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT b.*, r.room_number, r.room_type
            FROM bookings b
            JOIN rooms r ON b.room_id = r.id
            WHERE b.status IN ("active", "completed")
            ORDER BY b.check_in_time DESC
        ''')
        bookings = cursor.fetchall()
        self.db.return_connection(conn)
        return [dict(booking) for booking in bookings]

    def get_reservations(self):
        """Get all reservations (future bookings)"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                SELECT b.*, r.room_number, r.room_type
                FROM bookings b
                JOIN rooms r ON b.room_id = r.id
                WHERE b.reservation_type = "reservation"
                AND b.status = "reserved"
                ORDER BY b.check_in_date
            ''')

            bookings = cursor.fetchall()
            return [dict(booking) for booking in bookings]
        finally:
            self.db.return_connection(conn)

    def cancel_reservation(self, reservation_id: int):
        """Cancel a reservation"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                UPDATE bookings
                SET status = "cancelled"
                WHERE id = ? AND reservation_type = "reservation"
            ''', (reservation_id,))

            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise ValueError(f"Error cancelling reservation: {str(e)}")
        finally:
            self.db.return_connection(conn)

    def get_booking_by_id(self, booking_id: int):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT b.*, r.room_number, r.room_type, r.price_per_hour, r.price_per_day
            FROM bookings b
            JOIN rooms r ON b.room_id = r.id
            WHERE b.id = ?
        ''', (booking_id,))
        booking = cursor.fetchone()
        self.db.return_connection(conn)
        return dict(booking) if booking else None

    def get_all_bookings(self, start_date=None, end_date=None):
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            if start_date and end_date:
                cursor.execute('''
                    SELECT b.*, r.room_number, r.room_type
                    FROM bookings b
                    JOIN rooms r ON b.room_id = r.id
                    WHERE DATE(b.check_in_time) BETWEEN ? AND ?
                    ORDER BY b.check_in_time DESC
                ''', (start_date, end_date))
            else:
                cursor.execute('''
                    SELECT b.*, r.room_number, r.room_type
                    FROM bookings b
                    JOIN rooms r ON b.room_id = r.id
                    ORDER BY b.check_in_time DESC
                ''')

            bookings = cursor.fetchall()
            return [dict(booking) for booking in bookings]
        finally:
            self.db.return_connection(conn)

    # Bill management methods
    def update_bill(self, bill_id: int, update_data: dict, reason: str):
        """Update bill with adjustment record"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # Get current bill
            cursor.execute('SELECT * FROM bills WHERE id = ?', (bill_id,))
            bill = cursor.fetchone()

            if not bill:
                raise ValueError("Bill not found")

            bill = dict(bill)

            # Calculate new total
            new_total = float(update_data.get('total_amount', bill['total_amount']))
            adjustment_amount = new_total - bill['total_amount']

            # Update bill
            cursor.execute('''
                UPDATE bills
                SET total_amount = ?, payment_status = ?, payment_method = ?, notes = ?, verified_by = ?
                WHERE id = ?
            ''', (
                new_total,
                update_data.get('payment_status', bill['payment_status']),
                update_data.get('payment_method', bill['payment_method']),
                update_data.get('notes', bill['notes']),
                update_data.get('verified_by', bill['verified_by']),
                bill_id
            ))

            # Create adjustment record
            cursor.execute('''
                INSERT INTO bill_adjustments
                (bill_id, adjustment_type, amount, reason, adjusted_by)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                bill_id,
                'increase' if adjustment_amount > 0 else 'decrease',
                abs(adjustment_amount),
                reason,
                self.auth.current_user['id']
            ))

            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise ValueError(f"Error updating bill: {str(e)}")
        finally:
            self.db.return_connection(conn)

    def get_bill_by_id(self, bill_id: int):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT b.*, r.room_number, bk.guest_name, bk.guest_phone, bk.company_name,
                   bk.company_address, bk.party_gstin, bk.no_of_persons, bk.advance_payment,
                   u.username as created_by_name
            FROM bills b
            JOIN rooms r ON b.room_id = r.id
            JOIN bookings bk ON b.booking_id = bk.id
            LEFT JOIN users u ON b.created_by = u.id
            WHERE b.id = ?
        ''', (bill_id,))
        bill = cursor.fetchone()
        self.db.return_connection(conn)
        return dict(bill) if bill else None

    def get_bill_by_number(self, bill_number: str):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT b.*, r.room_number, bk.guest_name, bk.guest_phone, bk.company_name,
                   bk.company_address, bk.party_gstin, bk.no_of_persons, bk.advance_payment,
                   u.username as created_by_name
            FROM bills b
            JOIN rooms r ON b.room_id = r.id
            JOIN bookings bk ON b.booking_id = bk.id
            LEFT JOIN users u ON b.created_by = u.id
            WHERE b.bill_number = ?
        ''', (bill_number,))
        bill = cursor.fetchone()
        self.db.return_connection(conn)
        return dict(bill) if bill else None

    def get_all_bills(self, start_date=None, end_date=None):
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            if start_date and end_date:
                cursor.execute('''
                    SELECT b.*, r.room_number, bk.guest_name, u.username as created_by_name
                    FROM bills b
                    JOIN rooms r ON b.room_id = r.id
                    JOIN bookings bk ON b.booking_id = bk.id
                    LEFT JOIN users u ON b.created_by = u.id
                    WHERE DATE(b.bill_date) BETWEEN ? AND ?
                    ORDER BY b.bill_date DESC
                ''', (start_date, end_date))
            else:
                cursor.execute('''
                    SELECT b.*, r.room_number, bk.guest_name, u.username as created_by_name
                    FROM bills b
                    JOIN rooms r ON b.room_id = r.id
                    JOIN bookings bk ON b.booking_id = bk.id
                    LEFT JOIN users u ON b.created_by = u.id
                    ORDER BY b.bill_date DESC
                ''')

            bills = cursor.fetchall()
            return [dict(bill) for bill in bills]
        finally:
            self.db.return_connection(conn)

    def get_sales_summary(self, start_date: str = None, end_date: str = None):
        """Get sales summary with settlement amounts."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            if start_date and end_date:
                # Get from sales_summary table for the date range
                cursor.execute('''
                    SELECT 
                        date,
                        total_bookings,
                        total_amount,
                        collected_amount,
                        pending_amount,
                        settlement_amount
                    FROM sales_summary
                    WHERE date BETWEEN ? AND ?
                    ORDER BY date DESC
                ''', (start_date, end_date))
            else:
                # Get last 30 days
                thirty_days_ago = (datetime.now() - timedelta(days=30)).date().isoformat()
                cursor.execute('''
                    SELECT 
                        date,
                        total_bookings,
                        total_amount,
                        collected_amount,
                        pending_amount,
                        settlement_amount
                    FROM sales_summary
                    WHERE date >= ?
                    ORDER BY date DESC
                ''', (thirty_days_ago,))

            summary = cursor.fetchall()
            return [dict(record) for record in summary]
        finally:
            self.db.return_connection(conn)

    def get_detailed_sales(self, date_str: str):
        """Get detailed sales for a specific date including settlements."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # Get bills for the date
            cursor.execute('''
                SELECT b.bill_number, r.room_number, bk.guest_name,
                       b.total_amount, b.payment_status, b.advance_paid, b.balance_due,
                       b.check_in_time, b.check_out_time
                FROM bills b
                JOIN rooms r ON b.room_id = r.id
                JOIN bookings bk ON b.booking_id = bk.id
                WHERE DATE(b.bill_date) = ?
                ORDER BY b.bill_date
            ''', (date_str,))

            bills = cursor.fetchall()

            # Get settlements for the date
            cursor.execute('''
                SELECT s.*, b.bill_number, r.room_number, bk.guest_name
                FROM settlements s
                JOIN bills b ON s.bill_id = b.id
                JOIN rooms r ON b.room_id = r.id
                JOIN bookings bk ON b.booking_id = bk.id
                WHERE DATE(s.settlement_date) = ?
                ORDER BY s.settlement_date
            ''', (date_str,))

            settlements = cursor.fetchall()

            return {
                'bills': [dict(bill) for bill in bills],
                'settlements': [dict(settlement) for settlement in settlements]
            }
        finally:
            self.db.return_connection(conn)

    # User management methods
    def get_all_users(self):
        """Get all users."""
        return self.db.get_all_users()

    def delete_user(self, user_id: int):
        """Delete a user."""
        try:
            # Prevent deleting self
            if self.auth.current_user and user_id == self.auth.current_user['id']:
                raise ValueError("You cannot delete your own account")

            # Prevent deleting the last admin
            conn = self.db.get_connection()
            cursor = conn.cursor()

            cursor.execute('SELECT role FROM users WHERE id = ?', (user_id,))
            user = cursor.fetchone()

            if not user:
                self.db.return_connection(conn)
                raise ValueError("User not found")

            if user['role'] == 'admin':
                cursor.execute('SELECT COUNT(*) as admin_count FROM users WHERE role = "admin"')
                admin_count = cursor.fetchone()['admin_count']
                if admin_count <= 1:
                    self.db.return_connection(conn)
                    raise ValueError("Cannot delete the last admin user")

            self.db.delete_user(user_id)
            return True
        except Exception as e:
            raise ValueError(f"Error deleting user: {str(e)}")

    def check_today_reservations(self):
        """Check for reservations that are for today"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        today = datetime.now().date()

        cursor.execute('''
            SELECT b.*, r.room_number, r.room_type, r.price_per_hour, r.price_per_day,
                   u.username as created_by_name
            FROM bookings b
            JOIN rooms r ON b.room_id = r.id
            LEFT JOIN users u ON b.created_by = u.id
            WHERE b.reservation_type = 'reservation'
            AND b.status = 'reserved'
            AND DATE(b.check_in_date) = ?
            ORDER BY b.check_in_time
        ''', (today.isoformat(),))

        today_reservations = cursor.fetchall()
        self.db.return_connection(conn)

        return [dict(res) for res in today_reservations]

    def check_room_availability_with_reservation_warning(self, room_id, check_in_date, check_out_date):
        """
        Check room availability and provide warning if room is reserved
        Returns: (is_available, warning_message, reservation_details)
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            check_in = datetime.strptime(check_in_date, '%Y-%m-%d').date()
            today = datetime.now().date()
            days_until_reservation = (check_in - today).days

            # Check if room has any reservation
            cursor.execute('''
                SELECT b.*, r.room_number
                FROM bookings b
                JOIN rooms r ON b.room_id = r.id
                WHERE b.room_id = ?
                AND b.reservation_type = 'reservation'
                AND b.status = 'reserved'
                AND (
                    (DATE(b.check_in_date) <= ? AND DATE(b.check_out_date) > ?) OR
                    (DATE(b.check_in_date) < ? AND DATE(b.check_out_date) >= ?)
                )
            ''', (room_id, check_out_date, check_in_date, check_out_date, check_in_date))

            reservation = cursor.fetchone()

            if reservation:
                res_dict = dict(reservation)
                res_date = datetime.strptime(res_dict['check_in_date'], '%Y-%m-%d').date()
                days_diff = (res_date - today).days

                warning = f"⚠️ This room is RESERVED for {res_dict['guest_name']} on {res_dict['check_in_date']}"

                if days_diff <= 5 and days_diff > 0:
                    warning += f"\n⚠️ Reservation is in {days_diff} days! Only {days_diff} days remaining!"
                    return False, warning, res_dict
                elif days_diff <= 0:
                    warning += "\n⚠️ RESERVATION IS FOR TODAY! Please contact the guest!"
                    return False, warning, res_dict
                else:
                    return False, warning, res_dict

            return True, "Room is available", None

        except Exception as e:
            return False, f"Error checking availability: {str(e)}", None
        finally:
            self.db.return_connection(conn)

    def get_guest_history(self, search_term, search_by='name'):
        """
        Get detailed guest history by name, phone number, or ID card.

        Args:
            search_term: The term to search for
            search_by: 'name', 'phone', or 'id_card'

        Returns:
            List of bookings with all guest details for the guest
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            if search_by == 'name':
                cursor.execute('''
                    SELECT b.*, r.room_number, r.room_type,
                           (SELECT SUM(paid_amount) FROM settlements WHERE bill_id IN 
                            (SELECT id FROM bills WHERE booking_id = b.id)) as total_paid,
                           (SELECT SUM(discount_amount) FROM settlements WHERE bill_id IN 
                            (SELECT id FROM bills WHERE booking_id = b.id)) as total_discount,
                           u.username as created_by_name
                    FROM bookings b
                    JOIN rooms r ON b.room_id = r.id
                    LEFT JOIN users u ON b.created_by = u.id
                    WHERE b.guest_name LIKE ? OR b.guest_name LIKE ?
                    ORDER BY b.created_at DESC
                ''', (f'%{search_term}%', f'%{search_term.upper()}%'))
            elif search_by == 'phone':
                cursor.execute('''
                    SELECT b.*, r.room_number, r.room_type,
                           (SELECT SUM(paid_amount) FROM settlements WHERE bill_id IN 
                            (SELECT id FROM bills WHERE booking_id = b.id)) as total_paid,
                           (SELECT SUM(discount_amount) FROM settlements WHERE bill_id IN 
                            (SELECT id FROM bills WHERE booking_id = b.id)) as total_discount,
                           u.username as created_by_name
                    FROM bookings b
                    JOIN rooms r ON b.room_id = r.id
                    LEFT JOIN users u ON b.created_by = u.id
                    WHERE b.guest_phone LIKE ? OR b.guest_phone LIKE ?
                    ORDER BY b.created_at DESC
                ''', (f'%{search_term}%', f'%{search_term}%'))
            elif search_by == 'id_card':
                cursor.execute('''
                    SELECT b.*, r.room_number, r.room_type,
                           (SELECT SUM(paid_amount) FROM settlements WHERE bill_id IN 
                            (SELECT id FROM bills WHERE booking_id = b.id)) as total_paid,
                           (SELECT SUM(discount_amount) FROM settlements WHERE bill_id IN 
                            (SELECT id FROM bills WHERE booking_id = b.id)) as total_discount,
                           u.username as created_by_name
                    FROM bookings b
                    JOIN rooms r ON b.room_id = r.id
                    LEFT JOIN users u ON b.created_by = u.id
                    WHERE b.guest_id_card LIKE ?
                    ORDER BY b.created_at DESC
                ''', (f'%{search_term}%',))

            bookings = cursor.fetchall()
            return [dict(booking) for booking in bookings]

        except Exception as e:
            print(f"Error getting guest history: {e}")
            return []
        finally:
            self.db.return_connection(conn)

    def get_guest_bills(self, guest_name=None, guest_phone=None, guest_id_card=None):
        """
        Get all bills for a guest.

        Args:
            guest_name: Guest name to search
            guest_phone: Guest phone to search
            guest_id_card: Guest ID card to search

        Returns:
            List of bills for the guest
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            query = '''
                SELECT b.*, r.room_number, bk.guest_name, bk.guest_phone, 
                       bk.guest_id_card, bk.check_in_time, bk.check_out_time,
                       (SELECT SUM(paid_amount) FROM settlements WHERE bill_id = b.id) as total_paid,
                       (SELECT SUM(discount_amount) FROM settlements WHERE bill_id = b.id) as total_discount
                FROM bills b
                JOIN rooms r ON b.room_id = r.id
                JOIN bookings bk ON b.booking_id = bk.id
                WHERE 1=1
            '''
            params = []

            if guest_name:
                query += " AND bk.guest_name LIKE ?"
                params.append(f'%{guest_name}%')

            if guest_phone:
                query += " AND bk.guest_phone LIKE ?"
                params.append(f'%{guest_phone}%')

            if guest_id_card:
                query += " AND bk.guest_id_card LIKE ?"
                params.append(f'%{guest_id_card}%')

            query += " ORDER BY b.bill_date DESC"

            cursor.execute(query, params)
            bills = cursor.fetchall()
            return [dict(bill) for bill in bills]

        except Exception as e:
            print(f"Error getting guest bills: {e}")
            return []
        finally:
            self.db.return_connection(conn)

    def get_guest_history(self, search_term, search_by='name'):
        """
        Get detailed guest history by name, phone number, or ID card.
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            if search_by == 'name':
                cursor.execute('''
                    SELECT b.*, r.room_number, r.room_type,
                           (SELECT SUM(paid_amount) FROM settlements WHERE bill_id IN 
                            (SELECT id FROM bills WHERE booking_id = b.id)) as total_paid,
                           (SELECT SUM(discount_amount) FROM settlements WHERE bill_id IN 
                            (SELECT id FROM bills WHERE booking_id = b.id)) as total_discount,
                           u.username as created_by_name
                    FROM bookings b
                    JOIN rooms r ON b.room_id = r.id
                    LEFT JOIN users u ON b.created_by = u.id
                    WHERE b.guest_name LIKE ? OR b.guest_name LIKE ?
                    ORDER BY b.created_at DESC
                ''', (f'%{search_term}%', f'%{search_term.upper()}%'))
            elif search_by == 'phone':
                cursor.execute('''
                    SELECT b.*, r.room_number, r.room_type,
                           (SELECT SUM(paid_amount) FROM settlements WHERE bill_id IN 
                            (SELECT id FROM bills WHERE booking_id = b.id)) as total_paid,
                           (SELECT SUM(discount_amount) FROM settlements WHERE bill_id IN 
                            (SELECT id FROM bills WHERE booking_id = b.id)) as total_discount,
                           u.username as created_by_name
                    FROM bookings b
                    JOIN rooms r ON b.room_id = r.id
                    LEFT JOIN users u ON b.created_by = u.id
                    WHERE b.guest_phone LIKE ? OR b.guest_phone LIKE ?
                    ORDER BY b.created_at DESC
                ''', (f'%{search_term}%', f'%{search_term}%'))
            elif search_by == 'id_card':
                cursor.execute('''
                    SELECT b.*, r.room_number, r.room_type,
                           (SELECT SUM(paid_amount) FROM settlements WHERE bill_id IN 
                            (SELECT id FROM bills WHERE booking_id = b.id)) as total_paid,
                           (SELECT SUM(discount_amount) FROM settlements WHERE bill_id IN 
                            (SELECT id FROM bills WHERE booking_id = b.id)) as total_discount,
                           u.username as created_by_name
                    FROM bookings b
                    JOIN rooms r ON b.room_id = r.id
                    LEFT JOIN users u ON b.created_by = u.id
                    WHERE b.guest_id_card LIKE ?
                    ORDER BY b.created_at DESC
                ''', (f'%{search_term}%',))

            bookings = cursor.fetchall()
            return [dict(booking) for booking in bookings]

        except Exception as e:
            print(f"Error getting guest history: {e}")
            return []
        finally:
            self.db.return_connection(conn)

    def get_guest_bills(self, guest_name=None, guest_phone=None, guest_id_card=None):
        """
        Get all bills for a guest.
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            query = '''
                SELECT b.*, r.room_number, bk.guest_name, bk.guest_phone, 
                       bk.guest_id_card, bk.check_in_time, bk.check_out_time,
                       (SELECT SUM(paid_amount) FROM settlements WHERE bill_id = b.id) as total_paid,
                       (SELECT SUM(discount_amount) FROM settlements WHERE bill_id = b.id) as total_discount
                FROM bills b
                JOIN rooms r ON b.room_id = r.id
                JOIN bookings bk ON b.booking_id = bk.id
                WHERE 1=1
            '''
            params = []

            if guest_name and guest_name != 'N/A':
                query += " AND bk.guest_name LIKE ?"
                params.append(f'%{guest_name}%')

            if guest_phone and guest_phone != 'N/A':
                query += " AND bk.guest_phone LIKE ?"
                params.append(f'%{guest_phone}%')

            if guest_id_card and guest_id_card != 'N/A':
                query += " AND bk.guest_id_card LIKE ?"
                params.append(f'%{guest_id_card}%')

            query += " ORDER BY b.bill_date DESC"

            cursor.execute(query, params)
            bills = cursor.fetchall()
            return [dict(bill) for bill in bills]

        except Exception as e:
            print(f"Error getting guest bills: {e}")
            return []
        finally:
            self.db.return_connection(conn)


# Bill Generator Class - Updated for A4 size with proper spacing and dynamic data
class BillGenerator:
    def __init__(self, hotel_manager=None):
        self.hotel_manager = hotel_manager
        self.hotel_settings = None
        self.current_user = None
        if hotel_manager:
            self.set_hotel_manager(hotel_manager)

    def set_hotel_manager(self, hotel_manager):
        """Set the hotel manager instance to get dynamic data."""
        self.hotel_manager = hotel_manager
        if hotel_manager:
            self.hotel_settings = hotel_manager.get_hotel_settings()
            if hotel_manager.auth and hotel_manager.auth.current_user:
                self.current_user = hotel_manager.auth.current_user
            else:
                self.current_user = None

    @staticmethod
    def number_to_words(amount):
        """Convert number to words in Indian Rupees format."""

        def num_to_words(n):
            if n == 0:
                return "Zero"

            ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
                    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
                    "Seventeen", "Eighteen", "Nineteen"]
            tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

            if n < 20:
                return ones[n]
            if n < 100:
                return tens[n // 10] + (" " + ones[n % 10] if n % 10 != 0 else "")
            if n < 1000:
                return ones[n // 100] + " Hundred" + (" " + num_to_words(n % 100) if n % 100 != 0 else "")
            if n < 100000:
                return num_to_words(n // 1000) + " Thousand" + (" " + num_to_words(n % 1000) if n % 1000 != 0 else "")
            if n < 10000000:
                return num_to_words(n // 100000) + " Lakh" + (" " + num_to_words(n % 100000) if n % 100000 != 0 else "")
            return num_to_words(n // 10000000) + " Crore" + (
                " " + num_to_words(n % 10000000) if n % 10000000 != 0 else "")

        rupees = int(amount)
        paise = int(round((amount - rupees) * 100))

        if rupees == 0 and paise == 0:
            return "Zero Rupees"

        rupees_word = num_to_words(rupees) + " Rupee" + ("s" if rupees != 1 else "")
        if paise == 0:
            return rupees_word + " Only"
        else:
            paise_word = num_to_words(paise) + " Paise" if paise > 0 else ""
            return rupees_word + " and " + paise_word + " Only"

    def generate_bill_image(self, bill_data, day_breakdowns=None):
        """Generate A4 sized bill image with day-wise breakdown."""
        # Refresh hotel settings to get latest data
        if self.hotel_manager:
            self.hotel_settings = self.hotel_manager.get_hotel_settings()
            if not self.current_user and self.hotel_manager.auth:
                self.current_user = self.hotel_manager.auth.current_user

        # A4 dimensions in pixels at 100 DPI
        width = 827  # A4 width at 100 DPI (8.27 inches)
        height = 1169  # A4 height at 100 DPI (11.69 inches)

        img = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(img)

        try:
            # Try to load professional fonts with larger sizes
            font_paths = [
                "arial.ttf", "Arial.ttf", "Helvetica.ttf", "DejaVuSans.ttf",
                "LiberationSans-Regular.ttf", "/System/Library/Fonts/Arial.ttf",
                "/System/Library/Fonts/Helvetica.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/tahoma.ttf"
            ]

            font_title_large = ImageFont.load_default()
            font_title = ImageFont.load_default()
            font_header = ImageFont.load_default()
            font_normal = ImageFont.load_default()
            font_small = ImageFont.load_default()
            font_bold = ImageFont.load_default()

            for font_path in font_paths:
                try:
                    font_title_large = ImageFont.truetype(font_path, 28)  # Large title
                    font_title = ImageFont.truetype(font_path, 24)  # Title size
                    font_header = ImageFont.truetype(font_path, 18)  # Header size
                    font_normal = ImageFont.truetype(font_path, 14)  # Normal text
                    font_small = ImageFont.truetype(font_path, 12)  # Small text
                    font_bold = ImageFont.truetype(font_path, 14)  # Bold text
                    break
                except:
                    continue

        except Exception:
            font_title_large = font_title = font_header = font_normal = font_small = font_bold = ImageFont.load_default()

        # Get dynamic hotel settings with fallbacks
        hotel_name = self.hotel_settings.get('hotel_name', 'THE EVAANI') if self.hotel_settings else 'THE EVAANI'
        unit = self.hotel_settings.get('unit',
                                       'Unit of BY JS HOTELS & FOODS') if self.hotel_settings else 'Unit of BY JS HOTELS & FOODS'
        address = self.hotel_settings.get('address',
                                          'Talwandi Road, Mansa') if self.hotel_settings else 'Talwandi Road, Mansa'
        phone = self.hotel_settings.get('phone',
                                        '9501298836') if self.hotel_settings else '9501298836'
        gstin = self.hotel_settings.get('gstin',
                                        '03AATFJ9071F1Z3') if self.hotel_settings else '03AATFJ9071F1Z3'

        # Get verified by from logged-in user or bill data
        verified_by = bill_data.get('verified_by', '')
        if not verified_by and self.current_user:
            verified_by = self.current_user.get('username', 'Kapil')
        if not verified_by:
            verified_by = 'Kapil'

        # Margins and positions
        left_margin = 50
        right_margin = width - 50
        content_width = right_margin - left_margin
        col1 = left_margin
        col2 = left_margin + (content_width // 3)
        col3 = left_margin + (content_width * 2 // 3)

        y_position = 30  # Starting Y position

        # ========== LOGO SECTION ==========
        # Try to load and place logo
        try:
            # Look for logo in multiple possible locations
            logo_paths = [
                "evaani.png",
                "Evaani.png",
                "the_evaani.png",
                "THE_EVAANI.png",
                "images/evaani.png",
                "assets/evaani.png",
                "static/evaani.png",
                "logo/evaani.png",
                "../evaani.png",
                "../../evaani.png"
            ]

            logo = None
            for logo_path in logo_paths:
                try:
                    if os.path.exists(logo_path):
                        logo = Image.open(logo_path)
                        break
                except:
                    continue

            if logo:
                # Calculate logo size (max 150px height, maintain aspect ratio)
                max_logo_height = 100
                logo_width, logo_height = logo.size
                if logo_height > max_logo_height:
                    ratio = max_logo_height / logo_height
                    new_width = int(logo_width * ratio)
                    new_height = max_logo_height
                    logo = logo.resize((new_width, new_height), Image.Resampling.LANCZOS)

                # Calculate position to center the logo
                logo_x = (width - logo.width) // 2

                # Paste logo (handle transparency if present)
                if logo.mode in ('RGBA', 'LA') or (logo.mode == 'P' and 'transparency' in logo.info):
                    # Create a white background for transparency
                    logo_bg = Image.new('RGBA', logo.size, (255, 255, 255, 255))
                    logo_bg.paste(logo, (0, 0), logo)
                    logo = logo_bg.convert('RGB')

                img.paste(logo, (logo_x, y_position))
                y_position += logo.height + 15
            else:
                # If logo not found, just add some spacing
                y_position += 15
                print("Logo file not found. Continuing without logo.")
        except Exception as e:
            print(f"Error loading logo: {e}")
            y_position += 15

        # ========== HEADER SECTION ==========
        # Hotel Name
        draw.text((width // 2, y_position), hotel_name,
                  fill='#6a4334', font=font_title_large, anchor='mm')
        y_position += 40

        # Unit
        draw.text((width // 2, y_position), unit,
                  fill='#2e86c1', font=font_header, anchor='mm')
        y_position += 35

        # Address
        draw.text((width // 2, y_position), address,
                  fill='#333333', font=font_normal, anchor='mm')
        y_position += 30

        # Phone
        draw.text((width // 2, y_position), f"Phone: {phone}",
                  fill='#333333', font=font_normal, anchor='mm')
        y_position += 30

        # GSTIN
        draw.text((width // 2, y_position), f"GSTIN: {gstin}",
                  fill='#333333', font=font_normal, anchor='mm')
        y_position += 35

        # Decorative line
        draw.line([left_margin, y_position, right_margin, y_position], fill='#6a4334', width=3)
        y_position += 25

        # ========== INVOICE DETAILS SECTION ==========
        # Invoice Title
        draw.text((width // 2, y_position), "TAX INVOICE", fill='#c0392b',
                  font=font_header, anchor='mm')
        y_position += 35

        # Create a two-column layout for invoice details
        invoice_details = [
            ("Invoice No.:", bill_data.get('bill_number', ''), "Folio No.:", bill_data.get('folio_no', '')),
            ("Reg. No.:", bill_data.get('registration_no', ''), "Invoice Date:",
             datetime.fromisoformat(bill_data['bill_date']).strftime('%d/%m/%Y %H:%M') if bill_data.get(
                 'bill_date') else ''),
            ("Place:", "Mansa (16)", "Service Place:", "Mansa")
        ]

        for row in invoice_details:
            # Left column
            draw.text((col1, y_position), row[0], fill='#333333', font=font_bold)
            draw.text((col1 + 90, y_position), row[1], fill='#333333', font=font_normal)
            # Right column
            draw.text((col2 + 50, y_position), row[2], fill='#333333', font=font_bold)
            draw.text((col2 + 160, y_position), row[3], fill='#333333', font=font_normal)
            y_position += 25

        y_position += 10

        # ========== GUEST DETAILS SECTION ==========
        # Section header with background
        draw.rectangle([left_margin - 5, y_position - 5, right_margin + 5, y_position + 30],
                       fill='#f0f0f0', outline='#cccccc')
        draw.text((width // 2, y_position + 12), "GUEST & STAY DETAILS",
                  fill='#6a4334', font=font_bold, anchor='mm')
        y_position += 40

        # Guest details in grid format
        guest_details = [
            ("Room No.:", bill_data.get('room_number', ''), "Guest Name:", bill_data.get('guest_name', '')),
            ("No. of Persons:", str(bill_data.get('no_of_persons', 1)), "Phone:", bill_data.get('guest_phone', '')),
            ("Company", bill_data.get('company_name', 'N/A'), "Party GSTIN:",
             bill_data.get('party_gstin', 'N/A')),
            ("Advance Paid:", f"₹{bill_data.get('advance_paid', 0.0):.2f}", "Balance Due:",
             f"₹{bill_data.get('balance_due', 0.0):.2f}")
        ]

        for row in guest_details:
            # Left column
            draw.text((col1, y_position), row[0], fill='#333333', font=font_bold)
            draw.text((col1 + 100, y_position), str(row[1]), fill='#333333', font=font_normal)
            # Right column (if exists)
            if row[2]:
                draw.text((col2, y_position), row[2], fill='#333333', font=font_bold)
                draw.text((col2 + 120, y_position), str(row[3]), fill='#333333', font=font_normal)
            y_position += 25

        y_position += 10

        # ========== STAY TIMINGS SECTION ==========
        arrival_date = datetime.fromisoformat(bill_data['check_in_time']).strftime('%d/%m/%Y')
        arrival_time = datetime.fromisoformat(bill_data['check_in_time']).strftime('%H:%M')
        departure_date = datetime.fromisoformat(bill_data['check_out_time']).strftime('%d/%m/%Y')
        departure_time = datetime.fromisoformat(bill_data['check_out_time']).strftime('%H:%M')

        timings = [
            ("Arrival Date:", arrival_date, "Arrival Time:", arrival_time),
            ("Departure Date:", departure_date, "Departure Time:", departure_time),
            ("Total Days:", str(int(bill_data['total_hours'] / 24)), "Total Hours:", f"{bill_data['total_hours']:.1f}")
        ]

        for row in timings:
            draw.text((col1, y_position), row[0], fill='#333333', font=font_bold)
            draw.text((col1 + 100, y_position), row[1], fill='#333333', font=font_normal)
            draw.text((col2, y_position), row[2], fill='#333333', font=font_bold)
            draw.text((col2 + 120, y_position), row[3], fill='#333333', font=font_normal)
            y_position += 25

        y_position += 15

        # ========== DAY WISE BREAKDOWN TABLE ==========
        # Table header
        table_left = left_margin
        table_right = right_margin

        col_day = table_left + 30
        col_date = table_left + 120
        col_room = table_left + 250
        col_cgst = table_left + 380
        col_sgst = table_left + 480
        col_total = table_left + 580

        # Header background
        draw.rectangle([table_left - 5, y_position - 5, table_right + 5, y_position + 30],
                       fill='#2e86c1', outline='#cccccc')

        # Header text
        draw.text((table_left + 10, y_position + 8), "Day", fill='white', font=font_bold)
        draw.text((col_date, y_position + 8), "Date", fill='white', font=font_bold)
        draw.text((col_room, y_position + 8), "Room Charge", fill='white', font=font_bold)
        draw.text((col_cgst, y_position + 8), "CGST", fill='white', font=font_bold)
        draw.text((col_sgst, y_position + 8), "SGST", fill='white', font=font_bold)
        draw.text((col_total, y_position + 8), "Total", fill='white', font=font_bold)

        y_position += 35
        running_total = 0

        # Use provided day breakdowns or calculate
        if day_breakdowns:
            for day in day_breakdowns:
                draw.text((table_left + 10, y_position), str(day['day_number']),
                          fill='#333333', font=font_normal)
                draw.text((col_date, y_position), day['date'],
                          fill='#333333', font=font_normal)
                draw.text((col_room + 60, y_position), f"₹{day['room_charge']:.2f}",
                          fill='#333333', font=font_normal, anchor='ra')
                draw.text((col_cgst, y_position), f"₹{day['cgst_amount']:.2f}",
                          fill='#333333', font=font_normal, anchor='ra')
                draw.text((col_sgst, y_position), f"₹{day['sgst_amount']:.2f}",
                          fill='#333333', font=font_normal, anchor='ra')
                day_total = day['room_charge'] + day['cgst_amount'] + day['sgst_amount']
                draw.text((col_total, y_position), f"₹{day_total:.2f}",
                          fill='#333333', font=font_normal, anchor='ra')
                running_total += day_total
                y_position += 25

            # Light separator line
            draw.line([table_left, y_position - 8, table_right, y_position - 8],
                      fill='#eeeeee', width=1)

        # Food Orders if any
        if bill_data['food_total'] > 0:
            draw.text((table_left, y_position), "Room Services",
                      fill='#333333', font=font_normal)
            draw.text((col_room, y_position), f"₹{bill_data['food_total']:.2f}",
                      fill='#333333', font=font_normal, anchor='ra')
            draw.text((col_total, y_position), f"₹{bill_data['food_total'] + bill_data['food_gst_total']:.2f}",
                      fill='#333333', font=font_normal, anchor='ra')
            running_total += (bill_data['food_total'] + bill_data['food_gst_total'])
            y_position += 25

        # Discount if any
        if bill_data.get('discount_amount', 0) > 0:
            draw.text((table_left, y_position), f"Discount @ {bill_data['discount_percentage']}%",
                      fill='#c0392b', font=font_normal)
            draw.text((col_total, y_position), f"-₹{bill_data['discount_amount']:.2f}",
                      fill='#c0392b', font=font_normal, anchor='ra')
            running_total -= bill_data['discount_amount']
            y_position += 25

        y_position += 10

        # ========== TAX SUMMARY SECTION ==========
        # Header
        draw.rectangle([table_left - 5, y_position - 5, table_right + 5, y_position + 25],
                       fill='#f8f9fa', outline='#cccccc')
        draw.text((table_left, y_position + 5), "TAX SUMMARY",
                  fill='#6a4334', font=font_bold)
        y_position += 30

        # Tax details
        tax_y = y_position
        draw.text((table_left, tax_y), f"CGST @ {bill_data['cgst_percentage']}% on Room Rent:",
                  fill='#333333', font=font_normal)
        draw.text((col_total - 50, tax_y), f"₹{bill_data['cgst_amount']:.2f}",
                  fill='#333333', font=font_normal, anchor='ra')
        tax_y += 25

        draw.text((table_left, tax_y), f"SGST @ {bill_data['sgst_percentage']}% on Room Rent:",
                  fill='#333333', font=font_normal)
        draw.text((col_total - 50, tax_y), f"₹{bill_data['sgst_amount']:.2f}",
                  fill='#333333', font=font_normal, anchor='ra')
        tax_y += 25

        if bill_data['food_gst_total'] > 0:
            draw.text((table_left, tax_y), "GST on Food (Inclusive):",
                      fill='#333333', font=font_normal)
            draw.text((col_total - 50, tax_y), f"₹{bill_data['food_gst_total']:.2f}",
                      fill='#333333', font=font_normal, anchor='ra')
            tax_y += 25

        y_position = tax_y + 15

        # ========== GRAND TOTAL SECTION ==========
        # Grand total box
        draw.rectangle([table_left - 5, y_position - 5, table_right + 5, y_position + 45],
                       fill='#f0f0f0', outline='#6a4334', width=2)

        grand_total_text = f"GRAND TOTAL: ₹ {bill_data['total_amount']:.2f}"
        draw.text((width // 2, y_position + 15), grand_total_text,
                  fill='#c0392b', font=font_title, anchor='mm')
        y_position += 55

        # Amount in words
        words = BillGenerator.number_to_words(bill_data['total_amount'])
        draw.text((left_margin, y_position), f"Amount in Words: {words}",
                  fill='#333333', font=font_normal)
        y_position += 30

        # ========== PAYMENT DETAILS ==========
        payment_details = [
            ("Payment Mode:", bill_data.get('payment_method', '').replace('_', ' ').title()),
            ("Payment Status:", bill_data.get('payment_status', '').upper()),
            ("Payment Date:", datetime.now().strftime('%d/%m/%Y %H:%M'))
        ]

        for i, (label, value) in enumerate(payment_details):
            draw.text((left_margin, y_position + i * 25), label, fill='#333333', font=font_bold)
            draw.text((left_margin + 120, y_position + i * 25), value, fill='#333333', font=font_normal)

        y_position += len(payment_details) * 25 + 15

        # ========== SIGNATURE SECTION ==========
        draw.line([left_margin, y_position, left_margin + 200, y_position], fill='#cccccc', width=1)
        draw.text((left_margin, y_position + 5), f"Verified By: {verified_by}",
                  fill='#333333', font=font_small)

        draw.line([col2 + 50, y_position, col2 + 250, y_position], fill='#cccccc', width=1)
        draw.text((col2 + 150, y_position + 5), "Guest Signature",
                  fill='#333333', font=font_small, anchor='mm')

        draw.line([col3, y_position, right_margin, y_position], fill='#cccccc', width=1)
        draw.text((right_margin - 50, y_position + 5), "Office Copy",
                  fill='#333333', font=font_small)

        y_position += 30

        # ========== FOOTER ==========
        draw.line([left_margin, y_position, right_margin, y_position], fill='#6a4334', width=2)
        y_position += 20

        footer_text = "Thank you for being with us !!!"
        draw.text((width // 2, y_position), footer_text, fill='#6a4334',
                  font=font_header, anchor='mm')
        y_position += 25

        email = "theevaanis@gmail.com"
        website = "www.theevaanihotel.com"
        contact_text = f"Contact: {9501298836} | Email: {email} | {website}"
        draw.text((width // 2, y_position), contact_text, fill='#666666',
                  font=font_small, anchor='mm')

        # Save to temporary file
        temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        img.save(temp_file.name, dpi=(300, 300), quality=95)
        return temp_file.name

    def print_bill(self, bill_data, day_breakdowns=None):
        """Generate and display bill in A4 format with working buttons."""
        try:
            # Generate bill image
            image_path = self.generate_bill_image(bill_data, day_breakdowns)

            if image_path:
                # Open the image for viewing
                img = Image.open(image_path)

                # Create preview window - A4 size friendly
                preview_window = tk.Toplevel()
                preview_window.title("Bill Preview - A4 Size")
                preview_window.geometry("1000x1300")
                preview_window.configure(bg='white')

                # Make window modal
                preview_window.transient()
                preview_window.grab_set()

                # Create scrollable canvas for the image
                canvas_frame = ttk.Frame(preview_window)
                canvas_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

                canvas = tk.Canvas(canvas_frame, bg='white')
                scrollbar_y = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
                scrollbar_x = ttk.Scrollbar(canvas_frame, orient="horizontal", command=canvas.xview)

                canvas.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

                # Convert PIL image to PhotoImage
                img_tk = ImageTk.PhotoImage(img)

                # Create canvas image
                canvas.create_image(0, 0, anchor=tk.NW, image=img_tk)
                canvas.image = img_tk  # Keep reference

                # Update scroll region
                canvas.update_idletasks()
                canvas.configure(scrollregion=canvas.bbox("all"))

                # Pack widgets
                canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
                scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)

                # Action buttons frame
                button_frame = tk.Frame(preview_window, bg='white')
                button_frame.pack(fill=tk.X, padx=10, pady=10)

                def save_bill():
                    from tkinter import filedialog
                    file_path = filedialog.asksaveasfilename(
                        defaultextension=".png",
                        filetypes=[
                            ("PNG files", "*.png"),
                            ("PDF files", "*.pdf"),
                            ("JPEG files", "*.jpg"),
                            ("All files", "*.*")
                        ],
                        parent=preview_window
                    )
                    if file_path:
                        try:
                            if file_path.lower().endswith('.pdf'):
                                # Convert to PDF
                                img.save(file_path, "PDF", resolution=100.0)
                            else:
                                img.save(file_path, dpi=(300, 300), quality=95)
                            messagebox.showinfo("Success", f"Bill saved to {file_path}", parent=preview_window)
                        except Exception as e:
                            messagebox.showerror("Error", f"Could not save file: {str(e)}", parent=preview_window)

                def print_bill_action():
                    try:
                        # Try to open with default system print dialog
                        import subprocess
                        import platform

                        if platform.system() == 'Darwin':  # macOS
                            subprocess.run(['open', image_path])
                        elif platform.system() == 'Windows':
                            os.startfile(image_path, 'print')
                        else:  # Linux
                            subprocess.run(['xdg-open', image_path])

                        messagebox.showinfo("Print",
                                            "Bill opened in default viewer.\nUse File > Print (Ctrl+P) to print.",
                                            parent=preview_window)
                    except Exception as e:
                        messagebox.showerror("Error", f"Could not open image: {str(e)}", parent=preview_window)

                def close_window():
                    try:
                        os.unlink(image_path)
                    except:
                        pass
                    preview_window.destroy()

                # Style buttons with larger size
                save_btn = tk.Button(button_frame, text="💾 Save Bill", font=('Segoe UI', 12, 'bold'),
                                     bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                     command=save_bill, padx=30, pady=10)
                save_btn.pack(side=tk.LEFT, padx=5)

                print_btn = tk.Button(button_frame, text="🖨️ Print Bill", font=('Segoe UI', 12, 'bold'),
                                      bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                                      command=print_bill_action, padx=30, pady=10)
                print_btn.pack(side=tk.LEFT, padx=5)

                close_btn = tk.Button(button_frame, text="✖ Close", font=('Segoe UI', 12, 'bold'),
                                      bg='#c0392b', fg='black', relief='flat', cursor='hand2',
                                      command=close_window, padx=30, pady=10)
                close_btn.pack(side=tk.RIGHT, padx=5)

                # Bind Enter keys
                save_btn.bind('<Return>', lambda e: save_bill())
                print_btn.bind('<Return>', lambda e: print_bill_action())
                close_btn.bind('<Return>', lambda e: close_window())

                # Bind Escape key
                preview_window.bind('<Escape>', lambda e: close_window())

                # Center window on screen
                preview_window.update_idletasks()
                x = (preview_window.winfo_screenwidth() // 2) - (1000 // 2)
                y = (preview_window.winfo_screenheight() // 2) - (1300 // 2)
                preview_window.geometry(f'+{x}+{y}')

                return True
            else:
                # Fallback to text bill
                return self._show_text_bill(bill_data, day_breakdowns)

        except Exception as e:
            print(f"Error showing bill preview: {e}")
            import traceback
            traceback.print_exc()
            return self._show_text_bill(bill_data, day_breakdowns)

    def _show_text_bill(self, bill_data, day_breakdowns=None):
        """Fallback method to show bill as text."""
        # Get dynamic data
        if self.hotel_manager:
            self.hotel_settings = self.hotel_manager.get_hotel_settings()

        hotel_name = self.hotel_settings.get('hotel_name', 'THE EVAANI') if self.hotel_settings else 'THE EVAANI'
        unit = self.hotel_settings.get('unit',
                                       'Unit of BY JS HOTELS & FOODS') if self.hotel_settings else 'Unit of BY JS HOTELS & FOODS'
        address = self.hotel_settings.get('address',
                                          'Talwandi Road, Mansa') if self.hotel_settings else 'Talwandi Road, Mansa'
        phone = self.hotel_settings.get('phone',
                                        '9530752236, 9915297440') if self.hotel_settings else '9530752236, 9915297440'
        gstin = self.hotel_settings.get('gstin',
                                        '03AATFJ9071F1Z3') if self.hotel_settings else '03AATFJ9071F1Z3'

        verified_by = bill_data.get('verified_by', '')
        if not verified_by and self.current_user:
            verified_by = self.current_user.get('username', 'Kapil')
        if not verified_by:
            verified_by = 'Kapil'

        bill_text = f"""
{'=' * 100}
{' ' * 35}{hotel_name}
{' ' * 30}{unit}
{' ' * 33}{address}
{' ' * 30}Phone: {phone}
{' ' * 33}GSTIN: {gstin}
{'=' * 100}

{' ' * 45}TAX INVOICE
{'-' * 100}

Invoice Details:
{'-' * 50}
Invoice No.: {bill_data.get('bill_number', '')}
Folio No.: {bill_data.get('folio_no', '')}
Invoice Date: {datetime.fromisoformat(bill_data['bill_date']).strftime('%d/%m/%Y %H:%M') if bill_data.get('bill_date') else ''}
Place: Mansa

Guest Details:
{'-' * 50}
Room No.: {bill_data.get('room_number', '')}
Guest Name: {bill_data.get('guest_name', '')}
No. of Persons: {bill_data.get('no_of_persons', 1)}
Phone: {bill_data.get('guest_phone', '')}
Advance Paid: ₹{bill_data.get('advance_paid', 0.0):.2f}
Balance Due: ₹{bill_data.get('balance_due', 0.0):.2f}

Stay Details:
{'-' * 50}
Arrival: {datetime.fromisoformat(bill_data['check_in_time']).strftime('%d/%m/%Y %H:%M')}
Departure: {datetime.fromisoformat(bill_data['check_out_time']).strftime('%d/%m/%Y %H:%M')}
Total Days: {int(bill_data['total_hours'] / 24)}

DAY WISE BREAKDOWN:
{'-' * 100}
Day    Date        Room Charge    CGST      SGST      Total
{'-' * 100}"""

        if day_breakdowns:
            for day in day_breakdowns:
                bill_text += f"\n{day['day_number']:3}   {day['date']:10}   ₹{day['room_charge']:9.2f}   ₹{day['cgst_amount']:7.2f}   ₹{day['sgst_amount']:7.2f}   ₹{day['total']:9.2f}"

        bill_text += f"""
{'-' * 100}
Food Total: {' ' * 60} ₹{bill_data['food_total']:.2f}
Food GST: {' ' * 61} ₹{bill_data['food_gst_total']:.2f}
CGST @ {bill_data['cgst_percentage']}%: {' ' * 53} ₹{bill_data['cgst_amount']:.2f}
SGST @ {bill_data['sgst_percentage']}%: {' ' * 53} ₹{bill_data['sgst_amount']:.2f}
{'-' * 100}
{' ' * 70}SUB TOTAL: ₹{(bill_data['room_charges'] + bill_data['cgst_amount'] + bill_data['sgst_amount'] + bill_data['food_total'] + bill_data['food_gst_total']):.2f}
{'=' * 100}
{' ' * 70}GRAND TOTAL: ₹{bill_data['total_amount']:.2f}
{'=' * 100}

Amount in Words: {BillGenerator.number_to_words(bill_data['total_amount'])}

Payment Details:
{'-' * 50}
Payment Mode: {bill_data.get('payment_method', '').replace('_', ' ').title()}
Payment Status: {bill_data.get('payment_status', '').upper()}
Payment Date: {datetime.now().strftime('%d/%m/%Y %H:%M')}

Verified By: {verified_by}
Guest Signature: ________________
Copy Type: Office Copy

{'=' * 100}
{' ' * 35}Thank you for being with us !!!
{'=' * 100}
       """

        # Show in a text window
        text_window = tk.Toplevel()
        text_window.title("Bill Text")
        text_window.geometry("900x700")

        text_frame = ttk.Frame(text_window, padding=10)
        text_frame.pack(fill=tk.BOTH, expand=True)

        text_widget = tk.Text(text_frame, wrap=tk.NONE, font=('Courier', 11))
        text_widget.pack(fill=tk.BOTH, expand=True)
        text_widget.insert('1.0', bill_text)
        text_widget.config(state=tk.DISABLED)

        # Add scrollbars
        v_scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text_widget.yview)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.config(yscrollcommand=v_scroll.set)

        return True


# Tkinter GUI Application - Complete Modern UI Version with Keyboard Navigation
class HotelBillingAppGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("The Evaani Hotel - Billing Management System")

        # Start in full screen
        self.root.state('zoomed')

        # Get screen dimensions
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_width}x{screen_height}")

        # Initialize database and managers
        self.db = HotelDatabase()
        self.auth = Authentication(self.db)
        self.hotel = HotelBillingManager(self.db, self.auth)
        self.bill_generator = BillGenerator(self.hotel)

        # Widget references
        self.users_tree = None
        self.rooms_tree = None
        self.bookings_tree = None
        self.reservations_tree = None
        self.bills_tree = None
        self.sales_tree = None
        self.user_bills_tree = None
        self.food_orders_tree = None
        self.billings_tree = None
        self.settlements_tree = None

        # Current tab tracking
        self.current_tab = None
        self.active_dialog = None  # Track active dialog for ESC key

        # Set style
        self.setup_styles()

        # Login frame
        self.login_frame = None
        self.main_frame = None
        self.create_login_frame()

        # Bind global keys
        self.setup_global_shortcuts()

        # Schedule reservation check
        self.root.after(30000, self.check_today_reservations_reminder)

    def setup_global_shortcuts(self):
        """Setup global keyboard shortcuts."""
        self.root.bind('<Control-q>', lambda e: self.quit_app())
        self.root.bind('<Control-l>', lambda e: self.logout())
        self.root.bind('<F1>', lambda e: self.show_help())
        self.root.bind('<F5>', lambda e: self.refresh_current_dialog())
        self.root.bind('<Escape>', lambda e: self.close_active_dialog())

    def close_active_dialog(self):
        """Close the active dialog window."""
        if self.active_dialog and self.active_dialog.winfo_exists():
            self.active_dialog.destroy()
            self.active_dialog = None

    def refresh_current_dialog(self):
        """Refresh the current dialog's data."""
        if self.active_dialog and self.active_dialog.winfo_exists():
            # Find and call refresh function based on dialog title
            title = self.active_dialog.title()
            if "Room Status" in title:
                self.load_room_status_dialog()
            elif "Room Management" in title:
                self.load_rooms_data()
            elif "Active Bookings" in title:
                self.load_active_bookings()
            elif "Reservations" in title:
                self.load_reservations_data()
            elif "Food Orders" in title:
                if hasattr(self, 'current_food_booking'):
                    self.load_food_orders(self.current_food_booking['id'])
            elif "View Bills" in title:
                self.load_all_bills()
            elif "Sales Summary" in title:
                self.load_sales_summary()
            elif "User Management" in title:
                self.load_users_data()
            elif "Settlement" in title:
                self.load_pending_settlements()

    def center_dialog(self, dialog, width, height):
        """Center a dialog window on screen."""
        screen_width = dialog.winfo_screenwidth()
        screen_height = dialog.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        dialog.geometry(f'{width}x{height}+{x}+{y}')

        # Store reference for ESC key
        self.active_dialog = dialog

        # Bind Escape key to close dialog
        dialog.bind('<Escape>', lambda e: self.close_active_dialog())

    def handle_enter_key(self, event, button):
        """Handle Enter key press to click a button."""
        button.invoke()
        return "break"


    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')

        # Modern color scheme for luxury hotel with larger fonts
        primary_color = '#6a4334'  # Dark brown
        secondary_color = '#2e86c1'  # Light blue
        accent_color = '#c0392b'  # Red
        success_color = '#27ae60'  # Green
        warning_color = '#f39c12'  # Orange
        info_color = '#3498db'  # Blue
        light_bg = '#f8f9fa'
        grey_color = '#6c757d'  # Medium grey
        dark_grey = '#5a6268'  # Dark grey for hover

        # Configure styles with larger fonts
        style.configure('TFrame', background=light_bg)
        style.configure('TLabel', background=light_bg, font=('Segoe UI', 11))  # Reduced from 12 to 11
        style.configure('Header.TLabel', background=primary_color, foreground='white',
                        font=('Segoe UI', 18, 'bold'), padding=15)  # Reduced from 20 to 18
        style.configure('Title.TLabel', font=('Segoe UI', 16, 'bold'), foreground=primary_color)
        style.configure('Subtitle.TLabel', font=('Segoe UI', 14, 'bold'), foreground=secondary_color)

        # Configure buttons with grey color scheme and black text
        style.configure('TButton', font=('Segoe UI', 10, 'bold'), padding=6)  # Reduced padding
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
        style.configure('Treeview', font=('Segoe UI', 11), rowheight=30)  # Reduced from 35 to 30
        style.configure('Treeview.Heading', font=('Segoe UI', 12, 'bold'), background=light_bg)  # Reduced from 13 to 12

        # Configure notebook
        style.configure('TNotebook', background=light_bg)
        style.configure('TNotebook.Tab', font=('Segoe UI', 11, 'bold'), padding=[12, 5])  # Reduced from 12 to 11

        self.root.configure(bg=light_bg)

    def clear_frame(self, frame):
        for widget in frame.winfo_children():
            widget.destroy()

    def show_error(self, message):
        messagebox.showerror("Error", message)

    def show_info(self, message):
        messagebox.showinfo("Information", message)

    def show_warning(self, message):
        messagebox.showwarning("Warning", message)

    def ask_confirmation(self, message):
        return messagebox.askyesno("Confirmation", message)

    # Login Page
    def create_login_frame(self):
        if self.main_frame:
            self.main_frame.destroy()

        # Create gradient background
        self.login_frame = tk.Frame(self.root, bg='white')
        self.login_frame.pack(fill=tk.BOTH, expand=True)

        # Left side with hotel branding
        left_frame = tk.Frame(self.login_frame, bg='#6a4334', width=500)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left_frame.pack_propagate(False)

        # Hotel branding with larger fonts
        brand_frame = tk.Frame(left_frame, bg='#6a4334')
        brand_frame.pack(expand=True, pady=100)

        tk.Label(brand_frame, text="THE", font=('Georgia', 28, 'bold'),
                 bg='#6a4334', fg='white').pack()
        tk.Label(brand_frame, text="EVAANI", font=('Georgia', 52, 'bold'),
                 bg='#6a4334', fg='white').pack()
        tk.Label(brand_frame, text="HOTEL", font=('Georgia', 32, 'bold'),
                 bg='#6a4334', fg='white').pack(pady=(0, 20))

        tk.Label(brand_frame, text="Luxury & Comfort", font=('Segoe UI', 18),
                 bg='#6a4334', fg='#d5d8dc').pack()
        tk.Label(brand_frame, text="Billing Management System", font=('Segoe UI', 16),
                 bg='#6a4334', fg='#d5d8dc').pack(pady=(30, 0))

        # Right side with login form
        right_frame = tk.Frame(self.login_frame, bg='white', width=700)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        right_frame.pack_propagate(False)

        # Login form container
        form_container = tk.Frame(right_frame, bg='white')
        form_container.pack(expand=True, padx=100)

        # Form title
        tk.Label(form_container, text="Welcome Back", font=('Segoe UI', 28, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 40))

        # Username field
        tk.Label(form_container, text="Username", font=('Segoe UI', 14),
                 bg='white', fg='#6a4334').pack(anchor='w', pady=(10, 5))
        username_frame = tk.Frame(form_container, bg='white', height=50)
        username_frame.pack(fill=tk.X, pady=(0, 20))
        self.username_entry = tk.Entry(username_frame, font=('Segoe UI', 16),
                                       bd=0, highlightthickness=1, highlightcolor='#2e86c1',
                                       highlightbackground='#ddd', width=30)
        self.username_entry.pack(fill=tk.X, ipady=10)
        self.username_entry.focus()

        # Password field
        tk.Label(form_container, text="Password", font=('Segoe UI', 14),
                 bg='white', fg='#6a4334').pack(anchor='w', pady=(10, 5))
        password_frame = tk.Frame(form_container, bg='white', height=50)
        password_frame.pack(fill=tk.X, pady=(0, 30))
        self.password_entry = tk.Entry(password_frame, font=('Segoe UI', 16),
                                       show="*", bd=0, highlightthickness=1,
                                       highlightcolor='#2e86c1', highlightbackground='#ddd', width=30)
        self.password_entry.pack(fill=tk.X, ipady=10)

        # Login button
        login_btn = tk.Button(form_container, text="LOGIN", font=('Segoe UI', 16, 'bold'),
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
                 font=('Segoe UI', 11), bg='white', fg='#7f8c8d').pack()

    def login(self):
        username = self.username_entry.get()
        password = self.password_entry.get()

        try:
            user = self.auth.login(username, password)
            if user:
                self.login_frame.destroy()
                self.create_main_frame()
            else:
                self.show_error("Invalid username or password!")
        except ValueError as e:
            self.show_error(str(e))

    def create_guest_history_dialog(self, parent):
        """Create full-screen guest history dialog with all user details."""

        # Configure parent for full screen
        parent.configure(bg='white')

        # Create main container with padding
        main_container = tk.Frame(parent, bg='white', padx=20, pady=20)
        main_container.pack(fill=tk.BOTH, expand=True)

        # Title
        title_frame = tk.Frame(main_container, bg='white')
        title_frame.pack(fill=tk.X, pady=(0, 20))

        tk.Label(title_frame, text="👥 GUEST HISTORY",
                 font=('Segoe UI', 24, 'bold'),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT)

        # Search frame - Compact but visible
        search_frame = tk.LabelFrame(main_container, text="Search Guest",
                                     font=('Segoe UI', 14, 'bold'),
                                     bg='white', fg='#6a4334', padx=20, pady=15)
        search_frame.pack(fill=tk.X, pady=(0, 20))

        # Search by options in a single row
        row_frame = tk.Frame(search_frame, bg='white')
        row_frame.pack(fill=tk.X)

        tk.Label(row_frame, text="Search By:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=(0, 10))

        self.guest_search_by = tk.StringVar(value='name')
        search_options = [
            ("Name", 'name'),
            ("Phone", 'phone'),
            ("ID Card", 'id_card')
        ]

        for text, value in search_options:
            tk.Radiobutton(row_frame, text=text, variable=self.guest_search_by,
                           value=value, bg='white', font=('Segoe UI', 11)).pack(side=tk.LEFT, padx=10)

        tk.Label(row_frame, text="Search Term:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=(20, 10))

        self.guest_search_term = tk.Entry(row_frame, font=('Segoe UI', 12), width=25)
        self.guest_search_term.pack(side=tk.LEFT, padx=5)
        self.guest_search_term.bind('<Return>', lambda e: self.search_guest_history())

        search_btn = tk.Button(row_frame, text="🔍 SEARCH",
                               font=('Segoe UI', 11, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.search_guest_history, padx=20, pady=5)
        search_btn.pack(side=tk.LEFT, padx=5)
        search_btn.bind('<Return>', lambda e, b=search_btn: self.handle_enter_key(e, b))

        clear_btn = tk.Button(row_frame, text="🔄 CLEAR",
                              font=('Segoe UI', 11, 'bold'),
                              bg='#95a5a6', fg='black', relief='flat',
                              command=self.clear_guest_search, padx=20, pady=5)
        clear_btn.pack(side=tk.LEFT, padx=5)
        clear_btn.bind('<Return>', lambda e, b=clear_btn: self.handle_enter_key(e, b))

        # Guest Details Panel - Full width with better layout
        self.guest_details_frame = tk.LabelFrame(main_container, text="Guest Details",
                                                 font=('Segoe UI', 16, 'bold'),
                                                 bg='white', fg='#6a4334', padx=20, pady=15)
        self.guest_details_frame.pack(fill=tk.X, pady=(0, 20))
        self.guest_details_frame.pack_forget()  # Hidden initially

        # Create a 3-column layout for guest details
        details_grid = tk.Frame(self.guest_details_frame, bg='white')
        details_grid.pack(fill=tk.X, expand=True)

        # Column 1: Personal Information
        personal_frame = tk.LabelFrame(details_grid, text="👤 Personal Information",
                                       font=('Segoe UI', 13, 'bold'),
                                       bg='white', fg='#2e86c1', padx=15, pady=10)
        personal_frame.grid(row=0, column=0, padx=10, pady=5, sticky='nsew')

        # Personal info labels with larger font
        self.guest_name_label = tk.Label(personal_frame, text="Name: ",
                                         font=('Segoe UI', 12, 'bold'),
                                         bg='white', fg='#333333', anchor='w')
        self.guest_name_label.pack(fill=tk.X, pady=3)

        self.guest_phone_label = tk.Label(personal_frame, text="Phone: ",
                                          font=('Segoe UI', 12),
                                          bg='white', fg='#333333', anchor='w')
        self.guest_phone_label.pack(fill=tk.X, pady=3)

        self.guest_email_label = tk.Label(personal_frame, text="Email: ",
                                          font=('Segoe UI', 12),
                                          bg='white', fg='#333333', anchor='w')
        self.guest_email_label.pack(fill=tk.X, pady=3)

        self.guest_id_card_label = tk.Label(personal_frame, text="ID Card: ",
                                            font=('Segoe UI', 12),
                                            bg='white', fg='#333333', anchor='w')
        self.guest_id_card_label.pack(fill=tk.X, pady=3)

        self.guest_address_label = tk.Label(personal_frame, text="Address: ",
                                            font=('Segoe UI', 12),
                                            bg='white', fg='#333333', anchor='w', wraplength=300)
        self.guest_address_label.pack(fill=tk.X, pady=3)

        # Column 2: Company Information
        company_frame = tk.LabelFrame(details_grid, text="🏢 Company Information",
                                      font=('Segoe UI', 13, 'bold'),
                                      bg='white', fg='#27ae60', padx=15, pady=10)
        company_frame.grid(row=0, column=1, padx=10, pady=5, sticky='nsew')

        self.guest_company_label = tk.Label(company_frame, text="Company: ",
                                            font=('Segoe UI', 12),
                                            bg='white', fg='#333333', anchor='w')
        self.guest_company_label.pack(fill=tk.X, pady=3)

        self.guest_company_address_label = tk.Label(company_frame, text="Company Address: ",
                                                    font=('Segoe UI', 12),
                                                    bg='white', fg='#333333', anchor='w', wraplength=300)
        self.guest_company_address_label.pack(fill=tk.X, pady=3)

        self.guest_party_gstin_label = tk.Label(company_frame, text="Party GSTIN: ",
                                                font=('Segoe UI', 12),
                                                bg='white', fg='#333333', anchor='w')
        self.guest_party_gstin_label.pack(fill=tk.X, pady=3)

        # Column 3: Statistics
        stats_frame = tk.LabelFrame(details_grid, text="📊 Statistics",
                                    font=('Segoe UI', 13, 'bold'),
                                    bg='white', fg='#c0392b', padx=15, pady=10)
        stats_frame.grid(row=0, column=2, padx=10, pady=5, sticky='nsew')

        self.guest_total_stays_label = tk.Label(stats_frame, text="Total Stays: 0",
                                                font=('Segoe UI', 12, 'bold'),
                                                bg='white', fg='#2e86c1', anchor='w')
        self.guest_total_stays_label.pack(fill=tk.X, pady=3)

        self.guest_total_spent_label = tk.Label(stats_frame, text="Total Spent: ₹0.00",
                                                font=('Segoe UI', 12, 'bold'),
                                                bg='white', fg='#27ae60', anchor='w')
        self.guest_total_spent_label.pack(fill=tk.X, pady=3)

        self.guest_total_advance_label = tk.Label(stats_frame, text="Total Advance: ₹0.00",
                                                  font=('Segoe UI', 12),
                                                  bg='white', fg='#333333', anchor='w')
        self.guest_total_advance_label.pack(fill=tk.X, pady=3)

        self.guest_total_paid_label = tk.Label(stats_frame, text="Total Paid: ₹0.00",
                                               font=('Segoe UI', 12),
                                               bg='white', fg='#333333', anchor='w')
        self.guest_total_paid_label.pack(fill=tk.X, pady=3)

        self.guest_total_discount_label = tk.Label(stats_frame, text="Total Discount: ₹0.00",
                                                   font=('Segoe UI', 12),
                                                   bg='white', fg='#e74c3c', anchor='w')
        self.guest_total_discount_label.pack(fill=tk.X, pady=3)

        # Configure grid weights
        details_grid.grid_columnconfigure(0, weight=1)
        details_grid.grid_columnconfigure(1, weight=1)
        details_grid.grid_columnconfigure(2, weight=1)

        # Notebook for tabs - takes remaining space
        notebook = ttk.Notebook(main_container)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # ========== BOOKINGS TAB ==========
        bookings_tab = ttk.Frame(notebook)
        notebook.add(bookings_tab, text="📋 BOOKING HISTORY")

        # Create frame for bookings with scrollbars
        bookings_frame = tk.Frame(bookings_tab, bg='white')
        bookings_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Create Treeview with scrollbars for bookings
        bookings_tree_frame = tk.Frame(bookings_frame, bg='white')
        bookings_tree_frame.pack(fill=tk.BOTH, expand=True)

        # Vertical scrollbar
        v_scroll_bookings = ttk.Scrollbar(bookings_tree_frame)
        v_scroll_bookings.pack(side=tk.RIGHT, fill=tk.Y)

        # Horizontal scrollbar
        h_scroll_bookings = ttk.Scrollbar(bookings_tree_frame, orient=tk.HORIZONTAL)
        h_scroll_bookings.pack(side=tk.BOTTOM, fill=tk.X)

        # Enhanced columns for bookings - more columns for full screen
        bookings_columns = ('ID', 'Date', 'Room No', 'Room Type', 'Check-in', 'Check-out',
                            'Nights', 'Total (₹)', 'Advance (₹)', 'Paid (₹)', 'Discount (₹)',
                            'Balance (₹)', 'Status', 'Created By')

        self.guest_bookings_tree = ttk.Treeview(bookings_tree_frame, columns=bookings_columns,
                                                yscrollcommand=v_scroll_bookings.set,
                                                xscrollcommand=h_scroll_bookings.set,
                                                height=12, show='headings')

        v_scroll_bookings.config(command=self.guest_bookings_tree.yview)
        h_scroll_bookings.config(command=self.guest_bookings_tree.xview)

        # Configure columns with appropriate widths for full screen
        column_widths = {
            'ID': 60,
            'Date': 100,
            'Room No': 80,
            'Room Type': 100,
            'Check-in': 150,
            'Check-out': 150,
            'Nights': 70,
            'Total (₹)': 100,
            'Advance (₹)': 100,
            'Paid (₹)': 100,
            'Discount (₹)': 100,
            'Balance (₹)': 100,
            'Status': 100,
            'Created By': 120
        }

        for col in bookings_columns:
            self.guest_bookings_tree.heading(col, text=col, anchor=tk.W)
            self.guest_bookings_tree.column(col, width=column_widths.get(col, 100), minwidth=60)

        self.guest_bookings_tree.pack(fill=tk.BOTH, expand=True)

        # ========== BILLS TAB ==========
        bills_tab = ttk.Frame(notebook)
        notebook.add(bills_tab, text="💰 BILL HISTORY")

        # Create frame for bills with scrollbars
        bills_frame = tk.Frame(bills_tab, bg='white')
        bills_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Treeview frame for bills
        bills_tree_frame = tk.Frame(bills_frame, bg='white')
        bills_tree_frame.pack(fill=tk.BOTH, expand=True)

        # Scrollbars for bills
        v_scroll_bills = ttk.Scrollbar(bills_tree_frame)
        v_scroll_bills.pack(side=tk.RIGHT, fill=tk.Y)

        h_scroll_bills = ttk.Scrollbar(bills_tree_frame, orient=tk.HORIZONTAL)
        h_scroll_bills.pack(side=tk.BOTTOM, fill=tk.X)

        # Enhanced columns for bills - more columns for full screen
        bills_columns = ('Bill No', 'Date', 'Room No', 'Check-in', 'Check-out',
                         'Total (₹)', 'Advance (₹)', 'Paid (₹)', 'Discount (₹)',
                         'Settled (₹)', 'Balance (₹)', 'Status', 'Verified By')

        self.guest_bills_tree = ttk.Treeview(bills_tree_frame, columns=bills_columns,
                                             yscrollcommand=v_scroll_bills.set,
                                             xscrollcommand=h_scroll_bills.set,
                                             height=12, show='headings')

        v_scroll_bills.config(command=self.guest_bills_tree.yview)
        h_scroll_bills.config(command=self.guest_bills_tree.xview)

        # Configure column widths for bills
        bill_column_widths = {
            'Bill No': 180,
            'Date': 150,
            'Room No': 80,
            'Check-in': 150,
            'Check-out': 150,
            'Total (₹)': 110,
            'Advance (₹)': 110,
            'Paid (₹)': 110,
            'Discount (₹)': 110,
            'Settled (₹)': 110,
            'Balance (₹)': 110,
            'Status': 100,
            'Verified By': 120
        }

        for col in bills_columns:
            self.guest_bills_tree.heading(col, text=col, anchor=tk.W)
            self.guest_bills_tree.column(col, width=bill_column_widths.get(col, 100), minwidth=70)

        self.guest_bills_tree.pack(fill=tk.BOTH, expand=True)

        # Action buttons frame - at bottom
        button_frame = tk.Frame(main_container, bg='white')
        button_frame.pack(fill=tk.X, pady=10)

        # Left side buttons
        left_buttons = tk.Frame(button_frame, bg='white')
        left_buttons.pack(side=tk.LEFT)

        view_bill_btn = tk.Button(left_buttons, text="👁️ VIEW SELECTED BILL",
                                  font=('Segoe UI', 12, 'bold'),
                                  bg='#2e86c1', fg='black', relief='flat',
                                  command=self.view_selected_guest_bill, padx=25, pady=10)
        view_bill_btn.pack(side=tk.LEFT, padx=5)
        view_bill_btn.bind('<Return>', lambda e, b=view_bill_btn: self.handle_enter_key(e, b))

        export_btn = tk.Button(left_buttons, text="📊 EXPORT HISTORY",
                               font=('Segoe UI', 12, 'bold'),
                               bg='#27ae60', fg='black', relief='flat',
                               command=self.export_guest_history, padx=25, pady=10)
        export_btn.pack(side=tk.LEFT, padx=5)
        export_btn.bind('<Return>', lambda e, b=export_btn: self.handle_enter_key(e, b))

        quick_checkin_btn = tk.Button(left_buttons, text="🔑 QUICK CHECK-IN",
                                      font=('Segoe UI', 12, 'bold'),
                                      bg='#f39c12', fg='black', relief='flat',
                                      command=self.quick_checkin_from_history, padx=25, pady=10)
        quick_checkin_btn.pack(side=tk.LEFT, padx=5)
        quick_checkin_btn.bind('<Return>', lambda e, b=quick_checkin_btn: self.handle_enter_key(e, b))

        # Right side buttons
        right_buttons = tk.Frame(button_frame, bg='white')
        right_buttons.pack(side=tk.RIGHT)

        clear_results_btn = tk.Button(right_buttons, text="🗑️ CLEAR RESULTS",
                                      font=('Segoe UI', 12, 'bold'),
                                      bg='#e74c3c', fg='black', relief='flat',
                                      command=self.clear_guest_results, padx=25, pady=10)
        clear_results_btn.pack(side=tk.RIGHT, padx=5)
        clear_results_btn.bind('<Return>', lambda e, b=clear_results_btn: self.handle_enter_key(e, b))

        # Set focus to search entry
        self.guest_search_term.focus()

    def search_guest_history(self):
        """Search and display guest history with all user details."""
        search_term = self.guest_search_term.get().strip()
        search_by = self.guest_search_by.get()

        if not search_term:
            self.show_warning("Please enter a search term")
            return

        # Clear existing data
        for item in self.guest_bookings_tree.get_children():
            self.guest_bookings_tree.delete(item)

        for item in self.guest_bills_tree.get_children():
            self.guest_bills_tree.delete(item)

        # Hide guest details frame initially
        self.guest_details_frame.pack_forget()

        try:
            # Get guest history from bookings
            bookings = self.hotel.get_guest_history(search_term, search_by)

            if not bookings:
                self.show_info(f"No guest found with {search_by}: {search_term}")
                return

            # Get the most recent booking for guest details
            latest_booking = bookings[0]

            # Display guest details in the details panel
            self.guest_name_label.config(text=f"Name: {latest_booking.get('guest_name', 'N/A')}")
            self.guest_phone_label.config(text=f"Phone: {latest_booking.get('guest_phone', 'N/A')}")
            self.guest_email_label.config(text=f"Email: {latest_booking.get('guest_email', 'N/A')}")
            self.guest_id_card_label.config(text=f"ID Card: {latest_booking.get('guest_id_card', 'N/A')}")
            self.guest_address_label.config(text=f"Address: {latest_booking.get('guest_address', 'N/A')}")

            self.guest_company_label.config(text=f"Company: {latest_booking.get('company_name', 'N/A')}")
            self.guest_company_address_label.config(
                text=f"Company Address: {latest_booking.get('company_address', 'N/A')}")
            self.guest_party_gstin_label.config(text=f"Party GSTIN: {latest_booking.get('party_gstin', 'N/A')}")

            # Show the details frame
            self.guest_details_frame.pack(fill=tk.X, pady=(0, 10), padx=10)

            # Display bookings
            total_stays = 0
            total_spent = 0.0
            total_advance = 0.0
            total_paid = 0.0
            total_discount = 0.0

            for booking in bookings:
                check_in = booking.get('check_in_time', '')
                check_out = booking.get('check_out_time', '')

                if check_in:
                    try:
                        check_in = datetime.fromisoformat(check_in).strftime('%Y-%m-%d %H:%M')
                    except:
                        pass

                if check_out:
                    try:
                        check_out = datetime.fromisoformat(check_out).strftime('%Y-%m-%d %H:%M')
                    except:
                        pass
                else:
                    check_out = '-'

                # Calculate nights
                nights = 0
                if booking.get('check_in_time') and booking.get('check_out_time'):
                    try:
                        check_in_dt = datetime.fromisoformat(booking['check_in_time'])
                        check_out_dt = datetime.fromisoformat(booking['check_out_time'])
                        nights = (check_out_dt - check_in_dt).days
                        if nights < 1:
                            nights = 1
                    except:
                        nights = booking.get('total_hours', 0) // 24 if booking.get('total_hours') else 1

                booking_total = booking.get('total_amount', 0.0)
                advance = booking.get('advance_payment', 0.0)
                paid = booking.get('total_paid', 0.0) or 0.0
                discount = booking.get('total_discount', 0.0) or 0.0

                total_stays += 1
                total_spent += booking_total
                total_advance += advance
                total_paid += paid
                total_discount += discount

                created_at = booking.get('created_at', '')
                if created_at:
                    created_at = created_at[:10] if len(created_at) >= 10 else created_at

                created_by = booking.get('created_by_name', '')

                values = (
                    booking['id'],
                    created_at,
                    booking['room_number'],
                    booking.get('room_type', ''),
                    check_in,
                    check_out,
                    nights,
                    f"₹{booking_total:.2f}",
                    f"₹{advance:.2f}",
                    f"₹{paid:.2f}",
                    f"₹{discount:.2f}",
                    booking.get('status', '').upper(),
                    created_by
                )
                self.guest_bookings_tree.insert('', tk.END, values=values)

            # Update statistics
            self.guest_total_stays_label.config(text=f"Total Stays: {total_stays}")
            self.guest_total_spent_label.config(text=f"Total Spent: ₹{total_spent:.2f}")
            self.guest_total_advance_label.config(text=f"Total Advance: ₹{total_advance:.2f}")
            self.guest_total_paid_label.config(text=f"Total Paid: ₹{total_paid:.2f}")
            self.guest_total_discount_label.config(text=f"Total Discount: ₹{total_discount:.2f}")

            # Get and display bills
            guest_name = latest_booking.get('guest_name', '')
            guest_phone = latest_booking.get('guest_phone', '')
            guest_id = latest_booking.get('guest_id_card', '')

            if guest_name or guest_phone or guest_id:
                bills = self.hotel.get_guest_bills(guest_name, guest_phone, guest_id)

                for bill in bills:
                    bill_date = bill.get('bill_date', '')
                    if bill_date:
                        try:
                            bill_date = datetime.fromisoformat(bill_date).strftime('%Y-%m-%d %H:%M')
                        except:
                            pass

                    check_in = bill.get('check_in_time', '')
                    check_out = bill.get('check_out_time', '')

                    if check_in:
                        try:
                            check_in = datetime.fromisoformat(check_in).strftime('%Y-%m-%d %H:%M')
                        except:
                            pass

                    if check_out:
                        try:
                            check_out = datetime.fromisoformat(check_out).strftime('%Y-%m-%d %H:%M')
                        except:
                            pass

                    advance = bill.get('advance_paid', 0.0)
                    paid = bill.get('total_paid', 0.0) or 0.0
                    discount = bill.get('total_discount', 0.0) or 0.0
                    settled = paid
                    balance = bill.get('balance_due', 0.0)
                    verified_by = bill.get('verified_by', '')

                    values = (
                        bill['bill_number'],
                        bill_date,
                        bill['room_number'],
                        check_in,
                        check_out,
                        f"₹{bill['total_amount']:.2f}",
                        f"₹{advance:.2f}",
                        f"₹{paid:.2f}",
                        f"₹{discount:.2f}",
                        f"₹{settled:.2f}",
                        f"₹{balance:.2f}",
                        bill['payment_status'].upper(),
                        verified_by
                    )
                    self.guest_bills_tree.insert('', tk.END, values=values)

            # Update scrollregion after adding all data
            self.guest_details_frame.update_idletasks()
            scrollable_frame = self.guest_details_frame.master
            while scrollable_frame:
                if hasattr(scrollable_frame, 'configure') and hasattr(scrollable_frame, 'winfo_parent'):
                    try:
                        scrollable_frame.configure(scrollregion=scrollable_frame.bbox("all"))
                    except:
                        pass
                    scrollable_frame = scrollable_frame.master
                else:
                    break

        except Exception as e:
            self.show_error(f"Error searching guest history: {str(e)}")
            import traceback
            traceback.print_exc()

    def clear_guest_search(self):
        """Clear guest search fields."""
        self.guest_search_term.delete(0, tk.END)
        self.guest_search_by.set('name')
        self.clear_guest_results()

    def clear_guest_results(self):
        """Clear guest history results."""
        for item in self.guest_bookings_tree.get_children():
            self.guest_bookings_tree.delete(item)

        for item in self.guest_bills_tree.get_children():
            self.guest_bills_tree.delete(item)

        self.guest_summary_label.config(text="")

    def view_selected_guest_bill(self):
        """View selected bill from guest history."""
        if not self.guest_bills_tree.selection():
            self.show_warning("Please select a bill to view")
            return

        selection = self.guest_bills_tree.selection()
        bill_number = self.guest_bills_tree.item(selection[0])['values'][0]

        try:
            bill_details = self.hotel.get_bill_by_number(bill_number)

            if bill_details:
                # Get day breakdowns
                day_breakdowns = self.hotel.get_daily_breakdown(bill_details['id'])

                settings = self.hotel.get_hotel_settings()
                bill_details.update(settings)
                self.bill_generator.set_hotel_manager(self.hotel)
                self.bill_generator.print_bill(bill_details, day_breakdowns)
            else:
                self.show_error("Bill details not found!")
        except Exception as e:
            self.show_error(f"Error viewing bill: {str(e)}")

    def export_guest_history(self):
        """Export complete guest history with all details to CSV."""
        if not self.guest_bookings_tree.get_children():
            self.show_warning("No guest history to export")
            return

        try:
            # Get guest details
            guest_name = self.guest_name_label.cget("text").replace("Name: ", "")
            if guest_name == "N/A":
                guest_name = "Guest"

            filename = f"guest_history_{guest_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)

                # Header
                writer.writerow(['THE EVAANI HOTEL - COMPLETE GUEST HISTORY'])
                writer.writerow(['Generated:', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
                writer.writerow([])

                # Guest Details
                writer.writerow(['GUEST DETAILS'])
                writer.writerow(['Name:', self.guest_name_label.cget("text").replace("Name: ", "")])
                writer.writerow(['Phone:', self.guest_phone_label.cget("text").replace("Phone: ", "")])
                writer.writerow(['Email:', self.guest_email_label.cget("text").replace("Email: ", "")])
                writer.writerow(['ID Card:', self.guest_id_card_label.cget("text").replace("ID Card: ", "")])
                writer.writerow(['Address:', self.guest_address_label.cget("text").replace("Address: ", "")])
                writer.writerow([])

                # Company Details
                writer.writerow(['COMPANY DETAILS'])
                writer.writerow(['Company Name:', self.guest_company_label.cget("text").replace("Company: ", "")])
                writer.writerow(['Company Address:',
                                 self.guest_company_address_label.cget("text").replace("Company Address: ", "")])
                writer.writerow(
                    ['Party GSTIN:', self.guest_party_gstin_label.cget("text").replace("Party GSTIN: ", "")])
                writer.writerow([])

                # Statistics
                writer.writerow(['STATISTICS'])
                writer.writerow(
                    ['Total Stays:', self.guest_total_stays_label.cget("text").replace("Total Stays: ", "")])
                writer.writerow(
                    ['Total Spent:', self.guest_total_spent_label.cget("text").replace("Total Spent: ", "")])
                writer.writerow(
                    ['Total Advance:', self.guest_total_advance_label.cget("text").replace("Total Advance: ", "")])
                writer.writerow(['Total Paid:', self.guest_total_paid_label.cget("text").replace("Total Paid: ", "")])
                writer.writerow(
                    ['Total Discount:', self.guest_total_discount_label.cget("text").replace("Total Discount: ", "")])
                writer.writerow([])

                # Bookings
                writer.writerow(['BOOKING HISTORY'])
                writer.writerow(['ID', 'Date', 'Room No', 'Room Type', 'Check-in', 'Check-out',
                                 'Nights', 'Total (₹)', 'Advance (₹)', 'Paid (₹)', 'Discount (₹)',
                                 'Status', 'Created By'])

                for item in self.guest_bookings_tree.get_children():
                    values = self.guest_bookings_tree.item(item)['values']
                    writer.writerow(values)

                writer.writerow([])

                # Bills
                writer.writerow(['BILL HISTORY'])
                writer.writerow(['Bill No', 'Date', 'Room No', 'Check-in', 'Check-out',
                                 'Total (₹)', 'Advance (₹)', 'Paid (₹)', 'Discount (₹)',
                                 'Settled (₹)', 'Balance (₹)', 'Status', 'Verified By'])

                for item in self.guest_bills_tree.get_children():
                    values = self.guest_bills_tree.item(item)['values']
                    writer.writerow(values)

            self.show_info(f"✅ Complete guest history exported to:\n{filename}")

        except Exception as e:
            self.show_error(f"Error exporting guest history: {str(e)}")

    # Main Application Frame with Centered Buttons
    def create_main_frame(self):
        """Create main menu with centered buttons - transparent backgrounds with image."""
        self.main_frame = tk.Frame(self.root, bg='#f8f9fa')
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # Create header
        self.create_header()

        # Main container
        main_container = tk.Frame(self.main_frame, bg='#f8f9fa')
        main_container.pack(fill=tk.BOTH, expand=True)

        # BACKGROUND IMAGE - FULL SCREEN
        try:
            # Get current screen dimensions
            screen_width = self.root.winfo_width()
            screen_height = self.root.winfo_height()

            if screen_width <= 1 or screen_height <= 1:
                screen_width = 1600
                screen_height = 900

            img = Image.open("resort.jpg")
            img = img.resize((screen_width, screen_height), Image.Resampling.LANCZOS)
            self.bg_photo = ImageTk.PhotoImage(img)

            bg_label = tk.Label(main_container, image=self.bg_photo, bg='#f8f9fa')
            bg_label.place(x=0, y=0, relwidth=1, relheight=1)

            def resize_background(event):
                if event.width > 1 and event.height > 1:
                    new_img = Image.open("resort.jpg")
                    new_img = new_img.resize((event.width, event.height), Image.Resampling.LANCZOS)
                    new_photo = ImageTk.PhotoImage(new_img)
                    bg_label.config(image=new_photo)
                    bg_label.image = new_photo
                    self.bg_photo = new_photo

            main_container.bind('<Configure>', resize_background)

        except Exception as e:
            print(f"Could not load background image: {e}")
            bg_label = tk.Label(main_container, bg='#f8f9fa')
            bg_label.place(x=0, y=0, relwidth=1, relheight=1)

        # ALL CONTENT PLACED DIRECTLY ON IMAGE - NO BACKGROUND FRAMES
        # Title
        title_label = tk.Label(main_container,
                               text="HOTEL BILLING MANAGEMENT SYSTEM",
                               font=('Segoe UI', 28, 'bold'),
                               bg='#f8f9fa',
                               fg='black',  # Changed to white for visibility
                               bd=0)
        title_label.place(relx=0.5, rely=0.10, anchor=tk.CENTER)

        # Subtitle
        if self.auth.is_admin():
            subtitle_text = f"Welcome, {self.auth.current_user['username'].upper()} (ADMINISTRATOR)"
        else:
            subtitle_text = f"Welcome, {self.auth.current_user['username'].upper()} (FRONT DESK)"

        subtitle = tk.Label(main_container,
                            text=subtitle_text,
                            font=('Segoe UI', 18),
                            bg='#f8f9fa',
                            fg='black',  # Changed to white for visibility
                            bd=0)
        subtitle.place(relx=0.5, rely=0.16, anchor=tk.CENTER)

        # Define buttons based on user role
        grey_color = '#6c757d'
        dark_grey = '#5a6268'

        if self.auth.is_admin():
            left_buttons = [
                ('F1', '📊 DASHBOARD', 'dashboard', grey_color),
                ('F2', '🏨 ROOM MANAGEMENT', 'rooms', grey_color),
                ('F3', '🚪 ROOM STATUS', 'room_status', grey_color),
                ('F4', '🔑 CHECK-IN/OUT', 'checkinout', grey_color),
                ('F5', '📅 VIEW RESERVATIONS', 'reservations', grey_color),
                ('F6', '📋 ACTIVE BOOKINGS', 'bookings', grey_color),
                ('F7', '👥 GUEST HISTORY', 'guest_history', grey_color)
            ]

            right_buttons = [
                ('F8', '🍽️ FOOD ORDERS', 'food_orders', grey_color),
                ('F9', '🧾 GENERATE BILL', 'generate_bill', grey_color),
                ('F10', '📄 VIEW BILLS', 'view_bills', grey_color),
                ('F11', '💰 SALES SUMMARY', 'sales', grey_color),
                ('F12', '🤝 SETTLEMENTS', 'settlements', grey_color),
                ('Ctrl+J', '👥 USER MANAGEMENT', 'users', grey_color),
                ('Ctrl+K', '⚙️ SETTINGS', 'settings', grey_color)
            ]
        else:
            left_buttons = [
                ('F1', '🔑 CHECK-IN GUEST', 'checkin', grey_color),
                ('F2', '🚪 CHECK-OUT GUEST', 'checkout', grey_color),
                ('F3', '📅 MAKE RESERVATION', 'reservations', grey_color),
                ('F4', '🚪 ROOM STATUS', 'room_status', grey_color),
                ('F5', '👥 GUEST HISTORY', 'guest_history', grey_color)
            ]

            right_buttons = [
                ('F6', '🍽️ FOOD ORDERS', 'food_orders', grey_color),
                ('F7', '🧾 GENERATE BILL', 'generate_bill', grey_color),
                ('F8', '📄 VIEW BILLS', 'view_bills', grey_color),
                ('F9', '🤝 SETTLEMENTS', 'settlements', grey_color)
            ]

        # Place left column buttons - LARGER SIZE
        for i, (shortcut, text, command_id, color) in enumerate(left_buttons):
            y_pos = 0.24 + (i * 0.055)  # Adjusted spacing for larger buttons

            # Shortcut badge - INCREASED SIZE
            if shortcut:  # Only create badge if shortcut exists
                badge = tk.Label(main_container,
                                 text=shortcut,
                                 font=('Segoe UI', 11, 'bold'),  # Increased font
                                 bg='#6a4334',
                                 fg='white',
                                 width=4,  # Increased width
                                 height=2,  # Increased height
                                 relief=tk.FLAT,
                                 bd=0)
                badge.place(relx=0.28, rely=y_pos, anchor=tk.E)

            # Main button - INCREASED SIZE
            btn = tk.Button(main_container,
                            text=text,
                            font=('Segoe UI', 13, 'bold'),  # Increased from 11
                            bg=color,
                            fg='black',
                            activebackground=dark_grey,
                            activeforeground='black',
                            relief=tk.RAISED,
                            bd=2,  # Increased border
                            cursor='hand2',
                            width=28,  # Increased width
                            height=2,  # Increased height from 1 to 2
                            command=lambda c=command_id: self.open_function_dialog(c))

            if shortcut:
                btn.place(relx=0.29, rely=y_pos, anchor=tk.W)
                btn.shortcut_key = shortcut
            else:
                btn.place(relx=0.295, rely=y_pos, anchor=tk.CENTER)  # Center if no shortcut

        # Place right column buttons - LARGER SIZE
        for i, (shortcut, text, command_id, color) in enumerate(right_buttons):
            y_pos = 0.24 + (i * 0.055)  # Same spacing as left column

            # Shortcut badge - INCREASED SIZE
            if shortcut:  # Only create badge if shortcut exists
                badge = tk.Label(main_container,
                                 text=shortcut,
                                 font=('Segoe UI', 11, 'bold'),  # Increased font
                                 bg='#6a4334',
                                 fg='white',
                                 width=4,  # Increased width
                                 height=2,  # Increased height
                                 relief=tk.FLAT,
                                 bd=0)
                badge.place(relx=0.58, rely=y_pos, anchor=tk.E)

            # Main button - INCREASED SIZE
            btn = tk.Button(main_container,
                            text=text,
                            font=('Segoe UI', 13, 'bold'),  # Increased from 11
                            bg=color,
                            fg='black',
                            activebackground=dark_grey,
                            activeforeground='black',
                            relief=tk.RAISED,
                            bd=2,  # Increased border
                            cursor='hand2',
                            width=28,  # Increased width
                            height=2,  # Increased height from 1 to 2
                            command=lambda c=command_id: self.open_function_dialog(c))

            if shortcut:
                btn.place(relx=0.59, rely=y_pos, anchor=tk.W)
                btn.shortcut_key = shortcut
            else:
                btn.place(relx=0.595, rely=y_pos, anchor=tk.CENTER)  # Center if no shortcut

        # Setup keyboard shortcuts
        all_buttons = left_buttons + right_buttons
        self.setup_shortcuts(all_buttons)

        # Status bar (this remains with color background)
        status_bar = tk.Frame(self.main_frame, bg='#6a4334', height=30)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        status_bar.pack_propagate(False)

        status_text = f"Logged in as: {self.auth.current_user['username']} | Role: {self.auth.current_user['role']} | Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        tk.Label(status_bar, text=status_text, font=('Segoe UI', 10),
                 bg='#6a4334', fg='white').pack(side=tk.LEFT, padx=20, pady=4)

        # Force initial resize
        self.root.update_idletasks()
        main_container.event_generate('<Configure>')

    def setup_shortcuts(self, buttons):
        """Setup keyboard shortcuts including F-keys and Ctrl+ combinations."""
        # Unbind existing shortcuts
        for i in range(1, 14):
            self.root.unbind(f'<F{i}>')

        # Unbind Ctrl combinations
        self.root.unbind('<Control-j>')
        self.root.unbind('<Control-J>')
        self.root.unbind('<Control-k>')
        self.root.unbind('<Control-K>')

        # Bind shortcuts based on buttons list
        for shortcut, _, command_id, _ in buttons:
            if shortcut.startswith('F') and shortcut[1:].isdigit():
                # Bind F-keys
                key_num = shortcut[1:]
                self.root.bind(f'<F{key_num}>', lambda e, c=command_id: self.open_function_dialog(c))
            elif shortcut == 'Ctrl+J' or shortcut == 'Ctrl+j':
                # Bind Ctrl+J (case insensitive)
                self.root.bind('<Control-j>', lambda e, c=command_id: self.open_function_dialog(c))
                self.root.bind('<Control-J>', lambda e, c=command_id: self.open_function_dialog(c))
            elif shortcut == 'Ctrl+K' or shortcut == 'Ctrl+k':
                # Bind Ctrl+K (case insensitive)
                self.root.bind('<Control-k>', lambda e, c=command_id: self.open_function_dialog(c))
                self.root.bind('<Control-K>', lambda e, c=command_id: self.open_function_dialog(c))

        # Also add global help for Ctrl shortcuts
        self.root.bind('<Control-h>', lambda e: self.show_help())

    def open_function_dialog(self, function_id):
        """Open a dialog for the selected function."""
        # Close existing dialog if any
        self.close_active_dialog()

        # Create new dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(f"The Evaani Hotel - {self.get_function_title(function_id)}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg='white')

        # Get function to determine dialog size (larger for better readability)
        dialog_size = self.get_function_dialog_size(function_id)
        self.center_dialog(dialog, dialog_size[0], dialog_size[1])

        # Create content
        self.create_function_content(dialog, function_id)

        # Add close button
        close_btn = tk.Button(dialog, text="✕ CLOSE (ESC)", font=('Segoe UI', 12, 'bold'),
                              bg='#c0392b', fg='black', activebackground='#a93226',
                              activeforeground='white', relief='flat', cursor='hand2',
                              command=self.close_active_dialog, padx=15, pady=8)
        close_btn.place(relx=1.0, x=-20, y=20, anchor=tk.NE)

    def get_function_title(self, function_id):
        """Get display title for function."""
        titles = {
            'dashboard': 'Dashboard',
            'rooms': 'Room Management',
            'room_status': 'Room Status',
            'checkinout': 'Check-in/Check-out',
            'checkin': 'Check-in Guest',
            'checkout': 'Check-out Guest',
            'guest_history': 'Guest History',
            'reservations': 'Reservations' if self.auth.is_admin() else 'Make Reservation',
            'bookings': 'Active Bookings',
            'food_orders': 'Food Orders',
            'generate_bill': 'Generate Bill',
            'view_bills': 'View Bills',
            'sales': 'Sales Summary',
            'settlements': 'Settlement Management',
            'users': 'User Management',
            'settings': 'Hotel Settings',
            'export': 'Export Data'
        }
        return titles.get(function_id, function_id.replace('_', ' ').title())

    def get_function_dialog_size(self, function_id):
        """Get appropriate dialog size for each function (larger sizes)."""
        sizes = {
            'dashboard': (1100, 800),
            'rooms': (1200, 800),
            'room_status': (1200, 800),
            'checkinout': (1100, 900),
            'checkin': (800, 900),
            'checkout': (800, 700),
            'reservations': (1200, 700),
            'bookings': (1200, 700),
            'guest_history': (1300, 800),
            'food_orders': (1200, 800),
            'generate_bill': (1300, 800),
            'view_bills': (1300, 800),
            'sales': (1100, 800),
            'settlements': (1200, 700),
            'users': (1100, 700),
            'settings': (800, 700),
            'export': (700, 600)
        }
        return sizes.get(function_id, (1000, 700))

    def create_function_content(self, parent, function_id):
        """Create content for function dialog."""
        # Clear parent
        for widget in parent.winfo_children():
            if widget != parent.winfo_children()[-1]:  # Keep close button
                widget.destroy()

        # Main container
        main_container = tk.Frame(parent, bg='white', padx=25, pady=25)
        main_container.pack(fill=tk.BOTH, expand=True)

        # Title with larger font
        title_label = tk.Label(main_container, text=self.get_function_title(function_id).upper(),
                               font=('Segoe UI', 22, 'bold'),
                               bg='white', fg='#6a4334')
        title_label.pack(pady=(0, 25), anchor=tk.W)

        # Create content based on function_id
        if function_id == 'dashboard':
            self.create_dashboard_dialog(main_container)
        elif function_id == 'rooms':
            self.create_rooms_dialog(main_container)
        elif function_id == 'room_status':
            self.create_room_status_dialog(main_container)
        elif function_id == 'checkinout':
            self.create_checkinout_dialog(main_container)
        elif function_id == 'checkin':
            self.create_checkin_dialog(main_container)
        elif function_id == 'checkout':
            self.create_checkout_dialog(main_container)
        elif function_id == 'guest_history':
            self.create_guest_history_dialog(main_container)
        elif function_id == 'reservations':
            if self.auth.is_admin():
                self.create_reservations_view_dialog(main_container)
            else:
                self.create_reservations_form_dialog(main_container)
        elif function_id == 'bookings':
            self.create_bookings_dialog(main_container)
        elif function_id == 'food_orders':
            self.create_food_orders_dialog(main_container)
        elif function_id == 'generate_bill':
            self.create_generate_bill_dialog(main_container)
        elif function_id == 'view_bills':
            self.create_view_bills_dialog(main_container)
        elif function_id == 'sales':
            self.create_sales_dialog(main_container)
        elif function_id == 'settlements':
            self.create_settlements_dialog(main_container)
        elif function_id == 'users' and self.auth.is_admin():
            self.create_users_dialog(main_container)
        elif function_id == 'settings' and self.auth.is_admin():
            self.create_settings_dialog(main_container)
        elif function_id == 'export' and self.auth.is_admin():
            self.create_export_dialog(main_container)

    # Dashboard Dialog
    def create_dashboard_dialog(self, parent):
        """Create dashboard in dialog."""
        # Stats cards
        stats_frame = tk.Frame(parent, bg='white')
        stats_frame.pack(fill=tk.X, pady=(0, 25))

        try:
            rooms = self.hotel.get_all_rooms()
            room_counts = self.hotel.get_room_status_counts()
            active_bookings = self.hotel.get_active_bookings()
            reservations = self.hotel.get_reservations()
            today = datetime.now().strftime('%Y-%m-%d')
            bills_today = self.hotel.get_all_bills(today, today)
            pending_settlements = self.hotel.get_pending_settlements()

            stats_data = [
                ("Total Rooms", len(rooms), "#2e86c1", "🏨"),
                ("Available", room_counts.get('available', 0), "#27ae60", "✅"),
                ("Occupied", room_counts.get('occupied', 0), "#e74c3c", "👥"),
                ("Reserved", room_counts.get('reserved', 0), "#f39c12", "📅"),
                ("Housekeeping", room_counts.get('housekeeping', 0), "#3498db", "🧹"),
                ("Active Bookings", len(active_bookings), "#16a085", "📋"),
                ("Reservations", len(reservations), "#8e44ad", "📅"),
                ("Today's Bills", len(bills_today), "#c0392b", "💰"),
                ("Pending Settlements", len(pending_settlements), "#e67e22", "🤝")
            ]

            for i, (title, value, color, icon) in enumerate(stats_data):
                card = tk.Frame(stats_frame, bg=color, relief=tk.RAISED, bd=2, width=150, height=120)
                card.grid(row=i // 3, column=i % 3, padx=8, pady=8, sticky='nsew')
                card.grid_propagate(False)

                tk.Label(card, text=icon, font=('Segoe UI', 24), bg=color, fg='black').pack(pady=(15, 5))
                tk.Label(card, text=str(value), font=('Segoe UI', 24, 'bold'),
                         bg=color, fg='black').pack()
                tk.Label(card, text=title, font=('Segoe UI', 11),
                         bg=color, fg='black').pack()

            for i in range(3):
                stats_frame.grid_columnconfigure(i, weight=1)

        except Exception as e:
            self.show_error(f"Error loading dashboard: {str(e)}")

        # Quick actions
        actions_frame = tk.LabelFrame(parent, text="Quick Actions",
                                      font=('Segoe UI', 14, 'bold'),
                                      bg='white', fg='#6a4334', padx=20, pady=20)
        actions_frame.pack(fill=tk.X, pady=15)

        def open_checkin():
            self.close_active_dialog()
            self.open_function_dialog('checkin')

        def open_checkout():
            self.close_active_dialog()
            self.open_function_dialog('checkout')

        def open_reservation():
            self.close_active_dialog()
            self.open_function_dialog('reservations')

        def open_generate_bill():
            self.close_active_dialog()
            self.open_function_dialog('generate_bill')

        def open_settlements():
            self.close_active_dialog()
            self.open_function_dialog('settlements')

        actions = [
            ("Check-in Guest", "🔑", '#27ae60', open_checkin),
            ("Check-out Guest", "🚪", '#e74c3c', open_checkout),
            ("Make Reservation", "📅", '#8e44ad', open_reservation),
            ("Generate Bill", "🧾", '#27ae60', open_generate_bill),
            ("Settlements", "🤝", '#c0392b', open_settlements)
        ]

        for i, (text, icon, color, command) in enumerate(actions):
            btn = tk.Button(actions_frame, text=f"{icon} {text}",
                            font=('Segoe UI', 12, 'bold'),
                            bg=color, fg='black', relief='flat', cursor='hand2',
                            padx=20, pady=10, command=command)
            btn.grid(row=0, column=i, padx=8, sticky='nsew')
            actions_frame.grid_columnconfigure(i, weight=1)

            # Bind Enter key
            btn.bind('<Return>', lambda e, b=btn, cmd=command: [cmd(), self.handle_enter_key(e, b)])

    # Rooms Dialog
    def create_rooms_dialog(self, parent):
        """Create rooms management in dialog."""
        # Button frame
        button_frame = tk.Frame(parent, bg='white')
        button_frame.pack(fill=tk.X, pady=(0, 20))

        add_btn = tk.Button(button_frame, text="➕ ADD ROOM",
                            font=('Segoe UI', 12, 'bold'),
                            bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                            command=self.open_add_room_dialog, padx=20, pady=10)
        add_btn.pack(side=tk.LEFT, padx=5)
        add_btn.bind('<Return>', lambda e, b=add_btn: self.handle_enter_key(e, b))

        edit_btn = tk.Button(button_frame, text="✏️ EDIT",
                             font=('Segoe UI', 12, 'bold'),
                             bg='#f39c12', fg='black', relief='flat', cursor='hand2',
                             command=self.edit_room_dialog, padx=20, pady=10)
        edit_btn.pack(side=tk.LEFT, padx=5)
        edit_btn.bind('<Return>', lambda e, b=edit_btn: self.handle_enter_key(e, b))

        delete_btn = tk.Button(button_frame, text="🗑️ DELETE",
                               font=('Segoe UI', 12, 'bold'),
                               bg='#e74c3c', fg='black', relief='flat', cursor='hand2',
                               command=self.delete_room, padx=20, pady=10)
        delete_btn.pack(side=tk.LEFT, padx=5)
        delete_btn.bind('<Return>', lambda e, b=delete_btn: self.handle_enter_key(e, b))

        refresh_btn = tk.Button(button_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 12, 'bold'),
                                bg='#3498db', fg='black', relief='flat', cursor='hand2',
                                command=self.load_rooms_data, padx=20, pady=10)
        refresh_btn.pack(side=tk.RIGHT, padx=5)
        refresh_btn.bind('<Return>', lambda e, b=refresh_btn: self.handle_enter_key(e, b))

        # Treeview frame
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ('ID', 'Room No', 'Type', 'Price/Hour', 'Price/Day', 'Status', 'Max Occ', 'Amenities')
        self.rooms_tree = ttk.Treeview(tree_container, columns=columns,
                                       yscrollcommand=v_scrollbar.set,
                                       height=15)

        v_scrollbar.config(command=self.rooms_tree.yview)

        for col in columns:
            self.rooms_tree.heading(col, text=col, anchor=tk.W)
            self.rooms_tree.column(col, width=120, minwidth=100)

        self.rooms_tree.column('ID', width=60)
        self.rooms_tree.column('Room No', width=80)
        self.rooms_tree.column('Type', width=100)
        self.rooms_tree.column('Price/Hour', width=100)
        self.rooms_tree.column('Price/Day', width=100)
        self.rooms_tree.column('Status', width=120)
        self.rooms_tree.column('Max Occ', width=80)
        self.rooms_tree.column('Amenities', width=200)

        self.rooms_tree.pack(fill=tk.BOTH, expand=True)

        self.load_rooms_data()

    def load_rooms_data(self):
        """Load rooms data into treeview."""
        if self.rooms_tree is None:
            return

        for item in self.rooms_tree.get_children():
            self.rooms_tree.delete(item)

        try:
            rooms = self.hotel.get_all_rooms()
            today = datetime.now().date()

            for room in rooms:
                room_status = room.get('status', 'available')

                # Override status based on actual booking status
                conn = self.db.get_connection()
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT COUNT(*) FROM bookings
                    WHERE room_id = ?
                    AND status = 'active'
                ''', (room['id'],))
                active_booking = cursor.fetchone()[0]

                if active_booking > 0:
                    room_status = 'occupied'
                else:
                    cursor.execute('''
                        SELECT COUNT(*) FROM bookings
                        WHERE room_id = ?
                        AND status = 'reserved'
                        AND check_in_date <= ?
                        AND check_out_date > ?
                    ''', (room['id'], today.isoformat(), today.isoformat()))

                    today_reservation = cursor.fetchone()[0]

                    if today_reservation > 0:
                        room_status = 'reserved'
                    else:
                        cursor.execute('''
                            SELECT check_in_date FROM bookings
                            WHERE room_id = ?
                            AND status = 'reserved'
                            AND check_in_date > ?
                            ORDER BY check_in_date
                            LIMIT 1
                        ''', (room['id'], today.isoformat()))

                        future_reservation = cursor.fetchone()
                        if future_reservation:
                            room_status = f"reserved from {future_reservation['check_in_date']}"
                        else:
                            room_status = room['status']

                self.db.return_connection(conn)

                values = (
                    room['id'],
                    room['room_number'],
                    room['room_type'],
                    f"₹{room['price_per_hour']:.2f}",
                    f"₹{room['price_per_day']:.2f}",
                    room_status.upper(),
                    room['max_occupancy'],
                    room['amenities']
                )

                tags = ()
                if 'occupied' in room_status.lower():
                    tags = ('occupied',)
                elif 'reserved' in room_status.lower():
                    tags = ('reserved',)
                elif room_status == 'housekeeping':
                    tags = ('housekeeping',)
                elif room_status == 'underprocess':
                    tags = ('underprocess',)

                self.rooms_tree.insert('', tk.END, values=values, tags=tags)

            self.rooms_tree.tag_configure('occupied', background='#ffcccc')
            self.rooms_tree.tag_configure('reserved', background='#ffffcc')
            self.rooms_tree.tag_configure('housekeeping', background='#ccccff')
            self.rooms_tree.tag_configure('underprocess', background='#ffcc99')
        except Exception as e:
            self.show_error(f"Error loading rooms: {str(e)}")

    def open_add_room_dialog(self):
        """Open dialog to add a new room."""
        dialog = tk.Toplevel(self.active_dialog if self.active_dialog else self.root)
        dialog.title("Add New Room")
        dialog.geometry("650x700")
        dialog.transient(self.active_dialog if self.active_dialog else self.root)
        dialog.grab_set()
        dialog.configure(bg='white')
        self.center_dialog(dialog, 650, 700)

        main_frame = tk.Frame(dialog, bg='white', padx=30, pady=30)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="ADD NEW ROOM", font=('Segoe UI', 22, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 30))

        form_frame = tk.Frame(main_frame, bg='white')
        form_frame.pack(fill=tk.BOTH, expand=True)

        row = 0
        tk.Label(form_frame, text="Room Number:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
        room_number_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=35)
        room_number_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
        row += 1

        tk.Label(form_frame, text="Room Type:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
        room_type_combo = ttk.Combobox(form_frame,
                                       values=['Standard', 'Deluxe', 'Suite', 'Executive', 'Presidential'],
                                       state='readonly', width=33, font=('Segoe UI', 12))
        room_type_combo.grid(row=row, column=1, padx=10, pady=10, sticky='w')
        room_type_combo.set('Standard')
        row += 1

        tk.Label(form_frame, text="Price per Hour (₹):", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
        price_hour_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=35)
        price_hour_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
        price_hour_entry.insert(0, '500.00')
        row += 1

        tk.Label(form_frame, text="Price per Day (₹):", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
        price_day_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=35)
        price_day_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
        price_day_entry.insert(0, '5000.00')
        row += 1

        tk.Label(form_frame, text="Max Occupancy:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
        occupancy_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=35)
        occupancy_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
        occupancy_entry.insert(0, '2')
        row += 1

        tk.Label(form_frame, text="Amenities:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
        amenities_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=35)
        amenities_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
        row += 1

        tk.Label(form_frame, text="Description:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='ne')
        description_entry = tk.Text(form_frame, font=('Segoe UI', 12), width=35, height=4)
        description_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
        row += 1

        def add_room():
            try:
                room_data = {
                    'room_number': room_number_entry.get().strip(),
                    'room_type': room_type_combo.get(),
                    'price_per_hour': float(price_hour_entry.get()),
                    'price_per_day': float(price_day_entry.get()),
                    'max_occupancy': int(occupancy_entry.get()),
                    'amenities': amenities_entry.get().strip(),
                    'description': description_entry.get('1.0', tk.END).strip()
                }

                if not room_data['room_number']:
                    raise ValueError("Room number is required")

                room_id = self.hotel.add_room(room_data)
                self.show_info(f"Room '{room_data['room_number']}' added successfully!")
                self.load_rooms_data()
                dialog.destroy()

            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(f"Error adding room: {str(e)}")

        button_frame = tk.Frame(form_frame, bg='white')
        button_frame.grid(row=row, column=0, columnspan=2, pady=30)

        add_btn = tk.Button(button_frame, text="ADD ROOM", font=('Segoe UI', 13, 'bold'),
                            bg='#27ae60', fg='black', activebackground='#229954',
                            activeforeground='white', relief='flat', cursor='hand2',
                            command=add_room, padx=40, pady=12)
        add_btn.pack(side=tk.LEFT, padx=10)
        add_btn.bind('<Return>', lambda e, b=add_btn: self.handle_enter_key(e, b))

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 13, 'bold'),
                               bg='#95a5a6', fg='black', activebackground='#7f8c8d',
                               activeforeground='white', relief='flat', cursor='hand2',
                               command=dialog.destroy, padx=40, pady=12)
        cancel_btn.pack(side=tk.LEFT, padx=10)
        cancel_btn.bind('<Return>', lambda e, b=cancel_btn: self.handle_enter_key(e, b))

        # Set focus to first entry
        room_number_entry.focus()

    def edit_room_dialog(self):
        """Open dialog to edit a room."""
        if not self.rooms_tree.selection():
            self.show_error("Please select a room to edit.")
            return

        selection = self.rooms_tree.selection()
        room_id = self.rooms_tree.item(selection[0])['values'][0]

        try:
            room = self.hotel.get_room_by_id(room_id)
            if not room:
                raise ValueError("Room not found")

            dialog = tk.Toplevel(self.active_dialog if self.active_dialog else self.root)
            dialog.title("Edit Room")
            dialog.geometry("650x750")
            dialog.transient(self.active_dialog if self.active_dialog else self.root)
            dialog.grab_set()
            dialog.configure(bg='white')
            self.center_dialog(dialog, 650, 750)

            main_frame = tk.Frame(dialog, bg='white', padx=30, pady=30)
            main_frame.pack(fill=tk.BOTH, expand=True)

            tk.Label(main_frame, text="EDIT ROOM", font=('Segoe UI', 22, 'bold'),
                     bg='white', fg='#6a4334').pack(pady=(0, 30))

            form_frame = tk.Frame(main_frame, bg='white')
            form_frame.pack(fill=tk.BOTH, expand=True)

            row = 0
            tk.Label(form_frame, text="Room Number:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            room_number_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=35)
            room_number_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            room_number_entry.insert(0, room['room_number'])
            row += 1

            tk.Label(form_frame, text="Room Type:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            room_type_combo = ttk.Combobox(form_frame,
                                           values=['Standard', 'Deluxe', 'Suite', 'Executive', 'Presidential'],
                                           state='readonly', width=33, font=('Segoe UI', 12))
            room_type_combo.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            room_type_combo.set(room['room_type'])
            row += 1

            tk.Label(form_frame, text="Price per Hour (₹):", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            price_hour_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=35)
            price_hour_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            price_hour_entry.insert(0, str(room['price_per_hour']))
            row += 1

            tk.Label(form_frame, text="Price per Day (₹):", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            price_day_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=35)
            price_day_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            price_day_entry.insert(0, str(room['price_per_day']))
            row += 1

            tk.Label(form_frame, text="Status:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            status_combo = ttk.Combobox(form_frame,
                                        values=['available', 'occupied', 'housekeeping', 'underprocess'],
                                        state='readonly', width=33, font=('Segoe UI', 12))
            status_combo.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            status_combo.set(room['status'])
            row += 1

            tk.Label(form_frame, text="Max Occupancy:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            occupancy_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=35)
            occupancy_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            occupancy_entry.insert(0, str(room['max_occupancy']))
            row += 1

            tk.Label(form_frame, text="Amenities:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            amenities_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=35)
            amenities_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            amenities_entry.insert(0, room['amenities'])
            row += 1

            tk.Label(form_frame, text="Description:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='ne')
            description_entry = tk.Text(form_frame, font=('Segoe UI', 12), width=35, height=4)
            description_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            description_entry.insert('1.0', room['description'])
            row += 1

            def update_room():
                try:
                    update_data = {
                        'room_number': room_number_entry.get().strip(),
                        'room_type': room_type_combo.get(),
                        'price_per_hour': float(price_hour_entry.get()),
                        'price_per_day': float(price_day_entry.get()),
                        'status': status_combo.get(),
                        'max_occupancy': int(occupancy_entry.get()),
                        'amenities': amenities_entry.get().strip(),
                        'description': description_entry.get('1.0', tk.END).strip()
                    }

                    if not update_data['room_number']:
                        raise ValueError("Room number is required")

                    self.hotel.update_room(room_id, update_data)
                    self.show_info(f"Room '{update_data['room_number']}' updated successfully!")
                    self.load_rooms_data()
                    dialog.destroy()

                except ValueError as e:
                    self.show_error(str(e))
                except Exception as e:
                    self.show_error(f"Error updating room: {str(e)}")

            button_frame = tk.Frame(form_frame, bg='white')
            button_frame.grid(row=row, column=0, columnspan=2, pady=30)

            update_btn = tk.Button(button_frame, text="UPDATE ROOM", font=('Segoe UI', 13, 'bold'),
                                   bg='#2e86c1', fg='black', activebackground='#6a4334',
                                   activeforeground='white', relief='flat', cursor='hand2',
                                   command=update_room, padx=40, pady=12)
            update_btn.pack(side=tk.LEFT, padx=10)
            update_btn.bind('<Return>', lambda e, b=update_btn: self.handle_enter_key(e, b))

            cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 13, 'bold'),
                                   bg='#95a5a6', fg='black', activebackground='#7f8c8d',
                                   activeforeground='white', relief='flat', cursor='hand2',
                                   command=dialog.destroy, padx=40, pady=12)
            cancel_btn.pack(side=tk.LEFT, padx=10)
            cancel_btn.bind('<Return>', lambda e, b=cancel_btn: self.handle_enter_key(e, b))

        except Exception as e:
            self.show_error(f"Error loading room details: {str(e)}")

    def delete_room(self):
        """Delete selected room."""
        if not self.rooms_tree.selection():
            self.show_error("Please select a room to delete.")
            return

        selection = self.rooms_tree.selection()
        room_id = self.rooms_tree.item(selection[0])['values'][0]
        room_number = self.rooms_tree.item(selection[0])['values'][1]

        if self.ask_confirmation(f"Are you sure you want to delete room '{room_number}'?"):
            try:
                self.hotel.delete_room(room_id)
                self.show_info(f"Room '{room_number}' deleted successfully!")
                self.load_rooms_data()
            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(f"Error deleting room: {str(e)}")

    # Room Status Dialog
    def create_room_status_dialog(self, parent):
        """Create room status dashboard in dialog."""
        # Legend frame
        legend_frame = tk.Frame(parent, bg='white')
        legend_frame.pack(fill=tk.X, pady=(0, 15))

        legend_items = [
            ("🟢 Available", "#27ae60"),
            ("🔴 Occupied", "#e74c3c"),
            ("🟡 Reserved", "#f39c12"),
            ("🔵 Housekeeping", "#3498db"),
            ("⚪ Under Process", "#8e44ad")
        ]

        for i, (text, color) in enumerate(legend_items):
            legend = tk.Frame(legend_frame, bg=color, width=25, height=25)
            legend.grid(row=0, column=i * 2, padx=5, pady=5)
            tk.Label(legend_frame, text=text, font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').grid(row=0, column=i * 2 + 1, padx=(0, 20))

        # Filter buttons
        filter_frame = tk.Frame(parent, bg='white')
        filter_frame.pack(fill=tk.X, pady=(0, 15))

        filter_buttons = [
            ("ALL", None, '#6a4334'),
            ("AVAILABLE", "available", '#27ae60'),
            ("OCCUPIED", "occupied", '#e74c3c'),
            ("RESERVED", "reserved", '#f39c12'),
            ("HOUSEKEEPING", "housekeeping", '#3498db'),
            ("UNDER PROCESS", "underprocess", '#8e44ad')
        ]

        self.current_room_filter = None

        def apply_filter(status):
            self.current_room_filter = status
            self.load_room_status_dialog()

        for i, (text, status, color) in enumerate(filter_buttons):
            btn = tk.Button(filter_frame, text=text, font=('Segoe UI', 11, 'bold'),
                            bg=color, fg='black', relief='flat', cursor='hand2',
                            padx=15, pady=8, command=lambda s=status: apply_filter(s))
            btn.grid(row=0, column=i, padx=3, sticky='nsew')
            filter_frame.grid_columnconfigure(i, weight=1)
            btn.bind('<Return>', lambda e, b=btn, s=status: [apply_filter(s), self.handle_enter_key(e, b)])

        # Rooms grid
        self.rooms_grid_frame = tk.Frame(parent, bg='white')
        self.rooms_grid_frame.pack(fill=tk.BOTH, expand=True)

        # Create canvas with scrollbar for grid
        canvas = tk.Canvas(self.rooms_grid_frame, bg='white', highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.rooms_grid_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='white')

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Store scrollable frame reference
        self.room_status_scrollable = scrollable_frame

        # Load data
        self.load_room_status_dialog()

    def load_room_status_dialog(self):
        """Load room status in dialog."""
        if not hasattr(self, 'room_status_scrollable'):
            return

        # Clear existing
        for widget in self.room_status_scrollable.winfo_children():
            widget.destroy()

        try:
            rooms = self.hotel.get_all_rooms()

            # Apply filter
            if hasattr(self, 'current_room_filter') and self.current_room_filter:
                filtered_rooms = []
                for room in rooms:
                    status = room.get('status', 'available')
                    if self.current_room_filter == 'reserved':
                        if 'reserved' in status.lower():
                            filtered_rooms.append(room)
                    elif status == self.current_room_filter:
                        filtered_rooms.append(room)
                rooms = filtered_rooms

            # Create grid
            row, col = 0, 0
            max_cols = 3

            for room in rooms:
                status = room.get('status', 'available')

                if status == 'available':
                    color = '#27ae60'
                    status_icon = '✅'
                elif status == 'occupied':
                    color = '#e74c3c'
                    status_icon = '👥'
                elif 'reserved' in status:
                    color = '#f39c12'
                    status_icon = '📅'
                elif status == 'housekeeping':
                    color = '#3498db'
                    status_icon = '🧹'
                elif status == 'underprocess':
                    color = '#8e44ad'
                    status_icon = '⚙️'
                else:
                    color = '#95a5a6'
                    status_icon = '❓'

                # Room card - larger size
                card = tk.Frame(self.room_status_scrollable, bg=color, relief=tk.RAISED,
                                bd=2, width=250, height=180)
                card.grid(row=row, column=col, padx=10, pady=10)
                card.grid_propagate(False)

                tk.Label(card, text=f"ROOM {room['room_number']}",
                         font=('Segoe UI', 14, 'bold'), bg=color, fg='black').pack(pady=(12, 5))
                tk.Label(card, text=room['room_type'].upper(),
                         font=('Segoe UI', 11), bg=color, fg='black').pack()
                tk.Label(card, text=f"{status_icon} {status.upper()}",
                         font=('Segoe UI', 12, 'bold'), bg=color, fg='black').pack(pady=8)
                tk.Label(card, text=f"₹{room['price_per_day']}/day",
                         font=('Segoe UI', 11), bg=color, fg='black').pack()

                # Guest info if occupied
                if status == 'occupied':
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT guest_name FROM bookings
                        WHERE room_id = ? AND status = "active"
                        ORDER BY check_in_time DESC LIMIT 1
                    ''', (room['id'],))
                    booking = cursor.fetchone()
                    self.db.return_connection(conn)

                    if booking:
                        guest_name = booking['guest_name'][:18] + '...' if len(booking['guest_name']) > 18 else booking[
                            'guest_name']
                        tk.Label(card, text=f"Guest: {guest_name}",
                                 font=('Segoe UI', 10), bg=color, fg='black').pack()

                col += 1
                if col >= max_cols:
                    col = 0
                    row += 1

        except Exception as e:
            print(f"Error loading room status: {e}")

    # Check-in Dialog with ID auto-fill
    def create_checkin_dialog(self, parent):
        """Create check-in form in dialog with ID auto-fill."""
        from datetime import datetime

        form_frame = tk.Frame(parent, bg='white')
        form_frame.pack(fill=tk.BOTH, expand=True)

        # Create a canvas with scrollbar for the form
        canvas = tk.Canvas(form_frame, bg='white', highlightthickness=0)
        scrollbar = ttk.Scrollbar(form_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='white')

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Add warning note
        note_frame = tk.Frame(scrollable_frame, bg='#fff3cd', bd=1, relief=tk.SOLID)
        note_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(note_frame,
                 text="⚠️ Note: If a room has an upcoming reservation, you'll be warned before check-in | Enter ID Card to auto-fill guest data",
                 font=('Segoe UI', 11, 'italic'), bg='#fff3cd', fg='#856404',
                 padx=10, pady=5).pack()

        # ID Card Lookup
        id_frame = tk.LabelFrame(scrollable_frame, text="Guest ID Lookup",
                                 font=('Segoe UI', 12, 'bold'),
                                 bg='white', fg='#6a4334', padx=15, pady=10)
        id_frame.pack(fill=tk.X, pady=5)

        tk.Label(id_frame, text="ID Card Number:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.checkin_id_card = tk.Entry(id_frame, font=('Segoe UI', 12), width=25)
        self.checkin_id_card.pack(side=tk.LEFT, padx=5)
        self.checkin_id_card.bind('<Return>', lambda e: self.lookup_guest_by_id())

        lookup_btn = tk.Button(id_frame, text="🔍 LOOKUP",
                               font=('Segoe UI', 11, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.lookup_guest_by_id, padx=15, pady=5)
        lookup_btn.pack(side=tk.LEFT, padx=5)
        lookup_btn.bind('<Return>', lambda e, b=lookup_btn: self.handle_enter_key(e, b))

        # Room selection
        room_frame = tk.LabelFrame(scrollable_frame, text="Select Room",
                                   font=('Segoe UI', 12, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        room_frame.pack(fill=tk.X, pady=5)

        self.checkin_room_list = tk.Listbox(room_frame, height=4,
                                            font=('Segoe UI', 12), bg='white')
        self.checkin_room_list.pack(fill=tk.X)

        refresh_btn = tk.Button(room_frame, text="🔄 Refresh",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat',
                                command=self.load_checkin_rooms, padx=15, pady=5)
        refresh_btn.pack(pady=5)
        refresh_btn.bind('<Return>', lambda e, b=refresh_btn: self.handle_enter_key(e, b))

        self.load_checkin_rooms()

        # Guest info
        guest_frame = tk.LabelFrame(scrollable_frame, text="Guest Information",
                                    font=('Segoe UI', 12, 'bold'),
                                    bg='white', fg='#6a4334', padx=15, pady=10)
        guest_frame.pack(fill=tk.X, pady=5)

        row = 0
        tk.Label(guest_frame, text="Guest Name:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_guest_name = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_guest_name.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_guest_name.focus()
        row += 1

        tk.Label(guest_frame, text="Phone:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_guest_phone = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_guest_phone.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        row += 1

        tk.Label(guest_frame, text="Email:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_guest_email = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_guest_email.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        row += 1

        tk.Label(guest_frame, text="ID Card:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_guest_id_card = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_guest_id_card.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        row += 1

        tk.Label(guest_frame, text="Address:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_guest_address = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_guest_address.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        row += 1

        tk.Label(guest_frame, text="No. of Persons:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_persons = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_persons.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_persons.insert(0, '1')
        row += 1

        # Company Information
        company_frame = tk.LabelFrame(scrollable_frame, text="Company Information (Optional)",
                                      font=('Segoe UI', 12, 'bold'),
                                      bg='white', fg='#6a4334', padx=15, pady=10)
        company_frame.pack(fill=tk.X, pady=5)

        row = 0
        tk.Label(company_frame, text="Company Name:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_company_name = tk.Entry(company_frame, font=('Segoe UI', 12), width=35)
        self.checkin_company_name.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        row += 1

        tk.Label(company_frame, text="Company Address:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_company_address = tk.Entry(company_frame, font=('Segoe UI', 12), width=35)
        self.checkin_company_address.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        row += 1

        tk.Label(company_frame, text="Party GSTIN:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_party_gstin = tk.Entry(company_frame, font=('Segoe UI', 12), width=35)
        self.checkin_party_gstin.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        row += 1

        # Advance Payment
        advance_frame = tk.LabelFrame(scrollable_frame, text="Advance Payment",
                                      font=('Segoe UI', 12, 'bold'),
                                      bg='white', fg='#6a4334', padx=15, pady=10)
        advance_frame.pack(fill=tk.X, pady=5)

        row = 0
        tk.Label(advance_frame, text="Advance Amount (₹):", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_advance = tk.Entry(advance_frame, font=('Segoe UI', 12), width=20)
        self.checkin_advance.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_advance.insert(0, '0.00')
        row += 1

        tk.Label(advance_frame, text="Payment Method:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_advance_method = ttk.Combobox(advance_frame,
                                                   values=['cash', 'card', 'online', 'upi'],
                                                   width=18, state='readonly', font=('Segoe UI', 12))
        self.checkin_advance_method.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_advance_method.set('cash')
        row += 1

        # Check-in time
        time_frame = tk.LabelFrame(scrollable_frame, text="Check-in Time",
                                   font=('Segoe UI', 12, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        time_frame.pack(fill=tk.X, pady=5)

        tk.Label(time_frame, text="Time:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.checkin_time = tk.Entry(time_frame, font=('Segoe UI', 12), width=20)
        self.checkin_time.pack(side=tk.LEFT, padx=5)
        self.checkin_time.insert(0, datetime.now().strftime('%Y-%m-%d %H:%M'))

        now_btn = tk.Button(time_frame, text="NOW", font=('Segoe UI', 11, 'bold'),
                            bg='#f39c12', fg='black', relief='flat',
                            command=lambda: self.checkin_time.delete(0, tk.END) or
                                            self.checkin_time.insert(0, datetime.now().strftime('%Y-%m-%d %H:%M')),
                            padx=15, pady=5)
        now_btn.pack(side=tk.LEFT, padx=5)
        now_btn.bind('<Return>', lambda e, b=now_btn: self.handle_enter_key(e, b))

        # Check-in button
        checkin_btn = tk.Button(scrollable_frame, text="✅ CHECK-IN GUEST",
                                font=('Segoe UI', 14, 'bold'),
                                bg='#27ae60', fg='black', relief='flat',
                                command=self.checkin_guest, padx=40, pady=12)
        checkin_btn.pack(pady=15)
        checkin_btn.bind('<Return>', lambda e, b=checkin_btn: self.handle_enter_key(e, b))

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def lookup_guest_by_id(self):
        """Lookup guest information by ID card."""
        id_card = self.checkin_id_card.get().strip()
        if not id_card:
            return

        guest = self.hotel.get_guest_by_id_card(id_card)
        if guest:
            self.checkin_guest_name.delete(0, tk.END)
            self.checkin_guest_name.insert(0, guest.get('guest_name', ''))

            self.checkin_guest_phone.delete(0, tk.END)
            self.checkin_guest_phone.insert(0, guest.get('guest_phone', ''))

            self.checkin_guest_email.delete(0, tk.END)
            self.checkin_guest_email.insert(0, guest.get('guest_email', ''))

            self.checkin_guest_address.delete(0, tk.END)
            self.checkin_guest_address.insert(0, guest.get('guest_address', ''))

            self.checkin_company_name.delete(0, tk.END)
            self.checkin_company_name.insert(0, guest.get('company_name', ''))

            self.checkin_company_address.delete(0, tk.END)
            self.checkin_company_address.insert(0, guest.get('company_address', ''))

            self.checkin_party_gstin.delete(0, tk.END)
            self.checkin_party_gstin.insert(0, guest.get('party_gstin', ''))

            self.show_info(f"Guest data loaded for ID: {id_card}")
        else:
            self.show_warning(f"No previous guest found with ID: {id_card}")

    def load_checkin_rooms(self):
        """Load available rooms for check-in."""
        if hasattr(self, 'checkin_room_list'):
            self.checkin_room_list.delete(0, tk.END)
            try:
                rooms = self.hotel.get_available_rooms()
                for room in rooms:
                    room_info = f"{room['room_number']} - {room['room_type']} - ₹{room['price_per_day']}/day"
                    self.checkin_room_list.insert(tk.END, room_info)
            except Exception as e:
                self.show_error(f"Error loading rooms: {str(e)}")

    def checkin_guest(self):
        """Process guest check-in with advance payment."""
        try:
            if not hasattr(self, 'checkin_room_list') or not self.checkin_room_list.curselection():
                raise ValueError("Please select a room")

            selection = self.checkin_room_list.curselection()
            room_info = self.checkin_room_list.get(selection[0])
            room_number = room_info.split(' - ')[0]

            room = self.hotel.get_room_by_number(room_number)
            if not room:
                raise ValueError("Selected room not found")

            # Check for reservation warnings
            has_warning, warning_msg, reservation = self.check_room_reservation_warning(room['id'])

            if has_warning:
                if not messagebox.askyesno("⚠️ Reservation Warning",
                                           warning_msg + "\n\nDo you still want to allocate this room?",
                                           icon='warning'):
                    return

            guest_name = self.checkin_guest_name.get().strip()
            if not guest_name:
                raise ValueError("Guest name is required")

            # Validate check-in time
            checkin_time = self.checkin_time.get()
            try:
                datetime.strptime(checkin_time, '%Y-%m-%d %H:%M')
            except ValueError:
                raise ValueError("Invalid check-in time format. Use YYYY-MM-DD HH:MM")

            # Get advance payment
            advance_amount = float(self.checkin_advance.get() or 0)

            booking_data = {
                'room_id': room['id'],
                'guest_name': guest_name,
                'guest_phone': self.checkin_guest_phone.get().strip(),
                'guest_email': self.checkin_guest_email.get().strip(),
                'guest_id_card': self.checkin_guest_id_card.get().strip(),
                'guest_address': self.checkin_guest_address.get().strip(),
                'check_in_time': checkin_time,
                'no_of_persons': int(self.checkin_persons.get()),
                'company_name': self.checkin_company_name.get().strip(),
                'company_address': self.checkin_company_address.get().strip(),
                'party_gstin': self.checkin_party_gstin.get().strip(),
                'advance_payment': advance_amount,
                'advance_payment_method': self.checkin_advance_method.get()
            }

            booking_id = self.hotel.create_booking(booking_data)

            if has_warning:
                self.show_warning(
                    f"✅ Guest checked in successfully despite reservation!\n\nBooking ID: {booking_id}\nAdvance Paid: ₹{advance_amount:.2f}\n\n⚠️ Please ensure the reserved guest is contacted.")
            else:
                self.show_info(
                    f"✅ Guest checked in successfully!\n\nBooking ID: {booking_id}\nAdvance Paid: ₹{advance_amount:.2f}")

            # Clear form
            self.checkin_id_card.delete(0, tk.END)
            self.checkin_guest_name.delete(0, tk.END)
            self.checkin_guest_phone.delete(0, tk.END)
            self.checkin_guest_email.delete(0, tk.END)
            self.checkin_guest_id_card.delete(0, tk.END)
            self.checkin_guest_address.delete(0, tk.END)
            self.checkin_persons.delete(0, tk.END)
            self.checkin_persons.insert(0, '1')
            self.checkin_company_name.delete(0, tk.END)
            self.checkin_company_address.delete(0, tk.END)
            self.checkin_party_gstin.delete(0, tk.END)
            self.checkin_advance.delete(0, tk.END)
            self.checkin_advance.insert(0, '0.00')
            self.checkin_time.delete(0, tk.END)
            self.checkin_time.insert(0, datetime.now().strftime('%Y-%m-%d %H:%M'))

            self.load_checkin_rooms()
            self.load_active_bookings()

        except ValueError as e:
            self.show_error(str(e))
        except Exception as e:
            self.show_error(f"Error during check-in: {str(e)}")

    def check_room_reservation_warning(self, room_id):
        """Check if room has upcoming reservation and return warning message."""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()

            today = datetime.now().date()
            five_days_later = (today + timedelta(days=5)).isoformat()

            cursor.execute('''
                SELECT b.*, r.room_number
                FROM bookings b
                JOIN rooms r ON b.room_id = r.id
                WHERE b.room_id = ?
                AND b.status = 'reserved'
                AND DATE(b.check_in_date) BETWEEN ? AND ?
                ORDER BY b.check_in_date
            ''', (room_id, today.isoformat(), five_days_later))

            upcoming = cursor.fetchall()
            self.db.return_connection(conn)

            if upcoming:
                res = dict(upcoming[0])
                check_in = datetime.strptime(res['check_in_date'], '%Y-%m-%d').date()
                days_until = (check_in - today).days

                warning = f"⚠️ RESERVATION WARNING ⚠️\n\n"
                warning += f"This room is RESERVED for:\n"
                warning += f"👤 Guest: {res['guest_name']}\n"
                warning += f"📞 Phone: {res.get('guest_phone', 'N/A')}\n"
                warning += f"📅 Check-in Date: {res['check_in_date']}\n\n"

                if days_until == 0:
                    warning += "❌ RESERVATION IS FOR TODAY!\n"
                    warning += "Please contact the guest before allocating this room."
                    return True, warning, res
                elif days_until == 1:
                    warning += f"⚠️ Reservation is TOMORROW!\n"
                    warning += f"Only 1 day remaining before guest arrives."
                    return True, warning, res
                elif days_until <= 5:
                    warning += f"⚠️ Reservation is in {days_until} days!\n"
                    warning += f"Guest will arrive soon. Please consider before allocating."
                    return True, warning, res

            return False, "", None

        except Exception as e:
            print(f"Error checking reservation warning: {e}")
            return False, "", None

    # Check-out Dialog with 12:00 cycle
    def create_checkout_dialog(self, parent):
        """Create check-out form in dialog."""
        from datetime import datetime

        form_frame = tk.Frame(parent, bg='white')
        form_frame.pack(fill=tk.BOTH, expand=True)

        # Active bookings selection
        bookings_frame = tk.LabelFrame(form_frame, text="Select Active Booking",
                                       font=('Segoe UI', 12, 'bold'),
                                       bg='white', fg='#6a4334', padx=15, pady=10)
        bookings_frame.pack(fill=tk.X, pady=5)

        self.checkout_booking_list = tk.Listbox(bookings_frame, height=6,
                                                font=('Segoe UI', 12), bg='white')
        self.checkout_booking_list.pack(fill=tk.X)

        refresh_btn = tk.Button(bookings_frame, text="🔄 Refresh",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat',
                                command=self.load_checkout_bookings, padx=15, pady=5)
        refresh_btn.pack(pady=5)
        refresh_btn.bind('<Return>', lambda e, b=refresh_btn: self.handle_enter_key(e, b))

        self.load_checkout_bookings()

        # Billing cycle info
        info_frame = tk.Frame(form_frame, bg='#e8f4f8', bd=1, relief=tk.SOLID)
        info_frame.pack(fill=tk.X, pady=5)

        tk.Label(info_frame,
                 text="ℹ️ Billing Policy: Check-out after 12:00 PM charges for additional day (12:00 PM to 12:00 PM cycle)",
                 font=('Segoe UI', 11), bg='#e8f4f8', fg='#2c3e50',
                 padx=10, pady=5).pack()

        # Check-out time
        time_frame = tk.LabelFrame(form_frame, text="Check-out Time",
                                   font=('Segoe UI', 12, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        time_frame.pack(fill=tk.X, pady=5)

        tk.Label(time_frame, text="Time:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.checkout_time = tk.Entry(time_frame, font=('Segoe UI', 12), width=20)
        self.checkout_time.pack(side=tk.LEFT, padx=5)
        self.checkout_time.insert(0, datetime.now().strftime('%Y-%m-%d %H:%M'))

        now_btn = tk.Button(time_frame, text="NOW", font=('Segoe UI', 11, 'bold'),
                            bg='#f39c12', fg='black', relief='flat',
                            command=lambda: self.checkout_time.delete(0, tk.END) or
                                            self.checkout_time.insert(0, datetime.now().strftime('%Y-%m-%d %H:%M')),
                            padx=15, pady=5)
        now_btn.pack(side=tk.LEFT, padx=5)
        now_btn.bind('<Return>', lambda e, b=now_btn: self.handle_enter_key(e, b))

        # Check-out button
        checkout_btn = tk.Button(form_frame, text="🚪 CHECK-OUT GUEST",
                                 font=('Segoe UI', 14, 'bold'),
                                 bg='#e74c3c', fg='black', relief='flat',
                                 command=self.checkout_guest, padx=40, pady=12)
        checkout_btn.pack(pady=15)
        checkout_btn.bind('<Return>', lambda e, b=checkout_btn: self.handle_enter_key(e, b))

    def load_checkout_bookings(self):
        """Load active bookings for check-out."""
        if hasattr(self, 'checkout_booking_list'):
            self.checkout_booking_list.delete(0, tk.END)
            try:
                bookings = self.hotel.get_active_bookings()
                for booking in bookings:
                    check_in = datetime.fromisoformat(booking['check_in_time']).strftime('%Y-%m-%d %H:%M')
                    booking_info = f"ID:{booking['id']} - Room:{booking['room_number']} - {booking['guest_name']} - Check-in:{check_in}"
                    self.checkout_booking_list.insert(tk.END, booking_info)
            except Exception as e:
                self.show_error(f"Error loading bookings: {str(e)}")

    def checkout_guest(self):
        """Process guest check-out with 12:00 PM cycle."""
        try:
            if not hasattr(self, 'checkout_booking_list') or not self.checkout_booking_list.curselection():
                raise ValueError("Please select a booking")

            selection = self.checkout_booking_list.curselection()
            booking_info = self.checkout_booking_list.get(selection[0])
            booking_id = int(booking_info.split(' - ')[0].split(':')[1])

            checkout_time = self.checkout_time.get()

            # Calculate and show preview
            booking = self.hotel.get_booking_by_id(booking_id)
            if booking:
                check_in_time = datetime.fromisoformat(booking['check_in_time'])
                check_out_time_dt = datetime.fromisoformat(checkout_time)

                # Calculate days based on 12:00 PM policy
                cutoff_time = 12
                check_in_hour = check_in_time.hour
                check_in_minute = check_in_time.minute

                days = 0
                explanation = []

                if check_out_time_dt.date() == check_in_time.date():
                    days = 1
                    explanation = ["Same day checkout - Charged as 1 day"]
                else:
                    check_in_before_12 = check_in_hour < cutoff_time or (
                                check_in_hour == cutoff_time and check_in_minute == 0)
                    if check_in_before_12:
                        days = 1
                        explanation.append(
                            f"Day 1: {check_in_time.date().strftime('%d/%m/%Y')} (Check-in before/at 12 PM)")
                        current_date = check_in_time.date() + timedelta(days=1)
                    else:
                        days = 1
                        explanation.append(
                            f"Day 1: {check_in_time.date().strftime('%d/%m/%Y')} (Check-in after 12 PM - partial)")
                        current_date = check_in_time.date() + timedelta(days=1)

                    day_count = 2
                    while current_date < check_out_time_dt.date():
                        days += 1
                        explanation.append(f"Day {day_count}: {current_date.strftime('%d/%m/%Y')} (Full day)")
                        day_count += 1
                        current_date += timedelta(days=1)

                    if check_out_time_dt.hour >= cutoff_time:
                        days += 1
                        explanation.append(
                            f"Day {day_count}: {check_out_time_dt.date().strftime('%d/%m/%Y')} (Check-out after 12 PM)")

                total_amount = days * booking['price_per_day']

                # Show preview
                preview_msg = f"📋 BILLING PREVIEW (12 PM Policy)\n\n"
                preview_msg += f"Check-in: {check_in_time.strftime('%d/%m/%Y %H:%M')}\n"
                preview_msg += f"Check-out: {check_out_time_dt.strftime('%d/%m/%Y %H:%M')}\n"
                preview_msg += f"Daily Rate: ₹{booking['price_per_day']:.2f}\n"
                preview_msg += "-" * 40 + "\n"
                for exp in explanation:
                    preview_msg += f"{exp}\n"
                preview_msg += "-" * 40 + "\n"
                preview_msg += f"Total Days: {days}\n"
                preview_msg += f"Total Amount: ₹{total_amount:.2f}\n\n"
                preview_msg += "Proceed with check-out?"

                if not self.ask_confirmation(preview_msg):
                    return

            # Perform checkout
            days, total_amount, check_in_time, check_out_time_dt = self.hotel.checkout_booking(booking_id, checkout_time)

            self.show_info(
                f"✅ Guest checked out successfully!\n\n📅 Total Days: {days}\n💰 Total Amount: ₹{total_amount:.2f}")

            # Ask if user wants to generate bill now
            if self.ask_confirmation("Do you want to generate the bill now?"):
                self.generate_bill_for_checkout(booking_id, checkout_time, total_amount, days)

            self.load_checkout_bookings()
            self.load_checkin_rooms()
            self.load_active_bookings()

        except ValueError as e:
            self.show_error(str(e))
        except Exception as e:
            self.show_error(f"Error during check-out: {str(e)}")

    def generate_bill_for_checkout(self, booking_id, checkout_time, total_amount, days):
        """Generate bill with the correct calculated values."""
        try:
            # Get booking details
            booking = self.hotel.get_booking_by_id(booking_id)
            if not booking:
                raise ValueError("Booking not found")

            # Prepare bill data
            bill_data = {
                'check_out_time': checkout_time,
                'cgst_percentage': 2.5,
                'sgst_percentage': 2.5,
                'discount_percentage': 0.0,
                'payment_method': 'cash',
                'payment_status': 'pending',
                'verified_by': self.auth.current_user['username'] if self.auth.current_user else 'admin',
                'notes': ''
            }

            # Generate bill
            bill_id, bill_number, total_amount, advance_paid, balance_due, day_breakdowns = self.hotel.generate_bill(
                booking_id, bill_data)

            # Get full bill details for printing
            bill_details = self.hotel.get_bill_by_number(bill_number)
            if bill_details:
                # Add hotel settings
                settings = self.hotel.get_hotel_settings()
                bill_details.update(settings)

                # Update the bill generator with current hotel manager
                self.bill_generator.set_hotel_manager(self.hotel)

                # Print the bill
                self.bill_generator.print_bill(bill_details, day_breakdowns)

            self.show_info(
                f"✅ Bill generated successfully!\nBill Number: {bill_number}\nTotal: ₹{total_amount:.2f}\nAdvance Paid: ₹{advance_paid:.2f}\nBalance Due: ₹{balance_due:.2f}")

        except Exception as e:
            self.show_error(f"Error generating bill: {str(e)}")

    # Check-in/Check-out Tab
    def create_checkinout_dialog(self, parent):
        """Create combined check-in/check-out dialog."""
        notebook = ttk.Notebook(parent)
        notebook.pack(fill=tk.BOTH, expand=True)

        # Check-in tab
        checkin_frame = ttk.Frame(notebook)
        notebook.add(checkin_frame, text="🔑 Check-in Guest")
        self.create_checkin_dialog(checkin_frame)

        # Check-out tab
        checkout_frame = ttk.Frame(notebook)
        notebook.add(checkout_frame, text="🚪 Check-out Guest")
        self.create_checkout_dialog(checkout_frame)

        # Reservation tab
        reservation_frame = ttk.Frame(notebook)
        notebook.add(reservation_frame, text="📅 Make Reservation")
        self.create_reservations_form_dialog(reservation_frame)

    # Reservations Dialog
    def create_reservations_form_dialog(self, parent):
        """Create reservations form for users."""
        from datetime import datetime, timedelta

        form_frame = tk.Frame(parent, bg='white')
        form_frame.pack(fill=tk.BOTH, expand=True)

        # Create a canvas with scrollbar for the form
        canvas = tk.Canvas(form_frame, bg='white', highlightthickness=0)
        scrollbar = ttk.Scrollbar(form_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='white')

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Reservation Dates
        date_frame = tk.LabelFrame(scrollable_frame, text="Reservation Dates",
                                   font=('Segoe UI', 12, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        date_frame.pack(fill=tk.X, pady=5)

        row = 0
        tk.Label(date_frame, text="Check-in Date:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.res_checkin_date = tk.Entry(date_frame, font=('Segoe UI', 12), width=20)
        self.res_checkin_date.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.res_checkin_date.insert(0, datetime.now().strftime('%Y-%m-%d'))

        today_btn = tk.Button(date_frame, text="TODAY", font=('Segoe UI', 11, 'bold'),
                              bg='#f39c12', fg='black', relief='flat',
                              command=lambda: self.res_checkin_date.delete(0, tk.END) or
                                              self.res_checkin_date.insert(0, datetime.now().strftime('%Y-%m-%d')),
                              padx=10, pady=2)
        today_btn.grid(row=row, column=2, padx=5, pady=5)
        today_btn.bind('<Return>', lambda e, b=today_btn: self.handle_enter_key(e, b))
        row += 1

        tk.Label(date_frame, text="Check-out Date:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.res_checkout_date = tk.Entry(date_frame, font=('Segoe UI', 12), width=20)
        self.res_checkout_date.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        self.res_checkout_date.insert(0, tomorrow)

        tomorrow_btn = tk.Button(date_frame, text="TOMORROW", font=('Segoe UI', 11, 'bold'),
                                 bg='#f39c12', fg='black', relief='flat',
                                 command=lambda: self.res_checkout_date.delete(0, tk.END) or
                                                 self.res_checkout_date.insert(0, tomorrow),
                                 padx=10, pady=2)
        tomorrow_btn.grid(row=row, column=2, padx=5, pady=5)
        tomorrow_btn.bind('<Return>', lambda e, b=tomorrow_btn: self.handle_enter_key(e, b))
        row += 1

        check_btn = tk.Button(date_frame, text="🔍 Check Availability",
                              font=('Segoe UI', 11, 'bold'),
                              bg='#2e86c1', fg='black', relief='flat',
                              command=self.check_room_availability)
        check_btn.grid(row=row, column=0, columnspan=3, pady=10)
        check_btn.bind('<Return>', lambda e, b=check_btn: self.handle_enter_key(e, b))

        # Available Rooms
        rooms_frame = tk.LabelFrame(scrollable_frame, text="Available Rooms",
                                    font=('Segoe UI', 12, 'bold'),
                                    bg='white', fg='#6a4334', padx=15, pady=10)
        rooms_frame.pack(fill=tk.X, pady=5)

        self.res_room_list = tk.Listbox(rooms_frame, height=4,
                                        font=('Segoe UI', 12), bg='white')
        self.res_room_list.pack(fill=tk.X)

        # Guest Information
        guest_frame = tk.LabelFrame(scrollable_frame, text="Guest Information",
                                    font=('Segoe UI', 12, 'bold'),
                                    bg='white', fg='#6a4334', padx=15, pady=10)
        guest_frame.pack(fill=tk.X, pady=5)

        row = 0
        tk.Label(guest_frame, text="Guest Name:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.res_guest_name = tk.Entry(guest_frame, font=('Segoe UI', 12), width=30)
        self.res_guest_name.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.res_guest_name.focus()
        row += 1

        tk.Label(guest_frame, text="Phone:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.res_guest_phone = tk.Entry(guest_frame, font=('Segoe UI', 12), width=30)
        self.res_guest_phone.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        row += 1

        tk.Label(guest_frame, text="No. of Persons:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.res_persons = tk.Entry(guest_frame, font=('Segoe UI', 12), width=30)
        self.res_persons.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.res_persons.insert(0, '1')
        row += 1

        # Advance Payment
        advance_frame = tk.LabelFrame(scrollable_frame, text="Advance Payment",
                                      font=('Segoe UI', 12, 'bold'),
                                      bg='white', fg='#6a4334', padx=15, pady=10)
        advance_frame.pack(fill=tk.X, pady=5)

        row = 0
        tk.Label(advance_frame, text="Advance Amount (₹):", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.res_advance = tk.Entry(advance_frame, font=('Segoe UI', 12), width=20)
        self.res_advance.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.res_advance.insert(0, '0.00')
        row += 1

        tk.Label(advance_frame, text="Payment Method:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.res_advance_method = ttk.Combobox(advance_frame,
                                               values=['cash', 'card', 'online', 'upi'],
                                               width=18, state='readonly', font=('Segoe UI', 12))
        self.res_advance_method.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.res_advance_method.set('cash')
        row += 1

        # Reservation button
        reserve_btn = tk.Button(scrollable_frame, text="📅 MAKE RESERVATION",
                                font=('Segoe UI', 14, 'bold'),
                                bg='#8e44ad', fg='black', relief='flat',
                                command=self.make_reservation, padx=40, pady=12)
        reserve_btn.pack(pady=15)
        reserve_btn.bind('<Return>', lambda e, b=reserve_btn: self.handle_enter_key(e, b))

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def check_room_availability(self):
        """Check room availability for reservation."""
        try:
            check_in_date = self.res_checkin_date.get()
            check_out_date = self.res_checkout_date.get()

            datetime.strptime(check_in_date, '%Y-%m-%d')
            datetime.strptime(check_out_date, '%Y-%m-%d')

            if check_in_date >= check_out_date:
                raise ValueError("Check-out date must be after check-in date")

            self.res_room_list.delete(0, tk.END)
            rooms = self.hotel.get_available_rooms(check_in_date, check_out_date)

            if not rooms:
                self.res_room_list.insert(tk.END, "No rooms available for selected dates")
            else:
                for room in rooms:
                    room_info = f"{room['room_number']} - {room['room_type']} - ₹{room['price_per_day']}/day"
                    self.res_room_list.insert(tk.END, room_info)

        except ValueError as e:
            self.show_error(str(e))
        except Exception as e:
            self.show_error(f"Error checking availability: {str(e)}")

    def make_reservation(self):
        """Make a reservation."""
        try:
            if not hasattr(self, 'res_room_list') or not self.res_room_list.curselection():
                raise ValueError("Please select a room")

            selection = self.res_room_list.curselection()
            room_info = self.res_room_list.get(selection[0])

            if "No rooms available" in room_info:
                raise ValueError("Please check room availability first")

            room_number = room_info.split(' - ')[0]
            room = self.hotel.get_room_by_number(room_number)

            guest_name = self.res_guest_name.get().strip()
            if not guest_name:
                raise ValueError("Guest name is required")

            advance_amount = float(self.res_advance.get() or 0)

            booking_data = {
                'room_id': room['id'],
                'guest_name': guest_name,
                'guest_phone': self.res_guest_phone.get().strip(),
                'check_in_date': self.res_checkin_date.get(),
                'check_out_date': self.res_checkout_date.get(),
                'reservation_type': 'reservation',
                'no_of_persons': int(self.res_persons.get()),
                'advance_payment': advance_amount,
                'advance_payment_method': self.res_advance_method.get()
            }

            booking_id = self.hotel.create_booking(booking_data)
            self.show_info(f"✅ Reservation made successfully!\n\nReservation ID: {booking_id}\nAdvance Paid: ₹{advance_amount:.2f}")

            # Clear form
            self.res_guest_name.delete(0, tk.END)
            self.res_guest_phone.delete(0, tk.END)
            self.res_persons.delete(0, tk.END)
            self.res_persons.insert(0, '1')
            self.res_advance.delete(0, tk.END)
            self.res_advance.insert(0, '0.00')
            self.res_room_list.delete(0, tk.END)

        except ValueError as e:
            self.show_error(str(e))
        except Exception as e:
            self.show_error(f"Error making reservation: {str(e)}")

    # Reservations View Dialog
    def create_reservations_view_dialog(self, parent):
        """Create reservations view for admin."""
        # Button frame
        button_frame = tk.Frame(parent, bg='white')
        button_frame.pack(fill=tk.X, pady=(0, 15))

        refresh_btn = tk.Button(button_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 12, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_reservations_data, padx=20, pady=10)
        refresh_btn.pack(side=tk.LEFT, padx=5)
        refresh_btn.bind('<Return>', lambda e, b=refresh_btn: self.handle_enter_key(e, b))

        cancel_btn = tk.Button(button_frame, text="❌ CANCEL RESERVATION",
                               font=('Segoe UI', 12, 'bold'),
                               bg='#e74c3c', fg='black', relief='flat', cursor='hand2',
                               command=self.cancel_reservation, padx=20, pady=10)
        cancel_btn.pack(side=tk.LEFT, padx=5)
        cancel_btn.bind('<Return>', lambda e, b=cancel_btn: self.handle_enter_key(e, b))

        # Treeview frame
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ('ID', 'Room No', 'Guest Name', 'Check-in Date', 'Check-out Date', 'Phone', 'Advance', 'Status')
        self.reservations_tree = ttk.Treeview(tree_container, columns=columns,
                                              yscrollcommand=v_scrollbar.set,
                                              height=15)

        v_scrollbar.config(command=self.reservations_tree.yview)

        for col in columns:
            self.reservations_tree.heading(col, text=col, anchor=tk.W)
            self.reservations_tree.column(col, width=120, minwidth=100)

        self.reservations_tree.column('ID', width=60)
        self.reservations_tree.column('Room No', width=80)
        self.reservations_tree.column('Guest Name', width=150)
        self.reservations_tree.column('Check-in Date', width=120)
        self.reservations_tree.column('Check-out Date', width=120)
        self.reservations_tree.column('Phone', width=120)
        self.reservations_tree.column('Advance', width=100)
        self.reservations_tree.column('Status', width=100)

        self.reservations_tree.pack(fill=tk.BOTH, expand=True)

        self.load_reservations_data()

    def load_reservations_data(self):
        """Load reservations data."""
        if not hasattr(self, 'reservations_tree'):
            return

        for item in self.reservations_tree.get_children():
            self.reservations_tree.delete(item)

        try:
            reservations = self.hotel.get_reservations()
            today = datetime.now().date()

            for res in reservations:
                check_in_date = datetime.strptime(res['check_in_date'], '%Y-%m-%d').date()
                days_until = (check_in_date - today).days

                # Determine status
                if days_until < 0:
                    status = "OVERDUE"
                    tags = ('overdue',)
                elif days_until == 0:
                    status = "TODAY"
                    tags = ('today',)
                elif days_until <= 2:
                    status = f"SOON ({days_until}d)"
                    tags = ('soon',)
                else:
                    status = "UPCOMING"
                    tags = ('upcoming',)

                values = (
                    res['id'],
                    res['room_number'],
                    res['guest_name'],
                    res['check_in_date'],
                    res['check_out_date'],
                    res.get('guest_phone', ''),
                    f"₹{res.get('advance_payment', 0.0):.2f}",
                    status
                )
                self.reservations_tree.insert('', tk.END, values=values, tags=tags)

            # Configure tags
            self.reservations_tree.tag_configure('overdue', background='#ffcccc')
            self.reservations_tree.tag_configure('today', background='#ffff99')
            self.reservations_tree.tag_configure('soon', background='#ffcc99')
            self.reservations_tree.tag_configure('upcoming', background='#ccffcc')

        except Exception as e:
            self.show_error(f"Error loading reservations: {str(e)}")

    def cancel_reservation(self):
        """Cancel selected reservation."""
        if not hasattr(self, 'reservations_tree') or not self.reservations_tree.selection():
            self.show_error("Please select a reservation to cancel.")
            return

        selection = self.reservations_tree.selection()
        reservation_id = self.reservations_tree.item(selection[0])['values'][0]
        guest_name = self.reservations_tree.item(selection[0])['values'][2]

        if self.ask_confirmation(f"Are you sure you want to cancel reservation for '{guest_name}'?"):
            try:
                self.hotel.cancel_reservation(reservation_id)
                self.show_info("Reservation cancelled successfully!")
                self.load_reservations_data()
            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(f"Error cancelling reservation: {str(e)}")

    # Active Bookings Dialog
    def create_bookings_dialog(self, parent):
        """Create active bookings view in dialog."""
        # Button frame
        button_frame = tk.Frame(parent, bg='white')
        button_frame.pack(fill=tk.X, pady=(0, 15))

        refresh_btn = tk.Button(button_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 12, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_active_bookings, padx=20, pady=10)
        refresh_btn.pack(side=tk.LEFT, padx=5)
        refresh_btn.bind('<Return>', lambda e, b=refresh_btn: self.handle_enter_key(e, b))

        edit_btn = tk.Button(button_frame, text="✏️ EDIT BOOKING",
                             font=('Segoe UI', 12, 'bold'),
                             bg='#f39c12', fg='black', relief='flat', cursor='hand2',
                             command=self.edit_booking_dialog, padx=20, pady=10)
        edit_btn.pack(side=tk.LEFT, padx=5)
        edit_btn.bind('<Return>', lambda e, b=edit_btn: self.handle_enter_key(e, b))

        # Treeview frame
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ('ID', 'Room No', 'Guest Name', 'Check-in Time', 'Phone', 'No. Persons', 'Advance', 'Status')
        self.bookings_tree = ttk.Treeview(tree_container, columns=columns,
                                          yscrollcommand=v_scrollbar.set,
                                          height=15)

        v_scrollbar.config(command=self.bookings_tree.yview)

        for col in columns:
            self.bookings_tree.heading(col, text=col, anchor=tk.W)
            self.bookings_tree.column(col, width=130, minwidth=110)

        self.bookings_tree.column('ID', width=60)
        self.bookings_tree.column('Room No', width=80)
        self.bookings_tree.column('Guest Name', width=150)
        self.bookings_tree.column('Check-in Time', width=160)
        self.bookings_tree.column('Phone', width=130)
        self.bookings_tree.column('No. Persons', width=90)
        self.bookings_tree.column('Advance', width=100)
        self.bookings_tree.column('Status', width=90)

        self.bookings_tree.pack(fill=tk.BOTH, expand=True)

        self.load_active_bookings()

    def load_active_bookings(self):
        """Load active bookings into treeview."""
        if self.bookings_tree is None:
            return

        for item in self.bookings_tree.get_children():
            self.bookings_tree.delete(item)

        try:
            bookings = self.hotel.get_active_bookings()
            for booking in bookings:
                check_in_time = datetime.fromisoformat(booking['check_in_time']).strftime('%Y-%m-%d %H:%M')
                values = (
                    booking['id'],
                    booking['room_number'],
                    booking['guest_name'],
                    check_in_time,
                    booking['guest_phone'],
                    booking.get('no_of_persons', 1),
                    f"₹{booking.get('advance_payment', 0.0):.2f}",
                    booking['status'].upper()
                )
                self.bookings_tree.insert('', tk.END, values=values)
        except Exception as e:
            self.show_error(f"Error loading bookings: {str(e)}")

    def edit_booking_dialog(self):
        """Open dialog to edit booking."""
        if not self.bookings_tree or not self.bookings_tree.selection():
            self.show_error("Please select a booking to edit.")
            return

        selection = self.bookings_tree.selection()
        booking_id = self.bookings_tree.item(selection[0])['values'][0]

        try:
            booking = self.hotel.get_booking_by_id(booking_id)
            if not booking:
                raise ValueError("Booking not found")

            dialog = tk.Toplevel(self.active_dialog if self.active_dialog else self.root)
            dialog.title(f"Edit Booking - ID: {booking_id}")
            dialog.geometry("550x700")
            dialog.transient(self.active_dialog if self.active_dialog else self.root)
            dialog.grab_set()
            dialog.configure(bg='white')
            self.center_dialog(dialog, 550, 700)

            main_frame = tk.Frame(dialog, bg='white', padx=25, pady=25)
            main_frame.pack(fill=tk.BOTH, expand=True)

            tk.Label(main_frame, text=f"EDIT BOOKING - ROOM {booking['room_number']}",
                     font=('Segoe UI', 18, 'bold'), bg='white', fg='#6a4334').pack(pady=(0, 20))

            notebook = ttk.Notebook(main_frame)
            notebook.pack(fill=tk.BOTH, expand=True)

            # Guest Info Tab
            guest_frame = ttk.Frame(notebook)
            notebook.add(guest_frame, text='Guest Info')

            row = 0
            tk.Label(guest_frame, text="Guest Name:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            guest_name_entry = tk.Entry(guest_frame, font=('Segoe UI', 12), width=30)
            guest_name_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            guest_name_entry.insert(0, booking['guest_name'])
            row += 1

            tk.Label(guest_frame, text="Phone:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            phone_entry = tk.Entry(guest_frame, font=('Segoe UI', 12), width=30)
            phone_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            phone_entry.insert(0, booking.get('guest_phone', ''))
            row += 1

            tk.Label(guest_frame, text="Email:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            email_entry = tk.Entry(guest_frame, font=('Segoe UI', 12), width=30)
            email_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            email_entry.insert(0, booking.get('guest_email', ''))
            row += 1

            tk.Label(guest_frame, text="ID Card:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            id_card_entry = tk.Entry(guest_frame, font=('Segoe UI', 12), width=30)
            id_card_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            id_card_entry.insert(0, booking.get('guest_id_card', ''))
            row += 1

            tk.Label(guest_frame, text="Address:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            address_entry = tk.Entry(guest_frame, font=('Segoe UI', 12), width=30)
            address_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            address_entry.insert(0, booking.get('guest_address', ''))
            row += 1

            tk.Label(guest_frame, text="No. of Persons:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            persons_entry = tk.Entry(guest_frame, font=('Segoe UI', 12), width=30)
            persons_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            persons_entry.insert(0, str(booking.get('no_of_persons', 1)))
            row += 1

            # Company Info Tab
            company_frame = ttk.Frame(notebook)
            notebook.add(company_frame, text='Company Info')

            row = 0
            tk.Label(company_frame, text="Company Name:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            company_entry = tk.Entry(company_frame, font=('Segoe UI', 12), width=30)
            company_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            company_entry.insert(0, booking.get('company_name', ''))
            row += 1

            tk.Label(company_frame, text="Company Address:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            company_address_entry = tk.Entry(company_frame, font=('Segoe UI', 12), width=30)
            company_address_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            company_address_entry.insert(0, booking.get('company_address', ''))
            row += 1

            tk.Label(company_frame, text="Party GSTIN:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            gstin_entry = tk.Entry(company_frame, font=('Segoe UI', 12), width=30)
            gstin_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            gstin_entry.insert(0, booking.get('party_gstin', ''))
            row += 1

            # Advance Payment Tab
            advance_frame = ttk.Frame(notebook)
            notebook.add(advance_frame, text='Advance Payment')

            row = 0
            tk.Label(advance_frame, text="Advance Amount (₹):", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            advance_entry = tk.Entry(advance_frame, font=('Segoe UI', 12), width=20)
            advance_entry.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            advance_entry.insert(0, str(booking.get('advance_payment', 0.0)))
            row += 1

            tk.Label(advance_frame, text="Payment Method:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=10, pady=10, sticky='e')
            advance_method = ttk.Combobox(advance_frame, values=['cash', 'card', 'online', 'upi'],
                                          width=18, state='readonly', font=('Segoe UI', 12))
            advance_method.grid(row=row, column=1, padx=10, pady=10, sticky='w')
            advance_method.set(booking.get('advance_payment_method', 'cash'))
            row += 1

            def save_booking():
                try:
                    update_data = {
                        'guest_name': guest_name_entry.get().strip(),
                        'guest_phone': phone_entry.get().strip(),
                        'guest_email': email_entry.get().strip(),
                        'guest_id_card': id_card_entry.get().strip(),
                        'guest_address': address_entry.get().strip(),
                        'no_of_persons': int(persons_entry.get()),
                        'company_name': company_entry.get().strip(),
                        'company_address': company_address_entry.get().strip(),
                        'party_gstin': gstin_entry.get().strip(),
                        'advance_payment': float(advance_entry.get() or 0),
                        'advance_payment_method': advance_method.get()
                    }

                    self.hotel.update_booking(booking_id, update_data)
                    self.show_info("Booking updated successfully!")
                    self.load_active_bookings()
                    dialog.destroy()

                except ValueError as e:
                    self.show_error(str(e))
                except Exception as e:
                    self.show_error(f"Error updating booking: {str(e)}")

            button_frame = tk.Frame(main_frame, bg='white')
            button_frame.pack(pady=20)

            save_btn = tk.Button(button_frame, text="💾 SAVE CHANGES",
                                 font=('Segoe UI', 13, 'bold'),
                                 bg='#27ae60', fg='black', relief='flat',
                                 command=save_booking, padx=40, pady=12)
            save_btn.pack(side=tk.LEFT, padx=10)
            save_btn.bind('<Return>', lambda e, b=save_btn: self.handle_enter_key(e, b))

            cancel_btn = tk.Button(button_frame, text="CANCEL",
                                   font=('Segoe UI', 13, 'bold'),
                                   bg='#95a5a6', fg='black', relief='flat',
                                   command=dialog.destroy, padx=40, pady=12)
            cancel_btn.pack(side=tk.LEFT, padx=10)
            cancel_btn.bind('<Return>', lambda e, b=cancel_btn: self.handle_enter_key(e, b))

        except Exception as e:
            self.show_error(f"Error loading booking: {str(e)}")

    # Food Orders Dialog
    def create_food_orders_dialog(self, parent):
        """Create food orders management in dialog."""
        # Booking selection frame
        booking_frame = tk.LabelFrame(parent, text="Select Booking",
                                      font=('Segoe UI', 12, 'bold'),
                                      bg='white', fg='#6a4334', padx=15, pady=10)
        booking_frame.pack(fill=tk.X, pady=5)

        tk.Label(booking_frame, text="Booking ID:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.food_booking_id = tk.Entry(booking_frame, font=('Segoe UI', 12), width=15)
        self.food_booking_id.pack(side=tk.LEFT, padx=5)
        self.food_booking_id.bind('<Return>', lambda e: self.load_booking_for_food())

        load_btn = tk.Button(booking_frame, text="🔍 LOAD",
                             font=('Segoe UI', 11, 'bold'),
                             bg='#2e86c1', fg='black', relief='flat',
                             command=self.load_booking_for_food, padx=15, pady=5)
        load_btn.pack(side=tk.LEFT, padx=5)
        load_btn.bind('<Return>', lambda e, b=load_btn: self.handle_enter_key(e, b))

        self.food_guest_info = tk.Label(booking_frame, text="", font=('Segoe UI', 12),
                                        bg='white', fg='#2e86c1')
        self.food_guest_info.pack(side=tk.LEFT, padx=20)

        # Food order form
        food_form_frame = tk.LabelFrame(parent, text="Add Food Order",
                                        font=('Segoe UI', 12, 'bold'),
                                        bg='white', fg='#6a4334', padx=15, pady=10)
        food_form_frame.pack(fill=tk.X, pady=5)

        row = 0
        tk.Label(food_form_frame, text="Item Name:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.food_item_name = tk.Entry(food_form_frame, font=('Segoe UI', 12), width=25)
        self.food_item_name.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        row += 1

        tk.Label(food_form_frame, text="Quantity:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.food_quantity = tk.Entry(food_form_frame, font=('Segoe UI', 12), width=25)
        self.food_quantity.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.food_quantity.insert(0, '1')
        row += 1

        tk.Label(food_form_frame, text="Unit Price (₹):", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.food_unit_price = tk.Entry(food_form_frame, font=('Segoe UI', 12), width=25)
        self.food_unit_price.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.food_unit_price.insert(0, '0.00')
        row += 1

        tk.Label(food_form_frame, text="GST %:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.food_gst = ttk.Combobox(food_form_frame, values=['0', '5', '12', '18'],
                                     width=23, state='readonly', font=('Segoe UI', 12))
        self.food_gst.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.food_gst.set('5')
        row += 1

        add_btn = tk.Button(food_form_frame, text="➕ ADD ORDER",
                            font=('Segoe UI', 12, 'bold'),
                            bg='#27ae60', fg='black', relief='flat',
                            command=self.add_food_order, padx=25, pady=10)
        add_btn.grid(row=row, column=0, columnspan=2, pady=10)
        add_btn.bind('<Return>', lambda e, b=add_btn: self.handle_enter_key(e, b))

        # Orders list
        orders_frame = tk.LabelFrame(parent, text="Food Orders",
                                     font=('Segoe UI', 12, 'bold'),
                                     bg='white', fg='#6a4334', padx=15, pady=10)
        orders_frame.pack(fill=tk.BOTH, expand=True)

        tree_frame = tk.Frame(orders_frame, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ('ID', 'Order No', 'Item', 'Qty', 'Unit Price', 'Total', 'GST', 'Status')
        self.food_orders_tree = ttk.Treeview(tree_container, columns=columns,
                                             yscrollcommand=v_scrollbar.set,
                                             height=8)

        v_scrollbar.config(command=self.food_orders_tree.yview)

        for col in columns:
            self.food_orders_tree.heading(col, text=col, anchor=tk.W)
            self.food_orders_tree.column(col, width=120, minwidth=100)

        self.food_orders_tree.column('ID', width=60)
        self.food_orders_tree.column('Order No', width=150)
        self.food_orders_tree.column('Item', width=180)

        self.food_orders_tree.pack(fill=tk.BOTH, expand=True)

        delete_btn = tk.Button(orders_frame, text="🗑️ DELETE SELECTED",
                               font=('Segoe UI', 12, 'bold'),
                               bg='#e74c3c', fg='black', relief='flat',
                               command=self.delete_food_order, padx=20, pady=8)
        delete_btn.pack(pady=5)
        delete_btn.bind('<Return>', lambda e, b=delete_btn: self.handle_enter_key(e, b))

    def load_booking_for_food(self):
        """Load booking details for food order."""
        try:
            booking_id = int(self.food_booking_id.get())
            booking = self.hotel.get_booking_by_id(booking_id)

            if not booking:
                raise ValueError("Booking not found")

            self.food_guest_info.config(
                text=f"Guest: {booking['guest_name']} | Room: {booking['room_number']}"
            )
            self.current_food_booking = booking

            # Load existing orders
            self.load_food_orders(booking_id)

        except ValueError as e:
            self.show_error(str(e))
        except Exception as e:
            self.show_error(f"Error loading booking: {str(e)}")

    def load_food_orders(self, booking_id):
        """Load food orders for a booking."""
        if not hasattr(self, 'food_orders_tree'):
            return

        for item in self.food_orders_tree.get_children():
            self.food_orders_tree.delete(item)

        try:
            orders = self.hotel.get_food_orders_for_booking(booking_id)

            for order in orders:
                values = (
                    order['id'],
                    order['order_number'],
                    order['item_name'],
                    order['quantity'],
                    f"₹{order['unit_price']:.2f}",
                    f"₹{order['total_price']:.2f}",
                    f"{order['gst_percentage']}%",
                    order['status'].upper()
                )
                self.food_orders_tree.insert('', tk.END, values=values)

        except Exception as e:
            self.show_error(f"Error loading food orders: {str(e)}")

    def add_food_order(self):
        """Add a food order."""
        try:
            if not hasattr(self, 'current_food_booking'):
                raise ValueError("Please load a booking first")

            booking = self.current_food_booking

            item_name = self.food_item_name.get().strip()
            if not item_name:
                raise ValueError("Item name is required")

            quantity = int(self.food_quantity.get())
            unit_price = float(self.food_unit_price.get())
            gst = float(self.food_gst.get())

            order_data = {
                'booking_id': booking['id'],
                'room_id': booking['room_id'],
                'item_name': item_name,
                'quantity': quantity,
                'unit_price': unit_price,
                'gst_percentage': gst
            }

            order_id, order_number = self.hotel.add_food_order(order_data)
            self.show_info(f"Food order added successfully!\nOrder No: {order_number}")

            # Clear form
            self.food_item_name.delete(0, tk.END)
            self.food_quantity.delete(0, tk.END)
            self.food_quantity.insert(0, '1')
            self.food_unit_price.delete(0, tk.END)
            self.food_unit_price.insert(0, '0.00')
            self.food_gst.set('5')

            # Refresh orders list
            self.load_food_orders(booking['id'])

        except ValueError as e:
            self.show_error(str(e))
        except Exception as e:
            self.show_error(f"Error adding food order: {str(e)}")

    def delete_food_order(self):
        """Delete selected food order."""
        if not hasattr(self, 'food_orders_tree') or not self.food_orders_tree.selection():
            self.show_error("Please select an order to delete")
            return

        selection = self.food_orders_tree.selection()
        order_id = self.food_orders_tree.item(selection[0])['values'][0]

        if self.ask_confirmation("Are you sure you want to delete this order?"):
            try:
                self.hotel.delete_food_order(order_id)
                self.show_info("Order deleted successfully")
                if hasattr(self, 'current_food_booking'):
                    self.load_food_orders(self.current_food_booking['id'])
            except Exception as e:
                self.show_error(f"Error deleting order: {str(e)}")

    # Generate Bill Dialog
    def create_generate_bill_dialog(self, parent):
        """Create generate bill dialog."""
        # Main content frame with 2 columns
        content_frame = tk.Frame(parent, bg='white')
        content_frame.pack(fill=tk.BOTH, expand=True)

        content_frame.grid_columnconfigure(0, weight=1, uniform="equal")
        content_frame.grid_columnconfigure(1, weight=1, uniform="equal")
        content_frame.grid_rowconfigure(0, weight=1)

        # Left side: Bookings selection
        left_frame = tk.LabelFrame(content_frame, text="Select Booking",
                                   font=('Segoe UI', 14, 'bold'),
                                   bg='white', fg='#6a4334', padx=20, pady=15)
        left_frame.grid(row=0, column=0, sticky='nsew', padx=(0, 10))

        refresh_frame = tk.Frame(left_frame, bg='white')
        refresh_frame.pack(fill=tk.X, pady=(0, 10))

        refresh_btn = tk.Button(refresh_frame, text="🔄 LOAD BOOKINGS",
                                font=('Segoe UI', 12, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_bookings_for_billing, padx=20, pady=8)
        refresh_btn.pack(side=tk.RIGHT)
        refresh_btn.bind('<Return>', lambda e, b=refresh_btn: self.handle_enter_key(e, b))

        tree_frame = tk.Frame(left_frame, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ('ID', 'Room No', 'Guest Name', 'Check-in Time', 'Status')
        self.billings_tree = ttk.Treeview(tree_container, columns=columns,
                                          yscrollcommand=v_scrollbar.set,
                                          height=12, show='headings')

        v_scrollbar.config(command=self.billings_tree.yview)

        for col in columns:
            self.billings_tree.heading(col, text=col, anchor=tk.W)
            self.billings_tree.column(col, width=140, minwidth=120)

        self.billings_tree.pack(fill=tk.BOTH, expand=True)

        # Right side: Bill details form
        right_frame = tk.LabelFrame(content_frame, text="Bill Details",
                                    font=('Segoe UI', 14, 'bold'),
                                    bg='white', fg='#6a4334', padx=20, pady=15)
        right_frame.grid(row=0, column=1, sticky='nsew')

        form_frame = tk.Frame(right_frame, bg='white')
        form_frame.pack(fill=tk.BOTH, expand=True)

        from datetime import datetime

        row = 0
        # Check-out Time
        tk.Label(form_frame, text="Check-out Time:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        checkout_frame = tk.Frame(form_frame, bg='white')
        checkout_frame.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        self.checkout_time_entry = tk.Entry(checkout_frame, font=('Segoe UI', 12), width=20)
        self.checkout_time_entry.pack(side=tk.LEFT)
        self.checkout_time_entry.insert(0, datetime.now().strftime('%Y-%m-%d %H:%M'))

        now_btn = tk.Button(checkout_frame, text="NOW", font=('Segoe UI', 11, 'bold'),
                            bg='#f39c12', fg='black', relief='flat',
                            command=lambda: self.checkout_time_entry.delete(0, tk.END) or
                                            self.checkout_time_entry.insert(0,
                                                                            datetime.now().strftime('%Y-%m-%d %H:%M')),
                            padx=12, pady=3)
        now_btn.pack(side=tk.LEFT, padx=5)
        now_btn.bind('<Return>', lambda e, b=now_btn: self.handle_enter_key(e, b))
        row += 1

        # Tax settings
        tk.Label(form_frame, text="CGST %:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        self.cgst_percentage = tk.Entry(form_frame, font=('Segoe UI', 12), width=15)
        self.cgst_percentage.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        self.cgst_percentage.insert(0, '2.5')
        row += 1

        tk.Label(form_frame, text="SGST %:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        self.sgst_percentage = tk.Entry(form_frame, font=('Segoe UI', 12), width=15)
        self.sgst_percentage.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        self.sgst_percentage.insert(0, '2.5')
        row += 1

        tk.Label(form_frame, text="Discount %:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        self.discount_percentage = tk.Entry(form_frame, font=('Segoe UI', 12), width=15)
        self.discount_percentage.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        self.discount_percentage.insert(0, '0.0')
        row += 1

        # Payment Method
        tk.Label(form_frame, text="Payment Method:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        self.payment_method = ttk.Combobox(form_frame,
                                           values=['cash', 'credit_card', 'debit_card', 'online', 'card'],
                                           width=18, state='readonly', font=('Segoe UI', 12))
        self.payment_method.set('cash')
        self.payment_method.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        row += 1

        tk.Label(form_frame, text="Payment Status:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        self.payment_status = ttk.Combobox(form_frame, values=['paid', 'pending'],
                                           width=18, state='readonly', font=('Segoe UI', 12))
        self.payment_status.set('pending')
        self.payment_status.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        row += 1

        # Verified By
        tk.Label(form_frame, text="Verified By:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        self.verified_by = tk.Entry(form_frame, font=('Segoe UI', 12), width=20)
        self.verified_by.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        if self.auth.current_user:
            self.verified_by.insert(0, self.auth.current_user['username'])
        else:
            self.verified_by.insert(0, 'Kapil')
        row += 1

        # Notes
        tk.Label(form_frame, text="Notes:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='ne')
        self.bill_notes = tk.Text(form_frame, font=('Segoe UI', 12), width=25, height=3)
        self.bill_notes.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        row += 1

        button_frame = tk.Frame(right_frame, bg='white')
        button_frame.pack(pady=15)

        generate_btn = tk.Button(button_frame, text="🧾 GENERATE & PRINT BILL",
                                 font=('Segoe UI', 14, 'bold'),
                                 bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                                 command=self.generate_and_print_bill, padx=40, pady=12)
        generate_btn.pack()
        generate_btn.bind('<Return>', lambda e, b=generate_btn: self.handle_enter_key(e, b))

        self.load_bookings_for_billing()

    def load_bookings_for_billing(self):
        """Load bookings for billing selection."""
        try:
            if not hasattr(self, 'billings_tree') or self.billings_tree is None:
                return

            for item in self.billings_tree.get_children():
                self.billings_tree.delete(item)

            bookings = self.hotel.get_all_bookings_for_billing()
            for booking in bookings:
                check_in_time = booking.get('check_in_time', '')
                if check_in_time:
                    try:
                        check_in_time = datetime.fromisoformat(check_in_time).strftime('%Y-%m-%d %H:%M')
                    except:
                        check_in_time = "Invalid date"

                values = (
                    booking['id'],
                    booking['room_number'],
                    booking['guest_name'],
                    check_in_time,
                    booking['status'].upper()
                )
                self.billings_tree.insert('', tk.END, values=values)

        except Exception as e:
            print(f"Error loading bookings: {e}")

    def generate_and_print_bill(self):
        """Generate and print bill for selected booking."""
        try:
            if not hasattr(self, 'billings_tree') or not self.billings_tree.selection():
                self.show_error("Please select a booking from the list")
                return

            selection = self.billings_tree.selection()
            booking_id = self.billings_tree.item(selection[0])['values'][0]

            booking = self.hotel.get_booking_by_id(booking_id)
            if not booking:
                raise ValueError("Booking not found")

            bill_data = {
                'check_out_time': self.checkout_time_entry.get(),
                'cgst_percentage': float(self.cgst_percentage.get()),
                'sgst_percentage': float(self.sgst_percentage.get()),
                'discount_percentage': float(self.discount_percentage.get()),
                'payment_method': self.payment_method.get(),
                'payment_status': self.payment_status.get(),
                'verified_by': self.verified_by.get(),
                'notes': self.bill_notes.get('1.0', tk.END).strip()
            }

            bill_id, bill_number, total_amount, advance_paid, balance_due, day_breakdowns = self.hotel.generate_bill(
                booking_id, bill_data)

            bill_details = self.hotel.get_bill_by_number(bill_number)
            if bill_details:
                settings = self.hotel.get_hotel_settings()
                bill_details.update(settings)
                self.bill_generator.set_hotel_manager(self.hotel)
                self.bill_generator.print_bill(bill_details, day_breakdowns)

            self.show_info(
                f"✅ Bill generated successfully!\nBill Number: {bill_number}\nTotal: ₹{total_amount:.2f}\nAdvance Paid: ₹{advance_paid:.2f}\nBalance Due: ₹{balance_due:.2f}")

            # Clear form
            self.checkout_time_entry.delete(0, tk.END)
            self.checkout_time_entry.insert(0, datetime.now().strftime('%Y-%m-%d %H:%M'))
            self.cgst_percentage.delete(0, tk.END)
            self.cgst_percentage.insert(0, '2.5')
            self.sgst_percentage.delete(0, tk.END)
            self.sgst_percentage.insert(0, '2.5')
            self.discount_percentage.delete(0, tk.END)
            self.discount_percentage.insert(0, '0.0')
            self.payment_method.set('cash')
            self.payment_status.set('pending')
            self.bill_notes.delete('1.0', tk.END)

            self.load_bookings_for_billing()

        except ValueError as e:
            self.show_error(str(e))
        except Exception as e:
            self.show_error(f"Error generating bill: {str(e)}")

    # View Bills Dialog
    # In create_view_bills_dialog - Update columns
    def create_view_bills_dialog(self, parent):
        """Create view bills dialog with proper bill details."""
        # Filter frame (same as before)
        filter_frame = tk.LabelFrame(parent, text="Filter Bills",
                                     font=('Segoe UI', 12, 'bold'),
                                     bg='white', fg='#6a4334', padx=15, pady=10)
        filter_frame.pack(fill=tk.X, pady=5)

        # Bill Number filter
        tk.Label(filter_frame, text="Bill Number:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=0, column=0, padx=5, pady=8, sticky='e')
        self.bill_number_filter = tk.Entry(filter_frame, font=('Segoe UI', 12), width=20)
        self.bill_number_filter.grid(row=0, column=1, padx=5, pady=8, sticky='w')
        self.bill_number_filter.bind('<Return>', lambda e: self.filter_bills_by_number())

        search_btn = tk.Button(filter_frame, text="🔍 SEARCH",
                               font=('Segoe UI', 11, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.filter_bills_by_number, padx=15, pady=3)
        search_btn.grid(row=0, column=2, padx=5, pady=5)

        # Date range filters
        tk.Label(filter_frame, text="From Date:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=1, column=0, padx=5, pady=8, sticky='e')
        self.bills_from_date = tk.Entry(filter_frame, font=('Segoe UI', 12), width=15)
        self.bills_from_date.grid(row=1, column=1, padx=5, pady=8, sticky='w')

        tk.Label(filter_frame, text="To Date:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=1, column=2, padx=5, pady=8, sticky='e')
        self.bills_to_date = tk.Entry(filter_frame, font=('Segoe UI', 12), width=15)
        self.bills_to_date.grid(row=1, column=3, padx=5, pady=8, sticky='w')

        filter_btn = tk.Button(filter_frame, text="🔍 FILTER",
                               font=('Segoe UI', 11, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.filter_bills_by_date, padx=15, pady=3)
        filter_btn.grid(row=1, column=4, padx=5, pady=5)

        clear_btn = tk.Button(filter_frame, text="🔄 CLEAR",
                              font=('Segoe UI', 11, 'bold'),
                              bg='#95a5a6', fg='black', relief='flat',
                              command=self.clear_bills_filter, padx=15, pady=3)
        clear_btn.grid(row=1, column=5, padx=5, pady=5)

        # Buttons frame
        button_frame = tk.Frame(parent, bg='white')
        button_frame.pack(fill=tk.X, pady=10)

        view_btn = tk.Button(button_frame, text="👁️ VIEW BILL",
                             font=('Segoe UI', 12, 'bold'),
                             bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                             command=self.view_selected_bill, padx=20, pady=8)
        view_btn.pack(side=tk.LEFT, padx=5)
        view_btn.bind('<Return>', lambda e, b=view_btn: self.handle_enter_key(e, b))

        edit_btn = tk.Button(button_frame, text="✏️ EDIT BILL",
                             font=('Segoe UI', 12, 'bold'),
                             bg='#f39c12', fg='black', relief='flat', cursor='hand2',
                             command=self.edit_bill_dialog, padx=20, pady=8)
        edit_btn.pack(side=tk.LEFT, padx=5)
        edit_btn.bind('<Return>', lambda e, b=edit_btn: self.handle_enter_key(e, b))

        refresh_btn = tk.Button(button_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 12, 'bold'),
                                bg='#3498db', fg='black', relief='flat', cursor='hand2',
                                command=self.load_all_bills, padx=20, pady=8)
        refresh_btn.pack(side=tk.RIGHT, padx=5)
        refresh_btn.bind('<Return>', lambda e, b=refresh_btn: self.handle_enter_key(e, b))

        # Treeview frame
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        # Updated columns with proper breakdown
        columns = ('Bill No', 'Room No', 'Guest Name', 'Check-in', 'Check-out',
                   'Total', 'Advance', 'Paid', 'Total Paid', 'Discount')
        self.bills_tree = ttk.Treeview(tree_container, columns=columns,
                                       yscrollcommand=v_scrollbar.set,
                                       xscrollcommand=h_scrollbar.set,
                                       height=15)

        v_scrollbar.config(command=self.bills_tree.yview)
        h_scrollbar.config(command=self.bills_tree.xview)

        for col in columns:
            self.bills_tree.heading(col, text=col, anchor=tk.W)
            self.bills_tree.column(col, width=120, minwidth=100)

        self.bills_tree.column('Bill No', width=180)
        self.bills_tree.column('Guest Name', width=150)
        self.bills_tree.column('Check-in', width=120)
        self.bills_tree.column('Check-out', width=120)
        self.bills_tree.column('Total', width=100)
        self.bills_tree.column('Advance', width=90)
        self.bills_tree.column('Paid', width=90)
        self.bills_tree.column('Total Paid', width=90)
        self.bills_tree.column('Discount', width=90)

        self.bills_tree.pack(fill=tk.BOTH, expand=True)

        self.load_all_bills()

        # Update the create_view_bills_dialog method to include admin edit button (around line 5250)

        # In create_view_bills_dialog, add this button in the button_frame
        # Add this after the settle_btn and before refresh_btn

        if self.auth.is_admin():
            admin_edit_btn = tk.Button(button_frame, text="⚡ ADMIN EDIT",
                                       font=('Segoe UI', 12, 'bold'),
                                       bg='#c0392b', fg='white', relief='flat', cursor='hand2',
                                       command=self.admin_edit_bill_dialog, padx=20, pady=8)
            admin_edit_btn.pack(side=tk.LEFT, padx=5)
            admin_edit_btn.bind('<Return>', lambda e, b=admin_edit_btn: self.handle_enter_key(e, b))

    def filter_bills_by_number(self):
        """Filter bills by bill number."""
        if not hasattr(self, 'bills_tree'):
            return

        bill_number = self.bill_number_filter.get().strip()
        if not bill_number:
            self.show_warning("Please enter a bill number to search")
            return

        # Clear current tree
        for item in self.bills_tree.get_children():
            self.bills_tree.delete(item)

        try:
            bill = self.hotel.get_bill_by_number(bill_number)
            if bill:
                bill_date = datetime.fromisoformat(bill['bill_date']).strftime('%Y-%m-%d %H:%M')
                values = (
                    bill['bill_number'],
                    bill['room_number'],
                    bill['guest_name'],
                    bill_date,
                    f"{int(bill['total_hours'] / 24)}",
                    f"₹{bill['total_amount']:.2f}",
                    f"₹{bill.get('advance_paid', 0.0):.2f}",
                    f"₹{bill.get('balance_due', 0.0):.2f}",
                    bill['payment_status'].upper()
                )
                tags = ('paid',) if bill['payment_status'] == 'paid' else ('pending',)
                if bill.get('balance_due', 0) > 0:
                    tags = ('pending',)
                self.bills_tree.insert('', tk.END, values=values, tags=tags)

                # Configure tags
                self.bills_tree.tag_configure('paid', background='#ccffcc')
                self.bills_tree.tag_configure('pending', background='#ffffcc')

                self.show_info(f"Found bill: {bill_number}")
            else:
                self.show_info(f"No bill found with number: {bill_number}")
                self.load_all_bills()  # Reload all bills

        except Exception as e:
            self.show_error(f"Error searching bill: {str(e)}")

    def filter_bills_by_date(self):
        """Filter bills by date range."""
        from_date = self.bills_from_date.get()
        to_date = self.bills_to_date.get()

        if from_date and to_date:
            try:
                datetime.strptime(from_date, '%Y-%m-%d')
                datetime.strptime(to_date, '%Y-%m-%d')
            except:
                self.show_error("Invalid date format. Use YYYY-MM-DD")
                return

            for item in self.bills_tree.get_children():
                self.bills_tree.delete(item)

            try:
                bills = self.hotel.get_all_bills(from_date, to_date)

                for bill in bills:
                    bill_date = datetime.fromisoformat(bill['bill_date']).strftime('%Y-%m-%d %H:%M')
                    values = (
                        bill['bill_number'],
                        bill['room_number'],
                        bill['guest_name'],
                        bill_date,
                        f"{int(bill['total_hours'] / 24)}",
                        f"₹{bill['total_amount']:.2f}",
                        f"₹{bill.get('advance_paid', 0.0):.2f}",
                        f"₹{bill.get('balance_due', 0.0):.2f}",
                        bill['payment_status'].upper()
                    )

                    tags = ('paid',) if bill['payment_status'] == 'paid' else ('pending',)
                    if bill.get('balance_due', 0) > 0:
                        tags = ('pending',)
                    self.bills_tree.insert('', tk.END, values=values, tags=tags)

                self.bills_tree.tag_configure('paid', background='#ccffcc')
                self.bills_tree.tag_configure('pending', background='#ffffcc')

            except Exception as e:
                self.show_error(f"Error filtering bills: {str(e)}")

    def clear_bills_filter(self):
        """Clear all filters and reload bills."""
        if hasattr(self, 'bill_number_filter'):
            self.bill_number_filter.delete(0, tk.END)
        if hasattr(self, 'bills_from_date'):
            self.bills_from_date.delete(0, tk.END)
        if hasattr(self, 'bills_to_date'):
            self.bills_to_date.delete(0, tk.END)
        self.load_all_bills()

    def load_all_bills(self):
        """Load bills with proper payment breakdown - remove pending field."""
        if not hasattr(self, 'bills_tree') or self.bills_tree is None:
            return

        # Clear all existing items
        for item in self.bills_tree.get_children():
            self.bills_tree.delete(item)

        try:
            thirty_days_ago = (datetime.now() - timedelta(days=30)).date().isoformat()
            bills = self.hotel.get_all_bills(thirty_days_ago, datetime.now().strftime('%Y-%m-%d'))

            for bill in bills:
                # Get settlement details for this bill
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT IFNULL(SUM(paid_amount), 0) as total_paid, 
                           IFNULL(SUM(discount_amount), 0) as total_discount
                    FROM settlements
                    WHERE bill_id = ?
                ''', (bill['id'],))
                settlement_data = cursor.fetchone()
                self.db.return_connection(conn)

                paid = float(settlement_data['total_paid']) if settlement_data and settlement_data[
                    'total_paid'] else 0.0
                discount = float(settlement_data['total_discount']) if settlement_data and settlement_data[
                    'total_discount'] else 0.0

                advance_paid = float(bill.get('advance_paid', 0.0))

                # Total money received = advance + paid
                total_received = advance_paid + paid

                # Format dates properly
                try:
                    bill_date = datetime.fromisoformat(bill['bill_date']).strftime('%Y-%m-%d %H:%M')
                except:
                    bill_date = bill['bill_date']

                try:
                    check_in = datetime.fromisoformat(bill['check_in_time']).strftime('%Y-%m-%d %H:%M')
                except:
                    check_in = bill['check_in_time']

                try:
                    check_out = datetime.fromisoformat(bill['check_out_time']).strftime('%Y-%m-%d %H:%M')
                except:
                    check_out = bill['check_out_time']

                values = (
                    bill['bill_number'],
                    bill['room_number'],
                    bill['guest_name'],
                    check_in,
                    check_out,
                    f"₹{bill['total_amount']:.2f}",
                    f"₹{advance_paid:.2f}",
                    f"₹{paid:.2f}",
                    f"₹{total_received:.2f}",
                    f"₹{discount:.2f}"
                )

                # Color coding based on received amount
                if total_received >= bill['total_amount']:
                    tags = ('paid',)
                elif total_received > 0:
                    tags = ('partial',)
                else:
                    tags = ('pending',)

                self.bills_tree.insert('', tk.END, values=values, tags=tags)

            # Configure tags
            self.bills_tree.tag_configure('paid', background='#ccffcc')
            self.bills_tree.tag_configure('partial', background='#ffffcc')
            self.bills_tree.tag_configure('pending', background='#ffcccc')

            # Add totals row
            self.add_bills_totals()

        except Exception as e:
            self.show_error(f"Error loading bills: {str(e)}")
            import traceback
            traceback.print_exc()

    def add_bills_totals(self):
        """Add totals row at the bottom of bills tree."""
        try:
            # Calculate totals from visible items
            total_gross = 0.0
            total_advance = 0.0
            total_paid = 0.0
            total_received_all = 0.0
            total_discount = 0.0

            for item in self.bills_tree.get_children():
                values = self.bills_tree.item(item)['values']
                if len(values) >= 10 and values[0] != 'TOTAL' and values[0] != '-' * 20:
                    total_gross += float(values[5].replace('₹', ''))
                    total_advance += float(values[6].replace('₹', ''))
                    total_paid += float(values[7].replace('₹', ''))
                    total_received_all += float(values[8].replace('₹', ''))
                    total_discount += float(values[9].replace('₹', ''))

            # Insert separator
            self.bills_tree.insert('', tk.END, values=['-' * 20] * 10)

            # Insert totals row
            totals_values = (
                '💰 TOTAL',
                '',
                '',
                '',
                '',
                f"₹{total_gross:.2f}",
                f"₹{total_advance:.2f}",
                f"₹{total_paid:.2f}",
                f"₹{total_received_all:.2f}",
                f"₹{total_discount:.2f}"
            )
            self.bills_tree.insert('', tk.END, values=totals_values, tags=('total',))
            self.bills_tree.tag_configure('total', background='#e0e0e0', font=('Segoe UI', 12, 'bold'))

        except Exception as e:
            print(f"Error adding totals: {e}")

    def add_bills_totals(self):
        """Add totals row at the bottom of bills tree."""
        try:
            # Calculate totals from visible items
            total_gross = 0.0
            total_advance = 0.0
            total_paid = 0.0
            total_received_all = 0.0
            total_discount = 0.0

            # Get all items in the treeview
            all_items = self.bills_tree.get_children()

            # Filter out any existing totals or separator rows
            for item in all_items:
                values = self.bills_tree.item(item)['values']

                # Skip if it's a separator or total row
                if not values or len(values) < 10:
                    continue

                # Check if first value is a separator or total marker
                first_val = str(values[0]) if values[0] else ''
                if first_val.startswith('-') or first_val == '💰 TOTAL' or first_val == 'TOTAL':
                    continue

                try:
                    # Parse values - they come as strings with ₹ symbol
                    if len(values) >= 6 and values[5]:
                        gross_str = str(values[5]).replace('₹', '').replace(',', '').strip()
                        if gross_str:
                            total_gross += float(gross_str)

                    if len(values) >= 7 and values[6]:
                        advance_str = str(values[6]).replace('₹', '').replace(',', '').strip()
                        if advance_str:
                            total_advance += float(advance_str)

                    if len(values) >= 8 and values[7]:
                        paid_str = str(values[7]).replace('₹', '').replace(',', '').strip()
                        if paid_str:
                            total_paid += float(paid_str)

                    if len(values) >= 9 and values[8]:
                        received_str = str(values[8]).replace('₹', '').replace(',', '').strip()
                        if received_str:
                            total_received_all += float(received_str)

                    if len(values) >= 10 and values[9]:
                        discount_str = str(values[9]).replace('₹', '').replace(',', '').strip()
                        if discount_str:
                            total_discount += float(discount_str)

                except (ValueError, IndexError) as e:
                    print(f"Error parsing values {values}: {e}")
                    continue

            # Remove any existing totals rows first
            for item in all_items:
                values = self.bills_tree.item(item)['values']
                if values and len(values) > 0:
                    first_val = str(values[0]) if values[0] else ''
                    if first_val.startswith('-') or first_val == '💰 TOTAL' or first_val == 'TOTAL':
                        self.bills_tree.delete(item)

            # Insert separator
            separator_values = ['─' * 20] * 10
            self.bills_tree.insert('', tk.END, values=separator_values)

            # Insert totals row with proper formatting
            totals_values = (
                '💰 TOTAL',
                '',
                '',
                '',
                '',
                f"₹{total_gross:.2f}",
                f"₹{total_advance:.2f}",
                f"₹{total_paid:.2f}",
                f"₹{total_received_all:.2f}",
                f"₹{total_discount:.2f}"
            )

            totals_item = self.bills_tree.insert('', tk.END, values=totals_values)

            # Configure tags for totals row
            self.bills_tree.tag_configure('total', background='#e0e0e0', font=('Segoe UI', 12, 'bold'))
            self.bills_tree.item(totals_item, tags=('total',))

        except Exception as e:
            print(f"Error adding totals: {e}")
            import traceback
            traceback.print_exc()

    def view_selected_bill(self):
        """View and print selected bill."""
        if not self.bills_tree.selection():
            self.show_error("Please select a bill to view.")
            return

        selection = self.bills_tree.selection()
        bill_number = self.bills_tree.item(selection[0])['values'][0]

        try:
            bill_details = self.hotel.get_bill_by_number(bill_number)

            if bill_details:
                # Get day breakdowns
                day_breakdowns = self.hotel.get_daily_breakdown(bill_details['id'])

                settings = self.hotel.get_hotel_settings()
                bill_details.update(settings)
                self.bill_generator.set_hotel_manager(self.hotel)
                self.bill_generator.print_bill(bill_details, day_breakdowns)
            else:
                self.show_error("Bill details not found!")
        except Exception as e:
            self.show_error(f"Error viewing bill: {str(e)}")

    def edit_bill_dialog(self):
        """Open dialog to edit bill."""
        if not self.bills_tree.selection():
            self.show_error("Please select a bill to edit.")
            return

        selection = self.bills_tree.selection()
        bill_number = self.bills_tree.item(selection[0])['values'][0]

        try:
            bill = self.hotel.get_bill_by_number(bill_number)
            if not bill:
                raise ValueError("Bill not found")

            dialog = tk.Toplevel(self.active_dialog if self.active_dialog else self.root)
            dialog.title(f"Edit Bill: {bill_number}")
            dialog.geometry("550x600")
            dialog.transient(self.active_dialog if self.active_dialog else self.root)
            dialog.grab_set()
            dialog.configure(bg='white')
            self.center_dialog(dialog, 550, 600)

            main_frame = tk.Frame(dialog, bg='white', padx=25, pady=25)
            main_frame.pack(fill=tk.BOTH, expand=True)

            tk.Label(main_frame, text=f"EDIT BILL", font=('Segoe UI', 18, 'bold'),
                     bg='white', fg='#6a4334').pack(pady=(0, 20))

            form_frame = tk.Frame(main_frame, bg='white')
            form_frame.pack(fill=tk.BOTH, expand=True)

            row = 0
            tk.Label(form_frame, text="Total Amount (₹):", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
            total_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=25)
            total_entry.grid(row=row, column=1, padx=5, pady=10, sticky='w')
            total_entry.insert(0, str(bill['total_amount']))
            row += 1

            tk.Label(form_frame, text="Payment Method:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
            payment_method = ttk.Combobox(form_frame, values=['cash', 'credit_card', 'debit_card', 'online', 'card'],
                                          width=23, state='readonly', font=('Segoe UI', 12))
            payment_method.grid(row=row, column=1, padx=5, pady=10, sticky='w')
            payment_method.set(bill['payment_method'])
            row += 1

            tk.Label(form_frame, text="Payment Status:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
            payment_status = ttk.Combobox(form_frame, values=['paid', 'pending', 'partial'],
                                          width=23, state='readonly', font=('Segoe UI', 12))
            payment_status.grid(row=row, column=1, padx=5, pady=10, sticky='w')
            payment_status.set(bill['payment_status'])
            row += 1

            tk.Label(form_frame, text="Verified By:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
            verified_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=25)
            verified_entry.grid(row=row, column=1, padx=5, pady=10, sticky='w')
            verified_entry.insert(0, bill.get('verified_by', ''))
            row += 1

            tk.Label(form_frame, text="Reason for Change:", font=('Segoe UI', 12),
                     bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='ne')
            reason_entry = tk.Text(form_frame, font=('Segoe UI', 12), width=25, height=3)
            reason_entry.grid(row=row, column=1, padx=5, pady=10, sticky='w')
            row += 1

            def update_bill():
                try:
                    update_data = {
                        'total_amount': float(total_entry.get()),
                        'payment_method': payment_method.get(),
                        'payment_status': payment_status.get(),
                        'verified_by': verified_entry.get().strip()
                    }
                    reason = reason_entry.get('1.0', tk.END).strip()
                    if not reason:
                        raise ValueError("Reason for change is required")

                    self.hotel.update_bill(bill['id'], update_data, reason)
                    self.show_info("Bill updated successfully!")
                    self.load_all_bills()
                    dialog.destroy()

                except ValueError as e:
                    self.show_error(str(e))
                except Exception as e:
                    self.show_error(f"Error updating bill: {str(e)}")

            button_frame = tk.Frame(form_frame, bg='white')
            button_frame.grid(row=row, column=0, columnspan=2, pady=15)

            update_btn = tk.Button(button_frame, text="UPDATE BILL", font=('Segoe UI', 13, 'bold'),
                                   bg='#2e86c1', fg='black', relief='flat',
                                   command=update_bill, padx=30, pady=10)
            update_btn.pack(side=tk.LEFT, padx=5)
            update_btn.bind('<Return>', lambda e, b=update_btn: self.handle_enter_key(e, b))

            cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 13, 'bold'),
                                   bg='#95a5a6', fg='black', relief='flat',
                                   command=dialog.destroy, padx=30, pady=10)
            cancel_btn.pack(side=tk.LEFT, padx=5)
            cancel_btn.bind('<Return>', lambda e, b=cancel_btn: self.handle_enter_key(e, b))

        except Exception as e:
            self.show_error(f"Error loading bill: {str(e)}")

    def open_settlement_dialog_from_bill(self):
        """Open settlement dialog from bill selection."""
        if not self.bills_tree.selection():
            self.show_error("Please select a bill to settle.")
            return

        selection = self.bills_tree.selection()
        bill_number = self.bills_tree.item(selection[0])['values'][0]
        bill = self.hotel.get_bill_by_number(bill_number)

        if not bill:
            self.show_error("Bill not found!")
            return

        self.open_settlement_dialog(bill)

    # Settlements Dialog
    # In create_settlements_dialog - Update columns
    def create_settlements_dialog(self, parent):
        """Create settlements management dialog with proper details."""
        # Button frame
        button_frame = tk.Frame(parent, bg='white')
        button_frame.pack(fill=tk.X, pady=(0, 15))

        refresh_btn = tk.Button(button_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 12, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_pending_settlements, padx=20, pady=10)
        refresh_btn.pack(side=tk.LEFT, padx=5)
        refresh_btn.bind('<Return>', lambda e, b=refresh_btn: self.handle_enter_key(e, b))

        settle_btn = tk.Button(button_frame, text="🤝 SETTLE SELECTED",
                               font=('Segoe UI', 12, 'bold'),
                               bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                               command=self.settle_selected_bill, padx=20, pady=10)
        settle_btn.pack(side=tk.LEFT, padx=5)
        settle_btn.bind('<Return>', lambda e, b=settle_btn: self.handle_enter_key(e, b))

        # Treeview frame
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        # Updated columns with proper breakdown
        columns = ('Bill No', 'Room No', 'Guest Name', 'Check-in', 'Check-out',
                   'Total', 'Advance', 'Paid', 'Discount', 'Settled', 'Balance')
        self.settlements_tree = ttk.Treeview(tree_container, columns=columns,
                                             yscrollcommand=v_scrollbar.set,
                                             xscrollcommand=h_scrollbar.set,
                                             height=15)

        v_scrollbar.config(command=self.settlements_tree.yview)
        h_scrollbar.config(command=self.settlements_tree.xview)

        for col in columns:
            self.settlements_tree.heading(col, text=col, anchor=tk.W)
            self.settlements_tree.column(col, width=120, minwidth=100)

        self.settlements_tree.column('Bill No', width=180)
        self.settlements_tree.column('Guest Name', width=150)
        self.settlements_tree.column('Check-in', width=120)
        self.settlements_tree.column('Check-out', width=120)
        self.settlements_tree.column('Total', width=100)
        self.settlements_tree.column('Advance', width=90)
        self.settlements_tree.column('Paid', width=90)
        self.settlements_tree.column('Discount', width=90)
        self.settlements_tree.column('Settled', width=90)
        self.settlements_tree.column('Balance', width=90)

        self.settlements_tree.pack(fill=tk.BOTH, expand=True)

        self.load_pending_settlements()

    def load_pending_settlements(self):
        """Load bills pending settlement with proper details."""
        if not hasattr(self, 'settlements_tree'):
            return

        for item in self.settlements_tree.get_children():
            self.settlements_tree.delete(item)

        try:
            bills = self.hotel.get_pending_settlements()

            for bill in bills:
                # Get settlement details
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT SUM(paid_amount) as total_paid, 
                           SUM(discount_amount) as total_discount
                    FROM settlements
                    WHERE bill_id = ?
                ''', (bill['id'],))
                settlement_data = cursor.fetchone()
                self.db.return_connection(conn)

                paid = settlement_data['total_paid'] if settlement_data['total_paid'] else 0.0
                discount = settlement_data['total_discount'] if settlement_data['total_discount'] else 0.0
                settled = paid
                balance = max(0, bill['total_amount'] - paid - discount)

                bill_date = datetime.fromisoformat(bill['bill_date']).strftime('%Y-%m-%d %H:%M')
                check_in = datetime.fromisoformat(bill['check_in_time']).strftime('%Y-%m-%d %H:%M')
                check_out = datetime.fromisoformat(bill['check_out_time']).strftime('%Y-%m-%d %H:%M')

                values = (
                    bill['bill_number'],
                    bill['room_number'],
                    bill['guest_name'],
                    check_in,
                    check_out,
                    f"₹{bill['total_amount']:.2f}",
                    f"₹{bill.get('advance_paid', 0.0):.2f}",
                    f"₹{paid:.2f}",
                    f"₹{discount:.2f}",
                    f"₹{settled:.2f}",
                    f"₹{balance:.2f}"
                )

                tags = ('pending',)
                self.settlements_tree.insert('', tk.END, values=values, tags=tags)

            self.settlements_tree.tag_configure('pending', background='#ffffcc')

            # Add totals row
            self.add_settlements_totals()

        except Exception as e:
            self.show_error(f"Error loading settlements: {str(e)}")

    def add_settlements_totals(self):
        """Add totals row at the bottom of settlements tree."""
        try:
            total_amount = 0.0
            total_advance = 0.0
            total_paid = 0.0
            total_discount = 0.0
            total_settled = 0.0
            total_balance = 0.0

            for item in self.settlements_tree.get_children():
                values = self.settlements_tree.item(item)['values']
                if len(values) >= 11:
                    total_amount += float(values[5].replace('₹', ''))
                    total_advance += float(values[6].replace('₹', ''))
                    total_paid += float(values[7].replace('₹', ''))
                    total_discount += float(values[8].replace('₹', ''))
                    total_settled += float(values[9].replace('₹', ''))
                    total_balance += float(values[10].replace('₹', ''))

            # Insert separator
            self.settlements_tree.insert('', tk.END, values=['-' * 20] * 11)

            # Insert totals row
            totals_values = (
                'TOTAL',
                '',
                '',
                '',
                '',
                f"₹{total_amount:.2f}",
                f"₹{total_advance:.2f}",
                f"₹{total_paid:.2f}",
                f"₹{total_discount:.2f}",
                f"₹{total_settled:.2f}",
                f"₹{total_balance:.2f}"
            )
            self.settlements_tree.insert('', tk.END, values=totals_values, tags=('total',))
            self.settlements_tree.tag_configure('total', background='#e0e0e0', font=('Segoe UI', 12, 'bold'))

        except Exception as e:
            print(f"Error adding settlements totals: {e}")

    def load_pending_settlements(self):
        """Load bills pending settlement - show total received."""
        if not hasattr(self, 'settlements_tree'):
            return

        for item in self.settlements_tree.get_children():
            self.settlements_tree.delete(item)

        try:
            bills = self.hotel.get_pending_settlements()

            for bill in bills:
                # Get settlement details
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT SUM(paid_amount) as total_paid, 
                           SUM(discount_amount) as total_discount
                    FROM settlements
                    WHERE bill_id = ?
                ''', (bill['id'],))
                settlement_data = cursor.fetchone()
                self.db.return_connection(conn)

                paid = settlement_data['total_paid'] if settlement_data['total_paid'] else 0.0
                discount = settlement_data['total_discount'] if settlement_data['total_discount'] else 0.0
                advance_paid = bill.get('advance_paid', 0.0)

                total_received = advance_paid + paid
                balance = max(0, bill['total_amount'] - total_received - discount)

                bill_date = datetime.fromisoformat(bill['bill_date']).strftime('%Y-%m-%d %H:%M')
                check_in = datetime.fromisoformat(bill['check_in_time']).strftime('%Y-%m-%d %H:%M')
                check_out = datetime.fromisoformat(bill['check_out_time']).strftime('%Y-%m-%d %H:%M')

                values = (
                    bill['bill_number'],
                    bill['room_number'],
                    bill['guest_name'],
                    check_in,
                    check_out,
                    f"₹{bill['total_amount']:.2f}",
                    f"₹{advance_paid:.2f}",
                    f"₹{paid:.2f}",
                    f"₹{total_received:.2f}",
                    f"₹{discount:.2f}",
                    f"₹{balance:.2f}"
                )

                tags = ('pending',)
                self.settlements_tree.insert('', tk.END, values=values, tags=tags)

            self.settlements_tree.tag_configure('pending', background='#ffffcc')

            # Add totals row
            self.add_settlements_totals()

        except Exception as e:
            self.show_error(f"Error loading settlements: {str(e)}")

    def add_settlements_totals(self):
        """Add totals row at the bottom of settlements tree."""
        try:
            total_gross = 0.0
            total_advance = 0.0
            total_paid = 0.0
            total_received = 0.0
            total_discount = 0.0
            total_balance = 0.0

            for item in self.settlements_tree.get_children():
                values = self.settlements_tree.item(item)['values']
                if len(values) >= 11 and values[0] != 'TOTAL' and values[0] != '-' * 20:
                    total_gross += float(values[5].replace('₹', ''))
                    total_advance += float(values[6].replace('₹', ''))
                    total_paid += float(values[7].replace('₹', ''))
                    total_received += float(values[8].replace('₹', ''))
                    total_discount += float(values[9].replace('₹', ''))
                    total_balance += float(values[10].replace('₹', ''))

            # Insert separator
            self.settlements_tree.insert('', tk.END, values=['-' * 20] * 11)

            # Insert totals row
            totals_values = (
                '💰 TOTAL',
                '',
                '',
                '',
                '',
                f"₹{total_gross:.2f}",
                f"₹{total_advance:.2f}",
                f"₹{total_paid:.2f}",
                f"₹{total_received:.2f}",
                f"₹{total_discount:.2f}",
                f"₹{total_balance:.2f}"
            )
            self.settlements_tree.insert('', tk.END, values=totals_values, tags=('total',))
            self.settlements_tree.tag_configure('total', background='#e0e0e0', font=('Segoe UI', 12, 'bold'))

        except Exception as e:
            print(f"Error adding settlements totals: {e}")

    def settle_selected_bill(self):
        """Open settlement dialog for selected bill."""
        if not hasattr(self, 'settlements_tree') or not self.settlements_tree.selection():
            self.show_error("Please select a bill to settle.")
            return

        selection = self.settlements_tree.selection()
        bill_number = self.settlements_tree.item(selection[0])['values'][0]
        bill = self.hotel.get_bill_by_number(bill_number)

        if not bill:
            self.show_error("Bill not found!")
            return

        self.open_settlement_dialog(bill)

    def open_settlement_dialog(self, bill):
        """Open settlement dialog for a bill."""
        dialog = tk.Toplevel(self.active_dialog if self.active_dialog else self.root)
        dialog.title(f"Settlement - Bill: {bill['bill_number']}")
        dialog.geometry("500x600")
        dialog.transient(self.active_dialog if self.active_dialog else self.root)
        dialog.grab_set()
        dialog.configure(bg='white')
        self.center_dialog(dialog, 500, 600)

        main_frame = tk.Frame(dialog, bg='white', padx=25, pady=25)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="BILL SETTLEMENT", font=('Segoe UI', 18, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        # Bill summary
        summary_frame = tk.LabelFrame(main_frame, text="Bill Summary",
                                      font=('Segoe UI', 12, 'bold'),
                                      bg='white', fg='#6a4334', padx=15, pady=10)
        summary_frame.pack(fill=tk.X, pady=10)

        tk.Label(summary_frame, text=f"Bill No: {bill['bill_number']}", font=('Segoe UI', 12),
                 bg='white', fg='#333333').pack(anchor=tk.W, pady=2)
        tk.Label(summary_frame, text=f"Guest: {bill['guest_name']}", font=('Segoe UI', 12),
                 bg='white', fg='#333333').pack(anchor=tk.W, pady=2)
        tk.Label(summary_frame, text=f"Room: {bill['room_number']}", font=('Segoe UI', 12),
                 bg='white', fg='#333333').pack(anchor=tk.W, pady=2)
        tk.Label(summary_frame, text=f"Total Amount: ₹{bill['total_amount']:.2f}", font=('Segoe UI', 12, 'bold'),
                 bg='white', fg='#2e86c1').pack(anchor=tk.W, pady=2)
        tk.Label(summary_frame, text=f"Advance Paid: ₹{bill.get('advance_paid', 0.0):.2f}", font=('Segoe UI', 12),
                 bg='white', fg='#27ae60').pack(anchor=tk.W, pady=2)
        tk.Label(summary_frame, text=f"Balance Due: ₹{bill.get('balance_due', 0.0):.2f}", font=('Segoe UI', 12, 'bold'),
                 bg='white', fg='#e74c3c').pack(anchor=tk.W, pady=2)

        # Settlement form
        form_frame = tk.LabelFrame(main_frame, text="Settlement Details",
                                   font=('Segoe UI', 12, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        form_frame.pack(fill=tk.X, pady=10)

        row = 0
        tk.Label(form_frame, text="Amount Paid (₹):", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        paid_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=20)
        paid_entry.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        paid_entry.insert(0, str(bill.get('balance_due', 0.0)))

        # Add quick buttons for common payment amounts
        quick_frame = tk.Frame(form_frame, bg='white')
        quick_frame.grid(row=row, column=2, padx=5, pady=10, sticky='w')

        def set_full():
            paid_entry.delete(0, tk.END)
            paid_entry.insert(0, str(bill.get('balance_due', 0.0)))

        full_btn = tk.Button(quick_frame, text="Full", font=('Segoe UI', 10),
                             bg='#3498db', fg='black', relief='flat',
                             command=set_full, padx=8, pady=2)
        full_btn.pack(side=tk.LEFT, padx=2)
        full_btn.bind('<Return>', lambda e, b=full_btn: self.handle_enter_key(e, b))

        row += 1

        tk.Label(form_frame, text="Discount (₹):", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        discount_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=20)
        discount_entry.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        discount_entry.insert(0, '0.00')
        row += 1

        tk.Label(form_frame, text="Payment Method:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        payment_method = ttk.Combobox(form_frame, values=['cash', 'card', 'online', 'upi'],
                                      width=18, state='readonly', font=('Segoe UI', 12))
        payment_method.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        payment_method.set('cash')
        row += 1

        tk.Label(form_frame, text="Notes:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='ne')
        notes_entry = tk.Text(form_frame, font=('Segoe UI', 12), width=20, height=3)
        notes_entry.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        row += 1

        def process_settlement():
            try:
                paid = float(paid_entry.get() or 0)
                discount = float(discount_entry.get() or 0)

                if paid < 0 or discount < 0:
                    raise ValueError("Amounts cannot be negative")

                if paid == 0 and discount == 0:
                    raise ValueError("Either paid amount or discount must be greater than 0")

                balance_due = bill.get('balance_due', 0.0)

                # Allow small rounding differences
                if paid + discount > balance_due + 0.01:
                    raise ValueError(
                        f"Paid amount + discount ({paid + discount:.2f}) cannot exceed balance due ({balance_due:.2f})")

                settlement_data = {
                    'paid_amount': paid,
                    'discount_amount': discount,
                    'payment_method': payment_method.get(),
                    'notes': notes_entry.get('1.0', tk.END).strip()
                }

                result = self.hotel.settle_bill(bill['id'], settlement_data)

                self.show_info(
                    f"✅ Settlement completed!\n\n"
                    f"Bill No: {bill['bill_number']}\n"
                    f"Total Amount: ₹{result['total_amount']:.2f}\n"
                    f"Paid: ₹{result['paid_amount']:.2f}\n"
                    f"Discount: ₹{result['discount_amount']:.2f}\n"
                    f"Remaining Balance: ₹{result['balance_amount']:.2f}"
                )

                dialog.destroy()
                self.load_pending_settlements()
                self.load_all_bills()

            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(f"Error processing settlement: {str(e)}")

        # Calculate preview
        preview_frame = tk.Frame(main_frame, bg='#f0f0f0', bd=1, relief=tk.SOLID)
        preview_frame.pack(fill=tk.X, pady=10, padx=5)

        preview_label = tk.Label(preview_frame, text="", font=('Segoe UI', 11),
                                 bg='#f0f0f0', fg='#333333')
        preview_label.pack(pady=5)

        def update_preview(*args):
            try:
                paid = float(paid_entry.get() or 0)
                discount = float(discount_entry.get() or 0)
                balance = bill.get('balance_due', 0.0)
                remaining = balance - paid - discount
                if remaining < 0:
                    remaining = 0
                preview_label.config(
                    text=f"After settlement: Paid ₹{paid:.2f} + Discount ₹{discount:.2f} = Remaining ₹{remaining:.2f}"
                )
            except:
                preview_label.config(text="Enter valid amounts")

        paid_entry.bind('<KeyRelease>', update_preview)
        discount_entry.bind('<KeyRelease>', update_preview)
        update_preview()

        button_frame = tk.Frame(main_frame, bg='white')
        button_frame.pack(pady=20)

        settle_btn = tk.Button(button_frame, text="✅ PROCESS SETTLEMENT",
                               font=('Segoe UI', 13, 'bold'),
                               bg='#27ae60', fg='black', relief='flat',
                               command=process_settlement, padx=30, pady=10)
        settle_btn.pack(side=tk.LEFT, padx=5)
        settle_btn.bind('<Return>', lambda e, b=settle_btn: self.handle_enter_key(e, b))

        cancel_btn = tk.Button(button_frame, text="CANCEL",
                               font=('Segoe UI', 13, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat',
                               command=dialog.destroy, padx=30, pady=10)
        cancel_btn.pack(side=tk.LEFT, padx=5)
        cancel_btn.bind('<Return>', lambda e, b=cancel_btn: self.handle_enter_key(e, b))

    # Sales Summary Dialog
    # In create_sales_dialog method - Update columns
    def create_sales_dialog(self, parent):
        """Create sales summary dialog with proper money received breakdown."""
        # Filter frame (same as before)
        filter_frame = tk.LabelFrame(parent, text="Filter",
                                     font=('Segoe UI', 12, 'bold'),
                                     bg='white', fg='#6a4334', padx=15, pady=10)
        filter_frame.pack(fill=tk.X, pady=5)

        tk.Label(filter_frame, text="From Date:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=0, column=0, padx=5, pady=8, sticky='e')
        self.from_date = tk.Entry(filter_frame, font=('Segoe UI', 12), width=15)
        self.from_date.grid(row=0, column=1, padx=5, pady=8, sticky='w')

        tk.Label(filter_frame, text="To Date:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=0, column=2, padx=5, pady=8, sticky='e')
        self.to_date = tk.Entry(filter_frame, font=('Segoe UI', 12), width=15)
        self.to_date.grid(row=0, column=3, padx=5, pady=8, sticky='w')

        filter_btn = tk.Button(filter_frame, text="🔍 FILTER",
                               font=('Segoe UI', 11, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.load_sales_summary, padx=15, pady=5)
        filter_btn.grid(row=0, column=4, padx=5, pady=5)
        filter_btn.bind('<Return>', lambda e, b=filter_btn: self.handle_enter_key(e, b))

        clear_btn = tk.Button(filter_frame, text="🔄 CLEAR",
                              font=('Segoe UI', 11, 'bold'),
                              bg='#95a5a6', fg='black', relief='flat',
                              command=self.clear_sales_filter, padx=15, pady=5)
        clear_btn.grid(row=0, column=5, padx=5, pady=5)
        clear_btn.bind('<Return>', lambda e, b=clear_btn: self.handle_enter_key(e, b))

        # Export buttons
        self.add_export_buttons_to_sales_dialog(parent)

        # Treeview frame
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        # Updated columns - removed pending field
        columns = ('Date', 'Bookings', 'Gross Amount', 'Advance Received',
                   'Settlement Received', '💰 TOTAL RECEIVED', 'Discount Given')
        self.sales_tree = ttk.Treeview(tree_container, columns=columns,
                                       yscrollcommand=v_scrollbar.set,
                                       xscrollcommand=h_scrollbar.set,
                                       height=15)

        v_scrollbar.config(command=self.sales_tree.yview)
        h_scrollbar.config(command=self.sales_tree.xview)

        for col in columns:
            self.sales_tree.heading(col, text=col, anchor=tk.W)
            width = 130
            if col == '💰 TOTAL RECEIVED':
                width = 150
            self.sales_tree.column(col, width=width, minwidth=110)

        self.sales_tree.column('Date', width=120)
        self.sales_tree.column('Bookings', width=80)
        self.sales_tree.column('Gross Amount', width=130)
        self.sales_tree.column('Advance Received', width=140)
        self.sales_tree.column('Settlement Received', width=150)
        self.sales_tree.column('💰 TOTAL RECEIVED', width=150)
        self.sales_tree.column('Discount Given', width=130)

        self.sales_tree.pack(fill=tk.BOTH, expand=True)

        # Bind double-click to show details
        self.sales_tree.bind('<Double-1>', self.show_detailed_sales)

        # Summary label
        self.total_summary = tk.Label(parent, text="", font=('Segoe UI', 14, 'bold'),
                                      bg='white', fg='#6a4334')
        self.total_summary.pack(pady=10)

        self.load_sales_summary()

    # Update the load_sales_summary method
    def load_sales_summary(self):
        """Load sales summary data with total money received."""
        if not hasattr(self, 'sales_tree'):
            return

        for item in self.sales_tree.get_children():
            self.sales_tree.delete(item)

        try:
            from_date = self.from_date.get() if self.from_date.get() else None
            to_date = self.to_date.get() if self.to_date.get() else None

            # Get detailed sales for each day in range
            if from_date and to_date:
                current_date = datetime.strptime(from_date, '%Y-%m-%d')
                end_date = datetime.strptime(to_date, '%Y-%m-%d')
            else:
                # Default to last 30 days
                end_date = datetime.now()
                current_date = end_date - timedelta(days=30)
                from_date = current_date.strftime('%Y-%m-%d')
                to_date = end_date.strftime('%Y-%m-%d')

            daily_summaries = []

            while current_date <= end_date:
                date_str = current_date.strftime('%Y-%m-%d')
                detailed = self.hotel.get_detailed_sales(date_str)

                # Calculate daily totals
                gross_amount = sum(b['total_amount'] for b in detailed['bills'])

                # Advance received (from bookings)
                advance_received = sum(b.get('advance_paid', 0.0) for b in detailed['bills'])

                # Settlement received (actual cash collected during settlement)
                settlement_received = sum(s['paid_amount'] for s in detailed['settlements'])

                # TOTAL MONEY RECEIVED = Advance + Settlement
                total_received = advance_received + settlement_received

                # Discount given
                discounts = sum(s['discount_amount'] for s in detailed['settlements'])

                if gross_amount > 0 or len(detailed['bills']) > 0:
                    daily_summaries.append({
                        'date': date_str,
                        'bookings': len(detailed['bills']),
                        'gross_amount': gross_amount,
                        'advance_received': advance_received,
                        'settlement_received': settlement_received,
                        'total_received': total_received,
                        'discount': discounts
                    })

                current_date += timedelta(days=1)

            # Insert into treeview
            for summary in daily_summaries:
                values = (
                    summary['date'],
                    summary['bookings'],
                    f"₹{summary['gross_amount']:.2f}",
                    f"₹{summary['advance_received']:.2f}",
                    f"₹{summary['settlement_received']:.2f}",
                    f"₹{summary['total_received']:.2f}",
                    f"₹{summary['discount']:.2f}"
                )
                # Color code the total received in green
                item_id = self.sales_tree.insert('', tk.END, values=values)
                self.sales_tree.tag_configure('received', foreground='#27ae60', font=('Segoe UI', 12, 'bold'))
                self.sales_tree.item(item_id, tags=('received',))

            # Calculate totals
            total_bookings = sum(s['bookings'] for s in daily_summaries)
            total_gross = sum(s['gross_amount'] for s in daily_summaries)
            total_advance = sum(s['advance_received'] for s in daily_summaries)
            total_settlement = sum(s['settlement_received'] for s in daily_summaries)
            total_received_all = sum(s['total_received'] for s in daily_summaries)
            total_discount = sum(s['discount'] for s in daily_summaries)

            # Insert totals row
            self.sales_tree.insert('', tk.END, values=['-' * 20] * 7)

            totals_values = (
                'TOTAL',
                total_bookings,
                f"₹{total_gross:.2f}",
                f"₹{total_advance:.2f}",
                f"₹{total_settlement:.2f}",
                f"💰 ₹{total_received_all:.2f}",
                f"₹{total_discount:.2f}"
            )
            totals_item = self.sales_tree.insert('', tk.END, values=totals_values, tags=('total',))

            # Configure tags
            self.sales_tree.tag_configure('total', background='#e0e0e0', font=('Segoe UI', 12, 'bold'))
            self.sales_tree.tag_configure('received', foreground='#27ae60')

            # Update summary label
            self.total_summary.config(
                text=f"📊 SUMMARY: Bookings: {total_bookings} | "
                     f"Gross: ₹{total_gross:.2f} | "
                     f"Advance: ₹{total_advance:.2f} | "
                     f"Settlement: ₹{total_settlement:.2f} | "
                     f"💰 TOTAL CASH RECEIVED: ₹{total_received_all:.2f} | "
                     f"Discount: ₹{total_discount:.2f}"
            )

        except Exception as e:
            self.show_error(f"Error loading sales: {str(e)}")

    def show_detailed_sales(self, event):
        """Show detailed sales for selected date including settlements."""
        selection = self.sales_tree.selection()
        if not selection:
            return

        date_str = self.sales_tree.item(selection[0])['values'][0]

        try:
            detailed = self.hotel.get_detailed_sales(date_str)

            dialog = tk.Toplevel(self.active_dialog if self.active_dialog else self.root)
            dialog.title(f"Detailed Sales - {date_str}")
            dialog.geometry("1000x700")
            dialog.transient(self.active_dialog if self.active_dialog else self.root)
            dialog.grab_set()
            dialog.configure(bg='white')
            self.center_dialog(dialog, 1000, 700)

            main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
            main_frame.pack(fill=tk.BOTH, expand=True)

            tk.Label(main_frame, text=f"Sales Details for {date_str}",
                     font=('Segoe UI', 16, 'bold'), bg='white', fg='#6a4334').pack(pady=(0, 15))

            # Create notebook for tabs
            notebook = ttk.Notebook(main_frame)
            notebook.pack(fill=tk.BOTH, expand=True)

            # Bills Tab
            bills_frame = ttk.Frame(notebook)
            notebook.add(bills_frame, text="Bills")

            bills_tree_frame = tk.Frame(bills_frame, bg='white')
            bills_tree_frame.pack(fill=tk.BOTH, expand=True)

            bills_container = tk.Frame(bills_tree_frame, bg='white')
            bills_container.pack(fill=tk.BOTH, expand=True)

            bills_scroll = ttk.Scrollbar(bills_container)
            bills_scroll.pack(side=tk.RIGHT, fill=tk.Y)

            bills_columns = ('Bill No', 'Room No', 'Guest Name', 'Check-in', 'Check-out', 'Total', 'Status')
            bills_tree = ttk.Treeview(bills_container, columns=bills_columns,
                                      yscrollcommand=bills_scroll.set,
                                      height=12)

            bills_scroll.config(command=bills_tree.yview)

            for col in bills_columns:
                bills_tree.heading(col, text=col, anchor=tk.W)
                bills_tree.column(col, width=120, minwidth=100)

            bills_tree.column('Bill No', width=180)
            bills_tree.column('Guest Name', width=150)
            bills_tree.column('Check-in', width=150)
            bills_tree.column('Check-out', width=150)

            bills_tree.pack(fill=tk.BOTH, expand=True)

            for sale in detailed['bills']:
                check_in = datetime.fromisoformat(sale['check_in_time']).strftime('%d/%m %H:%M')
                check_out = datetime.fromisoformat(sale['check_out_time']).strftime('%d/%m %H:%M')
                values = (
                    sale['bill_number'],
                    sale['room_number'],
                    sale['guest_name'],
                    check_in,
                    check_out,
                    f"₹{sale['total_amount']:.2f}",
                    sale['payment_status'].upper()
                )
                bills_tree.insert('', tk.END, values=values)

            # Settlements Tab
            settlements_frame = ttk.Frame(notebook)
            notebook.add(settlements_frame, text="Settlements")

            settlements_tree_frame = tk.Frame(settlements_frame, bg='white')
            settlements_tree_frame.pack(fill=tk.BOTH, expand=True)

            settlements_container = tk.Frame(settlements_tree_frame, bg='white')
            settlements_container.pack(fill=tk.BOTH, expand=True)

            settlements_scroll = ttk.Scrollbar(settlements_container)
            settlements_scroll.pack(side=tk.RIGHT, fill=tk.Y)

            settlements_columns = ('Bill No', 'Room No', 'Guest Name', 'Total Amount', 'Paid', 'Discount', 'Balance',
                                   'Method')
            settlements_tree = ttk.Treeview(settlements_container, columns=settlements_columns,
                                            yscrollcommand=settlements_scroll.set,
                                            height=12)

            settlements_scroll.config(command=settlements_tree.yview)

            for col in settlements_columns:
                settlements_tree.heading(col, text=col, anchor=tk.W)
                settlements_tree.column(col, width=120, minwidth=100)

            settlements_tree.column('Bill No', width=180)
            settlements_tree.column('Guest Name', width=150)
            settlements_tree.column('Total Amount', width=120)
            settlements_tree.column('Paid', width=100)
            settlements_tree.column('Discount', width=100)
            settlements_tree.column('Balance', width=100)
            settlements_tree.column('Method', width=100)

            settlements_tree.pack(fill=tk.BOTH, expand=True)

            for settlement in detailed['settlements']:
                values = (
                    settlement['bill_number'],
                    settlement['room_number'],
                    settlement['guest_name'],
                    f"₹{settlement['total_amount']:.2f}",
                    f"₹{settlement['paid_amount']:.2f}",
                    f"₹{settlement['discount_amount']:.2f}",
                    f"₹{settlement['balance_amount']:.2f}",
                    settlement['payment_method'].upper()
                )
                settlements_tree.insert('', tk.END, values=values)

            # Summary
            summary_frame = tk.Frame(main_frame, bg='#f0f0f0', bd=1, relief=tk.SOLID)
            summary_frame.pack(fill=tk.X, pady=10)

            total_bills = sum(sale['total_amount'] for sale in detailed['bills'])
            total_settled = sum(s['paid_amount'] for s in detailed['settlements'])

            summary_text = f"Total Bills: ₹{total_bills:.2f} | Total Settlements: ₹{total_settled:.2f}"
            tk.Label(summary_frame, text=summary_text, font=('Segoe UI', 12, 'bold'),
                     bg='#f0f0f0', fg='#333333', padx=10, pady=5).pack()

            close_btn = tk.Button(main_frame, text="CLOSE", font=('Segoe UI', 12, 'bold'),
                                  bg='#2e86c1', fg='black', relief='flat',
                                  command=dialog.destroy, padx=30, pady=8)
            close_btn.pack(pady=10)
            close_btn.bind('<Return>', lambda e, b=close_btn: self.handle_enter_key(e, b))

        except Exception as e:
            self.show_error(f"Error loading details: {str(e)}")

    def clear_sales_filter(self):
        """Clear sales filter."""
        self.from_date.delete(0, tk.END)
        self.to_date.delete(0, tk.END)
        self.load_sales_summary()

    # Users Dialog
    def create_users_dialog(self, parent):
        """Create user management dialog."""
        # Button frame
        button_frame = tk.Frame(parent, bg='white')
        button_frame.pack(fill=tk.X, pady=(0, 15))

        add_btn = tk.Button(button_frame, text="➕ ADD USER",
                            font=('Segoe UI', 12, 'bold'),
                            bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                            command=self.open_add_user_dialog, padx=20, pady=8)
        add_btn.pack(side=tk.LEFT, padx=5)
        add_btn.bind('<Return>', lambda e, b=add_btn: self.handle_enter_key(e, b))

        delete_btn = tk.Button(button_frame, text="🗑️ DELETE",
                               font=('Segoe UI', 12, 'bold'),
                               bg='#e74c3c', fg='black', relief='flat', cursor='hand2',
                               command=self.delete_selected_user, padx=20, pady=8)
        delete_btn.pack(side=tk.LEFT, padx=5)
        delete_btn.bind('<Return>', lambda e, b=delete_btn: self.handle_enter_key(e, b))

        refresh_btn = tk.Button(button_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 12, 'bold'),
                                bg='#3498db', fg='black', relief='flat', cursor='hand2',
                                command=self.load_users_data, padx=20, pady=8)
        refresh_btn.pack(side=tk.RIGHT, padx=5)
        refresh_btn.bind('<Return>', lambda e, b=refresh_btn: self.handle_enter_key(e, b))

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
            self.users_tree.column(col, width=180, minwidth=150)

        self.users_tree.column('ID', width=60)
        self.users_tree.column('Role', width=100)

        self.users_tree.pack(fill=tk.BOTH, expand=True)

        self.load_users_data()

    def load_users_data(self):
        """Load users data."""
        if self.users_tree is None:
            return

        for item in self.users_tree.get_children():
            self.users_tree.delete(item)

        try:
            users = self.db.get_all_users()
            for user in users:
                values = (
                    user['id'],
                    user['username'],
                    user['role'].upper(),
                    user.get('email', ''),
                    user.get('created_at', '').split()[0] if user.get('created_at') else ''
                )
                self.users_tree.insert('', tk.END, values=values)
        except Exception as e:
            self.show_error(f"Error loading users: {str(e)}")

    def open_add_user_dialog(self):
        """Open dialog to add a new user."""
        dialog = tk.Toplevel(self.active_dialog if self.active_dialog else self.root)
        dialog.title("Add New User")
        dialog.geometry("550x550")
        dialog.transient(self.active_dialog if self.active_dialog else self.root)
        dialog.grab_set()
        dialog.configure(bg='white')
        self.center_dialog(dialog, 550, 550)

        main_frame = tk.Frame(dialog, bg='white', padx=30, pady=30)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="ADD NEW USER", font=('Segoe UI', 18, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        form_frame = tk.Frame(main_frame, bg='white')
        form_frame.pack(fill=tk.BOTH, expand=True)

        row = 0
        tk.Label(form_frame, text="Username:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        username_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        username_entry.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        row += 1

        tk.Label(form_frame, text="Password:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        password_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30, show="*")
        password_entry.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        row += 1

        tk.Label(form_frame, text="Confirm:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        confirm_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30, show="*")
        confirm_entry.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        row += 1

        tk.Label(form_frame, text="Role:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        role_var = tk.StringVar(value='user')
        role_combo = ttk.Combobox(form_frame, values=['admin', 'user'],
                                  width=28, state='readonly', font=('Segoe UI', 12))
        role_combo.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        role_combo.set('user')
        row += 1

        tk.Label(form_frame, text="Email:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        email_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=30)
        email_entry.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        row += 1

        def add_user():
            try:
                username = username_entry.get().strip()
                password = password_entry.get()
                confirm = confirm_entry.get()

                if not username:
                    raise ValueError("Username is required")
                if not password:
                    raise ValueError("Password is required")
                if password != confirm:
                    raise ValueError("Passwords do not match")
                if len(password) < 4:
                    raise ValueError("Password must be at least 4 characters")

                role = role_var.get()
                email = email_entry.get().strip()

                user_data = {
                    'username': username,
                    'password': password,
                    'role': role,
                    'email': email
                }

                self.db.add_user(user_data)
                self.show_info(f"User '{username}' added successfully!")
                self.load_users_data()
                dialog.destroy()

            except ValueError as e:
                self.show_error(str(e))
            except sqlite3.IntegrityError:
                self.show_error("Username already exists!")
            except Exception as e:
                self.show_error(f"Error adding user: {str(e)}")

        button_frame = tk.Frame(form_frame, bg='white')
        button_frame.grid(row=row, column=0, columnspan=2, pady=15)

        add_btn = tk.Button(button_frame, text="ADD USER", font=('Segoe UI', 13, 'bold'),
                            bg='#27ae60', fg='black', relief='flat',
                            command=add_user, padx=30, pady=10)
        add_btn.pack(side=tk.LEFT, padx=5)
        add_btn.bind('<Return>', lambda e, b=add_btn: self.handle_enter_key(e, b))

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 13, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat',
                               command=dialog.destroy, padx=30, pady=10)
        cancel_btn.pack(side=tk.LEFT, padx=5)
        cancel_btn.bind('<Return>', lambda e, b=cancel_btn: self.handle_enter_key(e, b))

        # Set focus
        username_entry.focus()

    def delete_selected_user(self):
        """Delete selected user."""
        if not self.users_tree.selection():
            self.show_error("Please select a user to delete")
            return

        selection = self.users_tree.selection()
        user_id = self.users_tree.item(selection[0])['values'][0]
        username = self.users_tree.item(selection[0])['values'][1]

        if self.ask_confirmation(f"Delete user '{username}'?"):
            try:
                self.hotel.delete_user(user_id)
                self.show_info(f"User '{username}' deleted")
                self.load_users_data()
            except ValueError as e:
                self.show_error(str(e))

    # Settings Dialog
    def create_settings_dialog(self, parent):
        """Create hotel settings dialog."""
        form_frame = tk.Frame(parent, bg='white', padx=25, pady=25)
        form_frame.pack(fill=tk.BOTH, expand=True)

        settings = self.hotel.get_hotel_settings()

        row = 0
        tk.Label(form_frame, text="Hotel Name:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        self.hotel_name_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=40)
        self.hotel_name_entry.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        self.hotel_name_entry.insert(0, settings.get('hotel_name', 'THE EVAANI'))
        row += 1

        tk.Label(form_frame, text="Unit:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        self.unit_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=40)
        self.unit_entry.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        self.unit_entry.insert(0, settings.get('unit', 'Unit of BY JS HOTELS & FOODS'))
        row += 1

        tk.Label(form_frame, text="Address:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='ne')
        self.address_entry = tk.Text(form_frame, font=('Segoe UI', 12), width=40, height=3)
        self.address_entry.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        self.address_entry.insert('1.0', settings.get('address', 'Talwandi Road, Mansa'))
        row += 1

        tk.Label(form_frame, text="Phone:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        self.phone_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=40)
        self.phone_entry.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        self.phone_entry.insert(0, settings.get('phone', '9530752236, 9915297440'))
        row += 1

        tk.Label(form_frame, text="GSTIN:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=10, sticky='e')
        self.gstin_entry = tk.Entry(form_frame, font=('Segoe UI', 12), width=40)
        self.gstin_entry.grid(row=row, column=1, padx=5, pady=10, sticky='w')
        self.gstin_entry.insert(0, settings.get('gstin', '03AATFJ9071F1Z3'))
        row += 1

        def save_settings():
            try:
                settings_data = {
                    'hotel_name': self.hotel_name_entry.get().strip(),
                    'unit': self.unit_entry.get().strip(),
                    'address': self.address_entry.get('1.0', tk.END).strip(),
                    'phone': self.phone_entry.get().strip(),
                    'gstin': self.gstin_entry.get().strip()
                }
                self.hotel.update_hotel_settings(settings_data)
                self.show_info("Settings saved successfully!")
            except Exception as e:
                self.show_error(f"Error saving settings: {str(e)}")

        save_btn = tk.Button(form_frame, text="💾 SAVE SETTINGS",
                             font=('Segoe UI', 14, 'bold'),
                             bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                             command=save_settings, padx=40, pady=12)
        save_btn.grid(row=row, column=0, columnspan=2, pady=15)
        save_btn.bind('<Return>', lambda e, b=save_btn: self.handle_enter_key(e, b))

    # Export Dialog
    def create_export_dialog(self, parent):
        """Create export data dialog."""
        form_frame = tk.Frame(parent, bg='white', padx=25, pady=25)
        form_frame.pack(fill=tk.BOTH, expand=True)

        # Data type
        tk.Label(form_frame, text="Data to Export:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=0, column=0, padx=5, pady=12, sticky='e')
        self.export_data_type = tk.StringVar(value='bills')
        type_combo = ttk.Combobox(form_frame, textvariable=self.export_data_type,
                                  values=['bills', 'rooms', 'bookings', 'sales', 'food_orders'],
                                  width=20, state='readonly', font=('Segoe UI', 12))
        type_combo.grid(row=0, column=1, padx=5, pady=12, sticky='w')

        # Format
        tk.Label(form_frame, text="Format:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=1, column=0, padx=5, pady=12, sticky='e')
        self.export_format = tk.StringVar(value='csv')
        format_frame = tk.Frame(form_frame, bg='white')
        format_frame.grid(row=1, column=1, padx=5, pady=12, sticky='w')
        tk.Radiobutton(format_frame, text="CSV", variable=self.export_format, value='csv',
                       bg='white', font=('Segoe UI', 12)).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(format_frame, text="JSON", variable=self.export_format, value='json',
                       bg='white', font=('Segoe UI', 12)).pack(side=tk.LEFT, padx=5)

        # Date range
        tk.Label(form_frame, text="From Date:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=2, column=0, padx=5, pady=12, sticky='e')
        self.export_from_date = tk.Entry(form_frame, font=('Segoe UI', 12), width=15)
        self.export_from_date.grid(row=2, column=1, padx=5, pady=12, sticky='w')

        tk.Label(form_frame, text="To Date:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=3, column=0, padx=5, pady=12, sticky='e')
        self.export_to_date = tk.Entry(form_frame, font=('Segoe UI', 12), width=15)
        self.export_to_date.grid(row=3, column=1, padx=5, pady=12, sticky='w')

        def export_data():
            try:
                data_type = self.export_data_type.get()
                format_type = self.export_format.get()
                from_date = self.export_from_date.get() or None
                to_date = self.export_to_date.get() or None

                filename = f"{data_type}_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{format_type}"

                conn = self.db.get_connection()
                cursor = conn.cursor()

                if data_type == 'bills':
                    if from_date and to_date:
                        cursor.execute('''
                            SELECT b.*, r.room_number, bk.guest_name
                            FROM bills b
                            JOIN rooms r ON b.room_id = r.id
                            JOIN bookings bk ON b.booking_id = bk.id
                            WHERE DATE(b.bill_date) BETWEEN ? AND ?
                        ''', (from_date, to_date))
                    else:
                        cursor.execute('''
                            SELECT b.*, r.room_number, bk.guest_name
                            FROM bills b
                            JOIN rooms r ON b.room_id = r.id
                            JOIN bookings bk ON b.booking_id = bk.id
                        ''')
                elif data_type == 'rooms':
                    cursor.execute('SELECT * FROM rooms')
                elif data_type == 'bookings':
                    cursor.execute('''
                        SELECT b.*, r.room_number
                        FROM bookings b
                        JOIN rooms r ON b.room_id = r.id
                    ''')
                elif data_type == 'food_orders':
                    cursor.execute('''
                        SELECT fo.*, r.room_number, bk.guest_name
                        FROM food_orders fo
                        JOIN rooms r ON fo.room_id = r.id
                        JOIN bookings bk ON fo.booking_id = bk.id
                    ''')
                elif data_type == 'sales':
                    cursor.execute('''
                        SELECT
                            DATE(b.bill_date) as date,
                            COUNT(*) as total_bookings,
                            SUM(b.total_amount) as total_amount,
                            SUM(CASE WHEN b.payment_status = 'paid' THEN b.total_amount ELSE 0 END) as collected,
                            SUM(CASE WHEN b.payment_status = 'pending' THEN b.total_amount ELSE 0 END) as pending
                        FROM bills b
                        GROUP BY DATE(b.bill_date)
                        ORDER BY date DESC
                    ''')

                rows = cursor.fetchall()
                data = [dict(row) for row in rows]
                self.db.return_connection(conn)

                if format_type == 'csv':
                    with open(filename, 'w', newline='', encoding='utf-8') as f:
                        if data:
                            writer = csv.DictWriter(f, fieldnames=data[0].keys())
                            writer.writeheader()
                            writer.writerows(data)
                else:
                    with open(filename, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, default=str)

                self.show_info(f"✅ Data exported to {filename}")

            except Exception as e:
                self.show_error(f"Error exporting data: {str(e)}")

        export_btn = tk.Button(form_frame, text="💾 EXPORT",
                               font=('Segoe UI', 14, 'bold'),
                               bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                               command=export_data, padx=40, pady=12)
        export_btn.grid(row=4, column=0, columnspan=2, pady=15)
        export_btn.bind('<Return>', lambda e, b=export_btn: self.handle_enter_key(e, b))

    # Header
    def create_header(self):
        """Create header for main menu - slightly smaller."""
        header_frame = tk.Frame(self.main_frame, bg='#6a4334', height=70)  # Reduced from 90 to 70
        header_frame.pack(fill=tk.X, padx=0, pady=0)
        header_frame.pack_propagate(False)

        # Left side: Hotel logo and name
        logo_frame = tk.Frame(header_frame, bg='#6a4334')
        logo_frame.pack(side=tk.LEFT, padx=20, pady=12)  # Reduced pady from 15 to 12

        hotel_label = tk.Label(logo_frame, text="🏨 THE EVAANI HOTEL",
                               font=('Georgia', 18, 'bold'), bg='#6a4334', fg='white')  # Reduced from 22 to 18
        hotel_label.pack(side=tk.LEFT, padx=(0, 20))

        system_label = tk.Label(logo_frame, text="Billing Management System",
                                font=('Segoe UI', 12), bg='#6a4334', fg='#d5d8dc')  # Reduced from 14 to 12
        system_label.pack(side=tk.LEFT)

        # Right side: User info and logout
        user_frame = tk.Frame(header_frame, bg='#6a4334')
        user_frame.pack(side=tk.RIGHT, padx=20, pady=12)  # Reduced pady from 15 to 12

        welcome_label = tk.Label(user_frame,
                                 text=f"Welcome, {self.auth.current_user['username'].upper()}",
                                 font=('Segoe UI', 12, 'bold'),  # Reduced from 14 to 12
                                 bg='#6a4334', fg='white')
        welcome_label.pack(side=tk.LEFT, padx=(0, 15))  # Reduced padx from 20 to 15

        role_badge = tk.Label(user_frame, text=self.auth.current_user['role'].upper(),
                              font=('Segoe UI', 10, 'bold'), bg='#2e86c1', fg='black',  # Reduced from 12 to 10
                              padx=12, pady=4, relief=tk.FLAT)  # Reduced padding
        role_badge.pack(side=tk.LEFT, padx=(0, 15))  # Reduced padx from 20 to 15

        logout_btn = tk.Button(user_frame, text="LOGOUT", font=('Segoe UI', 11, 'bold'),  # Reduced from 13 to 11
                               bg='#c0392b', fg='black', activebackground='#a93226',
                               activeforeground='white', relief='flat', cursor='hand2',
                               command=self.logout, padx=15, pady=4)  # Reduced padding
        logout_btn.pack(side=tk.LEFT)

    # Utility methods
    def show_error(self, message):
        messagebox.showerror("Error", message)

    def show_info(self, message):
        messagebox.showinfo("Information", message)

    def show_warning(self, message):
        messagebox.showwarning("Warning", message)

    def ask_confirmation(self, message):
        return messagebox.askyesno("Confirmation", message)

    def logout(self):
        self.auth.logout()
        if self.main_frame:
            self.main_frame.destroy()
        self.create_login_frame()

    def quit_app(self):
        if messagebox.askyesno("Quit", "Are you sure you want to quit?"):
            self.root.quit()

    def refresh_current_dialog(self):
        """Refresh the current dialog's data."""
        if self.active_dialog and self.active_dialog.winfo_exists():
            title = self.active_dialog.title()
            if "Room Status" in title:
                self.load_room_status_dialog()
            elif "Room Management" in title:
                self.load_rooms_data()
            elif "Active Bookings" in title:
                self.load_active_bookings()
            elif "Food Orders" in title and hasattr(self, 'current_food_booking'):
                self.load_food_orders(self.current_food_booking['id'])
            elif "View Bills" in title:
                self.load_all_bills()
            elif "Sales Summary" in title:
                self.load_sales_summary()
            elif "User Management" in title:
                self.load_users_data()
            elif "Settlement" in title:
                self.load_pending_settlements()

    def show_help(self):
        help_text = """
Keyboard Shortcuts:
F1-F13 - Quick access to functions
Enter - Submit form / Click focused button
ESC - Close current dialog
F5 - Refresh current dialog
Ctrl+L - Logout
Ctrl+Q - Quit application
Tab/Shift+Tab - Navigate between fields

Room Status:
🟢 Available - Room is vacant
🔴 Occupied - Guest currently checked in
🟡 Reserved - Room booked for future
🔵 Housekeeping - Room being cleaned
⚪ Under Process - Room under maintenance

Billing Policy (12:00 PM Cycle):
- Check-out after 12:00 PM charges for additional day
- Daily rate applies for each 24-hour period
- Sales are recorded on checkout date

Settlement:
- Partial payments allowed
- Discount can be applied during settlement
- Balance due tracked separately
        """
        messagebox.showinfo("Help", help_text)

    def check_today_reservations_reminder(self):
        """Check for today's reservations."""
        try:
            if self.auth.is_authenticated():
                reservations = self.hotel.check_today_reservations()
                if reservations:
                    message = "📅 TODAY'S RESERVATIONS\n\n"
                    total_advance = 0
                    for res in reservations:
                        message += f"Room {res['room_number']}: {res['guest_name']} - Advance: ₹{res.get('advance_payment', 0.0):.2f}\n"
                        total_advance += res.get('advance_payment', 0.0)
                    message += f"\nTotal Advance Collected: ₹{total_advance:.2f}"
                    messagebox.showinfo("Today's Reservations", message)
        except Exception as e:
            print(f"Error checking reservations: {e}")
        self.root.after(3600000, self.check_today_reservations_reminder)

    def add_export_buttons_to_sales_dialog(self, parent):
        """Add export buttons to the sales dialog."""
        export_frame = tk.Frame(parent, bg='white')
        export_frame.pack(fill=tk.X, pady=(10, 0))

        tk.Label(export_frame, text="Export Data:", font=('Segoe UI', 12, 'bold'),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=(0, 10))

        export_full_btn = tk.Button(export_frame, text="📊 FULL SUMMARY",
                                    font=('Segoe UI', 11, 'bold'),
                                    bg='#3498db', fg='black', relief='flat',
                                    command=self.export_full_sales_summary,
                                    padx=15, pady=5)
        export_full_btn.pack(side=tk.LEFT, padx=2)
        export_full_btn.bind('<Return>', lambda e, b=export_full_btn: self.handle_enter_key(e, b))

        export_daily_btn = tk.Button(export_frame, text="📅 DAILY SALES",
                                     font=('Segoe UI', 11, 'bold'),
                                     bg='#27ae60', fg='black', relief='flat',
                                     command=self.export_daily_sales,
                                     padx=15, pady=5)
        export_daily_btn.pack(side=tk.LEFT, padx=2)
        export_daily_btn.bind('<Return>', lambda e, b=export_daily_btn: self.handle_enter_key(e, b))

        export_bills_btn = tk.Button(export_frame, text="🧾 ALL BILLS",
                                     font=('Segoe UI', 11, 'bold'),
                                     bg='#f39c12', fg='black', relief='flat',
                                     command=self.export_all_bills,
                                     padx=15, pady=5)
        export_bills_btn.pack(side=tk.LEFT, padx=2)
        export_bills_btn.bind('<Return>', lambda e, b=export_bills_btn: self.handle_enter_key(e, b))

        export_settlements_btn = tk.Button(export_frame, text="🤝 SETTLEMENTS",
                                           font=('Segoe UI', 11, 'bold'),
                                           bg='#8e44ad', fg='black', relief='flat',
                                           command=self.export_settlements,
                                           padx=15, pady=5)
        export_settlements_btn.pack(side=tk.LEFT, padx=2)
        export_settlements_btn.bind('<Return>', lambda e, b=export_settlements_btn: self.handle_enter_key(e, b))

    def export_full_sales_summary(self):
        """Export full sales summary to CSV with total received."""
        try:
            from_date = self.from_date.get() if self.from_date.get() else None
            to_date = self.to_date.get() if self.to_date.get() else None

            # Get sales summary data with proper calculation
            summary = self.calculate_sales_summary_with_received(from_date, to_date)

            if not summary:
                self.show_warning("No sales data to export for the selected period.")
                return

            # Generate filename
            if from_date and to_date:
                filename = f"sales_summary_{from_date}_to_{to_date}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            else:
                filename = f"sales_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

            # Write to CSV
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['Date', 'Bookings', 'Gross Amount (₹)',
                              'Advance Received (₹)', 'Settlement Received (₹)',
                              '💰 TOTAL RECEIVED (₹)', 'Discount Given (₹)']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                total_bookings = 0
                total_gross = 0.0
                total_advance = 0.0
                total_settlement = 0.0
                total_received = 0.0
                total_discount = 0.0

                for record in summary:
                    writer.writerow({
                        'Date': record['date'],
                        'Bookings': record['bookings'],
                        'Gross Amount (₹)': f"{record['gross_amount']:.2f}",
                        'Advance Received (₹)': f"{record['advance_received']:.2f}",
                        'Settlement Received (₹)': f"{record['settlement_received']:.2f}",
                        '💰 TOTAL RECEIVED (₹)': f"{record['total_received']:.2f}",
                        'Discount Given (₹)': f"{record['discount']:.2f}"
                    })

                    total_bookings += record['bookings']
                    total_gross += record['gross_amount']
                    total_advance += record['advance_received']
                    total_settlement += record['settlement_received']
                    total_received += record['total_received']
                    total_discount += record['discount']

                # Add summary row
                writer.writerow({})
                writer.writerow({
                    'Date': 'TOTAL',
                    'Bookings': total_bookings,
                    'Gross Amount (₹)': f"{total_gross:.2f}",
                    'Advance Received (₹)': f"{total_advance:.2f}",
                    'Settlement Received (₹)': f"{total_settlement:.2f}",
                    '💰 TOTAL RECEIVED (₹)': f"{total_received:.2f}",
                    'Discount Given (₹)': f"{total_discount:.2f}"
                })

            self.show_info(f"✅ Full sales summary exported to:\n{filename}")

        except Exception as e:
            self.show_error(f"Error exporting sales summary: {str(e)}")

    def calculate_sales_summary_with_received(self, from_date, to_date):
        """Helper method to calculate sales summary with total received."""
        try:
            if from_date and to_date:
                current_date = datetime.strptime(from_date, '%Y-%m-%d')
                end_date = datetime.strptime(to_date, '%Y-%m-%d')
            else:
                end_date = datetime.now()
                current_date = end_date - timedelta(days=30)

            daily_summaries = []

            while current_date <= end_date:
                date_str = current_date.strftime('%Y-%m-%d')
                detailed = self.hotel.get_detailed_sales(date_str)

                gross_amount = sum(b['total_amount'] for b in detailed['bills'])
                advance_received = sum(b.get('advance_paid', 0.0) for b in detailed['bills'])
                settlement_received = sum(s['paid_amount'] for s in detailed['settlements'])
                total_received = advance_received + settlement_received
                discounts = sum(s['discount_amount'] for s in detailed['settlements'])

                if gross_amount > 0 or len(detailed['bills']) > 0:
                    daily_summaries.append({
                        'date': date_str,
                        'bookings': len(detailed['bills']),
                        'gross_amount': gross_amount,
                        'advance_received': advance_received,
                        'settlement_received': settlement_received,
                        'total_received': total_received,
                        'discount': discounts
                    })

                current_date += timedelta(days=1)

            return daily_summaries

        except Exception as e:
            print(f"Error calculating sales summary: {e}")
            return []

    def export_daily_sales(self):
        """Export daily sales for selected date range."""
        try:
            from_date = self.from_date.get() if self.from_date.get() else None
            to_date = self.to_date.get() if self.to_date.get() else None

            if not from_date or not to_date:
                # Default to last 30 days if no dates specified
                to_date = datetime.now().strftime('%Y-%m-%d')
                from_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
                self.from_date.delete(0, tk.END)
                self.from_date.insert(0, from_date)
                self.to_date.delete(0, tk.END)
                self.to_date.insert(0, to_date)

            # Get detailed sales for each day in range
            current_date = datetime.strptime(from_date, '%Y-%m-%d')
            end_date = datetime.strptime(to_date, '%Y-%m-%d')

            all_daily_sales = []

            while current_date <= end_date:
                date_str = current_date.strftime('%Y-%m-%d')
                detailed = self.hotel.get_detailed_sales(date_str)

                for bill in detailed['bills']:
                    all_daily_sales.append({
                        'date': date_str,
                        'type': 'BILL',
                        'bill_number': bill['bill_number'],
                        'room_number': bill['room_number'],
                        'guest_name': bill['guest_name'],
                        'amount': bill['total_amount'],
                        'status': bill['payment_status']
                    })

                for settlement in detailed['settlements']:
                    all_daily_sales.append({
                        'date': date_str,
                        'type': 'SETTLEMENT',
                        'bill_number': settlement['bill_number'],
                        'room_number': settlement['room_number'],
                        'guest_name': settlement['guest_name'],
                        'amount': settlement['paid_amount'],
                        'status': 'settled'
                    })

                current_date += timedelta(days=1)

            if not all_daily_sales:
                self.show_warning("No daily sales data to export for the selected period.")
                return

            # Generate filename
            filename = f"daily_sales_{from_date}_to_{to_date}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

            # Write to CSV
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['Date', 'Type', 'Bill Number', 'Room No', 'Guest Name', 'Amount (₹)', 'Status']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                for sale in all_daily_sales:
                    writer.writerow({
                        'Date': sale['date'],
                        'Type': sale['type'],
                        'Bill Number': sale['bill_number'],
                        'Room No': sale['room_number'],
                        'Guest Name': sale['guest_name'],
                        'Amount (₹)': f"{sale['amount']:.2f}",
                        'Status': sale['status'].upper()
                    })

                # Add summary
                total_bills = sum(s['amount'] for s in all_daily_sales if s['type'] == 'BILL')
                total_settlements = sum(s['amount'] for s in all_daily_sales if s['type'] == 'SETTLEMENT')

                writer.writerow({})
                writer.writerow({
                    'Date': 'SUMMARY',
                    'Type': '',
                    'Bill Number': '',
                    'Room No': '',
                    'Guest Name': 'Total Bills:',
                    'Amount (₹)': f"{total_bills:.2f}",
                    'Status': ''
                })
                writer.writerow({
                    'Date': '',
                    'Type': '',
                    'Bill Number': '',
                    'Room No': '',
                    'Guest Name': 'Total Settlements:',
                    'Amount (₹)': f"{total_settlements:.2f}",
                    'Status': ''
                })
                writer.writerow({
                    'Date': '',
                    'Type': '',
                    'Bill Number': '',
                    'Room No': '',
                    'Guest Name': 'Net Revenue:',
                    'Amount (₹)': f"{total_bills:.2f}",
                    'Status': ''
                })

            self.show_info(f"✅ Daily sales exported to:\n{filename}")

        except Exception as e:
            self.show_error(f"Error exporting daily sales: {str(e)}")

    def export_all_bills(self):
        """Export all bills for selected date range."""
        try:
            from_date = self.from_date.get() if self.from_date.get() else None
            to_date = self.to_date.get() if self.to_date.get() else None

            # Get bills data
            bills = self.hotel.get_all_bills(from_date, to_date)

            if not bills:
                self.show_warning("No bills to export for the selected period.")
                return

            # Generate filename
            if from_date and to_date:
                filename = f"all_bills_{from_date}_to_{to_date}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            else:
                filename = f"all_bills_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

            # Write to CSV
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['Bill Number', 'Date', 'Room No', 'Guest Name',
                              'Check-in', 'Check-out', 'Days', 'Room Charges',
                              'Food Total', 'CGST', 'SGST', 'Total Amount (₹)',
                              'Advance Paid', 'Balance Due', 'Payment Method', 'Status']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                for bill in bills:
                    bill_date = datetime.fromisoformat(bill['bill_date']).strftime('%Y-%m-%d %H:%M')
                    check_in = datetime.fromisoformat(bill['check_in_time']).strftime('%Y-%m-%d %H:%M')
                    check_out = datetime.fromisoformat(bill['check_out_time']).strftime('%Y-%m-%d %H:%M')

                    writer.writerow({
                        'Bill Number': bill['bill_number'],
                        'Date': bill_date,
                        'Room No': bill['room_number'],
                        'Guest Name': bill['guest_name'],
                        'Check-in': check_in,
                        'Check-out': check_out,
                        'Days': int(bill['total_hours'] / 24),
                        'Room Charges': f"₹{bill['room_charges']:.2f}",
                        'Food Total': f"₹{bill.get('food_total', 0.0):.2f}",
                        'CGST': f"₹{bill['cgst_amount']:.2f}",
                        'SGST': f"₹{bill['sgst_amount']:.2f}",
                        'Total Amount (₹)': f"₹{bill['total_amount']:.2f}",
                        'Advance Paid': f"₹{bill.get('advance_paid', 0.0):.2f}",
                        'Balance Due': f"₹{bill.get('balance_due', 0.0):.2f}",
                        'Payment Method': bill['payment_method'].upper(),
                        'Status': bill['payment_status'].upper()
                    })

                # Add summary
                total_amount = sum(b['total_amount'] for b in bills)
                total_advance = sum(b.get('advance_paid', 0.0) for b in bills)
                total_balance = sum(b.get('balance_due', 0.0) for b in bills)

                writer.writerow({})
                writer.writerow({
                    'Bill Number': 'SUMMARY',
                    'Total Amount (₹)': f"₹{total_amount:.2f}",
                    'Advance Paid': f"₹{total_advance:.2f}",
                    'Balance Due': f"₹{total_balance:.2f}"
                })

            self.show_info(f"✅ All bills exported to:\n{filename}")

        except Exception as e:
            self.show_error(f"Error exporting bills: {str(e)}")

    def export_settlements(self):
        """Export all settlements for selected date range."""
        try:
            from_date = self.from_date.get() if self.from_date.get() else None
            to_date = self.to_date.get() if self.to_date.get() else None

            conn = self.db.get_connection()
            cursor = conn.cursor()

            if from_date and to_date:
                cursor.execute('''
                    SELECT s.*, b.bill_number, r.room_number, bk.guest_name,
                           u.username as settled_by_name
                    FROM settlements s
                    JOIN bills b ON s.bill_id = b.id
                    JOIN rooms r ON b.room_id = r.id
                    JOIN bookings bk ON b.booking_id = bk.id
                    LEFT JOIN users u ON s.settled_by = u.id
                    WHERE DATE(s.settlement_date) BETWEEN ? AND ?
                    ORDER BY s.settlement_date DESC
                ''', (from_date, to_date))
            else:
                cursor.execute('''
                    SELECT s.*, b.bill_number, r.room_number, bk.guest_name,
                           u.username as settled_by_name
                    FROM settlements s
                    JOIN bills b ON s.bill_id = b.id
                    JOIN rooms r ON b.room_id = r.id
                    JOIN bookings bk ON b.booking_id = bk.id
                    LEFT JOIN users u ON s.settled_by = u.id
                    ORDER BY s.settlement_date DESC
                    LIMIT 1000
                ''')

            settlements = cursor.fetchall()
            self.db.return_connection(conn)

            if not settlements:
                self.show_warning("No settlements to export for the selected period.")
                return

            # Generate filename
            if from_date and to_date:
                filename = f"settlements_{from_date}_to_{to_date}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            else:
                filename = f"settlements_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

            # Write to CSV
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['Settlement Date', 'Bill Number', 'Room No', 'Guest Name',
                              'Total Amount (₹)', 'Paid Amount (₹)', 'Discount (₹)',
                              'Balance After (₹)', 'Payment Method', 'Status', 'Settled By']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                for settlement in settlements:
                    s = dict(settlement)
                    settlement_date = datetime.fromisoformat(s['settlement_date']).strftime('%Y-%m-%d %H:%M')

                    writer.writerow({
                        'Settlement Date': settlement_date,
                        'Bill Number': s['bill_number'],
                        'Room No': s['room_number'],
                        'Guest Name': s['guest_name'],
                        'Total Amount (₹)': f"₹{s['total_amount']:.2f}",
                        'Paid Amount (₹)': f"₹{s['paid_amount']:.2f}",
                        'Discount (₹)': f"₹{s['discount_amount']:.2f}",
                        'Balance After (₹)': f"₹{s['balance_amount']:.2f}",
                        'Payment Method': s['payment_method'].upper(),
                        'Status': s['payment_status'].upper(),
                        'Settled By': s.get('settled_by_name', '')
                    })

                # Add summary
                total_paid = sum(dict(s)['paid_amount'] for s in settlements)
                total_discount = sum(dict(s)['discount_amount'] for s in settlements)

                writer.writerow({})
                writer.writerow({
                    'Settlement Date': 'SUMMARY',
                    'Paid Amount (₹)': f"₹{total_paid:.2f}",
                    'Discount (₹)': f"₹{total_discount:.2f}"
                })

            self.show_info(f"✅ Settlements exported to:\n{filename}")

        except Exception as e:
            self.show_error(f"Error exporting settlements: {str(e)}")

    # Add method to export from detailed sales view
    def add_export_to_detailed_view(self, dialog, date_str, detailed):
        """Add export button to detailed sales view."""
        export_frame = tk.Frame(dialog, bg='white')
        export_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(export_frame, text="Export:", font=('Segoe UI', 11, 'bold'),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=(0, 10))

        export_bills_btn = tk.Button(export_frame, text="📋 EXPORT BILLS",
                                     font=('Segoe UI', 10, 'bold'),
                                     bg='#3498db', fg='black', relief='flat',
                                     command=lambda: self.export_detailed_bills(date_str, detailed['bills']),
                                     padx=10, pady=3)
        export_bills_btn.pack(side=tk.LEFT, padx=2)

        export_settlements_btn = tk.Button(export_frame, text="🤝 EXPORT SETTLEMENTS",
                                           font=('Segoe UI', 10, 'bold'),
                                           bg='#8e44ad', fg='black', relief='flat',
                                           command=lambda: self.export_detailed_settlements(date_str,
                                                                                            detailed['settlements']),
                                           padx=10, pady=3)
        export_settlements_btn.pack(side=tk.LEFT, padx=2)

        export_all_btn = tk.Button(export_frame, text="📊 EXPORT ALL",
                                   font=('Segoe UI', 10, 'bold'),
                                   bg='#27ae60', fg='black', relief='flat',
                                   command=lambda: self.export_detailed_all(date_str, detailed),
                                   padx=10, pady=3)
        export_all_btn.pack(side=tk.LEFT, padx=2)

    def export_detailed_bills(self, date_str, bills):
        """Export bills from detailed view."""
        try:
            filename = f"bills_{date_str}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['Bill Number', 'Room No', 'Guest Name', 'Check-in',
                              'Check-out', 'Total Amount (₹)', 'Status']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                for bill in bills:
                    check_in = datetime.fromisoformat(bill['check_in_time']).strftime('%H:%M')
                    check_out = datetime.fromisoformat(bill['check_out_time']).strftime('%H:%M')

                    writer.writerow({
                        'Bill Number': bill['bill_number'],
                        'Room No': bill['room_number'],
                        'Guest Name': bill['guest_name'],
                        'Check-in': check_in,
                        'Check-out': check_out,
                        'Total Amount (₹)': f"₹{bill['total_amount']:.2f}",
                        'Status': bill['payment_status'].upper()
                    })

                total = sum(b['total_amount'] for b in bills)
                writer.writerow({})
                writer.writerow({'Bill Number': 'TOTAL', 'Total Amount (₹)': f"₹{total:.2f}"})

            self.show_info(f"✅ Bills exported to: {filename}")

        except Exception as e:
            self.show_error(f"Error exporting bills: {str(e)}")

    def export_detailed_settlements(self, date_str, settlements):
        """Export settlements from detailed view."""
        try:
            filename = f"settlements_{date_str}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['Bill Number', 'Room No', 'Guest Name', 'Total Amount (₹)',
                              'Paid (₹)', 'Discount (₹)', 'Balance (₹)', 'Method']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                for settlement in settlements:
                    writer.writerow({
                        'Bill Number': settlement['bill_number'],
                        'Room No': settlement['room_number'],
                        'Guest Name': settlement['guest_name'],
                        'Total Amount (₹)': f"₹{settlement['total_amount']:.2f}",
                        'Paid (₹)': f"₹{settlement['paid_amount']:.2f}",
                        'Discount (₹)': f"₹{settlement['discount_amount']:.2f}",
                        'Balance (₹)': f"₹{settlement['balance_amount']:.2f}",
                        'Method': settlement['payment_method'].upper()
                    })

                total_paid = sum(s['paid_amount'] for s in settlements)
                total_discount = sum(s['discount_amount'] for s in settlements)

                writer.writerow({})
                writer.writerow({'Bill Number': 'TOTAL PAID', 'Paid (₹)': f"₹{total_paid:.2f}"})
                writer.writerow({'Bill Number': 'TOTAL DISCOUNT', 'Discount (₹)': f"₹{total_discount:.2f}"})

            self.show_info(f"✅ Settlements exported to: {filename}")

        except Exception as e:
            self.show_error(f"Error exporting settlements: {str(e)}")

    def export_detailed_all(self, date_str, detailed):
        """Export all data from detailed view."""
        try:
            filename = f"detailed_sales_{date_str}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)

                # Bills section
                writer.writerow(['BILLS'])
                writer.writerow(['Bill Number', 'Room No', 'Guest Name', 'Check-in',
                                 'Check-out', 'Total Amount (₹)', 'Status'])

                for bill in detailed['bills']:
                    check_in = datetime.fromisoformat(bill['check_in_time']).strftime('%H:%M')
                    check_out = datetime.fromisoformat(bill['check_out_time']).strftime('%H:%M')
                    writer.writerow([
                        bill['bill_number'],
                        bill['room_number'],
                        bill['guest_name'],
                        check_in,
                        check_out,
                        f"{bill['total_amount']:.2f}",
                        bill['payment_status'].upper()
                    ])

                writer.writerow([])

                # Settlements section
                writer.writerow(['SETTLEMENTS'])
                writer.writerow(['Bill Number', 'Room No', 'Guest Name', 'Total Amount (₹)',
                                 'Paid (₹)', 'Discount (₹)', 'Balance (₹)', 'Method'])

                for settlement in detailed['settlements']:
                    writer.writerow([
                        settlement['bill_number'],
                        settlement['room_number'],
                        settlement['guest_name'],
                        f"{settlement['total_amount']:.2f}",
                        f"{settlement['paid_amount']:.2f}",
                        f"{settlement['discount_amount']:.2f}",
                        f"{settlement['balance_amount']:.2f}",
                        settlement['payment_method'].upper()
                    ])

                writer.writerow([])

                # Summary
                total_bills = sum(b['total_amount'] for b in detailed['bills'])
                total_settlements = sum(s['paid_amount'] for s in detailed['settlements'])

                writer.writerow(['SUMMARY'])
                writer.writerow(['Total Bills:', f"₹{total_bills:.2f}"])
                writer.writerow(['Total Settlements:', f"₹{total_settlements:.2f}"])
                writer.writerow(['Net Revenue:', f"₹{total_bills:.2f}"])

            self.show_info(f"✅ Detailed data exported to: {filename}")

        except Exception as e:
            self.show_error(f"Error exporting detailed data: {str(e)}")

    # Update the show_detailed_sales method to include export buttons
    def show_detailed_sales(self, event):
        """Show detailed sales for selected date including settlements."""
        selection = self.sales_tree.selection()
        if not selection:
            return

        date_str = self.sales_tree.item(selection[0])['values'][0]

        try:
            detailed = self.hotel.get_detailed_sales(date_str)

            dialog = tk.Toplevel(self.active_dialog if self.active_dialog else self.root)
            dialog.title(f"Detailed Sales - {date_str}")
            dialog.geometry("1000x750")
            dialog.transient(self.active_dialog if self.active_dialog else self.root)
            dialog.grab_set()
            dialog.configure(bg='white')
            self.center_dialog(dialog, 1000, 750)

            main_frame = tk.Frame(dialog, bg='white', padx=20, pady=20)
            main_frame.pack(fill=tk.BOTH, expand=True)

            tk.Label(main_frame, text=f"Sales Details for {date_str}",
                     font=('Segoe UI', 16, 'bold'), bg='white', fg='#6a4334').pack(pady=(0, 15))

            # Add export buttons
            self.add_export_to_detailed_view(main_frame, date_str, detailed)

            # Create notebook for tabs
            notebook = ttk.Notebook(main_frame)
            notebook.pack(fill=tk.BOTH, expand=True)

            # Bills Tab
            bills_frame = ttk.Frame(notebook)
            notebook.add(bills_frame, text=f"Bills ({len(detailed['bills'])})")

            bills_tree_frame = tk.Frame(bills_frame, bg='white')
            bills_tree_frame.pack(fill=tk.BOTH, expand=True)

            bills_container = tk.Frame(bills_tree_frame, bg='white')
            bills_container.pack(fill=tk.BOTH, expand=True)

            bills_scroll = ttk.Scrollbar(bills_container)
            bills_scroll.pack(side=tk.RIGHT, fill=tk.Y)

            bills_columns = ('Bill No', 'Room No', 'Guest Name', 'Check-in', 'Check-out', 'Total', 'Status')
            bills_tree = ttk.Treeview(bills_container, columns=bills_columns,
                                      yscrollcommand=bills_scroll.set,
                                      height=12)

            bills_scroll.config(command=bills_tree.yview)

            for col in bills_columns:
                bills_tree.heading(col, text=col, anchor=tk.W)
                bills_tree.column(col, width=120, minwidth=100)

            bills_tree.column('Bill No', width=180)
            bills_tree.column('Guest Name', width=150)
            bills_tree.column('Check-in', width=120)
            bills_tree.column('Check-out', width=120)

            bills_tree.pack(fill=tk.BOTH, expand=True)

            for sale in detailed['bills']:
                check_in = datetime.fromisoformat(sale['check_in_time']).strftime('%H:%M')
                check_out = datetime.fromisoformat(sale['check_out_time']).strftime('%H:%M')
                values = (
                    sale['bill_number'],
                    sale['room_number'],
                    sale['guest_name'],
                    check_in,
                    check_out,
                    f"₹{sale['total_amount']:.2f}",
                    sale['payment_status'].upper()
                )
                bills_tree.insert('', tk.END, values=values)

            # Settlements Tab
            settlements_frame = ttk.Frame(notebook)
            notebook.add(settlements_frame, text=f"Settlements ({len(detailed['settlements'])})")

            settlements_tree_frame = tk.Frame(settlements_frame, bg='white')
            settlements_tree_frame.pack(fill=tk.BOTH, expand=True)

            settlements_container = tk.Frame(settlements_tree_frame, bg='white')
            settlements_container.pack(fill=tk.BOTH, expand=True)

            settlements_scroll = ttk.Scrollbar(settlements_container)
            settlements_scroll.pack(side=tk.RIGHT, fill=tk.Y)

            settlements_columns = ('Bill No', 'Room No', 'Guest Name', 'Total Amount', 'Paid', 'Discount', 'Balance',
                                   'Method')
            settlements_tree = ttk.Treeview(settlements_container, columns=settlements_columns,
                                            yscrollcommand=settlements_scroll.set,
                                            height=12)

            settlements_scroll.config(command=settlements_tree.yview)

            for col in settlements_columns:
                settlements_tree.heading(col, text=col, anchor=tk.W)
                settlements_tree.column(col, width=110, minwidth=90)

            settlements_tree.column('Bill No', width=180)
            settlements_tree.column('Guest Name', width=150)
            settlements_tree.column('Total Amount', width=110)
            settlements_tree.column('Paid', width=90)
            settlements_tree.column('Discount', width=90)
            settlements_tree.column('Balance', width=90)
            settlements_tree.column('Method', width=90)

            settlements_tree.pack(fill=tk.BOTH, expand=True)

            for settlement in detailed['settlements']:
                values = (
                    settlement['bill_number'],
                    settlement['room_number'],
                    settlement['guest_name'],
                    f"₹{settlement['total_amount']:.2f}",
                    f"₹{settlement['paid_amount']:.2f}",
                    f"₹{settlement['discount_amount']:.2f}",
                    f"₹{settlement['balance_amount']:.2f}",
                    settlement['payment_method'].upper()
                )
                settlements_tree.insert('', tk.END, values=values)

            # Summary
            summary_frame = tk.Frame(main_frame, bg='#f0f0f0', bd=1, relief=tk.SOLID)
            summary_frame.pack(fill=tk.X, pady=10)

            total_bills = sum(sale['total_amount'] for sale in detailed['bills'])
            total_settled = sum(s['paid_amount'] for s in detailed['settlements'])

            summary_text = f"Total Bills: ₹{total_bills:.2f} | Total Settlements: ₹{total_settled:.2f}"
            tk.Label(summary_frame, text=summary_text, font=('Segoe UI', 12, 'bold'),
                     bg='#f0f0f0', fg='#333333', padx=10, pady=5).pack()

            close_btn = tk.Button(main_frame, text="CLOSE", font=('Segoe UI', 12, 'bold'),
                                  bg='#2e86c1', fg='black', relief='flat',
                                  command=dialog.destroy, padx=30, pady=8)
            close_btn.pack(pady=10)
            close_btn.bind('<Return>', lambda e, b=close_btn: self.handle_enter_key(e, b))

        except Exception as e:
            self.show_error(f"Error loading details: {str(e)}")

    def quick_checkin_from_history(self):
        """Quick check-in using guest history data."""
        if not hasattr(self, 'guest_bookings_tree') or not self.guest_bookings_tree.get_children():
            self.show_warning("No guest history loaded")
            return

        # Get the latest booking data
        bookings = self.guest_bookings_tree.get_children()
        if not bookings:
            return

        # Get guest details from the details panel
        name = self.guest_name_label.cget("text").replace("Name: ", "")
        phone = self.guest_phone_label.cget("text").replace("Phone: ", "")
        email = self.guest_email_label.cget("text").replace("Email: ", "")
        id_card = self.guest_id_card_label.cget("text").replace("ID Card: ", "")
        address = self.guest_address_label.cget("text").replace("Address: ", "")
        company = self.guest_company_label.cget("text").replace("Company: ", "")
        company_address = self.guest_company_address_label.cget("text").replace("Company Address: ", "")
        gstin = self.guest_party_gstin_label.cget("text").replace("Party GSTIN: ", "")

        if name == "N/A":
            self.show_error("No valid guest data to check-in")
            return

        # Ask for confirmation
        if not self.ask_confirmation(f"Quick check-in for {name}?"):
            return

        # Open check-in dialog with pre-filled data
        self.open_checkin_with_guest_data({
            'guest_name': name,
            'guest_phone': phone,
            'guest_email': email,
            'guest_id_card': id_card,
            'guest_address': address,
            'company_name': company,
            'company_address': company_address,
            'party_gstin': gstin
        })

    def open_checkin_with_guest_data(self, guest_data):
        """Open check-in dialog with pre-filled guest data."""
        # Close current dialog
        self.close_active_dialog()

        # Open check-in dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("The Evaani Hotel - Quick Check-in")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg='white')
        self.center_dialog(dialog, 800, 900)

        # Create check-in content with pre-filled data
        self.create_checkin_dialog_with_data(dialog, guest_data)

        # Add close button
        close_btn = tk.Button(dialog, text="✕ CLOSE (ESC)", font=('Segoe UI', 12, 'bold'),
                              bg='#c0392b', fg='black', activebackground='#a93226',
                              activeforeground='white', relief='flat', cursor='hand2',
                              command=self.close_active_dialog, padx=15, pady=8)
        close_btn.place(relx=1.0, x=-20, y=20, anchor=tk.NE)

    def create_checkin_dialog_with_data(self, parent, guest_data):
        """Create check-in dialog with pre-filled guest data."""
        from datetime import datetime

        # Similar to create_checkin_dialog but with pre-filled data
        # Create a canvas with scrollbar for the form
        canvas = tk.Canvas(parent, bg='white', highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='white')

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Add warning note
        note_frame = tk.Frame(scrollable_frame, bg='#fff3cd', bd=1, relief=tk.SOLID)
        note_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(note_frame,
                 text="⚠️ Quick check-in from guest history - Data pre-filled",
                 font=('Segoe UI', 11, 'italic'), bg='#fff3cd', fg='#856404',
                 padx=10, pady=5).pack()

        # Room selection
        room_frame = tk.LabelFrame(scrollable_frame, text="Select Room",
                                   font=('Segoe UI', 12, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        room_frame.pack(fill=tk.X, pady=5)

        self.checkin_room_list = tk.Listbox(room_frame, height=4,
                                            font=('Segoe UI', 12), bg='white')
        self.checkin_room_list.pack(fill=tk.X)

        refresh_btn = tk.Button(room_frame, text="🔄 Refresh",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat',
                                command=self.load_checkin_rooms, padx=15, pady=5)
        refresh_btn.pack(pady=5)
        refresh_btn.bind('<Return>', lambda e, b=refresh_btn: self.handle_enter_key(e, b))

        self.load_checkin_rooms()

        # Guest info
        guest_frame = tk.LabelFrame(scrollable_frame, text="Guest Information",
                                    font=('Segoe UI', 12, 'bold'),
                                    bg='white', fg='#6a4334', padx=15, pady=10)
        guest_frame.pack(fill=tk.X, pady=5)

        row = 0
        tk.Label(guest_frame, text="Guest Name:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_guest_name = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_guest_name.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_guest_name.insert(0, guest_data.get('guest_name', ''))
        self.checkin_guest_name.focus()
        row += 1

        tk.Label(guest_frame, text="Phone:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_guest_phone = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_guest_phone.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_guest_phone.insert(0, guest_data.get('guest_phone', ''))
        row += 1

        tk.Label(guest_frame, text="Email:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_guest_email = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_guest_email.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_guest_email.insert(0, guest_data.get('guest_email', ''))
        row += 1

        tk.Label(guest_frame, text="ID Card:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_guest_id_card = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_guest_id_card.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_guest_id_card.insert(0, guest_data.get('guest_id_card', ''))
        row += 1

        tk.Label(guest_frame, text="Address:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_guest_address = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_guest_address.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_guest_address.insert(0, guest_data.get('guest_address', ''))
        row += 1

        tk.Label(guest_frame, text="No. of Persons:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_persons = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_persons.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_persons.insert(0, '1')
        row += 1

        # Company Information
        company_frame = tk.LabelFrame(scrollable_frame, text="Company Information (Optional)",
                                      font=('Segoe UI', 12, 'bold'),
                                      bg='white', fg='#6a4334', padx=15, pady=10)
        company_frame.pack(fill=tk.X, pady=5)

        row = 0
        tk.Label(company_frame, text="Company Name:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_company_name = tk.Entry(company_frame, font=('Segoe UI', 12), width=35)
        self.checkin_company_name.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_company_name.insert(0, guest_data.get('company_name', ''))
        row += 1

        tk.Label(company_frame, text="Company Address:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_company_address = tk.Entry(company_frame, font=('Segoe UI', 12), width=35)
        self.checkin_company_address.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_company_address.insert(0, guest_data.get('company_address', ''))
        row += 1

        tk.Label(company_frame, text="Party GSTIN:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_party_gstin = tk.Entry(company_frame, font=('Segoe UI', 12), width=35)
        self.checkin_party_gstin.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_party_gstin.insert(0, guest_data.get('party_gstin', ''))
        row += 1

        # Advance Payment
        advance_frame = tk.LabelFrame(scrollable_frame, text="Advance Payment",
                                      font=('Segoe UI', 12, 'bold'),
                                      bg='white', fg='#6a4334', padx=15, pady=10)
        advance_frame.pack(fill=tk.X, pady=5)

        row = 0
        tk.Label(advance_frame, text="Advance Amount (₹):", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_advance = tk.Entry(advance_frame, font=('Segoe UI', 12), width=20)
        self.checkin_advance.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_advance.insert(0, '0.00')
        row += 1

        tk.Label(advance_frame, text="Payment Method:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_advance_method = ttk.Combobox(advance_frame,
                                                   values=['cash', 'card', 'online', 'upi'],
                                                   width=18, state='readonly', font=('Segoe UI', 12))
        self.checkin_advance_method.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_advance_method.set('cash')
        row += 1

        # Check-in time
        time_frame = tk.LabelFrame(scrollable_frame, text="Check-in Time",
                                   font=('Segoe UI', 12, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        time_frame.pack(fill=tk.X, pady=5)

        tk.Label(time_frame, text="Time:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.checkin_time = tk.Entry(time_frame, font=('Segoe UI', 12), width=20)
        self.checkin_time.pack(side=tk.LEFT, padx=5)
        self.checkin_time.insert(0, datetime.now().strftime('%Y-%m-%d %H:%M'))

        now_btn = tk.Button(time_frame, text="NOW", font=('Segoe UI', 11, 'bold'),
                            bg='#f39c12', fg='black', relief='flat',
                            command=lambda: self.checkin_time.delete(0, tk.END) or
                                            self.checkin_time.insert(0, datetime.now().strftime('%Y-%m-%d %H:%M')),
                            padx=15, pady=5)
        now_btn.pack(side=tk.LEFT, padx=5)
        now_btn.bind('<Return>', lambda e, b=now_btn: self.handle_enter_key(e, b))

        # Check-in button
        checkin_btn = tk.Button(scrollable_frame, text="✅ CHECK-IN GUEST",
                                font=('Segoe UI', 14, 'bold'),
                                bg='#27ae60', fg='black', relief='flat',
                                command=self.checkin_guest, padx=40, pady=12)
        checkin_btn.pack(pady=15)
        checkin_btn.bind('<Return>', lambda e, b=checkin_btn: self.handle_enter_key(e, b))

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def create_guest_history_dialog(self, parent):
        """Create full-screen guest history dialog with all user details and scrolling."""

        # Configure parent for full screen
        parent.configure(bg='white')

        # Create a main canvas with scrollbar for the entire dialog
        main_canvas = tk.Canvas(parent, bg='white', highlightthickness=0)
        main_scrollbar_y = ttk.Scrollbar(parent, orient="vertical", command=main_canvas.yview)
        main_scrollbar_x = ttk.Scrollbar(parent, orient="horizontal", command=main_canvas.xview)

        # Create a frame inside the canvas to hold all content
        scrollable_frame = tk.Frame(main_canvas, bg='white')

        scrollable_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        )

        main_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=main_scrollbar_y.set, xscrollcommand=main_scrollbar_x.set)

        # Pack canvas and scrollbars
        main_canvas.pack(side="left", fill="both", expand=True)
        main_scrollbar_y.pack(side="right", fill="y")
        main_scrollbar_x.pack(side="bottom", fill="x")

        # Bind mouse wheel for scrolling
        def _on_mousewheel(event):
            main_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _on_shift_mousewheel(event):
            main_canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")

        main_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        main_canvas.bind_all("<Shift-MouseWheel>", _on_shift_mousewheel)

        # Create main container with padding inside scrollable frame
        main_container = tk.Frame(scrollable_frame, bg='white', padx=20, pady=20)
        main_container.pack(fill=tk.BOTH, expand=True)

        # Title
        title_frame = tk.Frame(main_container, bg='white')
        title_frame.pack(fill=tk.X, pady=(0, 20))

        tk.Label(title_frame, text="👥 GUEST HISTORY",
                 font=('Segoe UI', 24, 'bold'),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT)

        # Search frame - Compact but visible
        search_frame = tk.LabelFrame(main_container, text="Search Guest",
                                     font=('Segoe UI', 14, 'bold'),
                                     bg='white', fg='#6a4334', padx=20, pady=15)
        search_frame.pack(fill=tk.X, pady=(0, 20))

        # Search by options in a single row
        row_frame = tk.Frame(search_frame, bg='white')
        row_frame.pack(fill=tk.X)

        tk.Label(row_frame, text="Search By:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=(0, 10))

        self.guest_search_by = tk.StringVar(value='name')
        search_options = [
            ("Name", 'name'),
            ("Phone", 'phone'),
            ("ID Card", 'id_card')
        ]

        for text, value in search_options:
            tk.Radiobutton(row_frame, text=text, variable=self.guest_search_by,
                           value=value, bg='white', font=('Segoe UI', 11)).pack(side=tk.LEFT, padx=10)

        tk.Label(row_frame, text="Search Term:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=(20, 10))

        self.guest_search_term = tk.Entry(row_frame, font=('Segoe UI', 12), width=25)
        self.guest_search_term.pack(side=tk.LEFT, padx=5)
        self.guest_search_term.bind('<Return>', lambda e: self.search_guest_history())

        search_btn = tk.Button(row_frame, text="🔍 SEARCH",
                               font=('Segoe UI', 11, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat',
                               command=self.search_guest_history, padx=20, pady=5)
        search_btn.pack(side=tk.LEFT, padx=5)
        search_btn.bind('<Return>', lambda e, b=search_btn: self.handle_enter_key(e, b))

        clear_btn = tk.Button(row_frame, text="🔄 CLEAR",
                              font=('Segoe UI', 11, 'bold'),
                              bg='#95a5a6', fg='black', relief='flat',
                              command=self.clear_guest_search, padx=20, pady=5)
        clear_btn.pack(side=tk.LEFT, padx=5)
        clear_btn.bind('<Return>', lambda e, b=clear_btn: self.handle_enter_key(e, b))

        # Guest Details Panel - Full width with better layout
        self.guest_details_frame = tk.LabelFrame(main_container, text="Guest Details",
                                                 font=('Segoe UI', 16, 'bold'),
                                                 bg='white', fg='#6a4334', padx=20, pady=15)
        self.guest_details_frame.pack(fill=tk.X, pady=(0, 20))
        self.guest_details_frame.pack_forget()  # Hidden initially

        # Create a canvas for guest details with horizontal scroll if needed
        details_canvas = tk.Canvas(self.guest_details_frame, bg='white', highlightthickness=0, height=200)
        details_scrollbar_x = ttk.Scrollbar(self.guest_details_frame, orient="horizontal", command=details_canvas.xview)
        details_scrollable = tk.Frame(details_canvas, bg='white')

        details_scrollable.bind(
            "<Configure>",
            lambda e: details_canvas.configure(scrollregion=details_canvas.bbox("all"))
        )

        details_canvas.create_window((0, 0), window=details_scrollable, anchor="nw")
        details_canvas.configure(xscrollcommand=details_scrollbar_x.set)

        details_canvas.pack(side="top", fill="both", expand=True)
        details_scrollbar_x.pack(side="bottom", fill="x")

        # Create a 3-column layout for guest details inside scrollable frame
        details_grid = tk.Frame(details_scrollable, bg='white')
        details_grid.pack(fill=tk.X, expand=True)

        # Column 1: Personal Information
        personal_frame = tk.LabelFrame(details_grid, text="👤 Personal Information",
                                       font=('Segoe UI', 13, 'bold'),
                                       bg='white', fg='#2e86c1', padx=15, pady=10)
        personal_frame.grid(row=0, column=0, padx=10, pady=5, sticky='nsew')

        # Personal info labels with larger font
        self.guest_name_label = tk.Label(personal_frame, text="Name: ",
                                         font=('Segoe UI', 12, 'bold'),
                                         bg='white', fg='#333333', anchor='w')
        self.guest_name_label.pack(fill=tk.X, pady=3)

        self.guest_phone_label = tk.Label(personal_frame, text="Phone: ",
                                          font=('Segoe UI', 12),
                                          bg='white', fg='#333333', anchor='w')
        self.guest_phone_label.pack(fill=tk.X, pady=3)

        self.guest_email_label = tk.Label(personal_frame, text="Email: ",
                                          font=('Segoe UI', 12),
                                          bg='white', fg='#333333', anchor='w')
        self.guest_email_label.pack(fill=tk.X, pady=3)

        self.guest_id_card_label = tk.Label(personal_frame, text="ID Card: ",
                                            font=('Segoe UI', 12),
                                            bg='white', fg='#333333', anchor='w')
        self.guest_id_card_label.pack(fill=tk.X, pady=3)

        self.guest_address_label = tk.Label(personal_frame, text="Address: ",
                                            font=('Segoe UI', 12),
                                            bg='white', fg='#333333', anchor='w', wraplength=300)
        self.guest_address_label.pack(fill=tk.X, pady=3)

        # Column 2: Company Information
        company_frame = tk.LabelFrame(details_grid, text="🏢 Company Information",
                                      font=('Segoe UI', 13, 'bold'),
                                      bg='white', fg='#27ae60', padx=15, pady=10)
        company_frame.grid(row=0, column=1, padx=10, pady=5, sticky='nsew')

        self.guest_company_label = tk.Label(company_frame, text="Company: ",
                                            font=('Segoe UI', 12),
                                            bg='white', fg='#333333', anchor='w')
        self.guest_company_label.pack(fill=tk.X, pady=3)

        self.guest_company_address_label = tk.Label(company_frame, text="Company Address: ",
                                                    font=('Segoe UI', 12),
                                                    bg='white', fg='#333333', anchor='w', wraplength=300)
        self.guest_company_address_label.pack(fill=tk.X, pady=3)

        self.guest_party_gstin_label = tk.Label(company_frame, text="Party GSTIN: ",
                                                font=('Segoe UI', 12),
                                                bg='white', fg='#333333', anchor='w')
        self.guest_party_gstin_label.pack(fill=tk.X, pady=3)

        # Column 3: Statistics
        stats_frame = tk.LabelFrame(details_grid, text="📊 Statistics",
                                    font=('Segoe UI', 13, 'bold'),
                                    bg='white', fg='#c0392b', padx=15, pady=10)
        stats_frame.grid(row=0, column=2, padx=10, pady=5, sticky='nsew')

        self.guest_total_stays_label = tk.Label(stats_frame, text="Total Stays: 0",
                                                font=('Segoe UI', 12, 'bold'),
                                                bg='white', fg='#2e86c1', anchor='w')
        self.guest_total_stays_label.pack(fill=tk.X, pady=3)

        self.guest_total_spent_label = tk.Label(stats_frame, text="Total Spent: ₹0.00",
                                                font=('Segoe UI', 12, 'bold'),
                                                bg='white', fg='#27ae60', anchor='w')
        self.guest_total_spent_label.pack(fill=tk.X, pady=3)

        self.guest_total_advance_label = tk.Label(stats_frame, text="Total Advance: ₹0.00",
                                                  font=('Segoe UI', 12),
                                                  bg='white', fg='#333333', anchor='w')
        self.guest_total_advance_label.pack(fill=tk.X, pady=3)

        self.guest_total_paid_label = tk.Label(stats_frame, text="Total Paid: ₹0.00",
                                               font=('Segoe UI', 12),
                                               bg='white', fg='#333333', anchor='w')
        self.guest_total_paid_label.pack(fill=tk.X, pady=3)

        self.guest_total_discount_label = tk.Label(stats_frame, text="Total Discount: ₹0.00",
                                                   font=('Segoe UI', 12),
                                                   bg='white', fg='#e74c3c', anchor='w')
        self.guest_total_discount_label.pack(fill=tk.X, pady=3)

        # Configure grid weights
        details_grid.grid_columnconfigure(0, weight=1)
        details_grid.grid_columnconfigure(1, weight=1)
        details_grid.grid_columnconfigure(2, weight=1)

        # Notebook for tabs - takes remaining space
        notebook = ttk.Notebook(main_container)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # ========== BOOKINGS TAB ==========
        bookings_tab = ttk.Frame(notebook)
        notebook.add(bookings_tab, text="📋 BOOKING HISTORY")

        # Create frame for bookings with scrollbars
        bookings_frame = tk.Frame(bookings_tab, bg='white')
        bookings_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Create Treeview with scrollbars for bookings
        bookings_tree_frame = tk.Frame(bookings_frame, bg='white')
        bookings_tree_frame.pack(fill=tk.BOTH, expand=True)

        # Vertical scrollbar
        v_scroll_bookings = ttk.Scrollbar(bookings_tree_frame)
        v_scroll_bookings.pack(side=tk.RIGHT, fill=tk.Y)

        # Horizontal scrollbar
        h_scroll_bookings = ttk.Scrollbar(bookings_tree_frame, orient=tk.HORIZONTAL)
        h_scroll_bookings.pack(side=tk.BOTTOM, fill=tk.X)

        # Enhanced columns for bookings - more columns for full screen
        bookings_columns = ('ID', 'Date', 'Room No', 'Room Type', 'Check-in', 'Check-out',
                            'Nights', 'Total (₹)', 'Advance (₹)', 'Paid (₹)', 'Discount (₹)',
                            'Balance (₹)', 'Status', 'Created By')

        self.guest_bookings_tree = ttk.Treeview(bookings_tree_frame, columns=bookings_columns,
                                                yscrollcommand=v_scroll_bookings.set,
                                                xscrollcommand=h_scroll_bookings.set,
                                                height=12, show='headings')

        v_scroll_bookings.config(command=self.guest_bookings_tree.yview)
        h_scroll_bookings.config(command=self.guest_bookings_tree.xview)

        # Configure columns with appropriate widths for full screen
        column_widths = {
            'ID': 60,
            'Date': 100,
            'Room No': 80,
            'Room Type': 100,
            'Check-in': 150,
            'Check-out': 150,
            'Nights': 70,
            'Total (₹)': 100,
            'Advance (₹)': 100,
            'Paid (₹)': 100,
            'Discount (₹)': 100,
            'Balance (₹)': 100,
            'Status': 100,
            'Created By': 120
        }

        for col in bookings_columns:
            self.guest_bookings_tree.heading(col, text=col, anchor=tk.W)
            self.guest_bookings_tree.column(col, width=column_widths.get(col, 100), minwidth=60)

        self.guest_bookings_tree.pack(fill=tk.BOTH, expand=True)

        # ========== BILLS TAB ==========
        bills_tab = ttk.Frame(notebook)
        notebook.add(bills_tab, text="💰 BILL HISTORY")

        # Create frame for bills with scrollbars
        bills_frame = tk.Frame(bills_tab, bg='white')
        bills_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Treeview frame for bills
        bills_tree_frame = tk.Frame(bills_frame, bg='white')
        bills_tree_frame.pack(fill=tk.BOTH, expand=True)

        # Scrollbars for bills
        v_scroll_bills = ttk.Scrollbar(bills_tree_frame)
        v_scroll_bills.pack(side=tk.RIGHT, fill=tk.Y)

        h_scroll_bills = ttk.Scrollbar(bills_tree_frame, orient=tk.HORIZONTAL)
        h_scroll_bills.pack(side=tk.BOTTOM, fill=tk.X)

        # Enhanced columns for bills - more columns for full screen
        bills_columns = ('Bill No', 'Date', 'Room No', 'Check-in', 'Check-out',
                         'Total (₹)', 'Advance (₹)', 'Paid (₹)', 'Discount (₹)',
                         'Settled (₹)', 'Balance (₹)', 'Status', 'Verified By')

        self.guest_bills_tree = ttk.Treeview(bills_tree_frame, columns=bills_columns,
                                             yscrollcommand=v_scroll_bills.set,
                                             xscrollcommand=h_scroll_bills.set,
                                             height=12, show='headings')

        v_scroll_bills.config(command=self.guest_bills_tree.yview)
        h_scroll_bills.config(command=self.guest_bills_tree.xview)

        # Configure column widths for bills
        bill_column_widths = {
            'Bill No': 180,
            'Date': 150,
            'Room No': 80,
            'Check-in': 150,
            'Check-out': 150,
            'Total (₹)': 110,
            'Advance (₹)': 110,
            'Paid (₹)': 110,
            'Discount (₹)': 110,
            'Settled (₹)': 110,
            'Balance (₹)': 110,
            'Status': 100,
            'Verified By': 120
        }

        for col in bills_columns:
            self.guest_bills_tree.heading(col, text=col, anchor=tk.W)
            self.guest_bills_tree.column(col, width=bill_column_widths.get(col, 100), minwidth=70)

        self.guest_bills_tree.pack(fill=tk.BOTH, expand=True)

        # Action buttons frame - at bottom
        button_frame = tk.Frame(main_container, bg='white')
        button_frame.pack(fill=tk.X, pady=10)

        # Left side buttons
        left_buttons = tk.Frame(button_frame, bg='white')
        left_buttons.pack(side=tk.LEFT)

        view_bill_btn = tk.Button(left_buttons, text="👁️ VIEW SELECTED BILL",
                                  font=('Segoe UI', 12, 'bold'),
                                  bg='#2e86c1', fg='black', relief='flat',
                                  command=self.view_selected_guest_bill, padx=25, pady=10)
        view_bill_btn.pack(side=tk.LEFT, padx=5)
        view_bill_btn.bind('<Return>', lambda e, b=view_bill_btn: self.handle_enter_key(e, b))

        export_btn = tk.Button(left_buttons, text="📊 EXPORT HISTORY",
                               font=('Segoe UI', 12, 'bold'),
                               bg='#27ae60', fg='black', relief='flat',
                               command=self.export_guest_history, padx=25, pady=10)
        export_btn.pack(side=tk.LEFT, padx=5)
        export_btn.bind('<Return>', lambda e, b=export_btn: self.handle_enter_key(e, b))

        quick_checkin_btn = tk.Button(left_buttons, text="🔑 QUICK CHECK-IN",
                                      font=('Segoe UI', 12, 'bold'),
                                      bg='#f39c12', fg='black', relief='flat',
                                      command=self.quick_checkin_from_history, padx=25, pady=10)
        quick_checkin_btn.pack(side=tk.LEFT, padx=5)
        quick_checkin_btn.bind('<Return>', lambda e, b=quick_checkin_btn: self.handle_enter_key(e, b))

        # Right side buttons
        right_buttons = tk.Frame(button_frame, bg='white')
        right_buttons.pack(side=tk.RIGHT)

        clear_results_btn = tk.Button(right_buttons, text="🗑️ CLEAR RESULTS",
                                      font=('Segoe UI', 12, 'bold'),
                                      bg='#e74c3c', fg='black', relief='flat',
                                      command=self.clear_guest_results, padx=25, pady=10)
        clear_results_btn.pack(side=tk.RIGHT, padx=5)
        clear_results_btn.bind('<Return>', lambda e, b=clear_results_btn: self.handle_enter_key(e, b))

        # Set focus to search entry
        self.guest_search_term.focus()

        # Update the scrollregion after everything is packed
        scrollable_frame.update_idletasks()
        main_canvas.configure(scrollregion=main_canvas.bbox("all"))

    def search_guest_history(self):
        """Search and display guest history with all user details."""
        search_term = self.guest_search_term.get().strip()
        search_by = self.guest_search_by.get()

        if not search_term:
            self.show_warning("Please enter a search term")
            return

        # Clear existing data
        for item in self.guest_bookings_tree.get_children():
            self.guest_bookings_tree.delete(item)

        for item in self.guest_bills_tree.get_children():
            self.guest_bills_tree.delete(item)

        # Hide guest details frame initially
        self.guest_details_frame.pack_forget()

        try:
            # Get guest history from bookings
            bookings = self.hotel.get_guest_history(search_term, search_by)

            if not bookings:
                self.show_info(f"No guest found with {search_by}: {search_term}")
                return

            # Get the most recent booking for guest details
            latest_booking = bookings[0]

            # Display guest details in the details panel
            self.guest_name_label.config(text=f"Name: {latest_booking.get('guest_name', 'N/A')}")
            self.guest_phone_label.config(text=f"Phone: {latest_booking.get('guest_phone', 'N/A')}")
            self.guest_email_label.config(text=f"Email: {latest_booking.get('guest_email', 'N/A')}")
            self.guest_id_card_label.config(text=f"ID Card: {latest_booking.get('guest_id_card', 'N/A')}")
            self.guest_address_label.config(text=f"Address: {latest_booking.get('guest_address', 'N/A')}")

            self.guest_company_label.config(text=f"Company: {latest_booking.get('company_name', 'N/A')}")
            self.guest_company_address_label.config(
                text=f"Company Address: {latest_booking.get('company_address', 'N/A')}")
            self.guest_party_gstin_label.config(text=f"Party GSTIN: {latest_booking.get('party_gstin', 'N/A')}")

            # Show the details frame
            self.guest_details_frame.pack(fill=tk.X, pady=(0, 20))

            # Display bookings with balance calculation
            total_stays = 0
            total_spent = 0.0
            total_advance = 0.0
            total_paid = 0.0
            total_discount = 0.0

            for booking in bookings:
                # Format dates
                check_in = booking.get('check_in_time', '')
                check_out = booking.get('check_out_time', '')

                if check_in:
                    try:
                        check_in = datetime.fromisoformat(check_in).strftime('%Y-%m-%d %H:%M')
                    except:
                        check_in = str(check_in)

                if check_out:
                    try:
                        check_out = datetime.fromisoformat(check_out).strftime('%Y-%m-%d %H:%M')
                    except:
                        check_out = str(check_out)
                else:
                    check_out = '-'

                # Calculate nights
                nights = 0
                if booking.get('check_in_time') and booking.get('check_out_time'):
                    try:
                        check_in_dt = datetime.fromisoformat(booking['check_in_time'])
                        check_out_dt = datetime.fromisoformat(booking['check_out_time'])
                        nights = (check_out_dt - check_in_dt).days
                        if nights < 1:
                            nights = 1
                    except:
                        nights = booking.get('total_hours', 0) // 24 if booking.get('total_hours') else 1

                booking_total = booking.get('total_amount', 0.0)
                advance = booking.get('advance_payment', 0.0)
                paid = booking.get('total_paid', 0.0) or 0.0
                discount = booking.get('total_discount', 0.0) or 0.0
                balance = booking_total - advance - paid - discount
                if balance < 0:
                    balance = 0

                total_stays += 1
                total_spent += booking_total
                total_advance += advance
                total_paid += paid
                total_discount += discount

                created_at = booking.get('created_at', '')
                if created_at:
                    created_at = created_at[:10] if len(created_at) >= 10 else created_at

                created_by = booking.get('created_by_name', '')

                values = (
                    booking['id'],
                    created_at,
                    booking['room_number'],
                    booking.get('room_type', ''),
                    check_in,
                    check_out,
                    nights,
                    f"₹{booking_total:.2f}",
                    f"₹{advance:.2f}",
                    f"₹{paid:.2f}",
                    f"₹{discount:.2f}",
                    f"₹{balance:.2f}",
                    booking.get('status', '').upper(),
                    created_by
                )
                self.guest_bookings_tree.insert('', tk.END, values=values)

            # Update statistics
            self.guest_total_stays_label.config(text=f"Total Stays: {total_stays}")
            self.guest_total_spent_label.config(text=f"Total Spent: ₹{total_spent:.2f}")
            self.guest_total_advance_label.config(text=f"Total Advance: ₹{total_advance:.2f}")
            self.guest_total_paid_label.config(text=f"Total Paid: ₹{total_paid:.2f}")
            self.guest_total_discount_label.config(text=f"Total Discount: ₹{total_discount:.2f}")

            # Get and display bills
            guest_name = latest_booking.get('guest_name', '')
            guest_phone = latest_booking.get('guest_phone', '')
            guest_id = latest_booking.get('guest_id_card', '')

            if guest_name or guest_phone or guest_id:
                bills = self.hotel.get_guest_bills(guest_name, guest_phone, guest_id)

                for bill in bills:
                    # Format dates
                    bill_date = bill.get('bill_date', '')
                    if bill_date:
                        try:
                            bill_date = datetime.fromisoformat(bill_date).strftime('%Y-%m-%d %H:%M')
                        except:
                            bill_date = str(bill_date)

                    check_in = bill.get('check_in_time', '')
                    check_out = bill.get('check_out_time', '')

                    if check_in:
                        try:
                            check_in = datetime.fromisoformat(check_in).strftime('%Y-%m-%d %H:%M')
                        except:
                            check_in = str(check_in)

                    if check_out:
                        try:
                            check_out = datetime.fromisoformat(check_out).strftime('%Y-%m-%d %H:%M')
                        except:
                            check_out = str(check_out)

                    advance = bill.get('advance_paid', 0.0)
                    paid = bill.get('total_paid', 0.0) or 0.0
                    discount = bill.get('total_discount', 0.0) or 0.0
                    settled = paid
                    balance = bill.get('balance_due', 0.0)
                    verified_by = bill.get('verified_by', '')

                    values = (
                        bill['bill_number'],
                        bill_date,
                        bill['room_number'],
                        check_in,
                        check_out,
                        f"₹{bill['total_amount']:.2f}",
                        f"₹{advance:.2f}",
                        f"₹{paid:.2f}",
                        f"₹{discount:.2f}",
                        f"₹{settled:.2f}",
                        f"₹{balance:.2f}",
                        bill['payment_status'].upper(),
                        verified_by
                    )
                    self.guest_bills_tree.insert('', tk.END, values=values)

            # Show success message with count
            guest_name_display = latest_booking.get('guest_name', 'Guest')
            self.show_info(f"Found {total_stays} booking(s) for {guest_name_display}")

        except Exception as e:
            self.show_error(f"Error searching guest history: {str(e)}")
            import traceback
            traceback.print_exc()

    def clear_guest_search(self):
        """Clear guest search fields."""
        self.guest_search_term.delete(0, tk.END)
        self.guest_search_by.set('name')
        self.clear_guest_results()

    def clear_guest_results(self):
        """Clear guest history results."""
        for item in self.guest_bookings_tree.get_children():
            self.guest_bookings_tree.delete(item)

        for item in self.guest_bills_tree.get_children():
            self.guest_bills_tree.delete(item)

        self.guest_details_frame.pack_forget()

        # Reset labels
        self.guest_name_label.config(text="Name: ")
        self.guest_phone_label.config(text="Phone: ")
        self.guest_email_label.config(text="Email: ")
        self.guest_id_card_label.config(text="ID Card: ")
        self.guest_address_label.config(text="Address: ")
        self.guest_company_label.config(text="Company: ")
        self.guest_company_address_label.config(text="Company Address: ")
        self.guest_party_gstin_label.config(text="Party GSTIN: ")
        self.guest_total_stays_label.config(text="Total Stays: 0")
        self.guest_total_spent_label.config(text="Total Spent: ₹0.00")
        self.guest_total_advance_label.config(text="Total Advance: ₹0.00")
        self.guest_total_paid_label.config(text="Total Paid: ₹0.00")
        self.guest_total_discount_label.config(text="Total Discount: ₹0.00")

    def view_selected_guest_bill(self):
        """View selected bill from guest history."""
        if not self.guest_bills_tree.selection():
            self.show_warning("Please select a bill to view")
            return

        selection = self.guest_bills_tree.selection()
        bill_number = self.guest_bills_tree.item(selection[0])['values'][0]

        try:
            bill_details = self.hotel.get_bill_by_number(bill_number)

            if bill_details:
                # Get day breakdowns
                day_breakdowns = self.hotel.get_daily_breakdown(bill_details['id'])

                settings = self.hotel.get_hotel_settings()
                bill_details.update(settings)
                self.bill_generator.set_hotel_manager(self.hotel)
                self.bill_generator.print_bill(bill_details, day_breakdowns)
            else:
                self.show_error("Bill details not found!")
        except Exception as e:
            self.show_error(f"Error viewing bill: {str(e)}")

    def quick_checkin_from_history(self):
        """Quick check-in using guest history data."""
        if not hasattr(self, 'guest_bookings_tree') or not self.guest_bookings_tree.get_children():
            self.show_warning("No guest history loaded")
            return

        # Get guest details from the details panel
        name_text = self.guest_name_label.cget("text").replace("Name: ", "")
        phone_text = self.guest_phone_label.cget("text").replace("Phone: ", "")
        email_text = self.guest_email_label.cget("text").replace("Email: ", "")
        id_text = self.guest_id_card_label.cget("text").replace("ID Card: ", "")
        address_text = self.guest_address_label.cget("text").replace("Address: ", "")
        company_text = self.guest_company_label.cget("text").replace("Company: ", "")
        company_address_text = self.guest_company_address_label.cget("text").replace("Company Address: ", "")
        gstin_text = self.guest_party_gstin_label.cget("text").replace("Party GSTIN: ", "")

        if name_text == "N/A" or name_text == "":
            self.show_error("No valid guest data to check-in")
            return

        # Ask for confirmation
        if not self.ask_confirmation(f"Quick check-in for {name_text}?"):
            return

        # Open check-in dialog with pre-filled data
        self.open_checkin_with_guest_data({
            'guest_name': name_text if name_text != "N/A" else "",
            'guest_phone': phone_text if phone_text != "N/A" else "",
            'guest_email': email_text if email_text != "N/A" else "",
            'guest_id_card': id_text if id_text != "N/A" else "",
            'guest_address': address_text if address_text != "N/A" else "",
            'company_name': company_text if company_text != "N/A" else "",
            'company_address': company_address_text if company_address_text != "N/A" else "",
            'party_gstin': gstin_text if gstin_text != "N/A" else ""
        })

    def open_checkin_with_guest_data(self, guest_data):
        """Open check-in dialog with pre-filled guest data."""
        # Close current dialog
        self.close_active_dialog()

        # Open check-in dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("The Evaani Hotel - Quick Check-in")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg='white')
        self.center_dialog(dialog, 800, 900)

        # Create check-in content with pre-filled data
        self.create_checkin_dialog_with_data(dialog, guest_data)

        # Add close button
        close_btn = tk.Button(dialog, text="✕ CLOSE (ESC)", font=('Segoe UI', 12, 'bold'),
                              bg='#c0392b', fg='black', activebackground='#a93226',
                              activeforeground='white', relief='flat', cursor='hand2',
                              command=self.close_active_dialog, padx=15, pady=8)
        close_btn.place(relx=1.0, x=-20, y=20, anchor=tk.NE)

    def create_checkin_dialog_with_data(self, parent, guest_data):
        """Create check-in dialog with pre-filled guest data."""
        from datetime import datetime

        # Create a canvas with scrollbar for the form
        canvas = tk.Canvas(parent, bg='white', highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='white')

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Add warning note
        note_frame = tk.Frame(scrollable_frame, bg='#fff3cd', bd=1, relief=tk.SOLID)
        note_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(note_frame,
                 text="⚠️ Quick check-in from guest history - Data pre-filled",
                 font=('Segoe UI', 11, 'italic'), bg='#fff3cd', fg='#856404',
                 padx=10, pady=5).pack()

        # Room selection
        room_frame = tk.LabelFrame(scrollable_frame, text="Select Room",
                                   font=('Segoe UI', 12, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        room_frame.pack(fill=tk.X, pady=5)

        self.checkin_room_list = tk.Listbox(room_frame, height=4,
                                            font=('Segoe UI', 12), bg='white')
        self.checkin_room_list.pack(fill=tk.X)

        refresh_btn = tk.Button(room_frame, text="🔄 Refresh",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat',
                                command=self.load_checkin_rooms, padx=15, pady=5)
        refresh_btn.pack(pady=5)
        refresh_btn.bind('<Return>', lambda e, b=refresh_btn: self.handle_enter_key(e, b))

        self.load_checkin_rooms()

        # Guest info
        guest_frame = tk.LabelFrame(scrollable_frame, text="Guest Information",
                                    font=('Segoe UI', 12, 'bold'),
                                    bg='white', fg='#6a4334', padx=15, pady=10)
        guest_frame.pack(fill=tk.X, pady=5)

        row = 0
        tk.Label(guest_frame, text="Guest Name:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_guest_name = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_guest_name.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_guest_name.insert(0, guest_data.get('guest_name', ''))
        self.checkin_guest_name.focus()
        row += 1

        tk.Label(guest_frame, text="Phone:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_guest_phone = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_guest_phone.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_guest_phone.insert(0, guest_data.get('guest_phone', ''))
        row += 1

        tk.Label(guest_frame, text="Email:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_guest_email = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_guest_email.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_guest_email.insert(0, guest_data.get('guest_email', ''))
        row += 1

        tk.Label(guest_frame, text="ID Card:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_guest_id_card = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_guest_id_card.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_guest_id_card.insert(0, guest_data.get('guest_id_card', ''))
        row += 1

        tk.Label(guest_frame, text="Address:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_guest_address = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_guest_address.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_guest_address.insert(0, guest_data.get('guest_address', ''))
        row += 1

        tk.Label(guest_frame, text="No. of Persons:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_persons = tk.Entry(guest_frame, font=('Segoe UI', 12), width=35)
        self.checkin_persons.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_persons.insert(0, '1')
        row += 1

        # Company Information
        company_frame = tk.LabelFrame(scrollable_frame, text="Company Information (Optional)",
                                      font=('Segoe UI', 12, 'bold'),
                                      bg='white', fg='#6a4334', padx=15, pady=10)
        company_frame.pack(fill=tk.X, pady=5)

        row = 0
        tk.Label(company_frame, text="Company Name:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_company_name = tk.Entry(company_frame, font=('Segoe UI', 12), width=35)
        self.checkin_company_name.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_company_name.insert(0, guest_data.get('company_name', ''))
        row += 1

        tk.Label(company_frame, text="Company Address:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_company_address = tk.Entry(company_frame, font=('Segoe UI', 12), width=35)
        self.checkin_company_address.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_company_address.insert(0, guest_data.get('company_address', ''))
        row += 1

        tk.Label(company_frame, text="Party GSTIN:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_party_gstin = tk.Entry(company_frame, font=('Segoe UI', 12), width=35)
        self.checkin_party_gstin.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_party_gstin.insert(0, guest_data.get('party_gstin', ''))
        row += 1

        # Advance Payment
        advance_frame = tk.LabelFrame(scrollable_frame, text="Advance Payment",
                                      font=('Segoe UI', 12, 'bold'),
                                      bg='white', fg='#6a4334', padx=15, pady=10)
        advance_frame.pack(fill=tk.X, pady=5)

        row = 0
        tk.Label(advance_frame, text="Advance Amount (₹):", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_advance = tk.Entry(advance_frame, font=('Segoe UI', 12), width=20)
        self.checkin_advance.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_advance.insert(0, '0.00')
        row += 1

        tk.Label(advance_frame, text="Payment Method:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').grid(row=row, column=0, padx=5, pady=8, sticky='e')
        self.checkin_advance_method = ttk.Combobox(advance_frame,
                                                   values=['cash', 'card', 'online', 'upi'],
                                                   width=18, state='readonly', font=('Segoe UI', 12))
        self.checkin_advance_method.grid(row=row, column=1, padx=5, pady=8, sticky='w')
        self.checkin_advance_method.set('cash')
        row += 1

        # Check-in time
        time_frame = tk.LabelFrame(scrollable_frame, text="Check-in Time",
                                   font=('Segoe UI', 12, 'bold'),
                                   bg='white', fg='#6a4334', padx=15, pady=10)
        time_frame.pack(fill=tk.X, pady=5)

        tk.Label(time_frame, text="Time:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.checkin_time = tk.Entry(time_frame, font=('Segoe UI', 12), width=20)
        self.checkin_time.pack(side=tk.LEFT, padx=5)
        self.checkin_time.insert(0, datetime.now().strftime('%Y-%m-%d %H:%M'))

        now_btn = tk.Button(time_frame, text="NOW", font=('Segoe UI', 11, 'bold'),
                            bg='#f39c12', fg='black', relief='flat',
                            command=lambda: self.checkin_time.delete(0, tk.END) or
                                            self.checkin_time.insert(0, datetime.now().strftime('%Y-%m-%d %H:%M')),
                            padx=15, pady=5)
        now_btn.pack(side=tk.LEFT, padx=5)
        now_btn.bind('<Return>', lambda e, b=now_btn: self.handle_enter_key(e, b))

        # Check-in button
        checkin_btn = tk.Button(scrollable_frame, text="✅ CHECK-IN GUEST",
                                font=('Segoe UI', 14, 'bold'),
                                bg='#27ae60', fg='black', relief='flat',
                                command=self.checkin_guest, padx=40, pady=12)
        checkin_btn.pack(pady=15)
        checkin_btn.bind('<Return>', lambda e, b=checkin_btn: self.handle_enter_key(e, b))

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def export_guest_history(self):
        """Export complete guest history with all details to CSV."""
        if not self.guest_bookings_tree.get_children():
            self.show_warning("No guest history to export")
            return

        try:
            # Get guest details
            guest_name = self.guest_name_label.cget("text").replace("Name: ", "")
            if guest_name == "N/A" or guest_name == "":
                guest_name = "Guest"

            filename = f"guest_history_{guest_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)

                # Header
                writer.writerow(['THE EVAANI HOTEL - COMPLETE GUEST HISTORY'])
                writer.writerow(['Generated:', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
                writer.writerow([])

                # Guest Details
                writer.writerow(['GUEST DETAILS'])
                writer.writerow(['Name:', self.guest_name_label.cget("text").replace("Name: ", "")])
                writer.writerow(['Phone:', self.guest_phone_label.cget("text").replace("Phone: ", "")])
                writer.writerow(['Email:', self.guest_email_label.cget("text").replace("Email: ", "")])
                writer.writerow(['ID Card:', self.guest_id_card_label.cget("text").replace("ID Card: ", "")])
                writer.writerow(['Address:', self.guest_address_label.cget("text").replace("Address: ", "")])
                writer.writerow([])

                # Company Details
                writer.writerow(['COMPANY DETAILS'])
                writer.writerow(['Company Name:', self.guest_company_label.cget("text").replace("Company: ", "")])
                writer.writerow(['Company Address:',
                                 self.guest_company_address_label.cget("text").replace("Company Address: ", "")])
                writer.writerow(
                    ['Party GSTIN:', self.guest_party_gstin_label.cget("text").replace("Party GSTIN: ", "")])
                writer.writerow([])

                # Statistics
                writer.writerow(['STATISTICS'])
                writer.writerow(
                    ['Total Stays:', self.guest_total_stays_label.cget("text").replace("Total Stays: ", "")])
                writer.writerow(
                    ['Total Spent:', self.guest_total_spent_label.cget("text").replace("Total Spent: ", "")])
                writer.writerow(
                    ['Total Advance:', self.guest_total_advance_label.cget("text").replace("Total Advance: ", "")])
                writer.writerow(['Total Paid:', self.guest_total_paid_label.cget("text").replace("Total Paid: ", "")])
                writer.writerow(
                    ['Total Discount:', self.guest_total_discount_label.cget("text").replace("Total Discount: ", "")])
                writer.writerow([])

                # Bookings
                writer.writerow(['BOOKING HISTORY'])
                writer.writerow(['ID', 'Date', 'Room No', 'Room Type', 'Check-in', 'Check-out',
                                 'Nights', 'Total (₹)', 'Advance (₹)', 'Paid (₹)', 'Discount (₹)',
                                 'Balance (₹)', 'Status', 'Created By'])

                for item in self.guest_bookings_tree.get_children():
                    values = self.guest_bookings_tree.item(item)['values']
                    writer.writerow(values)

                writer.writerow([])

                # Bills
                writer.writerow(['BILL HISTORY'])
                writer.writerow(['Bill No', 'Date', 'Room No', 'Check-in', 'Check-out',
                                 'Total (₹)', 'Advance (₹)', 'Paid (₹)', 'Discount (₹)',
                                 'Settled (₹)', 'Balance (₹)', 'Status', 'Verified By'])

                for item in self.guest_bills_tree.get_children():
                    values = self.guest_bills_tree.item(item)['values']
                    writer.writerow(values)

            self.show_info(f"✅ Complete guest history exported to:\n{filename}")

        except Exception as e:
            self.show_error(f"Error exporting guest history: {str(e)}")

    # Add this to the HotelBillingAppGUI class (around line 5700-5800)

    def admin_edit_bill_dialog(self):
        """Admin-only full bill edit dialog."""

        if not self.auth.is_admin():
            self.show_error("Only administrators can edit bills")
            return

        if not self.bills_tree.selection():
            self.show_error("Please select a bill to edit")
            return

        selection = self.bills_tree.selection()
        bill_number = self.bills_tree.item(selection[0])['values'][0]

        try:
            bill = self.hotel.get_bill_by_number(bill_number)
            if not bill:
                raise ValueError("Bill not found")

            # Get full booking details
            booking = self.hotel.get_booking_by_id(bill['booking_id'])

            # Get all rooms for dropdown
            all_rooms = self.hotel.get_all_rooms_simple()

            dialog = tk.Toplevel(self.active_dialog if self.active_dialog else self.root)
            dialog.title(f"ADMIN EDIT BILL: {bill_number}")
            dialog.geometry("900x800")
            dialog.transient(self.active_dialog if self.active_dialog else self.root)
            dialog.grab_set()
            dialog.configure(bg='white')
            self.center_dialog(dialog, 900, 800)

            # Create main frame with scrollbar
            canvas = tk.Canvas(dialog, bg='white', highlightthickness=0)
            scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
            scrollable_frame = tk.Frame(canvas, bg='white')

            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )

            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)

            # Add warning banner
            warning_frame = tk.Frame(scrollable_frame, bg='#ffcccc', bd=2, relief=tk.SOLID)
            warning_frame.pack(fill=tk.X, pady=(0, 10))

            tk.Label(warning_frame,
                     text="⚠️ ADMIN EDIT MODE - Changes will affect bills, bookings, and settlements",
                     font=('Segoe UI', 12, 'bold'), bg='#ffcccc', fg='#c0392b',
                     padx=10, pady=5).pack()

            main_frame = tk.Frame(scrollable_frame, bg='white', padx=25, pady=15)
            main_frame.pack(fill=tk.BOTH, expand=True)

            tk.Label(main_frame, text=f"EDIT BILL - {bill_number}",
                     font=('Segoe UI', 20, 'bold'), bg='white', fg='#c0392b').pack(pady=(0, 15))

            # Create notebook for tabs
            notebook = ttk.Notebook(main_frame)
            notebook.pack(fill=tk.BOTH, expand=True)

            # Tab 1: Guest Information
            guest_tab = ttk.Frame(notebook)
            notebook.add(guest_tab, text='👤 Guest Info')

            self.create_admin_edit_guest_tab(guest_tab, bill, booking)

            # Tab 2: Room & Stay Details
            stay_tab = ttk.Frame(notebook)
            notebook.add(stay_tab, text='🏨 Room & Stay')

            self.create_admin_edit_stay_tab(stay_tab, bill, booking, all_rooms)

            # Tab 3: Financial Details
            finance_tab = ttk.Frame(notebook)
            notebook.add(finance_tab, text='💰 Financial')

            self.create_admin_edit_finance_tab(finance_tab, bill)

            # Tab 4: Tax & Discount
            tax_tab = ttk.Frame(notebook)
            notebook.add(tax_tab, text='📊 Tax & Discount')

            self.create_admin_edit_tax_tab(tax_tab, bill)

            # Reason for edit
            reason_frame = tk.LabelFrame(main_frame, text="Reason for Edit",
                                         font=('Segoe UI', 12, 'bold'),
                                         bg='white', fg='#c0392b', padx=15, pady=10)
            reason_frame.pack(fill=tk.X, pady=10)

            tk.Label(reason_frame, text="Reason:", font=('Segoe UI', 12),
                     bg='white', fg='#333333').pack(anchor=tk.W)
            self.admin_edit_reason = tk.Text(reason_frame, font=('Segoe UI', 12),
                                             height=3, width=80)
            self.admin_edit_reason.pack(fill=tk.X, pady=5)

            # Button frame
            button_frame = tk.Frame(main_frame, bg='white')
            button_frame.pack(pady=15)

            save_btn = tk.Button(button_frame, text="💾 SAVE CHANGES",
                                 font=('Segoe UI', 14, 'bold'),
                                 bg='#27ae60', fg='black', relief='flat',
                                 command=lambda: self.save_admin_bill_edit(bill['id']),
                                 padx=40, pady=10)
            save_btn.pack(side=tk.LEFT, padx=5)
            save_btn.bind('<Return>', lambda e, b=save_btn: self.handle_enter_key(e, b))

            preview_btn = tk.Button(button_frame, text="👁️ PREVIEW",
                                    font=('Segoe UI', 14, 'bold'),
                                    bg='#3498db', fg='black', relief='flat',
                                    command=lambda: self.preview_admin_bill_edit(bill['id']),
                                    padx=40, pady=10)
            preview_btn.pack(side=tk.LEFT, padx=5)
            preview_btn.bind('<Return>', lambda e, b=preview_btn: self.handle_enter_key(e, b))

            cancel_btn = tk.Button(button_frame, text="CANCEL",
                                   font=('Segoe UI', 14, 'bold'),
                                   bg='#95a5a6', fg='black', relief='flat',
                                   command=dialog.destroy, padx=40, pady=10)
            cancel_btn.pack(side=tk.LEFT, padx=5)
            cancel_btn.bind('<Return>', lambda e, b=cancel_btn: self.handle_enter_key(e, b))

            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            # Store references
            self.admin_edit_dialog = dialog
            self.admin_edit_bill = bill
            self.admin_edit_booking = booking

        except Exception as e:
            self.show_error(f"Error loading bill for edit: {str(e)}")
            import traceback
            traceback.print_exc()

    def create_admin_edit_guest_tab(self, parent, bill, booking):
        """Create guest information edit tab."""

        row = 0

        # Personal Information
        personal_frame = tk.LabelFrame(parent, text="Personal Information",
                                       font=('Segoe UI', 12, 'bold'),
                                       bg='white', fg='#2e86c1', padx=15, pady=10)
        personal_frame.grid(row=row, column=0, columnspan=2, padx=10, pady=5, sticky='nsew')
        row += 1

        r = 0
        tk.Label(personal_frame, text="Guest Name:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_guest_name = tk.Entry(personal_frame, font=('Segoe UI', 12), width=35)
        self.admin_edit_guest_name.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_guest_name.insert(0, booking.get('guest_name', ''))
        r += 1

        tk.Label(personal_frame, text="Phone:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_guest_phone = tk.Entry(personal_frame, font=('Segoe UI', 12), width=35)
        self.admin_edit_guest_phone.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_guest_phone.insert(0, booking.get('guest_phone', ''))
        r += 1

        tk.Label(personal_frame, text="Email:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_guest_email = tk.Entry(personal_frame, font=('Segoe UI', 12), width=35)
        self.admin_edit_guest_email.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_guest_email.insert(0, booking.get('guest_email', ''))
        r += 1

        tk.Label(personal_frame, text="ID Card:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_guest_id = tk.Entry(personal_frame, font=('Segoe UI', 12), width=35)
        self.admin_edit_guest_id.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_guest_id.insert(0, booking.get('guest_id_card', ''))
        r += 1

        tk.Label(personal_frame, text="Address:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_guest_address = tk.Entry(personal_frame, font=('Segoe UI', 12), width=35)
        self.admin_edit_guest_address.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_guest_address.insert(0, booking.get('guest_address', ''))
        r += 1

        tk.Label(personal_frame, text="No. of Persons:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_persons = tk.Entry(personal_frame, font=('Segoe UI', 12), width=35)
        self.admin_edit_persons.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_persons.insert(0, str(booking.get('no_of_persons', 1)))
        r += 1

        # Company Information
        company_frame = tk.LabelFrame(parent, text="Company Information",
                                      font=('Segoe UI', 12, 'bold'),
                                      bg='white', fg='#27ae60', padx=15, pady=10)
        company_frame.grid(row=row, column=0, columnspan=2, padx=10, pady=5, sticky='nsew')
        row += 1

        r = 0
        tk.Label(company_frame, text="Company Name:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_company = tk.Entry(company_frame, font=('Segoe UI', 12), width=35)
        self.admin_edit_company.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_company.insert(0, booking.get('company_name', ''))
        r += 1

        tk.Label(company_frame, text="Company Address:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_company_address = tk.Entry(company_frame, font=('Segoe UI', 12), width=35)
        self.admin_edit_company_address.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_company_address.insert(0, booking.get('company_address', ''))
        r += 1

        tk.Label(company_frame, text="Party GSTIN:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_gstin = tk.Entry(company_frame, font=('Segoe UI', 12), width=35)
        self.admin_edit_gstin.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_gstin.insert(0, booking.get('party_gstin', ''))
        r += 1

        # Document numbers
        doc_frame = tk.LabelFrame(parent, text="Document Numbers",
                                  font=('Segoe UI', 12, 'bold'),
                                  bg='white', fg='#8e44ad', padx=15, pady=10)
        doc_frame.grid(row=row, column=0, columnspan=2, padx=10, pady=5, sticky='nsew')
        row += 1

        r = 0
        tk.Label(doc_frame, text="Bill Number:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_bill_number = tk.Entry(doc_frame, font=('Segoe UI', 12), width=35)
        self.admin_edit_bill_number.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_bill_number.insert(0, bill.get('bill_number', ''))
        r += 1

        tk.Label(doc_frame, text="Folio No:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_folio = tk.Entry(doc_frame, font=('Segoe UI', 12), width=35)
        self.admin_edit_folio.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_folio.insert(0, bill.get('folio_no', ''))
        r += 1

        tk.Label(doc_frame, text="Registration No:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_reg = tk.Entry(doc_frame, font=('Segoe UI', 12), width=35)
        self.admin_edit_reg.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_reg.insert(0, bill.get('registration_no', ''))
        r += 1

    def create_admin_edit_stay_tab(self, parent, bill, booking, all_rooms):
        """Create room and stay details edit tab."""

        from datetime import datetime

        row = 0

        # Room Selection
        room_frame = tk.LabelFrame(parent, text="Room Details",
                                   font=('Segoe UI', 12, 'bold'),
                                   bg='white', fg='#e67e22', padx=15, pady=10)
        room_frame.grid(row=row, column=0, columnspan=2, padx=10, pady=5, sticky='nsew')
        row += 1

        r = 0
        tk.Label(room_frame, text="Current Room:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        current_room_label = tk.Label(room_frame, text=f"{bill['room_number']} ({bill.get('room_type', '')})",
                                      font=('Segoe UI', 12, 'bold'), bg='white', fg='#e74c3c')
        current_room_label.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        r += 1

        tk.Label(room_frame, text="New Room:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')

        # Create room selection dropdown
        room_values = [f"{room['id']} - {room['room_number']} ({room['room_type']})" for room in all_rooms]
        self.admin_edit_room = ttk.Combobox(room_frame, values=room_values,
                                            width=35, state='readonly', font=('Segoe UI', 12))
        self.admin_edit_room.grid(row=r, column=1, padx=5, pady=8, sticky='w')

        # Find current room in list
        current_room_id = bill['room_id']
        for i, val in enumerate(room_values):
            if val.startswith(str(current_room_id)):
                self.admin_edit_room.current(i)
                break

        r += 1

        # Stay Times
        time_frame = tk.LabelFrame(parent, text="Stay Times (12:00 PM Billing Cycle)",
                                   font=('Segoe UI', 12, 'bold'),
                                   bg='white', fg='#3498db', padx=15, pady=10)
        time_frame.grid(row=row, column=0, columnspan=2, padx=10, pady=5, sticky='nsew')
        row += 1

        r = 0
        # Check-in time
        tk.Label(time_frame, text="Check-in Time:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')

        checkin_frame = tk.Frame(time_frame, bg='white')
        checkin_frame.grid(row=r, column=1, padx=5, pady=8, sticky='w')

        self.admin_edit_checkin = tk.Entry(checkin_frame, font=('Segoe UI', 12), width=20)
        self.admin_edit_checkin.pack(side=tk.LEFT)
        checkin_str = datetime.fromisoformat(bill['check_in_time']).strftime('%Y-%m-%d %H:%M')
        self.admin_edit_checkin.insert(0, checkin_str)

        now_btn_checkin = tk.Button(checkin_frame, text="NOW", font=('Segoe UI', 10, 'bold'),
                                    bg='#f39c12', fg='black', relief='flat',
                                    command=lambda: self.admin_edit_checkin.delete(0, tk.END) or
                                                    self.admin_edit_checkin.insert(0, datetime.now().strftime(
                                                        '%Y-%m-%d %H:%M')),
                                    padx=10, pady=2)
        now_btn_checkin.pack(side=tk.LEFT, padx=5)
        r += 1

        # Check-out time
        tk.Label(time_frame, text="Check-out Time:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')

        checkout_frame = tk.Frame(time_frame, bg='white')
        checkout_frame.grid(row=r, column=1, padx=5, pady=8, sticky='w')

        self.admin_edit_checkout = tk.Entry(checkout_frame, font=('Segoe UI', 12), width=20)
        self.admin_edit_checkout.pack(side=tk.LEFT)
        checkout_str = datetime.fromisoformat(bill['check_out_time']).strftime('%Y-%m-%d %H:%M')
        self.admin_edit_checkout.insert(0, checkout_str)

        now_btn_checkout = tk.Button(checkout_frame, text="NOW", font=('Segoe UI', 10, 'bold'),
                                     bg='#f39c12', fg='black', relief='flat',
                                     command=lambda: self.admin_edit_checkout.delete(0, tk.END) or
                                                     self.admin_edit_checkout.insert(0, datetime.now().strftime(
                                                         '%Y-%m-%d %H:%M')),
                                     padx=10, pady=2)
        now_btn_checkout.pack(side=tk.LEFT, padx=5)
        r += 1

        # Info label about billing cycle
        info_label = tk.Label(time_frame,
                              text="Note: Changes to times will recalculate days based on 12:00 PM billing cycle",
                              font=('Segoe UI', 10, 'italic'), bg='white', fg='#7f8c8d')
        info_label.grid(row=r, column=0, columnspan=2, pady=5)

    def create_admin_edit_finance_tab(self, parent, bill):
        """Create financial details edit tab."""

        row = 0

        # Amounts
        amounts_frame = tk.LabelFrame(parent, text="Amounts",
                                      font=('Segoe UI', 12, 'bold'),
                                      bg='white', fg='#27ae60', padx=15, pady=10)
        amounts_frame.grid(row=row, column=0, columnspan=2, padx=10, pady=5, sticky='nsew')
        row += 1

        r = 0
        tk.Label(amounts_frame, text="Room Charges (₹):", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_room_charges = tk.Entry(amounts_frame, font=('Segoe UI', 12), width=20)
        self.admin_edit_room_charges.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_room_charges.insert(0, str(bill['room_charges']))
        r += 1

        tk.Label(amounts_frame, text="Food Total (₹):", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_food = tk.Entry(amounts_frame, font=('Segoe UI', 12), width=20)
        self.admin_edit_food.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_food.insert(0, str(bill.get('food_total', 0.0)))
        r += 1

        tk.Label(amounts_frame, text="Food GST (₹):", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_food_gst = tk.Entry(amounts_frame, font=('Segoe UI', 12), width=20)
        self.admin_edit_food_gst.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_food_gst.insert(0, str(bill.get('food_gst_total', 0.0)))
        r += 1

        # Payments
        payments_frame = tk.LabelFrame(parent, text="Payments",
                                       font=('Segoe UI', 12, 'bold'),
                                       bg='white', fg='#e74c3c', padx=15, pady=10)
        payments_frame.grid(row=row, column=0, columnspan=2, padx=10, pady=5, sticky='nsew')
        row += 1

        r = 0
        tk.Label(payments_frame, text="Advance Paid (₹):", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_advance = tk.Entry(payments_frame, font=('Segoe UI', 12), width=20)
        self.admin_edit_advance.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_advance.insert(0, str(bill.get('advance_paid', 0.0)))
        r += 1

        tk.Label(payments_frame, text="Payment Method:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_payment_method = ttk.Combobox(payments_frame,
                                                      values=['cash', 'card', 'online', 'upi'],
                                                      width=18, state='readonly', font=('Segoe UI', 12))
        self.admin_edit_payment_method.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_payment_method.set(bill.get('payment_method', 'cash'))
        r += 1

        tk.Label(payments_frame, text="Notes:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='ne')
        self.admin_edit_notes = tk.Text(payments_frame, font=('Segoe UI', 12), width=30, height=3)
        self.admin_edit_notes.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_notes.insert('1.0', bill.get('notes', ''))
        r += 1

    def create_admin_edit_tax_tab(self, parent, bill):
        """Create tax and discount edit tab."""

        row = 0

        # Tax percentages
        tax_frame = tk.LabelFrame(parent, text="Tax Percentages",
                                  font=('Segoe UI', 12, 'bold'),
                                  bg='white', fg='#8e44ad', padx=15, pady=10)
        tax_frame.grid(row=row, column=0, columnspan=2, padx=10, pady=5, sticky='nsew')
        row += 1

        r = 0
        tk.Label(tax_frame, text="CGST %:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_cgst = tk.Entry(tax_frame, font=('Segoe UI', 12), width=15)
        self.admin_edit_cgst.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_cgst.insert(0, str(bill.get('cgst_percentage', 2.5)))
        r += 1

        tk.Label(tax_frame, text="SGST %:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_sgst = tk.Entry(tax_frame, font=('Segoe UI', 12), width=15)
        self.admin_edit_sgst.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_sgst.insert(0, str(bill.get('sgst_percentage', 2.5)))
        r += 1

        tk.Label(tax_frame, text="CGST Amount (₹):", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_cgst_amt = tk.Entry(tax_frame, font=('Segoe UI', 12), width=15)
        self.admin_edit_cgst_amt.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_cgst_amt.insert(0, str(bill.get('cgst_amount', 0.0)))
        r += 1

        tk.Label(tax_frame, text="SGST Amount (₹):", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_sgst_amt = tk.Entry(tax_frame, font=('Segoe UI', 12), width=15)
        self.admin_edit_sgst_amt.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_sgst_amt.insert(0, str(bill.get('sgst_amount', 0.0)))
        r += 1

        # Discount
        discount_frame = tk.LabelFrame(parent, text="Discount",
                                       font=('Segoe UI', 12, 'bold'),
                                       bg='white', fg='#f39c12', padx=15, pady=10)
        discount_frame.grid(row=row, column=0, columnspan=2, padx=10, pady=5, sticky='nsew')
        row += 1

        r = 0
        tk.Label(discount_frame, text="Discount %:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_discount_pct = tk.Entry(discount_frame, font=('Segoe UI', 12), width=15)
        self.admin_edit_discount_pct.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_discount_pct.insert(0, str(bill.get('discount_percentage', 0.0)))
        r += 1

        tk.Label(discount_frame, text="Discount Amount (₹):", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_discount_amt = tk.Entry(discount_frame, font=('Segoe UI', 12), width=15)
        self.admin_edit_discount_amt.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_discount_amt.insert(0, str(bill.get('discount_amount', 0.0)))
        r += 1

        # Verified By
        verified_frame = tk.LabelFrame(parent, text="Verification",
                                       font=('Segoe UI', 12, 'bold'),
                                       bg='white', fg='#16a085', padx=15, pady=10)
        verified_frame.grid(row=row, column=0, columnspan=2, padx=10, pady=5, sticky='nsew')
        row += 1

        r = 0
        tk.Label(verified_frame, text="Verified By:", font=('Segoe UI', 12),
                 bg='white', fg='#333333').grid(row=r, column=0, padx=5, pady=8, sticky='e')
        self.admin_edit_verified = tk.Entry(verified_frame, font=('Segoe UI', 12), width=25)
        self.admin_edit_verified.grid(row=r, column=1, padx=5, pady=8, sticky='w')
        self.admin_edit_verified.insert(0, bill.get('verified_by', self.auth.current_user[
            'username'] if self.auth.current_user else ''))

    def preview_admin_bill_edit(self, bill_id):
        """Preview the bill with current edit changes."""
        try:
            # Collect all edit data
            edit_data = self.collect_admin_edit_data()

            # Get current bill
            bill = self.hotel.get_bill_by_id(bill_id)
            if not bill:
                raise ValueError("Bill not found")

            # Create preview by merging current bill with edits
            preview_bill = dict(bill)
            preview_bill.update(edit_data)

            # Add hotel settings
            settings = self.hotel.get_hotel_settings()
            preview_bill.update(settings)

            # Get day breakdowns (recalculated in preview)
            self.bill_generator.set_hotel_manager(self.hotel)

            # Show preview
            self.bill_generator.print_bill(preview_bill, None)

        except Exception as e:
            self.show_error(f"Error previewing bill: {str(e)}")

    def collect_admin_edit_data(self):
        """Collect all edit data from the admin edit form."""

        edit_data = {}

        # Guest info
        if hasattr(self, 'admin_edit_guest_name'):
            edit_data['guest_name'] = self.admin_edit_guest_name.get().strip()
        if hasattr(self, 'admin_edit_guest_phone'):
            edit_data['guest_phone'] = self.admin_edit_guest_phone.get().strip()
        if hasattr(self, 'admin_edit_guest_email'):
            edit_data['guest_email'] = self.admin_edit_guest_email.get().strip()
        if hasattr(self, 'admin_edit_guest_id'):
            edit_data['guest_id_card'] = self.admin_edit_guest_id.get().strip()
        if hasattr(self, 'admin_edit_guest_address'):
            edit_data['guest_address'] = self.admin_edit_guest_address.get().strip()
        if hasattr(self, 'admin_edit_persons'):
            edit_data['no_of_persons'] = int(self.admin_edit_persons.get() or 1)

        # Company info
        if hasattr(self, 'admin_edit_company'):
            edit_data['company_name'] = self.admin_edit_company.get().strip()
        if hasattr(self, 'admin_edit_company_address'):
            edit_data['company_address'] = self.admin_edit_company_address.get().strip()
        if hasattr(self, 'admin_edit_gstin'):
            edit_data['party_gstin'] = self.admin_edit_gstin.get().strip()

        # Document numbers
        if hasattr(self, 'admin_edit_bill_number'):
            edit_data['bill_number'] = self.admin_edit_bill_number.get().strip()
        if hasattr(self, 'admin_edit_folio'):
            edit_data['folio_no'] = self.admin_edit_folio.get().strip()
        if hasattr(self, 'admin_edit_reg'):
            edit_data['registration_no'] = self.admin_edit_reg.get().strip()

        # Room selection
        if hasattr(self, 'admin_edit_room') and self.admin_edit_room.get():
            room_val = self.admin_edit_room.get()
            room_id = int(room_val.split(' - ')[0])
            edit_data['room_id'] = room_id

        # Times
        if hasattr(self, 'admin_edit_checkin'):
            edit_data['check_in_time'] = self.admin_edit_checkin.get().strip()
        if hasattr(self, 'admin_edit_checkout'):
            edit_data['check_out_time'] = self.admin_edit_checkout.get().strip()

        # Amounts
        if hasattr(self, 'admin_edit_room_charges'):
            edit_data['room_charges'] = float(self.admin_edit_room_charges.get() or 0)
        if hasattr(self, 'admin_edit_food'):
            edit_data['food_total'] = float(self.admin_edit_food.get() or 0)
        if hasattr(self, 'admin_edit_food_gst'):
            edit_data['food_gst_total'] = float(self.admin_edit_food_gst.get() or 0)

        # Payments
        if hasattr(self, 'admin_edit_advance'):
            edit_data['advance_paid'] = float(self.admin_edit_advance.get() or 0)
        if hasattr(self, 'admin_edit_payment_method'):
            edit_data['payment_method'] = self.admin_edit_payment_method.get()
        if hasattr(self, 'admin_edit_notes'):
            edit_data['notes'] = self.admin_edit_notes.get('1.0', tk.END).strip()

        # Tax
        if hasattr(self, 'admin_edit_cgst'):
            edit_data['cgst_percentage'] = float(self.admin_edit_cgst.get() or 0)
        if hasattr(self, 'admin_edit_sgst'):
            edit_data['sgst_percentage'] = float(self.admin_edit_sgst.get() or 0)
        if hasattr(self, 'admin_edit_cgst_amt'):
            edit_data['cgst_amount'] = float(self.admin_edit_cgst_amt.get() or 0)
        if hasattr(self, 'admin_edit_sgst_amt'):
            edit_data['sgst_amount'] = float(self.admin_edit_sgst_amt.get() or 0)

        # Discount
        if hasattr(self, 'admin_edit_discount_pct'):
            edit_data['discount_percentage'] = float(self.admin_edit_discount_pct.get() or 0)
        if hasattr(self, 'admin_edit_discount_amt'):
            edit_data['discount_amount'] = float(self.admin_edit_discount_amt.get() or 0)

        # Verified by
        if hasattr(self, 'admin_edit_verified'):
            edit_data['verified_by'] = self.admin_edit_verified.get().strip()

        return edit_data

    def save_admin_bill_edit(self, bill_id):
        """Save admin bill edits."""

        reason = self.admin_edit_reason.get('1.0', tk.END).strip()
        if not reason:
            self.show_error("Please provide a reason for editing the bill")
            return

        if not self.ask_confirmation(
                "⚠️ ADMIN EDIT WARNING ⚠️\n\nThis will permanently modify the bill and all related records.\nThis action cannot be undone.\n\nAre you absolutely sure?"):
            return

        try:
            edit_data = self.collect_admin_edit_data()

            # Add reason
            edit_data['reason'] = reason

            # Perform the edit
            result = self.hotel.admin_edit_bill(bill_id, edit_data, reason)

            self.show_info(
                f"✅ BILL EDITED SUCCESSFULLY\n\n"
                f"Bill Number: {result['bill_number']}\n"
                f"Old Total: ₹{result['old_total']:.2f}\n"
                f"New Total: ₹{result['new_total']:.2f}\n"
                f"Old Balance: ₹{result['old_balance']:.2f}\n"
                f"New Balance: ₹{result['new_balance']:.2f}\n"
                f"{'Room Changed: Yes (New Room: ' + result['new_room_number'] + ')' if result['room_changed'] else 'Room Changed: No'}"
            )

            # Close dialog and refresh
            self.admin_edit_dialog.destroy()
            self.load_all_bills()
            self.load_pending_settlements()

        except Exception as e:
            self.show_error(f"Error saving bill edit: {str(e)}")
            import traceback
            traceback.print_exc()

    def run(self):
        self.root.mainloop()


# Main entry point
if __name__ == "__main__":
    try:
        app = HotelBillingAppGUI()
        app.run()
    except Exception as e:
        print(f"Error starting application: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")

