"""
School Parent Membership System - Production Server
Flask + SQLite Database
Configured for production deployment
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import hashlib
import secrets
import os
import re 
from datetime import datetime, timedelta

# Configuration
SECRET_KEY = os.environ.get('SECRET_KEY', secrets.token_hex(32))

DATABASE_PATH = '/data/membership.db'  # Your mount path
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

app = Flask(__name__, static_folder='static', static_url_path='')
app.config['SECRET_KEY'] = SECRET_KEY
CORS(app)

def ensure_data_directory():
    """Ensure /data directory exists and is writable"""
    global DATABASE_PATH  # Move this to the top of the function
    
    data_dir = os.path.dirname(DATABASE_PATH)
    if not os.path.exists(data_dir):
        try:
            os.makedirs(data_dir, exist_ok=True)
            print(f"✅ Created data directory: {data_dir}")
        except Exception as e:
            print(f"⚠️  Could not create data directory: {e}")
            # Fall back to local directory
            DATABASE_PATH = './membership.db'
            print(f"   Using fallback: {DATABASE_PATH}")
    
    # Check if writable
    if os.path.exists(data_dir) and not os.access(data_dir, os.W_OK):
        print(f"⚠️  Data directory not writable: {data_dir}")
        DATABASE_PATH = './membership.db'
        print(f"   Using fallback: {DATABASE_PATH}")

# ============================================
# PROFILE PICTURE HANDLING FUNCTIONS
# ============================================

def convert_google_drive_link(drive_url):
    """
    Convert Google Drive link to direct image URL
    
    Handles formats:
    - /open?id=FILE_ID
    - /file/d/FILE_ID  
    - Already direct format
    """
    if not drive_url or not isinstance(drive_url, str):
        return None
    
    # Skip if nan or empty
    if drive_url.lower() == 'nan' or not drive_url.strip():
        return None
    
    if 'drive.google.com' in drive_url:
        # Format 1: /open?id=FILE_ID
        match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', drive_url)
        if match:
            file_id = match.group(1)
            return f'https://drive.google.com/uc?export=view&id={file_id}'
        
        # Format 2: /file/d/FILE_ID/view
        match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', drive_url)
        if match:
            file_id = match.group(1)
            return f'https://drive.google.com/uc?export=view&id={file_id}'
        
        # Format 3: Already in direct format
        if 'uc?export=view&id=' in drive_url:
            return drive_url
    
    # If not Google Drive link, return as-is (might be direct URL)
    return drive_url

def generate_fallback_avatar(first_name, surname):
    """
    Generate UI Avatars fallback image URL
    Uses MHS colors (dark green background, gold text)
    """
    return f'https://ui-avatars.com/api/?name={first_name}+{surname}&background=1a472a&color=FFC107&size=200&bold=true'

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database with required tables"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Members table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_number TEXT UNIQUE NOT NULL,
            first_name TEXT NOT NULL,
            surname TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            password_hash TEXT NOT NULL,
            membership_type TEXT NOT NULL,
            expiry_date TEXT NOT NULL,
            status TEXT NOT NULL,
            photo_url TEXT,
            points INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Family members table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS family_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            primary_member_id INTEGER NOT NULL,
            member_number TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            relationship TEXT,
            FOREIGN KEY (primary_member_id) REFERENCES members (id)
        )
    ''')
    
    # Attendance table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_number TEXT NOT NULL,
            member_name TEXT NOT NULL,
            event_name TEXT,
            scanned_by TEXT,
            timestamp TEXT NOT NULL,
            points_awarded INTEGER DEFAULT 10,
            status TEXT NOT NULL
        )
    ''')
    
    # Sessions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL
        )
    ''')
    
    # Create default admin account if no admins exist
    cursor.execute('SELECT COUNT(*) FROM members WHERE is_admin = 1')
    admin_count = cursor.fetchone()[0]
    
    if admin_count == 0:
        print("\n⚠️  No admin accounts found. Creating default admin...")
        default_admin_email = 'admin@schoolsystem.com'
        default_admin_password = 'Admin123!'
        password_hash = hash_password(default_admin_password)
        
        try:
            cursor.execute('''
                INSERT INTO members 
                (member_number, first_name, surname, email, phone, password_hash, 
                 membership_type, expiry_date, status, photo_url, is_admin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (
                'M0000',
                'Leson',
                'Visagie',
                default_admin_email,
                '',
                password_hash,
                'Solo',
                '2030-12-31',
                'active',
                'https://ui-avatars.com/api/?name=Leson+Visagie&background=059669&color=fff'
            ))
            print("✅ Default admin created!")
            print(f"   Username: {default_admin_email}")
            print(f"   Password: {default_admin_password}")
            print("   Please login and add other admin accounts.")
        except Exception as e:
            print(f"⚠️  Could not create default admin: {e}")
    
    conn.commit()
    conn.close()

def hash_password(password):
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token():
    """Generate secure random token"""
    return secrets.token_urlsafe(32)

def verify_token(token):
    """Verify if token is valid and return user info"""
    if not token:
        return None
        
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT s.email, s.role, m.first_name, m.surname, m.member_number, m.is_admin
            FROM sessions s
            LEFT JOIN members m ON s.email = m.email
            WHERE s.token = ? AND s.expires_at > ?
        ''', (token, datetime.now().isoformat()))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                'email': result[0],
                'role': result[1],
                'first_name': result[2],
                'surname': result[3],
                'member_number': result[4],
                'is_admin': result[5]
            }
    except Exception as e:
        conn.close()
        print(f"Token verification error: {e}")
    
    return None

# ============= API ROUTES =============

@app.route('/')
def index():
    """Serve the main HTML file"""
    return send_from_directory('static', 'index.html')

@app.route('/health')
def health():
    """Health check endpoint for monitoring"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

