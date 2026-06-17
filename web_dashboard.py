from flask import Flask, render_template, request, jsonify, session
from functools import wraps
import sqlite3
import threading
import time
from datetime import datetime
from config import BOT_TOKEN, ADMIN_ID, BOT_NAME
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'soikot-vip-bot-2026-secure'

# Database pool
class DatabasePool:
    def __init__(self, max_connections=10):
        self.connections = []
        self.available = []
        for _ in range(max_connections):
            conn = sqlite3.connect('users.db', check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self.connections.append(conn)
            self.available.append(conn)
    
    def get_connection(self):
        while not self.available:
            time.sleep(0.01)
        return self.available.pop()
    
    def release_connection(self, conn):
        self.available.append(conn)

db_pool = DatabasePool(max_connections=10)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/admin')
def admin_login():
    return render_template('admin_login.html')

@app.route('/api/admin/login', methods=['POST'])
def login():
    data = request.json
    admin_key = data.get('admin_key')
    
    if admin_key == str(ADMIN_ID):
        session['admin_logged_in'] = True
        return jsonify({'success': True})
    return jsonify({'success': False}), 401

@app.route('/api/admin/logout', methods=['POST'])
def logout():
    session.pop('admin_logged_in', None)
    return jsonify({'success': True})

@app.route('/api/dashboard')
@admin_required
def dashboard():
    conn = db_pool.get_connection()
    try:
        cur = conn.cursor()
        
        cur.execute('SELECT COUNT(*) FROM users')
        total_users = cur.fetchone()[0]
        
        cur.execute('SELECT SUM(balance) FROM users')
        total_balance = cur.fetchone()[0] or 0
        
        cur.execute('SELECT COUNT(*) FROM transactions')
        total_trans = cur.fetchone()[0]
        
        return jsonify({
            'total_users': total_users,
            'total_balance': f"${total_balance:.2f}",
            'total_transactions': total_trans,
            'bot_status': '✅ চলছে'
        })
    finally:
        db_pool.release_connection(conn)

@app.route('/api/users')
@admin_required
def get_users():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    conn = db_pool.get_connection()
    try:
        cur = conn.cursor()
        
        cur.execute('SELECT * FROM users ORDER BY joined_date DESC LIMIT ? OFFSET ?', 
                   (per_page, offset))
        users = [dict(row) for row in cur.fetchall()]
        
        cur.execute('SELECT COUNT(*) FROM users')
        total = cur.fetchone()[0]
        
        return jsonify({
            'users': users,
            'total': total,
            'pages': (total + per_page - 1) // per_page
        })
    finally:
        db_pool.release_connection(conn)

@app.route('/api/user/<int:user_id>/balance', methods=['POST'])
@admin_required
def update_balance(user_id):
    data = request.json
    new_balance = float(data.get('balance', 0))
    
    conn = db_pool.get_connection()
    try:
        cur = conn.cursor()
        cur.execute('UPDATE users SET balance = ? WHERE user_id = ?', (new_balance, user_id))
        cur.execute('INSERT INTO transactions (user_id, amount, type) VALUES (?, ?, ?)',
                   (user_id, new_balance, 'admin_update'))
        conn.commit()
        return jsonify({'success': True})
    finally:
        db_pool.release_connection(conn)

@app.route('/api/transactions')
@admin_required
def get_transactions():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    conn = db_pool.get_connection()
    try:
        cur = conn.cursor()
        
        cur.execute('SELECT * FROM transactions ORDER BY timestamp DESC LIMIT ? OFFSET ?',
                   (per_page, offset))
        transactions = [dict(row) for row in cur.fetchall()]
        
        cur.execute('SELECT COUNT(*) FROM transactions')
        total = cur.fetchone()[0]
        
        return jsonify({
            'transactions': transactions,
            'total': total,
            'pages': (total + per_page - 1) // per_page
        })
    finally:
        db_pool.release_connection(conn)

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
