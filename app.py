import os
import re
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import certifi
import cloudinary
import cloudinary.uploader
from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_mail import Mail, Message
from flask_pymongo import PyMongo
from pymongo.errors import PyMongoError
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

app = Flask(__name__, template_folder="Templates", static_folder="Static", static_url_path="/static")
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024


def build_mongo_uri_with_timeouts(raw_uri):
    split_result = urlsplit(raw_uri)
    query = dict(parse_qsl(split_result.query, keep_blank_values=True))
    query.setdefault("serverSelectionTimeoutMS", "4000")
    query.setdefault("connectTimeoutMS", "4000")
    query.setdefault("socketTimeoutMS", "4000")
    return urlunsplit(
        (
            split_result.scheme,
            split_result.netloc,
            split_result.path,
            urlencode(query),
            split_result.fragment,
        )
    )


raw_mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017/yourtreasurer")
app.config["MONGO_URI"] = build_mongo_uri_with_timeouts(raw_mongo_uri)
app.config["MONGO_DBNAME"] = os.environ.get("MONGO_DBNAME", "yourtreasurer")

app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", "587"))
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME", os.environ.get("MAIL_USER", ""))
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD", os.environ.get("MAIL_PASS", ""))
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER", app.config["MAIL_USERNAME"])

mongo = PyMongo(app, tlsCAFile=certifi.where())
mail = Mail(app)

cloudinary_url = os.environ.get("CLOUDINARY_URL")
if cloudinary_url:
    cloudinary.config(cloudinary_url=cloudinary_url)
else:
    cloudinary.config(
        cloud_name=os.environ.get("CLOUDINARY_NAME"),
        api_key=os.environ.get("CLOUDINARY_KEY"),
        api_secret=os.environ.get("CLOUDINARY_SECRET"),
    )


def users_collection():
    return mongo.db.users


def daily_expenses_collection():
    return mongo.db.daily_expenses


def recurring_payments_collection():
    return mongo.db.recurring_payments


def is_name_valid(name):
    return bool(re.fullmatch(r"[A-Za-z ]+", name or ""))


def is_password_valid(password):
    if len(password or "") < 8:
        return False
    return (
        any(ch.isupper() for ch in password)
        and any(ch.islower() for ch in password)
        and any(ch.isdigit() for ch in password)
        and any(not ch.isalnum() for ch in password)
    )


def current_user_name():
    return session.get("user_name")


def current_user_doc():
    user_name = current_user_name()
    if not user_name:
        return None
    return users_collection().find_one({"name": user_name})


def login_required():
    if not session.get("user_name"):
        return redirect(url_for("my_profile"))
    return None