def convert_google_drive_link(drive_url):
    """Convert Google Drive link to direct image URL"""
    if not drive_url or not isinstance(drive_url, str):
        return None
    
    if drive_url.lower() == 'nan' or not drive_url.strip():
        return None
    
    if 'drive.google.com' in drive_url:
        # Format 1: /open?id=FILE_ID
        match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', drive_url)
        if match:
            file_id = match.group(1)
            return f'https://drive.google.com/uc?export=view&id={file_id}'
        
        # Format 2: /file/d/FILE_ID/view
        match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', drive_url)
        if match:
            file_id = match.group(1)
            return f'https://drive.google.com/uc?export=view&id={file_id}'
        
        # Format 3: Already in direct format
        if 'uc?export=view&id=' in drive_url:
            return drive_url
    
    return drive_url

def generate_fallback_avatar(first_name, surname):
    """Generate UI Avatars fallback image URL"""
    return f'https://ui-avatars.com/api/?name={first_name}+{surname}&background=1a472a&color=FFC107&size=200&bold=true'

@app.route('/api/admin/import-excel', methods=['POST'])
def import_excel():
    """Import members from Excel file (JSON data from frontend)"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user or user['role'] != 'admin':
        return jsonify({'error': 'Unauthorized - Admin access required'}), 401
    
    data = request.json.get('members', [])
    conn = get_db()
    cursor = conn.cursor()
    
    imported = 0
    errors = []
    
    for member_data in data:
        try:
            email = member_data.get('email', '').strip().lower()
            member_number = member_data.get('member_number', '').strip()
            
            if not email or not member_number:
                errors.append(f"Missing email or member number")
                continue
            
            default_password = email
            password_hash = hash_password(default_password)
            
            is_admin = 1 if str(member_data.get('is_admin', '')).lower() in ['yes', 'true', '1', 'admin'] else 0
            
            # Process profile picture
            photo_url = member_data.get('photo_url', '')
            if photo_url and photo_url != 'nan':
                # Convert Google Drive link if needed
                if 'drive.google.com' in photo_url:
                    # Format 1: /open?id=FILE_ID
                    match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', photo_url)
                    if match:
                        file_id = match.group(1)
                        photo_url = f'https://drive.google.com/uc?export=view&id={file_id}'
                    else:
                        # Format 2: /file/d/FILE_ID/view
                        match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', photo_url)
                        if match:
                            file_id = match.group(1)
                            photo_url = f'https://drive.google.com/uc?export=view&id={file_id}'
            else:
                # Generate fallback avatar
                first_name = member_data.get('first_name', '').strip()
                surname = member_data.get('surname', '').strip()
                if first_name and surname:
                    photo_url = f'https://ui-avatars.com/api/?name={first_name}+{surname}&background=1a472a&color=FFC107&size=200&bold=true'
                else:
                    photo_url = 'https://ui-avatars.com/api/?name=Member&background=1a472a&color=FFC107&size=200&bold=true'
            
            cursor.execute('''
                INSERT OR REPLACE INTO members 
                (member_number, first_name, surname, email, phone, password_hash, 
                 membership_type, expiry_date, status, photo_url, points, is_admin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            ''', (
                member_number,
                member_data.get('first_name', '').strip(),
                member_data.get('surname', '').strip(),
                email,
                member_data.get('phone', '').strip(),
                password_hash,
                member_data.get('membership_type', 'Solo'),
                member_data.get('expiry_date', ''),
                member_data.get('status', 'active'),
                photo_url,
                is_admin
            ))
            
            member_id = cursor.lastrowid
            
            if 'family_members' in member_data and member_data['family_members']:
                for fm in member_data['family_members']:
                    # Process family member photo
                    fm_photo_url = fm.get('photo_url', '')
                    if fm_photo_url and fm_photo_url != 'nan' and 'drive.google.com' in fm_photo_url:
                        # Convert Google Drive link
                        match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', fm_photo_url)
                        if match:
                            file_id = match.group(1)
                            fm_photo_url = f'https://drive.google.com/uc?export=view&id={file_id}'
                        else:
                            match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', fm_photo_url)
                            if match:
                                file_id = match.group(1)
                                fm_photo_url = f'https://drive.google.com/uc?export=view&id={file_id}'
                    
                    cursor.execute('''
                        INSERT OR REPLACE INTO family_members 
                        (primary_member_id, member_number, name, relationship, photo_url)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (member_id, fm['member_number'], fm['name'], fm.get('relationship', 'Family'), fm_photo_url))
            
            imported += 1
            
        except Exception as e:
            errors.append(f"{member_data.get('member_number', 'Unknown')}: {str(e)}")
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'imported': imported,
        'errors': errors
    })

@app.route('/api/login', methods=['POST'])
def login():
    """Login endpoint - email-based authentication"""
    data = request.json
    
    # Debug logging
    print(f"Login attempt with data: {data}")
    
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()
    
    if not email or not password:
        print("Missing email or password")
        return jsonify({'error': 'Email and password required'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        print(f"Looking for user with email: {email}")
        cursor.execute('SELECT * FROM members WHERE email = ?', (email,))
        member = cursor.fetchone()
        
        if member:
            print(f"Found user: {member['email']}")
            print(f"Stored hash: {member['password_hash']}")
            print(f"Provided password hash: {hash_password(password)}")
            
        if member and member['password_hash'] == hash_password(password):
            role = 'admin' if member['is_admin'] == 1 else 'member'
            print(f"Password match! Role: {role}")
            
            token = generate_token()
            expires_at = (datetime.now() + timedelta(days=30)).isoformat()
            
            # Clean up old sessions for this user
            cursor.execute('DELETE FROM sessions WHERE email = ?', (email,))
            
            cursor.execute('''
                INSERT INTO sessions (email, token, role, expires_at)
                VALUES (?, ?, ?, ?)
            ''', (email, token, role, expires_at))
            
            conn.commit()
            conn.close()
            
            return jsonify({
                'success': True,
                'token': token,
                'role': role,
                'member': {
                    'member_number': member['member_number'],
                    'first_name': member['first_name'],
                    'surname': member['surname'],
                    'email': member['email'],
                    'membership_type': member['membership_type'],
                    'status': member['status'],
                    'points': member['points'],
                    'is_admin': member['is_admin']
                }
            })
        else:
            print("Invalid credentials")
            conn.close()
            return jsonify({'error': 'Invalid email or password'}), 401
        
    except Exception as e:
        print(f"Login error: {str(e)}")
        import traceback
        traceback.print_exc()
        conn.close()
        return jsonify({'error': f'Login failed: {str(e)}'}), 500

        
@app.route('/api/member/profile', methods=['GET'])
def get_member_profile():
    """Get member profile and attendance"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT * FROM members WHERE email = ?', (user['email'],))
        member = cursor.fetchone()
        
        if not member:
            return jsonify({'error': 'Member not found'}), 404
        
        cursor.execute('''
            SELECT * FROM family_members 
            WHERE primary_member_id = (SELECT id FROM members WHERE email = ?)
        ''', (user['email'],))
        family_members = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute('''
            SELECT * FROM attendance 
            WHERE member_number = ? OR member_number IN (
                SELECT member_number FROM family_members 
                WHERE primary_member_id = (SELECT id FROM members WHERE email = ?)
            )
            ORDER BY timestamp DESC
            LIMIT 50
        ''', (member['member_number'], user['email']))
        attendance = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        return jsonify({
            'member': dict(member),
            'family_members': family_members,
            'attendance': attendance
        })
    except Exception as e:
        conn.close()
        return jsonify({'error': 'Failed to fetch profile'}), 500

