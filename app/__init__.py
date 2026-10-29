import logging
import os
from datetime import date, datetime, timedelta
from decimal import Decimal

import click
from flask import Flask, render_template
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import csrf, db, login_manager


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object("config.Config")
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY") or len(app.config["SECRET_KEY"]) < 32:
        raise RuntimeError("Set SECRET_KEY to a random value of at least 32 characters.")
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError("Set DATABASE_URL to your MySQL connection string.")

    os.makedirs(app.instance_path, exist_ok=True)
    logging.basicConfig(level=logging.INFO)
    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        try:
            user = db.session.get(User, int(user_id))
            return user if user and user.active else None
        except (TypeError, ValueError):
            return None

    from app.auth import bp as auth_bp
    from app.main import bp as main_bp
    from app.management import bp as management_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(management_bp)

    @app.context_processor
    def common_template_values():
        return {
            "today": date.today().isoformat(),
            "now": datetime.now(),
            "min_datetime": datetime.now().strftime("%Y-%m-%dT%H:%M"),
        }

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("error.html", code=403, message="You do not have access to this page."), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("error.html", code=404, message="The requested page was not found."), 404

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        db.session.rollback()
        app.logger.exception("Database operation failed: %s", error)
        return render_template(
            "error.html",
            code=500,
            message="The database operation could not be completed. Please try again.",
        ), 500

    @app.cli.command("init-db")
    def init_db_command():
        """Create tables for a fresh local installation."""
        db.create_all()
        print("Database tables created.")

    @app.cli.command("create-admin")
    def create_admin_command():
        """Interactively create the first administrator account."""
        import getpass

        from app.models import User

        name = input("Admin name: ").strip()
        email = input("Admin email: ").strip().lower()
        password = getpass.getpass("Password (minimum 12 characters): ")
        if not name or len(name) > 120 or len(email) > 190 or "@" not in email or len(password) < 12:
            raise click.ClickException("Provide a name, valid email, and password of at least 12 characters.")
        if User.query.filter_by(email=email).first():
            raise click.ClickException("An account already uses that email address.")
        admin = User(name=name, email=email, role="admin")
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        print("Administrator account created.")

    @app.cli.command("seed-demo")
    def seed_demo_command():
        """Insert fictional demo users and records using DEMO_PASSWORD."""
        from app.models import (
            Appointment,
            Bill,
            LabTest,
            MedicalRecord,
            Patient,
            Prescription,
            Staff,
            User,
        )

        password = os.getenv("DEMO_PASSWORD", "")
        if len(password) < 12:
            raise click.ClickException("Set DEMO_PASSWORD to a value of at least 12 characters.")
        emails = [
            "doctor@carepoint.local",
            "nurse@carepoint.local",
            "reception@carepoint.local",
            "patient@carepoint.local",
        ]
        if User.query.filter(User.email.in_(emails)).first():
            raise click.ClickException("Demo accounts already exist; seed-demo will not duplicate them.")

        doctor_user = User(name="Avery Patel", email=emails[0], role="doctor")
        nurse_user = User(name="Morgan Lee", email=emails[1], role="nurse")
        reception_user = User(name="Jordan Kim", email=emails[2], role="receptionist")
        patient_user = User(name="Taylor Brooks", email=emails[3], role="patient")
        for user in (doctor_user, nurse_user, reception_user, patient_user):
            user.set_password(password)
        doctor = Staff(
            user=doctor_user,
            employee_id="ST-DEMO-DOC",
            department="Internal Medicine",
            specialization="Family Medicine",
            phone="555-0101",
        )
        nurse = Staff(
            user=nurse_user,
            employee_id="ST-DEMO-NUR",
            department="Outpatient Care",
            phone="555-0102",
        )
        receptionist = Staff(
            user=reception_user,
            employee_id="ST-DEMO-REC",
            department="Front Desk",
            phone="555-0103",
        )
        patient = Patient(
            user=patient_user,
            mrn="PT-DEMO-0001",
            date_of_birth=date(1990, 5, 14),
            gender="Female",
            phone="555-0110",
            address="100 Example Street",
            blood_group="O+",
        )
        appointment = Appointment(
            patient=patient,
            doctor=doctor,
            scheduled_at=datetime.now().replace(second=0, microsecond=0) + timedelta(days=2),
            duration_minutes=30,
            reason="Routine health check",
            status="confirmed",
        )
        record = MedicalRecord(
            patient=patient,
            doctor=doctor,
            appointment=appointment,
            diagnosis="Seasonal allergies",
            notes="Fictional demo record. Review reported symptoms at follow-up.",
        )
        prescription = Prescription(
            record=record,
            medication="Cetirizine",
            dosage="10 mg",
            frequency="Once daily as needed",
            duration="7 days",
            instructions="Demo data only; confirm clinical decisions with a licensed clinician.",
        )
        bill = Bill(
            patient=patient,
            appointment=appointment,
            amount=Decimal("85.00"),
            description="Consultation fee",
            status="unpaid",
            due_date=date.today() + timedelta(days=14),
        )
        lab_test = LabTest(
            patient=patient,
            record=record,
            ordered_by=nurse,
            test_name="Complete blood count",
            status="ordered",
        )
        db.session.add_all([
            doctor_user, nurse_user, reception_user, patient_user,
            doctor, nurse, receptionist, patient, appointment, record,
            prescription, bill, lab_test,
        ])
        db.session.commit()
        print("Fictional demo records created for: " + ", ".join(emails))

    return app