def parse_date(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def maybe_reset_monthly_cycle(user_doc):
    start_date = parse_date(user_doc.get("start_date")) or datetime.utcnow()
    if datetime.utcnow() <= start_date + timedelta(days=30):
        return user_doc

    users_collection().update_one(
        {"_id": user_doc["_id"]},
        {
            "$set": {
                "current_spend": 0.0,
                "start_date": datetime.utcnow(),
                "alert_flags": {"ten_sent": False, "five_sent": False},
            }
        },
    )
    user_doc["current_spend"] = 0.0
    user_doc["start_date"] = datetime.utcnow()
    user_doc["alert_flags"] = {"ten_sent": False, "five_sent": False}
    return user_doc


def send_email_safe(subject, recipients, body):
    if not app.config["MAIL_USERNAME"] or not app.config["MAIL_PASSWORD"]:
        return False
    try:
        msg = Message(subject=subject, recipients=recipients, body=body)
        mail.send(msg)
        return True
    except Exception:
        return False


def send_guardian_alerts(user_doc, last_added_amount):
    monthly_limit = float(user_doc.get("monthly_limit", 0) or 0)
    if monthly_limit <= 0:
        return

    current_spend = float(user_doc.get("current_spend", 0) or 0)
    remaining = monthly_limit - current_spend
    ratio_left = (remaining / monthly_limit) * 100
    flags = user_doc.get("alert_flags", {"ten_sent": False, "five_sent": False})

    user_email = user_doc.get("email")
    if not user_email:
        return

    update_fields = {}
    if ratio_left <= 10 and ratio_left > 5 and not flags.get("ten_sent"):
        sent = send_email_safe(
            "YourTreasurer Guardian Alert: 10% budget left",
            [user_email],
            f"Hi {user_doc['name']}, only around 10% budget is left. Last expense: Rs.{last_added_amount:.2f}",
        )
        if sent:
            update_fields["alert_flags.ten_sent"] = True

    if ratio_left <= 5 and ratio_left > 0 and not flags.get("five_sent"):
        sent = send_email_safe(
            "YourTreasurer Guardian Alert: 5% budget left",
            [user_email],
            f"Critical warning {user_doc['name']}: only 5% budget remains.",
        )
        if sent:
            update_fields["alert_flags.five_sent"] = True

    if ratio_left <= 0:
        send_email_safe(
            "YourTreasurer Guardian Alert: Over budget",
            [user_email],
            f"Stop alert! You are over budget by Rs.{abs(remaining):.2f}. New expense: Rs.{last_added_amount:.2f}",
        )

    if update_fields:
        users_collection().update_one({"_id": user_doc["_id"]}, {"$set": update_fields})


def ensure_seed_expenses(user_name):
    existing_count = daily_expenses_collection().count_documents({"created_by": user_name})
    if existing_count >= 8:
        return

    now = datetime.utcnow()
    seed = [
        {"category": "Junk Food", "amount": 120.0, "created_by": user_name, "created_at": now - timedelta(days=1)},
        {"category": "Educational", "amount": 520.0, "created_by": user_name, "created_at": now - timedelta(days=2)},
        {"category": "Travel", "amount": 200.0, "created_by": user_name, "created_at": now - timedelta(days=3)},
        {"category": "Hostel Rent", "amount": 4200.0, "created_by": user_name, "created_at": now - timedelta(days=4)},
        {"category": "Lifestyle", "amount": 640.0, "created_by": user_name, "created_at": now - timedelta(days=5)},
        {"category": "Healthy Food", "amount": 300.0, "created_by": user_name, "created_at": now - timedelta(days=6)},
        {
            "category": "Other",
            "amount": 220.0,
            "created_by": user_name,
            "created_at": now - timedelta(days=7),
            "is_loan": True,
            "friend_name": "Rahul",
            "friend_email": "friend@example.com",
            "friend_relationship": "Classmate",
            "loan_status": "pending",
        },
        {"category": "Travel", "amount": 150.0, "created_by": user_name, "created_at": now - timedelta(days=8)},
    ]
    daily_expenses_collection().insert_many(seed)


def recurring_due_date(year, month, due_day):
    safe_day = max(1, min(int(due_day), 28))
    return datetime(year, month, safe_day)


def run_recurring_reminder_check(user_doc):
    if not user_doc.get("email"):
        return

    today = datetime.utcnow().date()
    cursor = recurring_payments_collection().find({"created_by": user_doc["name"]})
    for item in cursor:
        due_day = int(item.get("due_day", 1))
        remind_before = int(item.get("reminder_days", 1))
        due_this_month = recurring_due_date(today.year, today.month, due_day).date()
        reminder_date = due_this_month - timedelta(days=remind_before)
        if today == reminder_date:
            send_email_safe(
                "Recurring payment reminder",
                [user_doc["email"]],
                f"{item.get('item_name')} is due on {due_this_month.isoformat()} for Rs.{float(item.get('amount', 0)):.2f}",
            )


@app.route("/")
def home():
    if not current_user_name():
        return redirect(url_for("my_profile"))
    return render_template("index.html")


@app.route("/my_profile")
@app.route("/profile")
def my_profile():
    return render_template("profile.html")


@app.route("/login", methods=["POST"])
def login():
    payload = request.get_json(silent=True) or request.form
    name = (payload.get("name") or "").strip()
    password = payload.get("password") or ""

    if not name or not password:
        return jsonify({"success": False, "message": "Name and password are required."}), 400

    user_doc = users_collection().find_one({"name": name})
    if not user_doc:
        return jsonify({"success": False, "needs_signup": True, "message": "User not found. Please sign up first."}), 404

    if not check_password_hash(user_doc.get("password", ""), password):
        return jsonify({"success": False, "message": "Invalid credentials."}), 401

    user_doc = maybe_reset_monthly_cycle(user_doc)
    run_recurring_reminder_check(user_doc)

    session["user_name"] = user_doc["name"]
    session["user_id"] = str(user_doc["_id"])
    return jsonify(
        {
            "success": True,
            "message": "Login successful.",
            "redirect_url": url_for("home"),
            "user": {
                "name": user_doc["name"],
                "monthly_limit": float(user_doc.get("monthly_limit", 0) or 0),
                "current_spend": float(user_doc.get("current_spend", 0) or 0),
            },
        }
    )


@app.route("/signup", methods=["POST"])
def signup():
    payload = request.get_json(silent=True) or request.form
    name = (payload.get("name") or "").strip()
    password = payload.get("password") or ""
    monthly_limit_raw = payload.get("monthly_limit")
    email = (payload.get("email") or "").strip().lower()

    if not is_name_valid(name):
        return jsonify({"success": False, "message": "Name must contain only letters and spaces."}), 400
    if not is_password_valid(password):
        return jsonify(
            {
                "success": False,
                "message": "Password must contain uppercase, lowercase, number and special character.",
            }
        ), 400

    try:
        monthly_limit = float(monthly_limit_raw)
        if monthly_limit <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Monthly limit must be greater than zero."}), 400

    if users_collection().find_one({"name": name}):
        return jsonify({"success": False, "message": "User already exists."}), 409

    user_doc = {
        "name": name,
        "email": email,
        "password": generate_password_hash(password),
        "monthly_limit": monthly_limit,
        "current_spend": 0.0,
        "start_date": datetime.utcnow(),
        "alert_flags": {"ten_sent": False, "five_sent": False},
        "created_at": datetime.utcnow(),
    }
    inserted = users_collection().insert_one(user_doc)
    session["user_name"] = name
    session["user_id"] = str(inserted.inserted_id)
    return jsonify({"success": True, "message": "Profile created.", "redirect_url": url_for("home")})


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("my_profile"))


