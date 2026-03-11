import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sqlite3
import hashlib
import json
import os
from datetime import datetime
import csv
from PIL import Image, ImageTk
import sys
import queue
import threading
import time


# Database setup with connection pooling - FIXED for thread safety
class Database:
    def __init__(self, db_name='inventory.db'):
        self.db_name = db_name
        self.connection_pool = queue.Queue(maxsize=10)
        self.local = threading.local()
        self.init_connection_pool()
        self.init_database()

    def init_connection_pool(self):
        """Initialize connection pool with 5 connections."""
        for _ in range(5):
            conn = sqlite3.connect(self.db_name, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=2000")
            self.connection_pool.put(conn)

    def get_connection(self):
        """Get a connection from the pool with better error handling."""
        try:
            # Try to get from pool
            return self.connection_pool.get(timeout=10)
        except queue.Empty:
            # Create new connection if pool is empty
            conn = sqlite3.connect(self.db_name, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA synchronous=NORMAL")
            return conn

    def return_connection(self, conn):
        """Return connection to the pool safely."""
        if conn:
            try:
                # Rollback any pending transactions
                try:
                    conn.rollback()
                except:
                    pass
                # Try to return to pool
                self.connection_pool.put(conn, timeout=5)
            except queue.Full:
                # Close if pool is full
                try:
                    conn.close()
                except:
                    pass

    def execute_query(self, query, params=(), fetch_one=False, fetch_all=False, commit=False):
        """Execute a query with proper connection handling to avoid locks."""
        conn = None
        cursor = None
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
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                # Retry once
                time.sleep(0.5)
                if conn:
                    try:
                        conn.rollback()
                    except:
                        pass
                cursor = conn.cursor()
                cursor.execute(query, params)
                if fetch_one:
                    result = cursor.fetchone()
                elif fetch_all:
                    result = cursor.fetchall()
                if commit:
                    conn.commit()
                return result
            else:
                raise
        finally:
            if conn:
                self.return_connection(conn)

    def init_database(self):
        """Initialize database tables with proper schema - SAFE version without dropping tables."""
        conn = None
        try:
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

            # Inventory table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    category TEXT,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    price REAL,
                    min_stock_level INTEGER DEFAULT 10,
                    supplier TEXT,
                    location TEXT,
                    barcode TEXT UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Inventory history
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS inventory_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER,
                    user_id INTEGER,
                    action TEXT,
                    old_quantity INTEGER,
                    new_quantity INTEGER,
                    old_price REAL,
                    new_price REAL,
                    reason TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (item_id) REFERENCES inventory (id),
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')

            # Product usage table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS product_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER,
                    user_id INTEGER,
                    quantity_taken INTEGER,
                    reason TEXT,
                    usage_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (item_id) REFERENCES inventory (id),
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')

            # Orders table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_number TEXT UNIQUE,
                    customer_name TEXT,
                    items TEXT,
                    total_amount REAL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Stock additions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stock_additions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER,
                    user_id INTEGER,
                    quantity_added INTEGER,
                    addition_type TEXT,
                    reason TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (item_id) REFERENCES inventory (id),
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')

            # Supplier purchases table - SAFE initialization without dropping
            try:
                # Check if table exists
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='supplier_purchases'")
                table_exists = cursor.fetchone()

                if not table_exists:
                    # Create table if it doesn't exist
                    cursor.execute('''
                        CREATE TABLE supplier_purchases (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            supplier_name TEXT NOT NULL,
                            item_id INTEGER,
                            item_name TEXT NOT NULL,
                            quantity INTEGER NOT NULL,
                            unit_price REAL NOT NULL,
                            total_cost REAL NOT NULL,
                            purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            user_id INTEGER,
                            invoice_number TEXT,
                            notes TEXT,
                            FOREIGN KEY (item_id) REFERENCES inventory (id),
                            FOREIGN KEY (user_id) REFERENCES users (id)
                        )
                    ''')
                    print("Created supplier_purchases table")
                else:
                    # Table exists, check for missing columns
                    cursor.execute("PRAGMA table_info(supplier_purchases)")
                    columns = cursor.fetchall()
                    column_names = [col[1] for col in columns]

                    # Add missing columns if needed
                    if 'invoice_number' not in column_names:
                        cursor.execute("ALTER TABLE supplier_purchases ADD COLUMN invoice_number TEXT")
                        print("Added invoice_number column to supplier_purchases")

                    if 'notes' not in column_names:
                        cursor.execute("ALTER TABLE supplier_purchases ADD COLUMN notes TEXT")
                        print("Added notes column to supplier_purchases")

            except Exception as e:
                print(f"Error setting up supplier_purchases table: {e}")

            # Add default admin user if not exists
            admin_hash = self.hash_password('admin123')
            cursor.execute('''
                INSERT OR IGNORE INTO users (username, password_hash, role, email)
                VALUES (?, ?, ?, ?)
            ''', ('admin', admin_hash, 'admin', 'admin@inventory.com'))

            # Add test user if not exists
            user_hash = self.hash_password('user123')
            cursor.execute('''
                INSERT OR IGNORE INTO users (username, password_hash, role, email)
                VALUES (?, ?, ?, ?)
            ''', ('user', user_hash, 'user', 'user@inventory.com'))

            conn.commit()
            print("Database initialized successfully with correct schema")

        except Exception as e:
            print(f"Database initialization error: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
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


# Input validation utility
class InputValidator:
    @staticmethod
    def validate_integer(value, field_name, min_value=None, max_value=None):
        try:
            int_val = int(value)
            if min_value is not None and int_val < min_value:
                raise ValueError(f"{field_name} must be at least {min_value}")
            if max_value is not None and int_val > max_value:
                raise ValueError(f"{field_name} must be at most {max_value}")
            return int_val
        except ValueError as e:
            if "invalid literal" in str(e):
                raise ValueError(f"{field_name} must be a valid number")
            raise

    @staticmethod
    def validate_float(value, field_name, min_value=None, max_value=None):
        try:
            float_val = float(value)
            if min_value is not None and float_val < min_value:
                raise ValueError(f"{field_name} must be at least {min_value}")
            if max_value is not None and float_val > max_value:
                raise ValueError(f"{field_name} must be at most {max_value}")
            return float_val
        except ValueError:
            raise ValueError(f"{field_name} must be a valid decimal number")

    @staticmethod
    def validate_string(value, field_name, min_length=None, max_length=None):
        if not value or not value.strip():
            raise ValueError(f"{field_name} cannot be empty")

        value = value.strip()
        if min_length is not None and len(value) < min_length:
            raise ValueError(f"{field_name} must be at least {min_length} characters")
        if max_length is not None and len(value) > max_length:
            raise ValueError(f"{field_name} must be at most {max_length} characters")
        return value

    @staticmethod
    def validate_email(value):
        if not value:
            return ""
        if "@" not in value or "." not in value:
            raise ValueError("Please enter a valid email address")
        return value


# Authentication system
class Authentication:
    def __init__(self, db: Database):
        self.db = db
        self.current_user = None

    def login(self, username, password):
        try:
            username = InputValidator.validate_string(username, "Username", 1, 50)
            password = InputValidator.validate_string(password, "Password", 1, 50)

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


# Inventory Management
class InventoryManager:
    def __init__(self, db: Database, auth: Authentication):
        self.db = db
        self.auth = auth

    def add_item(self, item_data: dict, reason: str = "", addition_type: str = "NEW_ITEM"):
        conn = None
        try:
            # Validate input data
            item_data['name'] = InputValidator.validate_string(item_data['name'], "Item name", 1, 100)
            item_data['description'] = item_data.get('description', '').strip()
            item_data['category'] = InputValidator.validate_string(item_data['category'], "Category", 1, 50)
            item_data['quantity'] = InputValidator.validate_integer(item_data['quantity'], "Quantity", 0, 1000000)
            item_data['price'] = InputValidator.validate_float(item_data['price'], "Price", 0, 1000000)
            item_data['min_stock_level'] = InputValidator.validate_integer(
                item_data.get('min_stock_level', 10), "Minimum stock level", 0, 1000000
            )
            item_data['supplier'] = item_data.get('supplier', '').strip()
            item_data['location'] = item_data.get('location', '').strip()

            conn = self.db.get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO inventory 
                (name, description, category, quantity, price, min_stock_level, supplier, location, barcode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                item_data['name'],
                item_data['description'],
                item_data['category'],
                item_data['quantity'],
                item_data['price'],
                item_data['min_stock_level'],
                item_data['supplier'],
                item_data['location'],
                None
            ))

            item_id = cursor.lastrowid

            # Update barcode with the item ID
            cursor.execute('UPDATE inventory SET barcode = ? WHERE id = ?', (str(item_id), item_id))

            # Log the action in inventory_history
            if self.auth.current_user:
                cursor.execute('''
                    INSERT INTO inventory_history 
                    (item_id, user_id, action, old_quantity, new_quantity, old_price, new_price, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    item_id,
                    self.auth.current_user['id'],
                    'CREATE',
                    0,
                    item_data['quantity'],
                    0.0,
                    item_data['price'],
                    reason
                ))

                # Log stock addition
                cursor.execute('''
                    INSERT INTO stock_additions 
                    (item_id, user_id, quantity_added, addition_type, reason)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    item_id,
                    self.auth.current_user['id'],
                    item_data['quantity'],
                    addition_type,
                    reason
                ))

                # FORCE supplier purchase creation - ALWAYS create one if quantity > 0
                if item_data['quantity'] > 0:
                    # Get supplier name (use default if not provided)
                    supplier_name = item_data['supplier']
                    if not supplier_name or not supplier_name.strip():
                        supplier_name = 'UNKNOWN SUPPLIER'

                    total_cost = item_data['quantity'] * item_data['price']

                    print(
                        f"CREATING SUPPLIER PURCHASE - Item ID: {item_id}, Supplier: {supplier_name}, Qty: {item_data['quantity']}, Price: {item_data['price']}")

                    cursor.execute('''
                        INSERT INTO supplier_purchases 
                        (supplier_name, item_id, item_name, quantity, unit_price, total_cost, user_id, notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        supplier_name,
                        item_id,
                        item_data['name'],
                        item_data['quantity'],
                        item_data['price'],
                        total_cost,
                        self.auth.current_user['id'],
                        f"Initial stock - {reason}"
                    ))

            conn.commit()

            # Verify the record was created
            verify = self.db.execute_query(
                'SELECT COUNT(*) as count FROM supplier_purchases WHERE item_id = ?',
                (item_id,),
                fetch_one=True
            )
            print(f"VERIFICATION - Supplier purchases for item {item_id}: {verify['count'] if verify else 0}")

            return item_id

        except Exception as e:
            if conn:
                conn.rollback()
            print(f"ERROR adding item: {str(e)}")
            import traceback
            traceback.print_exc()
            raise ValueError(f"Error adding item: {str(e)}")
        finally:
            if conn:
                self.db.return_connection(conn)

    def update_item(self, item_id: int, item_data: dict, reason: str = ""):
        """Update an existing item and sync with supplier records."""
        conn = None
        try:
            # Validate input data
            item_data['name'] = InputValidator.validate_string(item_data['name'], "Item name", 1, 100)
            item_data['description'] = item_data.get('description', '').strip()
            item_data['category'] = InputValidator.validate_string(item_data['category'], "Category", 1, 50)
            item_data['quantity'] = InputValidator.validate_integer(item_data['quantity'], "Quantity", 0, 1000000)
            item_data['price'] = InputValidator.validate_float(item_data['price'], "Price", 0, 1000000)
            item_data['min_stock_level'] = InputValidator.validate_integer(
                item_data.get('min_stock_level', 10), "Minimum stock level", 0, 1000000
            )
            item_data['supplier'] = item_data.get('supplier', '').strip()
            item_data['location'] = item_data.get('location', '').strip()

            conn = self.db.get_connection()
            cursor = conn.cursor()

            # Get current item data
            cursor.execute('SELECT * FROM inventory WHERE id = ?', (item_id,))
            current_item = cursor.fetchone()

            if not current_item:
                raise ValueError(f"Item with ID {item_id} not found")

            # Convert current_item to dictionary for easier access
            current_item_dict = dict(current_item)

            # Update item
            cursor.execute('''
                UPDATE inventory 
                SET name = ?, description = ?, category = ?, quantity = ?, price = ?, 
                    min_stock_level = ?, supplier = ?, location = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (
                item_data['name'],
                item_data['description'],
                item_data['category'],
                item_data['quantity'],
                item_data['price'],  # This is now a float from validation
                item_data['min_stock_level'],
                item_data['supplier'],
                item_data['location'],
                item_id
            ))

            # Log the action in inventory_history
            if self.auth.current_user:
                cursor.execute('''
                    INSERT INTO inventory_history 
                    (item_id, user_id, action, old_quantity, new_quantity, old_price, new_price, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    item_id,
                    self.auth.current_user['id'],
                    'UPDATE',
                    current_item_dict['quantity'],
                    item_data['quantity'],
                    current_item_dict['price'],
                    item_data['price'],
                    reason or "Item updated"
                ))

            # If supplier or price changed, update relevant supplier records
            if (current_item_dict['supplier'] != item_data['supplier'] or
                    current_item_dict['price'] != item_data['price'] or
                    current_item_dict['name'] != item_data['name']):

                # First, update all supplier purchase records for this item with new name, price, and supplier
                cursor.execute('''
                    UPDATE supplier_purchases 
                    SET item_name = ?, unit_price = ?, supplier_name = ?
                    WHERE item_id = ?
                ''', (
                    item_data['name'],
                    item_data['price'],  # This is the new price as float
                    item_data['supplier'],
                    item_id
                ))

                # Recalculate total costs for all affected records
                cursor.execute('''
                    UPDATE supplier_purchases 
                    SET total_cost = quantity * unit_price
                    WHERE item_id = ?
                ''', (item_id,))

                # Log supplier update in notes for the most recent purchase
                cursor.execute('''
                    SELECT id FROM supplier_purchases 
                    WHERE item_id = ? 
                    ORDER BY purchase_date DESC LIMIT 1
                ''', (item_id,))

                last_purchase = cursor.fetchone()
                if last_purchase:
                    cursor.execute('''
                        UPDATE supplier_purchases 
                        SET notes = ? 
                        WHERE id = ?
                    ''', (
                        f"Updated: Supplier changed from {current_item_dict['supplier']} to {item_data['supplier']}, "
                        f"Price changed from ${current_item_dict['price']:.2f} to ${item_data['price']:.2f} - {reason}",
                        last_purchase['id']
                    ))

            conn.commit()
            return True

        except Exception as e:
            if conn:
                conn.rollback()
            raise ValueError(f"Error updating item: {str(e)}")
        finally:
            if conn:
                self.db.return_connection(conn)

    def delete_item(self, item_id: int, reason: str = ""):
        """Delete an item from inventory."""
        conn = None
        try:
            if not self.auth.is_admin():
                raise ValueError("Only administrators can delete items")

            conn = self.db.get_connection()
            cursor = conn.cursor()

            # Get current item data
            cursor.execute('SELECT * FROM inventory WHERE id = ?', (item_id,))
            item = cursor.fetchone()

            if not item:
                raise ValueError(f"Item with ID {item_id} not found")

            # Log the deletion in inventory_history
            if self.auth.current_user:
                cursor.execute('''
                    INSERT INTO inventory_history 
                    (item_id, user_id, action, old_quantity, new_quantity, old_price, new_price, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    item_id,
                    self.auth.current_user['id'],
                    'DELETE',
                    item['quantity'],
                    0,
                    item['price'],
                    0.0,
                    reason or "Item deleted"
                ))

            # Delete the item
            cursor.execute('DELETE FROM inventory WHERE id = ?', (item_id,))

            conn.commit()
            return True

        except Exception as e:
            if conn:
                conn.rollback()
            raise ValueError(f"Error deleting item: {str(e)}")
        finally:
            if conn:
                self.db.return_connection(conn)

    def add_to_existing_item(self, item_id: int, quantity: int, reason: str = "", unit_price: float = None,
                             invoice_number: str = ""):
        conn = None
        try:
            # Validate inputs
            quantity = InputValidator.validate_integer(quantity, "Quantity to add", 1, 1000000)

            if not reason or not reason.strip():
                if not self.auth.is_admin():
                    raise ValueError("Reason is required for this action")
                reason = "Stock addition by admin"

            conn = self.db.get_connection()
            cursor = conn.cursor()

            # Get current item data
            cursor.execute('SELECT quantity, name, price, supplier FROM inventory WHERE id = ?', (item_id,))
            item = cursor.fetchone()

            if not item:
                raise ValueError(f"Item with ID {item_id} not found")

            current_qty, item_name, current_price, supplier = item

            # Use current price if no new price provided
            if unit_price is None:
                unit_price = current_price

            # Update inventory quantity
            new_qty = current_qty + quantity
            cursor.execute('UPDATE inventory SET quantity = ? WHERE id = ?', (new_qty, item_id))

            # Log the action in inventory_history
            if self.auth.current_user:
                cursor.execute('''
                    INSERT INTO inventory_history 
                    (item_id, user_id, action, old_quantity, new_quantity, old_price, new_price, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    item_id,
                    self.auth.current_user['id'],
                    'STOCK_ADDITION',
                    current_qty,
                    new_qty,
                    current_price,
                    current_price,
                    reason
                ))

                # Log stock addition
                cursor.execute('''
                    INSERT INTO stock_additions 
                    (item_id, user_id, quantity_added, addition_type, reason)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    item_id,
                    self.auth.current_user['id'],
                    quantity,
                    'EXISTING_ITEM',
                    reason
                ))

                # ALWAYS log supplier purchase, use default if supplier doesn't exist
                supplier_name = supplier if supplier and supplier.strip() else 'UNKNOWN SUPPLIER'

                total_cost = quantity * unit_price

                print(
                    f"Logging supplier purchase for existing item - Supplier: {supplier_name}, Item: {item_name}, Quantity: {quantity}, Price: {unit_price}")

                try:
                    cursor.execute('''
                        INSERT INTO supplier_purchases 
                        (supplier_name, item_id, item_name, quantity, unit_price, total_cost, user_id, invoice_number, notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        supplier_name,
                        item_id,
                        item_name,
                        quantity,
                        unit_price,
                        total_cost,
                        self.auth.current_user['id'],
                        invoice_number,
                        reason
                    ))
                    print("Supplier purchase logged successfully")
                except Exception as e:
                    print(f"Error logging supplier purchase: {e}")
                    # Continue even if supplier logging fails

            conn.commit()
            return True, new_qty

        except Exception as e:
            if conn:
                conn.rollback()
            print(f"Error adding to existing item: {str(e)}")
            raise ValueError(f"Error adding to existing item: {str(e)}")
        finally:
            if conn:
                self.db.return_connection(conn)

    def take_product(self, item_id: int, quantity: int, reason: str):
        conn = None
        try:
            # Validate inputs
            if not reason or not reason.strip():
                raise ValueError("Reason is required for taking a product")

            quantity = InputValidator.validate_integer(quantity, "Quantity to take", 1, 1000000)

            conn = self.db.get_connection()
            cursor = conn.cursor()

            # Check current quantity
            cursor.execute('SELECT quantity, name FROM inventory WHERE id = ?', (item_id,))
            item = cursor.fetchone()

            if not item:
                raise ValueError(f"Item with ID {item_id} not found")

            current_qty, item_name = item
            if current_qty < quantity:
                raise ValueError(f"Not enough stock. Available: {current_qty}, Requested: {quantity}")

            # Update inventory
            new_qty = current_qty - quantity
            cursor.execute('UPDATE inventory SET quantity = ? WHERE id = ?', (new_qty, item_id))

            # Log product usage
            cursor.execute('''
                INSERT INTO product_usage (item_id, user_id, quantity_taken, reason)
                VALUES (?, ?, ?, ?)
            ''', (item_id, self.auth.current_user['id'], quantity, reason))

            # Log inventory history
            cursor.execute('''
                INSERT INTO inventory_history 
                (item_id, user_id, action, old_quantity, new_quantity, old_price, new_price, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                item_id,
                self.auth.current_user['id'],
                'USAGE',
                current_qty,
                new_qty,
                0.0,
                0.0,
                reason
            ))

            conn.commit()
            return True

        except Exception as e:
            if conn:
                conn.rollback()
            raise ValueError(f"Error taking product: {str(e)}")
        finally:
            if conn:
                self.db.return_connection(conn)

    def add_user(self, username, password, role, email):
        """Add a new user."""
        conn = None
        try:
            username = InputValidator.validate_string(username, "Username", 3, 50)
            if len(password) < 4:
                raise ValueError("Password must be at least 4 characters")
            role = InputValidator.validate_string(role, "Role", 1, 20)
            if email and email.strip():
                email = InputValidator.validate_email(email)

            conn = self.db.get_connection()
            cursor = conn.cursor()

            password_hash = self.db.hash_password(password)

            cursor.execute('''
                INSERT INTO users (username, password_hash, role, email)
                VALUES (?, ?, ?, ?)
            ''', (username, password_hash, role, email))

            conn.commit()
            return True

        except sqlite3.IntegrityError:
            raise ValueError("Username already exists!")
        except Exception as e:
            if conn:
                conn.rollback()
            raise ValueError(f"Error adding user: {str(e)}")
        finally:
            if conn:
                self.db.return_connection(conn)

    def delete_user(self, user_id: int):
        """Delete a user."""
        conn = None
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()

            # Check if user exists
            cursor.execute('SELECT username, role FROM users WHERE id = ?', (user_id,))
            user = cursor.fetchone()

            if not user:
                raise ValueError("User not found")

            # Prevent deleting self
            if self.auth.current_user and user_id == self.auth.current_user['id']:
                raise ValueError("You cannot delete your own account")

            # Prevent deleting the last admin
            if user['role'] == 'admin':
                cursor.execute('SELECT COUNT(*) as admin_count FROM users WHERE role = "admin"')
                admin_count = cursor.fetchone()['admin_count']
                if admin_count <= 1:
                    raise ValueError("Cannot delete the last admin user")

            # Delete user
            cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
            conn.commit()
            return True

        except Exception as e:
            if conn:
                conn.rollback()
            raise ValueError(f"Error deleting user: {str(e)}")
        finally:
            if conn:
                self.db.return_connection(conn)

    def get_all_users(self):
        """Get all users."""
        result = self.db.execute_query(
            'SELECT id, username, role, email, created_at FROM users ORDER BY username',
            fetch_all=True
        )

        users = []
        if result:
            for user in result:
                users.append(dict(user))
        return users

    def get_all_items(self, filters: dict = None):
        """Get all inventory items with optional filters."""
        query = 'SELECT * FROM inventory WHERE 1=1'
        params = []

        if filters:
            if 'category' in filters and filters['category']:
                query += ' AND LOWER(TRIM(category)) = LOWER(TRIM(?))'
                params.append(filters['category'])
            if 'name_like' in filters and filters['name_like']:
                query += ' AND name LIKE ?'
                params.append(f'%{filters["name_like"]}%')
            if 'supplier' in filters and filters['supplier']:
                query += ' AND LOWER(TRIM(supplier)) = LOWER(TRIM(?))'
                params.append(filters['supplier'])

        query += ' ORDER BY name'

        result = self.db.execute_query(query, params, fetch_all=True)

        items = []
        if result:
            for item in result:
                items.append(dict(item))
        return items

    def get_item_by_id(self, item_id: int):
        """Get item by ID."""
        result = self.db.execute_query(
            'SELECT * FROM inventory WHERE id = ?',
            (item_id,),
            fetch_one=True
        )
        return dict(result) if result else None

    def get_item_by_name(self, name: str):
        """Search items by name."""
        result = self.db.execute_query(
            'SELECT * FROM inventory WHERE name LIKE ?',
            (f'%{name}%',),
            fetch_all=True
        )

        items = []
        if result:
            for item in result:
                items.append(dict(item))
        return items

    def get_low_stock_items(self):
        """Get items with quantity <= min_stock_level."""
        result = self.db.execute_query(
            'SELECT * FROM inventory WHERE quantity <= min_stock_level ORDER BY quantity ASC',
            fetch_all=True
        )

        items = []
        if result:
            for item in result:
                items.append(dict(item))
        return items

    def get_inventory_history(self, item_id: int = None, limit: int = 100):
        """Get inventory history."""
        if item_id:
            result = self.db.execute_query('''
                SELECT h.*, u.username, i.name 
                FROM inventory_history h
                JOIN users u ON h.user_id = u.id
                JOIN inventory i ON h.item_id = i.id
                WHERE h.item_id = ?
                ORDER BY h.timestamp DESC
                LIMIT ?
            ''', (item_id, limit), fetch_all=True)
        else:
            result = self.db.execute_query('''
                SELECT h.*, u.username, i.name 
                FROM inventory_history h
                JOIN users u ON h.user_id = u.id
                JOIN inventory i ON h.item_id = i.id
                ORDER BY h.timestamp DESC
                LIMIT ?
            ''', (limit,), fetch_all=True)

        history = []
        if result:
            for record in result:
                history.append(dict(record))
        return history

    def get_product_usage(self, limit: int = 100):
        """Get product usage records."""
        result = self.db.execute_query('''
            SELECT pu.*, u.username, i.name 
            FROM product_usage pu
            JOIN users u ON pu.user_id = u.id
            JOIN inventory i ON pu.item_id = i.id
            ORDER BY pu.usage_date DESC
            LIMIT ?
        ''', (limit,), fetch_all=True)

        usage = []
        if result:
            for record in result:
                usage.append(dict(record))
        return usage

    def get_stock_additions(self, limit: int = 100):
        """Get all stock additions."""
        result = self.db.execute_query('''
            SELECT sa.*, u.username, i.name, i.category
            FROM stock_additions sa
            JOIN users u ON sa.user_id = u.id
            JOIN inventory i ON sa.item_id = i.id
            ORDER BY sa.added_at DESC
            LIMIT ?
        ''', (limit,), fetch_all=True)

        additions = []
        if result:
            for record in result:
                additions.append(dict(record))
        return additions

    def get_supplier_purchases(self, supplier_name: str = None, start_date: str = None, end_date: str = None):
        """Get supplier purchase data with filtering options."""
        print(
            f"Getting supplier purchases with filters - Supplier: {supplier_name}, Start: {start_date}, End: {end_date}")

        query = '''
            SELECT sp.*, u.username 
            FROM supplier_purchases sp
            LEFT JOIN users u ON sp.user_id = u.id
            WHERE 1=1
        '''
        params = []

        if supplier_name and supplier_name != 'ALL' and supplier_name.strip():
            query += ' AND LOWER(TRIM(sp.supplier_name)) = LOWER(TRIM(?))'
            params.append(supplier_name.strip())

        if start_date and start_date.strip():
            query += ' AND DATE(sp.purchase_date) >= DATE(?)'
            params.append(start_date.strip())

        if end_date and end_date.strip():
            query += ' AND DATE(sp.purchase_date) <= DATE(?)'
            params.append(end_date.strip())

        query += ' ORDER BY sp.purchase_date DESC'

        print(f"Executing query: {query}")
        print(f"With params: {params}")

        result = self.db.execute_query(query, params, fetch_all=True)

        purchases = []
        if result:
            for record in result:
                purchases.append(dict(record))
            print(f"Found {len(purchases)} supplier purchases")
        else:
            print("No supplier purchases found")

        return purchases

    def get_supplier_summary(self):
        """Get summary of purchases by supplier."""
        result = self.db.execute_query('''
            SELECT 
                supplier_name,
                COUNT(*) as purchase_count,
                SUM(quantity) as total_quantity,
                SUM(total_cost) as total_spent,
                AVG(unit_price) as avg_price,
                    MAX(purchase_date) as last_purchase
                FROM supplier_purchases
                WHERE supplier_name IS NOT NULL AND supplier_name != ''
                GROUP BY supplier_name
                ORDER BY total_spent DESC
            ''', fetch_all=True)

        summary = []
        if result:
            for record in result:
                summary.append(dict(record))
        return summary

    def get_all_suppliers(self):
        """Get list of all unique suppliers."""
        result = self.db.execute_query('''
            SELECT DISTINCT supplier_name 
            FROM supplier_purchases 
            WHERE supplier_name IS NOT NULL AND supplier_name != ''
            ORDER BY supplier_name
        ''', fetch_all=True)

        suppliers = ['ALL']
        if result:
            for supplier in result:
                if supplier['supplier_name'] and supplier['supplier_name'].strip():
                    suppliers.append(supplier['supplier_name'])
        return suppliers


