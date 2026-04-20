# YourTreasurer 🏛️ Digital CFO for Students
**Course:** 20PECE 601A: DevOps Fundamentals  
[cite_start]**Institution:** MKSSS's Cummins College of Engineering for Women, Pune [cite: 3, 4]  
[cite_start]**Semester:** II, 2025-2026 [cite: 6]

## 🎯 1. Problem Definition & Project Planning
**Problem:** University students often struggle with manual expense tracking, leading to budget overruns and forgotten peer-to-peer (P2P) social liabilities.  
**Objectives:** * Automate budget tracking with a 30-day reset logic.
* Implement a "Financial Bodyguard" via automated cloud-native mail alerts.
* Provide digital receipt vaulting for audit-ready compliance.
* Visualize spending trends using interactive dashboards.

## 🛠️ 2. DevOps Lifecycle & Tech Stack
[cite_start]This project implements a complete CI/CD pipeline to automate the software lifecycle[cite: 14].

| Stage | Tool | Implementation Detail |
| :--- | :--- | :--- |
| **Version Control** | Git / GitHub | [cite_start]Maintained with regular commits and branching strategy[cite: 15, 19]. |
| **Build Automation** | pip / requirements.txt | [cite_start]Automated dependency resolution within the CI pipeline[cite: 16, 19]. |
| **Continuous Integration** | GitHub Actions | [cite_start]Automated linting and unit testing on every push[cite: 16]. |
| **Containerization** | Docker | [cite_start]Environment isolation via Dockerfile for consistent deployment[cite: 17, 19]. |
| **Cloud Deployment** | Render | [cite_start]Automated Continuous Deployment (CD) to cloud staging[cite: 17, 19]. |

## ✨ Key Features
* **Guardian Mail Logic:** Cloud-native email alerts via **SendGrid API** (replaces SMTP for cloud reliability).
* **30-Day Auto-Reset:** Smart temporal logic that resets the budget cycle monthly.
* **Loan Handshake:** Automated P2P loan notifications sent to friends.
* **Receipt Vault:** Secure **Cloudinary** integration for digital invoice storage.
* **Visual Intelligence:** Dynamic **Chart.js** dashboards for trend analysis.

## 🚀 Setup & Installation

### 1. Prerequisites
* Docker installed locally
* MongoDB Atlas Cluster
* SendGrid API Key (Verified Sender)

### 2. Environment Variables
Configure these in your `.env` or Render Dashboard:
- `MONGO_URI`: Your MongoDB connection string.
- `SENDGRID_API_KEY`: Your SendGrid API key.
- `MAIL_USER`: Your verified sender email.
- `CLOUDINARY_URL`: Your Cloudinary environment variable.

### 3. Running with Docker
```bash
# Build the image
docker build -t your-treasurer .

# Run the container
docker run -p 5000:5000 your-treasurer
```

## 🧪 3. Continuous Testing (CI)
The project includes an automated test suite (`test_app.py`) covering:
* **Boundary Value Analysis (BVA):** Testing budget limits at 0 and extreme values.
* **Functional Logic:** Verifying login hash validation and expense addition.
* **Route Integrity:** Ensuring all 200 OK status codes for core navigation.

## 📊 4. Deployment Evidence
* **CI/CD Status:** [View GitHub Actions](https://github.com/Pritee3011/YourTreasurer/actions)
* **Live Demo:** [YourTreasurer on Render](https://treasure-1-yblo.onrender.com/)

``
