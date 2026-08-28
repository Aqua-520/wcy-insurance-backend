import asyncio

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient

# 加载环境变量
load_dotenv()

# 连接mcp服务器
mcp_client = MultiServerMCPClient(
    {
        # 模块名
        "wcy_tools":{
            "transport":"stdio",
            # 通过python启动,而不是npx和uvx
            "command":"python",
            # 文件名
            "args":["my_mcp_server.py"]
        }
    }
)

# 定义启动函数
# mcp的操作都是异步调用,必须使用await标注为异步函数
async def run_agent():
    # 获得工具列表
    my_tools = await mcp_client.get_tools()

    # 初始化agent智能体对象
    agent = create_agent(
        model=init_chat_model(
            model='deepseek-v4-flash',
            extra_body={"thinking": {"type": "disabled"}}
        ),
        # 给智能体挂载工具
        tools=my_tools
    )

    # 调用agent
    response = await agent.ainvoke({
        "messages": [HumanMessage("今天是几月几号")]
    })

    for m in response['messages']:
        m.pretty_print()

# 异步io调用
asyncio.run(run_agent())