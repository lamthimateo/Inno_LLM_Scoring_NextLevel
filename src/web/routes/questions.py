"""Questions tab routes.

Endpoints
---------

GET  /questions                            list + filter
GET  /questions/import                     upload form
POST /questions/import                     upload + parse + create draft set
GET  /questions/{set_id}                   detail (questions list + actions)
GET  /questions/{set_id}/edit              edit metadata
POST /questions/{set_id}/edit              save metadata
GET  /questions/{set_id}/{qid}             question detail / edit form
POST /questions/{set_id}/{qid}/edit        apply edit (creates new version)
POST /questions/{set_id}/submit-review     transition: draft -> in_review
POST /questions/{set_id}/approve           transition: in_review -> approved
POST /questions/{set_id}/lock              transition: approved -> locked
POST /questions/{set_id}/revert            transition: -> draft (with reason)
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from src.auth.dependencies import require_login
from src.benchmark.importing import (
    ImportError as ImportFailure,
    import_questions,
    parse_questions_from_text,
)
from src.benchmark.queries import (
    count_by_status,
    get_question,
    get_set_with_questions,
    list_question_versions,
    list_sets,
)
from src.benchmark.validation import validate_questions
from src.benchmark.workflow import (
    WorkflowError,
    approve,
    lock,
    revert_to_draft,
    submit_review,
    update_question,
)
from src.storage.db import get_session
from src.storage.models import QuestionSet, SetStatus, User, UserRole
from src.web.templating import render, templates


router = APIRouter(prefix="/questions", tags=["questions"])


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------


def _is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN.value


def _is_author_of(user: User, qs: QuestionSet) -> bool:
    return qs.author_id is not None and qs.author_id == user.id


def _is_reviewer_of(user: User, qs: QuestionSet) -> bool:
    return qs.reviewer_id is not None and qs.reviewer_id == user.id


def _ensure_author_or_admin(user: User, qs: QuestionSet) -> None:
    if not (_is_admin(user) or _is_author_of(user, qs)):
        raise HTTPException(
            status_code=403,
            detail="Only the set's author or an admin can perform this action.",
        )


def _ensure_reviewer_or_admin(user: User, qs: QuestionSet) -> None:
    """For approve/lock: must be assigned reviewer or admin AND not the author."""

    if _is_author_of(user, qs) and not _is_admin(user):
        raise HTTPException(
            status_code=403, detail="The author cannot review their own set."
        )
    if not (_is_admin(user) or _is_reviewer_of(user, qs)):
        raise HTTPException(
            status_code=403,
            detail="Only the assigned reviewer or an admin can perform this action.",
        )


def _flash_redirect(target: str, *, ok: str = "", error: str = "") -> RedirectResponse:
    sep = "&" if "?" in target else "?"
    params = []
    if ok:
        params.append(f"ok={quote(ok)}")
    if error:
        params.append(f"error={quote(error)}")
    url = f"{target}{sep}{'&'.join(params)}" if params else target
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def list_view(
    request: Request,
    status: Optional[str] = None,
    q: Optional[str] = None,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    sets = list_sets(session, status=status or None, search=q or None)
    counts = count_by_status(session)
    return render(
        request,
        "questions/list.html",
        current_user=user,
        active_tab="questions",
        sets=sets,
        counts=counts,
        filter_status=status or "",
        filter_search=q or "",
        # Aliases expected by the design-system templates:
        filters={"status": status or "", "q": q or ""},
        sets_count_total=counts.get("total", 0),
        sets_count_draft=counts.get("draft", 0),
        sets_count_review=counts.get("in_review", 0),
        sets_count_approved=counts.get("approved", 0),
        sets_count_locked=counts.get("locked", 0),
    )


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


@router.get("/import", response_class=HTMLResponse)
def import_form(
    request: Request, user: User = Depends(require_login),
):
    return render(
        request,
        "questions/import.html",
        current_user=user,
        active_tab="questions",
        error=None,
        form={"set_id": "", "title": "", "description": ""},
    )


@router.post("/import")
async def import_submit(
    request: Request,
    set_id: str = Form(...),
    title: str = Form(""),
    description: str = Form(""),
    files: list[UploadFile] = File(default_factory=list),
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    error: Optional[str] = None
    form = {"set_id": set_id, "title": title, "description": description}

    # Files come back from Starlette as a list of one empty UploadFile when
    # the input is left blank — treat those as "no files" so the validation
    # error fires before we wade into the temp-dir / parse path.
    real_files = [f for f in files if (f.filename or "").strip()]

    set_id_clean = set_id.strip()

    if not set_id_clean:
        error = "Set ID is required."
    elif session.get(QuestionSet, set_id_clean) is not None:
        error = (
            f"A set with ID {set_id_clean!r} already exists. "
            "Pick a different Set ID (e.g. add a _v2 suffix)."
        )
    elif not real_files:
        error = "Please upload at least one .txt file."

    if error is None:
        with tempfile.TemporaryDirectory(prefix="import_") as tmp:
            tmpdir = Path(tmp)
            count = 0
            for f in real_files:
                if not (f.filename or "").lower().endswith(".txt"):
                    continue
                target = tmpdir / Path(f.filename).name
                # The HTMX preview may have already consumed f.file's stream
                # cursor in front-end retries; rewind defensively before
                # copying so the save path never sees an empty file.
                try:
                    f.file.seek(0)
                except Exception:
                    pass
                with target.open("wb") as out:
                    shutil.copyfileobj(f.file, out)
                count += 1
            if count == 0:
                error = "No .txt files were uploaded."
            else:
                try:
                    summary = import_questions(
                        session,
                        source=tmpdir,
                        set_id=set_id_clean,
                        author_id=user.id,
                        title=title.strip() or None,
                        description=description.strip() or None,
                    )
                except ImportFailure as exc:
                    session.rollback()
                    error = str(exc)
                else:
                    session.commit()
                    return _flash_redirect(
                        f"/questions/{set_id_clean}",
                        ok=(
                            f"Imported {summary.inserted_count} questions "
                            f"({len(summary.warnings)} warnings)."
                        ),
                    )

    return render(
        request,
        "questions/import.html",
        current_user=user,
        active_tab="questions",
        error=error,
        form=form,
        status_code=400,
    )


# ---------------------------------------------------------------------------
# Live preview (HTMX)
# ---------------------------------------------------------------------------


@router.post("/preview", response_class=HTMLResponse)
async def preview(
    request: Request,
    files: list[UploadFile] = File(default_factory=list),
    user: User = Depends(require_login),
):
    """Parse uploaded .txt files in-memory and return an HTML preview fragment.

    The Questions → Import dropzone HTMX-posts file selections here on
    ``change``. Nothing is persisted — this is a pure preview that mirrors
    the static checks run by ``scripts/benchmark_review.py`` so the user
    sees parse counts and validation findings before saving.
    """

    parsed_total: list = []
    file_errors: list[str] = []

    accepted_files = [
        f for f in files if (f.filename or "").strip()
    ]

    for f in accepted_files:
        raw = await f.read()
        if not raw:
            file_errors.append(f"{f.filename or '(unnamed)'}: empty file")
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            file_errors.append(
                f"{f.filename or '(unnamed)'}: not valid UTF-8 — re-save the file as UTF-8"
            )
            continue
        try:
            parsed_total.extend(
                parse_questions_from_text(text, source_name=f.filename or "<upload>")
            )
        except ImportFailure as exc:
            file_errors.append(f"{f.filename or '(unnamed)'}: {exc}")

    report = validate_questions(parsed_total)

    response = templates.TemplateResponse(
        request,
        "questions/_preview_fragment.html",
        {
            "current_user": user,
            "questions": parsed_total,
            "summary": {
                "total": report.total,
                "by_category": report.by_category,
                "file_count": len(accepted_files),
            },
            "validation": report,
            "file_errors": file_errors,
            "no_files": len(accepted_files) == 0,
        },
    )
    response.headers["HX-Trigger"] = "set:revalidated"
    return response


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


@router.get("/{set_id}", response_class=HTMLResponse)
def detail(
    request: Request,
    set_id: str,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    found = get_set_with_questions(session, set_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Question set not found.")
    qs, questions = found

    counts_by_cat: dict[str, int] = {}
    for q in questions:
        counts_by_cat[q.category] = counts_by_cat.get(q.category, 0) + 1
        # The polished detail template iterates ``q.choices.items()`` —
        # adapt our ORM list-of-dicts to the {letter: text} dict it wants.
        q.choices = {c["label"]: c["text"] for c in (q.choices_json or [])}

    return render(
        request,
        "questions/detail.html",
        current_user=user,
        active_tab="questions",
        qs=qs,
        set=qs,  # alias for the design-system templates
        questions=questions,
        counts_by_cat=counts_by_cat,
        can_view_answers=True,
        can_edit=(
            qs.status in (SetStatus.DRAFT.value, SetStatus.IN_REVIEW.value)
            and (_is_author_of(user, qs) or _is_admin(user))
        ),
        can_submit=(
            qs.status == SetStatus.DRAFT.value
            and (_is_author_of(user, qs) or _is_admin(user))
        ),
        can_approve=(
            qs.status == SetStatus.IN_REVIEW.value
            and (_is_admin(user) or _is_reviewer_of(user, qs))
            and not _is_author_of(user, qs)
        ),
        can_lock=(
            qs.status == SetStatus.APPROVED.value
            and (_is_admin(user) or _is_reviewer_of(user, qs))
        ),
        can_revert=(
            qs.status in (SetStatus.IN_REVIEW.value, SetStatus.APPROVED.value)
            and (
                _is_admin(user)
                or _is_reviewer_of(user, qs)
                or _is_author_of(user, qs)
            )
        ),
    )


# ---------------------------------------------------------------------------
# Edit metadata
# ---------------------------------------------------------------------------


@router.get("/{set_id}/edit", response_class=HTMLResponse)
def edit_metadata_form(
    request: Request,
    set_id: str,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    qs = session.get(QuestionSet, set_id)
    if qs is None:
        raise HTTPException(status_code=404, detail="Question set not found.")
    _ensure_author_or_admin(user, qs)
    return render(
        request,
        "questions/edit_set.html",
        current_user=user,
        active_tab="questions",
        qs=qs,
        set=qs,
        error=None,
    )


@router.post("/{set_id}/edit")
def edit_metadata_submit(
    request: Request,
    set_id: str,
    title: str = Form(""),
    description: str = Form(""),
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    qs = session.get(QuestionSet, set_id)
    if qs is None:
        raise HTTPException(status_code=404, detail="Question set not found.")
    _ensure_author_or_admin(user, qs)
    if qs.status == SetStatus.LOCKED.value:
        raise HTTPException(status_code=400, detail="Locked sets cannot be edited.")

    qs.title = title.strip() or None
    qs.description = description.strip() or None
    session.commit()
    return _flash_redirect(f"/questions/{set_id}", ok="Set metadata updated.")


# ---------------------------------------------------------------------------
# Question detail / edit
# ---------------------------------------------------------------------------


@router.get("/{set_id}/{qid}", response_class=HTMLResponse)
def question_detail(
    request: Request,
    set_id: str,
    qid: str,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    q = get_question(session, set_id=set_id, qid=qid)
    if q is None:
        raise HTTPException(status_code=404, detail="Question not found.")
    qs = session.get(QuestionSet, set_id)
    versions = list_question_versions(session, set_id=set_id, qid=qid)

    can_edit = qs.status in (SetStatus.DRAFT.value, SetStatus.IN_REVIEW.value) and (
        _is_author_of(user, qs) or _is_admin(user)
    )

    # The design-system template uses ``question.choices`` as a {letter: text}
    # dict and ``question.versions`` for the diff CTA. Attach both onto the
    # ORM object so the template doesn't have to know about choices_json.
    q.choices = {c["label"]: c["text"] for c in (q.choices_json or [])}
    q.versions = versions

    return render(
        request,
        "questions/edit.html",
        current_user=user,
        active_tab="questions",
        qs=qs,
        q=q,
        set=qs,
        question=q,
        versions=versions,
        can_edit=can_edit,
        error=None,
    )


@router.post("/{set_id}/{qid}/edit")
def question_edit_submit(
    request: Request,
    set_id: str,
    qid: str,
    prompt: str = Form(...),
    choice_a: str = Form(""),
    choice_b: str = Form(""),
    choice_c: str = Form(""),
    choice_d: str = Form(""),
    choice_e: str = Form(""),
    correct_answer: str = Form(""),
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    qs = session.get(QuestionSet, set_id)
    if qs is None:
        raise HTTPException(status_code=404, detail="Question set not found.")
    _ensure_author_or_admin(user, qs)

    raw_choices = [
        ("A", choice_a),
        ("B", choice_b),
        ("C", choice_c),
        ("D", choice_d),
        ("E", choice_e),
    ]
    choices = [{"label": letter, "text": text.strip()} for letter, text in raw_choices]
    if any(not c["text"] for c in choices):
        return _flash_redirect(
            f"/questions/{set_id}/{qid}",
            error="All 5 choices (A-E) are required.",
        )
    correct = correct_answer.strip().upper() or None
    if correct is not None and correct not in {"A", "B", "C", "D", "E"}:
        return _flash_redirect(
            f"/questions/{set_id}/{qid}",
            error="Correct answer must be one of A/B/C/D/E (or blank).",
        )

    try:
        update_question(
            session,
            set_id=set_id,
            qid=qid,
            prompt=prompt.strip(),
            choices=choices,
            correct_answer=correct,
            actor_id=user.id,
        )
    except WorkflowError as exc:
        session.rollback()
        return _flash_redirect(f"/questions/{set_id}/{qid}", error=str(exc))

    session.commit()
    return _flash_redirect(f"/questions/{set_id}/{qid}", ok="Question updated.")


# ---------------------------------------------------------------------------
# Workflow transitions
# ---------------------------------------------------------------------------


@router.post("/{set_id}/submit-review")
def submit_review_view(
    request: Request,
    set_id: str,
    reviewer_id: int = Form(...),
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    qs = session.get(QuestionSet, set_id)
    if qs is None:
        raise HTTPException(status_code=404, detail="Question set not found.")
    _ensure_author_or_admin(user, qs)
    try:
        submit_review(
            session, set_id=set_id, reviewer_id=reviewer_id, actor_id=user.id
        )
    except WorkflowError as exc:
        session.rollback()
        return _flash_redirect(f"/questions/{set_id}", error=str(exc))
    session.commit()
    return _flash_redirect(f"/questions/{set_id}", ok="Submitted for review.")


@router.post("/{set_id}/approve")
def approve_view(
    request: Request,
    set_id: str,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    qs = session.get(QuestionSet, set_id)
    if qs is None:
        raise HTTPException(status_code=404, detail="Question set not found.")
    _ensure_reviewer_or_admin(user, qs)
    try:
        approve(session, set_id=set_id, reviewer_id=user.id, actor_id=user.id)
    except WorkflowError as exc:
        session.rollback()
        return _flash_redirect(f"/questions/{set_id}", error=str(exc))
    session.commit()
    return _flash_redirect(f"/questions/{set_id}", ok="Approved.")


@router.post("/{set_id}/lock")
def lock_view(
    request: Request,
    set_id: str,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    qs = session.get(QuestionSet, set_id)
    if qs is None:
        raise HTTPException(status_code=404, detail="Question set not found.")
    _ensure_reviewer_or_admin(user, qs)
    try:
        lock(session, set_id=set_id, actor_id=user.id)
    except WorkflowError as exc:
        session.rollback()
        return _flash_redirect(f"/questions/{set_id}", error=str(exc))
    session.commit()
    return _flash_redirect(
        f"/questions/{set_id}", ok="Locked. Ready to run against models."
    )


@router.post("/{set_id}/revert")
def revert_view(
    request: Request,
    set_id: str,
    reason: str = Form(""),
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    qs = session.get(QuestionSet, set_id)
    if qs is None:
        raise HTTPException(status_code=404, detail="Question set not found.")
    if not (_is_admin(user) or _is_reviewer_of(user, qs) or _is_author_of(user, qs)):
        raise HTTPException(status_code=403, detail="Not allowed.")
    try:
        revert_to_draft(
            session, set_id=set_id, reason=reason.strip(), actor_id=user.id
        )
    except WorkflowError as exc:
        session.rollback()
        return _flash_redirect(f"/questions/{set_id}", error=str(exc))
    session.commit()
    return _flash_redirect(f"/questions/{set_id}", ok="Reverted to draft.")
