import secrets
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.management import bp
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

ALL_STAFF = {"admin", "doctor", "nurse", "receptionist"}
ADMIN = {"admin"}
RESOURCES = {
    "appointments": {
        "title": "Appointments",
        "model": Appointment,
        "view": {"admin", "doctor", "nurse", "receptionist", "patient"},
        "write": {"admin", "receptionist"},
        "create": {"admin", "receptionist", "patient"},
        "fields": [
            ("patient_id", "Patient", "patient"),
            ("doctor_id", "Doctor", "doctor"),
            ("scheduled_at", "Date and time", "datetime-local"),
            ("duration_minutes", "Duration (minutes)", "number"),
            ("reason", "Reason for visit", "text"),
            ("status", "Status", "appointment_status"),
            ("notes", "Notes", "textarea"),
        ],
        "columns": ["id", "patient", "doctor", "scheduled_at", "status"],
    },
    "records": {
        "title": "Medical records",
        "model": MedicalRecord,
        "view": {"admin", "doctor", "nurse", "patient"},
        "write": {"admin", "doctor"},
        "create": {"admin", "doctor"},
        "fields": [
            ("patient_id", "Patient", "patient"),
            ("doctor_id", "Doctor", "doctor"),
            ("appointment_id", "Appointment (optional)", "appointment"),
            ("diagnosis", "Diagnosis", "text"),
            ("notes", "Clinical notes", "textarea"),
        ],
        "columns": ["id", "patient", "doctor", "diagnosis", "notes", "recorded_at"],
    },
    "prescriptions": {
        "title": "Prescriptions",
        "model": Prescription,
        "view": {"admin", "doctor", "patient"},
        "write": {"admin", "doctor"},
        "create": {"admin", "doctor"},
        "fields": [
            ("medical_record_id", "Medical record", "record"),
            ("medication", "Medication", "text"),
            ("dosage", "Dosage", "text"),
            ("frequency", "Frequency", "text"),
            ("duration", "Duration", "text"),
            ("instructions", "Instructions", "textarea"),
        ],
        "columns": [
            "id", "record", "medication", "dosage", "frequency",
            "duration", "instructions", "prescribed_at",
        ],
    },
    "billing": {
        "title": "Billing",
        "model": Bill,
        "view": {"admin", "receptionist", "patient"},
        "write": {"admin", "receptionist"},
        "create": {"admin", "receptionist"},
        "fields": [
            ("patient_id", "Patient", "patient"),
            ("appointment_id", "Appointment (optional)", "appointment"),
            ("amount", "Amount", "currency"),
            ("description", "Description", "text"),
            ("status", "Payment status", "bill_status"),
            ("due_date", "Due date", "date"),
        ],
        "columns": ["id", "patient", "description", "amount", "status", "due_date"],
    },
    "laboratory": {
        "title": "Laboratory",
        "model": LabTest,
        "view": {"admin", "doctor", "nurse", "patient"},
        "write": {"admin", "doctor", "nurse"},
        "create": {"admin", "doctor", "nurse"},
        "fields": [
            ("patient_id", "Patient", "patient"),
            ("medical_record_id", "Medical record (optional)", "record"),
            ("ordered_by_id", "Ordered by", "staff"),
            ("test_name", "Test name", "text"),
            ("status", "Status", "lab_status"),
            ("result", "Result", "textarea"),
        ],
        "columns": [
            "id", "patient", "test_name", "status", "result", "ordered_at", "completed_at",
        ],
    },
}

ENUMS = {
    "appointment_status": ["scheduled", "confirmed", "completed", "cancelled"],
    "bill_status": ["unpaid", "paid", "void"],
    "lab_status": ["ordered", "in_progress", "completed", "cancelled"],
}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")


def _require_role(roles):
    if current_user.role not in roles:
        abort(403)


def _staff_id():
    return current_user.staff.id if current_user.staff else None


def _patient_id():
    return current_user.patient.id if current_user.patient else None


