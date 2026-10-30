# AWS Shop: Final Step-by-Step Setup Guide (Free Tier friendly)

Region for everything: **Asia Pacific (Mumbai) ap-south-1**. Check it at the top right before every step.
Plan: Customers -> Load Balancer -> EC2 servers (Auto Scaling, 2 AZs) -> RDS MySQL (private) + S3 for images.
Free tier design: **no NAT gateway**, servers in public subnets (locked to the load balancer), Single-AZ RDS, 1 to 2 servers.
Time needed: about 3 hours. Delete everything the same day (Part 13).

## Names to use (so every step matches)
| Item | Name / value |
|---|---|
| VPC | `shop-vpc` (10.0.0.0/16) |
| Security groups | `alb-sg`, `app-sg`, `db-sg` |
| S3 bucket | your unique name, e.g. `shop-praneet-006` |
| IAM role | `shop-ec2-role` |
| RDS | instance `shop-db`, **database name `shopdb`**, user `admin` |
| Launch template | `shop-template` |
| Target group / ALB / ASG | `shop-tg` / `shop-alb` / `shop-asg` |

## Part 1: Billing alert
Billing and Cost Management -> Budgets -> Create budget -> Zero spend budget -> add your email.

## Part 2: VPC
VPC -> Create VPC -> **VPC and more**.
- Name `shop`, CIDR `10.0.0.0/16`, 2 AZs, **2 public** and **2 private** subnets
- **NAT gateways: None**, VPC endpoints: **S3 Gateway**, DNS hostnames + resolution on
- Create, wait for green ticks.

## Part 3: Security groups (VPC -> Security groups)
1. `alb-sg`: inbound HTTP 80 from `0.0.0.0/0`
2. `app-sg`: inbound HTTP 80, source = **`alb-sg`**
3. `db-sg`: inbound MYSQL/Aurora 3306, source = **`app-sg`**

## Part 4: S3 bucket
1. S3 -> Create bucket, unique name, ap-south-1, **Block all public access ON**.
2. Create folder `app`, open it, upload **`shop.zip`** -> path must be `app/shop.zip`.
3. Create folder `products` (product images go here).

## Part 5: IAM role
1. IAM -> Roles -> Create role -> AWS service -> **EC2** -> attach **AmazonSSMManagedInstanceCore** -> name `shop-ec2-role`.
2. Open the role -> Add permissions -> Create inline policy -> JSON (replace `YOUR-BUCKET` with your bucket name, 3 places) -> name `shop-s3-access`:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": ["s3:GetObject"],
     "Resource": ["arn:aws:s3:::YOUR-BUCKET/app/*", "arn:aws:s3:::YOUR-BUCKET/products/*"]},
    {"Effect": "Allow", "Action": ["s3:PutObject"],
     "Resource": "arn:aws:s3:::YOUR-BUCKET/products/*"}
  ]
}
```

## Part 6: RDS database
1. RDS -> Subnet groups -> Create: `shop-db-subnets`, VPC `shop-vpc`, both AZs, the **two private subnets**.
2. RDS -> Create database -> Standard create:
   - MySQL 8.0, template Free tier / Dev-Test, **Single-AZ**
   - Identifier `shop-db`, user `admin`, password letters+numbers only (e.g. `ShopPass2026x`)
   - `db.t3.micro`, 20 GiB, untick storage autoscaling
   - VPC `shop-vpc`, subnet group `shop-db-subnets`, **Public access: No**, security group **`db-sg`** only
   - Additional configuration -> **Initial database name: `shopdb`** (NOT `shop-db`)
   - Untick Enhanced monitoring and deletion protection
3. When status is **Available**, copy the **Endpoint**.

## Part 7: Edit the user data script
Open `deploy/user_data.sh` and set only the top lines (keep the quotes):
```
DB_HOST="your-rds-endpoint"
DB_USER="admin"
DB_PASSWORD="your-db-password"
DB_NAME="shopdb"
S3_BUCKET="your-bucket-name"
AWS_REGION="ap-south-1"
SECRET_KEY="any-long-random-letters-and-numbers"
```
`DB_NAME` must be **shopdb**. `SECRET_KEY` is something you invent (32+ characters, no symbols).

## Part 8: Launch template
EC2 -> Launch templates -> Create:
- Name `shop-template`, AMI **Amazon Linux 2023**, type **t3.micro** (free tier eligible)
- Key pair: don't include. Security group: **`app-sg`**, no subnet
- Advanced network configuration -> **Auto-assign public IP: Enable**
- Advanced details -> **IAM instance profile: `shop-ec2-role`**
- User data: paste the **whole** edited `user_data.sh` (first line `#!/bin/bash`, last line `systemctl enable --now shop nginx`)

