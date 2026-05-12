from flask import Flask, jsonify, make_response, render_template, request
from datetime import datetime
import os
import json
import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore

from bug.spider import fetch_upcoming_movies
from bug.weather import get_weather
from bug.opendata import get_taichung_accident_roads

MOVIE_COLLECTION = "即將上映電影"


def fetch_movies_with_rating():
    """
    爬取開眼電影(atmovies.com.tw)的今年上映電影及分級資訊
    回傳爬蟲的電影數量和最後更新時間
    """
    url = "https://www.atmovies.com.tw/movie/"

    try:
        Data = requests.get(url, timeout=10)
        Data.encoding = "utf-8"
        sp = BeautifulSoup(Data.text, "html.parser")
    except Exception as e:
        print(f"網路請求失敗：{e}")
        return 0, datetime.now().strftime("%Y/%m/%d %H:%M:%S")

    lastUpdate = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    print(f"電影含分級爬蟲更新時間：{lastUpdate}")

    # 新網站結構使用 c-item-card
    result = sp.select(".c-item-card")
    print(f"找到 {len(result)} 部電影")

    if len(result) == 0:
        return 0, lastUpdate

    count = 0
    for x in result:
        try:
            # 取得連結和電影ID
            link_elem = x.find("a")
            if not link_elem:
                continue

            href = link_elem.get("href", "")
            if not href:
                continue

            # 從 URL 提取電影ID：http://www.atmovies.com.tw/movie/fcko34385135/
            movie_id = href.strip("/").split("/")[-1]
            if not movie_id:
                continue

            # 取得標題和日期
            title_elem = x.find("div", class_="my-filmtitle")
            if not title_elem:
                continue

            # 標題在 div 的第一個文本子節點
            title_text = title_elem.get_text(strip=True)
            # 從標題中分離日期（格式如 "屍速禁區2026/5/22"）

            date_elem = title_elem.find("p", class_="my-date")
            if date_elem:
                showDate = date_elem.get_text(strip=True)
                # 移除日期部分，只保留標題
                title = title_text.replace(showDate, "").strip()
            else:
                showDate = ""
                title = title_text

            if not title:
                continue

            # 取得圖片（背景圖）
            bg = link_elem.get("data-bg", "")
            if bg.startswith("/"):
                picture = "https://www.atmovies.com.tw" + bg
            elif bg.startswith("http"):
                picture = bg
            else:
                picture = ""

            # 新結構中沒有分級和片長信息在列表頁面
            # 如果需要取得這些信息，需要訪問詳細頁面
            # 暫時使用空值或預設值
            rate = "待更新"
            showLength = 0
            introduce = ""

            hyperlink = (
                href if href.startswith("http") else "http://www.atmovies.com.tw" + href
            )

            try:
                doc = {
                    "title": title,
                    "introduce": introduce,
                    "picture": picture,
                    "hyperlink": hyperlink,
                    "showDate": showDate,
                    "showLength": showLength,
                    "rate": rate,
                    "lastUpdate": lastUpdate,
                }

                db_client = firestore.client()
                doc_ref = db_client.collection("電影含分級").document(movie_id)
                doc_ref.set(doc)
                count += 1
                print(f"[成功] {title} ({showDate})")
            except Exception as e:
                print(f"[Firestore 錯誤] {title}：{e}")
                continue
        except Exception as e:
            print(f"[處理電影錯誤]：{e}")
            continue

    print(f"[爬蟲完成] 共爬蟲 {count} 部電影")
    return count, lastUpdate


def build_movie_doc_id(movie_url: str) -> str:
    parts = movie_url.rstrip("/").split("/")
    return parts[-1] if parts else movie_url


def get_firestore_client():
    """建立 Firestore client；若未設定憑證則回傳 None。"""
    cred = None

    if os.path.exists("serviceAccountKey.json"):
        cred = credentials.Certificate("serviceAccountKey.json")
    else:
        firebase_config = os.getenv("FIREBASE_CONFIG")
        if not firebase_config:
            return None

        try:
            cred_dict = json.loads(firebase_config)
        except json.JSONDecodeError:
            return None

        cred = credentials.Certificate(cred_dict)

    try:
        firebase_admin.initialize_app(cred)
    except ValueError:
        pass

    return firestore.client()


app = Flask(__name__)
db = get_firestore_client()


