from __future__ import annotations

from typing import List

from maibot_sdk import Field, PluginConfigBase


class PluginSection(PluginConfigBase):
    __ui_label__ = "插件设置"
    __ui_icon__ = "smart-toy"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用 UNO 插件")
    config_version: str = Field(default="1.0.0", description="配置版本")


class GameSection(PluginConfigBase):
    __ui_label__ = "游戏设置"
    __ui_icon__ = "casino"
    __ui_order__ = 1

    max_players: int = Field(default=6, description="每局最大玩家数")
    allow_public_rooms: bool = Field(default=True, description="允许公开查看房间列表")
    auto_cleanup_minutes: int = Field(default=30, description="空闲房间自动清理时间（分钟）")
    bot_turn_delay_seconds: float = Field(default=1.5, description="Bot 出牌延迟（秒）")
    bot_uno_forget_probability: float = Field(default=0.15, description="Bot 忘记喊 UNO 的概率（0~1）")
    target_score: int = Field(default=500, description="达到此总分获胜（累计计分模式）")


class WebSection(PluginConfigBase):
    __ui_label__ = "Web 可视化"
    __ui_icon__ = "public"
    __ui_order__ = 2

    enabled: bool = Field(default=True, description="是否启用 Web 可视化界面（浏览器打开 http://127.0.0.1:端口 游玩）")
    host: str = Field(default="127.0.0.1", description="监听地址（建议保持 127.0.0.1）")
    port: int = Field(default=15810, description="监听端口（同机游玩保持默认即可）")


class CommentarySection(PluginConfigBase):
    __ui_label__ = "Bot 评论"
    __ui_icon__ = "chat"
    __ui_order__ = 3

    templates: List[str] = Field(
        default=[
            "嘿嘿，这把稳了！",
            "看我的厉害！",
            "运气不错嘛~",
            "哼，这只是开始！",
            "接招吧！",
            "你们还差得远呢！",
            "哇，这张牌太棒了！",
            "哈哈，你们完蛋了！",
            "别高兴太早！",
            "看我逆转局势！",
        ],
        description="Bot 评论模板列表，每次行动时随机选择一条发送",
    )


class GameSummarySection(PluginConfigBase):
    __ui_label__ = "对局总结"
    __ui_icon__ = "summary"
    __ui_order__ = 4

    enabled: bool = Field(default=False, description="启用后将详细对局信息发送到指定聊天流；禁用则由模型生成总结发送到当前聊天")
    stream_id: str = Field(default="", description="目标聊天流 ID，格式 \"平台:目标ID:类型\"，如 \"qq:123456789:group\" 或 \"qq:987654321:private\"")
    model_task: str = Field(default="replyer", description="AI 总结使用的模型任务名（对应 model_config.toml 中的 model_task_config.* 字段）")


class UnoPluginConfig(PluginConfigBase):
    plugin: PluginSection = Field(default_factory=PluginSection)
    game: GameSection = Field(default_factory=GameSection)
    web: WebSection = Field(default_factory=WebSection)
    commentary: CommentarySection = Field(default_factory=CommentarySection)
    game_summary: GameSummarySection = Field(default_factory=GameSummarySection)
