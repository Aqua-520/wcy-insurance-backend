"""
一键初始化/重置用户账号(幂等)。

用途:
1. 数据库里 demo 账号当前是假的密码占位符, 无法登录, 本脚本把它重置为真实 bcrypt 密码;
2. 顺带准备几个可登录的测试账号, 方便验证"会话按用户隔离"。

注意: 当前阶段所有账号都是普通客户, 不区分角色(知识库内容权限是后续升级点)。

运行(在 agent-service 目录):
    .venv/Scripts/python script/seed_users.py
"""
import asyncio
import sys
from pathlib import Path

# 把项目根目录加入模块搜索路径
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from app.infra.database import AsyncSessionFactory, close_database
from app.modules.auth.models import User
from app.modules.auth.security import hash_password

# 预置账号: 用户名, 密码, 邮箱, 昵称
SEED_USERS = [
    ("user1", "123456", "demo@example.com", "演示用户"),
    ("user2", "123456", "demo2@example.com", "演示用户二号"),
    ("test1", "123456", "test@example.com", "测试账号"),
]


async def main() -> None:
    async with AsyncSessionFactory() as session:
        async with session.begin():
            for username, password, email, display_name in SEED_USERS:
                # 按邮箱匹配已有账号(邮箱与库内 id=1/2/3 一一对应),
                # 命中则原地更新用户名和密码, 主键 id 保持不变; 没有才新增
                existing = await session.scalar(select(User).where(User.email == email))
                if existing is None:
                    session.add(User(
                        username=username,
                        email=email,
                        password_hash=hash_password(password),
                        display_name=display_name,
                        status="active",
                    ))
                    print(f"[新增] {username} (email={email})")
                else:
                    existing.username = username
                    existing.email = email
                    existing.password_hash = hash_password(password)
                    existing.display_name = display_name
                    existing.status = "active"
                    print(f"[重置] id={existing.id} -> {username} (email={email})")
    print("用户初始化完成 ✅")
    await close_database()


if __name__ == "__main__":
    asyncio.run(main())