def _patient_owner(item, key):
    if key in {"appointments", "billing", "laboratory", "records"}:
        return item.patient_id
    if key == "prescriptions":
        return item.record.patient_id
    return None


def _visible_query(key, spec):
    query = spec["model"].query
    if current_user.role == "patient":
        patient_id = _patient_id()
        if not patient_id:
            abort(403)
        if key == "patients":
            return query.filter_by(id=patient_id)
        if key == "staff":
            abort(403)
        if key == "prescriptions":
            return query.join(MedicalRecord).filter(MedicalRecord.patient_id == patient_id)
        return query.filter_by(patient_id=patient_id)
    if current_user.role == "doctor":
        staff_id = _staff_id()
        if not staff_id:
            abort(403)
        if key in {"appointments", "records"}:
            return query.filter_by(doctor_id=staff_id)
        if key == "prescriptions":
            return query.join(MedicalRecord).filter(MedicalRecord.doctor_id == staff_id)
        if key == "laboratory":
            return query.filter_by(ordered_by_id=staff_id)
    return query


def _can_write(item, key):
    if current_user.role not in RESOURCES[key]["write"]:
        return False
    if current_user.role == "doctor" and item is not None:
        staff_id = _staff_id()
        if key in {"appointments", "records"}:
            return item.doctor_id == staff_id
        if key == "prescriptions":
            return item.record.doctor_id == staff_id
        if key == "laboratory":
            return item.ordered_by_id == staff_id
    return True


def _choices(kind):
    if kind == "patient":
        return [(p.id, f"{p.name} · {p.mrn}") for p in Patient.query.order_by(Patient.id).all()]
    if kind == "doctor":
        return [
            (s.id, f"{s.name} · {s.specialization or s.department or 'Doctor'}")
            for s in Staff.query.join(User).filter(User.role == "doctor", User.active.is_(True)).all()
        ]
    if kind == "staff":
        return [
            (s.id, f"{s.name} · {s.role}")
            for s in Staff.query.join(User).filter(User.active.is_(True)).all()
        ]
    if kind == "appointment":
        return [
            (a.id, f"#{a.id} · {a.patient.name} · {a.scheduled_at:%Y-%m-%d %H:%M}")
            for a in Appointment.query.order_by(Appointment.scheduled_at.desc()).limit(250).all()
        ]
    if kind == "record":
        query = MedicalRecord.query
        if current_user.role == "doctor":
            staff_id = _staff_id()
            if not staff_id:
                abort(403)
            query = query.filter_by(doctor_id=staff_id)
        return [
            (r.id, f"#{r.id} · {r.patient.name} · {r.diagnosis}")
            for r in query.order_by(MedicalRecord.recorded_at.desc()).limit(250).all()
        ]
    return [(value, value.replace("_", " ").title()) for value in ENUMS[kind]]


def _fields_for(key):
    fields = RESOURCES[key]["fields"]
    if key == "appointments" and current_user.role == "patient":
        fields = [
            field for field in fields
            if field[0] not in {"patient_id", "duration_minutes", "status", "notes"}
        ]
    if key == "laboratory" and current_user.role in {"doctor", "nurse"}:
        fields = [field for field in fields if field[0] != "ordered_by_id"]
    return fields


def _form_context(key, item=None):
    fields = _fields_for(key)
    options = {}
    for name, _label, kind in fields:
        if kind in {"patient", "doctor", "staff", "appointment", "record"}:
            options[name] = _choices(kind)
        elif kind in ENUMS:
            options[name] = _choices(kind)
    return {
        "key": key,
        "spec": RESOURCES[key],
        "fields": fields,
        "options": options,
        "item": item,
        "editing": item is not None,
    }