@app.route("/add_expense", methods=["POST"])
def add_expense():
    guard = login_required()
    if guard:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    payload = request.form
    category = (payload.get("category") or "").strip()
    spent_at = (payload.get("spent_at") or "").strip()
    friend_name = (payload.get("friend_name") or "").strip()
    friend_email = (payload.get("friend_email") or "").strip()
    friend_relationship = (payload.get("friend_relationship") or "").strip()
    is_loan = payload.get("is_loan") == "yes"

    try:
        amount = float(payload.get("amount", "0"))
        if amount <= 0:
            raise ValueError
    except ValueError:
        return jsonify({"success": False, "message": "Invalid amount."}), 400

    receipt_url = ""
    file = request.files.get("receipt")
    if file and file.filename:
        try:
            uploaded = cloudinary.uploader.upload(file, folder="yourtreasurer/receipts")
            receipt_url = uploaded.get("secure_url", "")
        except Exception:
            receipt_url = ""

    user_name = current_user_name()
    expense_doc = {
        "created_by": user_name,
        "category": category,
        "amount": amount,
        "spent_at": spent_at,
        "is_loan": is_loan,
        "friend_name": friend_name if is_loan else "",
        "friend_email": friend_email if is_loan else "",
        "friend_relationship": friend_relationship if is_loan else "",
        "loan_status": "pending" if is_loan else "",
        "receipt_url": receipt_url,
        "created_at": datetime.utcnow(),
    }
    daily_expenses_collection().insert_one(expense_doc)

    users_collection().update_one({"name": user_name}, {"$inc": {"current_spend": amount}})
    user_doc = users_collection().find_one({"name": user_name})
    send_guardian_alerts(user_doc, amount)

    if is_loan and friend_email:
        send_email_safe(
            f"Loan handshake from {user_name}",
            [friend_email],
            f"Hi {friend_name or 'friend'}, this is a record that {user_name} lent you Rs.{amount:.2f}.",
        )

    return jsonify({"success": True, "message": "Expense logged successfully."})


