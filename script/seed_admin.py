"""
创建/重置后台管理员账号(幂等)。

默认从 .env.{APP_ENV} 读取:
    ADMIN_INIT_USERNAME=admin
    ADMIN_INIT_PASSWORD=admin123456
    ADMIN_INIT_DISPLAY_NAME=系统管理员

运行(在 agent-service 目录):
    .venv/Scripts/python script/seed_admin.py
    .venv/Scripts/python script/seed_admin.py --reset-password

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


async def main(reset_password: bool) -> None:
    username = settings.admin.init_username
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
                    display_name=settings.admin.init_display_name,
                    status="active",
                ))
                print(f"[新增] 管理员 {username} 创建成功")
            elif reset_password:
                existing.password_hash = hash_password(password)
                existing.status = "active"
                print(f"[重置] 管理员 {username} 密码已重置")
            else:
                print(f"[跳过] 管理员 {username} 已存在（如需重置密码请加 --reset-password）")

    print("管理员初始化完成 ✅")
    await close_database()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset-password", action="store_true", help="重置已存在管理员的密码")
    args = parser.parse_args()
    asyncio.run(main(args.reset_password))
