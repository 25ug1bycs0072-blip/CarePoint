from datetime import datetime
from decimal import Decimal

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(190), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(
        db.Enum("admin", "doctor", "nurse", "receptionist", "patient", name="user_role"),
        nullable=False,
    )
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    patient = db.relationship("Patient", back_populates="user", uselist=False)
    staff = db.relationship("Staff", back_populates="user", uselist=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return self.active


class Patient(db.Model):
    __tablename__ = "patients"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), unique=True)
    mrn = db.Column(db.String(24), unique=True, nullable=False, index=True)
    date_of_birth = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(30), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    emergency_contact = db.Column(db.String(120), nullable=True)
    blood_group = db.Column(db.String(5), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user = db.relationship("User", back_populates="patient")
    appointments = db.relationship("Appointment", back_populates="patient")
    records = db.relationship("MedicalRecord", back_populates="patient")
    bills = db.relationship("Bill", back_populates="patient")
    lab_tests = db.relationship("LabTest", back_populates="patient")

    @property
    def name(self):
        return self.user.name if self.user else "Unlinked patient"

    @property
    def email(self):
        return self.user.email if self.user else ""


class Staff(db.Model):
    __tablename__ = "staff"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), unique=True)
    employee_id = db.Column(db.String(24), unique=True, nullable=False, index=True)
    department = db.Column(db.String(100), nullable=True)
    specialization = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    hire_date = db.Column(db.Date, nullable=True)
    user = db.relationship("User", back_populates="staff")
    appointments = db.relationship("Appointment", back_populates="doctor")
    records = db.relationship("MedicalRecord", back_populates="doctor")

    @property
    def name(self):
        return self.user.name if self.user else "Unlinked staff"

    @property
    def role(self):
        return self.user.role if self.user else ""


class Appointment(db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=False, index=True)
    scheduled_at = db.Column(db.DateTime, nullable=False, index=True)
    duration_minutes = db.Column(db.Integer, nullable=False, default=30)
    reason = db.Column(db.String(500), nullable=False)
    status = db.Column(
        db.Enum("scheduled", "confirmed", "completed", "cancelled", name="appointment_status"),
        nullable=False,
        default="scheduled",
    )
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    patient = db.relationship("Patient", back_populates="appointments")
    doctor = db.relationship("Staff", back_populates="appointments")
    record = db.relationship("MedicalRecord", back_populates="appointment", uselist=False)
    bill = db.relationship("Bill", back_populates="appointment", uselist=False)


class MedicalRecord(db.Model):
    __tablename__ = "medical_records"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=False, index=True)
    appointment_id = db.Column(
        db.Integer, db.ForeignKey("appointments.id", ondelete="SET NULL"), unique=True
    )
    diagnosis = db.Column(db.String(255), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    patient = db.relationship("Patient", back_populates="records")
    doctor = db.relationship("Staff", back_populates="records")
    appointment = db.relationship("Appointment", back_populates="record")
    prescriptions = db.relationship(
        "Prescription", back_populates="record", cascade="all, delete-orphan"
    )
    lab_tests = db.relationship("LabTest", back_populates="record")


class Prescription(db.Model):
    __tablename__ = "prescriptions"

    id = db.Column(db.Integer, primary_key=True)
    medical_record_id = db.Column(db.Integer, db.ForeignKey("medical_records.id"), nullable=False)
    medication = db.Column(db.String(160), nullable=False)
    dosage = db.Column(db.String(100), nullable=False)
    frequency = db.Column(db.String(100), nullable=False)
    duration = db.Column(db.String(100), nullable=False)
    instructions = db.Column(db.Text, nullable=True)
    prescribed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    record = db.relationship("MedicalRecord", back_populates="prescriptions")


class Bill(db.Model):
    __tablename__ = "bills"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    appointment_id = db.Column(
        db.Integer, db.ForeignKey("appointments.id", ondelete="SET NULL"), unique=True
    )
    amount = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    description = db.Column(db.String(255), nullable=False)
    status = db.Column(
        db.Enum("unpaid", "paid", "void", name="bill_status"),
        nullable=False,
        default="unpaid",
    )
    due_date = db.Column(db.Date, nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    patient = db.relationship("Patient", back_populates="bills")
    appointment = db.relationship("Appointment", back_populates="bill")


class LabTest(db.Model):
    __tablename__ = "lab_tests"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    medical_record_id = db.Column(
        db.Integer, db.ForeignKey("medical_records.id", ondelete="SET NULL"), nullable=True
    )
    ordered_by_id = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=False)
    test_name = db.Column(db.String(160), nullable=False)
    status = db.Column(
        db.Enum("ordered", "in_progress", "completed", "cancelled", name="lab_status"),
        nullable=False,
        default="ordered",
    )
    result = db.Column(db.Text, nullable=True)
    ordered_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    patient = db.relationship("Patient", back_populates="lab_tests")
    record = db.relationship("MedicalRecord", back_populates="lab_tests")
    ordered_by = db.relationship("Staff", foreign_keys=[ordered_by_id])