@app.route("/my_expenses")
def my_expenses():
    guard = login_required()
    if guard:
        return guard

    user_name = current_user_name()
    ensure_seed_expenses(user_name)
    expenses = list(daily_expenses_collection().find({"created_by": user_name}).sort("created_at", -1))
    for item in expenses:
        item["_id"] = str(item["_id"])
    return render_template("expenses.html", expenses=expenses)


@app.route("/delete_expense/<expense_id>", methods=["POST"])
def delete_expense(expense_id):
    guard = login_required()
    if guard:
        return redirect(url_for("my_profile"))

    try:
        oid = ObjectId(expense_id)
    except (InvalidId, TypeError):
        flash("Invalid expense id.", "error")
        return redirect(url_for("my_expenses"))

    user_name = current_user_name()
    expense = daily_expenses_collection().find_one({"_id": oid, "created_by": user_name})
    if not expense:
        flash("Expense not found.", "error")
        return redirect(url_for("my_expenses"))

    amount = float(expense.get("amount", 0) or 0)
    daily_expenses_collection().delete_one({"_id": oid})
    users_collection().update_one({"name": user_name}, {"$inc": {"current_spend": -amount}})
    flash("Expense deleted.", "success")
    return redirect(url_for("my_expenses"))


@app.route("/mark_returned/<expense_id>", methods=["POST"])
def mark_returned(expense_id):
    guard = login_required()
    if guard:
        return redirect(url_for("my_profile"))

    try:
        oid = ObjectId(expense_id)
    except (InvalidId, TypeError):
        flash("Invalid loan id.", "error")
        return redirect(url_for("my_expenses"))

    user_name = current_user_name()
    loan_expense = daily_expenses_collection().find_one({"_id": oid, "created_by": user_name, "is_loan": True})
    if not loan_expense:
        flash("Loan entry not found.", "error")
        return redirect(url_for("my_expenses"))

    if loan_expense.get("loan_status") == "returned":
        flash("Already marked returned.", "info")
        return redirect(url_for("my_expenses"))

    amount = float(loan_expense.get("amount", 0) or 0)
    daily_expenses_collection().update_one({"_id": oid}, {"$set": {"loan_status": "returned", "returned_at": datetime.utcnow()}})
    daily_expenses_collection().insert_one(
        {
            "created_by": user_name,
            "category": "Loan Return",
            "amount": -amount,
            "is_loan": False,
            "spent_at": "Loan settled",
            "created_at": datetime.utcnow(),
        }
    )
    users_collection().update_one({"name": user_name}, {"$inc": {"current_spend": -amount}})
    flash("Loan marked as returned.", "success")
    return redirect(url_for("my_expenses"))


@app.route("/remind_friend/<expense_id>", methods=["POST"])
def remind_friend(expense_id):
    guard = login_required()
    if guard:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    try:
        oid = ObjectId(expense_id)
    except (InvalidId, TypeError):
        return jsonify({"success": False, "message": "Invalid id"}), 400

    user_name = current_user_name()
    expense = daily_expenses_collection().find_one({"_id": oid, "created_by": user_name, "is_loan": True})
    if not expense:
        return jsonify({"success": False, "message": "Loan not found"}), 404
    if not expense.get("friend_email"):
        return jsonify({"success": False, "message": "Friend email missing"}), 400

    sent = send_email_safe(
        "Gentle loan reminder",
        [expense["friend_email"]],
        f"Hi {expense.get('friend_name') or 'friend'}, reminder that Rs.{float(expense.get('amount', 0)):.2f} is pending with {user_name}.",
    )
    return jsonify({"success": sent, "message": "Reminder sent." if sent else "Failed to send reminder."})


@app.route("/analysis")
def analysis():
    guard = login_required()
    if guard:
        return guard
    return render_template("analysis.html")


@app.route("/api/stats")
def api_stats():
    guard = login_required()
    if guard:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    user_name = current_user_name()
    pipeline = [
        {"$match": {"created_by": user_name}},
        {"$group": {"_id": "$category", "total": {"$sum": "$amount"}}},
        {"$sort": {"total": -1}},
    ]
    rows = list(daily_expenses_collection().aggregate(pipeline))
    categories = [row["_id"] or "Other" for row in rows]
    amounts = [float(row["total"]) for row in rows]
    return jsonify({"success": True, "categories": categories, "amounts": amounts})


