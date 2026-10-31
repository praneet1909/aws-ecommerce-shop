# aws-ecommerce-shop
Highly available e-commerce website on AWS (EC2, RDS, S3, ALB, Auto Scaling)

# AWS Shop: Highly Available E-Commerce Website

A Flask e-commerce site on AWS with a load balancer, Auto Scaling, RDS MySQL and S3.

## Architecture
Customers -> Application Load Balancer -> EC2 servers (Auto Scaling, 2 AZs) -> RDS MySQL (private). Product images in S3, access through an IAM role.

## AWS services
VPC, EC2, Auto Scaling, ELB, RDS, S3, EBS, IAM

## Features
Product catalogue with categories, search and sorting, cart, login, checkout, order history, and an admin panel with image upload to S3.

## Setup
See `AWS_SETUP_GUIDE_FINAL.md` for the step-by-step AWS setup.

## Structure
- `app/`: Flask application
- `deploy/user_data.sh`: EC2 startup script (replace the placeholders first)

## Architecture
[Architecture](docs/Architecture.png)

## Screenshots
[Home page](docs/home.png)
[Cart Page](docs/cart.png)
[Mobile Interface Page](docs/mobileinterface.png)
[Admin Page](docs/admin.png)
[Product Page](docs/product.png)
