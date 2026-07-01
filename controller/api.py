from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Literal, Optional
from uuid import uuid4
import threading
import os

import chess
import chess.engine
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


# Change this if Stockfish is installed somewhere else
STOCKFISH_PATH = os.getenv("STOCKFISH_PATH", "/usr/games/stockfish")


DIFFICULTY_SKILL = {
    "B": 1,    # Beginner
    "E": 5,    # Easy
    "M": 10,   # Medium
    "X": 20,   # Expert
}


DIFFICULTY_NAMES = {
    "B": "Beginner",
    "E": "Easy",
    "M": "Medium",
    "X": "Expert",
}


PROMOTION_PIECES = {
    "q": chess.QUEEN,
    "r": chess.ROOK,
    "b": chess.BISHOP,
    "n": chess.KNIGHT,
}


PIECE_NAMES = {
    chess.QUEEN: "queen",
    chess.ROOK: "rook",
    chess.BISHOP: "bishop",
    chess.KNIGHT: "knight",
}


@dataclass
class GameSession:
    board: chess.Board
    difficulty: str
    human_color: str = "white"
    history: list = field(default_factory=list)

    # Physical robot mode pending move state
    pending_stockfish_move: Optional[str] = None
    pending_stockfish_san: Optional[str] = None
    pending_stockfish_is_castling: bool = False
    pending_stockfish_promotion: Optional[str] = None
    pending_human_record: Optional[dict] = None

    lock: threading.Lock = field(default_factory=threading.Lock)


engine: Optional[chess.engine.SimpleEngine] = None
engine_lock = threading.Lock()

games: dict[str, GameSession] = {}
games_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine

    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)

    yield

    if engine is not None:
        engine.quit()