@app.route("/api/trend")
def api_trend():
    guard = login_required()
    if guard:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    user_name = current_user_name()
    now = datetime.utcnow()
    start_of_today = datetime(now.year, now.month, now.day)
    start_of_window = start_of_today - timedelta(days=29)

    day_pipeline = [
        {"$match": {"created_by": user_name, "created_at": {"$gte": start_of_today}}},
        {"$group": {"_id": {"$hour": "$created_at"}, "total": {"$sum": "$amount"}}},
    ]
    month_pipeline = [
        {"$match": {"created_by": user_name, "created_at": {"$gte": start_of_window}}},
        {
            "$group": {
                "_id": {
                    "y": {"$year": "$created_at"},
                    "m": {"$month": "$created_at"},
                    "d": {"$dayOfMonth": "$created_at"},
                },
                "total": {"$sum": "$amount"},
            }
        },
    ]

    day_rows = {int(row["_id"]): float(row["total"]) for row in daily_expenses_collection().aggregate(day_pipeline)}
    day_labels = [f"{hour:02d}:00" for hour in range(24)]
    day_values = [day_rows.get(hour, 0.0) for hour in range(24)]

    month_rows = {}
    for row in daily_expenses_collection().aggregate(month_pipeline):
        key = f"{int(row['_id']['y']):04d}-{int(row['_id']['m']):02d}-{int(row['_id']['d']):02d}"
        month_rows[key] = float(row["total"])
    month_labels = []
    month_values = []
    for i in range(30):
        dt = start_of_window + timedelta(days=i)
        key = dt.strftime("%Y-%m-%d")
        month_labels.append(dt.strftime("%d %b"))
        month_values.append(month_rows.get(key, 0.0))

    return jsonify(
        {
            "success": True,
            "day": {"labels": day_labels, "values": day_values},
            "month": {"labels": month_labels, "values": month_values},
        }
    )


@app.route("/api/progress")
def api_progress():
    guard = login_required()
    if guard:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    user_doc = current_user_doc()
    monthly_limit = float(user_doc.get("monthly_limit", 0) or 0)
    current_spend = float(user_doc.get("current_spend", 0) or 0)
    progress = (current_spend / monthly_limit) * 100 if monthly_limit > 0 else 0
    over_budget = progress >= 100
    return jsonify(
        {
            "success": True,
            "spent": current_spend,
            "limit": monthly_limit,
            "progress": progress,
            "over_budget": over_budget,
        }
    )


@app.route("/interval_spend")
def interval_spend():
    guard = login_required()
    if guard:
        return guard

    user_name = current_user_name()
    today = datetime.utcnow().date()
    recurring_items = []
    for item in recurring_payments_collection().find({"created_by": user_name}).sort("due_day", 1):
        due = recurring_due_date(today.year, today.month, int(item.get("due_day", 1))).date()
        days_left = (due - today).days
        item["days_left"] = days_left
        recurring_items.append(item)
    return render_template("interval_spend.html", recurrings=recurring_items)


@app.route("/add_recurring", methods=["POST"])
def add_recurring():
    guard = login_required()
    if guard:
        return redirect(url_for("my_profile"))

    try:
        amount = float(request.form.get("amount", "0"))
        due_day = int(request.form.get("due_day", "1"))
        reminder_days = int(request.form.get("reminder_days", "1"))
        if amount <= 0:
            raise ValueError
    except ValueError:
        flash("Please enter valid recurring values.", "error")
        return redirect(url_for("interval_spend"))

    recurring_payments_collection().insert_one(
        {
            "created_by": current_user_name(),
            "item_name": (request.form.get("item_name") or "").strip(),
            "amount": amount,
            "due_day": due_day,
            "reminder_days": reminder_days,
            "created_at": datetime.utcnow(),
        }
    )
    flash("Recurring spend added.", "success")
    return redirect(url_for("interval_spend"))


@app.route("/about_us")
def about_us():
    return render_template("about_us.html")


if __name__ == "__main__":
    app.run(debug=True)