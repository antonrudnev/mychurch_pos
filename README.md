# MyChurch POS

**Language:** English | [Русский](README.ru.md)

A web-based accounting and Point of Sale (POS) system for a parish store (church shop), built with Django. The application unifies product and candle sales, donation and prayer request (commemoration) tracking, cash register movements, parish staff payouts, and report generation with HTML snapshots and PDF export.

---

## ✨ Key Features

* **Unified Item & Service Directory (`/directory/`):**
  * Flexible category (`ItemType`) and item (`Item`) structure supporting fixed prices, open/free-will donation amounts (`0` / `None`), and user-extensible open lists (`is_open_list`).
  * Preconfigured parish categories: **Commemoration Notes / Zapiski** (`treby-2`), **Candles** (`candle`), **Sacraments** (`treby-1`), **Donations** (`donate`), **Blessings / Consecrations** (`treby-3`), **Staff / Service Payouts** (`staff`), **Cash & Reconciliation** (`money`), **Other Rites** (`other-treby`), and **Other Expenses** (`other-expense`).
  * Granular permission for price editing (`change_item_price`) and protected system slugs (`handle`).
* **Transaction Journal & Cash Desk (`/transactions/`):**
  * Logs every operation with cashier attribution, timestamp, quantity, and calculated total (`total_cost`).
  * **Soft Deletion (`delete_soft`):** Deleted entries are flagged (`is_deleted`) and hidden from default queries via a custom `TransactionManager`, while remaining preserved in the database for audit trails (`all_with_deleted`).
  * **Transaction Auditing:** Supports auditor verification (`is_verified`, `verified_by`) and role-based access permissions (`view_all_transactions`, `verify_transaction`).
* **Reporting & Printing (`/reports/`):**
  * Generates **Cash Reports** (`cash-report`) and **Product Statements** (`product-report`).
  * Stores each generated report as an immutable HTML snapshot (`Report.dump`) with author and timestamp metadata, plus PDF rendering via **WeasyPrint**.
* **Access Control & Administration:**
  * User registration (`/register/`), login (`/login/`), password management (`/password-change/`), and Django admin panel (`/admin/`).
  * Visual test-environment banner controlled via `TEST_ENVIRONMENT`.
* **Automated HTTPS (HTTP-01 & DNS-01):**
  * Built-in `nginx-proxy` stack automatically provisions and renews Let's Encrypt SSL certificates via standard `http-01` validation or via the Dynu API (`dns-01`) when port 80 is unavailable.

---

## 🛠️ Tech Stack

* **Backend:** Python, Django 6.1.2, Gunicorn (5 workers)
* **Static Files & PDF:** WhiteNoise 6.12.0, WeasyPrint 70.0
* **Database:** SQLite (persisted on host in `./db_volume`)
* **Infrastructure & SSL:** Docker, Docker Compose, `nginxproxy/nginx-proxy:1.6.0`, `nginxproxy/acme-companion:2.4.0` / `acme.sh` (Dynu DNS-01)

---

## 📂 Project Structure

```text
mychurch_pos/
├── apps/
│   ├── directory/         # Models and catalog for categories (ItemType) and items (Item)
│   ├── transactions/      # Transaction journal (Transaction), soft-delete, and auditing
│   └── reports/           # Report types (ReportType) and HTML snapshot archive (Report)
├── config/                # Django project configuration (settings, urls, views, wsgi)
├── docker/
│   ├── acme-dynu/         # SSL certificate container using DNS-01 challenge (Dynu API)
│   └── default-cert/      # Initial self-signed certificate generator for nginx-proxy
├── scripts/
│   ├── data_upload.py     # Initial seed / sync for categories, items, and report types
│   └── ensure_superuser.py# Automated superuser creation from .env credentials
├── static/images/         # Static assets and images
├── templates/             # HTML templates for UI, reports, and authentication
├── .env.example           # Environment variables template
├── db_backup.sh.example   # Database backup script template
├── docker-compose.yml     # Service definitions and SSL profiles (http-01 / dns-01)
├── Dockerfile             # Application container build instructions
├── manage.py              # Django management CLI
├── requirements.txt       # Python dependencies
└── start-compose.sh       # Stack startup script with automatic SSL profile detection
```

---

## 🚀 Docker Deployment (Production)

### 1. Clone the Repository
```bash
git clone https://://github.com.git
cd mychurch_pos
```

### 2. Configure `.env`
Copy the environment template and fill in the required parameters:
```bash
cp .env.example .env
```

Key environment variables in `.env`:

| Variable | Required | Description |
| :--- | :--- | :--- |
| `DOMAIN` | Yes | Public domain name pointing to your server (e.g., `://example.com`). |
| `LETSENCRYPT_EMAIL` | Yes | Email address for Let's Encrypt SSL certificate notifications. |
| `DJANGO_SECRET_KEY` | Yes | Unique, randomly generated Django secret key. |
| `DJANGO_SUPERUSER_USERNAME` | Yes | Initial admin username (created on first startup). |
| `DJANGO_SUPERUSER_EMAIL` | Yes | Initial admin email address. |
| `DJANGO_SUPERUSER_PASSWORD` | Yes | Initial admin password (existing passwords are not overwritten). |
| `TIME_ZONE` | No | Server time zone (defaults to `Asia/Novokuznetsk`). |
| `TEST_ENVIRONMENT` | No | `true` / `false` - displays a visible test environment indicator. |
| `DYNU_CLIENT_ID` | No | Dynu API Client ID (enables the `dns-01` profile when paired with secret). |
| `DYNU_CLIENT_SECRET` | No | Dynu API Secret for DNS-01 domain validation. |

### 3. Start the Stack
Launch the application using `start-compose.sh`:
```bash
chmod +x start-compose.sh
./start-compose.sh
```

The `start-compose.sh` script automatically checks for `DYNU_CLIENT_ID` and `DYNU_CLIENT_SECRET` in `.env`:
* If both values are set, it starts the **`dns-01`** profile (`acme-dynu` container).
* If left empty, it starts the **`http-01`** profile (`letsencrypt` container).

On startup, the `web` container automatically runs:
1. `python manage.py migrate` - applies database migrations.
2. `python scripts/data_upload.py` - loads default categories, items, and report types.
3. `python scripts/ensure_superuser.py` - creates the initial admin account.
4. Starts `gunicorn` on port `8000` behind `nginx-proxy` (ports `80` and `443` with HTTPS redirect).

---

## 💻 Local Development Setup

1. Create a virtual environment and install dependencies (ensure system Pango/Cairo libraries are installed for WeasyPrint):
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. Apply migrations, load initial directory data, and start the development server:
   ```bash
   python manage.py migrate
   python scripts/data_upload.py
   python manage.py runserver
   ```

---

## 💾 Database Backups

The SQLite database is stored on the host in `./db_volume`. Use `db_backup.sh.example` to set up automated backups:
```bash
cp db_backup.sh.example db_backup.sh
chmod +x db_backup.sh
```

---

## 👤 Author

* **Anton Rudnev** (`@antonrudnev`)
