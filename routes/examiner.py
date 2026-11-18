from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from models import db, Exam, Slot, Booking, Evaluation, EvaluationScore
from .utils import role_required, parse_date, parse_time, to_int, to_float, log_booking, slots_overlap

bp = Blueprint("examiner", __name__)


# Fetch a slot owned by the current examiner
def own_slot(sid):
    slot = Slot.query.get_or_404(sid)
    if slot.examiner_id != current_user.id:
        abort(403)
    return slot


# Show examiner dashboard with slots and pending evaluations
@bp.route("/")
@role_required("examiner")
def dashboard():
    my_slots = Slot.query.filter_by(examiner_id=current_user.id).order_by(Slot.date, Slot.start_time).all()
    booked = [b for s in my_slots for b in s.active_bookings]
    pending = [b for b in booked if b.status == "Booked" and not b.evaluation]
    upcoming = [s for s in my_slots if s.date >= date.today() and s.status in ("Available", "Full")]
    return render_template("examiner/dashboard.html", exams=current_user.assigned_exams, slots=my_slots,
                           booked_count=len(booked), pending=pending, upcoming=upcoming[:6])


# List exams assigned to the examiner
@bp.route("/exams")
@role_required("examiner")
def exams():
    return render_template("examiner/exams.html", exams=current_user.assigned_exams)


# List the examiner's slots
@bp.route("/slots")
@role_required("examiner")
def slots():
    my_slots = Slot.query.filter_by(examiner_id=current_user.id).order_by(Slot.date.desc(), Slot.start_time).all()
    return render_template("examiner/slots.html", slots=my_slots)


# Validate slot form input and return values
def _slot_from_form(exam, slot=None):
    f = request.form
    try:
        d, st, et = parse_date(f.get("date")), parse_time(f.get("start_time")), parse_time(f.get("end_time"))
    except ValueError:
        d = st = et = None
    cap = to_int(f.get("capacity"))
    errors = []
    if not d or not st or not et:
        errors.append("Date, start time and end time are required.")
    else:
        if d < date.today():
            errors.append("Slot date cannot be in the past.")
        if et <= st:
            errors.append("End time must be after start time.")
        else:
            minutes = (datetime.combine(d, et) - datetime.combine(d, st)).seconds // 60
            if minutes < exam.duration:
                errors.append(f"Slot must be at least the exam duration ({exam.duration} min).")
            if slots_overlap(current_user.id, d, st, et, exclude_id=slot.id if slot else None):
                errors.append("This slot overlaps one of your existing slots.")
    if not cap or cap < 1:
        errors.append("Capacity must be at least 1.")
    for e in errors:
        flash(e, "danger")
    return None if errors else dict(date=d, start_time=st, end_time=et, capacity=cap,
                                    venue=f.get("venue", "").strip())


# Create a new slot for an assigned exam
@bp.route("/exams/<int:eid>/slots/new", methods=["GET", "POST"])
@role_required("examiner")
def slot_new(eid):
    exam = Exam.query.get_or_404(eid)
    if exam not in current_user.assigned_exams:
        abort(403)
    if not exam.slot_creation_allowed:
        flash("Slot creation is not open for this examination right now.", "warning")
        return redirect(url_for("examiner.exams"))
    if request.method == "POST":
        data = _slot_from_form(exam)
        if data:
            slot = Slot(exam=exam, examiner_id=current_user.id, available_seats=data["capacity"],
                        status="Available", **data)
            db.session.add(slot)
            db.session.commit()
            flash(f"Slot {slot.code} created.", "success")
            return redirect(url_for("examiner.slots"))
    return render_template("examiner/slot_form.html", exam=exam, slot=None)


