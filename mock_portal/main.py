import random
import string
import uuid
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Mock Government Portal")
templates = Jinja2Templates(directory="templates")

# Mock session store
sessions = {}

def get_session(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    return sessions[session_id]

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def do_login(username: str = Form(...), password: str = Form(...)):
    if username == "testuser" and password == "testpass":
        session_id = str(uuid.uuid4())
        sessions[session_id] = {"username": username, "status": "logged_in"}
        response = RedirectResponse(url="/apply", status_code=status.HTTP_302_FOUND)
        response.set_cookie(key="session_id", value=session_id)
        return response
    return RedirectResponse(url="/login?error=1", status_code=status.HTTP_302_FOUND)

@app.get("/apply", response_class=HTMLResponse)
async def apply_page(request: Request, session: dict = Depends(get_session)):
    return templates.TemplateResponse("apply.html", {"request": request})

@app.post("/apply")
async def post_apply(
    request: Request,
    full_name: str = Form(...),
    dob: str = Form(...),
    aadhaar_number: str = Form(...),
    session: dict = Depends(get_session)
):
    session["application_data"] = {
        "full_name": full_name,
        "dob": dob,
        "aadhaar_number": aadhaar_number
    }
    return RedirectResponse(url="/apply/uploads", status_code=status.HTTP_302_FOUND)

@app.get("/apply/uploads", response_class=HTMLResponse)
async def uploads_page(request: Request, session: dict = Depends(get_session)):
    return templates.TemplateResponse("uploads.html", {"request": request})

@app.post("/apply/uploads")
async def post_uploads(request: Request, session: dict = Depends(get_session)):
    # Simulating upload success
    return RedirectResponse(url="/apply/captcha", status_code=status.HTTP_302_FOUND)

@app.get("/apply/captcha", response_class=HTMLResponse)
async def captcha_page(request: Request, session: dict = Depends(get_session)):
    return templates.TemplateResponse("captcha.html", {"request": request})

@app.post("/apply/captcha")
async def post_captcha(request: Request, captcha_answer: str = Form(...), session: dict = Depends(get_session)):
    if captcha_answer == "4":  # simple math captcha 2+2
        return RedirectResponse(url="/apply/confirm", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/apply/captcha?error=1", status_code=status.HTTP_302_FOUND)

@app.get("/apply/confirm", response_class=HTMLResponse)
async def confirm_page(request: Request, session: dict = Depends(get_session)):
    return templates.TemplateResponse("confirm.html", {"request": request})

@app.post("/apply/confirm")
async def post_confirm(request: Request, session: dict = Depends(get_session)):
    return RedirectResponse(url="/apply/success", status_code=status.HTTP_302_FOUND)

@app.get("/apply/success", response_class=HTMLResponse)
async def success_page(request: Request, session: dict = Depends(get_session)):
    ref_num = f"MOCK-{uuid.uuid4().hex[:8].upper()}"
    return templates.TemplateResponse("success.html", {"request": request, "reference_number": ref_num})
