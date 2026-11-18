from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_

from models import (db, User, Course, Exam, Rubric, Slot, Booking, Evaluation,
                    EXAM_TYPES, EXAM_STATUSES, SLOT_STATUSES, BOOKING_STATUSES)
from .utils import (role_required, parse_date, to_float, to_int, log_booking, search_id, slots_overlap,
                    student_clash)

bp = Blueprint("admin", __name__)


# Show admin dashboard with stats and recent bookings
@bp.route("/")
@role_required("admin")
def dashboard():
    stats = {
        "courses": Course.query.count(),
        "exams": Exam.query.count(),
        "examiners": User.query.filter_by(role="examiner").count(),
        "pending_examiners": User.query.filter_by(role="examiner", status="Pending").count(),
        "students": User.query.filter_by(role="student").count(),
        "slots": Slot.query.count(),
        "bookings": Booking.query.count(),
        "active_bookings": Booking.query.filter_by(status="Booked").count(),
        "evaluations": Evaluation.query.count(),
    }
    exam_status = dict(db.session.query(Exam.status, func.count(Exam.id)).group_by(Exam.status).all())
    workload = (db.session.query(User.name, func.count(Booking.id))
                .join(Slot, Slot.examiner_id == User.id)
                .outerjoin(Booking, (Booking.slot_id == Slot.id) & (Booking.status != "Cancelled"))
                .group_by(User.id).order_by(func.count(Booking.id).desc()).limit(6).all())
    max_work = max([w[1] for w in workload] + [1])
    recent = Booking.query.order_by(Booking.booking_date.desc()).limit(6).all()
    return render_template("admin/dashboard.html", stats=stats, exam_status=exam_status,
                           statuses=EXAM_STATUSES, workload=workload, max_work=max_work, recent=recent)


# List all courses
@bp.route("/courses")
@role_required("admin")
def courses():
    return render_template("admin/courses.html", courses=Course.query.order_by(Course.code).all())


# Create or edit a course
@bp.route("/courses/new", methods=["GET", "POST"])
@bp.route("/courses/<int:cid>/edit", methods=["GET", "POST"])
@role_required("admin")
def course_form(cid=None):
    course = Course.query.get_or_404(cid) if cid else None
    if request.method == "POST":
        f = request.form
        code, name = f.get("code", "").strip().upper(), f.get("name", "").strip()
        dup = Course.query.filter(Course.code == code, Course.id != (cid or 0)).first()
        if not code or not name:
            flash("Course code and name are required.", "danger")
        elif dup:
            flash("Another course already uses this code.", "danger")
        else:
            course = course or Course()
            course.code, course.name = code, name
            course.description = f.get("description", "").strip()
            course.credits = to_int(f.get("credits"))
            course.status = f.get("status", "Active")
            db.session.add(course)
            db.session.commit()
            flash("Course saved.", "success")
            return redirect(url_for("admin.courses"))
    return render_template("admin/course_form.html", course=course)


# Delete a course that has no exams
@bp.route("/courses/<int:cid>/delete", methods=["POST"])
@role_required("admin")
def course_delete(cid):
    course = Course.query.get_or_404(cid)
    if course.exams:
        flash("This course has examinations. Remove them first or mark the course Inactive.", "warning")
    else:
        db.session.delete(course)
        db.session.commit()
        flash("Course removed.", "success")
    return redirect(url_for("admin.courses"))


# List exams with optional filters
@bp.route("/exams")
@role_required("admin")
def exams():
    q = Exam.query.join(Course)
    status = request.args.get("status")
    if status:
        q = q.filter(Exam.status == status)
    return render_template("admin/exams.html", exams=q.order_by(Exam.id.desc()).all(),
                           statuses=EXAM_STATUSES, status=status)