def _parse_value(kind, value):
    if value == "":
        return None
    if kind in {"patient", "doctor", "staff", "appointment", "record"}:
        return int(value)
    if kind == "date":
        return date.fromisoformat(value)
    if kind == "datetime-local":
        return datetime.fromisoformat(value)
    if kind == "number":
        parsed = int(value)
        if parsed < 1 or parsed > 1440:
            raise ValueError("Duration must be between 1 and 1440 minutes.")
        return parsed
    if kind == "currency":
        parsed = Decimal(value)
        if not parsed.is_finite() or parsed < 0 or parsed > Decimal("99999999.99"):
            raise ValueError("Enter a valid non-negative amount.")
        return parsed.quantize(Decimal("0.01"))
    if kind in ENUMS:
        if value not in ENUMS[kind]:
            raise ValueError("Select a valid status.")
        return value
    return value.strip()


def _validate_relations(key, values):
    patient_id = values.get("patient_id")
    if key in {"records", "billing", "laboratory"} and patient_id is not None:
        if not db.session.get(Patient, patient_id):
            raise ValueError("Select a valid patient.")
    if key == "appointments":
        if not db.session.get(Patient, patient_id):
            raise ValueError("Select a valid patient.")
        doctor = db.session.get(Staff, values.get("doctor_id"))
        if not doctor or doctor.role != "doctor" or not doctor.user or not doctor.user.active:
            raise ValueError("Select an active doctor.")
    if key == "records":
        doctor = db.session.get(Staff, values.get("doctor_id"))
        if not doctor or doctor.role != "doctor" or not doctor.user or not doctor.user.active:
            raise ValueError("Select a valid doctor.")
        appointment_id = values.get("appointment_id")
        appointment = db.session.get(Appointment, appointment_id) if appointment_id else None
        if appointment_id and not appointment:
            raise ValueError("Select a valid appointment.")
        if appointment and appointment.patient_id != patient_id:
            raise ValueError("The appointment must belong to the selected patient.")
        if appointment and appointment.doctor_id != values.get("doctor_id"):
            raise ValueError("The appointment must belong to the selected doctor.")
    if key == "prescriptions":
        if not db.session.get(MedicalRecord, values.get("medical_record_id")):
            raise ValueError("Select a valid medical record.")
    if key == "billing":
        appointment_id = values.get("appointment_id")
        appointment = db.session.get(Appointment, appointment_id) if appointment_id else None
        if appointment_id and not appointment:
            raise ValueError("Select a valid appointment.")
        if appointment and appointment.patient_id != patient_id:
            raise ValueError("The appointment must belong to the selected patient.")
    if key == "laboratory":
        record_id = values.get("medical_record_id")
        record = db.session.get(MedicalRecord, record_id) if record_id else None
        if record_id and not record:
            raise ValueError("Select a valid medical record.")
        if record and record.patient_id != patient_id:
            raise ValueError("The medical record must belong to the selected patient.")
        if values.get("ordered_by_id") is not None and not db.session.get(Staff, values["ordered_by_id"]):
            raise ValueError("Select valid staff.")


def _display(item, column):
    if column == "patient":
        return item.patient.name
    if column == "doctor":
        return item.doctor.name
    if column == "record":
        return f"#{item.record.id} · {item.record.diagnosis}"
    if column == "scheduled_at":
        return item.scheduled_at.strftime("%b %d, %Y %H:%M")
    if column in {"recorded_at", "prescribed_at", "ordered_at", "completed_at"}:
        value = getattr(item, column)
        return value.strftime("%b %d, %Y %H:%M") if value else "—"
    if column == "due_date":
        return item.due_date.strftime("%b %d, %Y") if item.due_date else "—"
    if column == "amount":
        return f"${item.amount:,.2f}"
    return getattr(item, column, "—") or "—"


