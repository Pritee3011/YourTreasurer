from flask import Flask, render_template, request, flash, redirect, url_for, jsonify, session
from flask_pymongo import PyMongo
from flask_mail import Mail, Message
from werkzeug.utils import secure_filename
import os
from dotenv import load_dotenv
import uuid 
import threading
import time
import cloudinary
import cloudinary.uploader
from datetime import datetime, timedelta
from bson.objectid import ObjectId
import certifi

app = Flask(__name__)
app.secret_key = "campuscoin_tracker_2026"
load_dotenv()

# --- CONFIGURATION ---

# 1. Cloudinary Setup (Participants will use this for receipt uploads)
cloudinary.config( 
    cloud_name = os.environ.get("CLOUDINARY_NAME", "your_cloud_name"), 
    api_key = os.environ.get("CLOUDINARY_KEY", "your_api_key"), 
    api_secret = os.environ.get("CLOUDINARY_SECRET", "your_api_secret") 
)

# 2. MongoDB & Mail Setup
app.config["MONGO_URI"] = os.environ.get("MONGO_URI", "mongodb+srv://priteepardeshi3011_db_user:o1UpyYozHv4zvlTn@cluster0.a5drjzn.mongodb.net/yourtreasurer?retryWrites=true&w=majority")
mongo = PyMongo(app, tlsCAFile=certifi.where(), tlsAllowInvalidCertificates=True)

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USER", 'your_email@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASS", 'your_app_password') 
mail = Mail(app)

app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024 # 5MB limit for receipts

# --- ASYNC BACKGROUND TASKS ---

def send_async_email(app, msg):
    """Function to send email in a background thread to prevent UI freezing."""
    with app.app_context():
        try:
            mail.send(msg)
            print("Email sent successfully!")
        except Exception as e:
            print(f"Background Mail Error: {e}")

# --- GLOBAL CHECKS ---

@app.before_request
def check_budget_setup():
    """
    Task 1: Check if the user has set up their initial monthly budget.
    If they haven't (and they aren't on static/profile pages), redirect them to MyProfile.
    """
    allowed_endpoints = ['my_profile', 'static']
    if request.endpoint and request.endpoint not in allowed_endpoints:
        if 'username' not in session or 'password' not in session:
            return redirect(url_for('my_profile'))
            
        user = mongo.db.users.find_one({
            "username": session['username'],
            "password": session['password']
        })
        
        if not user:
            session.clear()
            return redirect(url_for('my_profile'))
            
        # 30-Day Temporal Reset Logic
        start_date = user.get('start_date')
        if start_date:
            days_passed = (datetime.now() - start_date).days
            if days_passed >= 30:
                # Archive expenses
                mongo.db.daily_expenses.update_many(
                    {"username": user['username'], "archived": {"$ne": True}},
                    {"$set": {"archived": True}}
                )
                # Reset budget start date
                mongo.db.users.update_one(
                    {"_id": user['_id']},
                    {"$set": {"start_date": datetime.now()}}
                )

# --- CORE NAVIGATION ROUTES ---

@app.route('/')
def home():
    # TODO: Fetch today's expenses to show a quick summary on the home dashboard
    return render_template('index.html')

@app.route('/my_profile', methods=['GET', 'POST'])
def my_profile():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        monthly_limit = request.form.get('monthly_limit')
        
        if not username or not password:
            flash("Name and Password are required!")
            return redirect(url_for('my_profile'))
            
        user = mongo.db.users.find_one({"username": username})
        
        if user:
            # Login
            if user['password'] == password:
                session['username'] = username
                session['password'] = password
                flash("Login successful! Welcome back.", "success")
                return redirect(url_for('home'))
            else:
                flash("Invalid credentials.", "error")
                return redirect(url_for('my_profile'))
        else:
            # New user setup
            if not monthly_limit:
                flash("Please set a monthly limit for a new account.", "error")
                return redirect(url_for('my_profile'))
                
            mongo.db.users.insert_one({
                "username": username,
                "password": password,
                "monthly_limit": float(monthly_limit),
                "start_date": datetime.now(),
                "created_at": datetime.now()
            })
            session['username'] = username
            session['password'] = password
            flash("Account created! Let's manage your budget.", "success")
            return redirect(url_for('home'))
            
    # GET request
    user_data = None
    if 'username' in session and 'password' in session:
        user_data = mongo.db.users.find_one({"username": session['username'], "password": session['password']})

    return render_template('profile.html', user=user_data)

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for('my_profile'))

