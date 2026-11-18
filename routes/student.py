from datetime import date, datetime

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_

from models import db, Course, Exam, Slot, Booking, EXAM_TYPES
from .utils import role_required, to_int, log_booking, student_clash

bp = Blueprint("student", __name__)

VISIBLE = ["Slot Creation", "Booking Open", "Closed", "Completed"]


# Query the student's bookings, optionally filtered by status
def my_bookings(*statuses):
    q = Booking.query.filter_by(student_id=current_user.id)
    if statuses:
        q = q.filter(Booking.status.in_(statuses))
    return q


# Show student dashboard with open slots and bookings
@bp.route("/")
@role_required("student")
def dashboard():
    open_exams = [e for e in Exam.query.filter_by(status="Booking Open").all() if e.booking_allowed]
    booked_exam_ids = {b.exam_id for b in my_bookings("Booked", "Completed")}
    available_slots = (Slot.query.filter(Slot.exam_id.in_([e.id for e in open_exams]),
                                         Slot.status == "Available", Slot.date >= date.today())
                       .order_by(Slot.date, Slot.start_time).all())
    active = my_bookings("Booked").join(Slot).order_by(Slot.date, Slot.start_time).all()
    upcoming = [b for b in active if b.slot.date >= date.today()]
    results = [b for b in my_bookings("Completed").all() if b.evaluation and b.exam.results_published]
    return render_template("student/dashboard.html", open_exams=open_exams, booked_exam_ids=booked_exam_ids,
                           available_slots=available_slots[:8], available_count=len(available_slots),
                           upcoming=upcoming, active=active, results=results)


# List visible exams with optional filters
@bp.route("/exams")
@role_required("student")
def exams():
    q_text = request.args.get("q", "").strip()
    course_id = to_int(request.args.get("course_id"))
    etype = request.args.get("type", "")
    only_open = request.args.get("open") == "1"
    q = Exam.query.join(Course).filter(Exam.status.in_(VISIBLE))
    if q_text:
        like = f"%{q_text}%"
        q = q.filter(or_(Exam.name.ilike(like), Course.name.ilike(like), Course.code.ilike(like)))
    if course_id:
        q = q.filter(Exam.course_id == course_id)
    if etype in EXAM_TYPES:
        q = q.filter(Exam.exam_type == etype)
    if only_open:
        q = q.filter(Exam.status == "Booking Open")
    booked = {b.exam_id: b for b in my_bookings("Booked", "Completed")}
    return render_template("student/exams.html", exams=q.order_by(Exam.booking_start.desc()).all(),
                           courses=Course.query.order_by(Course.code).all(), types=EXAM_TYPES,
                           q=q_text, course_id=course_id, etype=etype, only_open=only_open, booked=booked)


# Show an exam and its available slots
@bp.route("/exams/<int:eid>")
@role_required("student")
def exam_detail(eid):
    exam = Exam.query.get_or_404(eid)
    if exam.status not in VISIBLE:
        abort(404)
    mine = my_bookings("Booked", "Completed").filter_by(exam_id=eid).first()
    slots = [s for s in sorted(exam.slots, key=lambda s: (s.date, s.start_time)) if s.status != "Cancelled"]
    return render_template("student/exam_detail.html", exam=exam, slots=slots, mine=mine)


# Book a slot after duplicate and clash checks
@bp.route("/slots/<int:sid>/book", methods=["POST"])
@role_required("student")
def book(sid):
    slot = Slot.query.get_or_404(sid)
    exam = slot.exam
    back = redirect(url_for("student.exam_detail", eid=exam.id))
    if not exam.booking_allowed:
        flash("Booking is not open for this examination.", "danger")
        return back
    if my_bookings("Booked", "Completed").filter_by(exam_id=exam.id).first():
        flash("You already have a booking for this examination. Cancel it first to choose another slot.", "warning")
        return back
    if slot.status != "Available" or slot.date < date.today():
        flash("This slot is not available.", "danger")
        return back
    clash = student_clash(current_user.id, slot)
    if clash:
        flash(f"This slot clashes with your booking for {clash.exam.name}.", "danger")
        return back
    updated = (Slot.query.filter(Slot.id == slot.id, Slot.available_seats > 0, Slot.status == "Available")
               .update({Slot.available_seats: Slot.available_seats - 1}, synchronize_session=False))
    if not updated:
        db.session.rollback()
        flash("Sorry, this slot just filled up.", "danger")
        return back
    booking = Booking(student_id=current_user.id, slot_id=slot.id, exam_id=exam.id, status="Booked")
    db.session.add(booking)
    db.session.flush()
    db.session.refresh(slot)
    slot.refresh()
    log_booking(booking, "Booked", f"{slot.code} ({slot.label}) with {slot.examiner.name}")
    db.session.commit()
    flash(f"Booked! Your booking ID is {booking.code}.", "success")
    return redirect(url_for("student.bookings"))


# Cancel the student's booking
@bp.route("/bookings/<int:bid>/cancel", methods=["POST"])
@role_required("student")
def cancel(bid):
    booking = Booking.query.get_or_404(bid)
    if booking.student_id != current_user.id:
        abort(403)
    if booking.status != "Booked":
        flash("Only active bookings can be cancelled.", "warning")
    elif not booking.exam.booking_allowed:
        flash("The booking deadline has passed; this booking can no longer be cancelled.", "danger")
    else:
        booking.status, booking.cancelled_at = "Cancelled", datetime.now()
        db.session.flush()
        booking.slot.refresh()
        log_booking(booking, "Cancelled", "Cancelled by student")
        db.session.commit()
        flash("Booking cancelled.", "success")
    return redirect(url_for("student.bookings"))


# Show booking history and exam schedule
@bp.route("/bookings")
@role_required("student")
def bookings():
    allb = my_bookings().order_by(Booking.booking_date.desc()).all()
    schedule = sorted([b for b in allb if b.status == "Booked"], key=lambda b: (b.slot.date, b.slot.start_time))
    return render_template("student/bookings.html", bookings=allb, schedule=schedule, today=date.today())


# List the student's published results
@bp.route("/results")
@role_required("student")
def results():
    rows = [b for b in my_bookings("Completed").order_by(Booking.booking_date.desc()).all()
            if b.evaluation and b.exam.results_published]
    return render_template("student/results.html", rows=rows)


# View or download a published scorecard
@bp.route("/results/<int:bid>/scorecard")
@role_required("student")
def scorecard(bid):
    booking = Booking.query.get_or_404(bid)
    if booking.student_id != current_user.id or not booking.evaluation or not booking.exam.results_published:
        abort(404)
    html = render_template("student/scorecard.html", b=booking, generated=datetime.now())
    if request.args.get("download"):
        return Response(html, mimetype="text/html", headers={
            "Content-Disposition": f"attachment; filename=scorecard_{booking.code}.html"})
    return html
