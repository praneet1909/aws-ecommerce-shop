"""Simple e-commerce app for the AWS project (Flask + RDS MySQL + S3).
Configuration comes from environment variables (see deploy/user_data.sh)."""
import os
import sys
import uuid
from functools import wraps

import boto3
import pymysql
import pymysql.cursors
from botocore.config import Config
from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-change-me")  # must be the same on all servers
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

DB_CONFIG = dict(
    host=os.environ.get("DB_HOST", "localhost"),
    user=os.environ.get("DB_USER", "admin"),
    password=os.environ.get("DB_PASSWORD", ""),
    database=os.environ.get("DB_NAME", "shopdb"),
    cursorclass=pymysql.cursors.DictCursor,
    autocommit=True,
    connect_timeout=5,
)
S3_BUCKET = os.environ.get("S3_BUCKET", "")
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")
# Credentials come from the EC2 IAM role automatically (no keys in code).
s3 = boto3.client("s3", region_name=AWS_REGION, config=Config(signature_version="s3v4"))
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}

SEED_PRODUCTS = [
    ("Wireless Headphones", "Bluetooth over-ear headphones with 20 hour battery.", 1999.00, "Electronics"),
    ("Cotton T-Shirt", "Soft everyday t-shirt, available in many sizes.", 499.00, "Fashion"),
    ("Steel Water Bottle", "Insulated 1 litre bottle, keeps drinks cold for 24 hours.", 699.00, "Home"),
    ("Laptop Backpack", "Water resistant backpack that fits a 15 inch laptop.", 1299.00, "Accessories"),
]
CATEGORY_MAP = {n: c for n, _d, _p, c in SEED_PRODUCTS}


# ---------- database helpers ----------
def get_db():
    if "db" not in g:
        g.db = pymysql.connect(**DB_CONFIG)
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, args=(), one=False):
    with get_db().cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    with get_db().cursor() as cur:
        cur.execute(sql, args)
        return cur.lastrowid


# ---------- template helpers ----------
@app.template_global()
def image_url(key):
    """Private S3 object -> temporary signed URL (bucket stays private)."""
    if not key or not S3_BUCKET:
        return url_for("static", filename="placeholder.svg")
    return s3.generate_presigned_url(
        "get_object", Params={"Bucket": S3_BUCKET, "Key": key}, ExpiresIn=3600)


@app.template_filter("money")
def money(v):
    return "₹{:,.2f}".format(float(v))


@app.context_processor
def inject_cart():
    return {"cart_count": sum(session.get("cart", {}).values())}


@app.errorhandler(403)
@app.errorhandler(404)
def http_error(e):
    return render_template("error.html", code=e.code, msg=e.name), e.code


@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", code=500, msg="Something went wrong"), 500


@app.before_request
def load_user():
    uid = session.get("user_id")
    g.user = None
    if uid and request.endpoint not in ("health", "static"):
        g.user = query("SELECT id, name, email, is_admin FROM users WHERE id=%s", (uid,), one=True)


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not g.user:
            flash("Please log in first.")
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return wrapper


def admin_required(f):
    @wraps(f)
    @login_required
    def wrapper(*a, **kw):
        if not g.user["is_admin"]:
            abort(403)
        return f(*a, **kw)
    return wrapper


# ---------- cart (stored in the signed cookie, so any server can serve any request) ----------
def cart_details():
    cart = session.get("cart", {})
    if not cart:
        return [], 0
    ids = [int(i) for i in cart]
    rows = query("SELECT * FROM products WHERE id IN (%s)" % ",".join(["%s"] * len(ids)), ids)
    items, total = [], 0
    for p in rows:
        qty = cart[str(p["id"])]
        sub = float(p["price"]) * qty
        total += sub
        items.append({"product": p, "qty": qty, "subtotal": sub})
    return items, total


# ---------- routes ----------
@app.route("/health")
def health():
    return "ok", 200  # used by the load balancer health check (no DB call on purpose)


