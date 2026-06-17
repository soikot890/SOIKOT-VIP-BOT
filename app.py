from flask import Flask, render_template, request, jsonify, session
from functools import wraps
import sqlite3
import os
from datetime import datetime
from config import BOT_TOKEN, ADMIN_ID, BOT_NAME
import telebot

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'

# Database helper functions
def get_db():
    db = sqlite3.connect('users.db')
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    cur = db.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users
        (user_id INTEGER PRIMARY KEY,
         balance REAL DEFAULT 0,
         referral_count INTEGER DEFAULT 0,
         joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    cur.execute('''CREATE TABLE IF NOT EXISTS transactions
        (id INTEGER PRIMARY KEY AUTOINCREMENT,
         user_id INTEGER,
         amount REAL,
         type TEXT,
         timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
         FOREIGN KEY (user_id) REFERENCES users(user_id))''')
    
    db.commit()
    db.close()

# Initialize database
init_db()

# Admin login decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    admin_key = data.get('admin_key')
    
    # Simple admin authentication
    if admin_key == str(ADMIN_ID):
        session['admin_logged_in'] = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Invalid key'}), 401

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('admin_logged_in', None)
    return jsonify({'success': True})

@app.route('/api/dashboard')
@admin_required
def dashboard():
    db = get_db()
    cur = db.cursor()
    
    # Get statistics
    cur.execute('SELECT COUNT(*) as total_users FROM users')
    total_users = cur.fetchone()['total_users']
    
    cur.execute('SELECT SUM(balance) as total_balance FROM users')
    total_balance = cur.fetchone()['total_balance'] or 0
    
    cur.execute('SELECT COUNT(*) as total_transactions FROM transactions')
    total_transactions = cur.fetchone()['total_transactions']
    
    db.close()
    
    return jsonify({
        'total_users': total_users,
        'total_balance': f"${total_balance:.2f}",
        'total_transactions': total_transactions,
        'bot_name': BOT_NAME,
        'bot_status': 'Running'
    })

@app.route('/api/users')
@admin_required
def get_users():
    db = get_db()
    cur = db.cursor()
    
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    cur.execute('SELECT * FROM users LIMIT ? OFFSET ?', (per_page, offset))
    users = [dict(row) for row in cur.fetchall()]
    
    cur.execute('SELECT COUNT(*) as count FROM users')
    total = cur.fetchone()['count']
    
    db.close()
    
    return jsonify({
        'users': users,
        'total': total,
        'pages': (total + per_page - 1) // per_page,
        'current_page': page
    })

@app.route('/api/user/<int:user_id>', methods=['GET', 'POST'])
@admin_required
def manage_user(user_id):
    db = get_db()
    cur = db.cursor()
    
    if request.method == 'GET':
        cur.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cur.fetchone()
        
        if not user:
            db.close()
            return jsonify({'error': 'User not found'}), 404
        
        # Get user transactions
        cur.execute('SELECT * FROM transactions WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10', (user_id,))
        transactions = [dict(row) for row in cur.fetchall()]
        
        db.close()
        
        return jsonify({
            'user': dict(user),
            'transactions': transactions
        })
    
    elif request.method == 'POST':
        data = request.json
        action = data.get('action')
        
        if action == 'update_balance':
            amount = float(data.get('amount', 0))
            cur.execute('UPDATE users SET balance = ? WHERE user_id = ?', (amount, user_id))
            
            # Log transaction
            cur.execute('INSERT INTO transactions (user_id, amount, type) VALUES (?, ?, ?)',
                       (user_id, amount, 'admin_update'))
            
            db.commit()
            db.close()
            
            return jsonify({'success': True, 'message': 'Balance updated'})
        
        elif action == 'add_bonus':
            amount = float(data.get('amount', 0))
            cur.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
            row = cur.fetchone()
            
            if not row:
                db.close()
                return jsonify({'error': 'User not found'}), 404
            
            new_balance = row['balance'] + amount
            cur.execute('UPDATE users SET balance = ? WHERE user_id = ?', (new_balance, user_id))
            
            # Log transaction
            cur.execute('INSERT INTO transactions (user_id, amount, type) VALUES (?, ?, ?)',
                       (user_id, amount, 'bonus'))
            
            db.commit()
            db.close()
            
            return jsonify({'success': True, 'message': f'Bonus of ${amount} added'})
    
    db.close()
    return jsonify({'error': 'Invalid action'}), 400

@app.route('/api/transactions')
@admin_required
def get_transactions():
    db = get_db()
    cur = db.cursor()
    
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    cur.execute('''SELECT t.*, u.user_id FROM transactions t 
                   LEFT JOIN users u ON t.user_id = u.user_id 
                   ORDER BY t.timestamp DESC LIMIT ? OFFSET ?''', (per_page, offset))
    transactions = [dict(row) for row in cur.fetchall()]
    
    cur.execute('SELECT COUNT(*) as count FROM transactions')
    total = cur.fetchone()['count']
    
    db.close()
    
    return jsonify({
        'transactions': transactions,
        'total': total,
        'pages': (total + per_page - 1) // per_page,
        'current_page': page
    })

@app.route('/api/add-user', methods=['POST'])
@admin_required
def add_user():
    data = request.json
    user_id = int(data.get('user_id'))
    balance = float(data.get('balance', 0))
    
    db = get_db()
    cur = db.cursor()
    
    try:
        cur.execute('INSERT OR REPLACE INTO users (user_id, balance) VALUES (?, ?)',
                   (user_id, balance))
        db.commit()
        db.close()
        
        return jsonify({'success': True, 'message': 'User added successfully'})
    except Exception as e:
        db.close()
        return jsonify({'success': False, 'error': str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
