"""
School Parent Membership System - Production Server
Flask + SQLite Database
Configured for production deployment
"""

# ⚡ INCREMENT THIS whenever you deploy — check /health to confirm which version is live
BUILD_VERSION = "2.3.0"

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

    # Sync all member passwords to match their current phone/email on every startup
    print("🔄 Running password sync on startup...")
    sync_passwords()

def hash_password(password):
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

def normalize_phone_number(phone):
    """Normalize a phone number to a standard 10-digit format starting with 0"""
    if not phone:
        return ''
    try:
        # Handle scientific notation from Excel
        if isinstance(phone, float) or (isinstance(phone, str) and '.' in phone):
            phone = str(int(float(phone)))
        phone = str(phone)
        digits_only = ''.join(c for c in phone if c.isdigit())
        if len(digits_only) == 9:
            return '0' + digits_only
        elif len(digits_only) == 10 and digits_only.startswith('0'):
            return digits_only
        elif len(digits_only) == 10 and not digits_only.startswith('0'):
            return '0' + digits_only[-9:]
        elif len(digits_only) > 10:
            candidate = digits_only[-10:]
            if candidate.startswith('0'):
                return candidate
            return '0' + digits_only[-9:]
        elif digits_only:
            return digits_only  # Less than 9 digits - return as-is
    except Exception:
        pass
    return ''

def sync_passwords(conn=None):
    """
    Sync every member's password so it always matches their current phone number
    (or email prefix if no valid phone). Also normalizes stored phone numbers.
    
    - Members with a valid phone: password = normalized 10-digit phone, phone stored normalized
    - Members with no valid phone: password = username part of email
    - Admin passwords are NEVER changed automatically
    - Members who have already changed their password away from the default are NOT reset
      (we detect this by checking if current hash matches ANY known default for that member)
    
    Returns a dict with counts: updated, skipped, errors
    """
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True

    cursor = conn.cursor()
    updated = 0
    skipped = 0
    errors = 0

    try:
        cursor.execute('''
            SELECT id, member_number, first_name, surname, email, phone,
                   password_hash, is_admin, status
            FROM members
        ''')
        members = cursor.fetchall()

        for m in members:
            mid, member_number, first_name, surname, email, phone, \
                current_hash, is_admin, status = m

            # Never touch admin passwords automatically
            if is_admin:
                skipped += 1
                continue

            try:
                raw_phone = phone or ''
                normalized = normalize_phone_number(raw_phone)
                email_prefix = (email or '').split('@')[0]

                # Determine what the default password SHOULD be
                if normalized and len(normalized) >= 9:
                    expected_password = normalized
                else:
                    expected_password = email_prefix

                # Determine what ALL valid "default" passwords could have been
                # (covers old imports where phone wasn't normalized)
                candidate_defaults = set()
                if normalized:
                    candidate_defaults.add(normalized)
                    # Also accept the 9-digit variant (without leading 0)
                    if normalized.startswith('0') and len(normalized) == 10:
                        candidate_defaults.add(normalized[1:])
                if email_prefix:
                    candidate_defaults.add(email_prefix)
                    candidate_defaults.add(email_prefix.lower())
                # Raw phone as stored in DB (may not be normalized yet)
                if raw_phone:
                    raw_digits = ''.join(c for c in str(raw_phone) if c.isdigit())
                    if raw_digits:
                        candidate_defaults.add(raw_digits)
                        if raw_digits.startswith('0'):
                            candidate_defaults.add(raw_digits[1:])

                candidate_hashes = {hash_password(p) for p in candidate_defaults if p}

                # Only update if current password is still one of the default candidates
                # This preserves passwords that members have changed themselves
                if current_hash not in candidate_hashes:
                    # Member has a custom password — still normalize the phone field
                    if normalized and normalized != raw_phone:
                        cursor.execute(
                            'UPDATE members SET phone = ? WHERE id = ?',
                            (normalized, mid)
                        )
                    skipped += 1
                    continue

                new_hash = hash_password(expected_password)

                # Only write if something actually changes
                if new_hash != current_hash or (normalized and normalized != raw_phone):
                    cursor.execute('''
                        UPDATE members
                        SET password_hash = ?,
                            phone = ?
                        WHERE id = ?
                    ''', (new_hash, normalized if normalized else raw_phone, mid))
                    updated += 1
                else:
                    skipped += 1

            except Exception as e:
                print(f"  ⚠️  sync_passwords: error on {member_number}: {e}")
                errors += 1

        conn.commit()

    except Exception as e:
        print(f"sync_passwords fatal error: {e}")
        errors += 1
    finally:
        if close_conn:
            conn.close()

    print(f"🔑 sync_passwords complete — updated: {updated}, skipped: {skipped}, errors: {errors}")
    return {'updated': updated, 'skipped': skipped, 'errors': errors}