@app.route('/my_expenses')
def my_expenses():
    if 'username' not in session:
        return redirect(url_for('my_profile'))
        
    username = session['username']
    expenses_cursor = mongo.db.daily_expenses.find({"username": username, "archived": {"$ne": True}}).sort("date", -1)
    expenses = list(expenses_cursor)
    
    if len(expenses) == 0:
        # Insert 8 dummy expenses to prove functionality
        dummy_data = [
            {"username": username, "category": "Junk Food", "amount": 150, "is_loan": False, "date": datetime.now(), "archived": False},
            {"username": username, "category": "Educational", "amount": 800, "is_loan": False, "date": datetime.now(), "archived": False},
            {"username": username, "category": "Travel", "amount": 250, "is_loan": False, "date": datetime.now(), "archived": False},
            {"username": username, "category": "Hostel Rent", "amount": 5000, "is_loan": False, "date": datetime.now(), "archived": False},
            {"username": username, "category": "Lifestyle", "amount": 1500, "is_loan": False, "date": datetime.now(), "archived": False},
            {"username": username, "category": "Healthy Food", "amount": 300, "is_loan": False, "date": datetime.now(), "archived": False},
            {"username": username, "category": "Other", "amount": 100, "is_loan": True, "friend_email": "friend1@example.com", "friend_relationship": "classmate", "returned": False, "date": datetime.now(), "archived": False},
            {"username": username, "category": "Junk Food", "amount": 200, "is_loan": True, "friend_email": "friend2@example.com", "friend_relationship": "roommate", "returned": False, "date": datetime.now(), "archived": False}
        ]
        mongo.db.daily_expenses.insert_many(dummy_data)
        # Fetch again to get the inserted ObjectIds
        expenses_cursor = mongo.db.daily_expenses.find({"username": username, "archived": {"$ne": True}}).sort("date", -1)
        expenses = list(expenses_cursor)
        
    return render_template('expenses.html', expenses=expenses)

@app.route('/about_us')
def about_us():
    return render_template('about_us.html')

# --- DATA SUBMISSION ROUTES (THE LOGIC) ---

@app.route('/add_expense', methods=['POST'])
def add_expense():
    """Handles adding a new daily expense."""
    try:
        category = request.form.get('category')
        amount = float(request.form.get('amount', 0))
        is_loan = request.form.get('is_loan') == 'yes'
        friend_email = request.form.get('friend_email')
        friend_relationship = request.form.get('friend_relationship')
        
        expense_doc = {
            "username": session['username'],
            "category": category,
            "amount": amount,
            "is_loan": is_loan,
            "date": datetime.now(),
            "archived": False
        }
        
        if is_loan:
            expense_doc.update({
                "friend_email": friend_email,
                "friend_relationship": friend_relationship,
                "returned": False
            })

        mongo.db.daily_expenses.insert_one(expense_doc)
        flash('Expense tracked successfully!', 'success')
        return redirect(url_for('my_expenses'))
    except Exception as e:
        print(f"Expense Submit Error: {e}")
        return f"Submission failed: {e}", 500




@app.errorhandler(413)
def request_entity_too_large(error):
    return "<h1>Receipt file is too large!</h1><p>Please keep your screenshot under 5MB.</p><a href='/my_expenses'>Try Again</a>", 413

if __name__ == '__main__':
    app.run(debug=True, port=5000)