@app.route("/webhook3", methods=["POST"])
def webhook3():
    req = request.get_json(force=True)
    query_result = req.get("queryResult", {})
    action = query_result.get("action", "")
    info = ""

    if action == "rateChoice":
        parameters = query_result.get("parameters", {})
        rate = parameters.get("rate", "")
        info = (
            "我是吳岱威開發的電影聊天機器人,您選擇的電影分級是："
            + rate
            + "，相關電影：\n"
        )

        if db is not None:
            collection_ref = db.collection("電影含分級")
            docs = collection_ref.get()
            matched_movies = []
            fallback_movies = []
            for doc in docs:
                movie_data = doc.to_dict()
                title = movie_data.get("title", "")
                show_date = movie_data.get("showDate", "")
                movie_rate = movie_data.get("rate", "")

                if title:
                    fallback_movies.append((title, show_date, movie_rate))

                if rate and movie_rate and rate in movie_rate:
                    matched_movies.append((title, show_date, movie_rate))

            target_movies = matched_movies if matched_movies else fallback_movies

            if matched_movies:
                info += "以下為符合分級的電影：\n"
            else:
                info += "目前分級欄位尚未完整，先列出已抓到的電影名稱：\n"

            for title, show_date, movie_rate in target_movies:
                info += "片名：" + title
                if show_date:
                    info += "；上映日期：" + show_date
                if movie_rate:
                    info += "；分級：" + movie_rate
                info += "\n"
        else:
            info += "尚未設定 Firestore 連線。"

    return make_response(jsonify({"fulfillmentText": info}))


@app.route("/")
def index():
    homepage = "<h1>吳岱威Python網頁</h1>"
    homepage += "<a href=/mis>MIS</a><br>"
    homepage += "<a href=/today>顯示日期時間</a><br>"
    homepage += (
        "<a href=/welcome?nick=David&school=靜宜大學資管系>傳送使用者暱稱</a><br>"
    )
    homepage += "<a href=/account>網頁表單傳值</a><br>"
    homepage += "<a href=/about>岱威簡介網頁</a><br>"
    homepage += "<a href=/math>簡易計算機</a><br>"
    homepage += "<br><a href=/read>查詢老師資料</a><br>"
    homepage += "<a href=/next>查詢即將上映電影</a><br>"
    homepage += "<br><a href=/movie2>movie2：存入即將上映電影資料庫</a><br>"
    homepage += "<a href=/movie3>movie3：查詢電影資料</a><br>"
    homepage += "<br><a href=/rate>rate：爬蟲電影含分級資訊</a><br>"
    homepage += "<br><a href=/weather>天氣查詢</a><br>"
    homepage += "<a href=/road>台中市十大肇事路口</a><br>"
    return homepage


@app.route("/mis")
def course():
    return "<h1>資訊管理導論</h1>"


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/today")
def today():
    now = datetime.now()
    return render_template("today.html", datetime=str(now))


@app.route("/welcome", methods=["GET"])
def welcome():
    user = request.values.get("nick", "")
    school = request.values.get("school", "")
    return render_template("welcome.html", name=user, school=school)


@app.route("/account", methods=["GET", "POST"])
def account():
    if request.method == "POST":
        user = request.form.get("user", "")
        pwd = request.form.get("pwd", "")
        result = "您輸入的帳號是：" + user + "; 密碼為：" + pwd
        return result
    else:
        return render_template("account.html")


@app.route("/math", methods=["GET", "POST"])
def math():
    if request.method == "POST":
        try:
            x = float(request.form.get("x", 0))
            y = float(request.form.get("y", 0))
        except ValueError:
            return "請輸入有效數字"

        op = request.form.get("op", "")
        try:
            if op == "+":
                result = x + y
            elif op == "-":
                result = x - y
            elif op == "*":
                result = x * y
            elif op == "/":
                result = x / y
            else:
                result = "不支援的運算子"
        except ZeroDivisionError:
            result = "除數不可為 0"

        return f"{x} {op} {y} = {result}"
    else:
        return render_template("math.html")


@app.route("/read")
def read():
    if db is None:
        return render_template(
            "read.html",
            docs=[],
            keyword="",
            error="尚未設定 Firestore 連線，無法讀取資料。",
        )

    keyword = request.values.get("q", "").strip()

    try:
        collection_ref = db.collection("靜宜資管")
        all_docs = [doc.to_dict() for doc in collection_ref.get()]

        if keyword:
            docs = [
                {
                    "name": doc.get("name", ""),
                    "lab": doc.get("lab", ""),
                    "mail": doc.get("mail", ""),
                }
                for doc in all_docs
                if keyword.lower() in str(doc.get("name", "")).lower()
            ]
        else:
            docs = [
                {
                    "name": doc.get("name", ""),
                    "lab": doc.get("lab", ""),
                    "mail": doc.get("mail", ""),
                }
                for doc in all_docs
            ]

        return render_template("read.html", docs=docs, keyword=keyword, error=None)
    except Exception as exc:
        return render_template(
            "read.html",
            docs=[],
            keyword=keyword,
            error=f"讀取 Firestore 時發生錯誤：{exc}",
        )


