from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from maibot_sdk import Command, CONFIG_RELOAD_SCOPE_SELF, MaiBotPlugin

from .config import UnoPluginConfig
from .uno import CardColor, GamePhase, Room, RoomManager
from .uno.engine import GameEngine
from .uno.player import Player
from .uno.web_server import UnoWebServer


_UNO_ICON = "🃏"


class UnoPlugin(MaiBotPlugin):
    config_model = UnoPluginConfig

    def __init__(self) -> None:
        super().__init__()
        self._room_manager = RoomManager()
        self._bot_tasks: Dict[str, asyncio.Task[None]] = {}
        self._cleanup_task: Optional[asyncio.Task[None]] = None
        self._web_server: Optional[UnoWebServer] = None

    async def on_load(self) -> None:
        if not self.config.plugin.enabled:
            self.ctx.logger.info("UNO 插件已禁用")
            return
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        if self.config.web.enabled:
            self._web_server = UnoWebServer(
                self._room_manager,
                host=self.config.web.host,
                port=self.config.web.port,
                commentary_templates=self.config.commentary.templates,
                on_game_end=self._on_web_game_end,
                bot_uno_forget_probability=self.config.game.bot_uno_forget_probability,
            )
            try:
                await self._web_server.start()
            except OSError as e:
                self.ctx.logger.warning("Web UI 端口 %s 被占用，跳过启动: %s", self.config.web.port, e)
                self._web_server = None
        self.ctx.logger.info("UNO 插件已加载")

    async def on_unload(self) -> None:
        if self._web_server is not None:
            await self._web_server.stop()
            self._web_server = None
        for task in list(self._bot_tasks.values()):
            task.cancel()
        if self._bot_tasks:
            await asyncio.gather(*self._bot_tasks.values(), return_exceptions=True)
        self._bot_tasks.clear()
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        self.ctx.logger.info("UNO 插件已卸载")

    async def on_config_update(self, scope: str, config_data: Dict[str, Any], version: str) -> None:
        if scope == CONFIG_RELOAD_SCOPE_SELF:
            self.ctx.logger.info("UNO 配置已热重载: %s", version)

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(60)
                now = time.time()
                timeout = self.config.game.auto_cleanup_minutes * 60
                for room in list(self._room_manager.list_rooms()):
                    r = self._room_manager.get_room(room["room_id"])
                    if r is None:
                        continue
                    if r.engine.phase == GamePhase.ENDED and r.created_at and now - r.created_at > timeout:
                        self._room_manager.cleanup_room(room["room_id"])
                        self.ctx.logger.info("清理过期房间: %s", room["room_id"])
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    def _extract_ids(self, kwargs: Dict[str, Any]) -> Tuple[str, str, str, str]:
        stream_id = kwargs.get("stream_id", "")
        user_id = kwargs.get("user_id", "")
        group_id = kwargs.get("group_id", "")

        base_info = kwargs.get("message_base_info", {}) or {}
        if not user_id:
            user_info = base_info.get("user_info", {}) or {}
            user_id = str(user_info.get("user_id", ""))
        if not group_id:
            group_info = base_info.get("group_info", {}) or {}
            group_id = str(group_info.get("group_id", ""))

        sender_name = str(base_info.get("sender_name", "") or "")
        if not sender_name:
            user_info = base_info.get("user_info", {}) or {}
            sender_name = str(
                user_info.get("user_cardname", "")
                or user_info.get("user_nickname", "")
                or ""
            )
        if not sender_name:
            sender_name = user_id

        return stream_id, user_id, group_id, sender_name

    def _can_manage_game(self, room: Room, user_id: str) -> bool:
        if not room:
            return False
        return room.host_id == user_id

    async def _send(self, text: str, group_id: str) -> None:
        try:
            result = await self.ctx.call_capability(
                "chat.get_stream_by_group_id", group_id=group_id
            )
            if not result or not result.get("success"):
                self.ctx.logger.error("发送消息失败: 无法获取群聊 stream, group_id=%s", group_id)
                return
            stream = result.get("stream")
            if not stream:
                self.ctx.logger.error("发送消息失败: 群聊 stream 为空, group_id=%s", group_id)
                return
            stream_id = stream.get("session_id", "")
            if not stream_id:
                self.ctx.logger.error("发送消息失败: stream 无 session_id, group_id=%s", group_id)
                return
            await self.ctx.send.text(text, stream_id=stream_id)
        except Exception as e:
            self.ctx.logger.error("发送消息失败: %s", e)

    async def _send_private(self, text: str, user_id: str) -> None:
        try:
            result = await self.ctx.call_capability(
                "chat.get_stream_by_user_id", user_id=user_id
            )
            if not result or not result.get("success"):
                self.ctx.logger.error("发送私聊失败: 无法获取用户 stream, user_id=%s", user_id)
                return
            stream = result.get("stream")
            if not stream:
                self.ctx.logger.error("发送私聊失败: 用户 stream 为空, user_id=%s", user_id)
                return
            stream_id = stream.get("session_id", "")
            if not stream_id:
                self.ctx.logger.error("发送私聊失败: stream 无 session_id, user_id=%s", user_id)
                return
            await self.ctx.send.text(text, stream_id=stream_id)
        except Exception as e:
            self.ctx.logger.error("发送私聊失败: %s", e)

    def _pick_commentary_template(self) -> str:
        templates = self.config.commentary.templates
        if not templates:
            return ""
        return random.choice(templates)

    @staticmethod
    def _resolve_summary_group(raw: str) -> str:
        parts = raw.split(":", 2)
        if len(parts) == 3 and parts[2] == "group":
            return parts[1]
        return ""

    async def _send_game_summary(self, room: Room, current_group: str) -> None:
        winner = room.engine.winner
        if not winner:
            return

        game_scores = room.engine.calculate_game_scores()
        score_summary = ""
        if game_scores:
            parts = []
            for p in room.engine.players:
                s = game_scores.get(p.player_id, 0)
                total = room.scores.get(p.player_id, 0)
                parts.append(f"{p.name}:+{s}(累计{total})")
            score_summary = " | ".join(parts)

        if self.config.game_summary.enabled and self.config.game_summary.stream_id:
            target = self._resolve_summary_group(self.config.game_summary.stream_id)
            if target:
                lines = [f"{_UNO_ICON} 对局结束！胜者：{winner.name}"]
                for p in room.engine.players:
                    lines.append(f"  {p.name}: {p.total_score()} 分（剩余 {p.hand_count()} 张）")
                if score_summary:
                    lines.append(f"  累计: {score_summary}")
                await self._send("\n".join(lines), target)
                return
        if current_group:
            try:
                players_str = "、".join(p.name for p in room.engine.players)
                prompt = [
                    {"role": "system", "content": "你是UNO游戏的解说员，请用简短有趣的语言总结这局UNO游戏（50字以内）。"},
                    {"role": "user", "content": f"玩家：{players_str}，胜者：{winner.name}。"},
                ]
                model_task = self.config.game_summary.model_task or ""
                result = await self.ctx.llm.generate(prompt, model=model_task, temperature=0.7, max_tokens=80)
                if isinstance(result, dict):
                    text = result.get("response", "") or result.get("content", "")
                    if text and len(text.strip()) > 2:
                        await self._send(f"{_UNO_ICON} 对局总结：{text.strip()}", current_group)
            except Exception as e:
                self.ctx.logger.debug("对局总结生成失败: %s", e)

    async def _on_web_game_end(self, room: Room) -> None:
        await self._send_game_summary(room, room.group_id)

    async def _run_bot_turns(self, room_id: str, group_id: str) -> None:
        await asyncio.sleep(0.3)
        try:
            room = self._room_manager.get_room(room_id)
            if room is None:
                return

            while room.engine.phase == GamePhase.PLAYING:
                player = room.engine.current_player
                if player is None or not player.is_bot:
                    break

                await asyncio.sleep(self.config.game.bot_turn_delay_seconds)

                room = self._room_manager.get_room(room_id)
                if room is None or room.engine.phase != GamePhase.PLAYING:
                    break

                result = room.engine.process_ai_turn(self.config.game.bot_uno_forget_probability)
                if result:
                    await self._send(f"{_UNO_ICON} {result}", group_id)
                    commentary = self._pick_commentary_template()
                    if commentary:
                        await asyncio.sleep(0.5)
                        await self._send(f"{player.name}：{commentary}", group_id)

                    if room.engine.phase == GamePhase.ENDED:
                        winner = room.engine.winner
                        if winner:
                            game_scores = room.accumulate_scores()
                            score_str = ""
                            if game_scores:
                                parts = []
                                for p in room.engine.players:
                                    s = game_scores.get(p.player_id, 0)
                                    parts.append(f"{p.name}:+{s}")
                                score_str = " | " + " ".join(parts)
                            win_msg = f"{_UNO_ICON} 游戏结束！{winner.name} 获胜！{score_str}"
                            await self._send(win_msg, group_id)
                            win_commentary = self._pick_commentary_template()
                            if win_commentary:
                                await asyncio.sleep(0.5)
                                await self._send(f"{winner.name}：{win_commentary}", group_id)
                            await self._send_game_summary(room, group_id)
                        break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.ctx.logger.error("Bot 回合异常: %s", e)

    def _get_player_name(self, room: Room, user_id: str) -> Optional[str]:
        for p in room.engine.players:
            if p.player_id == user_id:
                return p.name
        return None

    async def _handle_create(self, args: List[str], user_id: str, group_id: str, sender_name: str) -> str:
        if self._room_manager.get_room_by_player(user_id) is not None:
            return f"{_UNO_ICON} 你已经在房间中了，先 /uno 退出"

        room = self._room_manager.create_room(user_id, sender_name, group_id)
        room.created_at = time.time()
        return (
            f"{_UNO_ICON} UNO 房间已创建！\n"
            f"房间号：{room.room_id}\n"
            f"其他玩家输入 /uno 加入 {room.room_id} 参与游戏\n"
            f"房主输入 /uno 开始 开始游戏\n"
            f"输入 /uno 加机器人 添加 Bot 玩家"
        )

    async def _handle_join(self, args: List[str], stream_id: str, user_id: str, sender_name: str) -> str:
        if not args:
            rooms = self._room_manager.list_rooms()
            rooms_info = "\n".join(
                f"  {r['room_id']} - {r['player_count']}人 - {'等待中' if r['phase'] == 'waiting' else '游戏中'}"
                for r in rooms
            ) if rooms else "暂无房间"
            return f"{_UNO_ICON} 用法：/uno 加入 <房间号>\n当前房间：\n{rooms_info}"

        room_id = args[0].strip().upper()
        if self._room_manager.get_room_by_player(user_id) is not None:
            return f"{_UNO_ICON} 你已经在房间中了，先 /uno 退出"

        result = self._room_manager.join_room(room_id, user_id, sender_name)
        return f"{_UNO_ICON} {result}"

    async def _handle_start(self, stream_id: str, user_id: str, group_id: str) -> str:
        room = self._room_manager.get_room_by_player(user_id)
        if room is None:
            return f"{_UNO_ICON} 你没有加入任何房间"

        if room.host_id != user_id:
            return f"{_UNO_ICON} 只有房主可以开始游戏"

        if room.engine.phase != GamePhase.WAITING:
            return f"{_UNO_ICON} 游戏已开始"

        player_count = len(room.engine.players)
        if player_count < 2:
            return f"{_UNO_ICON} 至少需要2名玩家"

        result = room.engine.start_game()
        if room.engine.phase != GamePhase.PLAYING:
            return f"{_UNO_ICON} {result}"

        players_info = "\n".join(
            f"  {i + 1}. {p.name}" for i, p in enumerate(room.engine.players)
        )
        top = room.engine.top_card
        top_str = f"{top.color.emoji}{top.color.display} {top.value.display}" if top else "?"

        msg = (
            f"{_UNO_ICON} {result}\n"
            f"玩家列表：\n{players_info}\n"
            f"当前牌面：{top_str}\n"
            f"当前回合：{room.engine.current_player.name}\n"
        )

        for p in room.engine.players:
            if not p.is_bot:
                hand = p.hand_summary()
                try:
                    await self._send_private(
                        f"{_UNO_ICON} 你的手牌：\n{hand}\n"
                        f"出牌请用：/uno 出 <序号>\n"
                        f"摸牌请用：/uno 摸牌",
                        p.player_id,
                    )
                except Exception:
                    pass

        if room.engine.current_player and room.engine.current_player.is_bot:
            task = asyncio.create_task(
                self._run_bot_turns(room.room_id, group_id)
            )
            self._bot_tasks[room.room_id] = task

        return msg

    async def _handle_hand(self, user_id: str) -> str:
        room = self._room_manager.get_room_by_player(user_id)
        if room is None:
            return f"{_UNO_ICON} 你没有加入任何房间"

        if room.engine.phase != GamePhase.PLAYING:
            return f"{_UNO_ICON} 游戏未开始"

        for p in room.engine.players:
            if p.player_id == user_id:
                hand = p.hand_summary()
                try:
                    await self._send_private(
                        f"{_UNO_ICON} 你的手牌（{p.hand_count()}张）：\n{hand}",
                        user_id,
                    )
                except Exception:
                    pass
                return f"{_UNO_ICON} 手牌已通过私聊发送"

        return f"{_UNO_ICON} 你不是当前游戏的玩家"

    async def _handle_play(self, args: List[str], group_id: str, user_id: str) -> str:
        if not args:
            return f"{_UNO_ICON} 用法：/uno 出 <序号> [颜色]\n例：/uno 出 3 或 /uno 出 5 红"

        room = self._room_manager.get_room_by_player(user_id)
        if room is None:
            return f"{_UNO_ICON} 你没有加入任何房间"

        try:
            card_index = int(args[0]) - 1
        except ValueError:
            return f"{_UNO_ICON} 牌号必须是数字"

        chosen_color = args[1] if len(args) > 1 else None

        result = room.engine.play_card(user_id, card_index, chosen_color)
        if room.engine.phase == GamePhase.ENDED:
            winner = room.engine.winner
            self._bot_tasks.pop(room.room_id, None)
            if winner:
                game_scores = room.accumulate_scores()
                score_str = ""
                if game_scores:
                    parts = []
                    for p in room.engine.players:
                        s = game_scores.get(p.player_id, 0)
                        parts.append(f"{p.name}:+{s}")
                    score_str = " | " + " ".join(parts)
                await self._send(
                    f"{_UNO_ICON} {result}\n"
                    f"🏆 {winner.name} 获胜！{score_str}",
                    group_id,
                )
                await self._send_game_summary(room, group_id)
            return ""

        if "请指定颜色" in result:
            return f"{_UNO_ICON} {result}"

        if "不是你的回合" in result or "无效" in result:
            return f"{_UNO_ICON} {result}"

        room = self._room_manager.get_room_by_player(user_id)
        if room is None:
            return ""

        top = room.engine.top_card
        top_str = f"{top.color.emoji}{top.color.display} {top.value.display}" if top else "?"
        info = room.engine.next_turn_info()

        msg = f"{_UNO_ICON} {result}\n牌面：{top_str}\n{info}"

        if room.engine.current_player and room.engine.current_player.is_bot:
            task = self._bot_tasks.get(room.room_id)
            if task is None or task.done():
                new_task = asyncio.create_task(
                    self._run_bot_turns(room.room_id, group_id)
                )
                self._bot_tasks[room.room_id] = new_task

        return msg

    async def _handle_draw(self, group_id: str, user_id: str) -> str:
        room = self._room_manager.get_room_by_player(user_id)
        if room is None:
            return f"{_UNO_ICON} 你没有加入任何房间"

        result = room.engine.draw_card(user_id)

        room = self._room_manager.get_room_by_player(user_id)
        if room is None:
            return ""

        top = room.engine.top_card
        top_str = f"{top.color.emoji}{top.color.display} {top.value.display}" if top else "?"
        info = room.engine.next_turn_info()

        msg = f"{_UNO_ICON} {result}\n牌面：{top_str}\n{info}"

        if room.engine.current_player and room.engine.current_player.is_bot:
            task = self._bot_tasks.get(room.room_id)
            if task is None or task.done():
                new_task = asyncio.create_task(
                    self._run_bot_turns(room.room_id, group_id)
                )
                self._bot_tasks[room.room_id] = new_task

        return msg

    async def _handle_color(self, args: List[str], user_id: str) -> str:
        if not args:
            return f"{_UNO_ICON} 用法：/uno 颜色 <红/黄/蓝/绿>"

        room = self._room_manager.get_room_by_player(user_id)
        if room is None:
            return f"{_UNO_ICON} 你没有加入任何房间"

        color = CardColor(args[0].strip().lower()) if args[0].strip().lower() in ("red", "yellow", "blue", "green", "wild") else None
        if color is None:
            return f"{_UNO_ICON} 无效颜色，可选：红/黄/蓝/绿"

        return f"{_UNO_ICON} 颜色已设置为 {color.emoji}{color.display}"

    async def _handle_uno(self, stream_id: str, user_id: str) -> str:
        room = self._room_manager.get_room_by_player(user_id)
        if room is None:
            return f"{_UNO_ICON} 你没有加入任何房间"

        result = room.engine.say_uno(user_id)
        hand = room.engine._find_player(user_id)
        if hand and hand.said_uno:
            return f"{_UNO_ICON} {result}（下一张出牌不会被罚牌）"
        return f"{_UNO_ICON} {result}"

    async def _handle_catch(self, args: List[str], user_id: str) -> str:
        if not args:
            return f"{_UNO_ICON} 用法：/uno 抓UNO <对方QQ>"

        room = self._room_manager.get_room_by_player(user_id)
        if room is None:
            return f"{_UNO_ICON} 你没有加入任何房间"

        target_id = args[0].strip()
        result = room.engine.catch_uno(user_id, target_id)
        return f"{_UNO_ICON} {result}"

    async def _handle_status(self, stream_id: str, user_id: str) -> str:
        room = self._room_manager.get_room_by_player(user_id)
        if room is None:
            rooms = self._room_manager.list_rooms()
            if not rooms:
                return f"{_UNO_ICON} 当前没有任何活跃房间"
            lines = [f"{_UNO_ICON} 当前活跃房间："]
            for r in rooms:
                lines.append(
                    f"  {r['room_id']} - {r['player_count']}人 - {r['phase']}"
                )
            return "\n".join(lines)

        status = room.engine.get_status()
        top = room.engine.top_card
        top_str = f"{top.color.emoji}{top.color.display} {top.value.display}" if top else "?"
        players_info = "\n".join(
            f"  {p['name']} ({p['hand_count']}张)"
            + (" 🤖" if p['is_bot'] else "")
            + (" 👑" if p['player_id'] == room.host_id else "")
            for p in status["players"]
        )

        return (
            f"{_UNO_ICON} UNO 房间 {room.room_id}\n"
            f"状态：{status['phase']}\n"
            f"玩家：\n{players_info}\n"
            f"当前回合：{status['current_turn']}\n"
            f"牌面：{top_str}\n"
            f"方向：{'↻' if status['direction'] == 1 else '↺'}\n"
            f"牌堆剩余：{status['remaining_cards']}张"
        )

    async def _handle_rooms(self, stream_id: str) -> str:
        rooms = self._room_manager.list_rooms()
        if not rooms:
            return f"{_UNO_ICON} 当前没有任何房间"

        lines = [f"{_UNO_ICON} 当前房间列表："]
        for r in rooms:
            phase_text = "等待中" if r['phase'] == "waiting" else "游戏中" if r['phase'] == "playing" else "已结束"
            lines.append(f"  {r['room_id']} - {r['player_count']}人 - {phase_text}")
        return "\n".join(lines)

    async def _handle_leave(self, stream_id: str, user_id: str) -> str:
        result = self._room_manager.leave_room(user_id)
        return f"{_UNO_ICON} {result}"

    async def _handle_add_bot(self, stream_id: str, user_id: str) -> str:
        room = self._room_manager.get_room_by_player(user_id)
        if room is None:
            return f"{_UNO_ICON} 你没有加入任何房间"

        if room.host_id != user_id:
            return f"{_UNO_ICON} 只有房主可以添加 Bot"

        if room.engine.phase != GamePhase.WAITING:
            return f"{_UNO_ICON} 游戏已开始"

        result = self._room_manager.add_bot(room.room_id)
        return f"{_UNO_ICON} {result}"

    async def _handle_test(self, group_id: str, user_id: str) -> str:
        await self._send(f"{_UNO_ICON} UNO 插件消息发送测试（群聊）", group_id)
        await self._send_private(f"{_UNO_ICON} UNO 插件消息发送测试（私聊）", user_id)
        return f"{_UNO_ICON} 测试消息已发送，请检查群聊和私聊是否收到"

    async def _handle_help(self) -> str:
        return (
            f"{_UNO_ICON} UNO 命令列表：\n"
            "  /uno 创建 - 创建新房间\n"
            "  /uno 加入 <房间号> - 加入房间\n"
            "  /uno 开始 - 开始游戏（房主）\n"
            "  /uno 手牌 - 查看手牌（私聊发送）\n"
            "  /uno 出 <序号> [颜色] - 出牌\n"
            "  /uno 摸牌 - 摸一张牌\n"
            "  /uno UNO - 喊 UNO\n"
            "  /uno 抓UNO <对方QQ> - 抓没喊UNO的人\n"
            "  /uno 状态 - 查看游戏状态\n"
            "  /uno 房间 - 查看房间列表\n"
            "  /uno 加机器人 - 添加 Bot 玩家\n"
            "  /uno 退出 - 退出房间\n"
            "  /uno 测试 - 测试消息发送是否正常\n"
            "  /uno 帮助 - 显示此帮助\n"
            "📌 出牌时未喊UNO将自动罚摸2张（Bot也有概率忘记喊）\n"
            "📌 累计计分模式：手牌分值详见规则"
        )

    @Command(
        "uno_game",
        description="UNO 小游戏命令集",
        pattern=r"^/uno\s*(?P<action>\S+)?(?:\s+(?P<args>.*))?\s*$",
        aliases=["/UNO"],
    )
    async def handle_uno_command(
        self,
        stream_id: str = "",
        platform: str = "",
        user_id: str = "",
        group_id: str = "",
        matched_groups: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Tuple[bool, Optional[str], bool]:
        _ = platform
        actual_stream, actual_user, actual_group, sender_name = self._extract_ids(kwargs)

        action_raw = (matched_groups or {}).get("action", "")
        args_raw = (matched_groups or {}).get("args", "")
        action = str(action_raw).strip().lower() if action_raw else ""
        args = str(args_raw).strip().split() if args_raw else []

        if not action:
            result = await self._handle_help()
            await self._send(result, actual_group)
            return True, None, True

        action_map: Dict[str, Any] = {
            "创建": self._handle_create(args, actual_user, actual_group, sender_name),
            "加入": self._handle_join(args, actual_stream, actual_user, sender_name),
            "开始": self._handle_start(actual_stream, actual_user, actual_group),
            "手牌": self._handle_hand(actual_user),
            "出": self._handle_play(args, actual_group, actual_user),
            "摸牌": self._handle_draw(actual_group, actual_user),
            "颜色": self._handle_color(args, actual_user),
            "uno": self._handle_uno(actual_stream, actual_user),
            "抓uno": self._handle_catch(args, actual_user),
            "状态": self._handle_status(actual_stream, actual_user),
            "房间": self._handle_rooms(actual_stream),
            "退出": self._handle_leave(actual_stream, actual_user),
            "加机器人": self._handle_add_bot(actual_stream, actual_user),
            "测试": self._handle_test(actual_group, actual_user),
            "帮助": self._handle_help(),
        }

        handler = action_map.get(action)
        if handler is None:
            result = await self._handle_help()
        else:
            result = await handler if callable(handler) else handler

        if result:
            await self._send(result, actual_group)

        return True, None, True


def create_plugin() -> UnoPlugin:
    return UnoPlugin()
