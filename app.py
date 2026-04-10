from flask import Flask, render_template, request, redirect, session, jsonify
from flask_pymongo import PyMongo
from datetime import datetime
from bson.objectid import ObjectId

app = Flask(__name__)
app.secret_key = "secret123"

# MongoDB
app.config["MONGO_URI"] = "mongodb+srv://onkarghadage1107_db_user:cPfYrgcDoaCdkOlz@cluster0.gs7ggdy.mongodb.net/yourtreasurer"
mongo = PyMongo(app)

users = mongo.db.users
expenses = mongo.db.expenses
loans = mongo.db.loans


# ---------------- LOGIN ---------------- #
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        name = request.form['name']
        password = request.form['password']
        limit = request.form.get('monthly_limit', 0)

        user = users.find_one({"name": name})

        if not user:
            users.insert_one({
                "name": name,
                "password": password,
                "monthly_limit": int(limit),
                "current_spend": 0
            })
            session['user'] = name
            return redirect('/')

        if user['password'] == password:
            session['user'] = name
            return redirect('/')

    return render_template("profile.html")


# ---------------- HOME ---------------- #
@app.route('/')
def home():
    if "user" not in session:
        return redirect('/login')
    return render_template("index.html", user=session.get("user"))


# ---------------- PROGRESS API ---------------- #
@app.route('/api/progress')
def progress():
    user = users.find_one({"name": session["user"]})

    spent = user.get("current_spend",0)
    limit = user.get("monthly_limit",1)

    percent = (spent/limit)*100

    return jsonify({
        "progress": percent,
        "spent": spent,
        "limit": limit
    })


# ---------------- EXPENSE PAGE ---------------- #
@app.route('/my_expenses')
def my_expenses():
    exp = list(expenses.find({"user": session["user"]}))
    loan_data = list(loans.find({"user": session["user"]}))

    return render_template("expenses.html", expenses=exp, loans=loan_data)


# ---------------- ADD EXPENSE ---------------- #
@app.route('/add_expense', methods=['POST'])
def add_expense():
    amount = int(request.form['amount'])

    expenses.insert_one({
        "user": session["user"],
        "amount": amount,
        "category": request.form['category'],
        "date": datetime.now()
    })

    users.update_one(
        {"name": session["user"]},
        {"$inc": {"current_spend": amount}}
    )

    return redirect('/my_expenses')


# ---------------- ADD LOAN ---------------- #
@app.route('/add_loan', methods=['POST'])
def add_loan():
    loans.insert_one({
        "user": session["user"],
        "friend_name": request.form['friend_name'],
        "amount": int(request.form['amount']),
        "status": "pending"
    })
    return redirect('/my_expenses')


# ---------------- MARK RETURN ---------------- #
@app.route('/mark_returned/<loan_id>', methods=['POST'])
def mark_returned(loan_id):

    loan = loans.find_one({"_id": ObjectId(loan_id)})

    loans.update_one(
        {"_id": ObjectId(loan_id)},
        {"$set": {"status":"returned"}}
    )

    amount = loan['amount']

    expenses.insert_one({
        "user": session["user"],
        "amount": -amount,
        "category": "Loan Return",
        "date": datetime.now()
    })

    users.update_one(
        {"name": session["user"]},
        {"$inc": {"current_spend": -amount}}
    )

    return redirect('/my_expenses')


# ---------------- LOGOUT ---------------- #
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


if __name__ == "__main__":
    app.run(debug=True)