@app.route("/next")
def next_movies():
    try:
        movies = fetch_upcoming_movies()
        return render_template("next.html", movies=movies, error=None)
    except Exception as exc:
        return render_template(
            "next.html", movies=[], error=f"抓取即將上映電影失敗：{exc}"
        )


@app.route("/movie2")
def movie2():
    if db is None:
        return render_template(
            "movie2.html",
            movies=[],
            updated_at=None,
            count=0,
            error="尚未設定 Firestore 連線，無法存入即將上映電影資料。",
        )

    try:
        movies = fetch_upcoming_movies()
        updated_at = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        collection_ref = db.collection(MOVIE_COLLECTION)
        existing_docs = {doc.id for doc in collection_ref.stream()}
        current_ids = set()

        batch = db.batch()
        for movie in movies:
            doc_id = build_movie_doc_id(movie["url"])
            current_ids.add(doc_id)
            doc_ref = collection_ref.document(doc_id)
            batch.set(
                doc_ref,
                {
                    "title": movie.get("title", ""),
                    "url": movie.get("url", ""),
                    "showDate": movie.get("showDate", ""),
                    "showLength": movie.get("showLength", ""),
                    "updatedAt": updated_at,
                },
            )

        for stale_id in existing_docs - current_ids:
            batch.delete(collection_ref.document(stale_id))

        batch.commit()

        return render_template(
            "movie2.html",
            movies=movies,
            updated_at=updated_at,
            count=len(movies),
            error=None,
        )
    except Exception as exc:
        return render_template(
            "movie2.html",
            movies=[],
            updated_at=None,
            count=0,
            error=f"存入即將上映電影資料失敗：{exc}",
        )


@app.route("/movie3")
def movie3():
    keyword = request.values.get("q", "").strip()

    if db is None:
        return render_template(
            "movie3.html",
            movies=[],
            keyword=keyword,
            error="尚未設定 Firestore 連線，無法查詢電影資料。",
        )

    try:
        collection_ref = db.collection(MOVIE_COLLECTION)
        docs = [doc.to_dict() | {"id": doc.id} for doc in collection_ref.stream()]

        if keyword:
            movies = [
                movie
                for movie in docs
                if keyword.lower() in str(movie.get("title", "")).lower()
                or keyword.lower() in str(movie.get("showDate", "")).lower()
            ]
        else:
            movies = docs

        return render_template(
            "movie3.html",
            movies=movies,
            keyword=keyword,
            error=None,
        )
    except Exception as exc:
        return render_template(
            "movie3.html",
            movies=[],
            keyword=keyword,
            error=f"查詢電影資料失敗：{exc}",
        )


@app.route("/weather", methods=["GET", "POST"])
def weather():
    result = None
    city = ""
    error = None

    if request.method == "POST":
        city = request.form.get("city", "").strip()
        if not city:
            error = "請輸入縣市名稱"
        else:
            result = get_weather(city)
            if "error" in result and result["error"]:
                error = result["error"]

    return render_template("weather.html", result=result, city=city, error=error)


@app.route("/road")
def road():
    roads = get_taichung_accident_roads(10)
    error = None

    if isinstance(roads, dict) and "error" in roads:
        error = roads["error"]
        roads = []

    return render_template("road.html", roads=roads, error=error)


@app.route("/rate")
def rate():
    if db is None:
        return "尚未設定 Firestore 連線，無法存入電影資料。"
    try:
        count, lastUpdate = fetch_movies_with_rating()
        return f"已爬蟲 {count} 部電影及存檔完畢，網站最近更新日期為：{lastUpdate}"
    except Exception as e:
        return f"爬蟲電影資料失敗：{e}"


def initialize_movies_data():
    """系統啟動時，爬蟲一次電影資料"""
    if db is None:
        print("未設定 Firestore 連線，跳過電影資料初始化")
        return
    try:
        print("系統啟動，正在爬蟲電影含分級資訊...")
        count, lastUpdate = fetch_movies_with_rating()
        print(f"初始化完成：共爬蟲 {count} 部電影，更新時間 {lastUpdate}")
    except Exception as e:
        print(f"初始化電影資料失敗：{e}")


if __name__ == "__main__":
    initialize_movies_data()
    app.run()
