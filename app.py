from flask import Flask, render_template, request, flash, redirect, url_for, jsonify
from flask_pymongo import PyMongo
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import cloudinary
import cloudinary.uploader
from collections import defaultdict
from bson.objectid import ObjectId

# --- NEW: SendGrid Imports ---
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "campuscoin_tracker_2026")

# --- CONFIGURATION ---

# 1. Cloudinary Setup
cloudinary.config( 
    cloud_name = os.environ.get("CLOUDINARY_NAME", "your_cloud_name"), 
    api_key = os.environ.get("CLOUDINARY_KEY", "your_api_key"), 
    api_secret = os.environ.get("CLOUDINARY_SECRET", "your_api_secret") 
)

# 2. MongoDB Setup
app.config["MONGO_URI"] = os.environ.get("MONGO_URI", "mongodb+srv://Pritee:Pritee@cluster0.a5drjzn.mongodb.net/Treasure?retryWrites=true&w=majority")
mongo = PyMongo(app)

# 3. SendGrid Setup
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
SENDER_EMAIL = os.environ.get("MAIL_USER") # This MUST be verified in SendGrid

def send_email(to_email, subject, content):
    """Helper function to send emails via SendGrid API"""
    if not SENDGRID_API_KEY or not SENDER_EMAIL:
        print("❌ Email skipped: SendGrid credentials missing in Environment Variables.")
        return False

    message = Mail(
        from_email=SENDER_EMAIL,
        to_emails=to_email,
        subject=subject,
        plain_text_content=content
    )
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        sg.send(message)
        print(f"📧 Email sent to {to_email}")
        return True
    except Exception as e:
        print(f"❌ SendGrid Error: {e}")
        return False

# Connection Debugger
with app.app_context():
    try:
        mongo.cx.admin.command('ping')
        print("✅ MongoDB Connected to 'Treasure' Database!")
    except Exception as e:
        print(f"❌ MongoDB Connection Failed: {e}")

# --- CORE NAVIGATION ROUTES ---

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/my_profile')
def profile_page():
    return render_template('profile.html')

# --- BUDGET & PROFILE LOGIC ---

@app.route('/verify_profile', methods=['POST'])
def verify_profile():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    user_col = mongo.db.User
    user = user_col.find_one({"username": username})

    if not user:
        hashed_password = generate_password_hash(password)
        user_col.insert_one({
            "username": username,
            "password": hashed_password,
            "monthly_limit": 0,
            "start_date": datetime.utcnow(),
            "current_spend": 0
        })
        return jsonify({"status": "new", "message": "User created. Please set your monthly budget."})

    if check_password_hash(user['password'], password):
        start_date = user.get('start_date')
        if not start_date or datetime.utcnow() > start_date + timedelta(days=30):
            return jsonify({"status": "expired", "message": "Your 30-day budget cycle has ended. Please reset."})
        
        return jsonify({"status": "active", "budget": user['monthly_limit'], "username": username})
    else:
        return jsonify({"status": "error", "message": "Incorrect Password"}), 401

@app.route('/set_budget', methods=['POST'])
def set_budget():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    limit = data.get('limit')
    
    hashed_password = generate_password_hash(password)
    
    mongo.db.User.update_one(
        {"username": username},
        {"$set": {
            "password": hashed_password,
            "monthly_limit": float(limit),
            "start_date": datetime.utcnow(),
            "current_spend": 0
        }},
        upsert=True
    )
    return jsonify({"status": "success", "message": "Budget updated successfully!"})

# --- EXPENSE & LOAN ROUTES ---

@app.route('/my_expenses')
def my_expenses():
    return render_template('expense.html')

@app.route('/add_expense', methods=['POST'])
def add_expense():
    data = request.json
    username = data.get('username') 
    
    expense_data = {
        "username": username,
        "category": data.get('category'),
        "amount": float(data.get('amount')),
        "description": data.get('description'),
        "is_loan": data.get('is_loan'),
        "contact_email": data.get('email'),
        "status": "pending" if data.get('is_loan') else "personal",
        "timestamp": datetime.utcnow()
    }
    
    mongo.db.Expenses.insert_one(expense_data)
    
    # Send email if it's a loan
    if data.get('is_loan') and data.get('email'):
        subject = "Payment Reminder: YourTreasurer"
        body = f"Hi! {username} paid ₹{data.get('amount')} for '{data.get('description')}'. Please return it soon!"
        send_email(data.get('email'), subject, body)

    return jsonify({"status": "success"})

@app.route('/history')
def history_page():
    return render_template('history.html')

@app.route('/get_history/<username>')
def get_history(username):
    history = list(mongo.db.Expenses.find({"username": username}).sort("timestamp", -1))
    for item in history:
        item['_id'] = str(item['_id']) 
    return jsonify(history)

@app.route('/update_loan_status', methods=['POST'])
def update_loan_status():
    data = request.json
    mongo.db.Expenses.update_one(
        {"_id": ObjectId(data.get('id'))},
        {"$set": {"status": "completed"}}
    )
    return jsonify({"status": "success"})

# --- ANALYSIS ROUTES ---

@app.route('/analysis')
def analysis_page():
    return render_template('analysis.html')

@app.route('/api/analysis_data/<username>')
def analysis_data(username):
    expenses = list(mongo.db.Expenses.find({"username": username}))
    
    category_totals = defaultdict(float)
    daily_totals = defaultdict(float)
    
    for e in expenses:
        category_totals[e['category']] += e['amount']
        date_str = e['timestamp'].strftime('%Y-%m-%d')
        daily_totals[date_str] += e['amount']
    
    sorted_dates = sorted(daily_totals.keys())
    sorted_amounts = [daily_totals[d] for d in sorted_dates]

    return jsonify({
        "categories": list(category_totals.keys()),
        "category_amounts": list(category_totals.values()),
        "dates": sorted_dates,
        "daily_amounts": sorted_amounts
    })

# --- INTERVAL SPEND (SUBSCRIPTIONS) ---

@app.route('/interval_spend')
def interval_spend():
    return render_template('interval_spend.html')

@app.route('/add_interval_spend', methods=['POST'])
def add_interval_spend():
    data = request.json
    next_due = datetime.utcnow() + timedelta(days=30)
    
    interval_data = {
        "username": data.get('username'),
        "title": data.get('title'),
        "amount": float(data.get('amount')),
        "category": data.get('category'),
        "email": data.get('email'),
        "next_due": next_due,
        "status": "unpaid" 
    }
    
    mongo.db.IntervalSpends.insert_one(interval_data)
    return jsonify({"status": "success", "message": "Subscription added!"})

@app.route('/pay_interval_bill', methods=['POST'])
def pay_interval_bill():
    data = request.json
    bill_id = data.get('id')
    username = data.get('username')

    bill = mongo.db.IntervalSpends.find_one({"_id": ObjectId(bill_id)})
    new_due = bill['next_due'] + timedelta(days=30)

    mongo.db.IntervalSpends.update_one(
        {"_id": ObjectId(bill_id)},
        {"$set": {"status": "paid", "next_due": new_due}}
    )

    if bill.get('email'):
        subject = f"Payment Confirmed: {bill['title']}"
        body = f"Hello {username}!\n\nYour payment of ₹{bill['amount']} for {bill['title']} has been logged.\n\nNext due: {new_due.strftime('%d %B %Y')}."
        send_email(bill['email'], subject, body)

    return jsonify({"status": "success", "new_date": new_due.strftime('%Y-%m-%d')})

@app.route('/about_us')
def about_us():
    return render_template('about_us.html')

if __name__ == '__main__':
    # Use environment port for Render deployment
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)