def _check_appointment_conflict(values, exclude_id=None):
    start = values["scheduled_at"]
    end = start + timedelta(minutes=values["duration_minutes"])
    candidates = Appointment.query.filter(
        Appointment.status.in_(("scheduled", "confirmed")),
        Appointment.scheduled_at >= start - timedelta(days=1),
        Appointment.scheduled_at < end,
    )
    if exclude_id is not None:
        candidates = candidates.filter(Appointment.id != exclude_id)
    for existing in candidates.all():
        existing_end = existing.scheduled_at + timedelta(minutes=existing.duration_minutes)
        if start < existing_end and existing.scheduled_at < end:
            if existing.doctor_id == values["doctor_id"]:
                raise ValueError("This doctor already has an appointment at that time.")
            if existing.patient_id == values["patient_id"]:
                raise ValueError("This patient already has an appointment at that time.")


def _validate_field_lengths(model, values):
    for name, value in values.items():
        if not isinstance(value, str):
            continue
        column = model.__table__.columns[name]
        limit = getattr(column.type, "length", None) or (5000 if column.type.python_type is str else None)
        if limit and len(value) > limit:
            raise ValueError(f"{name.replace('_', ' ').title()} must be {limit} characters or fewer.")


def _validate_profile_fields(is_patient):
    profile_fields = {
        "phone": request.form.get("phone", "").strip() or None,
    }
    if is_patient:
        profile_fields.update(
            address=request.form.get("address", "").strip() or None,
            gender=request.form.get("gender") or None,
            blood_group=request.form.get("blood_group") or None,
        )
        _validate_field_lengths(Patient, profile_fields)
        if profile_fields["gender"] and profile_fields["gender"] not in {
            "Female", "Male", "Non-binary", "Other"
        }:
            raise ValueError("Select a valid gender option.")
        if profile_fields["blood_group"] and profile_fields["blood_group"] not in {
            "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"
        }:
            raise ValueError("Select a valid blood group.")
    else:
        profile_fields.update(
            department=request.form.get("department", "").strip() or None,
            specialization=request.form.get("specialization", "").strip() or None,
            hire_date=request.form.get("hire_date", "").strip() or None,
        )
        _validate_field_lengths(Staff, profile_fields)


@bp.route("/<key>")
@login_required
def index(key):
    spec = RESOURCES.get(key)
    if not spec:
        abort(404)
    _require_role(spec["view"])
    items = _visible_query(key, spec).order_by(spec["model"].id.desc()).limit(500).all()
    return render_template(
        "management/list.html",
        key=key,
        spec=spec,
        items=items,
        display=_display,
        can_create=current_user.role in spec["create"],
    )


@bp.route("/<key>/new", methods=["GET", "POST"])
@login_required
def create(key):
    spec = RESOURCES.get(key)
    if not spec:
        abort(404)
    _require_role(spec["create"])
    context = _form_context(key)
    if request.method == "POST":
        try:
            values = {}
            for name, label, kind in context["fields"]:
                raw = request.form.get(name, "")
                required = name in {
                    "patient_id", "doctor_id", "scheduled_at", "reason",
                    "diagnosis", "medication", "dosage",
                    "frequency", "duration", "amount", "description", "test_name",
                } or (name == "medical_record_id" and key == "prescriptions")
                if required and not raw:
                    raise ValueError(f"{label} is required.")
                values[name] = _parse_value(kind, raw)
            if current_user.role == "patient":
                values["patient_id"] = _patient_id()
            if key == "appointments":
                if current_user.role == "patient":
                    values.update(duration_minutes=30, status="scheduled", notes=None)
                else:
                    values["duration_minutes"] = values.get("duration_minutes") or 30
                    values["status"] = values.get("status") or "scheduled"
            if key == "billing":
                values["status"] = values.get("status") or "unpaid"
            if key == "laboratory":
                values["status"] = values.get("status") or "ordered"
            if key == "records" and current_user.role == "doctor":
                values["doctor_id"] = _staff_id()
            _validate_field_lengths(spec["model"], values)
            if key == "laboratory" and current_user.role in {"doctor", "nurse"}:
                values["ordered_by_id"] = _staff_id()
            _validate_relations(key, values)
            if key == "appointments" and values["scheduled_at"] <= datetime.now():
                raise ValueError("Choose a future appointment time.")
            if key == "appointments":
                _check_appointment_conflict(values)
            if key == "prescriptions":
                record = db.session.get(MedicalRecord, values["medical_record_id"])
                if current_user.role == "doctor" and record.doctor_id != _staff_id():
                    abort(403)
            if key == "laboratory":
                record = db.session.get(MedicalRecord, values.get("medical_record_id"))
                if current_user.role == "doctor" and record and record.doctor_id != _staff_id():
                    abort(403)
            item = spec["model"](**values)
            if key == "billing" and item.status == "paid":
                item.paid_at = datetime.utcnow()
            if key == "laboratory" and item.status == "completed":
                item.completed_at = datetime.utcnow()
            db.session.add(item)
            db.session.commit()
            flash(f"{spec['title'].rstrip('s')} created successfully.", "success")
            return redirect(url_for("management.index", key=key))
        except (ValueError, InvalidOperation, OverflowError) as error:
            db.session.rollback()
            flash(str(error) or "Enter valid form values.", "danger")
        except IntegrityError:
            db.session.rollback()
            flash("This entry conflicts with an existing record. Check linked records and try again.", "danger")
    return render_template("management/form.html", **context)


