#!/bin/bash
# EC2 user data for Amazon Linux 2023. Paste into the Launch Template (Advanced details > User data).
# EDIT the values below. Use a simple password (no spaces, quotes or # characters).
set -x
DB_HOST="PASTE-YOUR-RDS-ENDPOINT"
DB_USER="admin"
DB_PASSWORD="PASTE-YOUR-DB-PASSWORD"
DB_NAME="shopdb"
S3_BUCKET="PASTE-YOUR-BUCKET-NAME"
AWS_REGION="ap-south-1"
SECRET_KEY="PASTE-A-LONG-RANDOM-STRING-SAME-FOR-ALL-SERVERS"
# ---------------------------------------------------------------------------

dnf install -y python3 python3-pip nginx unzip

# 1. Download the app from S3 (allowed by the EC2 IAM role)
mkdir -p /opt/shop
aws s3 cp "s3://${S3_BUCKET}/app/shop.zip" /tmp/shop.zip --region "${AWS_REGION}"
unzip -o /tmp/shop.zip -d /opt/shop

# 2. Python environment
python3 -m venv /opt/shop/venv
/opt/shop/venv/bin/pip install -r /opt/shop/requirements.txt
chown -R ec2-user:ec2-user /opt/shop

# 3. App settings
cat > /etc/shop.env <<ENV
DB_HOST=${DB_HOST}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
DB_NAME=${DB_NAME}
S3_BUCKET=${S3_BUCKET}
AWS_REGION=${AWS_REGION}
SECRET_KEY=${SECRET_KEY}
ENV
chmod 600 /etc/shop.env

# 4. Create tables and sample products (safe to run on every server)
for i in 1 2 3 4 5 6 7 8 9 10; do
  (set -a; . /etc/shop.env; set +a; /opt/shop/venv/bin/python /opt/shop/app.py initdb) && break
  sleep 15
done

# 5. Run the app with gunicorn as a service
cat > /etc/systemd/system/shop.service <<'UNIT'
[Unit]
Description=AWS Shop (gunicorn)
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/opt/shop
EnvironmentFile=/etc/shop.env
ExecStart=/opt/shop/venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
UNIT

# 6. Nginx reverse proxy on port 80
cat > /etc/nginx/nginx.conf <<'NGINX'
user nginx;
worker_processes auto;
pid /run/nginx.pid;
events { worker_connections 1024; }
http {
  include /etc/nginx/mime.types;
  client_max_body_size 6m;
  server {
    listen 80 default_server;
    location / {
      proxy_pass http://127.0.0.1:8000;
      proxy_set_header Host $host;
      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
    }
  }
}
NGINX

systemctl daemon-reload
systemctl enable --now shop nginx
