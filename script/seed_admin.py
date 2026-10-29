"""
创建/重置后台员工账号(幂等)。

默认从 .env.{APP_ENV} 读取:
    ADMIN_INIT_USERNAME=admin
    ADMIN_INIT_PASSWORD=admin123456
    ADMIN_INIT_DISPLAY_NAME=系统管理员

运行(在 agent-service 目录):
    .venv/Scripts/python script/seed_admin.py                       # 默认管理员
    .venv/Scripts/python script/seed_admin.py --reset-password      # 重置密码并刷新岗位
    .venv/Scripts/python script/seed_admin.py --username cs01 --role cs --display-name 客服小王
    .venv/Scripts/python script/seed_admin.py --username kb01 --role kb --display-name 知识运营小李

岗位角色: admin(管理员, 全部权限) / cs(客服) / kb(知识运营)
注意: 脚本不会打印明文密码。
"""
import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from app.core.config import settings
from app.infra.database import AsyncSessionFactory, close_database
from app.modules.admin.models import AdminUser
from app.modules.auth.security import hash_password

VALID_ROLES = ("admin", "cs", "kb")


async def main(reset_password: bool, username: str, role: str, display_name: str) -> None:
    password = settings.admin.init_password

    async with AsyncSessionFactory() as session:
        async with session.begin():
            existing = await session.scalar(
                select(AdminUser).where(AdminUser.username == username)
            )
            if existing is None:
                session.add(AdminUser(
                    username=username,
                    password_hash=hash_password(password),
                    display_name=display_name,
                    status="active",
                    role=role,
                ))
                print(f"[新增] 员工 {username} 创建成功（岗位: {role}）")
            elif reset_password:
                existing.password_hash = hash_password(password)
                existing.status = "active"
                existing.role = role
                print(f"[重置] 员工 {username} 密码已重置，岗位已刷新为 {role}")
            else:
                print(f"[跳过] 员工 {username} 已存在（岗位: {existing.role}）")
                print("       如需重置密码/刷新岗位请加 --reset-password")

    print("员工账号初始化完成 ✅")
    await close_database()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset-password", action="store_true", help="重置已存在账号的密码并刷新岗位")
    parser.add_argument("--username", default=settings.admin.init_username, help="员工用户名")
    parser.add_argument("--role", default=settings.admin.init_role, choices=VALID_ROLES, help="岗位角色")
    parser.add_argument("--display-name", default=None, help="显示名(默认按岗位生成)")
    args = parser.parse_args()
    display_name = args.display_name or (
        settings.admin.init_display_name if args.role == "admin" else f"员工-{args.username}"
    )
    asyncio.run(main(args.reset_password, args.username, args.role, display_name))