@bp.route("/<key>/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit(key, item_id):
    spec = RESOURCES.get(key)
    if not spec:
        abort(404)
    item = db.session.get(spec["model"], item_id)
    if item is None:
        abort(404)
    if not _can_write(item, key):
        abort(403)
    context = _form_context(key, item)
    if request.method == "POST":
        try:
            values = {}
            for name, label, kind in context["fields"]:
                raw = request.form.get(name, "")
                required = name in {
                    "patient_id", "doctor_id", "scheduled_at", "reason",
                    "diagnosis", "medication", "dosage",
                    "frequency", "duration", "amount", "description", "test_name",
                } or (name == "medical_record_id" and key == "prescriptions")
                if required and not raw:
                    raise ValueError(f"{label} is required.")
                values[name] = _parse_value(kind, raw)
            if key == "appointments":
                values["duration_minutes"] = values.get("duration_minutes") or 30
                values["status"] = values.get("status") or item.status
            if key == "records" and current_user.role == "doctor":
                values["doctor_id"] = _staff_id()
            if key == "laboratory" and current_user.role in {"doctor", "nurse"}:
                values["ordered_by_id"] = item.ordered_by_id
            _validate_field_lengths(spec["model"], values)
            _validate_relations(key, values)
            if key == "prescriptions" and current_user.role == "doctor":
                record = db.session.get(MedicalRecord, values["medical_record_id"])
                if record.doctor_id != _staff_id():
                    abort(403)
            if key == "laboratory" and current_user.role == "doctor":
                record = db.session.get(MedicalRecord, values.get("medical_record_id"))
                if record and record.doctor_id != _staff_id():
                    abort(403)
            if key == "appointments" and values["scheduled_at"] <= datetime.now():
                if values["status"] not in {"completed", "cancelled"}:
                    raise ValueError("Choose a future time for an active appointment.")
            if key == "appointments":
                if values["status"] in {"scheduled", "confirmed"}:
                    _check_appointment_conflict(values, exclude_id=item.id)
            previous_paid_at = item.paid_at if key == "billing" else None
            previous_completed_at = item.completed_at if key == "laboratory" else None
            for name, value in values.items():
                setattr(item, name, value)
            if key == "billing":
                item.paid_at = (
                    previous_paid_at or datetime.utcnow()
                    if item.status == "paid"
                    else None
                )
            if key == "laboratory":
                item.completed_at = (
                    previous_completed_at or datetime.utcnow()
                    if item.status == "completed"
                    else None
                )
            db.session.commit()
            flash("Changes saved successfully.", "success")
            return redirect(url_for("management.index", key=key))
        except (ValueError, InvalidOperation, OverflowError) as error:
            db.session.rollback()
            flash(str(error) or "Enter valid form values.", "danger")
        except IntegrityError:
            db.session.rollback()
            flash("This change conflicts with an existing record.", "danger")
    return render_template("management/form.html", **context)


@bp.post("/<key>/<int:item_id>/delete")
@login_required
def delete(key, item_id):
    spec = RESOURCES.get(key)
    if not spec:
        abort(404)
    item = db.session.get(spec["model"], item_id)
    if item is None:
        abort(404)
    if not _can_write(item, key):
        abort(403)
    try:
        db.session.delete(item)
        db.session.commit()
        flash("Record deleted.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("This record is linked to other data and cannot be deleted.", "danger")
    return redirect(url_for("management.index", key=key))


@bp.route("/patients")
@login_required
def patients():
    _require_role(ALL_STAFF)
    items = Patient.query.order_by(Patient.id.desc()).limit(500).all()
    return render_template("management/people.html", kind="patients", title="Patients", items=items)


@bp.route("/staff")
@login_required
def staff():
    _require_role(ALL_STAFF)
    items = Staff.query.order_by(Staff.id.desc()).limit(500).all()
    return render_template("management/people.html", kind="staff", title="Doctors & staff", items=items)


@bp.route("/people/<kind>/new", methods=["GET", "POST"])
@login_required
def create_person(kind):
    _require_role(ADMIN)
    if kind not in {"patients", "staff"}:
        abort(404)
    is_patient = kind == "patients"
    roles = ["doctor", "nurse", "receptionist"] if not is_patient else ["patient"]
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = "patient" if is_patient else request.form.get("role", "")
        if (
            not name or len(name) > 120 or len(email) > 190
            or not EMAIL_PATTERN.fullmatch(email)
        ):
            flash("Enter a name and a valid email address.", "danger")
        elif role not in roles:
            flash("Select a valid account role.", "danger")
        elif not password or len(password) < 12:
            flash("A password must contain at least 12 characters.", "danger")
        else:
            try:
                _validate_field_lengths(User, {"name": name, "email": email})
                _validate_profile_fields(is_patient)
                user = User(name=name, email=email, role=role)
                user.set_password(password)
                db.session.add(user)
                db.session.flush()
                if is_patient:
                    dob = date.fromisoformat(request.form["date_of_birth"]) if request.form.get("date_of_birth") else None
                    if dob and dob > date.today():
                        raise ValueError("Date of birth cannot be in the future.")
                    db.session.add(Patient(
                        user=user,
                        mrn=f"PT-{secrets.token_hex(6).upper()}",
                        phone=request.form.get("phone", "").strip() or None,
                        address=request.form.get("address", "").strip() or None,
                        gender=request.form.get("gender") or None,
                        date_of_birth=dob,
                        blood_group=request.form.get("blood_group") or None,
                    ))
                else:
                    employee_id = request.form.get("employee_id", "").strip()
                    if not employee_id:
                        employee_id = f"ST-{secrets.token_hex(5).upper()}"
                    _validate_field_lengths(Staff, {"employee_id": employee_id})
                    db.session.add(Staff(
                        user=user,
                        employee_id=employee_id,
                        department=request.form.get("department", "").strip() or None,
                        specialization=request.form.get("specialization", "").strip() or None,
                        phone=request.form.get("phone", "").strip() or None,
                        hire_date=date.fromisoformat(request.form["hire_date"]) if request.form.get("hire_date") else None,
                    ))
                db.session.commit()
                flash(f"{'Patient' if is_patient else 'Staff member'} account created.", "success")
                return redirect(url_for("management.patients" if is_patient else "management.staff"))
            except ValueError as error:
                db.session.rollback()
                flash(str(error) or "Enter valid form values.", "danger")
            except IntegrityError:
                db.session.rollback()
                flash("The email or employee identifier is already in use.", "danger")
    return render_template(
        "management/person_form.html",
        kind=kind,
        is_patient=is_patient,
        roles=roles,
        item=None,
    )


@bp.route("/people/<kind>/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit_person(kind, item_id):
    _require_role(ADMIN)
    if kind == "patients":
        item = db.session.get(Patient, item_id)
        user = item.user if item else None
        is_patient = True
    elif kind == "staff":
        item = db.session.get(Staff, item_id)
        user = item.user if item else None
        is_patient = False
    else:
        abort(404)
    if item is None or user is None:
        abort(404)
    roles = ["doctor", "nurse", "receptionist"] if not is_patient else ["patient"]
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = "patient" if is_patient else request.form.get("role", "")
        if (
            not name or len(name) > 120 or len(email) > 190
            or not EMAIL_PATTERN.fullmatch(email)
        ):
            flash("Enter a name and a valid email address.", "danger")
        elif role not in roles:
            flash("Select a valid account role.", "danger")
        elif password and len(password) < 12:
            flash("A new password must contain at least 12 characters.", "danger")
        else:
            try:
                duplicate = User.query.filter(User.email == email, User.id != user.id).first()
                if duplicate:
                    raise ValueError("That email address is already in use.")
                _validate_field_lengths(User, {"name": name, "email": email})
                _validate_profile_fields(is_patient)
                user.name, user.email, user.role = name, email, role
                if password:
                    user.set_password(password)
                if is_patient:
                    item.phone = request.form.get("phone", "").strip() or None
                    item.address = request.form.get("address", "").strip() or None
                    item.gender = request.form.get("gender") or None
                    item.blood_group = request.form.get("blood_group") or None
                    item.date_of_birth = date.fromisoformat(request.form["date_of_birth"]) if request.form.get("date_of_birth") else None
                    if item.date_of_birth and item.date_of_birth > date.today():
                        raise ValueError("Date of birth cannot be in the future.")
                else:
                    item.department = request.form.get("department", "").strip() or None
                    item.specialization = request.form.get("specialization", "").strip() or None
                    item.phone = request.form.get("phone", "").strip() or None
                    item.hire_date = date.fromisoformat(request.form["hire_date"]) if request.form.get("hire_date") else None
                    item.employee_id = request.form.get("employee_id", "").strip()
                    if not item.employee_id:
                        raise ValueError("Employee ID is required.")
                    _validate_field_lengths(Staff, {"employee_id": item.employee_id})
                db.session.commit()
                flash("Profile updated.", "success")
                return redirect(url_for("management.patients" if is_patient else "management.staff"))
            except ValueError as error:
                db.session.rollback()
                flash(str(error) or "Enter valid form values.", "danger")
            except IntegrityError:
                db.session.rollback()
                flash("Email or employee identifier is already in use.", "danger")
    return render_template(
        "management/person_form.html",
        kind=kind,
        is_patient=is_patient,
        roles=roles,
        item=item,
        user=user,
    )


@bp.post("/people/<kind>/<int:item_id>/toggle")
@login_required
def toggle_person(kind, item_id):
    _require_role(ADMIN)
    if kind == "patients":
        item = db.session.get(Patient, item_id)
    elif kind == "staff":
        item = db.session.get(Staff, item_id)
    else:
        abort(404)
    if not item or not item.user:
        abort(404)
    if item.user.active and item.user.id == current_user.id:
        flash("You cannot deactivate your own account.", "warning")
        return redirect(url_for("management.patients" if kind == "patients" else "management.staff"))
    if item.user.active and item.user.role == "admin":
        active_admins = User.query.filter_by(role="admin", active=True).count()
        if active_admins <= 1:
            flash("The last active administrator cannot be deactivated.", "warning")
            return redirect(url_for("management.staff"))
    item.user.active = not item.user.active
    db.session.commit()
    flash(
        "Account activated." if item.user.active else "Account deactivated. It can no longer sign in.",
        "success",
    )
    return redirect(url_for("management.patients" if kind == "patients" else "management.staff"))
