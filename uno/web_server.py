from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import secrets
import time
import traceback
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .card import Card, CardColor, CardValue
from .engine import GameEngine, GamePhase
from .room import Room, RoomManager

logger = logging.getLogger("plugin.uno.web")

HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "webui", "index.html")
BOT_DELAY = 0.8


def _new_player_id() -> str:
    return "web_" + secrets.token_hex(8)


def _make_response(status: int, body: Any, content_type: str = "application/json") -> bytes:
    if isinstance(body, (dict, list)):
        body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
    elif isinstance(body, str):
        body_bytes = body.encode("utf-8")
    else:
        body_bytes = body
    headers = (
        f"HTTP/1.1 {status} {'OK' if status == 200 else 'Not Found' if status == 404 else 'Bad Request'}\r\n"
        f"Content-Type: {content_type}; charset=utf-8\r\n"
        f"Content-Length: {len(body_bytes)}\r\n"
        f"Access-Control-Allow-Origin: *\r\n"
        f"Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
        f"Access-Control-Allow-Headers: Content-Type, Authorization\r\n"
        f"Cache-Control: no-cache\r\n"
        f"\r\n"
    ).encode("utf-8")
    return headers + body_bytes


def _parse_request(data: bytes) -> Optional[Dict[str, Any]]:
    try:
        text = data.decode("utf-8")
        lines = text.split("\r\n")
        if not lines:
            return None
        method, path, _ = lines[0].split(" ", 2)
        parsed = urlparse(path)
        query = parse_qs(parsed.query)
        q = {k: v[0] for k, v in query.items()}
        body = {}
        if method in ("POST", "PUT"):
            blank = text.find("\r\n\r\n")
            if blank != -1:
                raw = text[blank + 4:]
                if raw.strip():
                    body = json.loads(raw)
        return {"method": method, "path": parsed.path, "query": q, "body": body}
    except Exception:
        return None


def _player_from_room(room: Room, player_id: str) -> Tuple[Any, int]:
    for i, p in enumerate(room.engine.players):
        if p.player_id == player_id:
            return p, i
    return None, -1


