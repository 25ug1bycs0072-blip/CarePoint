# CarePoint Hospital Management System

A full-stack hospital operations application built with Flask, MySQL, SQLAlchemy, HTML, CSS, JavaScript, and Bootstrap 5. It includes patient and staff accounts, appointments, medical records, prescriptions, billing, and laboratory workflows.

## Features

- Role-based authentication for administrators, doctors, nurses, receptionists, and patients.
- Patient self-registration and administrator-managed patient/staff profiles.
- Appointment booking with scheduling conflict checks, status tracking, and patient-specific visibility.
- Medical records and prescriptions linked to patients and clinicians.
- Billing records with paid/unpaid/void states and payment timestamps.
- Laboratory orders, results, and completion tracking.
- Administrative dashboard statistics, six-month appointment chart, and recent activity.
- Password hashing, CSRF protection on every form, ORM-bound queries, role checks, secure cookie options, and application logging.

## Project layout

```text
hospital/
├── app/
│   ├── auth/                 # Sign in, patient registration, sign out
│   ├── main/                 # Landing page and dashboards
│   ├── management/           # Patient/staff and clinical workflows
│   ├── static/css/           # Responsive application styles
│   ├── static/js/            # Table search, confirmations, chart setup
│   ├── templates/            # Jinja templates
│   ├── extensions.py         # SQLAlchemy, CSRF, and login extensions
│   └── models.py             # MySQL-backed relational schema
├── config.py
├── run.py
├── requirements.txt
└── .env.example
```

## Database design

`flask init-db` creates the MySQL tables from the SQLAlchemy models. The relational model is:

- `users`: unique email, password hash, role, active state.
- `patients`: patient medical record number and demographics; optional one-to-one link to a patient login.
- `staff`: unique employee identifier, department/specialty; optional one-to-one link to a staff login.
- `appointments`: patient and doctor foreign keys, scheduled time, duration, reason, and status.
- `medical_records`: patient and doctor foreign keys; optional unique appointment link.
- `prescriptions`: one-to-many from a medical record.
- `bills`: patient foreign key and optional unique appointment link.
- `lab_tests`: patient, ordering staff, and optional medical-record foreign keys.

Foreign keys, uniqueness constraints, indexes, enum-constrained statuses, and ORM relationships are declared in [app/models.py](./app/models.py). The app expects MySQL 8.0 or newer; create the database and application user before running `init-db`.

Example MySQL setup (replace the password):

```sql
CREATE DATABASE hospital_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
CREATE USER 'hospital_user'@'localhost' IDENTIFIED BY 'use-a-unique-password';
GRANT ALL PRIVILEGES ON hospital_db.* TO 'hospital_user'@'localhost';
FLUSH PRIVILEGES;
```

## Installation on Windows

1. Install Python 3.10+ and MySQL 8+, then create the database using the SQL above.
2. From PowerShell in this project folder, create and activate a virtual environment:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. Configure the environment:

   ```powershell
   Copy-Item .env.example .env
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

   Put the generated value in `SECRET_KEY` in `.env`, and set `DATABASE_URL` to:

   ```text
   mysql+pymysql://hospital_user:YOUR_DATABASE_PASSWORD@localhost/hospital_db?charset=utf8mb4
   ```

   URL-encode special characters in the database password. Keep `.env` private; it is excluded from source control.

4. Create the tables and the first administrator:

   ```powershell
   $env:FLASK_APP = "run.py"
   flask init-db
   flask create-admin
   ```

   The command prompts for the administrator's name, email, and password. Passwords must be at least 12 characters.

5. Start the local server:

   ```powershell
   python run.py
   ```

   Open `http://127.0.0.1:5000`. Patient accounts can also register from the public landing page. Bootstrap and chart/font assets load from public CDNs, so those UI assets require an internet connection.

## Sample data

Optional: set a private password for the fictional demo accounts (at least 12 characters), then run the sample-data command:

```powershell
$env:DEMO_PASSWORD = "choose-a-private-demo-password"
$env:FLASK_APP = "run.py"
flask seed-demo
```

The command creates fictional doctor, nurse, receptionist, and patient accounts with linked sample appointments, a medical record, a prescription, an unpaid bill, and a laboratory order. The login emails are `doctor@carepoint.local`, `nurse@carepoint.local`, `reception@carepoint.local`, and `patient@carepoint.local`; all use the `DEMO_PASSWORD` value. The command refuses to overwrite accounts if any of those emails already exist. Change or remove these accounts before using any shared or production environment.

## Role access summary

| Module | Admin | Doctor | Nurse | Receptionist | Patient |
|---|---:|---:|---:|---:|---:|
| Dashboard | Yes | Yes | Yes | Yes | Own activity |
| Patient/staff directory | Manage | Read | Read | Read | No |
| Appointments | Manage | Own schedule, read | Read | Manage | Book and view own |
| Medical records | Manage | Own records | Read | No | Own records |
| Prescriptions | Manage | Own records | No | No | Own prescriptions |
| Billing | Manage | No | No | Manage | Own bills |
| Laboratory | Manage | Own orders | Manage | No | Own results |

New staff accounts and role changes are administrator-managed. Only patient accounts can be self-registered. Inactive users cannot sign in; administrators can reactivate an account from its profile list.

## Deployment notes

- Set a unique random `SECRET_KEY` and a production-grade MySQL account with access only to this database.
- Terminate TLS at a trusted reverse proxy and set `COOKIE_SECURE=1` when serving over HTTPS.
- Do not enable Flask debug mode in production. Keep `.env`, backups, and patient data out of source control.
- `flask init-db` is for first-time local setup; it does not migrate an existing schema. Use a migration plan before changing a deployed database.
- This project records payment status; it does not connect to a payment processor or transmit payment card details.
