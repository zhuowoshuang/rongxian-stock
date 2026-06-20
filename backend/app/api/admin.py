"""管理员 API"""
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text, inspect
from pydantic import BaseModel
from typing import Optional

from app.db.session import get_db
from app.models.user import User
from app.api.auth import get_current_admin

router = APIRouter(prefix="/api/admin", tags=["管理"])


class UserUpdateRequest(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/stats")
def get_stats(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """系统统计数据"""
    from app.models.stock import Stock
    from app.models.trade_signal import TradeSignal
    from app.models.report import Report
    from app.models.research_report import ResearchReport

    total_stocks = db.query(Stock).count()
    total_signals = db.query(TradeSignal).count()
    total_users = db.query(User).count()
    total_reports = db.query(Report).count()
    total_research = db.query(ResearchReport).count()

    # DB file size
    db_size = "N/A"
    # Try common locations
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    for candidate in ["stock_agent.db", "data/rongxian.db", "data/stock_agent.db"]:
        db_path = os.path.join(backend_dir, candidate)
        if os.path.exists(db_path):
            size_bytes = os.path.getsize(db_path)
            if size_bytes > 1024 * 1024:
                db_size = f"{size_bytes / 1024 / 1024:.1f} MB"
            else:
                db_size = f"{size_bytes / 1024:.1f} KB"
            break
    if db_size == "N/A":
        size_bytes = os.path.getsize(db_path)
        if size_bytes > 1024 * 1024:
            db_size = f"{size_bytes / 1024 / 1024:.1f} MB"
        else:
            db_size = f"{size_bytes / 1024:.1f} KB"

    return {
        "total_stocks": total_stocks,
        "total_signals": total_signals,
        "total_users": total_users,
        "total_reports": total_reports,
        "total_research_reports": total_research,
        "db_size": db_size,
    }


@router.get("/users")
def list_users(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """列出所有用户"""
    users = db.query(User).order_by(User.id).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": str(u.created_at) if u.created_at else None,
            "updated_at": str(u.updated_at) if u.updated_at else None,
        }
        for u in users
    ]


@router.put("/users/{user_id}")
def update_user(user_id: int, req: UserUpdateRequest, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """更新用户角色或状态"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if req.role is not None:
        if req.role not in ("admin", "analyst", "user", "guest"):
            raise HTTPException(status_code=400, detail="角色必须是 admin、analyst、user 或 guest")
        user.role = req.role
    if req.is_active is not None:
        user.is_active = req.is_active
    db.commit()
    return {"status": "ok", "message": "用户已更新"}


@router.delete("/users/{user_id}")
def disable_user(user_id: int, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """禁用用户（软删除）"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能禁用自己")
    user.is_active = False
    db.commit()
    return {"status": "ok", "message": "用户已禁用"}


@router.get("/tables")
def list_tables(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """列出所有数据库表及行数"""
    inspector = inspect(db.bind)
    tables = inspector.get_table_names()
    result = []
    for table in sorted(tables):
        try:
            count = db.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
        except Exception:
            count = 0
        result.append({"name": table, "row_count": count})
    return result


@router.get("/tables/{table_name}")
def get_table_data(table_name: str, page: int = 1, page_size: int = 50, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """查看指定表的数据（分页）"""
    inspector = inspect(db.bind)
    tables = inspector.get_table_names()
    if table_name not in tables:
        raise HTTPException(status_code=404, detail=f"表 {table_name} 不存在")

    # Get columns
    columns = [col["name"] for col in inspector.get_columns(table_name)]

    # Get total count
    total = db.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar()

    # Get paginated data
    offset = (page - 1) * page_size
    rows = db.execute(text(f'SELECT * FROM "{table_name}" LIMIT :limit OFFSET :offset'), {"limit": page_size, "offset": offset}).fetchall()

    # Convert rows to list of dicts
    data = []
    for row in rows:
        row_dict = {}
        for i, col in enumerate(columns):
            val = row[i]
            # Convert non-serializable types
            if val is None:
                row_dict[col] = None
            elif isinstance(val, (int, float, bool, str)):
                row_dict[col] = val
            else:
                row_dict[col] = str(val)
        data.append(row_dict)

    return {
        "columns": columns,
        "total": total,
        "page": page,
        "page_size": page_size,
        "data": data,
    }