class UnoWebServer:
    def __init__(
        self,
        room_manager: RoomManager,
        host: str = "127.0.0.1",
        port: int = 15810,
        commentary_templates: Optional[List[str]] = None,
        on_game_end: Optional[Callable[..., Coroutine[Any, Any, None]]] = None,
        bot_uno_forget_probability: float = 0.15,
        access_token: str = "",
    ) -> None:
        self._room_manager = room_manager
        self._host = host
        self._port = port
        self._server: Optional[asyncio.AbstractServer] = None
        self._commentary_templates = commentary_templates or []
        self._on_game_end = on_game_end
        self._bot_uno_forget_probability = bot_uno_forget_probability
        self._access_token = access_token

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_connection, self._host, self._port
        )
        logger.info("Web UI 已启动: http://%s:%s", self._host, self._port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("Web UI 已停止")

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            data = await asyncio.wait_for(reader.read(65536), timeout=30)
            if not data:
                return
            req = _parse_request(data)
            if req is None:
                writer.write(_make_response(400, {"error": "bad request"}))
                await writer.drain()
                return

            method = req["method"]
            path = req["path"]
            query = req["query"]
            body = req["body"]

            if method == "OPTIONS":
                writer.write(_make_response(200, "ok"))
                await writer.drain()
                return

            if path == "/" or path == "/index.html":
                await self._serve_html(writer)
            elif path.startswith("/api/"):
                if self._access_token and query.get("token") != self._access_token:
                    writer.write(_make_response(403, {"error": "forbidden: invalid or missing token"}))
                    await writer.drain()
                    return
                await self._handle_api(method, path, query, body, writer)
            else:
                writer.write(_make_response(404, {"error": "not found"}))
                await writer.drain()
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.error("HTTP handler error: %s", e)
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _serve_html(self, writer: asyncio.StreamWriter) -> None:
        try:
            if os.path.exists(HTML_PATH):
                with open(HTML_PATH, "rb") as f:
                    content = f.read()
            else:
                content = b"<html><body><h1>WebUI not found</h1></body></html>"
            writer.write(_make_response(200, content, "text/html"))
        except Exception:
            writer.write(_make_response(500, {"error": "internal error"}))
        await writer.drain()

    async def _process_bot_turns(self, room: Room) -> List[str]:
        messages: List[str] = []
        while room.engine.phase == GamePhase.PLAYING:
            player = room.engine.current_player
            if player is None or not player.is_bot:
                break
            await asyncio.sleep(BOT_DELAY)
            if room.engine.phase != GamePhase.PLAYING:
                break
            result = room.engine.process_ai_turn(self._bot_uno_forget_probability)
            if result:
                messages.append(result)
                if self._commentary_templates:
                    commentary = random.choice(self._commentary_templates)
                    if commentary:
                        messages.append(f"{player.name}：{commentary}")
                if room.engine.phase == GamePhase.ENDED:
                    winner = room.engine.winner
                    if winner:
                        room.accumulate_scores()
                        scores_str = self._format_scores(room)
                        messages.append(f"{winner.name} 获胜！{scores_str}")
                        if self._on_game_end is not None:
                            await self._on_game_end(room)
                    break
        return messages

    async def _handle_api(
        self, method: str, path: str, query: Dict[str, str],
        body: Dict[str, Any], writer: asyncio.StreamWriter,
    ) -> None:
        result: Optional[Dict[str, Any]] = None
        try:
            if path == "/api/rooms" and method == "GET":
                rooms = self._room_manager.list_rooms()
                result = {"rooms": rooms}

            elif path == "/api/create-room" and method == "POST":
                name = body.get("name", "玩家")
                group_id = body.get("group_id", "")
                pid = _new_player_id()
                room = self._room_manager.create_room(pid, name, group_id)
                room.created_at = time.time()
                result = {"room_id": room.room_id, "player_id": pid}

            elif path == "/api/join-room" and method == "POST":
                room_id = body.get("room_id", "")
                name = body.get("name", "玩家")
                pid = _new_player_id()
                msg = self._room_manager.join_room(room_id, pid, name)
                result = {"message": msg, "room_id": room_id, "player_id": pid}

            elif path == "/api/destroy-room" and method == "POST":
                room_id = body.get("room_id", "")
                pid = body.get("player_id", "")
                room = self._room_manager.get_room(room_id)
                if not room:
                    result = {"error": "房间不存在"}
                elif room.host_id != pid:
                    result = {"error": "只有房主可以解散房间"}
                else:
                    self._room_manager.cleanup_room(room_id)
                    result = {"message": "房间已解散"}

            elif path == "/api/start-game" and method == "POST":
                room_id = body.get("room_id", "")
                pid = body.get("player_id", "")
                room = self._room_manager.get_room(room_id)
                if not room:
                    result = {"error": "房间不存在"}
                elif room.host_id != pid:
                    result = {"error": "只有房主可以开始"}
                elif room.engine.phase != GamePhase.WAITING:
                    result = {"error": "游戏已开始"}
                elif len(room.engine.players) < 2:
                    result = {"error": "至少需要2名玩家"}
                else:
                    msg = room.engine.start_game()
                    bot_msgs = await self._process_bot_turns(room)
                    result = {"message": msg, "bot_messages": bot_msgs, "game": self._build_state(room, pid)}

            elif path == "/api/add-bot" and method == "POST":
                room_id = body.get("room_id", "")
                pid = body.get("player_id", "")
                room = self._room_manager.get_room(room_id)
                if not room:
                    result = {"error": "房间不存在"}
                elif room.host_id != pid:
                    result = {"error": "只有房主可以添加 Bot"}
                else:
                    msg = self._room_manager.add_bot(room_id)
                    result = {"message": msg}

            elif path == "/api/game-state" and method == "GET":
                room_id = query.get("room_id", "")
                pid = query.get("player_id", "")
                room = self._room_manager.get_room(room_id)
                if not room:
                    result = {"error": "房间不存在"}
                else:
                    result = self._build_state(room, pid)

            elif path == "/api/hand" and method == "GET":
                room_id = query.get("room_id", "")
                pid = query.get("player_id", "")
                room = self._room_manager.get_room(room_id)
                if not room:
                    result = {"error": "房间不存在"}
                else:
                    player, _ = _player_from_room(room, pid)
                    if not player:
                        result = {"error": "你不是当前玩家"}
                    else:
                        cards = []
                        for i, c in enumerate(player.hand):
                            cards.append({
                                "index": i,
                                "color": c.color.name.lower(),
                                "color_display": c.color.display,
                                "value": c.value.name.lower(),
                                "value_display": c.value.display,
                                "emoji": c.color.emoji,
                                "playable": c.can_play_on(
                                    room.engine.top_card, room.engine.current_color
                                ),
                            })
                        result = {"cards": cards, "count": len(cards)}

            elif path == "/api/play-card" and method == "POST":
                room_id = body.get("room_id", "")
                pid = body.get("player_id", "")
                card_index = body.get("card_index", 0)
                chosen_color = body.get("chosen_color")
                room = self._room_manager.get_room(room_id)
                if not room:
                    result = {"error": "房间不存在"}
                elif room.engine.phase != GamePhase.PLAYING:
                    result = {"error": "游戏未开始"}
                else:
                    player, _ = _player_from_room(room, pid)
                    if not player:
                        result = {"error": "你不是当前玩家"}
                    elif player != room.engine.current_player:
                        result = {"error": "不是你的回合"}
                    else:
                        msg = room.engine.play_card(pid, card_index, chosen_color)
                        bot_msgs = await self._process_bot_turns(room)
                        result = {"message": msg, "bot_messages": bot_msgs, "game": self._build_state(room, pid)}

            elif path == "/api/draw-card" and method == "POST":
                room_id = body.get("room_id", "")
                pid = body.get("player_id", "")
                room = self._room_manager.get_room(room_id)
                if not room:
                    result = {"error": "房间不存在"}
                elif room.engine.phase != GamePhase.PLAYING:
                    result = {"error": "游戏未开始"}
                else:
                    player, _ = _player_from_room(room, pid)
                    if not player:
                        result = {"error": "你不是当前玩家"}
                    elif player != room.engine.current_player:
                        result = {"error": "不是你的回合"}
                    else:
                        msg = room.engine.draw_card(pid)
                        bot_msgs = await self._process_bot_turns(room)
                        result = {"message": msg, "bot_messages": bot_msgs, "game": self._build_state(room, pid)}

            elif path == "/api/say-uno" and method == "POST":
                room_id = body.get("room_id", "")
                pid = body.get("player_id", "")
                room = self._room_manager.get_room(room_id)
                if not room:
                    result = {"error": "房间不存在"}
                else:
                    msg = room.engine.say_uno(pid)
                    result = {"message": msg}

            elif path == "/api/catch-uno" and method == "POST":
                room_id = body.get("room_id", "")
                pid = body.get("player_id", "")
                target_id = body.get("target_id", "")
                room = self._room_manager.get_room(room_id)
                if not room:
                    result = {"error": "房间不存在"}
                else:
                    msg = room.engine.catch_uno(pid, target_id)
                    result = {"message": msg}

            elif path == "/api/leave" and method == "POST":
                pid = body.get("player_id", "")
                msg = self._room_manager.leave_room(pid)
                result = {"message": msg}

            elif path == "/api/restart-game" and method == "POST":
                room_id = body.get("room_id", "")
                pid = body.get("player_id", "")
                room = self._room_manager.get_room(room_id)
                if not room:
                    result = {"error": "房间不存在"}
                elif room.host_id != pid:
                    result = {"error": "只有房主可以重新开始"}
                elif room.engine.phase != GamePhase.ENDED:
                    result = {"error": "游戏未结束"}
                else:
                    msg = room.engine.restart_game()
                    bot_msgs = await self._process_bot_turns(room)
                    result = {"message": msg, "bot_messages": bot_msgs, "game": self._build_state(room, pid)}

            else:
                logger.warning("未知 API 请求: %s %s", method, path)
                result = {"error": "接口不存在"}
        except Exception as e:
            logger.error("API error: %s", e)
            traceback.print_exc()
            result = {"error": str(e)}

        if result:
            writer.write(_make_response(200, result))
        await writer.drain()

    @staticmethod
    def _format_scores(room: Room) -> str:
        parts: List[str] = []
        for p in room.engine.players:
            total = room.scores.get(p.player_id, 0)
            parts.append(f"{p.name}:{total}")
        return " | ".join(parts)

    def _build_state(self, room: Room, player_id: str) -> Dict[str, Any]:
        engine = room.engine
        top = engine.top_card
        top_card = None
        if top:
            top_card = {
                "color": top.color.name.lower(),
                "color_display": top.color.display,
                "value": top.value.name.lower(),
                "value_display": top.value.display,
                "emoji": top.color.emoji,
            }
        current = engine.current_player
        players = []
        for p in engine.players:
            players.append({
                "player_id": p.player_id,
                "name": p.name,
                "hand_count": p.hand_count(),
                "is_bot": p.is_bot,
                "is_host": p.player_id == room.host_id,
                "is_current": p is current,
                "said_uno": p.said_uno,
                "score": room.scores.get(p.player_id, 0),
            })
        my_idx = -1
        for i, p in enumerate(engine.players):
            if p.player_id == player_id:
                my_idx = i
                break
        return {
            "phase": engine.phase.value,
            "room_id": room.room_id,
            "top_card": top_card,
            "current_color": engine.current_color.name.lower(),
            "current_color_display": engine.current_color.display,
            "direction": engine.direction,
            "remaining_cards": engine.draw_pile.remaining if engine.draw_pile else 0,
            "players": players,
            "my_index": my_idx,
            "current_player_index": engine.current_player_index,
            "winner": engine.winner.name if engine.winner else None,
        }