## Part 9: Target group and load balancer
1. EC2 -> Target Groups -> Create: Instances, `shop-tg`, HTTP 80, VPC `shop-vpc`, health check path **`/health`**. Register no targets.
2. EC2 -> Load Balancers -> Create **Application Load Balancer**: `shop-alb`, Internet-facing, VPC `shop-vpc`, both AZs with the **public** subnets, security group **`alb-sg`**.
3. Listener HTTP:80 -> **Forward to `shop-tg`** (check this, otherwise the target group says "None associated").
4. Copy the ALB **DNS name**.

## Part 10: Auto Scaling group
EC2 -> Auto Scaling groups -> Create:
- Name `shop-asg`, template `shop-template`
- VPC `shop-vpc`, subnets: the two **public** subnets
- **Attach to an existing load balancer -> `shop-tg`** (this registers servers automatically)
- Turn on **ELB health checks**, grace period 300 seconds
- Desired **1**, min **1**, max **2**; target tracking policy: average CPU **50**
Wait 8 to 10 minutes; `shop-tg` -> Targets should show **Healthy**.

## Part 11: Open the website
Open `http://<ALB-DNS-NAME>` (http, not https). Register a customer, add items to the cart, place an order.

## Part 12: Make an admin, add images, run demos
1. **Admin:** EC2 -> Instances -> your instance -> Connect -> **Session Manager** -> Connect. Run (use the same email you registered with):
```bash
sudo bash -c 'set -a; . /etc/shop.env; set +a; /opt/shop/venv/bin/python /opt/shop/app.py create-admin YOUR-EMAIL@example.com YourPass123 Admin'
```
   Logout and login again. A **Manage** link appears.
2. **Images:** Manage -> Edit a product -> choose an image -> Save. Or Manage -> **New product**. Images are stored in the S3 `products/` folder.
3. **Demo A, scaling:** set the group's desired capacity to 2. On a server run `sudo dnf install -y stress-ng` then `stress-ng --cpu 2 --timeout 600` and watch Auto Scaling -> Activity.
4. **Demo B, failure:** terminate one server; the site stays up and a replacement launches.
5. **Demo C, security:** the RDS endpoint and the servers' public IPs cannot be opened directly from your laptop.

## Updating the app later
Upload the new `shop.zip` to `app/` in S3 (same name), then on the server:
```bash
sudo aws s3 cp s3://YOUR-BUCKET/app/shop.zip /tmp/shop.zip --region ap-south-1
sudo unzip -o /tmp/shop.zip -d /opt/shop && sudo chown -R ec2-user:ec2-user /opt/shop
sudo bash -c 'set -a; . /etc/shop.env; set +a; /opt/shop/venv/bin/python /opt/shop/app.py initdb'
sudo systemctl restart shop
```
Other servers pick it up through an **Instance refresh** on `shop-asg`.

## Part 13: Delete everything (same day, in this order)
1. Auto Scaling group `shop-asg` -> Delete (wait for instances to terminate)
2. Load balancer `shop-alb` -> Delete, then target group `shop-tg`
3. RDS `shop-db` -> Delete (untick final snapshot and retained backups), then subnet group `shop-db-subnets`
4. S3 bucket -> Empty, then Delete
5. If you made a NAT gateway: delete it, wait for Deleted, then release the Elastic IP
6. VPC `shop-vpc` -> Delete VPC (delete leftover security groups if it complains)
7. Launch template `shop-template`, IAM role `shop-ec2-role`
8. Check EC2 -> Volumes and Elastic IPs are empty; check Billing the next day

## Troubleshooting
| Problem | Fix |
|---|---|
| 502 Bad Gateway | Target group shows 0 targets or "None associated": do Part 9 step 3 and Part 10 (attach `shop-tg`). Otherwise wait 8 to 10 minutes. |
| 500 Internal Server Error | In Session Manager run `sudo journalctl -u shop -n 40 --no-pager`. |
| `Unknown database 'shop-db'` | `DB_NAME` is wrong. Run `sudo sed -i 's/^DB_NAME=.*/DB_NAME=shopdb/' /etc/shop.env`, run the `initdb` command, then `sudo systemctl restart shop`. Fix the launch template too (new version -> default -> ASG uses Latest). |
| `Can't connect to MySQL` | `db-sg` must allow 3306 from `app-sg`; RDS must be Available; check `DB_HOST`. |
| `Access denied for user` | Wrong `DB_PASSWORD` in `/etc/shop.env`. |
| `aws s3 cp` fails | File must be `app/shop.zip`; check the bucket name and the IAM role on the launch template. |
| Session Manager won't connect | Role `shop-ec2-role` attached? Instance has a public IP? Wait 5 minutes. |
| Editing the launch template | Versions can't be edited: Actions -> Modify template (Create new version) -> set default -> ASG Launch template Edit -> Latest -> Instance refresh. |
| Elastic IP can't be released | Delete the NAT gateway first, wait until Deleted. |