app = FastAPI(
    title="Stockfish Chess API",
    version="2.0.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class NewGameRequest(BaseModel):
    difficulty: Literal["B", "E", "M", "X"] = "M"
    # In physical mode:
    #   human_color="white" -> human moves first, robot/Stockfish is black.
    #   human_color="black" -> robot/Stockfish moves first as white, human is black.
    human_color: Literal["white", "black"] = "white"
    think_time: float = Field(default=0.5, ge=0.05, le=10)


class MoveRequest(BaseModel):
    move: str = Field(
        ...,
        examples=[
            "e2e4",
            "e1g1",
            "e7e8q",
        ],
    )

    promotion: Optional[Literal["q", "r", "b", "n"]] = None
    think_time: float = Field(default=0.5, ge=0.05, le=10)


class ConfirmStockfishMoveRequest(BaseModel):
    move: str = Field(
        ...,
        examples=[
            "e7e5",
            "e8g8",
            "e2e1q",
        ],
    )

    promotion: Optional[Literal["q", "r", "b", "n"]] = None


class GameResponse(BaseModel):
    game_id: str
    difficulty: str
    difficulty_name: str
    human_color: str
    robot_color: str
    fen: str
    game_over: bool
    result: Optional[str]
    turn: str
    legal_moves: list[str]
    history: list

    # Physical mode fields
    pending_stockfish_move: Optional[str] = None
    pending_stockfish_san: Optional[str] = None
    pending_stockfish_is_castling: bool = False
    pending_stockfish_promotion: Optional[str] = None

    pending_human_move: Optional[str] = None
    pending_human_san: Optional[str] = None


class MoveResponse(BaseModel):
    game_id: str

    human_move: str
    human_san: str
    human_is_castling: bool
    human_promotion: Optional[str]

    stockfish_move: Optional[str]
    stockfish_san: Optional[str]
    stockfish_is_castling: bool
    stockfish_promotion: Optional[str]

    fen: str
    game_over: bool
    result: Optional[str]
    turn: str
    legal_moves: list[str]
    history: list


class HumanMovePhysicalResponse(BaseModel):
    game_id: str

    human_move: str
    human_san: str
    human_is_castling: bool
    human_promotion: Optional[str]

    stockfish_move: Optional[str]
    stockfish_san: Optional[str]
    stockfish_is_castling: bool
    stockfish_promotion: Optional[str]

    pending_stockfish_move: Optional[str]

    fen: str
    game_over: bool
    result: Optional[str]
    turn: str
    legal_moves: list[str]
    history: list


class ConfirmStockfishMoveResponse(BaseModel):
    game_id: str

    confirmed_stockfish_move: str
    confirmed_stockfish_san: str
    confirmed_stockfish_is_castling: bool
    confirmed_stockfish_promotion: Optional[str]

    fen: str
    game_over: bool
    result: Optional[str]
    turn: str
    legal_moves: list[str]
    history: list


@app.get("/")
def root():
    return {
        "message": "Stockfish Chess API is running",
        "docs": "/docs",
        "viewer": "/viewer?game_id=YOUR_GAME_ID",
        "levels": DIFFICULTY_NAMES,
        "digital_mode": {
            "move": "POST /games/{game_id}/move",
        },
        "physical_robot_mode": {
            "human_move": "POST /games/{game_id}/human-move",
            "confirm_stockfish_move": "POST /games/{game_id}/confirm-stockfish-move",
        },
        "examples": {
            "normal_move": "e2e4",
            "white_kingside_castling": "e1g1",
            "white_queenside_castling": "e1c1",
            "black_kingside_castling": "e8g8",
            "black_queenside_castling": "e8c8",
            "promotion_to_queen": "e7e8q",
            "promotion_to_rook": "e7e8r",
            "promotion_to_bishop": "e7e8b",
            "promotion_to_knight": "e7e8n",
        },
    }


@app.get("/viewer", response_class=HTMLResponse)
def chess_viewer():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <title>Chess Game Viewer</title>

    <style>
        * {
            box-sizing: border-box;
        }

        body {
            font-family: Arial, sans-serif;
            background: #1f1f1f;
            color: #f1f3f4;
            margin: 0;
            padding: 24px;
            display: flex;
            gap: 32px;
            align-items: flex-start;
        }

        h1 {
            margin-top: 0;
            margin-bottom: 20px;
        }

        .left {
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        #board {
            display: grid;
            grid-template-columns: repeat(8, 72px);
            grid-template-rows: repeat(8, 72px);
            border: 4px solid #111;
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.5);
        }

        .square {
            width: 72px;
            height: 72px;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
            user-select: none;
        }

        .light {
            background: #f0d9b5;
        }

        .dark {
            background: #b58863;
        }

        .last-move-from {
            background: #f6f669 !important;
            box-shadow: inset 0 0 0 5px rgba(255, 193, 7, 0.95);
        }

        .last-move-to {
            background: #f6f669 !important;
            box-shadow: inset 0 0 0 5px rgba(255, 152, 0, 0.95);
        }

        .piece {
            font-size: 48px;
            line-height: 1;
            position: relative;
            z-index: 2;
        }

        .white-piece {
            color: #ffffff;
            text-shadow:
                0 0 1px #000,
                1px 1px 0 #000,
                -1px -1px 0 #000,
                1px -1px 0 #000,
                -1px 1px 0 #000;
        }

        .black-piece {
            color: #111111;
            text-shadow:
                0 0 1px #fff,
                1px 1px 0 #fff,
                -1px -1px 0 #fff,
                1px -1px 0 #fff,
                -1px 1px 0 #fff;
        }

        .coord {
            position: absolute;
            font-size: 11px;
            font-weight: bold;
            opacity: 0.8;
            z-index: 3;
        }

        .light .coord {
            color: #6b4f2a;
        }

        .dark .coord {
            color: #f7f2e8;
        }

        .rank {
            top: 4px;
            left: 5px;
        }

        .file {
            bottom: 4px;
            right: 5px;
        }

        .info {
            min-width: 380px;
            max-width: 580px;
            background: #2b2c30;
            border-radius: 16px;
            padding: 20px;
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.35);
        }

        .panel {
            background: #1f2023;
            padding: 16px;
            border-radius: 12px;
            margin-bottom: 18px;
        }

        .panel-title {
            font-size: 20px;
            font-weight: bold;
            margin-bottom: 12px;
        }

        select,
        input {
            padding: 10px;
            width: 100%;
            border-radius: 8px;
            border: none;
            margin-top: 8px;
            font-size: 15px;
        }

        button {
            margin-top: 10px;
            padding: 10px 14px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            background: #8ab4f8;
            color: #111;
            font-weight: bold;
            width: 100%;
        }

        button:hover {
            background: #a8c7fa;
        }

        .row {
            margin-bottom: 12px;
        }

        .label {
            color: #aaa;
            font-size: 13px;
        }

        .value {
            font-size: 17px;
            margin-top: 3px;
            word-break: break-word;
        }

        .status {
            padding: 10px 12px;
            border-radius: 10px;
            background: #3c4043;
            margin-bottom: 16px;
            font-weight: bold;
        }

        .turn-box {
            padding: 16px;
            border-radius: 14px;
            margin-bottom: 16px;
            text-align: center;
            font-size: 24px;
            font-weight: bold;
            border: 3px solid transparent;
        }

        .turn-white {
            background: #ffffff;
            color: #111111;
            border-color: #dddddd;
        }

        .turn-black {
            background: #111111;
            color: #ffffff;
            border-color: #555555;
        }

        .turn-pending {
            background: #7a1f1f;
            color: #ffffff;
            border-color: #ff8080;
        }

        .turn-game-over {
            background: #5f6368;
            color: #ffffff;
            border-color: #888;
        }

        .history {
            margin-top: 16px;
            max-height: 360px;
            overflow-y: auto;
            background: #1f2023;
            border-radius: 10px;
            padding: 12px;
        }

        .move-line {
            padding: 6px 0;
            border-bottom: 1px solid #333;
            font-size: 14px;
        }

        .error {
            color: #ff8a80;
            font-weight: bold;
        }

        .hint {
            color: #bbb;
            font-size: 13px;
            line-height: 1.4;
            margin-top: 10px;
            margin-bottom: 8px;
        }

        .legend {
            margin-top: 14px;
            font-size: 14px;
            background: #2b2c30;
            padding: 10px 14px;
            border-radius: 10px;
        }

        .legend span {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            margin-right: 18px;
        }

        .legend .piece {
            font-size: 28px;
        }

        .copy-box {
            display: flex;
            gap: 8px;
            align-items: center;
        }

        .copy-box button {
            width: auto;
            margin-top: 8px;
            white-space: nowrap;
        }

        @media (max-width: 1000px) {
            body {
                flex-direction: column;
                align-items: center;
            }

            #board {
                grid-template-columns: repeat(8, 44px);
                grid-template-rows: repeat(8, 44px);
            }

            .square {
                width: 44px;
                height: 44px;
            }

            .piece {
                font-size: 30px;
            }

            .info {
                min-width: auto;
                width: 100%;
            }
        }
    </style>