@app.route("/")
def index():
    search = request.args.get("q", "").strip()
    cat = request.args.get("cat", "").strip()
    sort = request.args.get("sort", "new")
    sql, args = "SELECT * FROM products WHERE 1=1", []
    if search:
        sql += " AND name LIKE %s"
        args.append("%" + search + "%")
    if cat:
        sql += " AND category=%s"
        args.append(cat)
    order = {"low": " ORDER BY price ASC", "high": " ORDER BY price DESC", "name": " ORDER BY name ASC"}
    sql += order.get(sort, " ORDER BY id DESC")
    products = query(sql, args)
    cats = [r["category"] for r in query("SELECT DISTINCT category FROM products ORDER BY category")]
    return render_template("index.html", products=products, search=search, cat=cat, sort=sort, cats=cats)


@app.route("/product/<int:pid>")
def product(pid):
    p = query("SELECT * FROM products WHERE id=%s", (pid,), one=True)
    if not p:
        abort(404)
    return render_template("product.html", p=p)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        pw = request.form["password"]
        if not name or not email or len(pw) < 6:
            flash("Fill all fields. Password needs 6+ characters.", "error")
            return render_template("register.html")
        try:
            uid = execute("INSERT INTO users (name,email,password_hash) VALUES (%s,%s,%s)",
                          (name, email, generate_password_hash(pw)))
        except pymysql.err.IntegrityError:
            flash("That email is already registered.", "error")
            return render_template("register.html")
        session["user_id"] = uid
        return redirect(url_for("index"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = query("SELECT * FROM users WHERE email=%s", (request.form["email"].strip().lower(),), one=True)
        if u and check_password_hash(u["password_hash"], request.form["password"]):
            session["user_id"] = u["id"]
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("index"))
        flash("Wrong email or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/cart")
def cart():
    items, total = cart_details()
    return render_template("cart.html", items=items, total=total)


@app.post("/cart/add/<int:pid>")
def cart_add(pid):
    if not query("SELECT id FROM products WHERE id=%s", (pid,), one=True):
        abort(404)
    c = session.get("cart", {})
    try:
        qty = max(1, min(int(request.form.get("qty", 1)), 20))
    except ValueError:
        qty = 1
    c[str(pid)] = min(c.get(str(pid), 0) + qty, 20)
    session["cart"] = c
    flash("Added to cart.", "success")
    return redirect(request.referrer or url_for("index"))


@app.post("/cart/remove/<int:pid>")
def cart_remove(pid):
    c = session.get("cart", {})
    c.pop(str(pid), None)
    session["cart"] = c
    return redirect(url_for("cart"))


@app.post("/cart/update/<int:pid>")
def cart_update(pid):
    c = session.get("cart", {})
    k = str(pid)
    if k in c:
        c[k] += 1 if request.form.get("action") == "inc" else -1
        if c[k] < 1:
            c.pop(k)
        else:
            c[k] = min(c[k], 20)
    session["cart"] = c
    return redirect(url_for("cart"))


@app.post("/checkout")
@login_required
def checkout():
    items, total = cart_details()  # prices always come from the database, not the browser
    if not items:
        flash("Your cart is empty.", "error")
        return redirect(url_for("cart"))
    db = get_db()
    db.begin()
    try:
        with db.cursor() as cur:
            cur.execute("INSERT INTO orders (user_id,total) VALUES (%s,%s)", (g.user["id"], total))
            oid = cur.lastrowid
            cur.executemany(
                "INSERT INTO order_items (order_id,product_id,quantity,unit_price) VALUES (%s,%s,%s,%s)",
                [(oid, i["product"]["id"], i["qty"], i["product"]["price"]) for i in items])
        db.commit()
    except Exception:
        db.rollback()
        raise
    session.pop("cart", None)
    flash("Order placed. Thank you!", "success")
    return redirect(url_for("orders"))


@app.route("/orders")
@login_required
def orders():
    rows = query("SELECT * FROM orders WHERE user_id=%s ORDER BY id DESC", (g.user["id"],))
    for o in rows:
        o["items"] = query(
            "SELECT p.name, oi.quantity, oi.unit_price FROM order_items oi "
            "JOIN products p ON p.id=oi.product_id WHERE oi.order_id=%s", (o["id"],))
    return render_template("orders.html", orders=rows)


def save_image(f):
    if not f or not f.filename:
        return None
    ext = f.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXT or not S3_BUCKET:
        raise ValueError("bad image")
    key = "products/%s.%s" % (uuid.uuid4().hex, ext)
    s3.upload_fileobj(f, S3_BUCKET, key, ExtraArgs={"ContentType": f.mimetype})
    return key


@app.route("/admin/products")
@admin_required
def admin_products():
    return render_template("admin_products.html", products=query("SELECT * FROM products ORDER BY id"))


@app.route("/admin/products/new", methods=["GET", "POST"])
@admin_required
def admin_new_product():
    if request.method == "POST":
        try:
            key = save_image(request.files.get("image"))
        except ValueError:
            flash("Image must be png/jpg/gif/webp and S3_BUCKET must be set.", "error")
            return redirect(url_for("admin_new_product"))
        execute("INSERT INTO products (name,description,price,category,image_key) VALUES (%s,%s,%s,%s,%s)",
                (request.form["name"].strip(), request.form["description"].strip(), request.form["price"],
                 request.form.get("category", "").strip() or "General", key))
        flash("Product added.", "success")
        return redirect(url_for("admin_products"))
    return render_template("admin_form.html", p=None)


@app.route("/admin/products/<int:pid>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_product(pid):
    p = query("SELECT * FROM products WHERE id=%s", (pid,), one=True)
    if not p:
        abort(404)
    if request.method == "POST":
        try:
            key = save_image(request.files.get("image")) or p["image_key"]
        except ValueError:
            flash("Image must be png/jpg/gif/webp and S3_BUCKET must be set.", "error")
            return redirect(url_for("admin_edit_product", pid=pid))
        execute("UPDATE products SET name=%s,description=%s,price=%s,category=%s,image_key=%s WHERE id=%s",
                (request.form["name"].strip(), request.form["description"].strip(), request.form["price"],
                 request.form.get("category", "").strip() or "General", key, pid))
        flash("Product updated.", "success")
        return redirect(url_for("admin_products"))
    return render_template("admin_form.html", p=p)


@app.post("/admin/products/<int:pid>/delete")
@admin_required
def admin_delete_product(pid):
    try:
        execute("DELETE FROM products WHERE id=%s", (pid,))
        flash("Product deleted.", "success")
    except pymysql.err.IntegrityError:
        flash("This product has orders and cannot be deleted.", "error")
    return redirect(url_for("admin_products"))


# ---------- command line: python app.py initdb | create-admin ----------
def init_db():
    conn = pymysql.connect(**DB_CONFIG)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")) as fh:
        statements = [s.strip() for s in fh.read().split(";") if s.strip()]
    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)
        cur.execute("SELECT COUNT(*) AS n FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
                    "AND TABLE_NAME='products' AND COLUMN_NAME='category'")
        if cur.fetchone()["n"] == 0:
            cur.execute("ALTER TABLE products ADD COLUMN category VARCHAR(60) NOT NULL DEFAULT 'General'")
        for pname, pcat in CATEGORY_MAP.items():
            cur.execute("UPDATE products SET category=%s WHERE name=%s AND category='General'", (pcat, pname))
        cur.execute("SELECT COUNT(*) AS n FROM products")
        if cur.fetchone()["n"] == 0:
            cur.executemany("INSERT INTO products (name,description,price,category) VALUES (%s,%s,%s,%s)", SEED_PRODUCTS)
    conn.close()
    print("Database ready.")


def create_admin(email, password, name="Admin"):
    conn = pymysql.connect(**DB_CONFIG)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (name,email,password_hash,is_admin) VALUES (%s,%s,%s,1) "
            "ON DUPLICATE KEY UPDATE is_admin=1, password_hash=VALUES(password_hash)",
            (name, email.lower(), generate_password_hash(password)))
    conn.close()
    print("Admin user ready:", email)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "initdb":
        init_db()
    elif len(sys.argv) >= 4 and sys.argv[1] == "create-admin":
        create_admin(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "Admin")
    else:
        app.run(host="0.0.0.0", port=8000, debug=True)
