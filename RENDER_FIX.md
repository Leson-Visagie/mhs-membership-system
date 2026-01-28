# 🔧 QUICK FIX - Render Deployment Error

## ❌ Error You're Seeing:
```
ModuleNotFoundError: No module named 'app'
```

## ✅ Solution (2 minutes):

### The Problem:
Render is trying to run `gunicorn app:app` but your file is named `server.py`

### The Fix:

1. **Go to Render Dashboard**
   - Open https://dashboard.render.com
   - Click on your service

2. **Update Start Command**:
   - Click "Settings" (left sidebar)
   - Scroll to "Build & Deploy"
   - Find "Start Command"
   - Change from: `gunicorn app:app`
   - Change to: **`gunicorn server:app`**
   - Click "Save Changes"

3. **Redeploy**:
   - Click "Manual Deploy" → "Deploy latest commit"
   - Wait 2-3 minutes
   - Should work now!

## Alternative: Update Render.yaml (If You Have One)

If you have a `render.yaml` file, update it:

```yaml
services:
  - type: web
    name: school-membership-system
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn server:app  # ← Make sure this is correct
    envVars:
      - key: SECRET_KEY
        generateValue: true
      - key: DEBUG
        value: False
```

## ✅ Correct Configuration:

Your Procfile is already correct:
```
web: gunicorn server:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
```

But Render might not be reading the Procfile. Setting it manually in the dashboard fixes this.

## 🎯 Expected Result:

After fixing, you should see:
```
✅ Database initialized successfully!
============================================================
🎓 School Membership System Server
============================================================
✅ Server starting
✅ Ready to accept connections
```

And your site will be live!

---

## 📋 Full Render Configuration (Copy These Settings):

**Service Name**: school-membership-system  
**Region**: Frankfurt (Europe) or closest to South Africa  
**Branch**: main  
**Build Command**: `pip install -r requirements.txt`  
**Start Command**: `gunicorn server:app` ← **THIS IS THE KEY!**  

**Environment Variables**:
```
SECRET_KEY = (generate using: python -c "import secrets; print(secrets.token_hex(32))")
DATABASE_PATH = /opt/render/project/src/membership.db
DEBUG = False
```

**Instance Type**: 
- Free (for testing)
- Starter $7/month (for production)

---

## 🔄 If Still Having Issues:

### Check 1: Verify File Structure
Your GitHub repo should have:
```
/
├── server.py          ← Must be in root!
├── static/
│   └── index.html
├── requirements.txt
├── Procfile
└── runtime.txt
```

### Check 2: Verify server.py Has App Variable
At the bottom of server.py, you should have:
```python
app = Flask(__name__, static_folder='static', static_url_path='')
```

### Check 3: Test Locally
Before deploying, test locally:
```bash
pip install -r requirements.txt
gunicorn server:app
# Should start without errors
```

### Check 4: Check Render Logs
In Render dashboard:
- Click "Logs" tab
- Look for the actual error
- Most common: wrong start command

---

## ✅ Once Fixed, Test These:

1. Open your Render URL
2. Should see login page (not error)
3. Try logging in (will fail - no admin yet)
4. Check: `https://your-app.onrender.com/health`
   - Should return: `{"status": "healthy", "timestamp": "..."}`

---

## 🆘 Still Not Working?

### Option 1: Delete and Recreate Service
1. In Render, delete the service
2. Create new web service
3. Connect GitHub repo again
4. **Make sure Start Command is: `gunicorn server:app`**
5. Deploy

### Option 2: Use Different Platform
Try Railway.app instead:
1. Sign up at railway.app
2. "Deploy from GitHub"
3. Select repo
4. Railway auto-detects everything
5. Usually works first time!

---

**After fixing, your site will be live at:**
`https://mhs-membership-system.onrender.com`

**Contact if still stuck:** lesonvisagie@gmail.com