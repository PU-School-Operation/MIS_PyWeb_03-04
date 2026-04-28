from flask import Flask, render_template, request
from datetime import datetime
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

from bug.spider import fetch_upcoming_movies


MOVIE_COLLECTION = "即將上映電影"


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


if __name__ == "__main__":
    app.run()