def normalize_name(name):
    """Normalize a name by removing diacritics and converting to uppercase"""
    if not name:
        return ''
    
    try:
        # For Python 3, we can use unicodedata to normalize
        import unicodedata
        # Normalize to NFKD form to separate diacritics
        normalized = unicodedata.normalize('NFKD', name)
        # Remove diacritical marks
        normalized = ''.join(c for c in normalized if not unicodedata.combining(c))
        # Keep only letters and spaces, convert to uppercase
        normalized = ''.join(c for c in normalized if c.isalpha() or c.isspace())
        return normalized.upper().strip()
    except:
        # Fallback: simple uppercase
        return name.upper().strip()

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
    """Serve the main HTML file - always fresh, never cached"""
    response = send_from_directory('static', 'index.html')
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/health')
def health():
    """Health check endpoint — also shows deployed version"""
    return jsonify({
        'status': 'healthy',
        'version': BUILD_VERSION,
        'timestamp': datetime.now().isoformat()
    })

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
    """Import members from Excel file (Admin only) - Smart duplicate checking with auto-numbering"""
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
    updated = 0
    
    # Get the highest existing member number
    cursor.execute("SELECT MAX(CAST(REPLACE(member_number, 'M', '') AS INTEGER)) FROM members WHERE member_number LIKE 'M%'")
    result = cursor.fetchone()
    next_number = result[0] + 1 if result[0] else 1000
    
    for idx, member_data in enumerate(data):
        try:
            # Handle both formats: direct JSON and Google Forms format
            # Google Forms format uses different column names
            if 'Name & Surname' in member_data or 'Email Adress' in member_data:
                # Google Forms format
                full_name_raw = member_data.get('Name & Surname', '').strip()
                email = member_data.get('Email Adress', member_data.get('Email Address', '')).strip().lower()
                phone = str(member_data.get('Contact Number', '')).strip()
                membership_type = member_data.get('Membership Type', 'Annual Membership(solo person) R500')
                
                # Parse full name into first and surname
                name_parts = full_name_raw.split()
                if len(name_parts) >= 2:
                    first_name = ' '.join(name_parts[:-1])  # Everything except last word
                    surname = name_parts[-1]  # Last word
                elif len(name_parts) == 1:
                    first_name = name_parts[0]
                    surname = name_parts[0]
                else:
                    errors.append(f"Row {idx + 1}: Missing name")
                    continue
                
                # Clean phone number - remove spaces and convert to string
                if phone:
                    # Handle scientific notation from Excel
                    try:
                        if isinstance(phone, float) or '.' in str(phone):
                            phone = str(int(float(phone)))
                        phone = str(phone).replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
                        
                        # Get only digits
                        digits_only = ''.join(c for c in phone if c.isdigit())
                        
                        # Normalize to 10 digits starting with 0
                        if len(digits_only) == 9:
                            # Add leading 0 (724734553 -> 0724734553)
                            phone = '0' + digits_only
                        elif len(digits_only) == 10 and digits_only.startswith('0'):
                            # Already correct (0724734553)
                            phone = digits_only
                        elif len(digits_only) == 10 and not digits_only.startswith('0'):
                            # Has 10 digits but doesn't start with 0, use last 9 and add 0
                            phone = '0' + digits_only[-9:]
                        elif len(digits_only) > 10:
                            # More than 10 digits, take last 10 or last 9 + add 0
                            if digits_only[-10:].startswith('0'):
                                phone = digits_only[-10:]
                            else:
                                phone = '0' + digits_only[-9:]
                        else:
                            # Less than 9 digits or other issue
                            phone = digits_only if digits_only else ''
                    except Exception as e:
                        errors.append(f"Row {idx + 1}: Phone parsing error: {e}")
                        phone = ''
                
                # Handle family member info from Google Forms
                family_members = []
                spouse_info = member_data.get('If family Package - Details of spouse\nName and surname ', '')
                spouse_contact_col = member_data.get('Contact details of spouse:', '') or member_data.get('Contact details of spouse', '')
                spouse_email_col = member_data.get('Email of spouse:', '') or member_data.get('Email of spouse', '')

                if 'family' in membership_type.lower():
                    spouse_name = ''
                    spouse_phone = ''
                    spouse_email_val = ''

                    if spouse_info and spouse_info.strip().lower() not in ['', 'no package', 'n/a']:
                        # Format A: "Name\nID\nPhone\nEmail" (all in one cell)
                        spouse_parts = [p.strip() for p in spouse_info.split('\n') if p.strip()]
                        if spouse_parts:
                            spouse_name = spouse_parts[0]
                        # Find phone: 10-digit number in parts
                        for part in spouse_parts[1:]:
                            digits = ''.join(c for c in str(part) if c.isdigit())
                            if 9 <= len(digits) <= 10:
                                if len(digits) == 9:
                                    spouse_phone = '0' + digits
                                else:
                                    spouse_phone = digits
                            elif '@' in str(part):
                                spouse_email_val = part.strip().lower()

                        # Format B: name only in col13, phone in col19, email in col20
                        if not spouse_phone and spouse_contact_col:
                            raw = str(spouse_contact_col)
                            digits = ''.join(c for c in raw if c.isdigit())
                            if len(digits) == 9:
                                spouse_phone = '0' + digits
                            elif len(digits) == 10:
                                spouse_phone = digits
                        if not spouse_email_val and spouse_email_col:
                            spouse_email_val = str(spouse_email_col).strip().lower()

                    elif spouse_contact_col:
                        # No col13 name but col19 has contact — still create spouse
                        raw = str(spouse_contact_col)
                        digits = ''.join(c for c in raw if c.isdigit())
                        if len(digits) == 9:
                            spouse_phone = '0' + digits
                        elif len(digits) == 10:
                            spouse_phone = digits
                        if spouse_email_col:
                            spouse_email_val = str(spouse_email_col).strip().lower()

                    if spouse_name or spouse_phone:
                        family_members.append({
                            'name': spouse_name or 'Spouse',
                            'relationship': 'Spouse',
                            'phone': spouse_phone,
                            'email': spouse_email_val,
                            'create_account': True,   # flag to create a members row
                            'expiry_date': member_data.get('expiry_date', '2027-12-31'),
                            'membership_type': membership_type,
                        })
            else:
                # Standard JSON format
                email = member_data.get('email', '').strip().lower()
                phone = member_data.get('phone', '').strip()
                first_name = member_data.get('first_name', '').strip()
                surname = member_data.get('surname', '').strip()
                membership_type = member_data.get('membership_type', 'Solo')
                family_members = member_data.get('family_members', [])
            
            if not email:
                errors.append(f"Row {idx + 1}: Missing email")
                continue
            
            if not first_name or not surname:
                errors.append(f"Row {idx + 1}: Missing name (first or last)")
                continue
            
            full_name = f"{first_name} {surname}"
            
            # Normalize phone for comparison
            normalized_phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '') if phone else ''
            
            # Check if member already exists by email
            cursor.execute('SELECT member_number, first_name, surname FROM members WHERE LOWER(email) = ?', (email,))
            existing_by_email = cursor.fetchone()
            
            if existing_by_email:
                existing_name = f"{existing_by_email[1]} {existing_by_email[2]}"
                
                if existing_name.lower() == full_name.lower():
                    # Same person with same email - skip
                    skipped += 1
                    errors.append(f"Skipped {full_name} ({email}) - already exists as {existing_by_email[0]}")
                    continue
                else:
                    # Different person with same email - generate unique email
                    base_email = email.split('@')[0]
                    domain = email.split('@')[1] if '@' in email else 'middiesklub.com'
                    new_email = f"{base_email}.{next_number}@{domain}"
                    email = new_email
                    errors.append(f"Row {idx + 1}: Original email in use, using {new_email} instead")
            
            # Also check by phone if provided (using normalized comparison)
            if normalized_phone and len(normalized_phone) >= 10:
                cursor.execute('''
                    SELECT member_number, first_name, surname 
                    FROM members 
                    WHERE REPLACE(REPLACE(REPLACE(REPLACE(phone, ' ', ''), '-', ''), '(', ''), ')', '') = ?
                ''', (normalized_phone,))
                existing_by_phone = cursor.fetchone()
                
                if existing_by_phone:
                    existing_name = f"{existing_by_phone[1]} {existing_by_phone[2]}"
                    
                    if existing_name.lower() == full_name.lower():
                        # Same person, different email - update email
                        cursor.execute('UPDATE members SET email = ? WHERE member_number = ?', (email, existing_by_phone[0]))
                        updated += 1
                        errors.append(f"Updated {existing_by_phone[0]} - updated email to {email}")
                        conn.commit()
                        continue
                    else:
                        # Different person with same phone - mark as duplicate but continue
                        errors.append(f"Row {idx + 1}: Phone {phone} already used by {existing_name}, skipping phone field")
                        phone = ''  # Clear phone to avoid constraint violation
            
            # Check if same person exists by name (fuzzy match)
            cursor.execute('''
                SELECT member_number, first_name, surname, email 
                FROM members 
                WHERE LOWER(first_name || ' ' || surname) = LOWER(?)
            ''', (full_name,))
            
            existing_by_name = cursor.fetchone()
            
            if existing_by_name:
                # Person with same name exists - check if it's likely the same person
                existing_email = existing_by_name[3]
                if '@middiesklub.temp' in existing_email or email.endswith('@middiesklub.temp'):
                    # Likely same person with temp email - update email
                    cursor.execute('UPDATE members SET email = ? WHERE member_number = ?', (email, existing_by_name[0]))
                    updated += 1
                    errors.append(f"Updated {existing_by_name[0]} - updated email from temp to {email}")
                    conn.commit()
                    continue
                else:
                    # Different person with same name - add with number suffix
                    first_name = f"{first_name}{next_number}"
                    errors.append(f"Row {idx + 1}: Name '{full_name}' already exists, using '{first_name} {surname}' instead")
            
            # Generate new sequential member number
            member_number = f"M{str(next_number).zfill(4)}"
            next_number += 1
            
            # Set default password: use phone if available, otherwise use email
            if phone and len(normalized_phone) >= 10:
                # Use normalized phone as password (10 digits)
                default_password = normalized_phone[-10:] if len(normalized_phone) > 10 else normalized_phone
            else:
                default_password = email.split('@')[0]  # Use username part of email
            
            password_hash = hash_password(default_password)
            
            is_admin = 1 if str(member_data.get('is_admin', '')).lower() in ['yes', 'true', '1', 'admin'] else 0
            
            cursor.execute('''
                INSERT INTO members 
                (member_number, first_name, surname, email, phone, password_hash, 
                 membership_type, expiry_date, status, photo_url, points, is_admin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            ''', (
                member_number,
                first_name,
                surname,
                email,
                phone,
                password_hash,
                membership_type,
                member_data.get('expiry_date', '2027-12-31'),
                member_data.get('status', 'active'),
                member_data.get('photo_url', f'https://ui-avatars.com/api/?name={first_name}+{surname}&background=1a472a&color=FFC107'),
                is_admin
            ))
            
            member_id = cursor.lastrowid

            # Handle family members / spouses
            family_counter = 1

            for fam in family_members:
                try:
                    fam_name = fam.get('name', '').strip()
                    if not fam_name:
                        continue

                    fam_phone = normalize_phone_number(fam.get('phone', ''))
                    fam_email = fam.get('email', '').strip().lower()
                    create_account = fam.get('create_account', False)

                    # Generate a family member number (e.g. M1005-F1)
                    family_member_number = f"{member_number}-F{family_counter}"
                    family_counter += 1

                    # --- Create a full members account so the spouse can log in ---
                    if create_account and (fam_phone or fam_email):
                        # Split name into first + surname
                        fam_parts = fam_name.split()
                        fam_first = ' '.join(fam_parts[:-1]) if len(fam_parts) > 1 else fam_parts[0]
                        fam_surname = fam_parts[-1] if len(fam_parts) > 1 else fam_parts[0]

                        # Build a fallback email if none provided
                        if not fam_email:
                            fam_slug = fam_name.lower().replace(' ', '.')
                            fam_email = f"{fam_slug}.{next_number}@middiesklub.temp"

                        # Default password = phone, fallback to email prefix
                        fam_password = fam_phone if fam_phone else fam_email.split('@')[0]
                        fam_hash = hash_password(fam_password)

                        fam_photo = f"https://ui-avatars.com/api/?name={fam_first}+{fam_surname}&background=1a472a&color=FFC107"
                        fam_expiry = fam.get('expiry_date', '2027-12-31')
                        fam_mtype = fam.get('membership_type', membership_type)

                        # Check if spouse account already exists by phone or email
                        spouse_exists = False
                        if fam_phone:
                            cursor.execute(
                                "SELECT member_number FROM members WHERE phone = ?", (fam_phone,)
                            )
                            if cursor.fetchone():
                                spouse_exists = True
                                errors.append(f"Spouse {fam_name} ({fam_phone}) already has an account — skipped duplicate")
                        if not spouse_exists and fam_email and '@middiesklub.temp' not in fam_email:
                            cursor.execute(
                                "SELECT member_number FROM members WHERE LOWER(email) = ?", (fam_email,)
                            )
                            if cursor.fetchone():
                                spouse_exists = True
                                errors.append(f"Spouse {fam_name} ({fam_email}) already has an account — skipped duplicate")

                        if not spouse_exists:
                            cursor.execute('''
                                INSERT INTO members
                                (member_number, first_name, surname, email, phone, password_hash,
                                 membership_type, expiry_date, status, photo_url, points, is_admin)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, 0, 0)
                            ''', (
                                family_member_number,
                                fam_first,
                                fam_surname,
                                fam_email,
                                fam_phone,
                                fam_hash,
                                fam_mtype,
                                fam_expiry,
                                fam_photo,
                            ))
                            next_number += 1
                            imported += 1

                    # Always also add to family_members table for QR/attendance linking
                    cursor.execute('''
                        SELECT id FROM family_members
                        WHERE primary_member_id = ? AND LOWER(name) = LOWER(?)
                    ''', (member_id, fam_name))

                    if cursor.fetchone():
                        errors.append(f"Family member '{fam_name}' already linked to {member_number}")
                        continue

                    cursor.execute('''
                        INSERT INTO family_members
                        (primary_member_id, member_number, name, relationship)
                        VALUES (?, ?, ?, ?)
                    ''', (
                        member_id,
                        family_member_number,
                        fam_name,
                        fam.get('relationship', 'Family')
                    ))

                except Exception as e:
                    errors.append(f"Family member error for {member_number}: {str(e)}")
            
            imported += 1
            
        except sqlite3.IntegrityError as e:
            if 'UNIQUE constraint failed' in str(e):
                errors.append(f"Row {idx + 1}: Duplicate entry - {str(e)}")
                skipped += 1
            else:
                errors.append(f"Row {idx + 1}: Database error - {str(e)}")
        except Exception as e:
            errors.append(f"Error importing row {idx + 1}: {str(e)}")
    
    conn.commit()
    conn.close()

    # After import, sync all passwords so new members can log in immediately
    print("🔄 Running password sync after import...")
    sync_passwords()

    return jsonify({
        'success': True,
        'imported': imported,
        'skipped': skipped,
        'updated': updated,
        'errors': errors[:50]  # Limit errors to first 50
    })

