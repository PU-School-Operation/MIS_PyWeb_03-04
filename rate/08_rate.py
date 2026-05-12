import requests
from bs4 import BeautifulSoup
from firebase_admin import firestore
from datetime import datetime


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

            # 從 URL 提取電影ID
            movie_id = href.strip("/").split("/")[-1]
            if not movie_id:
                continue

            # 取得標題和日期
            title_elem = x.find("div", class_="my-filmtitle")
            if not title_elem:
                continue

            title_text = title_elem.get_text(strip=True)

            date_elem = title_elem.find("p", class_="my-date")
            if date_elem:
                showDate = date_elem.get_text(strip=True)
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
            rate = "待更新"
            showLength = 0
            introduce = ""

            hyperlink = (
                href if href.startswith("http") else "http://www.atmovies.com.tw" + href
            )

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

            db = firestore.client()
            doc_ref = db.collection("電影含分級").document(movie_id)
            doc_ref.set(doc)
            count += 1
            print(f"[成功] {title} ({showDate})")
        except Exception as e:
            print(f"[處理電影錯誤]：{e}")
            continue

    print(f"[爬蟲完成] 共爬蟲 {count} 部電影")
    return count, lastUpdate
