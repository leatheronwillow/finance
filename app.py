import os

import sqlite3
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, g
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

load_dotenv()

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Connect to database
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect("finance.db")
    db.row_factory = sqlite3.Row
    return db

# Close database connection after use
@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

def query_db(query, args=(), one=False):
    db = get_db()
    cur = db.execute(query, args)
    result = cur.fetchall()
    db.commit()
    cur.close()
    return (result[0] if result else None) if one else result

# Make sure API key is set
if not os.environ.get("API_KEY"):
   raise RuntimeError("API_KEY not set")


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    """Show portfolio of stocks"""

    # retrieve from users table how much cash the user has left
    user_id = session["user_id"]
    cash = query_db("SELECT cash FROM users WHERE id = ?", [user_id])
    cash = float(cash[0]["cash"])

    # update cash in users if cash has been added i.e., if reached via POST
    if request.method == "POST":
        # check that form is not empty
        if not request.form.get("add_cash"):
            return apology("No value entered for cash", 403)

        # validate that the input is postive
        try:
            add_cash = float(request.form.get("add_cash"))
        except ValueError:
            return apology("Value must be a number", 403)

        if add_cash < 0.01:
            return apology("Value must be positive number", 403)

        # add cash to existing cash and update users table
        cash = cash + add_cash
        query_db("UPDATE users SET cash = ? WHERE id = ?", [cash, user_id])

    # update price of stock
    # select stocks owned by current user
    portfolio = query_db("SELECT * FROM portfolio WHERE user_id = ?", [user_id])

    # loop through to lookup and update the stocks
    for stock in portfolio:

        symbol = stock["symbol"]

        # if shares owned are 0, delete the stock from the portfolio
        if stock["shares_owned"] == 0:
            query_db("DELETE FROM portfolio WHERE user_id = ? AND symbol = ?", [user_id, symbol])

        # otherwise
        quote = lookup(symbol)
        price = quote["price"]
        total_value = price * float(stock["shares_owned"])

        # update the table with new price and value
        query_db("UPDATE portfolio SET price = ?, total_value = ? WHERE user_id = ? AND symbol = ?",
                   [price, total_value, user_id, symbol])

    # select the updated table to pass on to the template
    portfolio = query_db("SELECT * FROM portfolio WHERE user_id = ?", [user_id])

    # sum the total value of all stocks held
    holdings = query_db("SELECT SUM(total_value) AS holdings FROM portfolio WHERE user_id = ?", [user_id])

    try:
        holdings = float(holdings[0]["holdings"])
    except TypeError:
        holdings = float(0)

    grand_total = cash + holdings

    # render template
    return render_template("index.html", portfolio=portfolio, cash=cash, grand_total=grand_total)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""

   # if user registered via POST (i.e. submitted the form)
    if request.method == "POST":

        # Ensure symbol was submitted
        if not request.form.get("symbol"):
            return apology("Please enter symbol", 400)

        try:
            quantity = int(request.form.get("shares"))
        except ValueError:
            return apology("cannot sell fractional shares", 400)

        if quantity < 0:
            return apology("negative number entered for shares to be sold", 400)

        symbol = request.form.get("symbol")

        quote = lookup(symbol)

        # if no stock found with the geiven symbol
        if quote == None:
            return apology("No stock found with given symbol", 400)

        # check that there are enough funds available to make purchase
        user_id = session["user_id"]
        rows = query_db("SELECT cash FROM users WHERE id = ?", [user_id])
        cash = float(rows[0]["cash"])
        price = quote["price"]
        total_cost = quantity * price
        leftover = cash - total_cost

        if leftover < 0:
            return apology("Insufficient funds", 400)

        # if stock is found, retreive the relevant values and assign to variables
        symbol = quote["symbol"]
        purchased_or_sold = "purchased"
        stock_name = symbol

        # insert the transaction into transactions table
        query_db("INSERT INTO transactions (user_id, symbol, stock_name, quantity, price, total_cost, purchased_or_sold) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   [user_id, symbol, stock_name, quantity, price, total_cost, purchased_or_sold])

        # update cash left in users table
        query_db("UPDATE users SET cash = ? WHERE id = ?", [leftover, user_id])

        # update portfolio table

        # check if stock is previously owned
        # if not found, create new entry
        if not query_db("SELECT * FROM portfolio WHERE user_id = ? AND symbol = ?", [user_id, symbol]):
            query_db("INSERT INTO portfolio (user_id, symbol, shares_owned, price, total_value) VALUES (?, ?, ?, ?, ?)",
                       [user_id, symbol, quantity, price, total_cost])

        # if stock previously owned, update relevant fields
        else:
            rows = query_db("SELECT shares_owned FROM portfolio WHERE user_id = ? AND symbol = ?", user_id, symbol)
            shares_owned = rows[0]["shares_owned"]
            shares_owned = shares_owned + quantity
            total_value = float(shares_owned) * price
            query_db("UPDATE portfolio SET shares_owned = ?, price = ?, total_value = ? WHERE user_id = ? AND symbol = ?",
                       [shares_owned, price, total_value, user_id, symbol])

        return redirect("/")

    # if reached via GET
    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""

    # select transactions by current user
    user_id = session["user_id"]
    transactions = query_db("SELECT * FROM transactions WHERE user_id = ? ORDER BY transaction_id ASC", [user_id])

    # render template
    return render_template("history.html", transactions=transactions)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = query_db("SELECT * FROM users WHERE username = ?", [request.form.get("username")])

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""

    # if user registered via POST (i.e. submitted the form)
    if request.method == "POST":

        # Ensure symbol was submitted
        if not request.form.get("symbol"):
            return apology("Please enter symbol", 400)

        symbol = request.form.get("symbol")

        # look up the symbol using the function from helpers.
        quote = lookup(symbol)

        # if a stock with the given symbol doesn't exist
        if quote == None:
            return apology("No stock found with given symbol", 400)

        # if stock is found, retreive the relevant values and assign to variables
        price = quote["price"]
        symbol = quote["symbol"]

        return render_template("quoted.html", price=price, symbol=symbol)

    # if user reached page via get
    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    # if user registered via POST (i.e. submitted the form)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 400)

        elif query_db("SELECT username FROM users WHERE username = ?", [request.form.get("username")], one=True):
            return apology("Username already exists", 400)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 400)

        # Ensure confirmation was submitted
        elif not request.form.get("confirmation"):
            return apology("must provide password confirmation", 400)

        elif request.form.get("confirmation") != request.form.get("password"):
            return apology("Confirmation does not match password", 400)

        # generate password hash
        hash = generate_password_hash(request.form.get("password"))

        username = str(request.form.get("username"))

        # Insert values for username and password hash into database
        query_db("INSERT INTO users (username, hash) VALUES (?, ?)", [username, hash])

        return redirect("/")

    # user reached via GET
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""

    # if reached via POST method
    if request.method == "POST":

        # check symbol is provided
        if not request.form.get("symbol"):
            return apology("symbol not entered", 400)

        user_id = session["user_id"]
        symbol = request.form.get("symbol")

        # check that the user owns the stock
        stock = query_db("SELECT * FROM portfolio WHERE user_id = ? AND symbol = ?", [user_id, symbol])
        if len(stock) != 1:
            return apology("stock record could not be found", 400)

        if not request.form.get("shares"):
            return apology("number of shares not entered")

        shares_owned = int(stock[0]["shares_owned"])
        try:
            shares_sold = int(request.form.get("shares"))
        except ValueError:
            return apology("cannot sell fractional shares", 400)

        if shares_sold < 0:
            return apology("negative number entered for shares to be sold", 400)

        if shares_owned < shares_sold:
            return apology("cannot sell more shares than you own", 400)

        quote = lookup(symbol)
        stock_name = quote["symbol"]
        quantity = shares_sold
        price = quote["price"]
        total_cost = price * quantity
        purchased_or_sold = "sold"
        cash = query_db("SELECT cash FROM users WHERE id = ?", [user_id])
        cash = float(cash[0]["cash"])
        updated_cash = cash + total_cost
        shares_owned = shares_owned - shares_sold
        total_value = shares_owned * price

        # insert the transaction into transactions table
        query_db("INSERT INTO transactions (user_id, symbol, stock_name, quantity, price, total_cost, purchased_or_sold) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   [user_id, symbol, stock_name, quantity, price, total_cost, purchased_or_sold])

        # update cash in users table
        query_db("UPDATE users SET cash = ? WHERE id = ?", [updated_cash, user_id])

        # update portfolio
        if shares_owned == 0:
            query_db("DELETE FROM portfolio WHERE user_id = ? AND symbol = ?", [user_id, symbol])
        else:
            query_db("UPDATE portfolio SET shares_owned = ?, price = ?, total_value = ? WHERE user_id = ? AND symbol = ?",
                       [shares_owned, price, total_value, user_id, symbol])

        return redirect("/")

    # if reached via GET method
    else:
        user_id = session["user_id"]
        portfolio = query_db("SELECT * from portfolio WHERE user_id = ?", [user_id])
        return render_template("sell.html", portfolio=portfolio)