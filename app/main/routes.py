from datetime import datetime
from decimal import Decimal

from flask import abort, render_template
from flask_login import current_user, login_required
from sqlalchemy import func

from app.extensions import db
from app.main import bp
from app.models import Appointment, Bill, LabTest, MedicalRecord, Patient, Staff


@bp.route("/")
def home():
    if current_user.is_authenticated:
        return dashboard()
    return render_template("landing.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    role = current_user.role
    if role == "patient":
        patient = current_user.patient
        if not patient:
            abort(403)
        appointments = Appointment.query.filter_by(patient_id=patient.id).order_by(
            Appointment.scheduled_at.desc()
        ).limit(5).all()
        bills = Bill.query.filter_by(patient_id=patient.id).order_by(Bill.created_at.desc()).limit(5).all()
        return render_template(
            "dashboard.html",
            patient_mode=True,
            appointments=appointments,
            bills=bills,
            patient=patient,
            now=datetime.now(),
        )

    today = datetime.now().date()
    counts = {
        "patients": Patient.query.count(),
        "staff": Staff.query.count(),
        "today_appointments": Appointment.query.filter(
            func.date(Appointment.scheduled_at) == today,
            Appointment.status.in_(("scheduled", "confirmed")),
        ).count(),
        "pending_labs": LabTest.query.filter(LabTest.status.in_(("ordered", "in_progress"))).count(),
        "unpaid_total": db.session.query(func.coalesce(func.sum(Bill.amount), 0)).filter(
            Bill.status == "unpaid"
        ).scalar() or Decimal("0.00"),
        "records": MedicalRecord.query.count(),
    }
    recent_query = Appointment.query
    if role == "doctor":
        if not current_user.staff:
            abort(403)
        recent_query = recent_query.filter_by(doctor_id=current_user.staff.id)
    recent = recent_query.order_by(Appointment.scheduled_at.desc()).limit(6).all()
    chart_labels, chart_values = [], []
    for offset in range(5, -1, -1):
        month = (today.month - 1 - offset) % 12 + 1
        year = today.year + ((today.month - 1 - offset) // 12)
        chart_labels.append(datetime(year, month, 1).strftime("%b %Y"))
        chart_values.append(
            Appointment.query.filter(
                func.year(Appointment.scheduled_at) == year,
                func.month(Appointment.scheduled_at) == month,
            ).count()
        )
    return render_template(
        "dashboard.html",
        patient_mode=False,
        counts=counts,
        recent=recent,
        chart_labels=chart_labels,
        chart_values=chart_values,
        role=role,
        now=datetime.now(),
    )