@app.route('/api/login', methods=['POST'])
def login():
    """Login endpoint - ULTRA FLEXIBLE - tries all combinations"""
    data = request.json
    identifier = data.get('email', '').strip()
    password = data.get('password', '').strip()
    
    if not identifier or not password:
        return jsonify({'error': 'Please enter both username and password'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Normalize inputs
        normalized_identifier = identifier.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        normalized_password = password.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        identifier_lower = identifier.lower()
        password_lower = password.lower()
        
        # Build list of all possible password hashes to try
        password_attempts = [
            hash_password(password),                         # As entered
            hash_password(normalized_password),              # Normalized (no spaces/dashes)
            hash_password(password_lower),                   # Lowercase
            hash_password(identifier),                       # Username as password
            hash_password(normalized_identifier),            # Normalized username as password
            hash_password(identifier_lower),                 # Lowercase username as password
        ]
        
        # Add email prefix attempts if it looks like an email
        if '@' in identifier:
            email_prefix = identifier.split('@')[0]
            password_attempts.extend([
                hash_password(email_prefix),                 # Email prefix
                hash_password(email_prefix.lower()),         # Lowercase email prefix
            ])
        
        # Also try password as email prefix (for members whose password IS their email prefix)
        if '@' in password:
            pwd_prefix = password.split('@')[0]
            password_attempts.extend([
                hash_password(pwd_prefix),
                hash_password(pwd_prefix.lower()),
            ])
        
        # Remove duplicates
        password_attempts = list(set(password_attempts))
        
        member = None
        
        # SELECT columns: 0=member_number, 1=first_name, 2=surname, 3=email, 4=membership_type,
        #                 5=expiry_date, 6=status, 7=photo_url, 8=points, 9=is_admin, 10=phone
        
        # 1. Try as email - first look up the member, then validate password
        if '@' in identifier:
            cursor.execute('''
                SELECT member_number, first_name, surname, email, membership_type,
                       expiry_date, status, photo_url, points, is_admin, phone, password_hash
                FROM members
                WHERE LOWER(email) = ?
            ''', (identifier_lower,))
            candidate = cursor.fetchone()
            if candidate:
                stored_hash = candidate[11]
                candidate_phone = normalize_phone_number(candidate[10] or '')
                email_prefix = identifier.split('@')[0]

                # All valid passwords for this member:
                # - their stored password hash (whatever it is)
                # - their phone number in any format
                # - their email or email prefix
                # - the password as entered in any form
                valid_passwords = set()
                valid_passwords.add(stored_hash)  # always accept stored password

                # Build accepted password hashes
                accepted = set([stored_hash])
                for pwd in [password, normalized_password, password_lower,
                            identifier, identifier_lower, email_prefix, email_prefix.lower()]:
                    accepted.add(hash_password(pwd))
                if candidate_phone:
                    accepted.add(hash_password(candidate_phone))
                    if candidate_phone.startswith('0'):
                        accepted.add(hash_password(candidate_phone[1:]))

                if stored_hash in accepted:
                    # Convert to tuple without password_hash field
                    member = candidate[:11]
        
        # 2. If not found, try as phone number
        if not member and normalized_identifier.isdigit() and len(normalized_identifier) >= 9:
            # Handle phone numbers - try last 10 digits AND last 9 digits (without leading 0)
            phones_to_try = []
            
            if len(normalized_identifier) >= 10:
                phones_to_try.append(normalized_identifier[-10:])  # Last 10 digits (0724734553)
            if len(normalized_identifier) >= 9:
                phones_to_try.append(normalized_identifier[-9:])   # Last 9 digits (724734553)
            
            # Remove duplicates
            phones_to_try = list(set(phones_to_try))
            
            for phone_to_try in phones_to_try:
                for pwd_hash in password_attempts:
                    cursor.execute('''
                        SELECT member_number, first_name, surname, email, membership_type, 
                               expiry_date, status, photo_url, points, is_admin, phone
                        FROM members 
                        WHERE REPLACE(REPLACE(REPLACE(REPLACE(phone, ' ', ''), '-', ''), '(', ''), ')', '') LIKE ?
                        AND password_hash = ?
                    ''', ('%' + phone_to_try, pwd_hash))
                    member = cursor.fetchone()
                    if member:
                        break
                if member:
                    break
        
        # 3. If not found, try as member number
        if not member and normalized_identifier.upper().startswith('M'):
            for pwd_hash in password_attempts:
                cursor.execute('''
                    SELECT member_number, first_name, surname, email, membership_type, 
                           expiry_date, status, photo_url, points, is_admin, phone
                    FROM members 
                    WHERE UPPER(member_number) = ? AND password_hash = ?
                ''', (normalized_identifier.upper(), pwd_hash))
                member = cursor.fetchone()
                if member:
                    break
        
        # 4. LAST RESORT: Check if user entered phone/email in password field
        # Try swapping identifier and password
        if not member:
            # Try password as identifier (swap them)
            swap_password_attempts = [
                hash_password(identifier),
                hash_password(normalized_identifier),
                hash_password(identifier_lower)
            ]
            if '@' in identifier:
                swap_password_attempts.append(hash_password(identifier.split('@')[0]))
            
            swap_password_attempts = list(set(swap_password_attempts))
            
            # Try password as email
            for pwd_hash in swap_password_attempts:
                cursor.execute('''
                    SELECT member_number, first_name, surname, email, membership_type, 
                           expiry_date, status, photo_url, points, is_admin, phone
                    FROM members 
                    WHERE LOWER(email) = ? AND password_hash = ?
                ''', (password_lower, pwd_hash))
                member = cursor.fetchone()
                if member:
                    break
            
            # Try password as phone
            if not member and normalized_password.isdigit() and len(normalized_password) >= 9:
                phones_to_try = []
                if len(normalized_password) >= 10:
                    phones_to_try.append(normalized_password[-10:])
                if len(normalized_password) >= 9:
                    phones_to_try.append(normalized_password[-9:])
                phones_to_try = list(set(phones_to_try))
                
                for phone_to_try in phones_to_try:
                    for pwd_hash in swap_password_attempts:
                        cursor.execute('''
                            SELECT member_number, first_name, surname, email, membership_type, 
                                   expiry_date, status, photo_url, points, is_admin, phone
                            FROM members 
                            WHERE REPLACE(REPLACE(REPLACE(REPLACE(phone, ' ', ''), '-', ''), '(', ''), ')', '') LIKE ?
                            AND password_hash = ?
                        ''', ('%' + phone_to_try, pwd_hash))
                        member = cursor.fetchone()
                        if member:
                            break
                    if member:
                        break
        
        if not member:
            conn.close()
            return jsonify({'error': 'Login failed. Your username is your email or phone number. Your password is your phone number (e.g. 0821234567). Contact your admin if you need help.'}), 401
        
        # Extract member data using tuple indices
        member_number = member[0]
        first_name = member[1]
        surname = member[2]
        email = member[3]
        membership_type = member[4]
        expiry_date = member[5]
        status = member[6]
        photo_url = member[7]
        points = member[8]
        is_admin = member[9]
        phone = member[10]
        
        # Check if membership is active
        if status != 'active':
            conn.close()
            return jsonify({'error': 'Account is not active'}), 401
        
        # Generate session token
        token = generate_token()
        role = 'admin' if is_admin == 1 else 'member'
        expires_at = (datetime.now() + timedelta(days=7)).isoformat()
        
        cursor.execute('''
            INSERT INTO sessions (email, token, role, expires_at)
            VALUES (?, ?, ?, ?)
        ''', (email, token, role, expires_at))
        
        conn.commit()
        
        # Get family members if applicable
        family_members = []
        if 'family' in membership_type.lower():
            cursor.execute('''
                SELECT member_number, name, relationship
                FROM family_members
                WHERE primary_member_id = (SELECT id FROM members WHERE email = ?)
            ''', (email,))
            family_members = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        return jsonify({
            'success': True,
            'token': token,
            'role': role,
            'member': {
                'member_number': member_number,
                'first_name': first_name,
                'surname': surname,
                'email': email,
                'membership_type': membership_type,
                'expiry_date': expiry_date,
                'status': status,
                'photo_url': photo_url,
                'points': points,
                'family_members': family_members
            }
        })
    except Exception as e:
        conn.close()
        print(f"Login error: {e}")
        import traceback
        traceback.print_exc()
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
    scanned_data = data.get('member_data', '').strip()
    event_name = data.get('event_name', 'General Access')
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Normalize the scanned data for comparison
        normalized_scanned = normalize_name(scanned_data)
        
        # First try to match by member number
        cursor.execute('''
            SELECT m.*, m.first_name || ' ' || m.surname as full_name
            FROM members m
            WHERE m.member_number = ?
        ''', (scanned_data,))
        
        member = cursor.fetchone()
        
        if not member:
            # Try to match by normalized name (first + last name)
            cursor.execute('''
                SELECT m.*, m.first_name || ' ' || m.surname as full_name
                FROM members m
                WHERE normalize_name(m.first_name || ' ' || m.surname) = ?
            ''', (normalized_scanned,))
            
            member = cursor.fetchone()
            
            if not member:
                # Try to match family members by normalized name
                cursor.execute('''
                    SELECT m.*, fm.name as full_name, fm.member_number as scanned_number
                    FROM family_members fm
                    JOIN members m ON fm.primary_member_id = m.id
                    WHERE normalize_name(fm.name) = ?
                ''', (normalized_scanned,))
                
                family_result = cursor.fetchone()
                if family_result:
                    member = family_result
                    member_name = family_result['full_name']
                    scanned_member_number = family_result['scanned_number']
                else:
                    conn.close()
                    return jsonify({
                        'success': False,
                        'status': 'error',
                        'message': f'Member not found: {scanned_data}'
                    }), 404
            else:
                member_name = member['full_name']
                scanned_member_number = member['member_number']
        else:
            member_name = member['full_name']
            scanned_member_number = member['member_number']
        
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
            'scanned_data': scanned_data,
            'points_awarded': points_awarded,
            'message': 'Access Granted' if is_active else 'Membership Expired'
        })
    except Exception as e:
        conn.close()
        print(f"Scan error: {e}")
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

