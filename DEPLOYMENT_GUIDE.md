# 🚀 Production Deployment Guide

Complete guide to deploy the School Membership System to production hosting.

## 📋 Table of Contents

1. [Deployment Options](#deployment-options)
2. [Render.com Deployment (Recommended)](#rendercom-deployment-recommended)
3. [Railway.app Deployment](#railwayapp-deployment)
4. [DigitalOcean App Platform](#digitalocean-app-platform)
5. [VPS Deployment (Advanced)](#vps-deployment-advanced)
6. [Post-Deployment Setup](#post-deployment-setup)
7. [Selling to Schools](#selling-to-schools)

---

## Deployment Options

### Recommended: Render.com
- ✅ **FREE tier available**
- ✅ Auto-deploys from GitHub
- ✅ SSL certificates included
- ✅ Easy database backup
- ✅ Simple environment variables
- ⚠️ Free tier sleeps after 15 min inactivity

### Alternative: Railway.app
- ✅ $5/month credit free
- ✅ Very easy setup
- ✅ Fast deployment
- ⚠️ Requires credit card

### Professional: DigitalOcean
- ✅ $5-10/month
- ✅ Always on
- ✅ More control
- ⚠️ More complex

---

## Render.com Deployment (RECOMMENDED)

### Step 1: Prepare Your Code

1. **Create GitHub Account** (if you don't have one):
   - Go to https://github.com
   - Sign up for free

2. **Create New Repository**:
   - Click "New repository"
   - Name: `school-membership-system`
   - Public or Private (your choice)
   - Click "Create repository"

3. **Upload Your Code**:
   
   Option A - Using GitHub Website:
   ```
   1. Click "uploading an existing file"
   2. Drag all files from membership-production folder
   3. Click "Commit changes"
   ```
   
   Option B - Using Git Command Line:
   ```bash
   cd membership-production
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/school-membership-system.git
   git push -u origin main
   ```

### Step 2: Deploy to Render

1. **Create Render Account**:
   - Go to https://render.com
   - Sign up (free)
   - Connect your GitHub account

2. **Create New Web Service**:`
   - Click "New +" → "Web Service"
   - Select your GitHub repository
   - Configure:
     ```
     Name: school-membership-system
     Region: Choose closest to South Africa (Europe recommended)
     Branch: main
     Build Command: pip install -r requirements.txt
     Start Command: gunicorn server:app
     ```

3. **Choose Plan**:
   - Select **"Free"** for testing
   - Or **"Starter" ($7/month)** for production (recommended for schools)

4. **Add Environment Variables**:
   Click "Advanced" → "Add Environment Variable":
   ```
   SECRET_KEY = (generate random string)
   DATABASE_PATH = /opt/render/project/src/membership.db
   DEBUG = False
   ```

   To generate SECRET_KEY:
   ```python
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

5. **Create Service**:
   - Click "Create Web Service"
   - Wait 3-5 minutes for deployment
   - You'll get a URL like: `https://school-membership-system.onrender.com`

### Step 3: Set Up Database Persistence

**IMPORTANT:** Render free tier doesn't persist files by default!

For production (paid plan):
1. Go to your service
2. Click "Disks" → "Add Disk"
3. Configure:
   ```
   Name: membership-data
   Mount Path: /opt/render/project/src
   Size: 1 GB
   ```

For free tier testing:
- Database resets when service sleeps
- Good for testing only
- **Use paid plan for actual school deployment**

### Step 4: Test Your Deployment

1. Visit your Render URL
2. Should see login page
3. Won't have admin yet - need to add manually

---

## Railway.app Deployment

### Step 1: Prepare GitHub (same as Render above)

### Step 2: Deploy to Railway

1. **Create Railway Account**:
   - Go to https://railway.app
   - Sign up with GitHub

2. **Create New Project**:
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Choose your repository

3. **Configure Service**:
   - Railway auto-detects Python
   - No configuration needed!

4. **Add Environment Variables**:
   - Click "Variables"
   - Add:
     ```
     SECRET_KEY = (random string)
     DEBUG = False
     ```

5. **Get Your URL**:
   - Click "Settings" → "Generate Domain"
   - You'll get: `https://your-app.up.railway.app`

### Step 3: Add Persistent Volume

1. Click "New" → "Volume"
2. Configure:
   ```
   Name: membership-db
   Mount Path: /app
   ```
3. Restart service

---

## DigitalOcean App Platform

### For $10-15/month - Professional deployment

1. **Create DigitalOcean Account**
2. Click "Create" → "Apps"
3. Connect GitHub
4. Select repository
5. Configure:
   ```
   Name: school-membership
   Region: London (closest to South Africa)
   Instance Size: Basic ($5) or Professional ($12)
   ```
6. Add environment variables
7. Deploy

---

## VPS Deployment (Advanced)

### For full control - $5-10/month

#### Option 1: DigitalOcean Droplet

**Step 1: Create Droplet**
1. Create DigitalOcean account
2. Create Droplet:
   - Ubuntu 22.04
   - Basic plan ($6/month)
   - Choose datacenter close to South Africa

**Step 2: Connect via SSH**
```bash
ssh root@your_server_ip
```

**Step 3: Install Dependencies**
```bash
# Update system
apt update && apt upgrade -y

# Install Python and tools
apt install python3 python3-pip nginx git -y

# Install certbot for SSL
apt install certbot python3-certbot-nginx -y
```

**Step 4: Deploy Application**
```bash
# Create app directory
mkdir -p /var/www/membership
cd /var/www/membership

# Clone your code (or upload via SFTP)
git clone https://github.com/YOUR_USERNAME/school-membership-system.git .

# Install requirements
pip3 install -r requirements.txt

# Create environment file
nano .env
# Add: SECRET_KEY, DEBUG=False, etc.
```

**Step 5: Create Systemd Service**
```bash
nano /etc/systemd/system/membership.service
```

Add:
```ini
[Unit]
Description=School Membership System
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/membership
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
ExecStart=/usr/local/bin/gunicorn --workers 2 --bind 127.0.0.1:5000 server:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable service:
```bash
systemctl enable membership
systemctl start membership
systemctl status membership
```

**Step 6: Configure Nginx**
```bash
nano /etc/nginx/sites-available/membership
```

Add:
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    client_max_body_size 10M;
}
```

Enable site:
```bash
ln -s /etc/nginx/sites-available/membership /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx
```

**Step 7: Set Up SSL (Free)**
```bash
certbot --nginx -d your-domain.com
```

**Step 8: Set Up Backups**
```bash
# Create backup script
nano /usr/local/bin/backup-membership.sh
```

Add:
```bash
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/var/backups/membership"
mkdir -p $BACKUP_DIR
cp /var/www/membership/membership.db $BACKUP_DIR/membership_$DATE.db
# Keep only last 30 days
find $BACKUP_DIR -name "membership_*.db" -mtime +30 -delete
```

Make executable and schedule:
```bash
chmod +x /usr/local/bin/backup-membership.sh
crontab -e
# Add: 0 2 * * * /usr/local/bin/backup-membership.sh
```

---

## Post-Deployment Setup

### 1. Add First Admin

Since you can't run `add_admin.py` on most hosting platforms, use this method:

**Option A: Run locally then upload database**
1. Download `membership.db` from server
2. Run locally: `python add_admin.py`
3. Upload updated `membership.db` back to server

**Option B: Direct database access (if available)**
```python
import sqlite3
import hashlib

conn = sqlite3.connect('membership.db')
cursor = conn.cursor()

cursor.execute('''
    INSERT INTO members 
    (member_number, first_name, surname, email, phone, password_hash, 
     membership_type, expiry_date, status, photo_url, is_admin)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
''', (
    'M0001',
    'Admin',
    'User',
    'admin@school.com',
    '',
    hashlib.sha256('admin@school.com'.encode()).hexdigest(),
    'Solo',
    '2027-12-31',
    'active',
    'https://ui-avatars.com/api/?name=Admin+User'
))

conn.commit()
conn.close()
```

**Option C: Create admin via API endpoint** (if you add one)

### 2. Custom Domain Setup

#### Using Render/Railway/DigitalOcean App Platform:
1. Buy domain from Namecheap/GoDaddy (R150-300/year)
2. In domain settings, add DNS records:
   ```
   Type: CNAME
   Name: www
   Value: your-app.onrender.com
   ```
3. In hosting platform, add custom domain
4. Wait 24-48 hours for DNS propagation

#### Using VPS:
1. Point A record to your server IP:
   ```
   Type: A
   Name: @
   Value: YOUR_SERVER_IP
   ```

### 3. Set Up Monitoring

**Uptime Monitoring (Free)**:
- UptimeRobot: https://uptimerobot.com
- Pingdom (limited free): https://pingdom.com

Add your URL and get alerts if site goes down.

### 4. Regular Backups

**Automated Database Backups**:

For Render (paid plan):
- Use cron job within your app
- Store backups to external service (AWS S3, Backblaze)

For VPS:
- Set up daily cron job (shown above)
- Consider rsync to remote server

### 5. Security Checklist

✅ HTTPS enabled (SSL certificate)  
✅ Strong SECRET_KEY set  
✅ DEBUG=False in production  
✅ Regular database backups  
✅ Firewall configured (VPS only)  
✅ Regular updates  
✅ Monitor for unauthorized access  

---

## Selling to Schools

### Pricing Model Suggestions

**Option 1: One-Time Setup + Monthly**
- Setup fee: R5,000 - R10,000 (includes deployment, training)
- Monthly hosting: R300 - R500
- Annual renewal: R3,000 - R5,000 (support + updates)

**Option 2: Annual License**
- Year 1: R8,000 - R15,000 (includes setup)
- Year 2+: R5,000 - R8,000 (hosting + support)

**Option 3: Per-Member**
- R50-100 per member per year
- Minimum: R5,000 per year

### What to Include

**Bronze Package (R5,000/year)**:
- Hosted system
- Up to 200 members
- Email support
- Monthly backups

**Silver Package (R8,000/year)**:
- Hosted system
- Up to 500 members
- Priority email support
- Daily backups
- Custom domain
- Basic customization

**Gold Package (R12,000/year)**:
- Hosted system
- Unlimited members
- Phone + email support
- Real-time backups
- Custom domain + branding
- Full customization
- Training sessions

### Sales Materials Needed

1. **Demo Site**:
   - Deploy a demo with sample data
   - URL: `demo.yourbusiness.com`
   - Let schools test it

2. **Proposal Template**:
   ```
   TO: [School Name]
   FROM: [Your Company]
   RE: Digital Membership Management System
   
   PROBLEM:
   - Manual membership tracking
   - Physical cards get lost
   - No attendance tracking
   - Time-consuming check-ins
   
   SOLUTION:
   - Digital membership cards on phones
   - QR code scanning (instant)
   - Automatic points system
   - Easy Excel import from Google Forms
   
   BENEFITS:
   - Save 10+ hours per month
   - Better engagement (points/rewards)
   - Professional image
   - Real-time reporting
   
   INVESTMENT:
   - Setup: R8,000 (once-off)
   - Hosting: R400/month
   - Training: Included
   - Support: Email + phone
   
   TIMELINE:
   - Week 1: Setup + admin training
   - Week 2: Import members
   - Week 3: Go live
   
   GUARANTEE:
   30-day money-back guarantee
   ```

3. **Quick Start Guide for Schools**:
   - Simple PDF with screenshots
   - "From Excel to Live System in 24 Hours"

4. **Training Materials**:
   - Video tutorials (5-10 minutes each)
   - Quick reference cards
   - Admin checklist

### Ongoing Revenue Streams

1. **Hosting & Maintenance**: R300-500/month per school
2. **Support**: R500/hour (or included in package)
3. **Customization**: R2,000-5,000 per feature
4. **Training**: R1,500 per session
5. **Extra admins**: R500 per additional admin account
6. **White-label**: R10,000-20,000 one-time

### Support SLA Template

**Response Times**:
- Critical (system down): 2 hours
- High (feature broken): 8 hours
- Medium (minor issue): 24 hours
- Low (question): 48 hours

**Uptime Guarantee**:
- 99.5% uptime (about 3.5 hours downtime per month)
- Scheduled maintenance windows announced 48h ahead

---

## Quick Deployment Checklist

### Pre-Launch
- [ ] Code pushed to GitHub
- [ ] Requirements.txt complete
- [ ] Environment variables configured
- [ ] Database backup strategy planned
- [ ] Custom domain purchased (if needed)
- [ ] SSL certificate ready (auto on most platforms)

### Launch Day
- [ ] Deploy to hosting platform
- [ ] Add first admin account
- [ ] Test login works
- [ ] Test Excel import
- [ ] Test QR scanner
- [ ] Test on mobile devices
- [ ] Set up monitoring

### Post-Launch
- [ ] Train school administrators
- [ ] Import real member data
- [ ] Monitor for issues first week
- [ ] Set up automated backups
- [ ] Document any custom changes
- [ ] Schedule follow-up training

---

## Costs Summary

### Hosting Options
| Platform | Free Tier | Paid | Best For |
|----------|-----------|------|----------|
| Render | ✅ (sleeps) | $7/month | Easy start |
| Railway | $5 credit | $5-10/month | Fast setup |
| DigitalOcean Apps | ❌ | $5-12/month | Professional |
| VPS (DigitalOcean) | ❌ | $6-12/month | Full control |

### Recommended Setup for Schools
- **Development/Demo**: Render Free
- **Small School (<200 members)**: Render Starter ($7/month) or Railway ($5/month)
- **Medium School (200-500)**: DigitalOcean Apps ($12/month)
- **Large School (500+)**: VPS ($12/month)

### Your Costs (Reselling)
- Hosting: R100-200/month per school
- Domain: R15-25/month per school (if providing)
- Your Time: Setup (4-6 hours) + Support (1-2 hours/month)

### Your Profit Margins
- Bronze (R5,000/year): R4,500 profit (90%)
- Silver (R8,000/year): R7,000 profit (87%)
- Gold (R12,000/year): R10,500 profit (87%)

---

## Next Steps

1. **Deploy Demo**:
   - Follow Render.com steps above
   - Add sample data
   - Test everything

2. **Create Sales Materials**:
   - Screenshot the system
   - Write proposal
   - Make 1-pager

3. **Approach First School**:
   - Start with school you know
   - Offer 50% discount for being first
   - Get testimonial

4. **Iterate**:
   - Get feedback
   - Fix issues
   - Improve based on use

5. **Scale**:
   - Automate deployment
   - Create reseller packages
   - Build support team

---

**Need help?** Contact: lesonvisagie@gmail.com

**Ready to deploy?** Start with Render.com - easiest option!