</head>

<body>
    <div class="left">
        <h1>Chess Viewer</h1>

        <div id="board"></div>

        <div class="legend">
            <span><span class="piece white-piece">♔</span> White pieces</span>
            <span><span class="piece black-piece">♚</span> Black pieces</span>
        </div>
    </div>

    <div class="info">
        <div id="startPanel" class="panel">
            <div class="panel-title">Start New Game</div>

            <div class="label">Choose difficulty</div>
            <select id="difficultySelect">
                <option value="B">Beginner</option>
                <option value="E">Easy</option>
                <option value="M" selected>Medium</option>
                <option value="X">Expert</option>
            </select>

            <button onclick="startNewGame()">Start Game</button>

            <div class="hint">
                Use this page to create a game, then your Kinect controller can use the same Game ID.
            </div>
        </div>

        <div id="loadPanel" class="panel">
            <div class="panel-title">Load Existing Game</div>

            <div class="label">Game ID</div>
            <input id="gameIdInput" placeholder="Paste game_id here" />
            <button onclick="setGameId()">Load Game</button>
        </div>

        <div class="status" id="status">No game loaded.</div>

        <div id="turnBox" class="turn-box turn-game-over">
            No game started
        </div>

        <div class="row">
            <div class="label">Game ID</div>
            <div class="copy-box">
                <div class="value" id="gameId">-</div>
                <button onclick="copyGameId()">Copy</button>
            </div>
        </div>

        <div class="row">
            <div class="label">Difficulty</div>
            <div class="value" id="difficulty">-</div>
        </div>

        <div class="row">
            <div class="label">Pending Stockfish Move</div>
            <div class="value" id="pendingStockfish">-</div>
        </div>

        <div class="row">
            <div class="label">Result</div>
            <div class="value" id="result">-</div>
        </div>

        <div class="row">
            <div class="label">FEN</div>
            <div class="value" id="fen">-</div>
        </div>

        <div class="history">
            <div class="label">Move History</div>
            <div id="history"></div>
        </div>
    </div>

    <script>
        const pieceMap = {
            "P": "♙",
            "N": "♘",
            "B": "♗",
            "R": "♖",
            "Q": "♕",
            "K": "♔",
            "p": "♟",
            "n": "♞",
            "b": "♝",
            "r": "♜",
            "q": "♛",
            "k": "♚"
        };

        let gameId = new URLSearchParams(window.location.search).get("game_id");

        async function startNewGame() {
            const difficulty = document.getElementById("difficultySelect").value;

            try {
                const response = await fetch("/games", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        difficulty: difficulty,
                    }),
                });

                const data = await response.json();

                if (!response.ok) {
                    document.getElementById("status").innerHTML =
                        `<span class="error">${data.detail || "Could not create game."}</span>`;
                    return;
                }

                gameId = data.game_id;

                const newUrl = `${window.location.pathname}?game_id=${encodeURIComponent(gameId)}`;
                window.history.pushState({}, "", newUrl);

                document.getElementById("gameIdInput").value = gameId;

                renderGame(data);
            } catch (error) {
                document.getElementById("status").innerHTML =
                    `<span class="error">Could not connect to API.</span>`;
            }
        }

        function setGameId() {
            const input = document.getElementById("gameIdInput").value.trim();

            if (!input) {
                alert("Please enter a game_id.");
                return;
            }

            gameId = input;

            const newUrl = `${window.location.pathname}?game_id=${encodeURIComponent(gameId)}`;
            window.history.pushState({}, "", newUrl);

            loadGame();
        }

        function copyGameId() {
            if (!gameId) {
                alert("No game_id to copy.");
                return;
            }

            navigator.clipboard.writeText(gameId);
            alert("Game ID copied.");
        }

        function getLastMove(history) {
            if (!history || history.length === 0) {
                return null;
            }

            const lastRecord = history[history.length - 1];

            if (lastRecord.stockfish_move) {
                return lastRecord.stockfish_move;
            }

            return lastRecord.human_move || null;
        }

        function renderBoard(fen, lastMove) {
            const boardElement = document.getElementById("board");
            boardElement.innerHTML = "";

            const boardPart = fen.split(" ")[0];
            const ranks = boardPart.split("/");

            for (let rankIndex = 0; rankIndex < 8; rankIndex++) {
                const rank = ranks[rankIndex];
                let fileIndex = 0;

                for (const char of rank) {
                    if (!isNaN(char)) {
                        const emptyCount = Number(char);

                        for (let i = 0; i < emptyCount; i++) {
                            addSquare(boardElement, rankIndex, fileIndex, null, lastMove);
                            fileIndex++;
                        }
                    } else {
                        addSquare(boardElement, rankIndex, fileIndex, char, lastMove);
                        fileIndex++;
                    }
                }
            }
        }

        function addSquare(boardElement, rankIndex, fileIndex, pieceChar, lastMove) {
            const square = document.createElement("div");
            const isLight = (rankIndex + fileIndex) % 2 === 0;

            const rankNumber = 8 - rankIndex;
            const fileLetter = String.fromCharCode("a".charCodeAt(0) + fileIndex);
            const squareName = `${fileLetter}${rankNumber}`;

            square.className = `square ${isLight ? "light" : "dark"}`;

            if (lastMove) {
                const fromSquare = lastMove.slice(0, 2);
                const toSquare = lastMove.slice(2, 4);

                if (squareName === fromSquare) {
                    square.classList.add("last-move-from");
                }

                if (squareName === toSquare) {
                    square.classList.add("last-move-to");
                }
            }

            if (pieceChar) {
                const pieceSpan = document.createElement("span");
                pieceSpan.classList.add("piece");

                const isWhitePiece = pieceChar === pieceChar.toUpperCase();
                pieceSpan.classList.add(isWhitePiece ? "white-piece" : "black-piece");

                pieceSpan.textContent = pieceMap[pieceChar] || "";
                square.appendChild(pieceSpan);
            }

            if (fileIndex === 0) {
                const rankCoord = document.createElement("span");
                rankCoord.className = "coord rank";
                rankCoord.textContent = rankNumber;
                square.appendChild(rankCoord);
            }

            if (rankIndex === 7) {
                const fileCoord = document.createElement("span");
                fileCoord.className = "coord file";
                fileCoord.textContent = fileLetter;
                square.appendChild(fileCoord);
            }

            boardElement.appendChild(square);
        }

        function renderHistory(history) {
            const historyElement = document.getElementById("history");
            historyElement.innerHTML = "";

            if (!history || history.length === 0) {
                historyElement.innerHTML = "<p>No completed move pairs yet.</p>";
                return;
            }

            for (const item of history) {
                const div = document.createElement("div");
                div.className = "move-line";

                const human = item.human_san || item.human_move || "";
                const stockfish = item.stockfish_san || item.stockfish_move || "";

                div.textContent = `${item.move_number}. White: ${human}   Black: ${stockfish}`;
                historyElement.appendChild(div);
            }
        }

        function renderTurn(data) {
            const turnBox = document.getElementById("turnBox");

            turnBox.classList.remove("turn-white", "turn-black", "turn-pending", "turn-game-over");

            if (data.game_over) {
                turnBox.classList.add("turn-game-over");
                turnBox.textContent = `Game Over: ${data.result}`;
                return;
            }

            if (data.pending_stockfish_move) {
                turnBox.classList.add("turn-pending");
                turnBox.textContent = `Robot should play: ${data.pending_stockfish_move}`;
                return;
            }

            if (data.turn === "white") {
                turnBox.classList.add("turn-white");
                turnBox.textContent = "White / Human to move";
            } else {
                turnBox.classList.add("turn-black");
                turnBox.textContent = "Black to move";
            }
        }

        function renderGame(data) {
            const lastMove = getLastMove(data.history);

            renderBoard(data.fen, lastMove);
            renderHistory(data.history);
            renderTurn(data);

            document.getElementById("startPanel").style.display = "none";
            document.getElementById("loadPanel").style.display = "none";

            document.getElementById("status").textContent =
                data.game_over ? "Game over" : "Live game";

            document.getElementById("gameId").textContent = data.game_id;
            document.getElementById("difficulty").textContent = data.difficulty_name;

            if (data.pending_stockfish_move) {
                let pendingText = data.pending_stockfish_move;

                if (data.pending_stockfish_san) {
                    pendingText += ` (${data.pending_stockfish_san})`;
                }

                document.getElementById("pendingStockfish").textContent = pendingText;
            } else {
                document.getElementById("pendingStockfish").textContent = "-";
            }

            document.getElementById("result").textContent = data.result || "-";
            document.getElementById("fen").textContent = data.fen;
        }

        async function loadGame() {
            if (!gameId) {
                document.getElementById("status").innerHTML =
                    "No game loaded. Start a new game or paste a game_id.";
                return;
            }

            try {
                const response = await fetch(`/games/${gameId}`);
                const data = await response.json();

                if (!response.ok) {
                    document.getElementById("status").innerHTML =
                        `<span class="error">${data.detail || "Could not load game."}</span>`;
                    return;
                }

                renderGame(data);
            } catch (error) {
                document.getElementById("status").innerHTML =
                    `<span class="error">Could not connect to API.</span>`;
            }
        }

        loadGame();
        setInterval(loadGame, 800);
    </script>