@app.route('/api/scan', methods=['POST'])
def scan_qr():
    """Handle QR code scanning (Admin only)"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user or user['role'] != 'admin':
        return jsonify({'error': 'Unauthorized - Admin access required'}), 401
    
    data = request.json
    scanned_member_number = data.get('member_number')
    event_name = data.get('event_name', 'General Access')
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT m.*, m.first_name || ' ' || m.surname as full_name
            FROM members m
            WHERE m.member_number = ?
        ''', (scanned_member_number,))
        
        member = cursor.fetchone()
        
        if not member:
            cursor.execute('''
                SELECT m.*, fm.name as full_name, fm.member_number as scanned_number
                FROM family_members fm
                JOIN members m ON fm.primary_member_id = m.id
                WHERE fm.member_number = ?
            ''', (scanned_member_number,))
            
            family_result = cursor.fetchone()
            if family_result:
                member = family_result
                member_name = family_result['full_name']
            else:
                conn.close()
                return jsonify({
                    'success': False,
                    'status': 'error',
                    'message': 'Member not found'
                }), 404
        else:
            member_name = member['full_name']
        
        is_active = member['status'] == 'active' and datetime.fromisoformat(member['expiry_date']) > datetime.now()
        points_awarded = 10 if is_active else 0
        
        cursor.execute('''
            INSERT INTO attendance 
            (member_number, member_name, event_name, scanned_by, timestamp, points_awarded, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            scanned_member_number,
            member_name,
            event_name,
            user['email'],
            datetime.now().isoformat(),
            points_awarded,
            'granted' if is_active else 'denied'
        ))
        
        if is_active:
            cursor.execute('''
                UPDATE members 
                SET points = points + ? 
                WHERE member_number = ? OR id = (
                    SELECT primary_member_id FROM family_members WHERE member_number = ?
                )
            ''', (points_awarded, scanned_member_number, scanned_member_number))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'status': 'granted' if is_active else 'denied',
            'member_name': member_name,
            'points_awarded': points_awarded,
            'message': 'Access Granted' if is_active else 'Membership Expired'
        })
    except Exception as e:
        conn.close()
        return jsonify({'error': 'Scan failed'}), 500

@app.route('/api/member-info/<member_number>', methods=['GET'])
def get_member_info(member_number):
    """Get member info for confirmation display"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user or user['role'] != 'admin':
        return jsonify({'error': 'Unauthorized - Admin access required'}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Check regular members
        cursor.execute('''
            SELECT m.*, m.first_name || " " || m.surname as member_name
            FROM members m
            WHERE m.member_number = ?
        ''', (member_number,))
        
        member = cursor.fetchone()
        
        if not member:
            # Check family members
            cursor.execute('''
                SELECT m.*, fm.name as member_name, fm.member_number as scanned_number
                FROM family_members fm
                JOIN members m ON fm.primary_member_id = m.id
                WHERE fm.member_number = ?
            ''', (member_number,))
            member = cursor.fetchone()
        
        if member:
            is_active = member['status'] == 'active' and datetime.fromisoformat(member['expiry_date']) > datetime.now()
            
            return jsonify({
                'found': True,
                'member_number': member_number,
                'member_name': member['member_name'],
                'is_active': is_active,
                'expiry_date': member['expiry_date'],
                'status': member['status'],
                'membership_type': member['membership_type']
            })
        else:
            return jsonify({
                'found': False,
                'member_number': member_number,
                'message': 'Member not found'
            })
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/members', methods=['GET'])
def get_all_members():
    """Get all members (Admin only)"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user or user['role'] != 'admin':
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT m.*, 
                   COUNT(DISTINCT fm.id) as family_member_count,
                   COUNT(DISTINCT a.id) as attendance_count
            FROM members m
            LEFT JOIN family_members fm ON fm.primary_member_id = m.id
            LEFT JOIN attendance a ON a.member_number = m.member_number
            GROUP BY m.id
            ORDER BY m.created_at DESC
        ''')
        
        members = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({'members': members})
    except Exception as e:
        conn.close()
        return jsonify({'error': 'Failed to fetch members'}), 500

@app.route('/api/admin/attendance', methods=['GET'])
def get_all_attendance():
    """Get all attendance records (Admin only)"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user or user['role'] != 'admin':
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        limit = request.args.get('limit', 100)
        cursor.execute('''
            SELECT * FROM attendance 
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (limit,))
        
        attendance = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({'attendance': attendance})
    except Exception as e:
        conn.close()
        return jsonify({'error': 'Failed to fetch attendance'}), 500

@app.route('/api/admin/stats', methods=['GET'])
def get_admin_stats():
    """Get dashboard statistics (Admin only)"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user or user['role'] != 'admin':
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT COUNT(*) FROM members WHERE status = 'active'")
        active_members = cursor.fetchone()[0]
        
        expiry_threshold = (datetime.now() + timedelta(days=30)).isoformat()
        cursor.execute('''
            SELECT COUNT(*) FROM members 
            WHERE status = 'active' AND expiry_date <= ? AND expiry_date > ?
        ''', (expiry_threshold, datetime.now().isoformat()))
        expiring_soon = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM members WHERE membership_type LIKE '%Family%'")
        family_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM members WHERE membership_type LIKE '%Solo%'")
        solo_count = cursor.fetchone()[0]
        
        today = datetime.now().date().isoformat()
        cursor.execute('''
            SELECT COUNT(*) FROM attendance 
            WHERE DATE(timestamp) = ?
        ''', (today,))
        today_attendance = cursor.fetchone()[0]
        
        cursor.execute('SELECT SUM(points) FROM members')
        total_points = cursor.fetchone()[0] or 0
        
        conn.close()
        
        return jsonify({
            'active_members': active_members,
            'expiring_soon': expiring_soon,
            'family_memberships': family_count,
            'solo_memberships': solo_count,
            'today_attendance': today_attendance,
            'total_points': total_points
        })
    except Exception as e:
        conn.close()
        return jsonify({'error': 'Failed to fetch stats'}), 500

@app.route('/api/admin/expiring-members', methods=['GET'])
def get_expiring_members():
    """Get members expiring within 30 days (Admin only)"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user or user['role'] != 'admin':
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        expiry_threshold = (datetime.now() + timedelta(days=30)).isoformat()
        cursor.execute('''
            SELECT member_number, first_name, surname, email, expiry_date, membership_type
            FROM members 
            WHERE status = 'active' AND expiry_date <= ? AND expiry_date > ?
            ORDER BY expiry_date ASC
        ''', (expiry_threshold, datetime.now().isoformat()))
        
        expiring_members = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({'expiring_members': expiring_members})
    except Exception as e:
        conn.close()
        return jsonify({'error': 'Failed to fetch expiring members'}), 500

@app.route('/api/admin/create-admin', methods=['POST'])
def create_admin():
    """Create new admin account (Admin only)"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user or user['role'] != 'admin':
        return jsonify({'error': 'Unauthorized - Admin access required'}), 401
    
    data = request.json
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()
    first_name = data.get('first_name', '').strip()
    surname = data.get('surname', '').strip()
    member_number = data.get('member_number', '').strip()
    
    if not all([email, password, first_name, surname, member_number]):
        return jsonify({'error': 'All fields required'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Check if email already exists
        cursor.execute('SELECT email FROM members WHERE email = ?', (email,))
        if cursor.fetchone():
            conn.close()
            return jsonify({'error': 'Email already exists'}), 400
        
        # Check if member number already exists
        cursor.execute('SELECT member_number FROM members WHERE member_number = ?', (member_number,))
        if cursor.fetchone():
            conn.close()
            return jsonify({'error': 'Member number already exists'}), 400
        
        password_hash = hash_password(password)
        
        cursor.execute('''
            INSERT INTO members 
            (member_number, first_name, surname, email, phone, password_hash, 
             membership_type, expiry_date, status, photo_url, is_admin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ''', (
            member_number,
            first_name,
            surname,
            email,
            '',
            password_hash,
            'Solo',
            '2030-12-31',
            'active',
            f'https://ui-avatars.com/api/?name={first_name}+{surname}&background=059669&color=fff'
        ))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Admin account created for {first_name} {surname}',
            'email': email
        })
    except Exception as e:
        conn.close()
        return jsonify({'error': f'Failed to create admin: {str(e)}'}), 500

@app.route('/api/member/change-password', methods=['POST'])
def change_password():
    """Change member password"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    current_password = data.get('current_password', '').strip()
    new_password = data.get('new_password', '').strip()
    
    if not current_password or not new_password:
        return jsonify({'error': 'Both current and new password required'}), 400
    
    if len(new_password) < 6:
        return jsonify({'error': 'New password must be at least 6 characters'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Verify current password
        cursor.execute('SELECT password_hash FROM members WHERE email = ?', (user['email'],))
        result = cursor.fetchone()
        
        if not result or result[0] != hash_password(current_password):
            conn.close()
            return jsonify({'error': 'Current password is incorrect'}), 401
        
        # Update password
        new_password_hash = hash_password(new_password)
        cursor.execute('''
            UPDATE members 
            SET password_hash = ? 
            WHERE email = ?
        ''', (new_password_hash, user['email']))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Password changed successfully'
        })
    except Exception as e:
        conn.close()
        return jsonify({'error': 'Failed to change password'}), 500

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors"""
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors"""
    return jsonify({'error': 'Internal server error'}), 500

ensure_data_directory()

if __name__ == '__main__':
    init_db()
    print("\n" + "="*60)
    print("🎓 School Membership System Server")
    print("="*60)
    print("\n✅ Server starting")
    print("✅ Database initialized")
    print("✅ Ready to accept connections\n")
    
    # Production uses gunicorn, development uses Flask dev server
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=DEBUG, host='0.0.0.0', port=port)
else:
    # This runs when imported by gunicorn on Render
    print("📦 Running in production mode - initializing database...")
    init_db()