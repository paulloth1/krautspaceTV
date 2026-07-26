import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db
from .rotation import STATE, rotation_loop
from .slides import REGISTRY

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    task = asyncio.create_task(rotation_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/")
async def display(request: Request):
    return templates.TemplateResponse(request, "display.html", {})


@app.get("/api/slide/current")
async def slide_current():
    return await STATE.snapshot()


@app.get("/admin")
async def admin(request: Request):
    slides = await db.list_slides()
    interval = await db.get_setting("rotation_interval_seconds", "60")
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "slides": slides,
            "registry": REGISTRY,
            "rotation_interval": interval,
        },
    )


@app.get("/admin/slides/new")
async def new_slide_form(request: Request, type: str):
    slide_type = REGISTRY.get(type)
    if slide_type is None:
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(
        request,
        "slide_form.html",
        {"slide_type": slide_type, "slide": None, "action": "/admin/slides"},
    )


@app.post("/admin/slides")
async def create_slide(request: Request):
    form = await request.form()
    slide_type_key = form.get("_type")
    name = form.get("_name") or slide_type_key
    slide_type = REGISTRY.get(slide_type_key)
    if slide_type is None:
        return RedirectResponse("/admin", status_code=303)
    config = {f.name: form.get(f.name, "") for f in slide_type.config_fields}
    await db.add_slide(slide_type_key, name, config)
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/slides/{slide_id}/edit")
async def edit_slide_form(request: Request, slide_id: int):
    slide = await db.get_slide(slide_id)
    if slide is None:
        return RedirectResponse("/admin", status_code=303)
    slide_type = REGISTRY.get(slide["type"])
    return templates.TemplateResponse(
        request,
        "slide_form.html",
        {"slide_type": slide_type, "slide": slide, "action": f"/admin/slides/{slide_id}/update"},
    )


@app.post("/admin/slides/{slide_id}/update")
async def update_slide(request: Request, slide_id: int):
    form = await request.form()
    slide = await db.get_slide(slide_id)
    if slide is None:
        return RedirectResponse("/admin", status_code=303)
    slide_type = REGISTRY.get(slide["type"])
    name = form.get("_name") or slide["name"]
    config = {f.name: form.get(f.name, "") for f in slide_type.config_fields}
    await db.update_slide(slide_id, name, config)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/slides/{slide_id}/delete")
async def delete_slide(slide_id: int):
    await db.delete_slide(slide_id)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/slides/{slide_id}/toggle")
async def toggle_slide(slide_id: int):
    await db.toggle_slide(slide_id)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/slides/{slide_id}/move")
async def move_slide(slide_id: int, direction: str = Form(...)):
    await db.move_slide(slide_id, direction)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/settings")
async def update_settings(rotation_interval_seconds: str = Form(...)):
    await db.set_setting("rotation_interval_seconds", rotation_interval_seconds)
    return RedirectResponse("/admin", status_code=303)
