from datetime import datetime
from functools import wraps

from flask import abort, flash, redirect, url_for
from flask_login import current_user, login_required

from models import db, BookingLog


# Restrict a view to active users of a role
def role_required(role):
    # Wrap a view with role and status checks
    def decorator(view):
        # Enforce login, role and account status before view
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role != role:
                abort(403)
            if current_user.status == "Pending":
                return redirect(url_for("auth.pending"))
            if current_user.status != "Active":
                flash("Your account is inactive. Contact the administrator.", "danger")
                return redirect(url_for("auth.logout"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


# Parse a YYYY-MM-DD string into a date
def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


# Parse an HH:MM string into a time
def parse_time(value):
    return datetime.strptime(value, "%H:%M").time() if value else None


# Convert to float, returning default on failure
def to_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# Convert to int, returning default on failure
def to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# Add an audit log entry for a booking
def log_booking(booking, action, details=""):
    db.session.add(BookingLog(booking=booking, action=action, details=details,
                              actor_id=current_user.id if current_user.is_authenticated else None))


# Check whether an examiner's slot clashes with another
def slots_overlap(examiner_id, slot_date, start, end, exclude_id=None):
    from models import Slot
    q = Slot.query.filter(Slot.examiner_id == examiner_id, Slot.date == slot_date,
                          Slot.status != "Cancelled",
                          Slot.start_time < end, Slot.end_time > start)
    if exclude_id:
        q = q.filter(Slot.id != exclude_id)
    return q.first() is not None


# Find a student's active booking whose slot overlaps the given slot
def student_clash(student_id, slot, exclude_booking_id=None):
    from models import Booking, Slot
    q = Booking.query.join(Slot).filter(Booking.student_id == student_id, Booking.status == "Booked",
                                        Slot.date == slot.date,
                                        Slot.start_time < slot.end_time, Slot.end_time > slot.start_time)
    if exclude_booking_id:
        q = q.filter(Booking.id != exclude_booking_id)
    return q.first()


# Parse a plain or prefixed ID into an int
def search_id(q, prefix):
    q = q.strip().upper()
    if q.startswith(prefix):
        q = q[len(prefix):]
    return int(q) if q.isdigit() else None