# Tkinter GUI Application
class InventoryAppGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("The Evaani Hotel - Inventory Management System")

        # Start in full screen mode
        self.root.state('zoomed')

        # Get screen dimensions and set geometry
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_width}x{screen_height}")

        # Initialize database and managers
        self.db = Database()
        self.auth = Authentication(self.db)
        self.inventory = InventoryManager(self.db, self.auth)
        self.validator = InputValidator()

        # Set style
        self.setup_styles()

        # Login frame
        self.login_frame = None
        self.main_frame = None
        self.create_login_frame()

        # Dictionary to store active popup windows
        self.active_popups = {}

        # Track current popup
        self.current_popup = None

        # Bind Enter key globally for forms
        self.root.bind('<Return>', self.handle_enter_key)

    def center_window(self, width, height):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def setup_styles(self):
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
        style.configure('TLabel', background=light_bg, font=('Segoe UI', 11))
        style.configure('Header.TLabel', background=primary_color, foreground='white',
                        font=('Segoe UI', 18, 'bold'), padding=15)
        style.configure('Title.TLabel', font=('Segoe UI', 16, 'bold'), foreground=primary_color)
        style.configure('Subtitle.TLabel', font=('Segoe UI', 14, 'bold'), foreground=secondary_color)

        # Configure buttons with grey color scheme
        style.configure('TButton', font=('Segoe UI', 11, 'bold'), padding=8)  # Reduced padding
        style.configure('Primary.TButton', background=grey_color, foreground='white')
        style.map('Primary.TButton', background=[('active', dark_grey)])
        style.configure('Success.TButton', background=grey_color, foreground='white')
        style.map('Success.TButton', background=[('active', dark_grey)])
        style.configure('Danger.TButton', background=grey_color, foreground='white')
        style.map('Danger.TButton', background=[('active', dark_grey)])
        style.configure('Warning.TButton', background=grey_color, foreground='white')
        style.map('Warning.TButton', background=[('active', dark_grey)])
        style.configure('Info.TButton', background=grey_color, foreground='white')
        style.map('Info.TButton', background=[('active', dark_grey)])

        # Configure treeview
        style.configure('Treeview', font=('Segoe UI', 11), rowheight=28)  # Slightly reduced row height
        style.configure('Treeview.Heading', font=('Segoe UI', 12, 'bold'), background=light_bg)

        self.root.configure(bg=light_bg)

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
                if isinstance(child, tk.Button) and child.cget('text') in ['LOGIN', 'ADD', 'UPDATE', 'SEARCH', 'TAKE',
                                                                           'SAVE']:
                    child.invoke()
                    return "break"

        return None

    def clear_frame(self, frame):
        for widget in frame.winfo_children():
            widget.destroy()

    def show_error(self, message):
        messagebox.showerror("Error", message)

    def show_warning(self, message):
        messagebox.showwarning("Warning", message)

    def show_info(self, message):
        messagebox.showinfo("Information", message)

    def ask_confirmation(self, message):
        return messagebox.askyesno("Confirmation", message)

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

        # Hotel branding
        brand_frame = tk.Frame(left_frame, bg='#6a4334')
        brand_frame.pack(expand=True, pady=100)

        tk.Label(brand_frame, text="THE", font=('Georgia', 24, 'bold'),
                 bg='#6a4334', fg='white').pack()
        tk.Label(brand_frame, text="EVAANI", font=('Georgia', 48, 'bold'),
                 bg='#6a4334', fg='white').pack()
        tk.Label(brand_frame, text="HOTEL", font=('Georgia', 28, 'bold'),
                 bg='#6a4334', fg='white').pack(pady=(0, 20))

        tk.Label(brand_frame, text="Inventory Management System", font=('Segoe UI', 16),
                 bg='#6a4334', fg='#d5d8dc').pack()
        tk.Label(brand_frame, text="Track & Manage Your Inventory", font=('Segoe UI', 14),
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

    def login(self):
        username = self.username_entry.get()
        password = self.password_entry.get()

        try:
            user = self.auth.login(username, password)
            if user:
                self.login_frame.destroy()
                self.create_main_menu()
            else:
                self.show_error("Invalid username or password!")
        except ValueError as e:
            self.show_error(str(e))

    def create_main_menu(self):
        """Create the main menu screen with centered buttons in a vertical line - transparent backgrounds with image."""
        self.main_frame = tk.Frame(self.root, bg='#f8f9fa')
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # Create header
        self.create_header()

        # Create main container
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

            img = Image.open("resort.jpg")  # Make sure this image exists in your directory
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

        # ALL CONTENT PLACED DIRECTLY ON IMAGE - VERTICAL CENTERED LIST
        # Title
        title_label = tk.Label(main_container,
                               text="INVENTORY MANAGEMENT SYSTEM",
                               font=('Segoe UI', 24, 'bold'),
                               bg='#f8f9fa',
                               fg='black',
                               bd=0)
        title_label.place(relx=0.52, rely=0.12, anchor=tk.CENTER)

        # Subtitle
        if self.auth.is_admin():
            subtitle_text = f"Welcome, {self.auth.current_user['username'].upper()} (ADMINISTRATOR)"
        else:
            subtitle_text = f"Welcome, {self.auth.current_user['username'].upper()} (USER)"

        subtitle = tk.Label(main_container,
                            text=subtitle_text,
                            font=('Segoe UI', 16),
                            bg='#f8f9fa',
                            fg='black',
                            bd=0)
        subtitle.place(relx=0.52, rely=0.18, anchor=tk.CENTER)

        # Define buttons based on user role
        grey_color = '#6c757d'
        dark_grey = '#5a6268'

        if self.auth.is_admin():
            buttons = [
                ('F1', '📦 VIEW INVENTORY', 'inventory'),
                ('F2', '➕ ADD ITEM', 'add_item'),
                ('F3', '📈 ADD TO EXISTING', 'add_existing'),
                ('F4', '🚚 TAKE PRODUCT', 'take_product'),
                ('F5', '⚠️ LOW STOCK ALERTS', 'low_stock'),
                ('F6', '📜 INVENTORY HISTORY', 'history'),
                ('F7', '📊 PRODUCT USAGE', 'usage'),
                ('F8', '👥 USER MANAGEMENT', 'users'),
                ('F9', '📈 STOCK ADDITIONS', 'stock_additions'),
                ('F10', '🏭 SUPPLIER DATA', 'supplier_data'),
                ('F11', '💾 EXPORT DATA', 'export')
            ]
        else:
            buttons = [
                ('F1', '📦 VIEW INVENTORY', 'inventory'),
                ('F2', '➕ ADD ITEM', 'add_item'),
                ('F3', '📈 ADD TO EXISTING', 'add_existing'),
                ('F4', '🚚 TAKE PRODUCT', 'take_product'),
                ('F5', '⚠️ LOW STOCK ALERTS', 'low_stock'),
                ('F10', '🏭 SUPPLIER DATA', 'supplier_data')
            ]

        # Create vertical buttons - NO CONTAINER FRAMES, placed directly on main_container
        badge_start_x = 0.43  # Position for badge (left of center)
        button_start_x = 0.45  # Position for button (slightly right of badge)
        start_y = 0.26  # Starting Y position
        spacing = 0.055  # Space between buttons

        for i, (shortcut, text, command_id) in enumerate(buttons):
            y_pos = start_y + (i * spacing)

            # Shortcut badge - placed directly on main_container
            badge = tk.Label(main_container,
                             text=shortcut,
                             font=('Segoe UI', 11, 'bold'),
                             bg='#6a4334',
                             fg='white',
                             width=4,
                             height=2,
                             relief=tk.FLAT,
                             bd=0)
            badge.place(relx=badge_start_x, rely=y_pos, anchor=tk.E)

            # Main button - placed directly on main_container
            btn = tk.Button(main_container,
                            text=text,
                            font=('Segoe UI', 13, 'bold'),
                            bg=grey_color,
                            fg='black',
                            activebackground=dark_grey,
                            activeforeground='black',
                            relief=tk.RAISED,
                            bd=2,
                            cursor='hand2',
                            width=28,
                            height=2,
                            command=lambda c=command_id: self.open_popup(c))
            btn.place(relx=button_start_x, rely=y_pos, anchor=tk.W)

            # Store shortcut reference for keyboard binding
            btn.shortcut_key = shortcut

        # Keyboard shortcuts
        self.setup_shortcuts()

        # Status bar (this remains with color background at bottom)
        status_bar = tk.Frame(self.main_frame, bg='#6a4334', height=25)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        status_bar.pack_propagate(False)

        status_text = f"Logged in as: {self.auth.current_user['username']} | Role: {self.auth.current_user['role']} | Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        tk.Label(status_bar, text=status_text, font=('Segoe UI', 9),
                 bg='#6a4334', fg='white').pack(side=tk.LEFT, padx=20, pady=3)

        # Force initial resize
        self.root.update_idletasks()
        main_container.event_generate('<Configure>')

    def setup_shortcuts(self):
        """Setup keyboard shortcuts F1-F12 for menu items."""
        # Unbind any existing shortcuts
        for i in range(1, 13):
            self.root.unbind(f'<F{i}>')

        # Bind shortcuts based on user role
        if self.auth.is_admin():
            self.root.bind('<F1>', lambda e: self.open_popup('inventory'))
            self.root.bind('<F2>', lambda e: self.open_popup('add_item'))
            self.root.bind('<F3>', lambda e: self.open_popup('add_existing'))
            self.root.bind('<F4>', lambda e: self.open_popup('take_product'))
            self.root.bind('<F5>', lambda e: self.open_popup('low_stock'))
            self.root.bind('<F6>', lambda e: self.open_popup('history'))
            self.root.bind('<F7>', lambda e: self.open_popup('usage'))
            self.root.bind('<F8>', lambda e: self.open_popup('users'))
            self.root.bind('<F9>', lambda e: self.open_popup('stock_additions'))
            self.root.bind('<F10>', lambda e: self.open_popup('supplier_data'))
            self.root.bind('<F11>', lambda e: self.open_popup('export'))
            self.root.bind('<F12>', lambda e: self.show_info("Press F1-F11 for different functions"))
        else:
            self.root.bind('<F1>', lambda e: self.open_popup('inventory'))
            self.root.bind('<F2>', lambda e: self.open_popup('add_item'))
            self.root.bind('<F3>', lambda e: self.open_popup('add_existing'))
            self.root.bind('<F4>', lambda e: self.open_popup('take_product'))
            self.root.bind('<F5>', lambda e: self.open_popup('low_stock'))
            self.root.bind('<F10>', lambda e: self.open_popup('supplier_data'))

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
            'inventory': 'View Inventory',
            'add_item': 'Add Item',
            'add_existing': 'Add to Existing Item',
            'take_product': 'Take Product',
            'low_stock': 'Low Stock Alerts',
            'history': 'Inventory History',
            'usage': 'Product Usage',
            'users': 'User Management',
            'stock_additions': 'Stock Additions',
            'supplier_data': 'Supplier Data',
            'export': 'Export Data'
        }
        return titles.get(tab_id, tab_id.replace('_', ' ').title())

    def create_popup_content(self, parent, tab_id):
        """Create content for popup window."""
        # Clear parent
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
        if tab_id == 'inventory':
            self.create_inventory_popup(main_container)
        elif tab_id == 'add_item':
            self.create_add_item_popup(main_container)
        elif tab_id == 'add_existing':
            self.create_add_existing_popup(main_container)
        elif tab_id == 'take_product':
            self.create_take_product_popup(main_container)
        elif tab_id == 'low_stock':
            self.create_low_stock_popup(main_container)
        elif tab_id == 'history':
            self.create_history_popup(main_container)
        elif tab_id == 'usage':
            self.create_usage_popup(main_container)
        elif tab_id == 'users' and self.auth.is_admin():
            self.create_users_popup(main_container)
        elif tab_id == 'stock_additions' and self.auth.is_admin():
            self.create_stock_additions_popup(main_container)
        elif tab_id == 'supplier_data':
            self.create_supplier_data_popup(main_container)
        elif tab_id == 'export' and self.auth.is_admin():
            self.create_export_popup(main_container)

    def create_inventory_popup(self, parent):
        """Create inventory view popup with edit and delete functionality."""
        # Filter frame
        filter_frame = tk.Frame(parent, bg='white')
        filter_frame.pack(fill=tk.X, pady=(0, 20))

        # Category filter
        tk.Label(filter_frame, text="Category:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.category_var = tk.StringVar()
        self.category_combo = ttk.Combobox(filter_frame, textvariable=self.category_var, width=20,
                                           state='readonly', font=('Segoe UI', 11))
        self.category_combo.pack(side=tk.LEFT, padx=5)

        # Search filter
        tk.Label(filter_frame, text="Search:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=(20, 5))
        self.search_var = tk.StringVar()
        search_entry = tk.Entry(filter_frame, textvariable=self.search_var, font=('Segoe UI', 11), width=30)
        search_entry.pack(side=tk.LEFT, padx=5)
        search_entry.bind('<Return>', lambda e: self.load_inventory_popup_data())

        filter_btn = tk.Button(filter_frame, text="🔍 APPLY",
                               font=('Segoe UI', 11, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                               command=self.load_inventory_popup_data, padx=15, pady=5)
        filter_btn.pack(side=tk.LEFT, padx=10)

        # Action buttons frame
        action_frame = tk.Frame(parent, bg='white')
        action_frame.pack(fill=tk.X, pady=(0, 10))

        edit_btn = tk.Button(action_frame, text="✏️ EDIT SELECTED",
                             font=('Segoe UI', 11, 'bold'),
                             bg='#f39c12', fg='black', relief='flat', cursor='hand2',
                             command=self.edit_selected_item, padx=15, pady=5)
        edit_btn.pack(side=tk.LEFT, padx=5)

        if self.auth.is_admin():
            delete_btn = tk.Button(action_frame, text="🗑️ DELETE SELECTED",
                                   font=('Segoe UI', 11, 'bold'),
                                   bg='#c0392b', fg='black', relief='flat', cursor='hand2',
                                   command=self.delete_selected_item, padx=15, pady=5)
            delete_btn.pack(side=tk.LEFT, padx=5)

        refresh_btn = tk.Button(action_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                                command=self.load_inventory_popup_data, padx=15, pady=5)
        refresh_btn.pack(side=tk.RIGHT, padx=5)

        # Treeview frame
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        # Create treeview with scrollbars
        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        columns = ('ID', 'Name', 'Category', 'Quantity', 'Price', 'Min Stock', 'Location', 'Barcode', 'Supplier')
        self.inventory_tree_popup = ttk.Treeview(tree_container, columns=columns,
                                                 yscrollcommand=v_scrollbar.set,
                                                 xscrollcommand=h_scrollbar.set,
                                                 height=15)

        v_scrollbar.config(command=self.inventory_tree_popup.yview)
        h_scrollbar.config(command=self.inventory_tree_popup.xview)

        # Configure columns
        for col in columns:
            self.inventory_tree_popup.heading(col, text=col, anchor=tk.W)
            self.inventory_tree_popup.column(col, width=100, minwidth=80)

        self.inventory_tree_popup.column('ID', width=60)
        self.inventory_tree_popup.column('Name', width=150)
        self.inventory_tree_popup.column('Barcode', width=80)
        self.inventory_tree_popup.column('Supplier', width=120)

        self.inventory_tree_popup.pack(fill=tk.BOTH, expand=True)

        # Bind double-click for editing
        self.inventory_tree_popup.bind('<Double-Button-1>', lambda e: self.edit_selected_item())

        # Load initial data
        self.load_inventory_popup_data()
        self.load_categories()

    def edit_selected_item(self):
        """Edit the selected item."""
        selection = self.inventory_tree_popup.selection()
        if not selection:
            self.show_warning("Please select an item to edit.")
            return

        item_id = self.inventory_tree_popup.item(selection[0])['values'][0]

        # Get full item details
        item = self.inventory.get_item_by_id(item_id)
        if not item:
            self.show_error("Item not found.")
            return

        # Open edit dialog
        self.open_edit_item_dialog(item)

    def open_edit_item_dialog(self, item):
        """Open dialog to edit item."""
        dialog = tk.Toplevel(self.current_popup)
        dialog.title(f"Edit Item: {item['name']}")
        dialog.geometry("600x650")  # Slightly reduced height
        dialog.transient(self.current_popup)
        dialog.grab_set()
        dialog.configure(bg='white')

        # Center dialog
        self.center_dialog(dialog, 600, 650)

        main_frame = tk.Frame(dialog, bg='white', padx=30, pady=30)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="EDIT ITEM", font=('Segoe UI', 18, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 20))

        # Create a canvas with scrollbar
        canvas = tk.Canvas(main_frame, bg='white', highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='white')

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Form fields - changed from Text to Entry
        fields = [
            ("Item Name:", "name", item['name']),
            ("Description:", "description", item.get('description', '')),
            ("Category:", "category", item['category']),
            ("Quantity:", "quantity", str(item['quantity'])),
            ("Price ($):", "price", str(item['price'])),
            ("Min Stock Level:", "min_stock", str(item['min_stock_level'])),
            ("Supplier:", "supplier", item.get('supplier', '')),
            ("Location:", "location", item.get('location', '')),
            ("Reason for update:", "reason", "")
        ]

        self.edit_item_entries = {}

        for i, (label, field, default) in enumerate(fields):
            tk.Label(scrollable_frame, text=label, font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').grid(row=i, column=0, padx=10, pady=10, sticky='e')

            # All fields as Entry widgets now
            entry = tk.Entry(scrollable_frame, font=('Segoe UI', 11), width=40)
            entry.grid(row=i, column=1, padx=10, pady=10, sticky='w')
            if default:
                entry.insert(0, default)

            # Bind Enter key to next field
            entry.bind('<Return>', lambda e, next_idx=i + 1: self.focus_next_field(scrollable_frame, next_idx))

            if field == 'reason':
                tk.Label(scrollable_frame, text="*", font=('Segoe UI', 11),
                         bg='white', fg='red').grid(row=i, column=2, sticky='w')

            self.edit_item_entries[field] = entry

        # Add info about supplier sync
        tk.Label(scrollable_frame, text="Note: Changes to supplier or price will update all supplier records",
                 font=('Segoe UI', 10, 'italic'), bg='white', fg='#2e86c1').grid(
            row=len(fields), column=0, columnspan=2, padx=10, pady=15, sticky='w')

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Button frame
        button_frame = tk.Frame(main_frame, bg='white')
        button_frame.pack(pady=20)

        def save_changes():
            try:
                # Get reason from Entry widget
                reason = self.edit_item_entries['reason'].get().strip()
                if not reason and not self.auth.is_admin():
                    raise ValueError("Reason is required for this action")

                # Get description from Entry widget
                description = self.edit_item_entries['description'].get().strip()

                item_data = {
                    'name': self.edit_item_entries['name'].get(),
                    'description': description,
                    'category': self.edit_item_entries['category'].get(),
                    'quantity': self.edit_item_entries['quantity'].get(),
                    'price': self.edit_item_entries['price'].get(),
                    'min_stock_level': self.edit_item_entries['min_stock'].get(),
                    'supplier': self.edit_item_entries['supplier'].get(),
                    'location': self.edit_item_entries['location'].get()
                }

                success = self.inventory.update_item(item['id'], item_data, reason)
                if success:
                    self.show_info("✅ Item updated successfully!\n\nSupplier records have been synchronized.")
                    self.load_inventory_popup_data()
                    dialog.destroy()

            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(f"Error updating item: {str(e)}")

        save_btn = tk.Button(button_frame, text="💾 SAVE CHANGES",
                             font=('Segoe UI', 12, 'bold'),
                             bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                             command=save_changes, padx=30, pady=10)
        save_btn.pack(side=tk.LEFT, padx=10)

        # Bind Enter key to save button when in last field
        if 'reason' in self.edit_item_entries:
            self.edit_item_entries['reason'].bind('<Return>', lambda e: save_changes())

        cancel_btn = tk.Button(button_frame, text="CANCEL",
                               font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                               command=dialog.destroy, padx=30, pady=10)
        cancel_btn.pack(side=tk.LEFT, padx=10)

    def delete_selected_item(self):
        """Delete the selected item."""
        if not self.auth.is_admin():
            self.show_error("Only administrators can delete items.")
            return

        selection = self.inventory_tree_popup.selection()
        if not selection:
            self.show_warning("Please select an item to delete.")
            return

        item_id = self.inventory_tree_popup.item(selection[0])['values'][0]
        item_name = self.inventory_tree_popup.item(selection[0])['values'][1]

        # Ask for reason
        reason = simpledialog.askstring("Delete Item",
                                        f"Enter reason for deleting '{item_name}':",
                                        parent=self.current_popup)

        if reason is None:  # User cancelled
            return

        if self.ask_confirmation(f"Are you sure you want to delete '{item_name}'?"):
            try:
                self.inventory.delete_item(item_id, reason)
                self.show_info(f"✅ Item '{item_name}' deleted successfully!")
                self.load_inventory_popup_data()
            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(f"Error deleting item: {str(e)}")

    def load_inventory_popup_data(self):
        """Load inventory data for popup."""
        if not hasattr(self, 'inventory_tree_popup'):
            return

        for item in self.inventory_tree_popup.get_children():
            self.inventory_tree_popup.delete(item)

        # Get filters
        filters = {}
        if hasattr(self, 'category_var'):
            category_filter = self.category_var.get()
            if category_filter:
                filters['category'] = category_filter

        if hasattr(self, 'search_var'):
            search_filter = self.search_var.get()
            if search_filter:
                filters['name_like'] = search_filter

        try:
            items = self.inventory.get_all_items(filters)

            for item in items:
                values = (
                    item['id'],
                    item['name'],
                    item['category'],
                    item['quantity'],
                    f"${item['price']:.2f}",
                    item['min_stock_level'],
                    item.get('location', ''),
                    item.get('barcode', ''),
                    item.get('supplier', '')
                )

                # Color code low stock items
                tags = ()
                if item['quantity'] <= item['min_stock_level']:
                    tags = ('low_stock',)

                self.inventory_tree_popup.insert('', tk.END, values=values, tags=tags)

            self.inventory_tree_popup.tag_configure('low_stock', background='#ffcccc')

        except Exception as e:
            self.show_error(f"Error loading inventory: {str(e)}")

    def load_categories(self):
        """Load categories for filter dropdowns."""
        try:
            items = self.inventory.get_all_items()
            categories = sorted(
                set(item['category'] for item in items if item['category'] and item['category'].strip()))

            if hasattr(self, 'category_combo'):
                self.category_combo['values'] = categories

        except Exception as e:
            print(f"Error loading categories: {e}")

    def create_add_item_popup(self, parent):
        """Create add item popup."""
        # Main form container
        form_container = tk.Frame(parent, bg='white')
        form_container.pack(fill=tk.BOTH, expand=True)

        # Create a canvas with scrollbar
        canvas = tk.Canvas(form_container, bg='white', highlightthickness=0)
        scrollbar = ttk.Scrollbar(form_container, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='white')

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        fields = [
            ("Reason for adding (required):", "reason", True, False),  # Changed from is_text=True to False
            ("Item Name:", "name", True, False),
            ("Description:", "description", False, False),  # Changed from is_text=True to False
            ("Category:", "category", True, False),
            ("Quantity:", "quantity", True, False),
            ("Price ($):", "price", True, False),
            ("Min Stock Level:", "min_stock", True, False),
            ("Supplier:", "supplier", False, False),
            ("Location:", "location", False, False)
        ]

        self.add_item_entries = {}

        for i, (label, field, required, is_text) in enumerate(fields):
            tk.Label(scrollable_frame, text=label, font=('Segoe UI', 11),
                     bg='white', fg='#6a4334').grid(row=i, column=0, padx=10, pady=10, sticky='e')

            if is_text:
                entry = tk.Text(scrollable_frame, font=('Segoe UI', 11), width=40, height=3)
                entry.grid(row=i, column=1, padx=10, pady=10, sticky='w')
            else:
                entry = tk.Entry(scrollable_frame, font=('Segoe UI', 11), width=40)
                entry.grid(row=i, column=1, padx=10, pady=10, sticky='w')
                # Bind Enter key to next field for Entry widgets
                entry.bind('<Return>', lambda e, next_idx=i + 1: self.focus_next_field(scrollable_frame, next_idx))

            if required:
                tk.Label(scrollable_frame, text="*", font=('Segoe UI', 11),
                         bg='white', fg='red').grid(row=i, column=2, sticky='w')

            self.add_item_entries[field] = entry

        # Info about barcode
        tk.Label(scrollable_frame, text="Note: Barcode will be auto-generated with Item ID",
                 font=('Segoe UI', 10, 'italic'), bg='white', fg='#2e86c1').grid(
            row=len(fields), column=0, columnspan=2, padx=10, pady=15, sticky='w')

        # Set default values
        if 'min_stock' in self.add_item_entries:
            self.add_item_entries['min_stock'].insert(0, '10')
        if 'quantity' in self.add_item_entries:
            self.add_item_entries['quantity'].insert(0, '0')
        if 'price' in self.add_item_entries:
            self.add_item_entries['price'].insert(0, '0.00')

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Button frame
        button_frame = tk.Frame(parent, bg='white')
        button_frame.pack(pady=20)

        def add_item_action():
            try:
                # Get values from Entry widgets instead of Text widgets
                reason = self.add_item_entries['reason'].get().strip()
                if not reason and not self.auth.is_admin():
                    raise ValueError("Reason is required for this action")

                description = self.add_item_entries['description'].get().strip()

                item_data = {
                    'name': self.add_item_entries['name'].get(),
                    'description': description,
                    'category': self.add_item_entries['category'].get(),
                    'quantity': self.add_item_entries['quantity'].get(),
                    'price': self.add_item_entries['price'].get(),
                    'min_stock_level': self.add_item_entries['min_stock'].get(),
                    'supplier': self.add_item_entries['supplier'].get(),
                    'location': self.add_item_entries['location'].get()
                }

                item_id = self.inventory.add_item(item_data, reason, "NEW_ITEM")
                self.show_info(f"✅ Item added successfully!\n\n📋 Item ID: {item_id}\n🔖 Barcode: {item_id}")

                # Clear form
                self.clear_add_item_form()

            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(f"Error adding item: {str(e)}")

        add_btn = tk.Button(button_frame, text="➕ ADD ITEM",
                            font=('Segoe UI', 14, 'bold'),
                            bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                            command=add_item_action, padx=30, pady=10)
        add_btn.pack(side=tk.LEFT, padx=10)

        # Bind Enter key to add button when in last field
        if 'location' in self.add_item_entries:
            self.add_item_entries['location'].bind('<Return>', lambda e: add_item_action())

        clear_btn = tk.Button(button_frame, text="🗑️ CLEAR",
                              font=('Segoe UI', 14, 'bold'),
                              bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                              command=self.clear_add_item_form, padx=30, pady=10)
        clear_btn.pack(side=tk.LEFT, padx=10)

    def focus_next_field(self, parent, current_idx):
        """Focus on the next input field."""
        # Find the next entry widget
        entries = [widget for widget in parent.winfo_children() if isinstance(widget, tk.Entry)]
        if current_idx < len(entries):
            entries[current_idx].focus()
        return "break"

    def clear_add_item_form(self):
        """Clear add item form."""
        if hasattr(self, 'add_item_entries'):
            for field, entry in self.add_item_entries.items():
                if hasattr(entry, 'delete'):
                    if field == 'quantity':
                        entry.delete(0, tk.END)
                        entry.insert(0, '0')
                    elif field == 'price':
                        entry.delete(0, tk.END)
                        entry.insert(0, '0.00')
                    elif field == 'min_stock':
                        entry.delete(0, tk.END)
                        entry.insert(0, '10')
                    else:
                        entry.delete(0, tk.END)

    def create_add_existing_popup(self, parent):
        """Create add to existing item popup."""
        # Main form container
        form_container = tk.Frame(parent, bg='white')
        form_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Search frame
        search_frame = tk.LabelFrame(form_container, text="Search Item",
                                     font=('Segoe UI', 12, 'bold'),
                                     bg='white', fg='#6a4334', padx=20, pady=15)
        search_frame.pack(fill=tk.X, pady=(0, 20))

        # Method selection
        tk.Label(search_frame, text="Search by:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=0, column=0, padx=5, pady=5, sticky='e')

        self.existing_search_method = tk.StringVar(value='id')
        method_frame = tk.Frame(search_frame, bg='white')
        method_frame.grid(row=0, column=1, padx=5, pady=5, sticky='w')

        ttk.Radiobutton(method_frame, text="Item ID", variable=self.existing_search_method, value='id').pack(
            side=tk.LEFT, padx=5)
        ttk.Radiobutton(method_frame, text="Item Name", variable=self.existing_search_method, value='name').pack(
            side=tk.LEFT, padx=5)

        # Search entry
        tk.Label(search_frame, text="Search:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=1, column=0, padx=5, pady=5, sticky='e')
        self.existing_search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=self.existing_search_var,
                                font=('Segoe UI', 11), width=30)
        search_entry.grid(row=1, column=1, padx=5, pady=5, sticky='w')
        search_entry.bind('<Return>', lambda e: self.search_existing_item_popup())

        search_btn = tk.Button(search_frame, text="🔍 SEARCH",
                               font=('Segoe UI', 11, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                               command=self.search_existing_item_popup, padx=15, pady=5)
        search_btn.grid(row=1, column=2, padx=10, pady=5)

        # Item info display
        info_frame = tk.LabelFrame(form_container, text="Item Information",
                                   font=('Segoe UI', 12, 'bold'),
                                   bg='white', fg='#6a4334', padx=20, pady=15)
        info_frame.pack(fill=tk.X, pady=(0, 20))

        self.existing_item_info_text = tk.Text(info_frame, font=('Segoe UI', 11), height=5, width=70)
        self.existing_item_info_text.pack(fill=tk.X)
        self.existing_item_info_text.config(state=tk.DISABLED)

        # Item ID (hidden)
        self.selected_existing_item_id = tk.IntVar(value=0)

        # Details frame
        details_frame = tk.Frame(form_container, bg='white')
        details_frame.pack(fill=tk.X, pady=(0, 20))

        # Quantity
        tk.Label(details_frame, text="Quantity to add:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=0, column=0, padx=10, pady=8, sticky='e')
        self.quantity_to_add_entry = tk.Entry(details_frame, font=('Segoe UI', 11), width=15)
        self.quantity_to_add_entry.grid(row=0, column=1, padx=10, pady=8, sticky='w')
        self.quantity_to_add_entry.insert(0, '1')

        # Unit price (optional)
        tk.Label(details_frame, text="Unit Price ($):", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=0, column=2, padx=10, pady=8, sticky='e')
        self.unit_price_entry = tk.Entry(details_frame, font=('Segoe UI', 11), width=15)
        self.unit_price_entry.grid(row=0, column=3, padx=10, pady=8, sticky='w')

        # Invoice number (optional)
        tk.Label(details_frame, text="Invoice #:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=1, column=0, padx=10, pady=8, sticky='e')
        self.invoice_entry = tk.Entry(details_frame, font=('Segoe UI', 11), width=15)
        self.invoice_entry.grid(row=1, column=1, padx=10, pady=8, sticky='w')

        # Current quantity display
        self.current_qty_label = tk.Label(details_frame, text="Current: 0", font=('Segoe UI', 11),
                                          foreground='blue', bg='white')
        self.current_qty_label.grid(row=0, column=4, padx=20, pady=8, sticky='w')

        # Reason
        tk.Label(details_frame, text="Reason (required):", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=2, column=0, padx=10, pady=8, sticky='ne')
        self.existing_reason_entry = tk.Text(details_frame, font=('Segoe UI', 11), width=40, height=3)
        self.existing_reason_entry.grid(row=2, column=1, columnspan=3, padx=10, pady=8, sticky='w')

        # Button frame
        button_frame = tk.Frame(form_container, bg='white')
        button_frame.pack(pady=20)

        def add_to_existing_action():
            try:
                item_id = self.selected_existing_item_id.get()
                if item_id == 0:
                    raise ValueError("Please select an item first")

                quantity = self.validator.validate_integer(self.quantity_to_add_entry.get(), "Quantity to add", 1,
                                                           1000000)

                unit_price = None
                if self.unit_price_entry.get().strip():
                    unit_price = self.validator.validate_float(self.unit_price_entry.get(), "Unit price", 0, 1000000)

                invoice = self.invoice_entry.get().strip()
                reason = self.existing_reason_entry.get('1.0', tk.END).strip()

                if not reason and not self.auth.is_admin():
                    raise ValueError("Reason is required for this action")

                success, new_qty = self.inventory.add_to_existing_item(item_id, quantity, reason, unit_price, invoice)
                if success:
                    self.show_info(f"✅ Quantity added successfully!\n\n📦 New quantity: {new_qty}")

                    # Clear form
                    self.clear_add_existing_form()

            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(f"Error adding quantity: {str(e)}")

        add_btn = tk.Button(button_frame, text="📈 ADD QUANTITY",
                            font=('Segoe UI', 14, 'bold'),
                            bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                            command=add_to_existing_action, padx=30, pady=10)
        add_btn.pack(side=tk.LEFT, padx=10)

        # Bind Enter key to add button
        self.existing_reason_entry.bind('<Return>', lambda e: add_to_existing_action())

        clear_btn = tk.Button(button_frame, text="🗑️ CLEAR",
                              font=('Segoe UI', 14, 'bold'),
                              bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                              command=self.clear_add_existing_form, padx=30, pady=10)
        clear_btn.pack(side=tk.LEFT, padx=10)

    def search_existing_item_popup(self):
        """Search for existing item in popup."""
        try:
            search_value = self.existing_search_var.get().strip()
            if not search_value:
                raise ValueError("Please enter an item ID or name to search")

            items = []

            if self.existing_search_method.get() == 'id':
                item_id = self.validator.validate_integer(search_value, "Item ID", 1)
                item = self.inventory.get_item_by_id(item_id)
                if item:
                    items = [item]
                else:
                    raise ValueError(f"No item found with ID: {item_id}")
            else:
                # Search by name
                items = self.inventory.get_item_by_name(search_value)
                if not items:
                    raise ValueError(f"No items found with name containing: '{search_value}'")
                elif len(items) > 1:
                    self.show_multiple_items_popup(items)
                    return

            # Single item found
            self.display_existing_item(items[0])

        except ValueError as e:
            self.show_error(str(e))
        except Exception as e:
            self.show_error(f"Error searching item: {str(e)}")

    def show_multiple_items_popup(self, items):
        """Show multiple items selection popup."""
        dialog = tk.Toplevel(self.current_popup)
        dialog.title("Select Item")
        dialog.geometry("600x400")
        dialog.transient(self.current_popup)
        dialog.grab_set()
        dialog.configure(bg='white')

        # Center dialog
        self.center_dialog(dialog, 600, 400)

        # Treeview for items
        tree_frame = tk.Frame(dialog, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        v_scrollbar = ttk.Scrollbar(tree_frame)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ('ID', 'Name', 'Category', 'Quantity', 'Price', 'Supplier')
        tree = ttk.Treeview(tree_frame, columns=columns, yscrollcommand=v_scrollbar.set, selectmode='browse')
        v_scrollbar.config(command=tree.yview)

        for col in columns:
            tree.heading(col, text=col, anchor=tk.W)
            tree.column(col, width=100, minwidth=80)

        tree.pack(fill=tk.BOTH, expand=True)

        # Add items
        for item in items:
            values = (
                item['id'],
                item['name'],
                item['category'],
                item['quantity'],
                f"${item['price']:.2f}",
                item.get('supplier', '')
            )
            tree.insert('', tk.END, values=values)

        # Button frame
        button_frame = tk.Frame(dialog, bg='white')
        button_frame.pack(fill=tk.X, padx=10, pady=10)

        def select_item():
            selection = tree.selection()
            if not selection:
                self.show_error("Please select an item")
                return

            item_id = tree.item(selection[0])['values'][0]
            selected_item = None
            for item in items:
                if item['id'] == item_id:
                    selected_item = item
                    break

            if selected_item:
                self.display_existing_item(selected_item)
                dialog.destroy()

        select_btn = tk.Button(button_frame, text="SELECT",
                               font=('Segoe UI', 12, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                               command=select_item, padx=20, pady=10)
        select_btn.pack(side=tk.LEFT)

        cancel_btn = tk.Button(button_frame, text="CANCEL",
                               font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                               command=dialog.destroy, padx=20, pady=10)
        cancel_btn.pack(side=tk.LEFT, padx=10)

    def display_existing_item(self, item):
        """Display existing item details."""
        self.selected_existing_item_id.set(item['id'])

        info_text = f"ID: {item['id']}\n"
        info_text += f"Name: {item['name']}\n"
        info_text += f"Category: {item['category']}\n"
        info_text += f"Current Quantity: {item['quantity']}\n"
        info_text += f"Price: ${item['price']:.2f}\n"
        info_text += f"Supplier: {item.get('supplier', 'N/A')}\n"
        info_text += f"Location: {item.get('location', 'N/A')}"

        self.existing_item_info_text.config(state=tk.NORMAL)
        self.existing_item_info_text.delete('1.0', tk.END)
        self.existing_item_info_text.insert('1.0', info_text)
        self.existing_item_info_text.config(state=tk.DISABLED)

        self.current_qty_label.config(text=f"Current: {item['quantity']}")
        self.quantity_to_add_entry.delete(0, tk.END)
        self.quantity_to_add_entry.insert(0, '1')
        self.unit_price_entry.delete(0, tk.END)
        self.unit_price_entry.insert(0, str(item['price']))

    def clear_add_existing_form(self):
        """Clear add to existing form."""
        self.existing_search_var.set('')
        self.selected_existing_item_id.set(0)
        self.existing_item_info_text.config(state=tk.NORMAL)
        self.existing_item_info_text.delete('1.0', tk.END)
        self.existing_item_info_text.config(state=tk.DISABLED)
        self.quantity_to_add_entry.delete(0, tk.END)
        self.quantity_to_add_entry.insert(0, '1')
        self.unit_price_entry.delete(0, tk.END)
        self.invoice_entry.delete(0, tk.END)
        self.existing_reason_entry.delete('1.0', tk.END)
        self.current_qty_label.config(text="Current: 0")

    def create_take_product_popup(self, parent):
        """Create take product popup."""
        # Main form container
        form_container = tk.Frame(parent, bg='white')
        form_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Search frame
        search_frame = tk.LabelFrame(form_container, text="Select Item",
                                     font=('Segoe UI', 12, 'bold'),
                                     bg='white', fg='#6a4334', padx=20, pady=15)
        search_frame.pack(fill=tk.X, pady=(0, 20))

        # Method selection
        tk.Label(search_frame, text="Select by:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=0, column=0, padx=5, pady=5, sticky='e')

        self.take_search_method = tk.StringVar(value='id')
        method_frame = tk.Frame(search_frame, bg='white')
        method_frame.grid(row=0, column=1, padx=5, pady=5, sticky='w')

        ttk.Radiobutton(method_frame, text="Item ID", variable=self.take_search_method, value='id').pack(side=tk.LEFT,
                                                                                                         padx=5)
        ttk.Radiobutton(method_frame, text="Item Name", variable=self.take_search_method, value='name').pack(
            side=tk.LEFT, padx=5)

        # Search entry
        tk.Label(search_frame, text="Search:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=1, column=0, padx=5, pady=5, sticky='e')
        self.take_search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=self.take_search_var,
                                font=('Segoe UI', 11), width=30)
        search_entry.grid(row=1, column=1, padx=5, pady=5, sticky='w')
        search_entry.bind('<Return>', lambda e: self.search_take_item())

        search_btn = tk.Button(search_frame, text="🔍 SEARCH",
                               font=('Segoe UI', 11, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                               command=self.search_take_item, padx=15, pady=5)
        search_btn.grid(row=1, column=2, padx=10, pady=5)

        # Item info display
        info_frame = tk.LabelFrame(form_container, text="Item Information",
                                   font=('Segoe UI', 12, 'bold'),
                                   bg='white', fg='#6a4334', padx=20, pady=15)
        info_frame.pack(fill=tk.X, pady=(0, 20))

        self.take_item_info_text = tk.Text(info_frame, font=('Segoe UI', 11), height=5, width=70)
        self.take_item_info_text.pack(fill=tk.X)
        self.take_item_info_text.config(state=tk.DISABLED)

        # Item ID (hidden)
        self.selected_take_item_id = tk.IntVar(value=0)

        # Details frame
        details_frame = tk.Frame(form_container, bg='white')
        details_frame.pack(fill=tk.X, pady=(0, 20))

        # Quantity
        tk.Label(details_frame, text="Quantity to take:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=0, column=0, padx=10, pady=8, sticky='e')
        self.quantity_take_entry = tk.Entry(details_frame, font=('Segoe UI', 11), width=15)
        self.quantity_take_entry.grid(row=0, column=1, padx=10, pady=8, sticky='w')
        self.quantity_take_entry.insert(0, '1')

        # Available quantity display
        self.available_qty_label = tk.Label(details_frame, text="Available: 0", font=('Segoe UI', 11),
                                            foreground='blue', bg='white')
        self.available_qty_label.grid(row=0, column=2, padx=20, pady=8, sticky='w')

        # Reason
        tk.Label(details_frame, text="Reason (required):", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=1, column=0, padx=10, pady=8, sticky='ne')
        self.take_reason_entry = tk.Text(details_frame, font=('Segoe UI', 11), width=40, height=3)
        self.take_reason_entry.grid(row=1, column=1, columnspan=2, padx=10, pady=8, sticky='w')

        # Button frame
        button_frame = tk.Frame(form_container, bg='white')
        button_frame.pack(pady=20)

        def take_product_action():
            try:
                item_id = self.selected_take_item_id.get()
                if item_id == 0:
                    raise ValueError("Please select an item first")

                quantity = self.validator.validate_integer(self.quantity_take_entry.get(), "Quantity to take", 1,
                                                           1000000)
                reason = self.take_reason_entry.get('1.0', tk.END).strip()

                if not reason:
                    raise ValueError("Reason is required for taking a product")

                success = self.inventory.take_product(item_id, quantity, reason)
                if success:
                    self.show_info("✅ Product taken successfully!")

                    # Clear form
                    self.clear_take_form()

            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(f"Error taking product: {str(e)}")

        take_btn = tk.Button(button_frame, text="🚚 TAKE PRODUCT",
                             font=('Segoe UI', 14, 'bold'),
                             bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                             command=take_product_action, padx=30, pady=10)
        take_btn.pack(side=tk.LEFT, padx=10)

        # Bind Enter key to take button
        self.take_reason_entry.bind('<Return>', lambda e: take_product_action())

        clear_btn = tk.Button(button_frame, text="🗑️ CLEAR",
                              font=('Segoe UI', 14, 'bold'),
                              bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                              command=self.clear_take_form, padx=30, pady=10)
        clear_btn.pack(side=tk.LEFT, padx=10)

    def search_take_item(self):
        """Search for item to take."""
        try:
            search_value = self.take_search_var.get().strip()
            if not search_value:
                raise ValueError("Please enter an item ID or name to search")

            items = []

            if self.take_search_method.get() == 'id':
                item_id = self.validator.validate_integer(search_value, "Item ID", 1)
                item = self.inventory.get_item_by_id(item_id)
                if item:
                    items = [item]
                else:
                    raise ValueError(f"No item found with ID: {item_id}")
            else:
                # Search by name
                items = self.inventory.get_item_by_name(search_value)
                if not items:
                    raise ValueError(f"No items found with name containing: '{search_value}'")
                elif len(items) > 1:
                    self.show_multiple_take_items_popup(items)
                    return

            # Single item found
            self.display_take_item(items[0])

        except ValueError as e:
            self.show_error(str(e))
        except Exception as e:
            self.show_error(f"Error searching item: {str(e)}")

    def show_multiple_take_items_popup(self, items):
        """Show multiple items selection for taking."""
        dialog = tk.Toplevel(self.current_popup)
        dialog.title("Select Item to Take")
        dialog.geometry("600x400")
        dialog.transient(self.current_popup)
        dialog.grab_set()
        dialog.configure(bg='white')

        # Center dialog
        self.center_dialog(dialog, 600, 400)

        # Treeview for items
        tree_frame = tk.Frame(dialog, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        v_scrollbar = ttk.Scrollbar(tree_frame)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ('ID', 'Name', 'Category', 'Quantity', 'Price', 'Supplier')
        tree = ttk.Treeview(tree_frame, columns=columns, yscrollcommand=v_scrollbar.set, selectmode='browse')
        v_scrollbar.config(command=tree.yview)

        for col in columns:
            tree.heading(col, text=col, anchor=tk.W)
            tree.column(col, width=100, minwidth=80)

        tree.pack(fill=tk.BOTH, expand=True)

        # Add items
        for item in items:
            values = (
                item['id'],
                item['name'],
                item['category'],
                item['quantity'],
                f"${item['price']:.2f}",
                item.get('supplier', '')
            )
            tree.insert('', tk.END, values=values)

        # Button frame
        button_frame = tk.Frame(dialog, bg='white')
        button_frame.pack(fill=tk.X, padx=10, pady=10)

        def select_item():
            selection = tree.selection()
            if not selection:
                self.show_error("Please select an item")
                return

            item_id = tree.item(selection[0])['values'][0]
            selected_item = None
            for item in items:
                if item['id'] == item_id:
                    selected_item = item
                    break

            if selected_item:
                self.display_take_item(selected_item)
                dialog.destroy()

        select_btn = tk.Button(button_frame, text="SELECT",
                               font=('Segoe UI', 12, 'bold'),
                               bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                               command=select_item, padx=20, pady=10)
        select_btn.pack(side=tk.LEFT)

        cancel_btn = tk.Button(button_frame, text="CANCEL",
                               font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                               command=dialog.destroy, padx=20, pady=10)
        cancel_btn.pack(side=tk.LEFT, padx=10)

    def display_take_item(self, item):
        """Display item for taking."""
        self.selected_take_item_id.set(item['id'])

        info_text = f"ID: {item['id']}\n"
        info_text += f"Name: {item['name']}\n"
        info_text += f"Category: {item['category']}\n"
        info_text += f"Available Quantity: {item['quantity']}\n"
        info_text += f"Price: ${item['price']:.2f}\n"
        info_text += f"Location: {item.get('location', 'N/A')}"

        self.take_item_info_text.config(state=tk.NORMAL)
        self.take_item_info_text.delete('1.0', tk.END)
        self.take_item_info_text.insert('1.0', info_text)
        self.take_item_info_text.config(state=tk.DISABLED)

        self.available_qty_label.config(text=f"Available: {item['quantity']}")
        self.quantity_take_entry.delete(0, tk.END)
        self.quantity_take_entry.insert(0, '1')

    def clear_take_form(self):
        """Clear take product form."""
        self.take_search_var.set('')
        self.selected_take_item_id.set(0)
        self.take_item_info_text.config(state=tk.NORMAL)
        self.take_item_info_text.delete('1.0', tk.END)
        self.take_item_info_text.config(state=tk.DISABLED)
        self.quantity_take_entry.delete(0, tk.END)
        self.quantity_take_entry.insert(0, '1')
        self.take_reason_entry.delete('1.0', tk.END)
        self.available_qty_label.config(text="Available: 0")

    def create_low_stock_popup(self, parent):
        """Create low stock alerts popup."""
        # Treeview frame
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        # Create treeview with scrollbars
        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        columns = ('ID', 'Name', 'Category', 'Current Qty', 'Min Qty', 'Difference', 'Status', 'Location')
        self.low_stock_tree_popup = ttk.Treeview(tree_container, columns=columns,
                                                 yscrollcommand=v_scrollbar.set,
                                                 xscrollcommand=h_scrollbar.set,
                                                 height=15)

        v_scrollbar.config(command=self.low_stock_tree_popup.yview)
        h_scrollbar.config(command=self.low_stock_tree_popup.xview)

        for col in columns:
            self.low_stock_tree_popup.heading(col, text=col, anchor=tk.W)
            self.low_stock_tree_popup.column(col, width=100, minwidth=80)

        self.low_stock_tree_popup.pack(fill=tk.BOTH, expand=True)

        # Status label
        status_frame = tk.Frame(parent, bg='white')
        status_frame.pack(fill=tk.X, pady=(10, 0))

        self.low_stock_status = tk.Label(status_frame, text="", font=('Segoe UI', 11),
                                         bg='white', fg='#6a4334')
        self.low_stock_status.pack(side=tk.LEFT, padx=5, pady=5)

        refresh_btn = tk.Button(status_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_low_stock_popup_data, padx=15, pady=5)
        refresh_btn.pack(side=tk.RIGHT, padx=5, pady=5)

        # Load data
        self.load_low_stock_popup_data()

    def load_low_stock_popup_data(self):
        """Load low stock data for popup."""
        if not hasattr(self, 'low_stock_tree_popup'):
            return

        for item in self.low_stock_tree_popup.get_children():
            self.low_stock_tree_popup.delete(item)

        try:
            items = self.inventory.get_low_stock_items()

            critical_count = 0
            warning_count = 0

            for item in items:
                diff = item['quantity'] - item['min_stock_level']
                if item['quantity'] == 0:
                    status = "CRITICAL"
                    tags = ('critical',)
                    critical_count += 1
                else:
                    status = "LOW"
                    tags = ('warning',)
                    warning_count += 1

                values = (
                    item['id'],
                    item['name'],
                    item['category'],
                    item['quantity'],
                    item['min_stock_level'],
                    diff,
                    status,
                    item.get('location', '')
                )

                self.low_stock_tree_popup.insert('', tk.END, values=values, tags=tags)

            self.low_stock_tree_popup.tag_configure('critical', background='#ff9999')
            self.low_stock_tree_popup.tag_configure('warning', background='#ffff99')

            status_text = f"📊 Critical: {critical_count} | Warning: {warning_count} | Total: {len(items)}"
            self.low_stock_status.config(text=status_text)

        except Exception as e:
            self.show_error(f"Error loading low stock items: {str(e)}")

    def create_history_popup(self, parent):
        """Create inventory history popup."""
        # Filter frame
        filter_frame = tk.Frame(parent, bg='white')
        filter_frame.pack(fill=tk.X, pady=(0, 20))

        tk.Label(filter_frame, text="Item ID (optional):", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.history_item_id = tk.Entry(filter_frame, font=('Segoe UI', 11), width=15)
        self.history_item_id.pack(side=tk.LEFT, padx=5)
        self.history_item_id.bind('<Return>', lambda e: self.load_history_popup_data())

        load_btn = tk.Button(filter_frame, text="🔍 LOAD",
                             font=('Segoe UI', 11, 'bold'),
                             bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                             command=self.load_history_popup_data, padx=15, pady=5)
        load_btn.pack(side=tk.LEFT, padx=20)

        # Treeview
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        columns = ('Timestamp', 'Item', 'User', 'Action', 'Reason', 'Old Qty', 'New Qty')
        self.history_tree_popup = ttk.Treeview(tree_container, columns=columns,
                                               yscrollcommand=v_scrollbar.set,
                                               xscrollcommand=h_scrollbar.set,
                                               height=15)

        v_scrollbar.config(command=self.history_tree_popup.yview)
        h_scrollbar.config(command=self.history_tree_popup.xview)

        for col in columns:
            self.history_tree_popup.heading(col, text=col, anchor=tk.W)
            self.history_tree_popup.column(col, width=120, minwidth=80)

        self.history_tree_popup.pack(fill=tk.BOTH, expand=True)

        # Load data
        self.load_history_popup_data()

    def load_history_popup_data(self):
        """Load history data for popup."""
        if not hasattr(self, 'history_tree_popup'):
            return

        for item in self.history_tree_popup.get_children():
            self.history_tree_popup.delete(item)

        try:
            item_id = None
            history_item_id = self.history_item_id.get().strip()
            if history_item_id:
                item_id = self.validator.validate_integer(history_item_id, "Item ID", 1)

            history = self.inventory.get_inventory_history(item_id, 100)

            for record in history:
                timestamp = record['timestamp'].split('.')[0] if record['timestamp'] else ''
                reason = record.get('reason', '') or ''
                values = (
                    timestamp,
                    record['name'],
                    record['username'],
                    record['action'],
                    reason[:50] + '...' if len(reason) > 50 else reason,
                    record['old_quantity'],
                    record['new_quantity']
                )

                tags = ()
                if record['action'] == 'CREATE':
                    tags = ('create',)
                elif record['action'] == 'DELETE':
                    tags = ('delete',)
                elif record['action'] == 'USAGE':
                    tags = ('usage',)
                elif record['action'] == 'STOCK_ADDITION':
                    tags = ('stock_addition',)

                self.history_tree_popup.insert('', tk.END, values=values, tags=tags)

            self.history_tree_popup.tag_configure('create', background='#ccffcc')
            self.history_tree_popup.tag_configure('delete', background='#ffcccc')
            self.history_tree_popup.tag_configure('usage', background='#ccccff')
            self.history_tree_popup.tag_configure('stock_addition', background='#ffffcc')

        except ValueError as e:
            self.show_error(str(e))
        except Exception as e:
            self.show_error(f"Error loading history: {str(e)}")

    def create_usage_popup(self, parent):
        """Create product usage popup."""
        # Treeview
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        columns = ('Date', 'Item', 'User', 'Quantity Taken', 'Reason')
        self.usage_tree_popup = ttk.Treeview(tree_container, columns=columns,
                                             yscrollcommand=v_scrollbar.set,
                                             xscrollcommand=h_scrollbar.set,
                                             height=15)

        v_scrollbar.config(command=self.usage_tree_popup.yview)
        h_scrollbar.config(command=self.usage_tree_popup.xview)

        for col in columns:
            self.usage_tree_popup.heading(col, text=col, anchor=tk.W)
            self.usage_tree_popup.column(col, width=130, minwidth=100)

        self.usage_tree_popup.pack(fill=tk.BOTH, expand=True)

        # Refresh button
        refresh_btn = tk.Button(parent, text="🔄 REFRESH",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_usage_popup_data, padx=15, pady=5)
        refresh_btn.pack(pady=(10, 0))

        # Load data
        self.load_usage_popup_data()

    def load_usage_popup_data(self):
        """Load usage data for popup."""
        if not hasattr(self, 'usage_tree_popup'):
            return

        for item in self.usage_tree_popup.get_children():
            self.usage_tree_popup.delete(item)

        try:
            usage = self.inventory.get_product_usage(limit=100)

            for record in usage:
                date = record['usage_date'].split('.')[0] if record['usage_date'] else ''
                values = (
                    date,
                    record['name'],
                    record['username'],
                    record['quantity_taken'],
                    record['reason']
                )
                self.usage_tree_popup.insert('', tk.END, values=values)

        except Exception as e:
            self.show_error(f"Error loading product usage: {str(e)}")

    def create_users_popup(self, parent):
        """Create user management popup."""
        # Button frame
        button_frame = tk.Frame(parent, bg='white')
        button_frame.pack(fill=tk.X, pady=(0, 20))

        add_user_btn = tk.Button(button_frame, text="➕ ADD NEW USER",
                                 font=('Segoe UI', 11, 'bold'),
                                 bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                                 command=self.open_add_user_dialog_popup, padx=20, pady=8)
        add_user_btn.pack(side=tk.LEFT, padx=5)

        delete_user_btn = tk.Button(button_frame, text="🗑️ DELETE SELECTED",
                                    font=('Segoe UI', 11, 'bold'),
                                    bg='#e74c3c', fg='black', relief='flat', cursor='hand2',
                                    command=self.delete_selected_user_popup, padx=20, pady=8)
        delete_user_btn.pack(side=tk.LEFT, padx=5)

        refresh_btn = tk.Button(button_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#3498db', fg='black', relief='flat', cursor='hand2',
                                command=self.load_users_popup_data, padx=20, pady=8)
        refresh_btn.pack(side=tk.RIGHT, padx=5)

        # Treeview
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ('ID', 'Username', 'Role', 'Email', 'Created')
        self.users_tree_popup = ttk.Treeview(tree_container, columns=columns,
                                             yscrollcommand=v_scrollbar.set,
                                             height=15)

        v_scrollbar.config(command=self.users_tree_popup.yview)

        for col in columns:
            self.users_tree_popup.heading(col, text=col, anchor=tk.W)
            self.users_tree_popup.column(col, width=120, minwidth=80)

        self.users_tree_popup.pack(fill=tk.BOTH, expand=True)

        # Load data
        self.load_users_popup_data()

    def load_users_popup_data(self):
        """Load users data for popup."""
        if not hasattr(self, 'users_tree_popup'):
            return

        for item in self.users_tree_popup.get_children():
            self.users_tree_popup.delete(item)

        try:
            users = self.inventory.get_all_users()

            for user in users:
                values = (
                    user['id'],
                    user['username'],
                    user['role'],
                    user['email'],
                    user['created_at'].split()[0] if user['created_at'] else ''
                )
                self.users_tree_popup.insert('', tk.END, values=values)

        except Exception as e:
            self.show_error(f"Error loading users: {str(e)}")

    def open_add_user_dialog_popup(self):
        """Open add user dialog from popup."""
        dialog = tk.Toplevel(self.current_popup)
        dialog.title("Add New User - The Evaani Hotel")
        dialog.geometry("500x450")
        dialog.transient(self.current_popup)
        dialog.grab_set()
        dialog.configure(bg='white')

        # Center dialog
        self.center_dialog(dialog, 500, 450)

        main_frame = tk.Frame(dialog, bg='white', padx=30, pady=30)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="ADD NEW USER", font=('Segoe UI', 18, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 30))

        form_frame = tk.Frame(main_frame, bg='white')
        form_frame.pack(fill=tk.BOTH, expand=True)

        # Username
        tk.Label(form_frame, text="Username:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=0, column=0, padx=10, pady=10, sticky='e')
        username_entry = tk.Entry(form_frame, font=('Segoe UI', 11), width=30)
        username_entry.grid(row=0, column=1, padx=10, pady=10, sticky='w')
        username_entry.bind('<Return>', lambda e: password_entry.focus())

        # Password
        tk.Label(form_frame, text="Password:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=1, column=0, padx=10, pady=10, sticky='e')
        password_entry = tk.Entry(form_frame, font=('Segoe UI', 11), width=30, show="*")
        password_entry.grid(row=1, column=1, padx=10, pady=10, sticky='w')
        password_entry.bind('<Return>', lambda e: confirm_entry.focus())

        # Confirm Password
        tk.Label(form_frame, text="Confirm Password:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=2, column=0, padx=10, pady=10, sticky='e')
        confirm_entry = tk.Entry(form_frame, font=('Segoe UI', 11), width=30, show="*")
        confirm_entry.grid(row=2, column=1, padx=10, pady=10, sticky='w')
        confirm_entry.bind('<Return>', lambda e: role_combo.focus())

        # Role
        tk.Label(form_frame, text="Role:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=3, column=0, padx=10, pady=10, sticky='e')
        role_var = tk.StringVar(value='user')
        role_combo = ttk.Combobox(form_frame, textvariable=role_var,
                                  values=['admin', 'user'], width=28, state='readonly',
                                  font=('Segoe UI', 11))
        role_combo.grid(row=3, column=1, padx=10, pady=10, sticky='w')
        role_combo.bind('<<ComboboxSelected>>', lambda e: email_entry.focus())

        # Email
        tk.Label(form_frame, text="Email:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=4, column=0, padx=10, pady=10, sticky='e')
        email_entry = tk.Entry(form_frame, font=('Segoe UI', 11), width=30)
        email_entry.grid(row=4, column=1, padx=10, pady=10, sticky='w')
        email_entry.bind('<Return>', lambda e: add_user_action())

        def add_user_action():
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
                    raise ValueError("Passwords do not match!")
                if len(password) < 4:
                    raise ValueError("Password must be at least 4 characters")

                self.inventory.add_user(username, password, role, email)

                self.show_info("✅ User added successfully!")
                self.load_users_popup_data()
                dialog.destroy()

            except ValueError as e:
                self.show_error(str(e))

        button_frame = tk.Frame(form_frame, bg='white')
        button_frame.grid(row=5, column=0, columnspan=2, pady=20)

        add_btn = tk.Button(button_frame, text="ADD USER", font=('Segoe UI', 12, 'bold'),
                            bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                            command=add_user_action, padx=30, pady=10)
        add_btn.pack(side=tk.LEFT, padx=10)

        cancel_btn = tk.Button(button_frame, text="CANCEL", font=('Segoe UI', 12, 'bold'),
                               bg='#95a5a6', fg='black', relief='flat', cursor='hand2',
                               command=dialog.destroy, padx=30, pady=10)
        cancel_btn.pack(side=tk.LEFT, padx=10)

    def delete_selected_user_popup(self):
        """Delete selected user from popup."""
        selection = self.users_tree_popup.selection()
        if not selection:
            self.show_warning("Please select a user to delete.")
            return

        user_id = self.users_tree_popup.item(selection[0])['values'][0]
        username = self.users_tree_popup.item(selection[0])['values'][1]

        if self.ask_confirmation(f"Are you sure you want to delete user '{username}'?"):
            try:
                self.inventory.delete_user(user_id)
                self.show_info(f"✅ User '{username}' deleted successfully!")
                self.load_users_popup_data()
            except ValueError as e:
                self.show_error(str(e))
            except Exception as e:
                self.show_error(f"Error deleting user: {str(e)}")

    def create_stock_additions_popup(self, parent):
        """Create stock additions popup."""
        # Filter frame
        filter_frame = tk.Frame(parent, bg='white')
        filter_frame.pack(fill=tk.X, pady=(0, 20))

        tk.Label(filter_frame, text="Filter by Type:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=5)
        self.stock_type_filter_popup = tk.StringVar(value='ALL')
        type_combo = ttk.Combobox(filter_frame, textvariable=self.stock_type_filter_popup,
                                  values=['ALL', 'NEW_ITEM', 'EXISTING_ITEM'], width=15,
                                  state='readonly', font=('Segoe UI', 11))
        type_combo.pack(side=tk.LEFT, padx=5)

        load_btn = tk.Button(filter_frame, text="🔍 LOAD",
                             font=('Segoe UI', 11, 'bold'),
                             bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                             command=self.load_stock_additions_popup_data, padx=15, pady=5)
        load_btn.pack(side=tk.LEFT, padx=20)

        # Treeview
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        columns = ('Date', 'Item', 'Category', 'User', 'Quantity Added', 'Type', 'Reason')
        self.stock_additions_tree_popup = ttk.Treeview(tree_container, columns=columns,
                                                       yscrollcommand=v_scrollbar.set,
                                                       xscrollcommand=h_scrollbar.set,
                                                       height=15)

        v_scrollbar.config(command=self.stock_additions_tree_popup.yview)
        h_scrollbar.config(command=self.stock_additions_tree_popup.xview)

        for col in columns:
            self.stock_additions_tree_popup.heading(col, text=col, anchor=tk.W)
            self.stock_additions_tree_popup.column(col, width=120, minwidth=80)

        self.stock_additions_tree_popup.pack(fill=tk.BOTH, expand=True)

        # Load data
        self.load_stock_additions_popup_data()

    def load_stock_additions_popup_data(self):
        """Load stock additions data for popup."""
        if not hasattr(self, 'stock_additions_tree_popup'):
            return

        for item in self.stock_additions_tree_popup.get_children():
            self.stock_additions_tree_popup.delete(item)

        try:
            additions = self.inventory.get_stock_additions(100)

            for record in additions:
                if hasattr(self, 'stock_type_filter_popup') and \
                        self.stock_type_filter_popup.get() != 'ALL' and \
                        record['addition_type'] != self.stock_type_filter_popup.get():
                    continue

                date = record['added_at'].split('.')[0] if record['added_at'] else ''
                type_text = "New Item" if record['addition_type'] == 'NEW_ITEM' else "Existing Item"

                values = (
                    date,
                    record['name'],
                    record['category'],
                    record['username'],
                    record['quantity_added'],
                    type_text,
                    record.get('reason', '')[:50] + '...' if len(record.get('reason', '')) > 50 else record.get(
                        'reason', '')
                )

                tags = ('new_item',) if record['addition_type'] == 'NEW_ITEM' else ('existing_item',)
                self.stock_additions_tree_popup.insert('', tk.END, values=values, tags=tags)

            self.stock_additions_tree_popup.tag_configure('new_item', background='#ccffcc')
            self.stock_additions_tree_popup.tag_configure('existing_item', background='#ffffcc')

        except Exception as e:
            self.show_error(f"Error loading stock additions: {str(e)}")

    def create_supplier_data_popup(self, parent):
        """Create supplier data popup with comprehensive reporting."""
        # Notebook for tabs
        notebook = ttk.Notebook(parent)
        notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: Supplier Summary
        summary_frame = tk.Frame(notebook, bg='white')
        notebook.add(summary_frame, text='Supplier Summary')
        self.create_supplier_summary_tab(summary_frame)

        # Tab 2: Purchase History
        history_frame = tk.Frame(notebook, bg='white')
        notebook.add(history_frame, text='Purchase History')
        self.create_supplier_purchase_history_tab(history_frame)

    def create_supplier_summary_tab(self, parent):
        """Create supplier summary tab."""
        # Title
        tk.Label(parent, text="SUPPLIER PURCHASE SUMMARY", font=('Segoe UI', 14, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(10, 20))

        # Treeview
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ('Supplier', 'Purchase Count', 'Total Quantity', 'Total Spent ($)', 'Avg Price ($)', 'Last Purchase')
        self.supplier_summary_tree = ttk.Treeview(tree_container, columns=columns,
                                                  yscrollcommand=v_scrollbar.set,
                                                  height=15)

        v_scrollbar.config(command=self.supplier_summary_tree.yview)

        for col in columns:
            self.supplier_summary_tree.heading(col, text=col, anchor=tk.W)
            self.supplier_summary_tree.column(col, width=140, minwidth=100)

        self.supplier_summary_tree.pack(fill=tk.BOTH, expand=True)

        # Refresh button
        refresh_btn = tk.Button(parent, text="🔄 REFRESH",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                                command=self.load_supplier_summary_data, padx=20, pady=10)
        refresh_btn.pack(pady=10)

        # Load data
        self.load_supplier_summary_data()

    def load_supplier_summary_data(self):
        """Load supplier summary data."""
        if not hasattr(self, 'supplier_summary_tree'):
            return

        for item in self.supplier_summary_tree.get_children():
            self.supplier_summary_tree.delete(item)

        try:
            summary = self.inventory.get_supplier_summary()

            for record in summary:
                values = (
                    record['supplier_name'],
                    record['purchase_count'],
                    record['total_quantity'],
                    f"${record['total_spent']:.2f}",
                    f"${record['avg_price']:.2f}",
                    record['last_purchase'].split()[0] if record['last_purchase'] else ''
                )
                self.supplier_summary_tree.insert('', tk.END, values=values)

        except Exception as e:
            self.show_error(f"Error loading supplier summary: {str(e)}")

    def create_supplier_purchase_history_tab(self, parent):
        """Create supplier purchase history tab."""
        # Filter frame
        filter_frame = tk.Frame(parent, bg='white')
        filter_frame.pack(fill=tk.X, pady=(10, 20), padx=10)

        # Supplier filter
        tk.Label(filter_frame, text="Supplier:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=0, column=0, padx=5, pady=5, sticky='e')

        self.supplier_filter_var = tk.StringVar(value='ALL')
        self.supplier_combo = ttk.Combobox(filter_frame, textvariable=self.supplier_filter_var,
                                           width=20, state='readonly', font=('Segoe UI', 11))
        self.supplier_combo.grid(row=0, column=1, padx=5, pady=5, sticky='w')

        # Date filters
        tk.Label(filter_frame, text="From:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=0, column=2, padx=5, pady=5, sticky='e')
        self.date_from_entry = tk.Entry(filter_frame, font=('Segoe UI', 11), width=12)
        self.date_from_entry.grid(row=0, column=3, padx=5, pady=5, sticky='w')
        self.date_from_entry.insert(0, '')
        self.date_from_entry.bind('<Return>', lambda e: self.load_supplier_purchases_data())

        tk.Label(filter_frame, text="To:", font=('Segoe UI', 11),
                 bg='white', fg='#6a4334').grid(row=0, column=4, padx=5, pady=5, sticky='e')
        self.date_to_entry = tk.Entry(filter_frame, font=('Segoe UI', 11), width=12)
        self.date_to_entry.grid(row=0, column=5, padx=5, pady=5, sticky='w')
        self.date_to_entry.insert(0, '')
        self.date_to_entry.bind('<Return>', lambda e: self.load_supplier_purchases_data())

        # Load button
        load_btn = tk.Button(filter_frame, text="🔍 LOAD",
                             font=('Segoe UI', 11, 'bold'),
                             bg='#2e86c1', fg='black', relief='flat', cursor='hand2',
                             command=self.load_supplier_purchases_data, padx=15, pady=5)
        load_btn.grid(row=0, column=6, padx=10, pady=5)

        # Refresh button
        refresh_btn = tk.Button(filter_frame, text="🔄 REFRESH",
                                font=('Segoe UI', 11, 'bold'),
                                bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                                command=self.load_supplier_purchases_data, padx=15, pady=5)
        refresh_btn.grid(row=0, column=7, padx=5, pady=5)

        # Treeview
        tree_frame = tk.Frame(parent, bg='white')
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        tree_container = tk.Frame(tree_frame, bg='white')
        tree_container.pack(fill=tk.BOTH, expand=True)

        v_scrollbar = ttk.Scrollbar(tree_container)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        columns = ('Date', 'Supplier', 'Item', 'Quantity', 'Unit Price', 'Total Cost', 'Invoice', 'User', 'Notes')
        self.supplier_purchases_tree = ttk.Treeview(tree_container, columns=columns,
                                                    yscrollcommand=v_scrollbar.set,
                                                    xscrollcommand=h_scrollbar.set,
                                                    height=15)

        v_scrollbar.config(command=self.supplier_purchases_tree.yview)
        h_scrollbar.config(command=self.supplier_purchases_tree.xview)

        for col in columns:
            self.supplier_purchases_tree.heading(col, text=col, anchor=tk.W)
            self.supplier_purchases_tree.column(col, width=120, minwidth=80)

        self.supplier_purchases_tree.pack(fill=tk.BOTH, expand=True)

        # Status label
        status_frame = tk.Frame(parent, bg='white')
        status_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        self.supplier_status_label = tk.Label(status_frame, text="", font=('Segoe UI', 10),
                                              bg='white', fg='#6a4334')
        self.supplier_status_label.pack(side=tk.LEFT)

        # Load suppliers and initial data
        self.load_supplier_list()
        self.load_supplier_purchases_data()

    def load_supplier_list(self):
        """Load supplier list for combobox."""
        try:
            suppliers = self.inventory.get_all_suppliers()
            if hasattr(self, 'supplier_combo'):
                self.supplier_combo['values'] = suppliers
                self.supplier_combo.set('ALL')
        except Exception as e:
            print(f"Error loading suppliers: {e}")

    def load_supplier_purchases_data(self):
        """Load supplier purchase history data."""
        if not hasattr(self, 'supplier_purchases_tree'):
            return

        # Clear existing items
        for item in self.supplier_purchases_tree.get_children():
            self.supplier_purchases_tree.delete(item)

        try:
            supplier = self.supplier_filter_var.get() if hasattr(self, 'supplier_filter_var') else 'ALL'
            from_date = self.date_from_entry.get().strip() if hasattr(self, 'date_from_entry') else None
            to_date = self.date_to_entry.get().strip() if hasattr(self, 'date_to_entry') else None

            # If no dates provided, don't filter by date
            if from_date == '':
                from_date = None
            if to_date == '':
                to_date = None

            purchases = self.inventory.get_supplier_purchases(
                supplier_name=None if supplier == 'ALL' else supplier,
                start_date=from_date,
                end_date=to_date
            )

            for record in purchases:
                date = record['purchase_date'].split('.')[0] if record['purchase_date'] else ''
                values = (
                    date,
                    record['supplier_name'],
                    record['item_name'],
                    record['quantity'],
                    f"${record['unit_price']:.2f}",
                    f"${record['total_cost']:.2f}",
                    record.get('invoice_number', ''),
                    record.get('username', ''),
                    record.get('notes', '')[:30] + '...' if len(record.get('notes', '')) > 30 else record.get('notes',
                                                                                                              '')
                )
                self.supplier_purchases_tree.insert('', tk.END, values=values)

            # Update status
            if hasattr(self, 'supplier_status_label'):
                self.supplier_status_label.config(text=f"Showing {len(purchases)} records")

        except Exception as e:
            self.show_error(f"Error loading supplier purchases: {str(e)}")

    def create_export_popup(self, parent):
        """Create export data popup."""
        # Main container
        main_frame = tk.Frame(parent, bg='white')
        main_frame.pack(expand=True, padx=50, pady=50)

        tk.Label(main_frame, text="EXPORT INVENTORY DATA", font=('Segoe UI', 18, 'bold'),
                 bg='white', fg='#6a4334').pack(pady=(0, 30))

        # Format selection
        format_frame = tk.Frame(main_frame, bg='white')
        format_frame.pack(pady=10)

        tk.Label(format_frame, text="Export Format:", font=('Segoe UI', 12),
                 bg='white', fg='#6a4334').pack(side=tk.LEFT, padx=10)
        self.export_format = tk.StringVar(value='csv')

        ttk.Radiobutton(format_frame, text="CSV", variable=self.export_format, value='csv').pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(format_frame, text="JSON", variable=self.export_format, value='json').pack(side=tk.LEFT,
                                                                                                   padx=10)

        # Options
        options_frame = tk.Frame(main_frame, bg='white')
        options_frame.pack(pady=20)

        self.include_all = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Include all items",
                        variable=self.include_all).grid(row=0, column=0, padx=10, pady=5, sticky='w')

        self.only_low_stock = tk.BooleanVar(value=False)
        ttk.Checkbutton(options_frame, text="Only low stock items",
                        variable=self.only_low_stock).grid(row=1, column=0, padx=10, pady=5, sticky='w')

        # Status label
        self.export_status = tk.Label(main_frame, text="", font=('Segoe UI', 11),
                                      foreground='green', bg='white')
        self.export_status.pack(pady=10)

        # Export button
        export_btn = tk.Button(main_frame, text="💾 EXPORT DATA",
                               font=('Segoe UI', 14, 'bold'),
                               bg='#27ae60', fg='black', relief='flat', cursor='hand2',
                               command=self.export_data, padx=30, pady=15)
        export_btn.pack(pady=20)
        export_btn.bind('<Return>', lambda e: self.export_data())

    def export_data(self):
        """Export data to CSV or JSON."""
        try:
            if self.only_low_stock.get():
                items = self.inventory.get_low_stock_items()
            else:
                items = self.inventory.get_all_items()

            if not items:
                self.show_warning("No data to export!")
                return

            format_type = self.export_format.get()
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'inventory_export_{timestamp}.{format_type}'

            if format_type == 'csv':
                with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                    if items:
                        fieldnames = items[0].keys()
                        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(items)

            elif format_type == 'json':
                with open(filename, 'w', encoding='utf-8') as jsonfile:
                    json.dump(items, jsonfile, indent=2, default=str)

            self.export_status.config(text=f"✅ Exported {len(items)} items to {filename}")
            self.show_info(f"✅ Data exported successfully to:\n{filename}")

        except Exception as e:
            self.show_error(f"Error exporting data: {str(e)}")

    def create_header(self):
        """Create header for main menu."""
        header_frame = tk.Frame(self.main_frame, bg='#6a4334', height=60)  # Reduced from 80 to 60
        header_frame.pack(fill=tk.X, padx=0, pady=0)
        header_frame.pack_propagate(False)

        # Left side: Hotel logo and name
        logo_frame = tk.Frame(header_frame, bg='#6a4334')
        logo_frame.pack(side=tk.LEFT, padx=20, pady=8)  # Reduced pady from 10 to 8

        hotel_label = tk.Label(logo_frame, text="🏨 THE EVAANI HOTEL",
                               font=('Georgia', 18, 'bold'), bg='#6a4334', fg='white')  # Reduced from 20 to 18
        hotel_label.pack(side=tk.LEFT, padx=(0, 20))

        system_label = tk.Label(logo_frame, text="Inventory Management System",
                                font=('Segoe UI', 11), bg='#6a4334', fg='#d5d8dc')  # Reduced from 12 to 11
        system_label.pack(side=tk.LEFT)

        # Right side: User info and logout
        user_frame = tk.Frame(header_frame, bg='#6a4334')
        user_frame.pack(side=tk.RIGHT, padx=20, pady=8)  # Reduced pady from 10 to 8

        welcome_label = tk.Label(user_frame,
                                 text=f"Welcome, {self.auth.current_user['username'].upper()}",
                                 font=('Segoe UI', 11, 'bold'),  # Reduced from 12 to 11
                                 bg='#6a4334', fg='white')
        welcome_label.pack(side=tk.LEFT, padx=(0, 15))  # Reduced padx from 20 to 15

        role_badge = tk.Label(user_frame, text=self.auth.current_user['role'].upper(),
                              font=('Segoe UI', 9, 'bold'), bg='#2e86c1', fg='black',  # Reduced from 10 to 9
                              padx=8, pady=3, relief=tk.FLAT)  # Reduced padx from 10 to 8, pady from 5 to 3
        role_badge.pack(side=tk.LEFT, padx=(0, 15))  # Reduced padx from 20 to 15

        logout_btn = tk.Button(user_frame, text="LOGOUT", font=('Segoe UI', 10, 'bold'),  # Reduced from 11 to 10
                               bg='#c0392b', fg='black', activebackground='#a93226',
                               activeforeground='white', relief='flat', cursor='hand2',
                               command=self.logout, padx=12, pady=3)  # Reduced padx from 15 to 12, pady from 5 to 3
        logout_btn.pack(side=tk.LEFT)

    def center_dialog(self, dialog, width, height):
        """Center a dialog window on screen."""
        screen_width = dialog.winfo_screenwidth()
        screen_height = dialog.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        dialog.geometry(f'{width}x{height}+{x}+{y}')

    def logout(self):
        """Logout and return to login screen."""
        self.auth.logout()
        self.main_frame.destroy()
        self.create_login_frame()

    def run(self):
        self.root.mainloop()


# Main entry point
if __name__ == "__main__":
    try:
        app = InventoryAppGUI()
        app.run()
    except Exception as e:
        print(f"Error starting application: {e}")
        import traceback

        traceback.print_exc()
        input("Press Enter to exit...")