@app.route('/api/member-info-by-email/<email>', methods=['GET'])
def get_member_info_by_email(email):
    """Get member info by email for confirmation display"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user or user['role'] != 'admin':
        return jsonify({'error': 'Unauthorized - Admin access required'}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Look up member by email
        cursor.execute('''
            SELECT m.*, m.first_name || " " || m.surname as member_name
            FROM members m
            WHERE m.email = ?
        ''', (email.lower(),))
        
        member = cursor.fetchone()
        
        if member:
            is_active = member['status'] == 'active' and datetime.fromisoformat(member['expiry_date']) > datetime.now()
            
            return jsonify({
                'found': True,
                'email': member['email'],
                'member_number': member['member_number'],
                'member_name': member['member_name'],
                'is_active': is_active,
                'expiry_date': member['expiry_date'],
                'status': member['status'],
                'membership_type': member['membership_type']
            })
        else:
            return jsonify({
                'found': False,
                'email': email,
                'message': 'Member not found'
            })
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/scan-by-email', methods=['POST'])
def scan_by_email():
    """Scan by email and record attendance (Admin only)"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user or user['role'] != 'admin':
        return jsonify({'error': 'Unauthorized - Admin access required'}), 401
    
    data = request.json
    email = data.get('email', '').strip().lower()
    event_name = data.get('event_name', 'General Access')
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        member = None
        member_name = None
        member_number = None
        is_family_member = False

        # Check if this is a family member fallback QR (primary_email+familyN)
        if '+family' in email:
            primary_email = email.split('+family')[0]
            family_index_str = email.split('+family')[1]
            try:
                family_index = int(family_index_str)
            except ValueError:
                family_index = 0

            # Find the primary member
            cursor.execute('''
                SELECT m.id, m.member_number, m.first_name, m.surname, m.status, m.expiry_date
                FROM members m
                WHERE LOWER(m.email) = ?
            ''', (primary_email,))
            primary = cursor.fetchone()

            if primary:
                # Get the family member at this index
                cursor.execute('''
                    SELECT fm.name, fm.member_number
                    FROM family_members fm
                    WHERE fm.primary_member_id = ?
                    ORDER BY fm.id
                    LIMIT 1 OFFSET ?
                ''', (primary['id'], family_index))
                fam = cursor.fetchone()

                if fam:
                    member_name = fam['name']
                    member_number = fam['member_number']
                    is_family_member = True
                    # Use primary member's status/expiry for access check
                    is_active = primary['status'] == 'active' and datetime.fromisoformat(primary['expiry_date']) > datetime.now()
                    # Points go to primary member
                    points_member_number = primary['member_number']
                    points_email = primary_email

        if not member_name:
            # Normal email lookup
            cursor.execute('''
                SELECT m.*, m.first_name || ' ' || m.surname as full_name
                FROM members m
                WHERE LOWER(m.email) = ?
            ''', (email,))
            member = cursor.fetchone()

            if not member:
                conn.close()
                return jsonify({
                    'success': False,
                    'status': 'error',
                    'message': 'Member not found'
                }), 404

            member_name = member['full_name']
            member_number = member['member_number']
            is_active = member['status'] == 'active' and datetime.fromisoformat(member['expiry_date']) > datetime.now()
            points_member_number = member_number
            points_email = email

        points_awarded = 10 if is_active else 0
        
        cursor.execute('''
            INSERT INTO attendance 
            (member_number, member_name, event_name, scanned_by, timestamp, points_awarded, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            member_number,
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
                WHERE member_number = ?
            ''', (points_awarded, points_member_number))
        
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
            SELECT m.member_number, m.first_name, m.surname, m.email, m.phone, 
                   m.membership_type, m.expiry_date, m.status, m.points, m.is_admin,
                   COUNT(a.id) as attendance_count
            FROM members m
            LEFT JOIN attendance a ON a.member_number = m.member_number
            GROUP BY m.id
            ORDER BY m.created_at DESC
        ''')
        
        members = []
        for row in cursor.fetchall():
            member = dict(row)

            # Strip newlines from name fields (can sneak in from bad Excel imports
            # and break HTML table rendering client-side)
            for field in ('first_name', 'surname', 'email', 'phone', 'membership_type'):
                if member.get(field):
                    member[field] = str(member[field]).replace('\n', ' ').replace('\r', '').replace('\t', ' ').strip()

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

@app.route('/api/admin/reset-password/<member_number>', methods=['POST'])
def reset_member_password(member_number):
    """Reset a member's password back to their default (phone or email prefix). Admin only."""
    token = request.headers.get('Authorization')
    user = verify_token(token)

    if not user or user['role'] != 'admin':
        return jsonify({'error': 'Unauthorized - Admin access required'}), 401

    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT id, email, phone, first_name, surname FROM members WHERE member_number = ?', (member_number,))
        member = cursor.fetchone()

        if not member:
            conn.close()
            return jsonify({'error': 'Member not found'}), 404

        phone = normalize_phone_number(member['phone'] or '')
        email_prefix = (member['email'] or '').split('@')[0]
        default_password = phone if phone and len(phone) >= 9 else email_prefix

        if not default_password:
            conn.close()
            return jsonify({'error': 'No phone or email to reset password to'}), 400

        cursor.execute('UPDATE members SET password_hash = ? WHERE member_number = ?',
                      (hash_password(default_password), member_number))
        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'message': f"Password reset for {member['first_name']} {member['surname']}",
            'default_password': default_password
        })

    except Exception as e:
        conn.close()
        return jsonify({'error': f'Failed to reset password: {str(e)}'}), 500

@app.route('/api/admin/sync-passwords', methods=['POST'])
def admin_sync_passwords():
    """
    Manually trigger password sync for all members (Admin only).
    Safe to run at any time — does not reset custom passwords.
    """
    token = request.headers.get('Authorization')
    user = verify_token(token)

    if not user or user['role'] != 'admin':
        return jsonify({'error': 'Unauthorized - Admin access required'}), 401

    result = sync_passwords()
    return jsonify({
        'success': True,
        'message': f"Password sync complete. Updated: {result['updated']}, "
                   f"Skipped: {result['skipped']}, Errors: {result['errors']}",
        **result
    })

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

@app.route('/api/admin/toggle-admin/<member_number>', methods=['POST'])
def toggle_admin_status(member_number):
    """Toggle admin status for a member (Admin only, only klub@middies.co.za can demote)"""
    token = request.headers.get('Authorization')
    user = verify_token(token)
    
    if not user or user['role'] != 'admin':
        return jsonify({'error': 'Unauthorized - Admin access required'}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Get current member info
        cursor.execute('SELECT id, first_name, surname, email, is_admin FROM members WHERE member_number = ?', (member_number,))
        member = cursor.fetchone()
        
        if not member:
            conn.close()
            return jsonify({'error': 'Member not found'}), 404
        
        member_id = member[0]
        member_name = f"{member[1]} {member[2]}"
        member_email = member[3]
        current_admin_status = member[4]
        
        # Prevent modifying your own admin status
        if member_email == user['email']:
            conn.close()
            return jsonify({'error': 'Cannot modify your own admin status'}), 400
        
        # Determine new status
        new_admin_status = 0 if current_admin_status == 1 else 1
        
        # Special rule: Only klub@middies.co.za can REMOVE admin privileges
        if current_admin_status == 1 and new_admin_status == 0:
            if user['email'] != 'klub@middies.co.za':
                conn.close()
                return jsonify({'error': 'Only klub@middies.co.za can remove admin privileges'}), 403
        
        # Update admin status
        cursor.execute('UPDATE members SET is_admin = ? WHERE member_number = ?', (new_admin_status, member_number))
        
        # Update all active sessions for this member
        new_role = 'admin' if new_admin_status == 1 else 'member'
        cursor.execute('UPDATE sessions SET role = ? WHERE email = ?', (new_role, member_email))
        
        conn.commit()
        conn.close()
        
        action = 'promoted to admin' if new_admin_status == 1 else 'removed from admin'
        
        return jsonify({
            'success': True,
            'message': f'{member_name} has been {action}',
            'new_admin_status': new_admin_status,
            'member_number': member_number
        })
        
    except Exception as e:
        conn.close()
        print(f"Toggle admin error: {e}")
        return jsonify({'error': f'Failed to update admin status: {str(e)}'}), 500

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