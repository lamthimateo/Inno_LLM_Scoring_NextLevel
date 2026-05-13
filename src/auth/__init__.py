"""Authentication + authorization.

Modules:

- ``passwords``     — bcrypt hashing helpers
- ``service``       — register / login / change_password / reset flows
- ``dependencies``  — FastAPI deps: get_current_user, require_role, require_login
- ``router``        — HTTP routes for login / logout / signup / forgot / reset / change

Sessions are signed cookies via ``starlette.middleware.sessions.SessionMiddleware``;
the secret is read from ``SESSION_SECRET``. The session stores only
``user_id`` (everything else is fetched from the DB on each request).
"""
