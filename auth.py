import hashlib
import os

import streamlit as st
import streamlit.components.v1 as components

_COOKIE_NAME = "auth"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 50  # 50 years


def _token() -> str:
    return hashlib.sha256(os.environ.get("APP_PASSWORD", "").encode()).hexdigest()[:16]


def check_password() -> bool:
    token = _token()

    # On the rerun right after login, inject the cookie-setter script first so it
    # renders in the same pass as the main app. The browser runs the JS and writes
    # the cookie before any subsequent page load, so st.context.cookies picks it up.
    if st.session_state.get("set_cookie"):
        del st.session_state["set_cookie"]
        components.html(
            f'<script>document.cookie="{_COOKIE_NAME}={token};'
            f'max-age={_COOKIE_MAX_AGE};path=/;SameSite=Lax";</script>',
            height=0,
        )

    if st.session_state.get("authenticated"):
        return True

    # st.context.cookies reads directly from HTTP request headers — no timing issues
    if st.context.cookies.get(_COOKIE_NAME) == token:
        st.session_state.authenticated = True
        return True

    login_area = st.empty()
    with login_area.container():
        st.title("Email Intent Viewer")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            if password == os.environ.get("APP_PASSWORD", ""):
                st.session_state.authenticated = True
                st.session_state.set_cookie = True
                st.rerun()
            else:
                st.error("Incorrect password")
    return False
