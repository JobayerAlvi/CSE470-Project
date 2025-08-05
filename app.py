from flask import Flask, request, redirect, render_template, flash, url_for, make_response, jsonify
import pymysql
import bcrypt
import datetime
import random
from datetime import datetime, date, timedelta
import string
import threading
from time import sleep
from decimal import Decimal
import logging
import time
import traceback
from flask import jsonify
from flask import jsonify, session
from dateutil.relativedelta import relativedelta
import os
from flask import send_file, request, redirect
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
import os
from werkzeug.utils import secure_filename



logging.basicConfig(level=logging.DEBUG)
app = Flask(__name__)
app.secret_key = 'your_secret_key_here' 

db = pymysql.connect(
    host="localhost",
    user="root",
    password="",
    database=" ",
    cursorclass=pymysql.cursors.DictCursor  
)
#user_signup
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html")
    try:
        firstName = request.form.get("firstName")
        lastName = request.form.get("lastName")
        dob = request.form.get("dob")
        email = request.form.get("email")
        phone = request.form.get("phone")
        nid = request.form.get("nid")
        password = request.form.get("password")
        # Validating phone number 
        if len(phone) != 11 or not phone.startswith("01"):
            return render_template("signup.html", error="Enter a valid 11-digit phone number starting with '01'.")
        try:
            dob_date = datetime.strptime(dob, "%Y-%m-%d").date()
        except ValueError:
            return render_template("signup.html", error="Invalid DOB format. Use YYYY-MM-DD.")
        # Checking if the phone number already exists
        with db.cursor() as cursor:
            cursor.execute("SELECT * FROM user_profile WHERE phone_number = %s", (phone,))
            existing_user = cursor.fetchone()
            if existing_user:
                return render_template("signup.html", phone_error="Phone number already in use")
        hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        with db.cursor() as cursor:
            cursor.execute("""INSERT INTO user_profile (first_name, last_name, dob, email, phone_number, nid, password, balance, points, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 1000, 0, 'active')""", 
                (firstName, lastName, dob_date, email, phone, nid, hashed_password.decode()))
            db.commit()
        return redirect("/login")
    except Exception as e:
        return render_template("signup.html", error=f"Signup error: {str(e)}")

#user_login
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    phone = request.form.get("phone")
    password = request.form.get("password")
    if not phone or len(phone) != 11 or not phone.startswith("01"):
        return render_template("login.html", error="Enter a valid 11-digit phone number starting with '01'.")
    
    with db.cursor() as cursor:
        cursor.execute("SELECT * FROM user_profile WHERE phone_number = %s", (phone,))
        user = cursor.fetchone()
    
    if user:
        if user["status"] != "active":
            return render_template("account_suspended.html")

        if bcrypt.checkpw(password.encode("utf-8"), user['password'].encode("utf-8")):
            resp = make_response(redirect("/home"))
            resp = set_secure_cookie(resp, user["user_id"])
            return resp

    return render_template("login.html", error="Invalid phone number or password.")

#send money
#send_now
@app.route("/send_now", methods=["GET", "POST"])
def send_now():
    user_id = get_user_id_from_cookie()
    if not user_id:
        return render_template("login.html")

    if request.method == "GET":
        prefill_name = request.args.get("name")
        prefill_phone = request.args.get("phone")
        success = request.args.get("success", "")
        return render_template("send_now.html", prefill_name=prefill_name, prefill_phone=prefill_phone, success=success)


    recipient_phone = request.form.get("recipient_phone")
    recipient_name = request.form.get("recipient_name")
    amount_str = request.form.get("amount")
    save_info = request.form.get("save_info")

    try:
        amount = float(amount_str)
        if amount <= 0:
            return redirect(url_for('send_now', success='0'))
    except (ValueError, TypeError):
        return redirect(url_for('send_now', success='0'))

    with db.cursor() as cursor:
        cursor.execute("SELECT * FROM user_profile WHERE phone_number = %s", (recipient_phone,))
        recipient = cursor.fetchone()
        if not recipient:
            return redirect(url_for('send_now', success='0'))

        cursor.execute("SELECT balance, transaction_limit FROM user_profile WHERE user_id = %s", (user_id,))
        sender = cursor.fetchone()
        if not sender:
            return render_template("login.html")

        if sender['balance'] < amount:
            return redirect(url_for('send_now', status='insufficient_balance'))

        if sender['transaction_limit'] < amount:
            return redirect(url_for('send_now', status='limit_reached'))

        trx_id = generate_unique_trx_id(cursor)

        cursor.execute("""
            INSERT INTO send_money (user_id, phone_no, name, amount, trx_id)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, recipient_phone, recipient_name, amount, trx_id))

        cursor.execute("UPDATE user_profile SET balance = balance - %s WHERE user_id = %s", (amount, user_id))
        cursor.execute("UPDATE user_profile SET balance = balance + %s WHERE phone_number = %s", (amount, recipient_phone))

        if save_info == "on":
            try:
                cursor.execute("""
                    INSERT IGNORE INTO saved_details (user_id, name, phone)
                    VALUES (%s, %s, %s)
                """, (user_id, recipient_name, recipient_phone))
            except Exception as e:
                print("Error saving recipient details:", e)

        cursor.execute("INSERT INTO notifications (user_id, alerts) VALUES (%s, %s)",
                       (user_id, f"Sent {amount} to {recipient_name or recipient_phone}"))
        cursor.execute("INSERT INTO notifications (user_id, alerts) VALUES (%s, %s)",
                       (recipient['user_id'], f"Received {amount} from User {user_id}"))

        cursor.execute("""
            INSERT INTO history (user_id, type, trx_id, account, amount)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, "Send Money", trx_id, recipient_phone, -amount))

        db.commit()

    return redirect(url_for('send_now', status='success'))
