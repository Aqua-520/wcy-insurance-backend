"""
人工接管模块。

边界(务必守住):
- **实时接管走会话**: chat_threads.mode + chat_messages, 客服在会话工作台接进聊天框;
- **工单只做账本/凭据**: 转人工时建一条 ticket_type='handoff' 的工单拿受理编号,
  状态由会话状态派生(pending/processing/closed), **正文不双写**;
- ticket_messages 只服务异步场景(客户离线补充说明、投诉详情)。
"""
