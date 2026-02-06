"""
School Parent Membership System - Production Server
Flask + SQLite Database
Configured for production deployment
"""

from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
import sqlite3
import hashlib
import secrets
import os
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import uuid

# Configuration
SECRET_KEY = os.environ.get('SECRET_KEY', secrets.token_hex(32))
DATABASE = os.environ.get('DATABASE_PATH', 'membership.db')
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

# Photo storage configuration
UPLOAD_FOLDER = '/data/profile_photos'  # Using Render's persistent disk
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

app = Flask(__name__, static_folder='static', static_url_path='')
app.config['SECRET_KEY'] = SECRET_KEY
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE
CORS(app)

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE)
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

@app.route('/api/upload-profile-photo', methods=['POST'])
def upload_profile_photo():
    """Upload profile photo for logged-in member"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Check if file is present
    if 'photo' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['photo']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Allowed: PNG, JPG, JPEG, GIF, WEBP'}), 400
    
    try:
        # Generate unique filename
        file_extension = file.filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{user['member_number']}_{uuid.uuid4().hex[:8]}.{file_extension}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        
        # Save file
        file.save(filepath)
        
        # Update database with new photo URL
        photo_url = f'/api/profile-photo/{unique_filename}'
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Delete old photo if it exists and is not a default avatar
        cursor.execute('SELECT photo_url FROM members WHERE member_number = ?', (user['member_number'],))
        result = cursor.fetchone()
        if result and result[0] and result[0].startswith('/api/profile-photo/'):
            old_filename = result[0].split('/')[-1]
            old_filepath = os.path.join(app.config['UPLOAD_FOLDER'], old_filename)
            if os.path.exists(old_filepath):
                try:
                    os.remove(old_filepath)
                except Exception as e:
                    print(f"Could not delete old photo: {e}")
        
        # Update member's photo_url
        cursor.execute('''
            UPDATE members 
            SET photo_url = ? 
            WHERE member_number = ?
        ''', (photo_url, user['member_number']))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'photo_url': photo_url,
            'message': 'Profile photo uploaded successfully'
        })
        
    except Exception as e:
        print(f"Photo upload error: {e}")
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@app.route('/api/profile-photo/<filename>')
def serve_profile_photo(filename):
    """Serve uploaded profile photos"""
    try:
        # Secure the filename to prevent directory traversal
        safe_filename = secure_filename(filename)
        return send_file(
            os.path.join(app.config['UPLOAD_FOLDER'], safe_filename),
            mimetype='image/jpeg'
        )
    except Exception as e:
        print(f"Error serving photo: {e}")
        return jsonify({'error': 'Photo not found'}), 404

@app.route('/api/import-excel', methods=['POST'])
def import_excel():
    """Import members from Excel file (Admin only)"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user or user['role'] != 'admin':
        return jsonify({'error': 'Unauthorized - Admin access required'}), 401
    
    data = request.json.get('members', [])
    conn = get_db()
    cursor = conn.cursor()
    
    imported = 0
    errors = []
    skipped = 0
    
    # Get the highest existing member number to continue from there
    cursor.execute("SELECT member_number FROM members ORDER BY member_number DESC LIMIT 1")
    result = cursor.fetchone()
    if result and result[0]:
        # Extract number from M1234 format
        last_num = int(result[0].replace('M', ''))
        next_number = last_num + 1
    else:
        next_number = 1000  # Start from M1000 if no members exist
    
    for idx, member_data in enumerate(data):
        try:
            email = member_data.get('email', '').strip().lower()
            phone = member_data.get('phone', '').strip()
            
            if not email:
                errors.append(f"Missing email for row {idx + 1}")
                continue
            
            # Check if member already exists by email or phone
            cursor.execute('''
                SELECT member_number FROM members 
                WHERE email = ? OR (phone = ? AND phone != '')
            ''', (email, phone))
            existing = cursor.fetchone()
            
            if existing:
                skipped += 1
                errors.append(f"Skipped {email} - already exists as {existing[0]}")
                continue
            
            # Generate new sequential member number
            member_number = f"M{str(next_number).zfill(4)}"
            next_number += 1
            
            # Set default password: use phone if available, otherwise use email
            if phone and len(phone) == 10 and phone.startswith('0'):
                default_password = phone
            else:
                default_password = email
            
            password_hash = hash_password(default_password)
            
            is_admin = 1 if str(member_data.get('is_admin', '')).lower() in ['yes', 'true', '1', 'admin'] else 0
            
            cursor.execute('''
                INSERT INTO members 
                (member_number, first_name, surname, email, phone, password_hash, 
                 membership_type, expiry_date, status, photo_url, points, is_admin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            ''', (
                member_number,
                member_data.get('first_name', '').strip(),
                member_data.get('surname', '').strip(),
                email,
                phone,
                password_hash,
                member_data.get('membership_type', 'Solo'),
                member_data.get('expiry_date', ''),
                member_data.get('status', 'active'),
                member_data.get('photo_url', f'https://ui-avatars.com/api/?name={member_data.get("first_name", "U")}+{member_data.get("surname", "U")}&background=059669&color=fff'),
                is_admin
            ))
            
            member_id = cursor.lastrowid
            
            # Handle family members
            family_members = member_data.get('family_members', [])
            for fam in family_members:
                try:
                    cursor.execute('''
                        INSERT INTO family_members 
                        (primary_member_id, member_number, name, relationship)
                        VALUES (?, ?, ?, ?)
                    ''', (
                        member_id,
                        fam.get('member_number', ''),
                        fam.get('name', ''),
                        fam.get('relationship', 'Family')
                    ))
                except Exception as e:
                    errors.append(f"Family member error for {member_number}: {str(e)}")
            
            imported += 1
            
        except Exception as e:
            errors.append(f"Error importing row {idx + 1}: {str(e)}")
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'imported': imported,
        'skipped': skipped,
        'errors': errors
    })

