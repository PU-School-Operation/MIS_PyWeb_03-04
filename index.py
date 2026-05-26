import importlib.util
import json
import os
import random
from datetime import datetime
from pathlib import Path

import firebase_admin
import requests
from bs4 import BeautifulSoup
from flask import (
    Flask,
    jsonify,
    make_response,
    render_template,
    render_template_string,
    request,
)
from firebase_admin import credentials, firestore

from bug.opendata import search_accident_by_road
from bug.spider import fetch_upcoming_movies
from bug.weather import get_weather
from AI.gemini import ask_gemini

from google import genai

BASE_DIR = Path(__file__).resolve().parent


def _load_local_env_file(env_path):
    if not env_path.exists():
        return

    with env_path.open("r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value


_load_local_env_file(BASE_DIR / ".env")


def _get_gemini_api_key():
    return (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("google_API_key")
        or os.getenv("google_api_key")
    )


def _get_gemini_model():
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# 判斷是在 Vercel 還是本地
local_service_account = BASE_DIR / "serviceAccountKey.json"
if local_service_account.exists():
    # 本地環境：讀取檔案
    cred = credentials.Certificate(str(local_service_account))
else:
    # 雲端環境：從環境變數讀取 JSON 字串
    firebase_config = os.getenv("FIREBASE_CONFIG")
    cred = (
        credentials.Certificate(json.loads(firebase_config))
        if firebase_config
        else None
    )

if cred is not None and not firebase_admin._apps:
    firebase_admin.initialize_app(cred)


app = Flask(__name__)

_gemini_client = None
_gemini_client_error = None

api_key = _get_gemini_api_key()
if api_key:
    try:
        _gemini_client = genai.Client(api_key=api_key)
    except Exception as exc:
        _gemini_client_error = str(exc)
else:
    _gemini_client_error = "找不到 Gemini API Key，請確認專案根目錄的 .env 是否設定 GOOGLE_API_KEY"

MOVIE_RATING_COLLECTION = "本週新片含分級"


def _load_rate_helper():
    module_path = Path(__file__).resolve().parent / "rate" / "08_rate.py"
    spec = importlib.util.spec_from_file_location("rate_08_rate", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("無法載入 rate/08_rate.py")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _get_firestore_collection(collection_name):
    if not firebase_admin._apps:
        raise RuntimeError("Firestore 尚未初始化，請先設定 Firebase 憑證")

    db = firestore.client()
    return db.collection(collection_name)


def _build_rate_movie_reply(rate, include_introduce=False):
    try:
        collection_ref = _get_firestore_collection(MOVIE_RATING_COLLECTION)
        docs = collection_ref.get()
    except Exception as exc:
        return f"目前無法讀取電影資料庫：{exc}\n"

    result = ""

    for doc in docs:
        data = doc.to_dict() or {}
        movie_rate = str(data.get("rate", ""))
        if rate not in movie_rate:
            continue

        result += "片名：" + str(data.get("title", "")) + "\n"
        if include_introduce:
            result += "影片介紹：" + str(data.get("introduce", "")) + "\n"
        else:
            result += "介紹：" + str(data.get("hyperlink", "")) + "\n"
        result += "\n"

    if result == "":
        return "目前沒有查到符合此分級的相關電影。\n"

    return result


def _render_ai_page(question, answer=None, error=None):
    title = "AI 問答"
    question = question or ""
    answer = answer or ""
    error = error or ""

    return render_template_string(
        """
        <!doctype html>
        <html lang="zh-TW">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>{{ title }}</title>
                <style>
                    :root {
                        color-scheme: light;
                        --bg-a: #0f172a;
                        --bg-b: #1d4ed8;
                        --bg-c: #06b6d4;
                        --card: rgba(255, 255, 255, 0.94);
                        --text: #0f172a;
                        --muted: #64748b;
                        --border: rgba(148, 163, 184, 0.24);
                        --shadow: 0 24px 80px rgba(15, 23, 42, 0.22);
                    }

                    * {
                        box-sizing: border-box;
                    }

                    body {
                        margin: 0;
                        min-height: 100vh;
                        font-family: "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif;
                        color: var(--text);
                        background:
                            radial-gradient(circle at top left, rgba(255, 255, 255, 0.18), transparent 32%),
                            radial-gradient(circle at bottom right, rgba(255, 255, 255, 0.12), transparent 28%),
                            linear-gradient(135deg, var(--bg-a), var(--bg-b) 52%, var(--bg-c));
                        display: grid;
                        place-items: center;
                        padding: 32px 16px;
                    }

                    .page {
                        width: min(100%, 920px);
                    }

                    .hero {
                        color: white;
                        margin-bottom: 18px;
                    }

                    .eyebrow {
                        display: inline-flex;
                        align-items: center;
                        gap: 8px;
                        padding: 8px 12px;
                        border-radius: 999px;
                        background: rgba(255, 255, 255, 0.12);
                        border: 1px solid rgba(255, 255, 255, 0.16);
                        backdrop-filter: blur(8px);
                        font-size: 14px;
                        letter-spacing: 0.06em;
                        text-transform: uppercase;
                    }

                    h1 {
                        margin: 14px 0 10px;
                        font-size: clamp(2rem, 4vw, 3.4rem);
                        line-height: 1.05;
                    }

                    .subtitle {
                        margin: 0;
                        max-width: 60ch;
                        color: rgba(255, 255, 255, 0.88);
                        font-size: 1.02rem;
                        line-height: 1.7;
                    }

                    .panel {
                        display: grid;
                        grid-template-columns: 1.2fr 1fr;
                        gap: 18px;
                    }

                    .card {
                        background: var(--card);
                        border: 1px solid var(--border);
                        border-radius: 24px;
                        box-shadow: var(--shadow);
                        overflow: hidden;
                        backdrop-filter: blur(12px);
                    }

                    .card-body {
                        padding: 22px;
                    }

                    label {
                        display: block;
                        margin-bottom: 10px;
                        font-weight: 700;
                        color: #111827;
                    }

                    textarea {
                        width: 100%;
                        min-height: 160px;
                        resize: vertical;
                        border-radius: 18px;
                        border: 1px solid rgba(148, 163, 184, 0.4);
                        padding: 16px 18px;
                        font: inherit;
                        line-height: 1.65;
                        color: var(--text);
                        background: #f8fafc;
                        outline: none;
                    }

                    textarea:focus {
                        border-color: #2563eb;
                        box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.12);
                        background: white;
                    }

                    .actions {
                        display: flex;
                        gap: 12px;
                        margin-top: 14px;
                        flex-wrap: wrap;
                    }

                    button, .link-btn {
                        border: 0;
                        border-radius: 14px;
                        padding: 12px 18px;
                        font: inherit;
                        font-weight: 700;
                        cursor: pointer;
                        text-decoration: none;
                        transition: transform 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
                    }

                    button {
                        color: white;
                        background: linear-gradient(135deg, #2563eb, #06b6d4);
                        box-shadow: 0 14px 32px rgba(37, 99, 235, 0.35);
                    }

                    .link-btn {
                        color: #0f172a;
                        background: rgba(15, 23, 42, 0.06);
                    }

                    button:hover, .link-btn:hover {
                        transform: translateY(-1px);
                    }

                    .result-title {
                        margin: 0 0 12px;
                        font-size: 1rem;
                        color: #111827;
                    }

                    .result-box {
                        min-height: 220px;
                        border-radius: 20px;
                        padding: 18px 18px 20px;
                        background: linear-gradient(180deg, #ffffff, #f8fafc);
                        border: 1px solid rgba(148, 163, 184, 0.26);
                        white-space: pre-wrap;
                        line-height: 1.8;
                        overflow-wrap: anywhere;
                    }

                    .hint {
                        margin-top: 10px;
                        color: var(--muted);
                        font-size: 0.92rem;
                        line-height: 1.7;
                    }

                    .error {
                        margin-top: 14px;
                        padding: 12px 14px;
                        border-radius: 14px;
                        background: #fef2f2;
                        color: #b91c1c;
                        border: 1px solid rgba(239, 68, 68, 0.18);
                        line-height: 1.6;
                    }

                    @media (max-width: 860px) {
                        .panel {
                            grid-template-columns: 1fr;
                        }
                    }
                </style>
            </head>
            <body>
                <div class="page">
                    <div class="hero">
                        <div class="eyebrow">AI Assistant</div>
                        <h1>{{ title }}</h1>
                        <p class="subtitle">輸入你的問題後送出，系統會透過 Gemini 回答；如果是 Dialogflow webhook，也會用同一套 AI 能力回應使用者。</p>
                    </div>

                    <div class="panel">
                        <section class="card">
                            <div class="card-body">
                                <form method="get" action="/AI">
                                    <label for="q">你的問題</label>
                                    <textarea id="q" name="q" placeholder="請輸入你的問題">{{ question }}</textarea>
                                    <div class="actions">
                                        <button type="submit">送出問題</button>
                                        <a class="link-btn" href="/">回到首頁</a>
                                    </div>
                                </form>
                                {% if error %}
                                <div class="error">{{ error }}</div>
                                {% endif %}
                            </div>
                        </section>

                        <section class="card">
                            <div class="card-body">
                                <p class="result-title">AI 回答</p>
                                <div class="result-box">{{ answer if answer else '尚未輸入問題，這裡會顯示 AI 回答。' }}</div>
                                <div class="hint">提示：你也可以直接把這個頁面當成 AI 測試介面，先確認 Gemini 與 .env 設定是否正常。</div>
                            </div>
                        </section>
                    </div>
                </div>
            </body>
        </html>
        """,
        title=title,
        question=question,
        answer=answer,
        error=error,
    )


@app.route("/")
def index():
    homepage = "<h1>吳岱威Python網頁</h1>"
    homepage += "<a href=/mis>MIS</a><br>"
    homepage += "<a href=/today>顯示日期時間</a><br>"
    homepage += "<a href=/welcome?name=吳岱威&school=資管系>傳送使用者暱稱</a><br>"
    homepage += "<a href=/account>網頁表單傳值</a><br>"
    homepage += "<a href=/math>數學運算</a><br>"
    homepage += "<a href=/about>岱威簡介網頁</a><br>"
    homepage += "<br><a href=/read>老師資料查詢</a><br>"
    homepage += "<br><a href=/next>讀取開眼電影即將上映影片</a><br>"
    homepage += "<br><a href=/movie2>本週即將上映電影進DB</a><br>"
    homepage += "<br><a href=/movie3>查詢即將上映電影</a><br>"
    homepage += "<br><a href=/check_update>檢查開眼電影網頁最後更新時間</a><br>"
    homepage += "<br><a href=/road>查詢易肇事路口</a><br>"
    homepage += "<br><a href=/weather>查詢氣象預報</a><br>"
    homepage += "<br><a href=/rate>本週新片進DB</a><br>"
    homepage += "<br><a href=/AI>AI 問答</a><br>"

    # 【修正】：修正 HTML 標籤拼字錯誤與增加必要空格
    homepage += '<script src="https://www.gstatic.com/dialogflow-console/fast/messenger/bootstrap.js?v=1"></script>'
    homepage += '<df-messenger intent="WELCOME" chat-title="吳岱威的聊天機器人-MIS" '
    homepage += 'agent-id="afa9a893-0765-40e2-a001-4e48982a5bc1" '
    homepage += 'language-code="zh-tw"></df-messenger>'

    return homepage


@app.route("/mis")
def course():
    return "<h1>資訊管理導論</h1><a href=/>回到網站首頁</a>"


@app.route("/today")
def today():
    now = datetime.now()
    year = str(now.year)  # 取得年份
    month = str(now.month)  # 取得月份
    day = str(now.day)  # 取得日期
    now = year + "年" + month + "月" + day + "日"
    return render_template("today.html", datetime=now)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/welcome", methods=["GET"])
def welcome():
    x = request.values.get("name")
    y = request.values.get("school")
    return render_template("welcome.html", name=x, school=y)


@app.route("/account", methods=["GET", "POST"])
def account():
    if request.method == "POST":
        user = request.form["user"]
        pwd = request.form["pwd"]
        result = "您輸入的帳號是：" + user + "; 密碼為：" + pwd
        return result
    else:
        return render_template("account.html")


@app.route("/math", methods=["GET", "POST"])
def math():
    if request.method == "POST":
        x = int(request.form["x"])
        opt = request.form["opt"]
        y = int(request.form["y"])
        result = "您輸入的是：" + str(x) + opt + str(y)

        if opt == "/" and y == 0:
            result += "，除數不能為0"
        else:
            match opt:
                case "+":
                    r = x + y
                case "-":
                    r = x - y
                case "*":
                    r = x * y
                case "/":
                    r = x / y  # 修正：之前誤寫為 x - y
                case _:
                    return "未知運算符號"
            result += "=" + str(r) + "<br><a href=/>返回首頁</a>"
        return result
    else:
        return render_template("math.html")


@app.route("/cup", methods=["GET"])
def cup():
    action = request.values.get("action")
    result = None

    if action == "toss":
        x1 = random.randint(0, 1)
        x2 = random.randint(0, 1)

        if x1 != x2:
            msg = "聖筊：表示神明允許、同意，或行事會順利。"
        elif x1 == 0:
            msg = "笑筊：表示神明一笑、不解，或者考慮中，行事狀況不明。"
        else:
            msg = "陰筊：表示神明否定、憤怒，或者不宜行事。"

        result = {
            "cup1": "/static/" + str(x1) + ".jpg",
            "cup2": "/static/" + str(x2) + ".jpg",
            "message": msg,
        }

        if result is None:
            return render_template_string("""
                        <html lang="zh-TW">
                            <head><meta charset="UTF-8"><title>擲筊</title></head>
                            <body>
                                <h1>擲筊</h1>
                                <form method="get" action="/cup">
                                    <input type="hidden" name="action" value="toss">
                                    <button type="submit">開始擲筊</button>
                                </form>
                                <p><a href="/">回到首頁</a></p>
                            </body>
                        </html>
                        """)

        return render_template_string(
            """
                <html lang="zh-TW">
                    <head><meta charset="UTF-8"><title>擲筊結果</title></head>
                    <body>
                        <h1>擲筊結果</h1>
                        <p><img src="{{ result.cup1 }}" alt="cup1" width="120"></p>
                        <p><img src="{{ result.cup2 }}" alt="cup2" width="120"></p>
                        <p>{{ result.message }}</p>
                        <p><a href="/cup">重新擲筊</a> | <a href="/">回到首頁</a></p>
                    </body>
                </html>
                """,
            result=result,
        )


@app.route("/math2", methods=["GET", "POST"])
def math2():
    result = None
    if request.method == "POST":
        # 取得使用者輸入
        x = int(request.form.get("x"))
        opt = request.form.get("opt")
        y = int(request.form.get("y"))

        # 你的核心邏輯
        match opt:
            case "∧":
                result = x**y
            case "√":
                if y != 0:
                    result = x ** (1 / y)
                else:
                    result = "數學上不存在「0 次方根」"
            case _:
                result = "請輸入∧(次方)或√(根號)"
        return render_template_string(
            """
                <html lang="zh-TW">
                    <head><meta charset="UTF-8"><title>math2</title></head>
                    <body>
                        <h1>math2</h1>
                        <form method="post" action="/math2">
                            x：<input type="text" name="x" value="0"><br><br>
                            y：<input type="text" name="y" value="0"><br><br>
                            運算子(∧, √)：<input type="text" name="opt" value="∧"><br><br>
                            <button type="submit">送出</button>
                        </form>
                        {% if result is not none %}
                        <p>結果：{{ result }}</p>
                        {% endif %}
                        <p><a href="/">回到首頁</a></p>
                    </body>
                </html>
                """,
            result=result,
        )


@app.route("/read")
def read():
    keyword = request.values.get("q", "").strip()
    docs = []
    error = None

    try:
        collection_ref = _get_firestore_collection("靜宜資管")
        for doc in collection_ref.get():
            data = doc.to_dict() or {}
            if keyword:
                values = [
                    str(data.get("name", "")),
                    str(data.get("lab", "")),
                    str(data.get("mail", "")),
                ]
                if not any(keyword in value for value in values):
                    continue
            docs.append(data)
    except Exception as e:
        error = f"讀取 Firestore 失敗：{e}"

    return render_template("read.html", docs=docs, keyword=keyword, error=error)


@app.route("/search", methods=["GET", "POST"])
def search():
    return read()


@app.route("/movie")
def movie():
    return next_movies()


@app.route("/next")
def next_movies():
    try:
        movies = fetch_upcoming_movies()
        return render_template("next.html", movies=movies, error=None)
    except Exception as e:
        return render_template("next.html", movies=[], error=f"抓取失敗：{e}")


@app.route("/movie2", methods=["GET"])
def movie2():
    try:
        movies = fetch_upcoming_movies()
        updated_at = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        collection_ref = _get_firestore_collection("電影")

        for movie in movies:
            movie_id = movie.get("url", "").rstrip("/").split("/")[-1]
            if not movie_id:
                movie_id = movie.get("title", "movie")

            doc = {
                "title": movie.get("title", ""),
                "url": movie.get("url", ""),
                "hyperlink": movie.get("url", ""),
                "showDate": movie.get("showDate", ""),
                "showLength": movie.get("showLength", ""),
                "updatedAt": updated_at,
            }
            collection_ref.document(movie_id).set(doc)

        return render_template(
            "movie2.html",
            movies=movies,
            count=len(movies),
            updated_at=updated_at,
            error=None,
        )
    except Exception as e:
        return render_template(
            "movie2.html",
            movies=[],
            count=0,
            updated_at="",
            error=f"存入 Firestore 失敗：{e}",
        )


@app.route("/movie3", methods=["GET", "POST"])
def movie3():
    keyword = request.values.get("q", "").strip()
    movies = []
    error = None

    try:
        collection_ref = _get_firestore_collection("電影")
        for doc in collection_ref.get():
            movie = doc.to_dict() or {}
            if keyword and keyword not in movie.get("title", ""):
                continue
            movies.append(movie)
    except Exception as e:
        error = f"查詢 Firestore 失敗：{e}"

    return render_template("movie3.html", movies=movies, keyword=keyword, error=error)


@app.route("/searchQ", methods=["POST", "GET"])
def searchQ():
    return movie3()


@app.route("/check_update")
def check_update():
    url = "http://www.atmovies.com.tw/movie/next/"
    try:
        # 發送請求
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        Data = requests.get(url, headers=headers)
        Data.encoding = "utf-8"
        sp = BeautifulSoup(Data.text, "html.parser")

        # 尋找包含更新日期的 div (通常是 class="smaller09")
        update_div = sp.find("div", class_="smaller09")

        if update_div:
            update_text = update_div.text.strip()
            # 這裡 update_text 會像是 "最後更新日期：2024/05/20"
        else:
            update_text = "找不到更新日期資訊"

    except Exception as e:
        update_text = f"抓取失敗，錯誤原因：{e}"

    # 建立回傳的網頁內容
    html = f"""
    <html>
        <head><title>網頁更新狀態</title></head>
        <body>
            <h1>開眼電影網 更新狀態</h1>
            <p style="font-size: 20px; color: blue;">{update_text}</p>
            <hr>
            <a href="/">回到首頁</a>
        </body>
    </html>
    """
    return html


@app.route("/road", methods=["GET", "POST"])
def road():
    if request.method == "POST":
        road_name = request.form.get("road_name")
        try:
            result = search_accident_by_road(road_name)
            if isinstance(result, dict) and result.get("error"):
                return render_template("road.html", roads=[], error=result["error"])
            return render_template("road.html", roads=result, error=None)
        except Exception as e:
            return render_template("road.html", roads=[], error=f"查詢失敗：{e}")
    else:
        return render_template("road.html")


@app.route("/weather", methods=["GET", "POST"])
def weather():
    if request.method == "POST":
        city = request.form.get("city")
        try:
            result = get_weather(city)
            return render_template(
                "weather.html",
                result=result,
                city=city,
                error=result.get("error") if isinstance(result, dict) else None,
            )
        except Exception as e:
            return render_template("weather.html", result=None, city=city, error=str(e))
    else:
        return render_template("weather.html")


@app.route("/rate")
def rate():
    try:
        # 本週新片
        url = "https://www.atmovies.com.tw/movie/new/"
        Data = requests.get(url)
        Data.encoding = "utf-8"
        sp = BeautifulSoup(Data.text, "html.parser")
        lastUpdate = sp.find(class_="smaller09").text[5:]
        print(lastUpdate)
        print()

        result = sp.select(".filmList")

        for x in result:
            title = x.find("a").text
            introduce = x.find("p").text

            movie_id = x.find("a").get("href").replace("/", "").replace("movie", "")
            hyperlink = "http://www.atmovies.com.tw/movie/" + movie_id
            picture = (
                "https://www.atmovies.com.tw/photo101/"
                + movie_id
                + "/pm_"
                + movie_id
                + ".jpg"
            )

            r = x.find(class_="runtime").find("img")
            rate = ""
            if r != None:
                rr = r.get("src").replace("/images/cer_", "").replace(".gif", "")
                if rr == "G":
                    rate = "普遍級"
                elif rr == "P":
                    rate = "保護級"
                elif rr == "F2":
                    rate = "輔12級"
                elif rr == "F5":
                    rate = "輔15級"
                else:
                    rate = "限制級"

            t = x.find(class_="runtime").text

            t1 = t.find("片長")
            t2 = t.find("分")
            showLength = t[t1 + 3 : t2]

            t1 = t.find("上映日期")
            t2 = t.find("上映廳數")
            showDate = t[t1 + 5 : t2 - 8]

            doc = {
                "title": title,
                "introduce": introduce,
                "picture": picture,
                "hyperlink": hyperlink,
                "showDate": showDate,
                "showLength": int(showLength),
                "rate": rate,
                "lastUpdate": lastUpdate,
            }

            db = firestore.client()
            doc_ref = db.collection("本週新片含分級").document(movie_id)
            doc_ref.set(doc)
        return "本週新片已爬蟲及存檔完畢，網站最近更新日期為：" + lastUpdate
    except Exception as exc:
        return f"本週新片處理失敗：{exc}"


@app.route("/webhook", methods=["POST"])
def webhook():
    # build a request object
    req = request.get_json(force=True)
    # fetch queryResult from json
    action = req.get("queryResult").get("action")
    msg = req.get("queryResult").get("queryText")
    info = "動作：" + action + "； 查詢內容：" + msg
    return make_response(jsonify({"fulfillmentText": info}))


@app.route("/webhook2", methods=["POST"])
def webhook2():
    # build a request object
    req = request.get_json(force=True)
    # fetch queryResult from json
    action = req.get("queryResult").get("action")
    # msg =  req.get("queryResult").get("queryText")
    # info = "動作：" + action + "； 查詢內容：" + msg
    info = "目前沒有可回覆的內容"
    if action == "rateChoice":
        rate = req.get("queryResult").get("parameters").get("rate")
        info = "您選擇的電影分級是：" + rate
    return make_response(jsonify({"fulfillmentText": info}))


@app.route("/webhook3", methods=["POST"])
def webhook3():
    # build a request object
    req = request.get_json(force=True)
    # fetch queryResult from json
    action = req.get("queryResult").get("action")
    # msg =  req.get("queryResult").get("queryText")
    # info = "動作：" + action + "； 查詢內容：" + msg
    info = "目前沒有可回覆的內容"
    if action == "rateChoice":
        rate = req.get("queryResult").get("parameters").get("rate")
        info = (
            "我是吳岱威開發的電影聊天機器人,您選擇的電影分級是："
            + rate
            + "，相關電影：\n"
        )
        info += _build_rate_movie_reply(rate)
    return make_response(jsonify({"fulfillmentText": info}))


@app.route("/webhook4", methods=["POST"])
def webhook4():
    req = request.get_json(force=True)
    action = req["queryResult"]["action"]
    info = "目前沒有可回覆的內容"
    if action == "rateChoice":
        rate = req.get("queryResult").get("parameters").get("rate")
        info = (
            "我是吳岱威開發的電影聊天機器人,您選擇的電影分級是："
            + rate
            + "，相關電影：\n"
        )
        info += _build_rate_movie_reply(rate, include_introduce=True)
    elif action == "MovieDetail":
        question = req.get("queryResult").get("parameters").get("filmq")
        keyword = req.get("queryResult").get("parameters").get("any")
        info = (
            "我是吳岱威開發的電影聊天機器人，您要查詢電影的"
            + question
            + "，關鍵字是："
            + keyword
            + "\n\n"
        )

        if question == "片名":
            collection_ref = _get_firestore_collection(MOVIE_RATING_COLLECTION)
            docs = collection_ref.get()
            found = False
            info = ""
            for doc in docs:
                movie_data = doc.to_dict()
                if keyword in movie_data["title"]:
                    found = True
                    info += "片名：" + movie_data["title"] + "\n"
                    info += "影片介紹：" + movie_data["introduce"] + "\n"
                    info += "片長：" + str(movie_data["showLength"]) + " 分鐘\n"
                    info += "分級：" + movie_data["rate"] + "\n"
                    info += "上映日期：" + movie_data["showDate"] + "\n\n"
            if not found:
                info += "很抱歉，目前無符合這個關鍵字的相關電影喔"

    return make_response(jsonify({"fulfillmentText": info}))


@app.route("/AI")
def AI():
    question = request.values.get("q", "").strip()
    if not question:
        question = "我想查詢靜宜大學資管系的評價？"

    if _gemini_client is None:
        return _render_ai_page(question, error=_gemini_client_error)

    try:
        response = _gemini_client.models.generate_content(
            model=_get_gemini_model(),
            contents=question,
        )
        answer = response.text or "模型沒有回傳文字內容。"
    except Exception as exc:
        answer = f"AI 查詢失敗：{exc}"

    return _render_ai_page(question, answer=answer)


@app.route("/webhook7", methods=["POST"])
def webhook7():
    req = request.get_json(force=True) or {}
    query_result = req.get("queryResult") or {}
    action = query_result.get("action", "")
    query_text = query_result.get("queryText", "").strip()
    info = "目前沒有可回覆的內容"

    if action == "rateChoice":
        rate = query_result.get("parameters", {}).get("rate", "")
        info = (
            "我是吳岱威開發的電影聊天機器人,您選擇的電影分級是："
            + rate
            + "，相關電影：\n"
        )
        info += _build_rate_movie_reply(rate, include_introduce=True)

    elif action == "input.unknown":
        try:
            info = ask_gemini(
                query_text or "請用繁體中文簡短回答使用者問題。",
                token=int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "500")),
                model=_get_gemini_model(),
            )
            if not info.strip():
                info = "Gemini 沒有回傳文字內容。"
        except Exception as exc:
            info = f"AI 查詢失敗：{exc}"

    return make_response(jsonify({"fulfillmentText": info}))


if __name__ == "__main__":
    app.run()