# Create or edit an exam
@bp.route("/exams/new", methods=["GET", "POST"])
@bp.route("/exams/<int:eid>/edit", methods=["GET", "POST"])
@role_required("admin")
def exam_form(eid=None):
    exam = Exam.query.get_or_404(eid) if eid else None
    courses = Course.query.filter_by(status="Active").order_by(Course.code).all()
    if exam and exam.course not in courses:
        courses.append(exam.course)
    if request.method == "POST":
        f = request.form
        try:
            data = dict(
                course_id=int(f["course_id"]), name=f["name"].strip(), exam_type=f["exam_type"],
                description=f.get("description", "").strip(),
                duration=int(f["duration"]), max_marks=float(f["max_marks"]),
                pass_marks=to_float(f.get("pass_marks")),
                slot_creation_start=parse_date(f.get("slot_creation_start")),
                slot_creation_end=parse_date(f.get("slot_creation_end")),
                booking_start=parse_date(f.get("booking_start")),
                booking_end=parse_date(f.get("booking_end")),
            )
        except (KeyError, ValueError):
            flash("Please fill all required fields with valid values.", "danger")
            return render_template("admin/exam_form.html", exam=exam, courses=courses, types=EXAM_TYPES)
        errors = []
        if not data["name"] or data["exam_type"] not in EXAM_TYPES:
            errors.append("Name and a valid examination type are required.")
        if data["duration"] <= 0 or data["max_marks"] <= 0:
            errors.append("Duration and maximum marks must be positive.")
        if data["pass_marks"] is not None and data["pass_marks"] > data["max_marks"]:
            errors.append("Pass marks cannot exceed maximum marks.")
        for a, b, label in [("slot_creation_start", "slot_creation_end", "Slot creation"),
                            ("booking_start", "booking_end", "Slot booking")]:
            if data[a] and data[b] and data[a] > data[b]:
                errors.append(f"{label} start date must be on or before its end date.")
        if data["slot_creation_end"] and data["booking_start"] and data["booking_start"] < data["slot_creation_end"]:
            errors.append("Booking should start after the slot creation period ends.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("admin/exam_form.html", exam=exam, courses=courses, types=EXAM_TYPES)
        exam = exam or Exam(status="Draft")
        for k, v in data.items():
            setattr(exam, k, v)
        db.session.add(exam)
        db.session.commit()
        flash("Examination saved.", "success")
        return redirect(url_for("admin.exam_detail", eid=exam.id))
    return render_template("admin/exam_form.html", exam=exam, courses=courses, types=EXAM_TYPES)


# Show details of a single exam
@bp.route("/exams/<int:eid>")
@role_required("admin")
def exam_detail(eid):
    exam = Exam.query.get_or_404(eid)
    examiners = User.query.filter_by(role="examiner", status="Active").order_by(User.name).all()
    bookings = Booking.query.filter_by(exam_id=eid).order_by(Booking.booking_date.desc()).all()
    return render_template("admin/exam_detail.html", exam=exam, examiners=examiners, bookings=bookings)


# Delete an exam if it has no bookings
@bp.route("/exams/<int:eid>/delete", methods=["POST"])
@role_required("admin")
def exam_delete(eid):
    exam = Exam.query.get_or_404(eid)
    if Booking.query.filter_by(exam_id=eid).first():
        flash("Examination has booking records and cannot be removed (history must be preserved). "
              "Mark it Closed or Completed instead.", "warning")
        return redirect(url_for("admin.exam_detail", eid=eid))
    db.session.delete(exam)
    db.session.commit()
    flash("Examination removed.", "success")
    return redirect(url_for("admin.exams"))


# Advance the exam timeline or publish results
@bp.route("/exams/<int:eid>/status", methods=["POST"])
@role_required("admin")
def exam_status(eid):
    exam = Exam.query.get_or_404(eid)
    action = request.form.get("action")
    if action == "open_slots":
        exam.status = "Slot Creation"
        msg = "Examiner slot creation opened."
    elif action == "close_slots":
        exam.status = "Closed"
        msg = "Examiner slot creation closed."
    elif action == "open_booking":
        if not any(s.status == "Available" for s in exam.slots):
            flash("There are no available slots yet; students will have nothing to book.", "warning")
        exam.status = "Booking Open"
        msg = "Student slot booking opened."
    elif action == "close_booking":
        exam.status = "Closed"
        msg = "Student slot booking closed."
    elif action == "complete":
        exam.status = "Completed"
        for s in exam.slots:
            if s.status != "Cancelled":
                s.status = "Completed"
        msg = "Examination marked as completed."
    elif action == "draft":
        exam.status = "Draft"
        msg = "Examination moved back to draft."
    elif action == "publish":
        exam.results_published = True
        msg = "Results published to students."
    elif action == "unpublish":
        exam.results_published = False
        msg = "Results hidden from students."
    else:
        flash("Unknown action.", "danger")
        return redirect(url_for("admin.exam_detail", eid=eid))
    db.session.commit()
    flash(msg, "success")
    return redirect(url_for("admin.exam_detail", eid=eid))


# Assign examiners to an exam
@bp.route("/exams/<int:eid>/examiners", methods=["POST"])
@role_required("admin")
def exam_examiners(eid):
    exam = Exam.query.get_or_404(eid)
    ids = {int(i) for i in request.form.getlist("examiner_ids")}
    exam.examiners = User.query.filter(User.id.in_(ids), User.role == "examiner").all() if ids else []
    db.session.commit()
    flash("Examiner assignment updated.", "success")
    return redirect(url_for("admin.exam_detail", eid=eid))


# Add a rubric criterion to an exam
@bp.route("/exams/<int:eid>/rubrics/new", methods=["GET", "POST"])
@bp.route("/rubrics/<int:rid>/edit", methods=["GET", "POST"])
@role_required("admin")
def rubric_form(eid=None, rid=None):
    rubric = Rubric.query.get_or_404(rid) if rid else None
    exam = rubric.exam if rubric else Exam.query.get_or_404(eid)
    if request.method == "POST":
        f = request.form
        criterion = f.get("criterion", "").strip()
        max_marks, weightage = to_float(f.get("max_marks")), to_float(f.get("weightage"))
        other_weight = sum(r.weightage for r in exam.rubrics if r is not rubric)
        if not criterion or not max_marks or max_marks <= 0 or weightage is None or weightage <= 0:
            flash("Criterion, positive maximum marks and weightage are required.", "danger")
        elif other_weight + weightage > 100:
            flash(f"Total weightage would exceed 100% (currently {other_weight:g}% used).", "danger")
        else:
            rubric = rubric or Rubric(exam=exam)
            rubric.criterion, rubric.max_marks, rubric.weightage = criterion, max_marks, weightage
            rubric.description = f.get("description", "").strip()
            db.session.add(rubric)
            db.session.commit()
            flash("Rubric criterion saved.", "success")
            return redirect(url_for("admin.exam_detail", eid=exam.id))
    return render_template("admin/rubric_form.html", rubric=rubric, exam=exam)


# Delete a rubric criterion
@bp.route("/rubrics/<int:rid>/delete", methods=["POST"])
@role_required("admin")
def rubric_delete(rid):
    rubric = Rubric.query.get_or_404(rid)
    eid = rubric.exam_id
    from models import EvaluationScore
    if EvaluationScore.query.filter_by(rubric_id=rid).first():
        flash("This criterion has already been used in evaluations and cannot be removed.", "warning")
    else:
        db.session.delete(rubric)
        db.session.commit()
        flash("Rubric criterion removed.", "success")
    return redirect(url_for("admin.exam_detail", eid=eid))


# List all examiners
@bp.route("/examiners")
@role_required("admin")
def examiners():
    status = request.args.get("status")
    q = User.query.filter_by(role="examiner")
    if status:
        q = q.filter_by(status=status)
    return render_template("admin/examiners.html", examiners=q.order_by(User.status.desc(), User.name).all(),
                           status=status)


# Create a new examiner account
@bp.route("/examiners/new", methods=["GET", "POST"])
@role_required("admin")
def examiner_new():
    if request.method == "POST":
        f = request.form
        email = f.get("email", "").strip().lower()
        if not f.get("name") or not email or len(f.get("password", "")) < 6:
            flash("Name, email and a password of at least 6 characters are required.", "danger")
        elif User.query.filter_by(email=email).first():
            flash("Email already registered.", "danger")
        else:
            u = User(role="examiner", name=f["name"].strip(), email=email, phone=f.get("phone"),
                     department=f.get("department"), designation=f.get("designation"), status="Active")
            u.set_password(f["password"])
            db.session.add(u)
            db.session.commit()
            flash("Examiner added and activated.", "success")
            return redirect(url_for("admin.examiners"))
    return render_template("admin/examiner_form.html")


# Approve, activate or deactivate a user
@bp.route("/users/<int:uid>/status", methods=["POST"])
@role_required("admin")
def user_status(uid):
    user = User.query.get_or_404(uid)
    if user.role == "admin":
        flash("The administrator account cannot be changed.", "danger")
    else:
        user.status = {"approve": "Active", "activate": "Active", "deactivate": "Inactive"}.get(
            request.form.get("action"), user.status)
        db.session.commit()
        flash(f"{user.name} is now {user.status}.", "success")
    return redirect(request.referrer or url_for("admin.dashboard"))


# Show details of a single user
@bp.route("/users/<int:uid>")
@role_required("admin")
def user_detail(uid):
    user = User.query.get_or_404(uid)
    return render_template("admin/user_detail.html", user=user)


# List all students
@bp.route("/students")
@role_required("admin")
def students():
    return render_template("admin/students.html",
                           students=User.query.filter_by(role="student").order_by(User.name).all())


# List all slots with optional filters
@bp.route("/slots")
@role_required("admin")
def slots():
    q = Slot.query
    eid, status = to_int(request.args.get("exam_id")), request.args.get("status")
    if eid:
        q = q.filter_by(exam_id=eid)
    if status:
        q = q.filter_by(status=status)
    return render_template("admin/slots.html", slots=q.order_by(Slot.date, Slot.start_time).all(),
                           exams=Exam.query.order_by(Exam.name).all(), eid=eid, status=status,
                           statuses=SLOT_STATUSES)


# Reassign a slot to another examiner
@bp.route("/slots/<int:sid>/examiner", methods=["GET", "POST"])
@role_required("admin")
def slot_change_examiner(sid):
    slot = Slot.query.get_or_404(sid)
    examiners = User.query.filter(User.role == "examiner", User.status == "Active",
                                  User.id != slot.examiner_id).order_by(User.name).all()
    if request.method == "POST":
        new = User.query.filter_by(id=to_int(request.form.get("examiner_id")), role="examiner").first()
        if not new:
            flash("Choose a valid examiner.", "danger")
        elif slots_overlap(new.id, slot.date, slot.start_time, slot.end_time):
            flash(f"{new.name} already has a slot overlapping this time.", "danger")
        else:
            old = slot.examiner
            slot.examiner = new
            if new not in slot.exam.examiners:
                slot.exam.examiners.append(new)
            reason = request.form.get("reason", "").strip()
            for b in slot.active_bookings:
                log_booking(b, "Examiner Changed", f"{old.name} -> {new.name}. {reason}")
            db.session.commit()
            flash(f"Slot {slot.code} reassigned from {old.name} to {new.name}.", "success")
            return redirect(url_for("admin.slots", exam_id=slot.exam_id))
    return render_template("admin/slot_examiner.html", slot=slot, examiners=examiners)


# Cancel a slot and its bookings
@bp.route("/slots/<int:sid>/cancel", methods=["POST"])
@role_required("admin")
def slot_cancel(sid):
    slot = Slot.query.get_or_404(sid)
    for b in slot.bookings:
        if b.status == "Booked":
            b.status = "Cancelled"
            log_booking(b, "Cancelled", "Slot cancelled by admin")
    slot.status = "Cancelled"
    slot.available_seats = 0
    db.session.commit()
    flash(f"Slot {slot.code} cancelled; its bookings were cancelled.", "warning")
    return redirect(request.referrer or url_for("admin.slots"))


# List all bookings with optional filters
@bp.route("/bookings")
@role_required("admin")
def bookings():
    q = Booking.query
    eid, status = to_int(request.args.get("exam_id")), request.args.get("status")
    if eid:
        q = q.filter_by(exam_id=eid)
    if status:
        q = q.filter_by(status=status)
    return render_template("admin/bookings.html", bookings=q.order_by(Booking.booking_date.desc()).all(),
                           exams=Exam.query.order_by(Exam.name).all(), eid=eid, status=status,
                           statuses=BOOKING_STATUSES)


# Show a booking and its history
@bp.route("/bookings/<int:bid>")
@role_required("admin")
def booking_detail(bid):
    return render_template("admin/booking_detail.html", booking=Booking.query.get_or_404(bid))


# Move a booking to a different slot
@bp.route("/bookings/<int:bid>/reschedule", methods=["GET", "POST"])
@role_required("admin")
def booking_reschedule(bid):
    booking = Booking.query.get_or_404(bid)
    if booking.status != "Booked":
        flash("Only active bookings can be rescheduled.", "warning")
        return redirect(url_for("admin.booking_detail", bid=bid))
    options = Slot.query.filter(Slot.exam_id == booking.exam_id, Slot.id != booking.slot_id,
                                Slot.status == "Available").order_by(Slot.date, Slot.start_time).all()
    if request.method == "POST":
        new_slot = db.session.get(Slot, to_int(request.form.get("slot_id")) or 0)
        clash = new_slot and student_clash(booking.student_id, new_slot, exclude_booking_id=booking.id)
        if not new_slot or new_slot not in options:
            flash("Choose an available slot of the same examination.", "danger")
        elif clash:
            flash(f"{booking.student.name} already has a booking at that time "
                  f"({clash.code}, {clash.exam.name}).", "danger")
        else:
            old_slot = booking.slot
            booking.slot = new_slot
            db.session.flush()
            old_slot.refresh()
            new_slot.refresh()
            log_booking(booking, "Rescheduled",
                        f"{old_slot.code} ({old_slot.label}) -> {new_slot.code} ({new_slot.label}). "
                        + request.form.get("reason", "").strip())
            db.session.commit()
            flash("Booking rescheduled.", "success")
            return redirect(url_for("admin.booking_detail", bid=bid))
    return render_template("admin/booking_reschedule.html", booking=booking, options=options)


# Cancel a booking on a student's behalf
@bp.route("/bookings/<int:bid>/cancel", methods=["POST"])
@role_required("admin")
def booking_cancel(bid):
    from datetime import datetime
    booking = Booking.query.get_or_404(bid)
    if booking.status == "Booked":
        booking.status, booking.cancelled_at = "Cancelled", datetime.now()
        db.session.flush()
        booking.slot.refresh()
        log_booking(booking, "Cancelled", "Cancelled by admin")
        db.session.commit()
        flash("Booking cancelled.", "success")
    return redirect(url_for("admin.booking_detail", bid=bid))


# Search users, exams, slots and bookings
@bp.route("/search")
@role_required("admin")
def search():
    q = request.args.get("q", "").strip()
    results = {"students": [], "examiners": [], "exams": [], "bookings": []}
    if q:
        like = f"%{q}%"
        for role, prefix in (("student", "STU"), ("examiner", "EXR")):
            uid = search_id(q, prefix)
            cond = [User.name.ilike(like), User.email.ilike(like)]
            if role == "student":
                cond.append(User.roll_no.ilike(like))
            else:
                cond.append(User.department.ilike(like))
            if uid:
                cond.append(User.id == uid)
            results[role + "s"] = User.query.filter(User.role == role, or_(*cond)).all()
        eid = search_id(q, "EXM")
        results["exams"] = Exam.query.join(Course).filter(or_(
            Exam.name.ilike(like), Course.name.ilike(like), Course.code.ilike(like),
            Exam.id == (eid or -1))).all()
        bid = search_id(q, "BKG")
        results["bookings"] = Booking.query.join(User, Booking.student_id == User.id).join(Exam).filter(or_(
            User.name.ilike(like), User.roll_no.ilike(like), Exam.name.ilike(like),
            Booking.id == (bid or -1))).all()
    return render_template("admin/search.html", q=q, results=results)