@app.route('/api/login', methods=['POST'])
def login():
    """Login endpoint - supports email or phone number"""
    data = request.json
    email_or_phone = data.get('email', '').strip()
    password = data.get('password', '').strip()
    
    if not email_or_phone or not password:
        return jsonify({'error': 'Email/phone and password required'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        password_hash = hash_password(password)
        
        # Check if input is a phone number (10 digits starting with 0)
        is_phone = email_or_phone.isdigit() and len(email_or_phone) == 10 and email_or_phone.startswith('0')
        
        if is_phone:
            # Login with phone number
            cursor.execute('''
                SELECT member_number, first_name, surname, email, membership_type, 
                       expiry_date, status, photo_url, points, is_admin
                FROM members 
                WHERE phone = ? AND password_hash = ?
            ''', (email_or_phone, password_hash))
        else:
            # Login with email (convert to lowercase)
            email_or_phone = email_or_phone.lower()
            cursor.execute('''
                SELECT member_number, first_name, surname, email, membership_type, 
                       expiry_date, status, photo_url, points, is_admin
                FROM members 
                WHERE email = ? AND password_hash = ?
            ''', (email_or_phone, password_hash))
        
        member = cursor.fetchone()
        
        if not member:
            conn.close()
            return jsonify({'error': 'Invalid credentials'}), 401
        
        # Check if membership is active
        if member['status'] != 'active':
            conn.close()
            return jsonify({'error': 'Account is not active'}), 401
        
        # Generate session token (use email for session, not phone)
        token = generate_token()
        role = 'admin' if member['is_admin'] == 1 else 'member'
        expires_at = (datetime.now() + timedelta(days=7)).isoformat()
        
        cursor.execute('''
            INSERT INTO sessions (email, token, role, expires_at)
            VALUES (?, ?, ?, ?)
        ''', (member['email'], token, role, expires_at))
        
        conn.commit()
        
        # Get family members if applicable
        family_members = []
        if 'family' in member['membership_type'].lower():
            cursor.execute('''
                SELECT member_number, name, relationship
                FROM family_members
                WHERE primary_member_id = (SELECT id FROM members WHERE email = ?)
            ''', (member['email'],))
            family_members = [dict(row) for row in cursor.fetchall()]
        
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
                'expiry_date': member['expiry_date'],
                'status': member['status'],
                'photo_url': member['photo_url'],
                'points': member['points'],
                'family_members': family_members
            }
        })
    except Exception as e:
        conn.close()
        print(f"Login error: {e}")
        return jsonify({'error': 'Login failed'}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    """Logout endpoint"""
    token = request.headers.get('Authorization')
    
    if token:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM sessions WHERE token = ?', (token,))
        conn.commit()
        conn.close()
    
    return jsonify({'success': True})

@app.route('/api/verify', methods=['GET'])
def verify():
    """Verify session token"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user:
        return jsonify({'error': 'Invalid or expired token'}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT member_number, first_name, surname, email, membership_type, 
                   expiry_date, status, photo_url, points
            FROM members 
            WHERE email = ?
        ''', (user['email'],))
        
        member = cursor.fetchone()
        
        if not member:
            conn.close()
            return jsonify({'error': 'Member not found'}), 404
        
        # Get family members
        family_members = []
        if 'family' in member['membership_type'].lower():
            cursor.execute('''
                SELECT member_number, name, relationship
                FROM family_members
                WHERE primary_member_id = (SELECT id FROM members WHERE email = ?)
            ''', (user['email'],))
            family_members = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        return jsonify({
            'success': True,
            'role': user['role'],
            'member': {
                'member_number': member['member_number'],
                'first_name': member['first_name'],
                'surname': member['surname'],
                'email': member['email'],
                'membership_type': member['membership_type'],
                'expiry_date': member['expiry_date'],
                'status': member['status'],
                'photo_url': member['photo_url'],
                'points': member['points'],
                'family_members': family_members
            }
        })
    except Exception as e:
        conn.close()
        return jsonify({'error': 'Verification failed'}), 500

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
def scan():
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

@app.route('/api/scan-qr', methods=['POST'])
def scan_qr():
    """Scan QR code and record attendance (Admin only)"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user or user['role'] != 'admin':
        return jsonify({'error': 'Unauthorized - Admin access required'}), 401
    
    data = request.json
    member_number = data.get('member_number', '').strip()
    event_name = data.get('event_name', 'General Event').strip()
    
    if not member_number:
        return jsonify({'error': 'Member number required'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Check if member exists
        cursor.execute('''
            SELECT first_name, surname, status, expiry_date 
            FROM members 
            WHERE member_number = ?
        ''', (member_number,))
        
        member = cursor.fetchone()
        
        if not member:
            # Check if it's a family member
            cursor.execute('''
                SELECT fm.name, m.status, m.expiry_date
                FROM family_members fm
                JOIN members m ON fm.primary_member_id = m.id
                WHERE fm.member_number = ?
            ''', (member_number,))
            
            family_member = cursor.fetchone()
            
            if not family_member:
                conn.close()
                return jsonify({'error': 'Member not found'}), 404
            
            member_name = family_member['name']
            status = family_member['status']
            expiry_date = family_member['expiry_date']
        else:
            member_name = f"{member['first_name']} {member['surname']}"
            status = member['status']
            expiry_date = member['expiry_date']
        
        # Check if membership is active
        if status != 'active':
            conn.close()
            return jsonify({'error': 'Membership is not active', 'status': 'inactive'}), 400
        
        # Check if membership has expired
        if expiry_date < datetime.now().date().isoformat():
            conn.close()
            return jsonify({'error': 'Membership has expired', 'status': 'expired'}), 400
        
        # Record attendance
        timestamp = datetime.now().isoformat()
        points_awarded = 10
        
        cursor.execute('''
            INSERT INTO attendance 
            (member_number, member_name, event_name, scanned_by, timestamp, points_awarded, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            member_number,
            member_name,
            event_name,
            f"{user['first_name']} {user['surname']}",
            timestamp,
            points_awarded,
            'present'
        ))
        
        # Update member points (only for primary members, not family members)
        if member:  # Only if it's a primary member
            cursor.execute('''
                UPDATE members 
                SET points = points + ? 
                WHERE member_number = ?
            ''', (points_awarded, member_number))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'member_name': member_name,
            'member_number': member_number,
            'points_awarded': points_awarded,
            'timestamp': timestamp,
            'status': 'present'
        })
    except Exception as e:
        conn.close()
        print(f"Scan error: {e}")
        return jsonify({'error': 'Failed to record attendance'}), 500

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
            SELECT member_number, first_name, surname, email, phone, 
                   membership_type, expiry_date, status, points, is_admin
            FROM members 
            ORDER BY created_at DESC
        ''')
        
        members = []
        for row in cursor.fetchall():
            member = dict(row)
            
            # Get family members
            cursor.execute('''
                SELECT member_number, name, relationship
                FROM family_members
                WHERE primary_member_id = (
                    SELECT id FROM members WHERE member_number = ?
                )
            ''', (member['member_number'],))
            
            member['family_members'] = [dict(fam) for fam in cursor.fetchall()]
            members.append(member)
        
        conn.close()
        
        return jsonify({'members': members})
    except Exception as e:
        conn.close()
        return jsonify({'error': 'Failed to fetch members'}), 500

@app.route('/api/admin/attendance', methods=['GET'])
def get_attendance():
    """Get attendance records (Admin only)"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user or user['role'] != 'admin':
        return jsonify({'error': 'Unauthorized'}), 401
    
    limit = request.args.get('limit', 100, type=int)
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT member_number, member_name, event_name, scanned_by, 
                   timestamp, points_awarded, status
            FROM attendance 
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

@app.route('/api/admin/delete-member/<member_number>', methods=['DELETE'])
def delete_member(member_number):
    """Delete a member and all associated data (Admin only)"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user or user['role'] != 'admin':
        return jsonify({'error': 'Unauthorized - Admin access required'}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # First, check if member exists
        cursor.execute('SELECT id, first_name, surname, email FROM members WHERE member_number = ?', (member_number,))
        member = cursor.fetchone()
        
        if not member:
            conn.close()
            return jsonify({'error': 'Member not found'}), 404
        
        member_id = member[0]
        member_name = f"{member[1]} {member[2]}"
        member_email = member[3]
        
        # Prevent deleting yourself
        if member_email == user['email']:
            conn.close()
            return jsonify({'error': 'Cannot delete your own account'}), 400
        
        # Delete family members
        cursor.execute('DELETE FROM family_members WHERE primary_member_id = ?', (member_id,))
        
        # Delete attendance records
        cursor.execute('DELETE FROM attendance WHERE member_number = ?', (member_number,))
        cursor.execute('''
            DELETE FROM attendance WHERE member_number IN (
                SELECT member_number FROM family_members WHERE primary_member_id = ?
            )
        ''', (member_id,))
        
        # Delete sessions
        cursor.execute('DELETE FROM sessions WHERE email = ?', (member_email,))
        
        # Delete the member
        cursor.execute('DELETE FROM members WHERE member_number = ?', (member_number,))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Member {member_name} ({member_number}) has been deleted',
            'deleted_member': member_number
        })
        
    except Exception as e:
        conn.close()
        print(f"Delete member error: {e}")
        return jsonify({'error': f'Failed to delete member: {str(e)}'}), 500

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

if __name__ == '__main__':
    init_db()
    print("\n" + "="*60)
    print("🎓 School Membership System Server")
    print("="*60)
    print("\n✅ Server starting")
    print("✅ Database initialized")
    print(f"✅ Photo uploads directory: {UPLOAD_FOLDER}")
    print("✅ Ready to accept connections\n")
    
    # Production uses gunicorn, development uses Flask dev server
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=DEBUG, host='0.0.0.0', port=port)
else:
    # This runs when imported by gunicorn on Render
    print("📦 Running in production mode - initializing database...")
    init_db()