</body>
</html>
    """


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "engine_loaded": engine is not None,
    }


@app.get("/levels")
def get_levels():
    return {
        "levels": [
            {
                "code": "B",
                "name": "Beginner",
                "stockfish_skill": DIFFICULTY_SKILL["B"],
            },
            {
                "code": "E",
                "name": "Easy",
                "stockfish_skill": DIFFICULTY_SKILL["E"],
            },
            {
                "code": "M",
                "name": "Medium",
                "stockfish_skill": DIFFICULTY_SKILL["M"],
            },
            {
                "code": "X",
                "name": "Expert",
                "stockfish_skill": DIFFICULTY_SKILL["X"],
            },
        ]
    }


@app.post("/games", response_model=GameResponse)
def create_game(request: NewGameRequest):
    game_id = str(uuid4())
    board = chess.Board()

    session = GameSession(
        board=board,
        difficulty=request.difficulty,
        human_color=request.human_color,
    )

    # If the human is black, the robot/Stockfish is white and must move first.
    # We calculate that first white move and store it as pending.
    # It is NOT pushed to the board yet; the physical robot must make it first,
    # then /confirm-stockfish-move will verify and push it.
    if request.human_color == "black":
        set_pending_stockfish_move(
            session=session,
            board=board,
            think_time=request.think_time,
        )

    with games_lock:
        games[game_id] = session

    return build_game_response(game_id, session)


@app.get("/games/{game_id}", response_model=GameResponse)
def get_game(game_id: str):
    session = get_session(game_id)

    with session.lock:
        return build_game_response(game_id, session)


@app.post("/games/{game_id}/move", response_model=MoveResponse)
def play_move(game_id: str, request: MoveRequest):
    """
    Normal digital mode.

    This endpoint applies:
    1. Human move
    2. Stockfish move immediately

    Do not use this endpoint for the physical robot flow.
    """
    session = get_session(game_id)

    with session.lock:
        board = session.board

        if session.pending_stockfish_move is not None:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "This game has a pending Stockfish move.",
                    "pending_stockfish_move": session.pending_stockfish_move,
                    "use": f"/games/{game_id}/confirm-stockfish-move",
                },
            )

        if board.is_game_over():
            raise HTTPException(
                status_code=400,
                detail=f"Game is already over. Result: {board.result()}",
            )

        human_move = parse_human_move(
            board=board,
            move_text=request.move,
            promotion=request.promotion,
        )

        human_is_castling = board.is_castling(human_move)
        human_promotion = get_promotion_name(human_move)
        human_san = board.san(human_move)

        board.push(human_move)

        stockfish_move = None
        stockfish_san = None
        stockfish_is_castling = False
        stockfish_promotion = None

        if not board.is_game_over():
            stockfish_move = calculate_stockfish_move(
                board=board,
                difficulty=session.difficulty,
                think_time=request.think_time,
            )

            stockfish_is_castling = board.is_castling(stockfish_move)
            stockfish_promotion = get_promotion_name(stockfish_move)
            stockfish_san = board.san(stockfish_move)

            board.push(stockfish_move)

        move_record = {
            "move_number": len(session.history) + 1,

            "human_move": human_move.uci(),
            "human_san": human_san,
            "human_is_castling": human_is_castling,
            "human_promotion": human_promotion,

            "stockfish_move": stockfish_move.uci() if stockfish_move else None,
            "stockfish_san": stockfish_san,
            "stockfish_is_castling": stockfish_is_castling,
            "stockfish_promotion": stockfish_promotion,
        }

        session.history.append(move_record)

        return MoveResponse(
            game_id=game_id,

            human_move=human_move.uci(),
            human_san=human_san,
            human_is_castling=human_is_castling,
            human_promotion=human_promotion,

            stockfish_move=stockfish_move.uci() if stockfish_move else None,
            stockfish_san=stockfish_san,
            stockfish_is_castling=stockfish_is_castling,
            stockfish_promotion=stockfish_promotion,

            fen=board.fen(),
            game_over=board.is_game_over(),
            result=board.result() if board.is_game_over() else None,
            turn=get_turn(board),
            legal_moves=get_legal_moves(board),
            history=session.history,
        )


@app.post("/games/{game_id}/human-move", response_model=HumanMovePhysicalResponse)
def play_human_move_physical(game_id: str, request: MoveRequest):
    """
    Physical robot mode.

    This endpoint:
    1. Applies the human move.
    2. Calculates Stockfish/robot's reply.
    3. Stores Stockfish/robot's move as pending.
    4. Does NOT push Stockfish/robot's move yet.
    """
    session = get_session(game_id)

    with session.lock:
        board = session.board

        if session.pending_stockfish_move is not None:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "There is already a pending Stockfish move.",
                    "pending_stockfish_move": session.pending_stockfish_move,
                    "use": f"/games/{game_id}/confirm-stockfish-move",
                },
            )

        if board.is_game_over():
            raise HTTPException(
                status_code=400,
                detail=f"Game is already over. Result: {board.result()}",
            )

        human_turn = color_to_chess(session.human_color)

        if board.turn != human_turn:
            raise HTTPException(
                status_code=400,
                detail=f"It is not the human's turn. Human is {session.human_color}.",
            )

        human_move = parse_human_move(
            board=board,
            move_text=request.move,
            promotion=request.promotion,
        )

        human_is_castling = board.is_castling(human_move)
        human_promotion = get_promotion_name(human_move)
        human_san = board.san(human_move)

        board.push(human_move)

        move_record = {
            "move_number": len(session.history) + 1,

            "human_move": human_move.uci(),
            "human_san": human_san,
            "human_is_castling": human_is_castling,
            "human_promotion": human_promotion,

            "stockfish_move": None,
            "stockfish_san": None,
            "stockfish_is_castling": False,
            "stockfish_promotion": None,
        }

        if board.is_game_over():
            session.history.append(move_record)
            clear_pending_stockfish(session)

            return HumanMovePhysicalResponse(
                game_id=game_id,

                human_move=human_move.uci(),
                human_san=human_san,
                human_is_castling=human_is_castling,
                human_promotion=human_promotion,

                stockfish_move=None,
                stockfish_san=None,
                stockfish_is_castling=False,
                stockfish_promotion=None,

                pending_stockfish_move=None,

                fen=board.fen(),
                game_over=True,
                result=board.result(),
                turn=get_turn(board),
                legal_moves=get_legal_moves(board),
                history=session.history,
            )

        stockfish_move = calculate_stockfish_move(
            board=board,
            difficulty=session.difficulty,
            think_time=request.think_time,
        )

        stockfish_is_castling = board.is_castling(stockfish_move)
        stockfish_promotion = get_promotion_name(stockfish_move)
        stockfish_san = board.san(stockfish_move)

        session.pending_stockfish_move = stockfish_move.uci()
        session.pending_stockfish_san = stockfish_san
        session.pending_stockfish_is_castling = stockfish_is_castling
        session.pending_stockfish_promotion = stockfish_promotion
        session.pending_human_record = move_record

        return HumanMovePhysicalResponse(
            game_id=game_id,

            human_move=human_move.uci(),
            human_san=human_san,
            human_is_castling=human_is_castling,
            human_promotion=human_promotion,

            stockfish_move=stockfish_move.uci(),
            stockfish_san=stockfish_san,
            stockfish_is_castling=stockfish_is_castling,
            stockfish_promotion=stockfish_promotion,

            pending_stockfish_move=stockfish_move.uci(),

            # Important:
            # This FEN is after the human move only.
            # Stockfish move is pending, not applied yet.
            fen=board.fen(),
            game_over=False,
            result=None,
            turn=get_turn(board),
            legal_moves=get_legal_moves(board),
            history=session.history,
        )


@app.post(
    "/games/{game_id}/confirm-stockfish-move",
    response_model=ConfirmStockfishMoveResponse,
)
def confirm_stockfish_move_physical(
    game_id: str,
    request: ConfirmStockfishMoveRequest,
):
    """
    Physical robot mode.

    This endpoint:
    1. Receives the robot/camera verified Stockfish move.
    2. Checks it matches the pending Stockfish move.
    3. Pushes the Stockfish move.
    4. Clears the pending move.
    """
    session = get_session(game_id)

    with session.lock:
        board = session.board

        if session.pending_stockfish_move is None:
            raise HTTPException(
                status_code=400,
                detail="There is no pending Stockfish move to confirm.",
            )

        if board.is_game_over():
            raise HTTPException(
                status_code=400,
                detail=f"Game is already over. Result: {board.result()}",
            )

        confirmed_move = parse_human_move(
            board=board,
            move_text=request.move,
            promotion=request.promotion,
        )

        confirmed_uci = confirmed_move.uci()
        expected_uci = session.pending_stockfish_move

        if confirmed_uci != expected_uci:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Confirmed robot move does not match pending Stockfish move.",
                    "expected": expected_uci,
                    "received": confirmed_uci,
                },
            )

        confirmed_is_castling = board.is_castling(confirmed_move)
        confirmed_promotion = get_promotion_name(confirmed_move)
        confirmed_san = board.san(confirmed_move)

        board.push(confirmed_move)

        move_record = session.pending_human_record or {
            "move_number": len(session.history) + 1,
            "human_move": None,
            "human_san": None,
            "human_is_castling": False,
            "human_promotion": None,
        }

        move_record["stockfish_move"] = confirmed_uci
        move_record["stockfish_san"] = confirmed_san
        move_record["stockfish_is_castling"] = confirmed_is_castling
        move_record["stockfish_promotion"] = confirmed_promotion

        session.history.append(move_record)

        clear_pending_stockfish(session)

        return ConfirmStockfishMoveResponse(
            game_id=game_id,

            confirmed_stockfish_move=confirmed_uci,
            confirmed_stockfish_san=confirmed_san,
            confirmed_stockfish_is_castling=confirmed_is_castling,
            confirmed_stockfish_promotion=confirmed_promotion,

            fen=board.fen(),
            game_over=board.is_game_over(),
            result=board.result() if board.is_game_over() else None,
            turn=get_turn(board),
            legal_moves=get_legal_moves(board),
            history=session.history,
        )


@app.delete("/games/{game_id}")
def delete_game(game_id: str):
    with games_lock:
        if game_id not in games:
            raise HTTPException(status_code=404, detail="Game not found")

        del games[game_id]

    return {
        "message": "Game deleted",
        "game_id": game_id,
    }


def build_game_response(game_id: str, session: GameSession) -> GameResponse:
    board = session.board

    pending_human_move = None
    pending_human_san = None

    if session.pending_human_record:
        pending_human_move = session.pending_human_record.get("human_move")
        pending_human_san = session.pending_human_record.get("human_san")

    return GameResponse(
        game_id=game_id,
        difficulty=session.difficulty,
        difficulty_name=DIFFICULTY_NAMES[session.difficulty],
        human_color=session.human_color,
        robot_color=opposite_color(session.human_color),
        fen=board.fen(),
        game_over=board.is_game_over(),
        result=board.result() if board.is_game_over() else None,
        turn=get_turn(board),
        legal_moves=get_legal_moves(board),
        history=session.history,

        pending_stockfish_move=session.pending_stockfish_move,
        pending_stockfish_san=session.pending_stockfish_san,
        pending_stockfish_is_castling=session.pending_stockfish_is_castling,
        pending_stockfish_promotion=session.pending_stockfish_promotion,

        pending_human_move=pending_human_move,
        pending_human_san=pending_human_san,
    )



def color_to_chess(color: str) -> bool:
    return chess.WHITE if color == "white" else chess.BLACK


def opposite_color(color: str) -> str:
    return "black" if color == "white" else "white"


def set_pending_stockfish_move(
    session: GameSession,
    board: chess.Board,
    think_time: float,
) -> chess.Move:
    if board.is_game_over():
        raise HTTPException(
            status_code=400,
            detail=f"Game is already over. Result: {board.result()}",
        )

    stockfish_move = calculate_stockfish_move(
        board=board,
        difficulty=session.difficulty,
        think_time=think_time,
    )

    stockfish_is_castling = board.is_castling(stockfish_move)
    stockfish_promotion = get_promotion_name(stockfish_move)
    stockfish_san = board.san(stockfish_move)

    session.pending_stockfish_move = stockfish_move.uci()
    session.pending_stockfish_san = stockfish_san
    session.pending_stockfish_is_castling = stockfish_is_castling
    session.pending_stockfish_promotion = stockfish_promotion
    session.pending_human_record = None

    return stockfish_move

def get_session(game_id: str) -> GameSession:
    with games_lock:
        session = games.get(game_id)

    if session is None:
        raise HTTPException(status_code=404, detail="Game not found")

    return session


def get_turn(board: chess.Board) -> str:
    return "white" if board.turn == chess.WHITE else "black"


def get_legal_moves(board: chess.Board) -> list[str]:
    return [move.uci() for move in board.legal_moves]


def get_promotion_name(move: chess.Move) -> Optional[str]:
    if move.promotion is None:
        return None

    return PIECE_NAMES.get(move.promotion)


def calculate_stockfish_move(
    board: chess.Board,
    difficulty: str,
    think_time: float,
) -> chess.Move:
    if engine is None:
        raise HTTPException(
            status_code=500,
            detail="Stockfish engine is not loaded.",
        )

    skill_level = DIFFICULTY_SKILL[difficulty]

    with engine_lock:
        result = engine.play(
            board,
            chess.engine.Limit(time=think_time),
            options={
                "Skill Level": skill_level,
            },
        )

    if result.move is None:
        raise HTTPException(
            status_code=500,
            detail="Stockfish did not return a move.",
        )

    return result.move


def clear_pending_stockfish(session: GameSession):
    session.pending_stockfish_move = None
    session.pending_stockfish_san = None
    session.pending_stockfish_is_castling = False
    session.pending_stockfish_promotion = None
    session.pending_human_record = None


def parse_human_move(
    board: chess.Board,
    move_text: str,
    promotion: Optional[str],
) -> chess.Move:
    move_text = move_text.strip().lower()

    if promotion and len(move_text) == 4:
        move_text = move_text + promotion.lower()

    try:
        move = chess.Move.from_uci(move_text)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid move format. Use moves like e2e4, g1f3, "
                "e1g1 for castling, or e7e8q for promotion."
            ),
        )

    if len(move_text) == 4:
        promotion_options = get_promotion_options_for_move(board, move)

        if promotion_options:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Promotion required. Choose q, r, b, or n.",
                    "promotion_required": True,
                    "promotion_options": promotion_options,
                    "examples": {
                        "queen": promotion_options[0],
                        "rook": promotion_options[1],
                        "bishop": promotion_options[2],
                        "knight": promotion_options[3],
                    },
                },
            )

    if move not in board.legal_moves:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Illegal move.",
                "legal_moves": get_legal_moves(board),
            },
        )

    return move


def get_promotion_options_for_move(
    board: chess.Board,
    move: chess.Move,
) -> list[str]:
    options = []

    for legal_move in board.legal_moves:
        same_from = legal_move.from_square == move.from_square
        same_to = legal_move.to_square == move.to_square
        is_promotion = legal_move.promotion is not None

        if same_from and same_to and is_promotion:
            options.append(legal_move.uci())

    return options