from flask import Blueprint, jsonify, request

from models import User, Exam, Slot, Booking, Course
from .utils import role_required

bp = Blueprint("api", __name__)


# Format a date as ISO string or None
def d(v):
    return v.isoformat() if v else None


# Serialize an exam, optionally with full details
def exam_json(e, full=False):
    data = {"id": e.id, "code": e.code, "name": e.name, "type": e.exam_type,
            "course": {"id": e.course.id, "code": e.course.code, "name": e.course.name},
            "duration_min": e.duration, "max_marks": e.max_marks, "status": e.status,
            "slot_creation": [d(e.slot_creation_start), d(e.slot_creation_end)],
            "booking": [d(e.booking_start), d(e.booking_end)],
            "results_published": e.results_published}
    if full:
        data["rubrics"] = [{"id": r.id, "criterion": r.criterion, "max_marks": r.max_marks,
                            "weightage": r.weightage} for r in e.rubrics]
        data["examiners"] = [{"id": u.id, "name": u.name} for u in e.examiners]
        data["slots"] = [slot_json(s) for s in e.slots]
    return data


# Serialize a slot to a dict
def slot_json(s):
    return {"id": s.id, "exam_id": s.exam_id, "examiner_id": s.examiner_id, "examiner": s.examiner.name,
            "date": d(s.date), "start": s.start_time.strftime("%H:%M"), "end": s.end_time.strftime("%H:%M"),
            "capacity": s.capacity, "available_seats": s.available_seats, "status": s.status}


# Serialize an examiner or student to a dict
def user_json(u):
    data = {"id": u.id, "code": u.code, "name": u.name, "email": u.email, "phone": u.phone, "status": u.status}
    if u.role == "examiner":
        data.update(department=u.department, designation=u.designation,
                    assigned_exams=[e.id for e in u.assigned_exams])
    else:
        data.update(roll_no=u.roll_no, program=u.program)
    return data


# Return all exams as JSON, optionally filtered
@bp.route("/exams")
@role_required("admin")
def exams():
    q = Exam.query
    if request.args.get("status"):
        q = q.filter_by(status=request.args["status"])
    return jsonify([exam_json(e) for e in q.all()])


# Return one exam with full details as JSON
@bp.route("/exams/<int:eid>")
@role_required("admin")
def exam(eid):
    return jsonify(exam_json(Exam.query.get_or_404(eid), full=True))


# Return all examiners as JSON
@bp.route("/examiners")
@role_required("admin")
def examiners():
    return jsonify([user_json(u) for u in User.query.filter_by(role="examiner").all()])


# Return all students as JSON
@bp.route("/students")
@role_required("admin")
def students():
    return jsonify([user_json(u) for u in User.query.filter_by(role="student").all()])


# Return all slots as JSON
@bp.route("/slots")
@role_required("admin")
def slots():
    return jsonify([slot_json(s) for s in Slot.query.all()])


# Return all bookings as JSON
@bp.route("/bookings")
@role_required("admin")
def bookings():
    return jsonify([{
        "id": b.id, "code": b.code, "student_id": b.student_id, "student": b.student.name,
        "exam_id": b.exam_id, "slot_id": b.slot_id, "status": b.status,
        "booking_date": d(b.booking_date),
        "marks": b.evaluation.total_marks if b.evaluation else None,
    } for b in Booking.query.all()])


# Return record counts for each entity as JSON
@bp.route("/stats")
@role_required("admin")
def stats():
    return jsonify({
        "courses": Course.query.count(), "exams": Exam.query.count(),
        "examiners": User.query.filter_by(role="examiner").count(),
        "students": User.query.filter_by(role="student").count(),
        "slots": Slot.query.count(), "bookings": Booking.query.count(),
    })