# Edit an existing editable slot
@bp.route("/slots/<int:sid>/edit", methods=["GET", "POST"])
@role_required("examiner")
def slot_edit(sid):
    slot = own_slot(sid)
    if not slot.editable:
        flash("Slots can only be changed before booking starts and while unbooked.", "warning")
        return redirect(url_for("examiner.slots"))
    if request.method == "POST":
        data = _slot_from_form(slot.exam, slot)
        if data:
            for k, v in data.items():
                setattr(slot, k, v)
            slot.refresh()
            db.session.commit()
            flash("Slot updated.", "success")
            return redirect(url_for("examiner.slots"))
    return render_template("examiner/slot_form.html", exam=slot.exam, slot=slot)


# Delete an editable slot
@bp.route("/slots/<int:sid>/delete", methods=["POST"])
@role_required("examiner")
def slot_delete(sid):
    slot = own_slot(sid)
    if not slot.editable:
        flash("Slots can only be removed before booking starts and while unbooked.", "warning")
    else:
        for b in list(slot.bookings):
            db.session.delete(b)
        db.session.delete(slot)
        db.session.commit()
        flash("Slot removed.", "success")
    return redirect(url_for("examiner.slots"))


# Show students booked into a slot
@bp.route("/slots/<int:sid>")
@role_required("examiner")
def slot_students(sid):
    slot = own_slot(sid)
    return render_template("examiner/slot_students.html", slot=slot)


# List evaluations done by the examiner
@bp.route("/evaluations")
@role_required("examiner")
def evaluations():
    bookings = (Booking.query.join(Slot).filter(Slot.examiner_id == current_user.id,
                                                Booking.status.in_(["Booked", "Completed"]))
                .order_by(Slot.date, Slot.start_time).all())
    return render_template("examiner/evaluations.html", bookings=bookings)


# Record rubric marks for a booked student
@bp.route("/bookings/<int:bid>/evaluate", methods=["GET", "POST"])
@role_required("examiner")
def evaluate(bid):
    booking = Booking.query.get_or_404(bid)
    if booking.slot.examiner_id != current_user.id:
        abort(403)
    if booking.status == "Cancelled":
        flash("This booking was cancelled.", "warning")
        return redirect(url_for("examiner.evaluations"))
    exam = booking.exam
    if exam.results_published and booking.evaluation:
        flash("Results are already published; evaluation is locked.", "warning")
        return redirect(url_for("examiner.evaluations"))
    ev = booking.evaluation
    existing = {s.rubric_id: s.marks for s in ev.scores} if ev else {}

    if request.method == "POST":
        f = request.form
        scores, errors = {}, []
        if exam.rubrics:
            for r in exam.rubrics:
                m = to_float(f.get(f"rubric_{r.id}"))
                if m is None or m < 0 or m > r.max_marks:
                    errors.append(f"'{r.criterion}': enter marks between 0 and {r.max_marks:g}.")
                scores[r.id] = m
            if not errors:
                tw = exam.rubric_total_weight
                total = exam.max_marks * sum((scores[r.id] / r.max_marks) * r.weightage
                                             for r in exam.rubrics) / tw
        else:
            total = to_float(f.get("total_marks"))
            if total is None or total < 0 or total > exam.max_marks:
                errors.append(f"Enter total marks between 0 and {exam.max_marks:g}.")
        if errors:
            for e in errors:
                flash(e, "danger")
            existing = {k: v for k, v in scores.items() if v is not None}
        else:
            ev = ev or Evaluation(booking=booking, examiner_id=current_user.id)
            ev.examiner_id = current_user.id
            ev.total_marks = round(total, 2)
            ev.remarks = f.get("remarks", "").strip()
            ev.evaluated_at = datetime.now()
            ev.scores = [EvaluationScore(rubric_id=rid, marks=m) for rid, m in scores.items()]
            db.session.add(ev)
            booking.status = "Completed"
            log_booking(booking, "Evaluated", f"Marks: {ev.total_marks:g}/{exam.max_marks:g}")
            db.session.commit()
            flash(f"Evaluation saved for {booking.student.name}.", "success")
            return redirect(url_for("examiner.evaluations"))
    return render_template("examiner/evaluate.html", booking=booking, exam=exam, ev=ev, existing=existing)
