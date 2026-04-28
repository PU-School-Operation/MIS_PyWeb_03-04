from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.atmovies.com.tw"
NEXT_URL = "https://www.atmovies.com.tw/movie/next/"


def fetch_upcoming_movies():
    response = requests.get(
        NEXT_URL,
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.encoding = response.apparent_encoding or "utf-8"

    soup = BeautifulSoup(response.text, "html.parser")
    movies = []

    for item in soup.select(".filmListAllX li"):
        title_link = item.select_one(".filmtitle a")
        if not title_link:
            continue

        title = title_link.get_text(strip=True)
        hyperlink = urljoin(BASE_URL, title_link.get("href", ""))

        # 解析上映日期與片長（若頁面有提供）
        showDate = ""
        showLength = ""
        runtime_div = item.find("div", class_="runtime")
        if runtime_div:
            # 優先取 runtime 裡的 a 標籤（通常是上映日期）
            a = runtime_div.find("a")
            if a and a.get_text(strip=True):
                showDate = a.get_text(strip=True)
            else:
                text = runtime_div.get_text(" ", strip=True)
                try:
                    import re

                    m = re.search(r"\d{4}/\d{2}/\d{2}", text)
                    if m:
                        showDate = m.group(0)
                    m2 = re.search(r"片長[:：]?\s*(\d+)\s*分", text)
                    if m2:
                        showLength = m2.group(1)
                except Exception:
                    pass

        if title and hyperlink:
            movies.append(
                {
                    "title": title,
                    "url": hyperlink,
                    "showDate": showDate,
                    "showLength": showLength,
                }
            )

    return movies


if __name__ == "__main__":
    for movie in fetch_upcoming_movies():
        print(movie["title"])
        print(movie["url"])
        print()