#Add money
#add money bank
@app.route("/bank", methods=["GET", "POST"])
def bank():
    user_id = get_user_id_from_cookie()
    if not user_id:
        return render_template("login.html")   
    if request.method == "GET":
        return render_template("bank.html")  
    account_no = request.form.get("accountNo")
    amount = request.form.get("amount")
    if not account_no or not amount:
        return render_template("bank.html", error="Please fill in all fields.")
    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError("Amount must be positive")
    except ValueError:
        return render_template("bank.html", error="Invalid amount entered.")
    try:
        with db.cursor() as cursor:
            trx_id = generate_unique_trx_id(cursor)
            cursor.execute(""" 
                INSERT INTO add_money_bank (user_id, acc_no, amount, trx_id)
                VALUES (%s, %s, %s, %s)
            """, (user_id, account_no, amount, trx_id))
            cursor.execute("""
                UPDATE user_profile SET balance = balance + %s WHERE user_id = %s
            """, (amount, user_id))
            #notification
            cursor.execute("""
                INSERT INTO notifications (user_id, alerts)
                VALUES (%s, %s)
            """, (user_id, f"Add money from Bank account {account_no} for Taka {amount:.2f} successful, Trx ID: {trx_id}"))
            cursor.execute("""
                INSERT INTO history (user_id, type, trx_id, account, amount)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, "Add Money from Bank", trx_id, account_no, amount))

            db.commit()
        return render_template("bank.html", success=True)  
    except Exception as e:
        db.rollback()
        return render_template("bank.html", error="Something went wrong. Please try again.")

#add money card
@app.route("/card", methods=["GET", "POST"])
def card():
    user_id = get_user_id_from_cookie()
    if not user_id:
        return render_template("login.html")  
    if request.method == "GET":
        return render_template("card.html")    
    account_no = request.form.get("cardNo")
    amount = request.form.get("amount")
    if not account_no or not amount:
        return render_template("card.html", error="Please fill in all fields.") 
    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError("Amount must be positive")
    except ValueError:
        return render_template("card.html", error="Invalid amount entered.")
    try:
        with db.cursor() as cursor:
            trx_id = generate_unique_trx_id(cursor)
            cursor.execute(""" 
                INSERT INTO add_money_card (user_id, card_no, amount, trx_id)
                VALUES (%s, %s, %s, %s)
            """, (user_id, account_no, amount, trx_id))
            cursor.execute("""
                UPDATE user_profile SET balance = balance + %s WHERE user_id = %s
            """, (amount, user_id))
            #notification
            cursor.execute("""
                INSERT INTO notifications (user_id, alerts)
                VALUES (%s, %s)
            """, (user_id, f"Add money from card account {account_no} for Taka {amount:.2f} successful, Trx ID: {trx_id}"))
            cursor.execute("""
                INSERT INTO history (user_id, type, trx_id, account, amount)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, "Add Money from Card", trx_id, account_no, amount))

            db.commit()
        return render_template("card.html", success=True) 
    except Exception as e:
        db.rollback()
        return render_template("card.html", error="Something went wrong. Please try again.")

