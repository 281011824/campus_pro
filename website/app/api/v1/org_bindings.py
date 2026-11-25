# -*- coding: utf-8 -*-
"""全校账号 → 职务与班级映射的查看、生成、修正与导出。"""

from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.api.v1.files import _can_manage_teachers, _ok, _unauthorized, _user
from tasks.domain.identity import bindings
from tasks.shared import db

router = APIRouter()


@router.get("/org/bindings")
async def list_bindings(request: Request):
    if not _user(request):
        return _unauthorized()
    items = bindings.list_rows(request.query_params.get("portal", ""),
                               request.query_params.get("q", ""),
                               int(request.query_params.get("limit") or 500))
    return _ok({"stats": bindings.stats(), "items": items})


@router.post("/org/bindings/generate")
async def generate_bindings(request: Request):
    user = _user(request)
    if not user:
        return _unauthorized()
    if not _can_manage_teachers(user):
        return JSONResponse({"code": 403, "error": "仅校领导、中层干部可生成账号映射"},
                            status_code=403)
    result = bindings.generate()
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "org.bindings", "ok", "generate",
             "账号 %d，映射 %d 条" % (result["accounts"], result["bindings"]))
    return _ok(result)


@router.post("/org/bindings/update")
async def update_binding(request: Request):
    user = _user(request)
    if not user:
        return _unauthorized()
    if not _can_manage_teachers(user):
        return JSONResponse({"code": 403, "error": "仅校领导、中层干部可修正账号映射"},
                            status_code=403)
    body = await request.json()
    try:
        res = bindings.update(str(body.get("userid") or ""),
                              str(body.get("post_name") or ""),
                              body.get("class_ids"),
                              str(body.get("level") or ""),
                              str(body.get("portal") or ""))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "org.bindings", "ok", "update", str(body.get("userid")))
    return _ok(res)


@router.get("/org/bindings.csv")
async def export_bindings(request: Request):
    if not _user(request):
        return _unauthorized()
    content = bindings.export_csv()
    name = "账号职务班级映射.csv"
    return Response(content, media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": "attachment; filename*=UTF-8''%s" % quote(name)})
